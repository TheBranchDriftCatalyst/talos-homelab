"""
Reddit Domain Entities

Pydantic models for Submissions (posts) and Comments.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from corpus_core.utils import parse_timestamp


class Submission(BaseModel):
    """Reddit submission (post) entity."""

    # Identifiers
    id: str = Field(description="Reddit submission ID")
    subreddit: str = Field(description="Subreddit name")

    # Content
    title: str = Field(description="Post title")
    selftext: str = Field(default="", description="Post body text (for text posts)")
    url: str | None = Field(default=None, description="Link URL (for link posts)")

    # Author
    author: str = Field(description="Author username")
    author_flair_text: str | None = Field(default=None, description="Author flair")

    # Metadata
    created_utc: datetime = Field(description="Post creation timestamp")
    score: int = Field(default=0, description="Net upvotes")
    upvote_ratio: float | None = Field(default=None, description="Upvote percentage")
    num_comments: int = Field(default=0, description="Number of comments")

    # Flags
    is_self: bool = Field(default=True, description="True if text post")
    over_18: bool = Field(default=False, description="NSFW flag")
    spoiler: bool = Field(default=False, description="Spoiler flag")
    stickied: bool = Field(default=False, description="Pinned post")

    # Flair/Tags
    link_flair_text: str | None = Field(default=None, description="Post flair")

    # Source
    permalink: str | None = Field(default=None, description="Reddit permalink")

    @classmethod
    def from_pushshift(cls, data: dict[str, Any]) -> "Submission":
        """Create Submission from Pushshift record."""
        created_dt = parse_timestamp(data.get("created_utc")) or datetime.utcnow()

        return cls(
            id=data.get("id", ""),
            subreddit=data.get("subreddit", ""),
            title=data.get("title", ""),
            selftext=data.get("selftext", "") or "",
            url=data.get("url"),
            author=data.get("author", "[deleted]"),
            author_flair_text=data.get("author_flair_text"),
            created_utc=created_dt,
            score=data.get("score", 0),
            upvote_ratio=data.get("upvote_ratio"),
            num_comments=data.get("num_comments", 0),
            is_self=data.get("is_self", True),
            over_18=data.get("over_18", False),
            spoiler=data.get("spoiler", False),
            stickied=data.get("stickied", False),
            link_flair_text=data.get("link_flair_text"),
            permalink=data.get("permalink"),
        )

    @property
    def full_text(self) -> str:
        """Get full text content (title + body)."""
        if self.selftext:
            return f"{self.title}\n\n{self.selftext}"
        return self.title

    @property
    def content_length(self) -> int:
        """Get total content length."""
        return len(self.full_text)


class Comment(BaseModel):
    """Reddit comment entity."""

    # Identifiers
    id: str = Field(description="Reddit comment ID")
    parent_id: str = Field(description="Parent comment/post ID (t1_ for comment, t3_ for post)")
    link_id: str = Field(description="Parent submission ID")
    subreddit: str = Field(description="Subreddit name")

    # Content
    body: str = Field(description="Comment text")

    # Author
    author: str = Field(description="Author username")
    author_flair_text: str | None = Field(default=None, description="Author flair")

    # Metadata
    created_utc: datetime = Field(description="Comment creation timestamp")
    score: int = Field(default=0, description="Net upvotes")

    # Hierarchy
    depth: int | None = Field(default=None, description="Comment depth (0 = top-level)")

    # Flags
    stickied: bool = Field(default=False, description="Pinned comment")
    distinguished: str | None = Field(default=None, description="Mod/admin distinction")

    # Source
    permalink: str | None = Field(default=None, description="Reddit permalink")

    @classmethod
    def from_pushshift(cls, data: dict[str, Any]) -> "Comment":
        """Create Comment from Pushshift record."""
        created_dt = parse_timestamp(data.get("created_utc")) or datetime.utcnow()

        return cls(
            id=data.get("id", ""),
            parent_id=data.get("parent_id", ""),
            link_id=data.get("link_id", ""),
            subreddit=data.get("subreddit", ""),
            body=data.get("body", "") or "",
            author=data.get("author", "[deleted]"),
            author_flair_text=data.get("author_flair_text"),
            created_utc=created_dt,
            score=data.get("score", 0),
            depth=data.get("depth"),
            stickied=data.get("stickied", False),
            distinguished=data.get("distinguished"),
            permalink=data.get("permalink"),
        )

    @property
    def is_top_level(self) -> bool:
        """Check if this is a top-level comment."""
        return self.parent_id.startswith("t3_")

    @property
    def content_length(self) -> int:
        """Get content length."""
        return len(self.body)
