// =====================================================================
// Power Query (M) for the North West Housing Power BI report
// =====================================================================
// 1. In Power BI Desktop: Home > Transform data > New Parameter
//      Name: DataSource   Type: Text   Current value: Web   (or Local)
//      Name: LocalFolder  Type: Text   Current value: C:\path\to\nw-housing-analytics\data\gold\
// 2. Home > New Source > Blank Query, open Advanced Editor and paste the
//    "GoldTable" function below. Rename the query to GoldTable.
// 3. For each table, create a Blank Query containing one line, e.g.
//        = GoldTable("fact_sales")
//    and name the query after the table (fact_sales, dim_date, ...).
//
// "Web" reads the monthly-refreshed files from the GitHub release, so the
// published report refreshes in the Power BI Service without a gateway.
// RelativePath keeps the base URL static, which the Service requires for
// scheduled refresh of Web.Contents sources.
// =====================================================================

// ---- GoldTable (function) -------------------------------------------
(tableName as text) as table =>
let
    FileName = tableName & ".parquet",
    Binary =
        if DataSource = "Web" then
            Web.Contents(
                "https://github.com",
                [RelativePath = "raniabdj/nw-housing-analytics/releases/download/data-latest/" & FileName]
            )
        else
            File.Contents(LocalFolder & FileName),
    Data = Parquet.Document(Binary)
in
    Data


// ---- Type fixes applied after loading (paste into each query as a step) ----
// dim_date:
//   = Table.TransformColumnTypes(Source, {{"date", type date}, {"month_start", type date},
//        {"date_key", Int64.Type}, {"year", Int64.Type}, {"month_number", Int64.Type},
//        {"is_complete_month", type logical}})
// fact_sales:
//   = Table.TransformColumnTypes(Source, {{"sale_date", type date}, {"sale_month", type date},
//        {"price", Int64.Type}, {"date_key", Int64.Type}})
// fact_rates_monthly:
//   = Table.TransformColumnTypes(Source, {{"month", type date}, {"date_key", Int64.Type}})
// dim_outcode:
//   = Table.TransformColumnTypes(Source, {{"latitude", type number}, {"longitude", type number}})
