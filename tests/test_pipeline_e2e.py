"""End-to-end: run the whole pipeline on synthetic data, then an incremental (CDC) run."""
import duckdb
import pandas as pd

from nwhousing.config import load_config
from nwhousing.pipeline import run


def test_full_pipeline_on_demo_data(tmp_path):
    cfg = load_config(data_dir=str(tmp_path / "data"), demo=True)
    cfg.paths.site_dir = tmp_path / "site"
    cfg.paths.ensure()

    first = run(cfg, mode="auto")
    assert first["status"] == "success" and first["mode"] == "backfill"

    gold = cfg.paths.gold
    for name in ("fact_sales.parquet", "dim_date.csv", "mart_region_month.csv",
                 "analysis_rate_sensitivity.csv", "analysis_headlines.csv", "dq_results.csv"):
        assert (gold / name).exists(), name

    con = duckdb.connect(str(cfg.paths.warehouse), read_only=True)
    # every sale joins to each dimension (referential integrity of the star schema)
    orphans = con.execute("""
        SELECT count(*) FROM fact_sales f
        LEFT JOIN dim_date d USING (date_key)
        LEFT JOIN dim_district di USING (district)
        LEFT JOIN dim_property_type p USING (property_type_code)
        WHERE d.date IS NULL OR di.district IS NULL OR p.property_type IS NULL""").fetchone()[0]
    assert orphans == 0
    n_before = con.execute("SELECT count(*) FROM fact_sales").fetchone()[0]
    con.close()

    heads = pd.read_csv(gold / "analysis_headlines.csv").set_index("metric")["value"]
    effect = float(heads["rate_effect_per_1pp"])
    assert -0.2 < effect < 0          # synthetic data has a built-in negative rate effect

    second = run(cfg, mode="auto")
    assert second["status"] == "success" and second["mode"] == "incremental"
    con = duckdb.connect(str(cfg.paths.warehouse), read_only=True)
    n_after = con.execute("SELECT count(*) FROM fact_sales").fetchone()[0]
    con.close()
    assert n_after > n_before          # demo change file adds more rows than it deletes

    assert (cfg.paths.site_dir / "index_demo.html").read_text().count("Plotly") > 0
