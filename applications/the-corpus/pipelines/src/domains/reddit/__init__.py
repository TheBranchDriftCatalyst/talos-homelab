"""
Reddit domain (Pushshift archives).

ETL pipeline for discourse data:
- Submissions (posts)
- Comments
"""

from domains.reddit.entities import Submission, Comment

__all__ = ["Submission", "Comment"]
