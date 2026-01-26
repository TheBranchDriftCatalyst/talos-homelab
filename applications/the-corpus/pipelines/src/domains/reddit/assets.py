"""
Reddit Domain Dagster Assets

ETL pipeline assets for Reddit/Pushshift data:
1. Submission extraction from HuggingFace
2. Comment extraction (optional)
3. Document transformation for NER training
"""

from datetime import datetime

from dagster import (
    AssetExecutionContext,
    MetadataValue,
    Output,
    asset,
)

from corpus_core import Document, get_env_int

from .loader import PushshiftLoader, TARGET_SUBREDDITS, get_all_target_subreddits
from .entities import Submission, Comment


# ============================================================================
# Raw Data Extraction Assets
# ============================================================================

@asset(
    group_name="reddit",
    description="Extract Reddit submissions from Pushshift/HuggingFace",
    compute_kind="extract",
)
def reddit_submissions(context: AssetExecutionContext) -> Output[list[Submission]]:
    """
    Extract Reddit submissions from Pushshift archives.

    Uses HuggingFace datasets for streaming access.
    """
    max_submissions = get_env_int(
        "MAX_REDDIT_SUBMISSIONS", 10000,
        description="Maximum Reddit submissions to extract",
        domain="reddit",
    )
    target_subreddits = get_all_target_subreddits()

    loader = PushshiftLoader()
    submissions = []

    try:
        # Try HuggingFace first
        context.log.info("Loading from HuggingFace datasets...")

        for record in loader.load_from_huggingface(
            dataset="HuggingFaceGECLM/REDDIT_comments",
            subreddits=target_subreddits,
            max_records=max_submissions,
        ):
            # Filter for submissions (not comments)
            if "title" in record:
                submission = Submission.from_pushshift(record)

                # Skip deleted/removed content
                if submission.author == "[deleted]":
                    continue
                if submission.selftext in ("[deleted]", "[removed]"):
                    submission.selftext = ""

                # Skip very short posts
                if submission.content_length < 50:
                    continue

                submissions.append(submission)

                if len(submissions) % 1000 == 0:
                    context.log.info(f"Loaded {len(submissions)} submissions...")

    except Exception as e:
        context.log.warning(f"HuggingFace loading failed: {e}")
        context.log.info("Creating sample submissions for development...")

        # Create sample submissions for development
        sample_subreddits = ["politics", "news", "investing"]
        for i, subreddit in enumerate(sample_subreddits):
            for j in range(10):
                submission = Submission(
                    id=f"sample_{subreddit}_{j}",
                    subreddit=subreddit,
                    title=f"Sample {subreddit} post {j}: Discussion about current events",
                    selftext=f"This is sample content for {subreddit}. "
                             f"It discusses various topics related to the subreddit theme.",
                    author=f"user_{j}",
                    created_utc=datetime.utcnow(),
                    score=100 * (j + 1),
                    num_comments=50 * (j + 1),
                )
                submissions.append(submission)

    context.log.info(f"Extracted {len(submissions)} submissions")

    # Calculate stats
    by_subreddit = {}
    for s in submissions:
        by_subreddit[s.subreddit] = by_subreddit.get(s.subreddit, 0) + 1

    return Output(
        submissions,
        metadata={
            "count": len(submissions),
            "subreddits": len(by_subreddit),
            "top_subreddits": MetadataValue.json(
                dict(sorted(by_subreddit.items(), key=lambda x: -x[1])[:10])
            ),
            "avg_score": sum(s.score for s in submissions) // max(len(submissions), 1),
            "avg_length": sum(s.content_length for s in submissions) // max(len(submissions), 1),
        },
    )


@asset(
    group_name="reddit",
    description="Extract Reddit comments from Pushshift/HuggingFace",
    compute_kind="extract",
)
def reddit_comments(
    context: AssetExecutionContext,
    reddit_submissions: list[Submission],
) -> Output[list[Comment]]:
    """
    Extract Reddit comments related to submissions.

    Note: Full comment extraction is expensive - this asset provides
    a sample for development. Production would use streaming.
    """
    max_comments = get_env_int(
        "MAX_REDDIT_COMMENTS", 5000,
        description="Maximum Reddit comments to extract",
        domain="reddit",
    )
    target_subreddits = [s.subreddit for s in reddit_submissions]

    loader = PushshiftLoader()
    comments = []

    try:
        context.log.info("Loading comments from HuggingFace datasets...")

        for record in loader.load_from_huggingface(
            dataset="HuggingFaceGECLM/REDDIT_comments",
            subreddits=target_subreddits,
            max_records=max_comments,
        ):
            # Filter for comments (not submissions)
            if "body" in record and "title" not in record:
                comment = Comment.from_pushshift(record)

                # Skip deleted/removed content
                if comment.author == "[deleted]":
                    continue
                if comment.body in ("[deleted]", "[removed]"):
                    continue

                # Skip very short comments
                if comment.content_length < 20:
                    continue

                comments.append(comment)

                if len(comments) % 1000 == 0:
                    context.log.info(f"Loaded {len(comments)} comments...")

    except Exception as e:
        context.log.warning(f"Comment loading failed: {e}")
        context.log.info("Creating sample comments for development...")

        # Create sample comments
        for submission in reddit_submissions[:10]:
            for j in range(5):
                comment = Comment(
                    id=f"comment_{submission.id}_{j}",
                    parent_id=f"t3_{submission.id}",
                    link_id=f"t3_{submission.id}",
                    subreddit=submission.subreddit,
                    body=f"This is a sample comment discussing {submission.title[:50]}...",
                    author=f"commenter_{j}",
                    created_utc=submission.created_utc,
                    score=50 * (j + 1),
                )
                comments.append(comment)

    context.log.info(f"Extracted {len(comments)} comments")

    return Output(
        comments,
        metadata={
            "count": len(comments),
            "top_level_comments": len([c for c in comments if c.is_top_level]),
            "avg_score": sum(c.score for c in comments) // max(len(comments), 1),
            "avg_length": sum(c.content_length for c in comments) // max(len(comments), 1),
        },
    )


# ============================================================================
# Document Transformation Asset
# ============================================================================

@asset(
    group_name="reddit",
    description="Transform Reddit data into training documents",
    compute_kind="transform",
)
def reddit_documents(
    context: AssetExecutionContext,
    reddit_submissions: list[Submission],
    reddit_comments: list[Comment],
) -> Output[list[Document]]:
    """
    Transform Reddit data into training documents.

    Creates documents suitable for NER training focusing on:
    - Political entities (PERSON, ORG, GPE)
    - Financial entities (ORG, MONEY, PERCENT)
    - General named entities
    """
    documents = []

    # Categorize subreddits
    subreddit_categories = {}
    for category, subs in TARGET_SUBREDDITS.items():
        for sub in subs:
            subreddit_categories[sub.lower()] = category

    # Transform submissions
    for submission in reddit_submissions:
        category = subreddit_categories.get(submission.subreddit.lower(), "general")

        doc = Document(
            id=f"reddit-submission-{submission.id}",
            title=submission.title,
            content=submission.full_text,
            source="reddit.com",
            source_url=f"https://reddit.com{submission.permalink}" if submission.permalink else None,
            document_type="reddit_submission",
            domain="reddit",
            entity_type="Submission",
            metadata={
                "subreddit": submission.subreddit,
                "category": category,
                "author": submission.author,
                "score": submission.score,
                "num_comments": submission.num_comments,
                "is_self": submission.is_self,
                "created_utc": submission.created_utc.isoformat(),
            },
        )
        documents.append(doc)

    # Transform comments (sample - combine with parent context)
    # Build submission lookup for context
    submission_lookup = {s.id: s for s in reddit_submissions}

    for comment in reddit_comments:
        # Try to get parent submission for context
        link_id = comment.link_id.replace("t3_", "")
        parent_submission = submission_lookup.get(link_id)

        category = subreddit_categories.get(comment.subreddit.lower(), "general")

        # Build content with context
        if parent_submission:
            content = f"[In response to: {parent_submission.title}]\n\n{comment.body}"
        else:
            content = comment.body

        doc = Document(
            id=f"reddit-comment-{comment.id}",
            title=f"Comment in r/{comment.subreddit}",
            content=content,
            source="reddit.com",
            source_url=f"https://reddit.com{comment.permalink}" if comment.permalink else None,
            document_type="reddit_comment",
            domain="reddit",
            entity_type="Comment",
            metadata={
                "subreddit": comment.subreddit,
                "category": category,
                "author": comment.author,
                "score": comment.score,
                "is_top_level": comment.is_top_level,
                "created_utc": comment.created_utc.isoformat(),
            },
        )
        documents.append(doc)

    context.log.info(f"Created {len(documents)} training documents")

    # Stats by category
    by_category = {}
    for doc in documents:
        cat = doc.metadata.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1

    return Output(
        documents,
        metadata={
            "total_documents": len(documents),
            "submissions": len(reddit_submissions),
            "comments": len(reddit_comments),
            "by_category": MetadataValue.json(by_category),
            "avg_content_length": sum(len(d.content) for d in documents) // max(len(documents), 1),
        },
    )
