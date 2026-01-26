"""
Dagster Definitions

Entry point for all pipeline assets, jobs, schedules, and resources.
"""

import os
from pathlib import Path

from dagster import (
    Definitions,
    EnvVar,
    load_assets_from_modules,
)

from domains.congress import assets as congress_assets
from domains.edgar import assets as edgar_assets
from domains.reddit import assets as reddit_assets
from resources import (
    ParquetIOManager,
    datasets_path_resource,
)


# Load all assets from domain modules
congress_asset_list = load_assets_from_modules([congress_assets])
edgar_asset_list = load_assets_from_modules([edgar_assets])
reddit_asset_list = load_assets_from_modules([reddit_assets])

all_assets = [
    *congress_asset_list,
    *edgar_asset_list,
    *reddit_asset_list,
]

# Resources
resources = {
    "parquet_io_manager": ParquetIOManager(
        base_path=os.environ.get("DATASETS_PATH", str(Path(__file__).parent.parent.parent / "datasets")),
    ),
    "datasets_path": datasets_path_resource,
}

defs = Definitions(
    assets=all_assets,
    resources=resources,
)
