# Power BI dashboard: build guide

This is the step-by-step guide for building the Power BI report on top of the pipeline's gold layer.
It takes about 2–3 hours the first time. Save the result as `powerbi/NW-Housing.pbix` and commit it, together with screenshots in `docs/img/`.

## 1. Get the data

**Option A, local:** run `python -m nwhousing run` first. The gold files are written to `data/gold/`.
**Option B, web (recommended for publishing):** once the GitHub Action has run, the files are on the `data-latest` release, and Power BI Service can refresh from them with no gateway.

1. Create two parameters (Home → Transform data → Manage Parameters → New):
   - `DataSource` (Text) = `Web` or `Local`
   - `LocalFolder` (Text) = full path to `data\gold\` ending in a backslash
2. Create the `GoldTable` function from [`queries.pq`](queries.pq).
3. Create one query per table: `= GoldTable("fact_sales")`, and so on for:
   `fact_sales`, `fact_rates_monthly`, `dim_date`, `dim_district`, `dim_outcode`, `dim_property_type`,
   `dim_market_period`, `dim_market_event`, `analysis_price_index`, `analysis_rate_sensitivity`,
   `analysis_price_drivers`, `mart_segment_change`, `dq_results`.
4. Apply the type fixes listed at the bottom of `queries.pq`.

## 2. Model (star schema)

```
                    dim_property_type
                           │ 1
                           │
dim_district 1 ──── * fact_sales * ──── 1 dim_date 1 ──── * fact_rates_monthly
                           │ *                 │ 1
                           │                   └──── * analysis_price_index (month → date)
                     1 dim_outcode
```

| From (many) | To (one) | Notes |
|---|---|---|
| `fact_sales[date_key]` | `dim_date[date_key]` | single direction |
| `fact_sales[district]` | `dim_district[district]` | |
| `fact_sales[property_type_code]` | `dim_property_type[property_type_code]` | |
| `fact_sales[outcode]` | `dim_outcode[outcode]` | |
| `fact_rates_monthly[date_key]` | `dim_date[date_key]` | rates are stored on the 1st of each month |
| `analysis_price_index[month]` | `dim_date[date]` | |

Then:
- **Mark `dim_date` as the date table** (Table tools → Mark as date table → `date`).
- Sort `dim_date[month_name]` by `month_number`, `dim_property_type[property_type]` by `sort_order`,
  and `dim_market_period[market_period]` by `period_order`.
- Set `dim_outcode[latitude]` / `[longitude]` data categories to Latitude / Longitude.
- Hide the key columns (`date_key`, `property_type_code`, `outcode` on the fact table) from report view.
- Leave `mart_segment_change`, `analysis_rate_sensitivity`, `analysis_price_drivers`, `dq_results` disconnected:
  they are already aggregated.

## 3. Measures

Create an empty `_Measures` table and paste in every measure from [`measures.dax`](measures.dax).
Formats: prices `£#,0`, percentages `0.0%`, with `+0.0%;-0.0%;0.0%` for the change measures.

## 4. Theme

View → Themes → Browse for themes → [`nw-housing-theme.json`](nw-housing-theme.json).

## 5. Report pages

Canvas 1280 × 720. Put the slicers in one row at the top of every page: **Year range** (between slicer on `dim_date[date]`),
**County** and **District** (`dim_district`), **Property type**. Sync the slicers across pages (View → Sync slicers).

### Page 1: Market overview
| Visual | Fields |
|---|---|
| 4 KPI cards | `Last 12M Median Price`, `Last 12M Sales` (subtitle `Last 12M Sales YoY %`), `Bank Rate Latest %`, `Monthly Repayment (Median Home)` |
| Text box (dynamic) | `Data Through Label` |
| Clustered column + line | X `dim_date[month_start]`, columns `Sales`, line `Sales 3M Rolling Avg`; column colour = conditional formatting by field value `Sales Bar Colour` |
| Line chart (directly below, same X axis width) | X `fact_rates_monthly[month]`, Y `Bank Rate %`, `Mortgage Rate 2Y Fixed %` |
| Constant-line / shaded areas | Use `dim_market_event` as a tooltip table or add the stamp duty holiday & rate rise periods as X-axis constant lines |

**Do not** combine sales and rates on one dual-axis chart. Use the two stacked charts with the same time axis, as in the HTML report.

### Page 2: Rates & affordability
| Visual | Fields |
|---|---|
| Line | X `dim_date[month_start]`, Y `Monthly Repayment (Median Home)` |
| Line | `analysis_price_index[month]` vs `mix_adjusted_index`, `median_index` |
| Scatter / error bars | `analysis_rate_sensitivity`: X `lag_months`, Y `effect_per_1pp` (filter `rate_measure = "bank_rate"`), error bars from `ci_low` / `ci_high` |
| Card | `rate_effect_per_1pp` from the best lag (`is_best_lag = TRUE`) |
| Smart narrative or text box | Explain that the effect is an association, not causation |

### Page 3: Local areas
| Visual | Fields |
|---|---|
| Map (Azure Maps / bubble map) | Latitude/Longitude from `dim_outcode`, size `Sales`, colour `Median Price vs Region %` (diverging blue ↔ red, grey midpoint) |
| Bar chart | `mart_segment_change` filtered to `dimension = "District"`: `volume_change` by `segment`; Liverpool highlighted with `District Highlight Colour` |
| Matrix | Rows `dim_district[district_name]`; values `Median Price`, `Median Price YoY %`, `Sales per Month`, `Sales vs 2019 %`, `New Build Share` |
| Drill-through | From district to a detail page with monthly trend for that district |

### Page 4: Data quality (optional, recruiters like it)
A table of `dq_results` with conditional icons on `passed`, plus the `Data Through Label`.

## 6. Publish & schedule refresh
1. Publish to a Power BI workspace (Power BI Service).
2. Dataset settings → Data source credentials → `https://github.com` → **Anonymous**, Privacy level **Public**.
3. Scheduled refresh: monthly, a day after the GitHub Action (e.g. the 4th of each month).
4. Optional: *Publish to web* gives a public embed link for your portfolio and LinkedIn, if your tenant allows it. It is safe here because the data is public under the OGL.
   Without Power BI Service access (it needs a work or school account), commit the `.pbix` plus screenshots instead. The HTML report on GitHub Pages already gives recruiters a live view.

## 7. Portfolio finishing touches
- Export each page as PNG to `docs/img/` and reference them in the README.
- Record a 60–90 second walkthrough (Loom/Teams) and link it in the README.
