"""Pattern Library for Plan-and-Execute mode.

Stores learned workflow patterns that enable upfront planning
when the agent encounters familiar goals.
"""

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class PatternStep:
    """A single step in a workflow pattern."""

    description: str
    """What this step accomplishes."""

    action_hint: str = ""
    """Type of action (click, fill, navigate, extract, wait)."""

    selector_hint: str = ""
    """Suggested selector or element description."""

    fallback_hint: str = ""
    """Alternative approach if primary fails."""


@dataclass
class WorkflowPattern:
    """A reusable workflow pattern for common goals."""

    name: str
    """Unique identifier for this pattern."""

    description: str
    """Human-readable description of what this pattern does."""

    goal_patterns: List[str]
    """Regex patterns that match goals this workflow handles."""

    steps: List[PatternStep]
    """Ordered list of steps to execute."""

    # Metadata
    domain: str = ""
    """Domain this pattern applies to (e.g., 'search', 'login', 'shopping')."""

    success_count: int = 0
    """Number of successful executions."""

    failure_count: int = 0
    """Number of failed executions."""

    last_used: str = ""
    """ISO timestamp of last use."""

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    """When this pattern was created."""

    # Tags for filtering
    tags: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.0
        return self.success_count / total

    def matches_goal(self, goal: str) -> float:
        """Check if this pattern matches a goal.

        Returns confidence score 0.0-1.0.
        """
        goal_lower = goal.lower()

        for pattern in self.goal_patterns:
            try:
                if re.search(pattern, goal_lower, re.IGNORECASE):
                    # Base confidence from pattern match
                    confidence = 0.7

                    # Boost for success rate
                    if self.success_count > 5:
                        confidence += 0.1 * min(self.success_rate, 1.0)

                    # Boost for recency
                    if self.last_used:
                        # Could add time-based boost here
                        pass

                    return min(confidence, 1.0)
            except re.error:
                logger.warning(f"Invalid regex pattern: {pattern}")
                continue

        return 0.0

    def record_success(self):
        """Record a successful execution."""
        self.success_count += 1
        self.last_used = datetime.now().isoformat()

    def record_failure(self):
        """Record a failed execution."""
        self.failure_count += 1
        self.last_used = datetime.now().isoformat()


@dataclass
class PatternMatch:
    """Result of pattern matching."""

    pattern: WorkflowPattern
    confidence: float
    matched_regex: str = ""


class PatternLibrary:
    """Library of learned workflow patterns.

    Provides plan-and-execute capability by storing and matching
    known workflow patterns.
    """

    def __init__(self, persist_path: Optional[Path] = None):
        """Initialize pattern library.

        Args:
            persist_path: Optional path to persist patterns
        """
        self.persist_path = persist_path
        self.patterns: Dict[str, WorkflowPattern] = {}

        # Initialize with built-in patterns
        self._init_builtin_patterns()

        # Load persisted patterns
        if persist_path and persist_path.exists():
            self._load()

    def _init_builtin_patterns(self):
        """Initialize built-in workflow patterns."""

        # Search and extract pattern
        self.add_pattern(WorkflowPattern(
            name="web_search",
            description="Search the web for information and extract results",
            goal_patterns=[
                r"search\s+(for|about)\s+.+",
                r"find\s+.+",  # Broader: "find practice questions", "find articles", etc.
                r"look\s+(up|for)\s+.+",
                r"research\s+.+",
                r"(information|info|details|materials|questions|articles)\s+(about|on|for)\s+.+",
            ],
            steps=[
                PatternStep(
                    description="Navigate to search engine or search page",
                    action_hint="navigate",
                    selector_hint="search input field",
                ),
                PatternStep(
                    description="Enter search query in search box",
                    action_hint="fill",
                    selector_hint="input[type='search'], input[name='q']",
                ),
                PatternStep(
                    description="Submit search and wait for results",
                    action_hint="submit",
                    selector_hint="Enter key or search button",
                ),
                PatternStep(
                    description="Click on first relevant result",
                    action_hint="click",
                    selector_hint="Search result link",
                ),
                PatternStep(
                    description="Extract key information from page",
                    action_hint="extract",
                    selector_hint="Main content area",
                ),
                PatternStep(
                    description="Navigate back and try another result",
                    action_hint="navigate",
                    selector_hint="Browser back button",
                ),
                PatternStep(
                    description="Extract more information for comparison",
                    action_hint="extract",
                    selector_hint="Main content area",
                ),
                PatternStep(
                    description="Summarize findings and complete",
                    action_hint="done",
                    selector_hint="N/A",
                ),
            ],
            domain="search",
            tags=["search", "research", "extract"],
        ))

        # Login pattern
        self.add_pattern(WorkflowPattern(
            name="login_form",
            description="Log into a website using credentials",
            goal_patterns=[
                r"log\s*in\s+to\s+.+",
                r"sign\s*in\s+to\s+.+",
                r"authenticate\s+(with|to)\s+.+",
            ],
            steps=[
                PatternStep(
                    description="Find and fill username/email field",
                    action_hint="fill",
                    selector_hint="input[type='email'], input[name='username']",
                ),
                PatternStep(
                    description="Find and fill password field",
                    action_hint="fill",
                    selector_hint="input[type='password']",
                ),
                PatternStep(
                    description="Click login/submit button",
                    action_hint="click",
                    selector_hint="button[type='submit'], button:has-text('Login')",
                ),
                PatternStep(
                    description="Wait for login confirmation",
                    action_hint="wait",
                    selector_hint="Dashboard or profile element",
                ),
            ],
            domain="auth",
            tags=["login", "auth", "credentials"],
        ))

        # Form fill pattern
        self.add_pattern(WorkflowPattern(
            name="fill_form",
            description="Fill out a form with provided information",
            goal_patterns=[
                r"fill\s+(out|in)\s+.+\s+form",
                r"complete\s+.+\s+form",
                r"submit\s+.+\s+form",
            ],
            steps=[
                PatternStep(
                    description="Identify form fields",
                    action_hint="observe",
                    selector_hint="form elements",
                ),
                PatternStep(
                    description="Fill required text fields",
                    action_hint="fill",
                    selector_hint="input[required], input:not([type='submit'])",
                ),
                PatternStep(
                    description="Handle dropdowns/selects",
                    action_hint="select",
                    selector_hint="select elements",
                ),
                PatternStep(
                    description="Check any required checkboxes",
                    action_hint="check",
                    selector_hint="input[type='checkbox']",
                ),
                PatternStep(
                    description="Submit form",
                    action_hint="click",
                    selector_hint="button[type='submit']",
                ),
                PatternStep(
                    description="Verify submission success",
                    action_hint="wait",
                    selector_hint="Success message or confirmation",
                ),
            ],
            domain="forms",
            tags=["form", "input", "submit"],
        ))

        # Navigate and extract pattern
        self.add_pattern(WorkflowPattern(
            name="navigate_extract",
            description="Navigate to a URL and extract specific information",
            goal_patterns=[
                r"go\s+to\s+.+\s+and\s+.+",
                r"visit\s+.+\s+and\s+.+",
                r"open\s+.+\s+and\s+.+",
                r"navigate\s+to\s+.+",
            ],
            steps=[
                PatternStep(
                    description="Navigate to target URL",
                    action_hint="navigate",
                    selector_hint="URL from goal",
                ),
                PatternStep(
                    description="Wait for page to load",
                    action_hint="wait",
                    selector_hint="Main content element",
                ),
                PatternStep(
                    description="Extract requested information",
                    action_hint="extract",
                    selector_hint="Relevant content elements",
                ),
                PatternStep(
                    description="Format and return results",
                    action_hint="done",
                    selector_hint="N/A",
                ),
            ],
            domain="navigation",
            tags=["navigate", "extract", "visit"],
        ))

        # Shopping pattern
        self.add_pattern(WorkflowPattern(
            name="product_search",
            description="Search for products on shopping sites",
            goal_patterns=[
                r"(find|search|look\s+for)\s+(product|item|.+)\s+on\s+(amazon|ebay|walmart)",
                r"shop\s+for\s+.+",
                r"buy\s+.+",
            ],
            steps=[
                PatternStep(
                    description="Navigate to shopping site",
                    action_hint="navigate",
                    selector_hint="Shopping site URL",
                ),
                PatternStep(
                    description="Find search box",
                    action_hint="fill",
                    selector_hint="input[type='search'], #twotabsearchtextbox",
                ),
                PatternStep(
                    description="Enter product search",
                    action_hint="fill",
                    selector_hint="Product name from goal",
                ),
                PatternStep(
                    description="Submit search",
                    action_hint="submit",
                    selector_hint="Search button or Enter",
                ),
                PatternStep(
                    description="Review search results",
                    action_hint="observe",
                    selector_hint="Product listing",
                ),
                PatternStep(
                    description="Click on relevant product",
                    action_hint="click",
                    selector_hint="Product link",
                ),
                PatternStep(
                    description="Extract product details",
                    action_hint="extract",
                    selector_hint="Product info (price, title, reviews)",
                ),
            ],
            domain="shopping",
            tags=["shopping", "product", "ecommerce"],
        ))

    def add_pattern(self, pattern: WorkflowPattern):
        """Add a pattern to the library."""
        self.patterns[pattern.name] = pattern
        logger.debug(f"Added pattern: {pattern.name}")

    def find_match(self, goal: str) -> Optional[PatternMatch]:
        """Find the best matching pattern for a goal.

        Args:
            goal: The goal to match

        Returns:
            PatternMatch if found, None otherwise
        """
        best_match: Optional[PatternMatch] = None
        best_confidence = 0.0

        for name, pattern in self.patterns.items():
            confidence = pattern.matches_goal(goal)
            if confidence > best_confidence:
                best_confidence = confidence
                best_match = PatternMatch(
                    pattern=pattern,
                    confidence=confidence,
                )

        return best_match

    def get_pattern(self, name: str) -> Optional[WorkflowPattern]:
        """Get a pattern by name."""
        return self.patterns.get(name)

    def list_patterns(self, domain: Optional[str] = None) -> List[WorkflowPattern]:
        """List all patterns, optionally filtered by domain."""
        patterns = list(self.patterns.values())
        if domain:
            patterns = [p for p in patterns if p.domain == domain]
        return sorted(patterns, key=lambda p: p.success_rate, reverse=True)

    def record_execution(self, pattern_name: str, success: bool):
        """Record the result of executing a pattern."""
        pattern = self.patterns.get(pattern_name)
        if pattern:
            if success:
                pattern.record_success()
            else:
                pattern.record_failure()

            if self.persist_path:
                self._save()

    def learn_pattern(
        self,
        name: str,
        description: str,
        goal: str,
        steps: List[Dict[str, str]],
        domain: str = "learned",
    ) -> WorkflowPattern:
        """Learn a new pattern from a successful session.

        Args:
            name: Unique pattern name
            description: What this pattern does
            goal: The goal that was achieved (used to create regex)
            steps: List of step dicts with description/action_hint
            domain: Pattern domain

        Returns:
            The created pattern
        """
        # Create goal pattern from the successful goal
        # Extract key terms and create flexible regex
        words = goal.lower().split()
        key_words = [w for w in words if len(w) > 3 and w not in ("the", "and", "for", "with")]

        if key_words:
            goal_pattern = r".*".join(re.escape(w) for w in key_words[:3])
        else:
            goal_pattern = re.escape(goal.lower()[:30])

        pattern = WorkflowPattern(
            name=name,
            description=description,
            goal_patterns=[goal_pattern],
            steps=[
                PatternStep(
                    description=s.get("description", ""),
                    action_hint=s.get("action_hint", ""),
                    selector_hint=s.get("selector_hint", ""),
                )
                for s in steps
            ],
            domain=domain,
            tags=["learned"],
            success_count=1,  # Start with 1 success (the learning session)
        )

        self.add_pattern(pattern)

        if self.persist_path:
            self._save()

        logger.info(f"Learned new pattern: {name}")
        return pattern

    def _save(self):
        """Persist patterns to file."""
        if not self.persist_path:
            return

        data = {
            "version": "1.0",
            "patterns": {
                name: {
                    "name": p.name,
                    "description": p.description,
                    "goal_patterns": p.goal_patterns,
                    "steps": [
                        {
                            "description": s.description,
                            "action_hint": s.action_hint,
                            "selector_hint": s.selector_hint,
                            "fallback_hint": s.fallback_hint,
                        }
                        for s in p.steps
                    ],
                    "domain": p.domain,
                    "success_count": p.success_count,
                    "failure_count": p.failure_count,
                    "last_used": p.last_used,
                    "created_at": p.created_at,
                    "tags": p.tags,
                }
                for name, p in self.patterns.items()
            }
        }

        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(json.dumps(data, indent=2))
            logger.debug(f"Saved {len(self.patterns)} patterns")
        except Exception as e:
            logger.warning(f"Failed to save patterns: {e}")

    def _load(self):
        """Load patterns from file."""
        if not self.persist_path or not self.persist_path.exists():
            return

        try:
            data = json.loads(self.persist_path.read_text())

            for name, pdata in data.get("patterns", {}).items():
                # Skip built-in patterns (they're already initialized)
                if name in self.patterns and "learned" not in pdata.get("tags", []):
                    # But update stats from persisted data
                    self.patterns[name].success_count = pdata.get("success_count", 0)
                    self.patterns[name].failure_count = pdata.get("failure_count", 0)
                    self.patterns[name].last_used = pdata.get("last_used", "")
                    continue

                # Load learned patterns
                pattern = WorkflowPattern(
                    name=pdata["name"],
                    description=pdata["description"],
                    goal_patterns=pdata["goal_patterns"],
                    steps=[
                        PatternStep(
                            description=s["description"],
                            action_hint=s.get("action_hint", ""),
                            selector_hint=s.get("selector_hint", ""),
                            fallback_hint=s.get("fallback_hint", ""),
                        )
                        for s in pdata.get("steps", [])
                    ],
                    domain=pdata.get("domain", ""),
                    success_count=pdata.get("success_count", 0),
                    failure_count=pdata.get("failure_count", 0),
                    last_used=pdata.get("last_used", ""),
                    created_at=pdata.get("created_at", ""),
                    tags=pdata.get("tags", []),
                )
                self.patterns[name] = pattern

            logger.info(f"Loaded {len(self.patterns)} patterns")

        except Exception as e:
            logger.warning(f"Failed to load patterns: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get library statistics."""
        patterns = list(self.patterns.values())
        return {
            "total_patterns": len(patterns),
            "domains": list(set(p.domain for p in patterns if p.domain)),
            "total_executions": sum(p.success_count + p.failure_count for p in patterns),
            "overall_success_rate": (
                sum(p.success_count for p in patterns) /
                max(1, sum(p.success_count + p.failure_count for p in patterns))
            ),
            "most_used": sorted(
                [(p.name, p.success_count + p.failure_count) for p in patterns],
                key=lambda x: x[1],
                reverse=True
            )[:5],
        }
