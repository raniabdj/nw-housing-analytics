"""Extract: postcodes.io outward-code lookup (coordinates for maps).

Only outcodes not already in the cache are requested, so monthly runs make a
handful of calls rather than hundreds.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd
import requests

from ..config import Config
from ..http import make_session

log = logging.getLogger(__name__)

CACHE_COLUMNS = ["outcode", "latitude", "longitude", "admin_district", "lookup_status"]


def _load_cache(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(columns=CACHE_COLUMNS)


def lookup_outcode(outcode: str, base_url: str, session: requests.Session) -> dict:
    resp = session.get(f"{base_url}/outcodes/{outcode}", timeout=30)
    if resp.status_code == 404:
        return {"outcode": outcode, "latitude": None, "longitude": None,
                "admin_district": None, "lookup_status": "not_found"}
    resp.raise_for_status()
    r = resp.json()["result"]
    districts = r.get("admin_district") or []
    return {
        "outcode": outcode,
        "latitude": r.get("latitude"),
        "longitude": r.get("longitude"),
        "admin_district": "; ".join(districts) if isinstance(districts, list) else districts,
        "lookup_status": "ok",
    }


def extract_outcodes(cfg: Config, outcodes: list[str]) -> Path:
    out = cfg.paths.bronze / "postcodes" / "outcodes.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    cache = _load_cache(out)

    demo_file = cfg.extra.get("outcodes_file")
    if demo_file:                                       # demo/offline mode: read from local JSON
        records = json.loads(Path(demo_file).read_text())
        pd.DataFrame(records, columns=CACHE_COLUMNS).to_parquet(out, index=False)
        return out

    resolved = set(cache.loc[cache["lookup_status"] != "error", "outcode"])   # errors are retried
    todo = sorted(set(o for o in outcodes if o) - resolved)
    log.info("postcodes.io: %s cached, %s to look up", len(cache), len(todo))
    session = make_session()
    rows = []
    for i, oc in enumerate(todo, 1):
        try:
            rows.append(lookup_outcode(oc, cfg["postcodes"]["base_url"], session))
        except requests.RequestException as exc:       # a lookup failure must not stop the pipeline
            log.warning("Outcode %s lookup failed: %s", oc, exc)
            rows.append({"outcode": oc, "latitude": None, "longitude": None,
                         "admin_district": None, "lookup_status": "error"})
        if i % 50 == 0:
            log.info("  looked up %s/%s", i, len(todo))
        time.sleep(cfg["postcodes"]["pause_seconds"])

    if rows:
        new = pd.DataFrame(rows, columns=CACHE_COLUMNS)
        cache = pd.concat([cache[cache["lookup_status"] != "error"], new], ignore_index=True)
        cache = cache.drop_duplicates("outcode", keep="last")
        cache.to_parquet(out, index=False)
    return out
