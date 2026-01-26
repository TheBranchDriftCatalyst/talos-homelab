"""
Reddit Pushshift Loader

Load Reddit data from Pushshift archives via HuggingFace datasets
or local Parquet files.

Data sources:
1. HuggingFaceGECLM/REDDIT_comments - 50 subreddits, 2006-2023
2. fddemarco/pushshift-reddit-comments - Pushshift mirror
3. Local Parquet files (from Academic Torrents)
"""

from pathlib import Path
from typing import Iterator, Any

import structlog

logger = structlog.get_logger()


class PushshiftLoader:
    """
    Load Reddit data from Pushshift archives.

    Supports:
    - HuggingFace datasets (streaming)
    - Local Parquet files
    """

    def __init__(self, cache_dir: Path | None = None):
        """
        Initialize loader.

        Args:
            cache_dir: Optional directory for HuggingFace cache
        """
        self.cache_dir = cache_dir

    def load_from_huggingface(
        self,
        dataset: str = "HuggingFaceGECLM/REDDIT_comments",
        split: str = "train",
        subreddits: list[str] | None = None,
        max_records: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Stream data from HuggingFace datasets.

        Args:
            dataset: HuggingFace dataset name
            split: Dataset split
            subreddits: Optional list of subreddits to filter
            max_records: Maximum number of records to return

        Yields:
            Record dicts
        """
        from datasets import load_dataset

        logger.info("loading_huggingface_dataset", dataset=dataset, split=split)

        # Stream to avoid loading entire dataset into memory
        ds = load_dataset(
            dataset,
            split=split,
            streaming=True,
            cache_dir=str(self.cache_dir) if self.cache_dir else None,
        )

        count = 0
        for record in ds:
            # Filter by subreddit if specified
            if subreddits:
                subreddit = record.get("subreddit", "").lower()
                if subreddit not in [s.lower() for s in subreddits]:
                    continue

            yield dict(record)
            count += 1

            if max_records and count >= max_records:
                break

        logger.info("huggingface_load_complete", count=count)

    def load_from_parquet(
        self,
        path: Path,
        subreddits: list[str] | None = None,
        max_records: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Load data from local Parquet files.

        Args:
            path: Path to Parquet file or directory
            subreddits: Optional list of subreddits to filter
            max_records: Maximum number of records to return

        Yields:
            Record dicts
        """
        import pyarrow.parquet as pq

        logger.info("loading_parquet", path=str(path))

        if path.is_dir():
            files = list(path.glob("*.parquet"))
        else:
            files = [path]

        count = 0
        for file in files:
            parquet_file = pq.ParquetFile(file)

            for batch in parquet_file.iter_batches(batch_size=10000):
                for record in batch.to_pylist():
                    # Filter by subreddit if specified
                    if subreddits:
                        subreddit = record.get("subreddit", "").lower()
                        if subreddit not in [s.lower() for s in subreddits]:
                            continue

                    yield record
                    count += 1

                    if max_records and count >= max_records:
                        logger.info("parquet_load_complete", count=count)
                        return

        logger.info("parquet_load_complete", count=count)


# Target subreddits for NER training (diverse entity types)
TARGET_SUBREDDITS = {
    # Political/News (PERSON, ORG, GPE, DATE)
    "political": ["politics", "news", "worldnews", "geopolitics", "uspolitics"],

    # Finance/Business (ORG, MONEY, PERCENT, DATE)
    "finance": ["investing", "stocks", "wallstreetbets", "business", "finance", "economics"],

    # Science/Tech (ORG, PRODUCT, PERSON)
    "science": ["science", "technology", "programming", "machinelearning", "artificial"],

    # General discussion (mixed entities)
    "general": ["askreddit", "todayilearned", "explainlikeimfive"],
}


def get_all_target_subreddits() -> list[str]:
    """Get flat list of all target subreddits."""
    subreddits = []
    for category_subs in TARGET_SUBREDDITS.values():
        subreddits.extend(category_subs)
    return subreddits
