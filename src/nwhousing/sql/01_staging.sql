-- Staging: expose silver files and seed CSVs to DuckDB as views.
-- {silver}, {bronze} and {config} are filled in by warehouse.py.

-- "ST HELENS" -> "St Helens", keeping small joining words lower case.
CREATE OR REPLACE MACRO initcap(s) AS array_to_string(
    list_transform(string_split(lower(s), ' '),
        w -> CASE WHEN w IN ('and', 'with', 'of', 'the', 'upon', 'on') THEN w
                  ELSE upper(w[1]) || w[2:] END), ' ');

CREATE OR REPLACE VIEW stg_sales AS
SELECT * FROM read_parquet('{silver}/sales.parquet');

CREATE OR REPLACE VIEW stg_rates AS
SELECT * FROM read_parquet('{silver}/rates_monthly.parquet');

CREATE OR REPLACE VIEW stg_outcodes AS
SELECT * FROM read_parquet('{bronze}/postcodes/outcodes.parquet');

CREATE OR REPLACE TABLE seed_market_periods AS
SELECT * FROM read_csv('{config}/market_periods.csv', header = true,
    columns = {{'period_order': 'INTEGER', 'market_period': 'VARCHAR', 'start_month': 'DATE',
               'end_month': 'DATE', 'description': 'VARCHAR'}});

CREATE OR REPLACE TABLE seed_market_events AS
SELECT * FROM read_csv('{config}/market_events.csv', header = true,
    columns = {{'event_date': 'DATE', 'event': 'VARCHAR', 'category': 'VARCHAR'}});

-- Land Registry registrations lag completions by 2-3 months, so the most
-- recent months are provisional. One row holding the cut-off used everywhere.
CREATE OR REPLACE TABLE meta_cutoff AS
SELECT
    max(sale_month)                                   AS latest_month,
    CAST(max(sale_month) - INTERVAL 3 MONTH AS DATE)  AS last_complete_month,
    min(sale_month)                                   AS first_month
FROM stg_sales;
