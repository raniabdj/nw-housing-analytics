"""Shared HTTP session with retries, back-off and a polite User-Agent.

All network access in the project goes through this module, so retry and
timeout behaviour is consistent and easy to test.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

USER_AGENT = "nw-housing-analytics/1.0 (portfolio data pipeline; github.com/raniabdj)"


def make_session(total_retries: int = 5, backoff: float = 1.5) -> requests.Session:
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff,                     # 0s, 1.5s, 3s, 6s, 12s ...
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def download_file(url: str, dest: Path, session: requests.Session | None = None,
                  timeout: int = 120) -> dict:
    """Stream a (possibly very large) file to disk. Supports file:// URLs for demo/offline runs.

    Returns a small manifest dict (url, bytes, sha256) used for lineage.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    sha = hashlib.sha256()

    parsed = urlparse(url)
    if parsed.scheme == "file":
        shutil.copyfile(Path(parsed.path), tmp)
        sha.update(tmp.read_bytes())
    else:
        session = session or make_session()
        log.info("Downloading %s", url)
        with session.get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
                    sha.update(chunk)
    tmp.replace(dest)
    size = dest.stat().st_size
    log.info("Saved %s (%.1f MB)", dest.name, size / 1e6)
    return {"url": url, "bytes": size, "sha256": sha.hexdigest()}


def get_text(url: str, params: dict | None = None, session: requests.Session | None = None,
             timeout: int = 60) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return Path(parsed.path).read_text(encoding="utf-8")
    session = session or make_session()
    resp = session.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.text
