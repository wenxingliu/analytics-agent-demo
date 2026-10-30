-- Builds the demo database (SQLite). Deterministic, so results are repeatable.
-- Mimics a legacy warehouse: terse column names, coded values, UTC text timestamps.
DROP TABLE IF EXISTS fct_rfnd;
DROP TABLE IF EXISTS fct_ord_ln;
DROP TABLE IF EXISTS fct_ord_hdr;
DROP TABLE IF EXISTS dim_sku;
DROP TABLE IF EXISTS ref_prod_grp;
DROP TABLE IF EXISTS ref_fx_rate;
DROP TABLE IF EXISTS dim_cust;

CREATE TABLE dim_cust (
    cust_id        INTEGER PRIMARY KEY,
    cust_nm        TEXT NOT NULL,
    eml_addr       TEXT NOT NULL,
    ph_no          TEXT,
    ctry_cd        TEXT NOT NULL,
    st_prov_cd     TEXT,
    reg_ts         TEXT NOT NULL,
    reg_chnl_cd    TEXT NOT NULL,
    cust_tier_cd   TEXT NOT NULL,
    mktg_optin_flg TEXT NOT NULL,
    acct_sts_cd    TEXT NOT NULL,
    tst_acct_flg   TEXT NOT NULL,
    mrg_to_cust_id INTEGER,
    ref_cust_id    INTEGER,
    lst_login_ts   TEXT
);

CREATE TABLE ref_prod_grp (
    grp_cd  TEXT PRIMARY KEY,
    grp_nm  TEXT NOT NULL,
    dept_cd TEXT NOT NULL
);

CREATE TABLE dim_sku (
    sku_id        INTEGER PRIMARY KEY,
    sku_nm        TEXT,
    grp_cd        TEXT NOT NULL REFERENCES ref_prod_grp(grp_cd),
    brand_cd      TEXT NOT NULL,
    list_prc_usd  DECIMAL(10,2) NOT NULL,
    cost_usd      DECIMAL(10,2),
    launch_dt     TEXT,
    discont_dt    TEXT,
    actv_flg      TEXT NOT NULL,
    wt_g          INTEGER,
    vndr_id       INTEGER
);

CREATE TABLE ref_fx_rate (
    curr_cd     TEXT NOT NULL,
    fx_mth      TEXT NOT NULL,
    rate_to_usd DECIMAL(10,4) NOT NULL,
    PRIMARY KEY (curr_cd, fx_mth)
);

CREATE TABLE fct_ord_hdr (
    ord_id        INTEGER PRIMARY KEY,
    cust_id       INTEGER NOT NULL REFERENCES dim_cust(cust_id),
    ord_ts        TEXT NOT NULL,
    shp_ts        TEXT,
    ord_sts_cd    INTEGER NOT NULL,
    ord_chnl_cd   TEXT NOT NULL,
    curr_cd       TEXT NOT NULL,
    gross_amt_lcl DECIMAL(12,2),
    disc_amt_lcl  DECIMAL(12,2),
    tax_amt_lcl   DECIMAL(12,2),
    shp_fee_lcl   DECIMAL(12,2),
    tot_amt       DECIMAL(12,2),
    promo_cd      TEXT,
    pymt_mthd_cd  TEXT NOT NULL,
    b2b_flg       TEXT NOT NULL,
    ship_ctry_cd  TEXT NOT NULL,
    cncl_rsn_cd   TEXT,
    parent_ord_id INTEGER
);

CREATE TABLE fct_ord_ln (
    ord_id       INTEGER NOT NULL REFERENCES fct_ord_hdr(ord_id),
    ln_no        INTEGER NOT NULL,
    sku_id       INTEGER NOT NULL REFERENCES dim_sku(sku_id),
    ln_typ_cd    TEXT NOT NULL,
    qty          INTEGER NOT NULL,
    unit_prc_lcl DECIMAL(10,2) NOT NULL,
    ln_disc_lcl  DECIMAL(10,2) NOT NULL,
    ln_sts_cd    TEXT NOT NULL,
    PRIMARY KEY (ord_id, ln_no)
);

CREATE TABLE fct_rfnd (
    rfnd_id      INTEGER PRIMARY KEY,
    ord_id       INTEGER NOT NULL REFERENCES fct_ord_hdr(ord_id),
    ln_no        INTEGER,
    rfnd_ts      TEXT NOT NULL,
    rfnd_amt_lcl DECIMAL(12,2) NOT NULL,
    rfnd_rsn_cd  TEXT NOT NULL,
    rfnd_typ_cd  TEXT NOT NULL
);

-- Customers: 300 rows; ids above 290 are internal test accounts, every 40th is merged into the previous id.
WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 300)
INSERT INTO dim_cust
SELECT i,
       'Customer ' || i,
       'customer' || i || '@example.com',
       CASE WHEN i % 5 = 0 THEN NULL ELSE '555-' || (1000 + i) END,
       CASE i % 10 WHEN 0 THEN 'GB' WHEN 1 THEN 'CA' WHEN 2 THEN 'CA' ELSE 'US' END,
       CASE
           WHEN i % 10 = 0 THEN NULL
           WHEN i % 10 IN (1, 2) THEN CASE i % 2 WHEN 0 THEN 'ON' ELSE 'BC' END
           ELSE CASE i % 4 WHEN 0 THEN 'CA' WHEN 1 THEN 'NY' WHEN 2 THEN 'TX' ELSE 'WA' END
       END,
       datetime('2023-01-01 09:00:00', '+' || (i * 3) || ' days', '+' || ((i * 977) % 86400) || ' seconds'),
       CASE i % 4 WHEN 0 THEN 'WEB' WHEN 1 THEN 'APP' WHEN 2 THEN 'STR' ELSE 'REF' END,
       CASE i % 9 WHEN 0 THEN 'P' WHEN 1 THEN 'G' WHEN 2 THEN 'G' WHEN 3 THEN 'S' WHEN 4 THEN 'S' WHEN 5 THEN 'S' ELSE 'B' END,
       CASE WHEN i % 3 = 0 THEN 'N' ELSE 'Y' END,
       CASE WHEN i % 25 = 0 THEN 'C' WHEN i % 37 = 0 THEN 'S' ELSE 'A' END,
       CASE WHEN i > 290 THEN 'Y' ELSE 'N' END,
       CASE WHEN i % 40 = 0 THEN i - 1 END,
       CASE WHEN i % 4 = 3 AND i > 5 THEN (i * 7) % (i - 1) + 1 END,
       datetime('2026-10-28 12:00:00', '-' || ((i * 53) % 200) || ' days')
FROM n;

INSERT INTO ref_prod_grp (grp_cd, grp_nm, dept_cd) VALUES
    ('KTCH', 'Kitchen & Dining', 'HOME'),
    ('LVRM', 'Living Room', 'HOME'),
    ('BDRM', 'Bedroom', 'HOME'),
    ('BATH', 'Bath', 'HOME'),
    ('DECO', 'Decor', 'LIFESTYLE'),
    ('STOR', 'Storage', 'LIFESTYLE'),
    ('BNDL', 'Bundles', 'BUNDLE');

-- SKUs: 1-55 regular, 56 is a bundle parent, 57-58 are its components.
WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 58)
INSERT INTO dim_sku
SELECT i,
       NULL,
       CASE WHEN i = 56 THEN 'BNDL'
            ELSE CASE i % 6 WHEN 0 THEN 'KTCH' WHEN 1 THEN 'LVRM' WHEN 2 THEN 'BDRM' WHEN 3 THEN 'BATH' WHEN 4 THEN 'DECO' ELSE 'STOR' END
       END,
       CASE i % 3 WHEN 0 THEN 'ACM' WHEN 1 THEN 'NRD' ELSE 'HVN' END,
       CASE WHEN i = 56 THEN 100.00 ELSE ROUND(8 + (i * 37) % 140 + 0.99, 2) END,
       NULL,
       date('2024-01-01', '+' || (i * 11) || ' days'),
       CASE WHEN i % 13 = 0 THEN '2026-03-01' END,
       CASE WHEN i % 13 = 0 THEN 'N' ELSE 'Y' END,
       100 + (i * 53) % 2000,
       100 + i % 7
FROM n;

UPDATE dim_sku
SET sku_nm = CASE WHEN sku_id = 56 THEN 'Starter Kit'
                  ELSE (SELECT grp_nm FROM ref_prod_grp g WHERE g.grp_cd = dim_sku.grp_cd) || ' item ' || sku_id END,
    cost_usd = ROUND(list_prc_usd * 0.45, 2);

-- One rate per currency per month, 2025-01 to 2026-10.
WITH RECURSIVE m(i) AS (SELECT 0 UNION ALL SELECT i + 1 FROM m WHERE i < 21)
INSERT INTO ref_fx_rate
SELECT 'USD', strftime('%Y-%m', date('2025-01-01', '+' || i || ' months')), 1.0 FROM m
UNION ALL
SELECT 'CAD', strftime('%Y-%m', date('2025-01-01', '+' || i || ' months')), ROUND(0.70 + ((i * 7) % 10) / 100.0, 4) FROM m
UNION ALL
SELECT 'GBP', strftime('%Y-%m', date('2025-01-01', '+' || i || ' months')), ROUND(1.20 + ((i * 11) % 12) / 100.0, 4) FROM m;

-- Order headers. Amounts are filled in from the lines below.
WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 4000),
base AS (
    SELECT i,
           (i * 37) % 300 + 1 AS cust_id,
           datetime('2025-01-01 00:00:00', '+' || ((i * 14251) % 57024000) || ' seconds') AS ts
    FROM n
),
stat AS (
    SELECT i, cust_id, ts,
           CASE
               WHEN i % 50 = 0 AND ts < '2026-10-20' THEN 40
               WHEN ts >= '2026-10-20' THEN CASE i % 3 WHEN 0 THEN 10 WHEN 1 THEN 20 ELSE 30 END
               ELSE CASE i % 20 WHEN 0 THEN 90 WHEN 1 THEN 90 WHEN 2 THEN 95 ELSE 40 END
           END AS sts
    FROM base
)
INSERT INTO fct_ord_hdr
SELECT s.i,
       s.cust_id,
       s.ts,
       CASE WHEN s.sts IN (30, 40, 95)
            THEN datetime(s.ts, '+' || (1 + s.i % 4) || ' days', '+' || ((s.i * 31) % 36000) || ' seconds') END,
       s.sts,
       CASE s.i % 10 WHEN 0 THEN 'CS' WHEN 1 THEN 'APP' WHEN 2 THEN 'APP' WHEN 3 THEN 'MKT' WHEN 4 THEN 'MKT' ELSE 'WEB' END,
       CASE c.ctry_cd WHEN 'CA' THEN 'CAD' WHEN 'GB' THEN 'GBP' ELSE 'USD' END,
       0, 0, 0, 0, NULL,
       CASE WHEN s.i % 7 = 0 THEN 'SAVE10' WHEN s.i % 11 = 0 THEN 'WELCOME15' END,
       CASE s.i % 8 WHEN 0 THEN 'PP' WHEN 1 THEN 'PP' WHEN 2 THEN 'GC' WHEN 3 THEN 'BNPL' ELSE 'CC' END,
       CASE WHEN s.i % 17 = 0 THEN 'Y' ELSE 'N' END,
       c.ctry_cd,
       CASE WHEN s.sts = 90 THEN CASE s.i % 3 WHEN 0 THEN 'CUST' WHEN 1 THEN 'FRAUD' ELSE 'OOS' END END,
       CASE WHEN s.i % 50 = 0 AND s.ts < '2026-10-20' THEN s.i - 1 END
FROM stat s
JOIN dim_cust c ON c.cust_id = s.cust_id;

-- Regular lines: 1 to 3 per order.
WITH RECURSIVE k(ln) AS (SELECT 1 UNION ALL SELECT ln + 1 FROM k WHERE ln < 3),
l AS (
    SELECT h.ord_id, k.ln, s.sku_id,
           (h.ord_id + k.ln) % 3 + 1 AS qty,
           ROUND(s.list_prc_usd * CASE h.curr_cd WHEN 'CAD' THEN 1.37 WHEN 'GBP' THEN 0.79 ELSE 1 END, 2) AS price,
           CASE WHEN h.ord_sts_cd IN (30, 40, 95) THEN 'SHP' WHEN h.ord_sts_cd = 90 THEN 'CXL' ELSE 'OPN' END AS lsts,
           s.sku_id % 5 = 0 AND h.ord_id % 4 = 0 AS on_sale
    FROM fct_ord_hdr h
    JOIN k ON k.ln <= h.ord_id % 3 + 1
    JOIN dim_sku s ON s.sku_id = (h.ord_id * 7 + k.ln * 11) % 55 + 1
)
INSERT INTO fct_ord_ln
SELECT ord_id, ln, sku_id, 'STD', qty, price,
       CASE WHEN on_sale THEN ROUND(0.15 * qty * price, 2) ELSE 0 END,
       lsts
FROM l;

-- Bundles on every 10th order: a priced parent line (BND) and two zero-priced component lines (CMP).
INSERT INTO fct_ord_ln
SELECT h.ord_id, 10, 56, 'BND', 1,
       ROUND(100.00 * CASE h.curr_cd WHEN 'CAD' THEN 1.37 WHEN 'GBP' THEN 0.79 ELSE 1 END, 2), 0,
       CASE WHEN h.ord_sts_cd IN (30, 40, 95) THEN 'SHP' WHEN h.ord_sts_cd = 90 THEN 'CXL' ELSE 'OPN' END
FROM fct_ord_hdr h WHERE h.ord_id % 10 = 0;

INSERT INTO fct_ord_ln
SELECT h.ord_id, 10 + c.n, 56 + c.n, 'CMP', 1, 0, 0,
       CASE WHEN h.ord_sts_cd IN (30, 40, 95) THEN 'SHP' WHEN h.ord_sts_cd = 90 THEN 'CXL' ELSE 'OPN' END
FROM fct_ord_hdr h
JOIN (SELECT 1 AS n UNION ALL SELECT 2) c
WHERE h.ord_id % 10 = 0;

-- Header money columns, from the lines. Each UPDATE sees the previous one's result.
UPDATE fct_ord_hdr
SET gross_amt_lcl = COALESCE((SELECT ROUND(SUM(l.qty * l.unit_prc_lcl), 2) FROM fct_ord_ln l
                              WHERE l.ord_id = fct_ord_hdr.ord_id AND l.ln_typ_cd IN ('STD', 'BND')), 0),
    disc_amt_lcl  = COALESCE((SELECT SUM(l.ln_disc_lcl) FROM fct_ord_ln l
                              WHERE l.ord_id = fct_ord_hdr.ord_id AND l.ln_typ_cd IN ('STD', 'BND')), 0);

UPDATE fct_ord_hdr
SET disc_amt_lcl = ROUND(disc_amt_lcl + CASE promo_cd
        WHEN 'SAVE10' THEN 0.10 * (gross_amt_lcl - disc_amt_lcl)
        WHEN 'WELCOME15' THEN 0.15 * (gross_amt_lcl - disc_amt_lcl)
        ELSE 0 END, 2);

UPDATE fct_ord_hdr
SET tax_amt_lcl = ROUND((gross_amt_lcl - disc_amt_lcl) * CASE ship_ctry_cd WHEN 'US' THEN 0.07 WHEN 'CA' THEN 0.13 ELSE 0.20 END, 2),
    shp_fee_lcl = CASE WHEN gross_amt_lcl - disc_amt_lcl >= 75 THEN 0 ELSE 7.99 END;

-- Legacy total: only filled before the 2025-07 migration, and wrong (ignores discounts and shipping).
UPDATE fct_ord_hdr SET tot_amt = ROUND(gross_amt_lcl + tax_amt_lcl, 2) WHERE ord_ts < '2025-07-01';

-- Refunds: full for returned orders, partial and goodwill for some delivered ones. None dated in the future.
INSERT INTO fct_rfnd (ord_id, ln_no, rfnd_ts, rfnd_amt_lcl, rfnd_rsn_cd, rfnd_typ_cd)
SELECT ord_id, NULL, datetime(shp_ts, '+7 days'), ROUND(gross_amt_lcl - disc_amt_lcl, 2), 'RTN', 'FULL'
FROM fct_ord_hdr WHERE ord_sts_cd = 95 AND datetime(shp_ts, '+7 days') <= '2026-10-28 23:59:59';

INSERT INTO fct_rfnd (ord_id, ln_no, rfnd_ts, rfnd_amt_lcl, rfnd_rsn_cd, rfnd_typ_cd)
SELECT ord_id, NULL, datetime(shp_ts, '+10 days'), ROUND(0.3 * (gross_amt_lcl - disc_amt_lcl), 2), 'DMG', 'PART'
FROM fct_ord_hdr WHERE ord_sts_cd = 40 AND ord_id % 23 = 0 AND datetime(shp_ts, '+10 days') <= '2026-10-28 23:59:59';

INSERT INTO fct_rfnd (ord_id, ln_no, rfnd_ts, rfnd_amt_lcl, rfnd_rsn_cd, rfnd_typ_cd)
SELECT ord_id, NULL, datetime(shp_ts, '+3 days'), 5.00, 'LATE', 'GDW'
FROM fct_ord_hdr WHERE ord_sts_cd = 40 AND ord_id % 31 = 0 AND datetime(shp_ts, '+3 days') <= '2026-10-28 23:59:59';

-- Nobody registers after their first order.
UPDATE dim_cust
SET reg_ts = CASE
    WHEN (SELECT MIN(o.ord_ts) FROM fct_ord_hdr o WHERE o.cust_id = dim_cust.cust_id) < reg_ts
    THEN (SELECT MIN(o.ord_ts) FROM fct_ord_hdr o WHERE o.cust_id = dim_cust.cust_id)
    ELSE reg_ts END;
