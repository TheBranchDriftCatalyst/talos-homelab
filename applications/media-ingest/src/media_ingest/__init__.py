"""Media file processing pipeline — Dagster code location."""

from dagster import Definitions

from media_ingest.assets import (
    media_documents,
    media_embeddings,
    media_files,
    media_metadata,
    media_transcriptions,
)

defs = Definitions(
    assets=[
        media_files,
        media_metadata,
        media_documents,
        media_transcriptions,
        media_embeddings,
    ],
)
