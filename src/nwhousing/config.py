"""Configuration loading and project paths."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "pipeline.yaml"


@dataclass
class Paths:
    data_dir: Path
    site_dir: Path

    @property
    def bronze(self) -> Path:
        return self.data_dir / "bronze"

    @property
    def silver(self) -> Path:
        return self.data_dir / "silver"

    @property
    def gold(self) -> Path:
        return self.data_dir / "gold"

    @property
    def warehouse(self) -> Path:
        return self.data_dir / "warehouse.duckdb"

    def ensure(self) -> None:
        for p in (self.bronze, self.silver, self.gold, self.site_dir):
            p.mkdir(parents=True, exist_ok=True)


@dataclass
class Config:
    raw: dict[str, Any]
    paths: Paths
    demo: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    @property
    def counties(self) -> list[str]:
        return [c.upper() for c in self.raw["counties"]]


def load_config(path: Path | str | None = None, data_dir: str | None = None, demo: bool = False) -> Config:
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    base = PROJECT_ROOT
    ddir = Path(data_dir) if data_dir else base / raw["paths"]["data_dir"]
    if demo and not data_dir:
        ddir = base / "data_demo"
    paths = Paths(data_dir=ddir, site_dir=base / raw["paths"]["site_dir"])
    paths.ensure()
    return Config(raw=raw, paths=paths, demo=demo)
