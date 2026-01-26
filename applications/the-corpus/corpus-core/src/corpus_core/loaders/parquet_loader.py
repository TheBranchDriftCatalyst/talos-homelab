"""
Parquet Loader

Unified Parquet storage for all datasets.
Supports writing, reading, and streaming large datasets.
"""

from pathlib import Path
from typing import Iterator, Any

import pyarrow as pa
import pyarrow.parquet as pq
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class ParquetLoader:
    """
    Unified Parquet storage for all datasets.

    Provides efficient columnar storage with:
    - Domain-based organization
    - Batch reading for large datasets
    - Streaming support for memory-efficient processing
    """

    def __init__(self, base_path: Path | str):
        """
        Initialize ParquetLoader.

        Args:
            base_path: Base directory for all Parquet files
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_path(self, domain: str, name: str) -> Path:
        """Get the full path for a dataset."""
        return self.base_path / domain / f"{name}.parquet"

    def write(
        self,
        domain: str,
        name: str,
        data: list[BaseModel] | list[dict[str, Any]],
        compression: str = "snappy",
    ) -> Path:
        """
        Write dataset to Parquet.

        Args:
            domain: Domain name (e.g., 'congress', 'edgar', 'reddit')
            name: Dataset name (e.g., 'bills', 'filings', 'submissions')
            data: List of Pydantic models or dicts to write
            compression: Compression codec (snappy, gzip, zstd)

        Returns:
            Path to the written Parquet file
        """
        path = self._get_path(domain, name)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Convert Pydantic models to dicts
        if data and isinstance(data[0], BaseModel):
            records = [d.model_dump(mode="json") for d in data]
        else:
            records = list(data)

        if not records:
            logger.warning("write_empty_dataset", domain=domain, name=name)
            # Write empty parquet with schema inferred from empty list
            table = pa.Table.from_pylist([])
            pq.write_table(table, path, compression=compression)
            return path

        table = pa.Table.from_pylist(records)
        pq.write_table(table, path, compression=compression)

        logger.info(
            "parquet_written",
            domain=domain,
            name=name,
            rows=len(records),
            path=str(path),
        )
        return path

    def write_batched(
        self,
        domain: str,
        name: str,
        data_iterator: Iterator[BaseModel | dict[str, Any]],
        batch_size: int = 10000,
        compression: str = "snappy",
    ) -> Path:
        """
        Write large dataset to Parquet in batches.

        Useful for datasets too large to fit in memory.

        Args:
            domain: Domain name
            name: Dataset name
            data_iterator: Iterator yielding records
            batch_size: Number of records per batch
            compression: Compression codec

        Returns:
            Path to the written Parquet file
        """
        path = self._get_path(domain, name)
        path.parent.mkdir(parents=True, exist_ok=True)

        writer = None
        total_rows = 0

        try:
            batch = []
            for record in data_iterator:
                if isinstance(record, BaseModel):
                    batch.append(record.model_dump(mode="json"))
                else:
                    batch.append(record)

                if len(batch) >= batch_size:
                    table = pa.Table.from_pylist(batch)
                    if writer is None:
                        writer = pq.ParquetWriter(path, table.schema, compression=compression)
                    writer.write_table(table)
                    total_rows += len(batch)
                    logger.debug("batch_written", rows=len(batch), total=total_rows)
                    batch = []

            # Write remaining records
            if batch:
                table = pa.Table.from_pylist(batch)
                if writer is None:
                    writer = pq.ParquetWriter(path, table.schema, compression=compression)
                writer.write_table(table)
                total_rows += len(batch)

        finally:
            if writer:
                writer.close()

        logger.info(
            "parquet_written_batched",
            domain=domain,
            name=name,
            total_rows=total_rows,
            path=str(path),
        )
        return path

    def read(self, domain: str, name: str) -> pa.Table:
        """
        Read entire dataset from Parquet.

        Args:
            domain: Domain name
            name: Dataset name

        Returns:
            PyArrow Table
        """
        path = self._get_path(domain, name)
        if not path.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")

        table = pq.read_table(path)
        logger.info("parquet_read", domain=domain, name=name, rows=table.num_rows)
        return table

    def read_pandas(self, domain: str, name: str):
        """
        Read dataset as pandas DataFrame.

        Args:
            domain: Domain name
            name: Dataset name

        Returns:
            pandas DataFrame
        """
        table = self.read(domain, name)
        return table.to_pandas()

    def stream(
        self,
        domain: str,
        name: str,
        batch_size: int = 10000,
        columns: list[str] | None = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """
        Stream large datasets in batches.

        Memory-efficient way to process datasets that don't fit in memory.

        Args:
            domain: Domain name
            name: Dataset name
            batch_size: Number of records per batch
            columns: Optional list of columns to read

        Yields:
            Lists of records (dicts)
        """
        path = self._get_path(domain, name)
        if not path.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")

        parquet_file = pq.ParquetFile(path)
        total_batches = 0

        for batch in parquet_file.iter_batches(batch_size=batch_size, columns=columns):
            records = batch.to_pylist()
            total_batches += 1
            logger.debug("batch_streamed", batch=total_batches, rows=len(records))
            yield records

        logger.info("stream_complete", domain=domain, name=name, batches=total_batches)

    def exists(self, domain: str, name: str) -> bool:
        """Check if a dataset exists."""
        return self._get_path(domain, name).exists()

    def get_metadata(self, domain: str, name: str) -> dict[str, Any]:
        """
        Get metadata about a dataset.

        Returns:
            Dict with num_rows, num_columns, schema, file_size
        """
        path = self._get_path(domain, name)
        if not path.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")

        parquet_file = pq.ParquetFile(path)
        metadata = parquet_file.metadata

        return {
            "num_rows": metadata.num_rows,
            "num_columns": metadata.num_columns,
            "schema": str(parquet_file.schema_arrow),
            "file_size_bytes": path.stat().st_size,
            "created_by": metadata.created_by,
        }

    def list_datasets(self, domain: str | None = None) -> list[dict[str, str]]:
        """
        List available datasets.

        Args:
            domain: Optional domain filter

        Returns:
            List of dicts with domain and name
        """
        datasets = []

        if domain:
            domain_path = self.base_path / domain
            if domain_path.exists():
                for f in domain_path.glob("*.parquet"):
                    datasets.append({"domain": domain, "name": f.stem})
        else:
            for domain_path in self.base_path.iterdir():
                if domain_path.is_dir():
                    for f in domain_path.glob("*.parquet"):
                        datasets.append({"domain": domain_path.name, "name": f.stem})

        return datasets

    def delete(self, domain: str, name: str) -> bool:
        """
        Delete a dataset.

        Returns:
            True if deleted, False if not found
        """
        path = self._get_path(domain, name)
        if path.exists():
            path.unlink()
            logger.info("parquet_deleted", domain=domain, name=name)
            return True
        return False
