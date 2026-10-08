-- Fact tables.

-- One row per registered sale (transaction grain).
CREATE OR REPLACE TABLE fact_sales AS
SELECT
    transaction_id,
    CAST(strftime(sale_date, '%Y%m%d') AS INTEGER)    AS date_key,
    CAST(sale_date AS DATE)                           AS sale_date,
    CAST(sale_month AS DATE)                          AS sale_month,
    price,
    property_type_code,
    is_new_build,
    tenure,
    district,
    county,
    outcode,
    postcode,
    town_city,
    ppd_category,
    is_standard,
    is_price_outlier,
    -- Analysis population: standard market sales of houses/flats, outliers excluded.
    (is_standard AND NOT is_price_outlier)            AS in_analysis
FROM stg_sales;

-- One row per month of interest-rate data.
CREATE OR REPLACE TABLE fact_rates_monthly AS
SELECT
    CAST(month AS DATE)                               AS month,
    CAST(strftime(month, '%Y%m%d') AS INTEGER)        AS date_key,
    * EXCLUDE (month)
FROM stg_rates
WHERE month >= (SELECT first_month FROM meta_cutoff) - INTERVAL 12 MONTH;
