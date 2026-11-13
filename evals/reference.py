"""Reference SQL for the numeric eval cases: plain, independent of the agent's queries.

Run `python -m evals.reference` to print the correct answer for each case.
"""

import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text

# Orders that count as shipped revenue: the standard exclusions plus a shipped status.
SHIPPED = """h.ord_sts_cd IN (30, 40, 95) AND h.parent_ord_id IS NULL AND h.b2b_flg = 'N'
    AND h.cust_id NOT IN (SELECT cust_id FROM dim_cust WHERE tst_acct_flg = 'Y')"""
# Orders that count as placed (not cancelled), same exclusions.
PLACED = """h.ord_sts_cd <> 90 AND h.parent_ord_id IS NULL AND h.b2b_flg = 'N'
    AND h.cust_id NOT IN (SELECT cust_id FROM dim_cust WHERE tst_acct_flg = 'Y')"""
NET = "(h.gross_amt_lcl - h.disc_amt_lcl)"
MARKETPLACE_SHARE = "CASE WHEN h.ord_chnl_cd = 'MKT' THEN 0.12 ELSE 1 END"


def local_day(column: str) -> str:
    """Reporting date: timestamps are UTC, the business day is US Eastern."""
    return f"date({column}, '-5 hours')"


def recognized_revenue(start: str, end: str, extra: str = "1=1") -> str:
    return f"""
SELECT ROUND(SUM({NET} * fx.rate_to_usd * {MARKETPLACE_SHARE}), 2)
FROM fct_ord_hdr h, ref_fx_rate fx
WHERE fx.curr_cd = h.curr_cd AND fx.fx_mth = strftime('%Y-%m', h.shp_ts)
  AND {SHIPPED} AND {extra}
  AND {local_day("h.shp_ts")} >= '{start}' AND {local_day("h.shp_ts")} < '{end}'"""


def refunds(start: str, end: str) -> str:
    return f"""
SELECT ROUND(SUM(r.rfnd_amt_lcl * fx.rate_to_usd * {MARKETPLACE_SHARE}), 2)
FROM fct_rfnd r
JOIN fct_ord_hdr h ON h.ord_id = r.ord_id
JOIN ref_fx_rate fx ON fx.curr_cd = h.curr_cd AND fx.fx_mth = strftime('%Y-%m', r.rfnd_ts)
WHERE r.rfnd_typ_cd <> 'GDW' AND {SHIPPED}
  AND {local_day("r.rfnd_ts")} >= '{start}' AND {local_day("r.rfnd_ts")} < '{end}'"""


REFERENCE = {
    "How many customer accounts are there, excluding internal test accounts?": """
SELECT COUNT(*) FROM dim_cust WHERE tst_acct_flg = 'N'""",
    "How many unique customers had at least one non-cancelled order placed in 2026?": f"""
SELECT COUNT(DISTINCT COALESCE(c.mrg_to_cust_id, c.cust_id))
FROM fct_ord_hdr h JOIN dim_cust c ON c.cust_id = h.cust_id
WHERE {PLACED} AND {local_day("h.ord_ts")} >= '2026-01-01' AND {local_day("h.ord_ts")} < '2027-01-01'""",
    "How many Gold tier customers placed a non-cancelled order in 2026?": f"""
SELECT COUNT(DISTINCT COALESCE(c.mrg_to_cust_id, c.cust_id))
FROM fct_ord_hdr h JOIN dim_cust c ON c.cust_id = h.cust_id
WHERE c.cust_tier_cd = 'G' AND {PLACED}
  AND {local_day("h.ord_ts")} >= '2026-01-01' AND {local_day("h.ord_ts")} < '2027-01-01'""",
    "What was GMV in USD for orders placed in March 2026?": f"""
SELECT ROUND(SUM({NET} * fx.rate_to_usd), 2)
FROM fct_ord_hdr h, ref_fx_rate fx
WHERE fx.curr_cd = h.curr_cd AND fx.fx_mth = strftime('%Y-%m', h.ord_ts) AND {PLACED}
  AND {local_day("h.ord_ts")} >= '2026-03-01' AND {local_day("h.ord_ts")} < '2026-04-01'""",
    "What was the average order value in USD for orders placed in April to June 2026?": f"""
SELECT ROUND(SUM({NET} * fx.rate_to_usd) / COUNT(*), 2)
FROM fct_ord_hdr h, ref_fx_rate fx
WHERE fx.curr_cd = h.curr_cd AND fx.fx_mth = strftime('%Y-%m', h.ord_ts) AND {PLACED}
  AND {local_day("h.ord_ts")} >= '2026-04-01' AND {local_day("h.ord_ts")} < '2026-07-01'""",
    "What was recognized revenue in USD in April 2026?": recognized_revenue(
        "2026-04-01", "2026-05-01"
    ),
    "What was recognized revenue in USD from the marketplace channel in April to June 2026?": recognized_revenue(
        "2026-04-01", "2026-07-01", "h.ord_chnl_cd = 'MKT'"
    ),
    "What was net revenue in USD for fiscal quarter FY2027 Q1?": f"""
SELECT ROUND(({recognized_revenue("2026-02-01", "2026-05-01")}) - ({refunds("2026-02-01", "2026-05-01")}), 2)""",
    "What were total refunds in USD in June 2026?": refunds("2026-06-01", "2026-07-01"),
    "How many units shipped in May 2026?": f"""
SELECT SUM(l.qty)
FROM fct_ord_ln l JOIN fct_ord_hdr h ON h.ord_id = l.ord_id
WHERE l.ln_typ_cd IN ('STD', 'CMP') AND l.ln_sts_cd = 'SHP' AND {SHIPPED}
  AND {local_day("h.shp_ts")} >= '2026-05-01' AND {local_day("h.shp_ts")} < '2026-06-01'""",
    "Which product group shipped the most units in 2026?": f"""
SELECT g.grp_nm
FROM fct_ord_ln l
JOIN fct_ord_hdr h ON h.ord_id = l.ord_id
JOIN dim_sku s ON s.sku_id = l.sku_id
JOIN ref_prod_grp g ON g.grp_cd = s.grp_cd
WHERE l.ln_typ_cd IN ('STD', 'CMP') AND l.ln_sts_cd = 'SHP' AND {SHIPPED}
  AND {local_day("h.shp_ts")} >= '2026-01-01' AND {local_day("h.shp_ts")} < '2027-01-01'
GROUP BY g.grp_nm ORDER BY SUM(l.qty) DESC LIMIT 1""",
    "How many orders were placed in January 2026?": f"""
SELECT COUNT(*) FROM fct_ord_hdr h
WHERE {PLACED} AND {local_day("h.ord_ts")} >= '2026-01-01' AND {local_day("h.ord_ts")} < '2026-02-01'""",
    "How many orders were placed on 3 March 2026?": f"""
SELECT COUNT(*) FROM fct_ord_hdr h
WHERE {PLACED} AND {local_day("h.ord_ts")} = '2026-03-03'""",
    "How many orders placed in 2026 were cancelled because of fraud?": """
SELECT COUNT(*) FROM fct_ord_hdr h
WHERE h.ord_sts_cd = 90 AND h.cncl_rsn_cd = 'FRAUD' AND h.parent_ord_id IS NULL AND h.b2b_flg = 'N'
  AND h.cust_id NOT IN (SELECT cust_id FROM dim_cust WHERE tst_acct_flg = 'Y')
  AND date(h.ord_ts, '-5 hours') >= '2026-01-01' AND date(h.ord_ts, '-5 hours') < '2027-01-01'""",
}


def compute(database_url: str) -> dict[str, str]:
    """Run every reference query and return the answers as text (money to 2 decimals)."""
    answers = {}
    with create_engine(database_url).connect() as conn:
        for query, sql in REFERENCE.items():
            value = conn.execute(text(sql)).scalar()
            answers[query] = f"{value:.2f}" if isinstance(value, float) else str(value)
    return answers


def main() -> None:
    from demo import seed_db  # imported here: it reads settings, which need the repo root as cwd

    with tempfile.TemporaryDirectory() as folder:
        url = f"sqlite:///{Path(folder) / 'reference.db'}"
        seed_db.seed(url)
        for query, answer in compute(url).items():
            print(f"{answer:>14}  {query}")


if __name__ == "__main__":
    main()
