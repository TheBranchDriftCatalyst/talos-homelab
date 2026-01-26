"""
Shared Dagster resources for all pipelines.
"""

import os
from pathlib import Path
from typing import Any

from dagster import (
    ConfigurableIOManager,
    ConfigurableResource,
    InputContext,
    OutputContext,
    resource,
)
from corpus_core.loaders import ParquetLoader
from pydantic import BaseModel


class ParquetIOManager(ConfigurableIOManager):
    """
    IO Manager that stores assets as Parquet files.

    Organizes files by domain/asset_name.parquet
    """

    base_path: str

    def _get_path(self, context: OutputContext | InputContext) -> Path:
        """Get the path for an asset."""
        # Get domain from asset group or default to 'default'
        domain = getattr(context, "asset_key", None)
        if domain and len(domain.path) > 0:
            domain_name = context.asset_key.path[0] if len(context.asset_key.path) > 1 else "default"
            asset_name = context.asset_key.path[-1]
        else:
            domain_name = "default"
            asset_name = context.name

        return Path(self.base_path) / domain_name / f"{asset_name}.parquet"

    def handle_output(self, context: OutputContext, obj: Any) -> None:
        """Save asset to Parquet."""
        path = self._get_path(context)
        path.parent.mkdir(parents=True, exist_ok=True)

        loader = ParquetLoader(Path(self.base_path))

        # Determine domain from context
        domain = "default"
        if context.asset_key and len(context.asset_key.path) > 1:
            domain = context.asset_key.path[0]

        asset_name = context.asset_key.path[-1] if context.asset_key else context.name

        # Convert list of Pydantic models to list of dicts if needed
        if isinstance(obj, list) and len(obj) > 0 and hasattr(obj[0], "model_dump"):
            data = [item.model_dump(mode="json") for item in obj]
        elif isinstance(obj, list):
            data = obj
        else:
            data = [obj] if obj else []

        loader.write(domain, asset_name, data)
        context.log.info(f"Wrote {len(data)} records to {path}")

    def load_input(self, context: InputContext) -> Any:
        """Load asset from Parquet."""
        path = self._get_path(context)

        if not path.exists():
            raise FileNotFoundError(f"Asset not found: {path}")

        loader = ParquetLoader(Path(self.base_path))

        domain = "default"
        if context.asset_key and len(context.asset_key.path) > 1:
            domain = context.asset_key.path[0]

        asset_name = context.asset_key.path[-1] if context.asset_key else context.name

        table = loader.read(domain, asset_name)
        return table.to_pylist()


@resource
def datasets_path_resource(context) -> Path:
    """Resource providing the datasets directory path."""
    return Path(os.environ.get(
        "DATASETS_PATH",
        str(Path(__file__).parent.parent.parent / "datasets")
    ))
