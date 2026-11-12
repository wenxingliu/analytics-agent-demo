"""Query guardrails. They read only the YAML flags, never table or column names."""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from analytics_agent.config import ConfigError, Guardrails
from analytics_agent.metadata import Metadata, Table


class GuardrailError(ValueError):
    pass


def validate_config(metadata: Metadata, rails: Guardrails) -> None:
    """Fail at startup if a guardrail is on but the YAML has nothing for it to act on."""
    columns = [(t, c) for t in metadata.tables for c in t.columns]
    if rails.min_date and not any(c.event_time for _, c in columns):
        raise ConfigError("GUARDRAIL_MIN_DATE is set but no catalog column has event_time: true.")
    if rails.no_individual_data and not any(
        c.individual_id or c.pii or t.individual_level for t, c in columns
    ):
        raise ConfigError(
            "GUARDRAIL_NO_INDIVIDUAL_DATA is on but the catalog has no individual_id, pii or "
            "individual_level flags. Add them or turn the guardrail off."
        )


def enforce(sql: str, metadata: Metadata, dialect: str, rails: Guardrails) -> str:
    """Raise GuardrailError if the query breaks an active guardrail; else return it, date-filtered."""
    tree = sqlglot.parse_one(sql, dialect=dialect)
    tables = {t.table.lower(): t for t in metadata.tables}
    ctes = {cte.alias.lower(): cte.this for cte in tree.find_all(exp.CTE)}
    if rails.no_pii:
        _block_pii(tree, tables, ctes)
    if rails.no_individual_data:
        _block_individual_data(tree, tables, ctes)
    if rails.min_date:
        tree = _apply_date_floor(tree, tables, ctes, rails.min_date)
    return tree.sql(dialect=dialect)


def _catalog_table(node: exp.Table, tables: dict[str, Table], ctes: dict) -> Table | None:
    """The catalog table a node refers to; None for CTE names and unknown tables."""
    if node.db or node.name.lower() in ctes:
        return None
    return tables.get(node.name.lower())


# --- PII -------------------------------------------------------------------------------------


def _block_pii(tree: exp.Expression, tables: dict[str, Table], ctes: dict) -> None:
    used = {
        t.alias_or_name.lower(): table
        for t in tree.find_all(exp.Table)
        if (table := _catalog_table(t, tables, ctes))
    }
    pii_by_alias = {a: {c.name.lower() for c in t.columns if c.pii} for a, t in used.items()}
    any_pii = set().union(*pii_by_alias.values())
    for star in tree.find_all(exp.Star):
        if any_pii and not isinstance(star.parent, exp.Count):
            raise GuardrailError(
                "SELECT * would include personal data (PII). List the columns you need."
            )
    for col in tree.find_all(exp.Column):
        name = col.name.lower()
        pii = pii_by_alias.get(col.table.lower(), set()) if col.table else any_pii
        if name in pii:
            raise GuardrailError(f"Column '{col.name}' is personal data (PII) and cannot be used.")


# --- Individual-level data -------------------------------------------------------------------


@dataclass
class _Info:
    tainted: set[str]  # output columns that identify a person
    rowlevel: bool  # output has one row per person


def _block_individual_data(tree: exp.Expression, tables: dict[str, Table], ctes: dict) -> None:
    ids = {c.name.lower() for t in tables.values() for c in t.columns if c.individual_id or c.pii}
    for node in tree.find_all(exp.EQ, exp.In):
        looks_up = isinstance(node.this, exp.Column) and node.this.name.lower() in ids
        values = node.args.get("expressions") or [node.args.get("expression")]
        if looks_up and any(isinstance(v, exp.Literal) for v in values):
            raise GuardrailError(
                "Looking up a single person is not allowed. Use aggregated results."
            )
    info = _analyze(tree, tables, ctes, ids, ())
    if info.tainted or info.rowlevel:
        raise GuardrailError(
            "The result would contain individual-level data (rows or ids per person). "
            "Return aggregates instead, e.g. COUNT(DISTINCT id) or SUM/AVG grouped by a non-identifying attribute."
        )


def _analyze(query, tables, ctes, ids, seen) -> _Info:
    """Work out whether a query's output identifies people, following CTEs and subqueries."""
    if isinstance(query, exp.Subquery):
        return _analyze(query.this, tables, ctes, ids, seen)
    if isinstance(query, exp.SetOperation):
        left = _analyze(query.left, tables, ctes, ids, seen)
        right = _analyze(query.right, tables, ctes, ids, seen)
        return _Info(left.tainted | right.tainted, left.rowlevel or right.rowlevel)

    base, inner = [], []
    for node in query.find_all(exp.Table, exp.Subquery):
        if node.parent_select is not query:
            continue
        if isinstance(node, exp.Subquery):
            if isinstance(node.parent, (exp.From, exp.Join)):
                inner.append(_analyze(node.this, tables, ctes, ids, seen))
        elif node.name.lower() in ctes and not node.db:
            name = node.name.lower()
            if name not in seen:  # a recursive CTE refers to itself
                inner.append(_analyze(ctes[name], tables, ctes, ids, (*seen, name)))
        elif table := _catalog_table(node, tables, ctes):
            base.append(table)

    visible = ids.union(*(i.tainted for i in inner))
    tainted: set[str] = set()
    for projection in query.expressions:
        if any(not isinstance(s.parent, exp.Count) for s in projection.find_all(exp.Star)):
            tainted |= {c.name.lower() for t in base for c in t.columns if c.name.lower() in ids}
            tainted |= visible - ids
        elif any(c.name.lower() in visible for c in _bare_columns(projection)):
            tainted.add(projection.alias_or_name.lower())

    grouped_by_person = any(
        c.name.lower() in visible for g in _group_expressions(query) for c in _bare_columns(g)
    )
    reads_people = any(t.individual_level for t in base) or any(i.rowlevel for i in inner)
    return _Info(tainted, grouped_by_person or (reads_people and not _is_aggregate(query)))


def _group_expressions(query: exp.Select) -> list[exp.Expression]:
    """GROUP BY expressions, with positional references (GROUP BY 1) resolved."""
    group = query.args.get("group")
    resolved = []
    for g in group.expressions if group else []:
        if isinstance(g, exp.Literal) and g.is_int and 0 < int(g.name) <= len(query.expressions):
            g = query.expressions[int(g.name) - 1]
        resolved.append(g)
    return resolved


def _is_aggregate(query: exp.Select) -> bool:
    if query.args.get("group"):
        return True
    return bool(query.expressions) and all(_has_aggregate(p) for p in query.expressions)


def _has_aggregate(expression: exp.Expression) -> bool:
    return any(not a.find_ancestor(exp.Window) for a in expression.find_all(exp.AggFunc))


def _bare_columns(expression: exp.Expression):
    """Columns whose values reach the output as they are. Only COUNT hides them."""
    for col in expression.find_all(exp.Column):
        agg = col.find_ancestor(exp.AggFunc)
        if agg is None or not isinstance(agg, exp.Count) or agg.find_ancestor(exp.Window):
            yield col


# --- Date floor ------------------------------------------------------------------------------


def _apply_date_floor(tree, tables: dict[str, Table], ctes: dict, floor: str):
    """Replace each dated table with a copy that only has rows on or after the floor date."""

    def restrict(node: exp.Expression) -> exp.Expression:
        if not isinstance(node, exp.Table) or not (table := _catalog_table(node, tables, ctes)):
            return node
        condition = _floor_condition(table, tables, floor)
        if condition is None:
            return node
        inner = exp.select("*").from_(exp.to_identifier(table.table)).where(condition)
        alias = exp.TableAlias(this=exp.to_identifier(node.alias_or_name))
        return exp.Subquery(this=inner, alias=alias)

    return tree.transform(restrict)


def _floor_condition(table: Table, tables: dict[str, Table], floor: str) -> exp.Expression | None:
    """Condition keeping rows dated on or after floor, or None if the table has no date."""
    for col in table.columns:
        if col.event_time:
            return exp.GTE(this=exp.column(col.name), expression=exp.Literal.string(floor))
    for col in table.columns:
        if col.event_time_via_fk and col.foreign_key:
            parent_name, parent_col = col.foreign_key.split(".")
            parent = tables[parent_name.lower()]
            parent_condition = _floor_condition(parent, tables, floor)
            if parent_condition is None:
                raise ConfigError(
                    f"{table.table}.{col.name}: {parent_name} has no event_time column."
                )
            allowed = exp.select(parent_col).from_(parent.table).where(parent_condition)
            return exp.In(this=exp.column(col.name), query=allowed.subquery())
    return None
