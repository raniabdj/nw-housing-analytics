-- Dimensions for the star schema.

CREATE OR REPLACE TABLE dim_date AS
WITH days AS (
    SELECT CAST(d AS DATE) AS date
    FROM generate_series(
        (SELECT CAST(first_month AS TIMESTAMP) FROM meta_cutoff),
        CAST(make_date(year(current_date), 12, 31) AS TIMESTAMP),
        INTERVAL 1 DAY) AS t(d)
)
SELECT
    d.date,
    CAST(strftime(d.date, '%Y%m%d') AS INTEGER)       AS date_key,
    year(d.date)                                      AS year,
    'Q' || quarter(d.date)                            AS quarter,
    month(d.date)                                     AS month_number,
    strftime(d.date, '%b')                            AS month_name,
    CAST(date_trunc('month', d.date) AS DATE)         AS month_start,
    strftime(d.date, '%Y-%m')                         AS year_month,
    p.market_period,
    p.period_order,
    date_trunc('month', d.date) <= c.last_complete_month AS is_complete_month
FROM days d
CROSS JOIN meta_cutoff c
LEFT JOIN seed_market_periods p
       ON date_trunc('month', d.date) BETWEEN p.start_month AND p.end_month
ORDER BY d.date;

CREATE OR REPLACE TABLE dim_property_type AS
SELECT * FROM (VALUES
    ('D', 'Detached',        1),
    ('S', 'Semi-detached',   2),
    ('T', 'Terraced',        3),
    ('F', 'Flat/Maisonette', 4),
    ('O', 'Other',           5)
) AS t(property_type_code, property_type, sort_order);

CREATE OR REPLACE TABLE dim_district AS
SELECT
    district,
    -- a district belongs to one county; take the most common if the source disagrees
    mode(county)                                      AS county,
    initcap(lower(district))                          AS district_name,
    initcap(lower(mode(county)))                      AS county_name,
    count(*)                                          AS total_sales
FROM stg_sales
GROUP BY district;

CREATE OR REPLACE TABLE dim_outcode AS
SELECT
    s.outcode,
    mode(s.district)                                  AS main_district,
    o.latitude,
    o.longitude,
    count(*)                                          AS total_sales
FROM stg_sales s
LEFT JOIN stg_outcodes o USING (outcode)
WHERE s.outcode IS NOT NULL
GROUP BY s.outcode, o.latitude, o.longitude;

CREATE OR REPLACE TABLE dim_market_period AS
SELECT period_order, market_period, start_month,
       least(end_month, (SELECT latest_month FROM meta_cutoff)) AS end_month,
       description
FROM seed_market_periods;

CREATE OR REPLACE TABLE dim_market_event AS
SELECT * FROM seed_market_events ORDER BY event_date;
