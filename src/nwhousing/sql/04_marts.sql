-- Analysis marts: pre-aggregated tables for the report and Power BI.
-- {ltv} and {term_months} come from config/pipeline.yaml.

-- Region-level monthly series joined to interest rates.
CREATE OR REPLACE TABLE mart_region_month AS
WITH m AS (
    SELECT
        sale_month                                         AS month,
        count(*)                                           AS sales_all,
        count(*) FILTER (WHERE in_analysis)                AS sales,
        median(price) FILTER (WHERE in_analysis)           AS median_price,
        avg(price) FILTER (WHERE in_analysis)              AS mean_price,
        quantile_cont(price, 0.25) FILTER (WHERE in_analysis) AS p25_price,
        quantile_cont(price, 0.75) FILTER (WHERE in_analysis) AS p75_price,
        avg(CASE WHEN is_new_build THEN 1 ELSE 0 END) FILTER (WHERE in_analysis) AS new_build_share
    FROM fact_sales
    GROUP BY sale_month
),
r AS (SELECT * FROM fact_rates_monthly)
SELECT
    m.*,
    m.month <= c.last_complete_month                       AS is_complete_month,
    r.bank_rate,
    r.bank_rate_month_end,
    r.mortgage_2y_fixed_75ltv,
    -- Monthly repayment on the median home: {ltv} LTV, {term_months}-month repayment mortgage.
    CASE WHEN r.mortgage_2y_fixed_75ltv IS NOT NULL THEN
        (m.median_price * {ltv}) * (r.mortgage_2y_fixed_75ltv / 1200.0)
        / (1 - pow(1 + r.mortgage_2y_fixed_75ltv / 1200.0, -{term_months}))
    END                                                    AS median_monthly_payment,
    m.median_price / lag(m.median_price, 12) OVER (ORDER BY m.month) - 1    AS median_price_yoy,
    m.sales / lag(m.sales, 12) OVER (ORDER BY m.month) - 1                  AS sales_yoy,
    avg(m.sales) OVER (ORDER BY m.month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS sales_3m_avg,
    p.market_period
FROM m
CROSS JOIN meta_cutoff c
LEFT JOIN r ON r.month = m.month
LEFT JOIN seed_market_periods p ON m.month BETWEEN p.start_month AND p.end_month
ORDER BY m.month;

-- District x month.
CREATE OR REPLACE TABLE mart_district_month AS
WITH m AS (
    SELECT sale_month AS month, district,
           count(*)                    AS sales,
           median(price)               AS median_price,
           avg(price)                  AS mean_price
    FROM fact_sales WHERE in_analysis
    GROUP BY ALL
)
SELECT m.*, d.county,
       m.month <= c.last_complete_month AS is_complete_month,
       m.median_price / lag(m.median_price, 12) OVER (PARTITION BY m.district ORDER BY m.month) - 1 AS median_price_yoy
FROM m
JOIN dim_district d USING (district)
CROSS JOIN meta_cutoff c
ORDER BY district, month;

-- Before/after: baseline year vs the latest 12 complete months, by segment.
CREATE OR REPLACE TABLE mart_segment_change AS
WITH windows AS (
    SELECT
        make_date({baseline_year}, 1, 1)                       AS base_start,
        make_date({baseline_year}, 12, 1)                      AS base_end,
        CAST(last_complete_month - INTERVAL 11 MONTH AS DATE)  AS latest_start,
        last_complete_month                                    AS latest_end
    FROM meta_cutoff
),
tagged AS (
    SELECT f.*,
        CASE WHEN f.sale_month BETWEEN w.base_start AND w.base_end THEN 'baseline'
             WHEN f.sale_month BETWEEN w.latest_start AND w.latest_end THEN 'latest' END AS win
    FROM fact_sales f CROSS JOIN windows w
    WHERE f.in_analysis
),
segments AS (
    SELECT 'Region' AS dimension, '{region}' AS segment, win, price FROM tagged WHERE win IS NOT NULL
    UNION ALL
    SELECT 'Property type', pt.property_type, win, price
    FROM tagged t JOIN dim_property_type pt USING (property_type_code) WHERE win IS NOT NULL
    UNION ALL
    SELECT 'District', initcap(lower(district)), win, price FROM tagged WHERE win IS NOT NULL
    UNION ALL
    SELECT 'Build', CASE WHEN is_new_build THEN 'New build' ELSE 'Existing home' END, win, price
    FROM tagged WHERE win IS NOT NULL
)
SELECT
    dimension, segment,
    count(*) FILTER (WHERE win = 'baseline') / 12.0       AS baseline_sales_per_month,
    count(*) FILTER (WHERE win = 'latest')   / 12.0       AS latest_sales_per_month,
    median(price) FILTER (WHERE win = 'baseline')         AS baseline_median_price,
    median(price) FILTER (WHERE win = 'latest')           AS latest_median_price,
    latest_sales_per_month / nullif(baseline_sales_per_month, 0) - 1 AS volume_change,
    latest_median_price / nullif(baseline_median_price, 0) - 1      AS price_change
FROM segments
GROUP BY dimension, segment
HAVING count(*) FILTER (WHERE win = 'baseline') >= 50     -- suppress tiny segments
ORDER BY dimension, volume_change;
