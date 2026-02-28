"""Progressive memory/state management for Poisonarr agents."""

import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


def extract_hour(timestamp: str) -> Optional[int]:
    """Extract hour from ISO timestamp."""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return dt.hour
    except Exception:
        return None


def categorize_site(domain: str) -> str:
    """Categorize a domain into a site type."""
    domain = domain.lower()

    categories = {
        "news": ["cnn", "bbc", "reuters", "nytimes", "guardian", "news", "washingtonpost", "npr"],
        "tech": ["github", "stackoverflow", "hackernews", "ycombinator", "techcrunch", "wired", "ars"],
        "shopping": ["amazon", "ebay", "walmart", "target", "bestbuy", "etsy", "shop"],
        "social": ["reddit", "twitter", "facebook", "instagram", "linkedin", "tiktok"],
        "video": ["youtube", "vimeo", "twitch", "netflix", "hulu"],
        "search": ["google", "bing", "duckduckgo", "searx", "localhost"],
        "reference": ["wikipedia", "wiki", "docs", "documentation"],
    }

    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword in domain:
                return category

    return "other"


@dataclass
class SessionMemory:
    """Memory of a single browsing session."""
    timestamp: str
    persona: str
    goal: str
    success: bool
    summary: str
    sites_visited: List[str] = field(default_factory=list)
    actions_taken: int = 0


@dataclass
class AgentMemory:
    """Long-term memory for an agent with progressive summarization."""

    agent_id: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Recent sessions (full detail, last N sessions)
    recent_sessions: List[SessionMemory] = field(default_factory=list)

    # Compressed summary of older sessions
    historical_summary: str = ""

    # Stats
    total_sessions: int = 0
    successful_sessions: int = 0
    favorite_sites: Dict[str, int] = field(default_factory=dict)  # site -> visit count

    # Behavioral patterns learned
    patterns: List[str] = field(default_factory=list)  # e.g., "prefers news sites in morning"

    # Maximum recent sessions before summarization
    max_recent: int = 10

    def add_session(self, session: SessionMemory):
        """Add a session and trigger summarization if needed."""
        self.recent_sessions.append(session)
        self.total_sessions += 1
        if session.success:
            self.successful_sessions += 1

        # Track site visits
        for site in session.sites_visited:
            self.favorite_sites[site] = self.favorite_sites.get(site, 0) + 1

        # Trigger summarization if we have too many recent sessions
        if len(self.recent_sessions) > self.max_recent:
            self._compress_old_sessions()

    def _compress_old_sessions(self):
        """Compress older sessions into historical summary."""
        # Keep last 5 sessions as recent
        to_compress = self.recent_sessions[:-5]
        self.recent_sessions = self.recent_sessions[-5:]

        if not to_compress:
            return

        # Build summary text
        summaries = []
        for s in to_compress:
            summaries.append(f"- {s.persona}: {s.goal} ({'success' if s.success else 'failed'})")

        new_summary = "\n".join(summaries)

        if self.historical_summary:
            self.historical_summary = f"{self.historical_summary}\n\n{new_summary}"
        else:
            self.historical_summary = new_summary

        # Keep summary under reasonable size (truncate oldest if needed)
        max_summary_chars = 5000
        if len(self.historical_summary) > max_summary_chars:
            self.historical_summary = "..." + self.historical_summary[-max_summary_chars:]

        logger.info(f"Compressed {len(to_compress)} sessions into historical summary")

    def get_context_for_llm(self) -> str:
        """Get a context string suitable for LLM prompts."""
        parts = []

        if self.historical_summary:
            parts.append(f"## Browsing History Summary\n{self.historical_summary[:1000]}")

        if self.recent_sessions:
            recent_text = "\n".join([
                f"- {s.persona}: {s.goal} ({s.summary[:50]})"
                for s in self.recent_sessions[-3:]
            ])
            parts.append(f"## Recent Sessions\n{recent_text}")

        if self.favorite_sites:
            top_sites = sorted(self.favorite_sites.items(), key=lambda x: -x[1])[:5]
            sites_text = ", ".join([f"{site}({count})" for site, count in top_sites])
            parts.append(f"## Frequently Visited: {sites_text}")

        if self.patterns:
            parts.append(f"## Behavioral Patterns\n" + "\n".join(f"- {p}" for p in self.patterns[:3]))

        return "\n\n".join(parts) if parts else "No browsing history yet."


class MemoryManager:
    """Manages persistent agent memory."""

    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize memory manager.

        Args:
            storage_dir: Directory to store memory files.
                        If None, memory is not persisted.
        """
        self.storage_dir = Path(storage_dir) if storage_dir else None
        self._memories: Dict[str, AgentMemory] = {}

        if self.storage_dir:
            self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_memory_path(self, agent_id: str) -> Optional[Path]:
        """Get path for agent's memory file."""
        if not self.storage_dir:
            return None
        return self.storage_dir / f"{agent_id}_memory.json"

    def get_memory(self, agent_id: str) -> AgentMemory:
        """Get or create memory for an agent."""
        if agent_id in self._memories:
            return self._memories[agent_id]

        # Try loading from disk
        memory_path = self._get_memory_path(agent_id)
        if memory_path and memory_path.exists():
            try:
                data = json.loads(memory_path.read_text())
                # Reconstruct from dict
                memory = AgentMemory(
                    agent_id=data.get("agent_id", agent_id),
                    created_at=data.get("created_at", datetime.now().isoformat()),
                    recent_sessions=[
                        SessionMemory(**s) for s in data.get("recent_sessions", [])
                    ],
                    historical_summary=data.get("historical_summary", ""),
                    total_sessions=data.get("total_sessions", 0),
                    successful_sessions=data.get("successful_sessions", 0),
                    favorite_sites=data.get("favorite_sites", {}),
                    patterns=data.get("patterns", []),
                )
                logger.info(f"Loaded memory for {agent_id}: {memory.total_sessions} sessions")
                self._memories[agent_id] = memory
                return memory
            except Exception as e:
                logger.warning(f"Failed to load memory for {agent_id}: {e}")

        # Create new memory
        memory = AgentMemory(agent_id=agent_id)
        self._memories[agent_id] = memory
        return memory

    def save_memory(self, agent_id: str):
        """Save agent memory to disk."""
        if agent_id not in self._memories:
            return

        memory_path = self._get_memory_path(agent_id)
        if not memory_path:
            return

        memory = self._memories[agent_id]
        try:
            # Convert to dict
            data = {
                "agent_id": memory.agent_id,
                "created_at": memory.created_at,
                "recent_sessions": [asdict(s) for s in memory.recent_sessions],
                "historical_summary": memory.historical_summary,
                "total_sessions": memory.total_sessions,
                "successful_sessions": memory.successful_sessions,
                "favorite_sites": memory.favorite_sites,
                "patterns": memory.patterns,
            }
            memory_path.write_text(json.dumps(data, indent=2))
            logger.debug(f"Saved memory for {agent_id}")
        except Exception as e:
            logger.error(f"Failed to save memory for {agent_id}: {e}")

    def record_session(
        self,
        agent_id: str,
        persona: str,
        goal: str,
        success: bool,
        summary: str,
        sites_visited: List[str] = None,
        actions_taken: int = 0,
    ):
        """Record a completed session."""
        memory = self.get_memory(agent_id)
        session = SessionMemory(
            timestamp=datetime.now().isoformat(),
            persona=persona,
            goal=goal,
            success=success,
            summary=summary,
            sites_visited=sites_visited or [],
            actions_taken=actions_taken,
        )
        memory.add_session(session)

        # Learn patterns every 10 sessions
        if memory.total_sessions % 10 == 0:
            self.learn_patterns(agent_id)

        self.save_memory(agent_id)

    def learn_patterns(self, agent_id: str):
        """Analyze sessions and learn behavioral patterns.

        Best practice: Extract insights from session history.
        """
        memory = self.get_memory(agent_id)

        if memory.total_sessions < 5:
            return  # Need enough data

        patterns = []
        sessions = memory.recent_sessions

        # Pattern 1: Time-of-day preferences
        hours = [extract_hour(s.timestamp) for s in sessions]
        hours = [h for h in hours if h is not None]
        if hours:
            hour_counts = Counter(hours)
            most_common_hour, count = hour_counts.most_common(1)[0]
            if count >= len(sessions) * 0.3:  # 30%+ in same hour
                if 6 <= most_common_hour < 12:
                    patterns.append("Most active in morning hours")
                elif 12 <= most_common_hour < 18:
                    patterns.append("Most active in afternoon hours")
                elif 18 <= most_common_hour < 22:
                    patterns.append("Most active in evening hours")
                else:
                    patterns.append("Most active in late night hours")

        # Pattern 2: Site category preferences
        all_sites = []
        for s in sessions:
            all_sites.extend(s.sites_visited)

        if all_sites:
            categories = [categorize_site(site) for site in all_sites]
            cat_counts = Counter(categories)
            top_cats = cat_counts.most_common(2)
            if top_cats:
                cat1, count1 = top_cats[0]
                if cat1 != "other" and cat1 != "search":
                    patterns.append(f"Prefers {cat1} sites")
                if len(top_cats) > 1:
                    cat2, count2 = top_cats[1]
                    if cat2 != "other" and cat2 != "search" and count2 >= count1 * 0.5:
                        patterns.append(f"Also frequently visits {cat2} sites")

        # Pattern 3: Success rate analysis
        if memory.total_sessions >= 10:
            success_rate = memory.successful_sessions / memory.total_sessions
            if success_rate >= 0.8:
                patterns.append("High success rate (80%+) - reliable browsing patterns")
            elif success_rate <= 0.4:
                patterns.append("Low success rate - may need goal refinement")

        # Pattern 4: Session length patterns
        action_counts = [s.actions_taken for s in sessions if s.actions_taken > 0]
        if action_counts:
            avg_actions = sum(action_counts) / len(action_counts)
            if avg_actions < 5:
                patterns.append("Quick browsing sessions (few actions)")
            elif avg_actions > 12:
                patterns.append("Deep browsing sessions (many actions)")

        # Pattern 5: Favorite site loyalty
        if memory.favorite_sites:
            sorted_sites = sorted(memory.favorite_sites.items(), key=lambda x: -x[1])
            if sorted_sites:
                top_site, top_count = sorted_sites[0]
                total_visits = sum(memory.favorite_sites.values())
                if top_count >= total_visits * 0.3:
                    patterns.append(f"Frequently returns to {top_site}")

        # Update patterns (keep unique, max 8)
        existing = set(memory.patterns)
        for p in patterns:
            if p not in existing:
                memory.patterns.append(p)

        # Trim to max 8 patterns (keep most recent)
        if len(memory.patterns) > 8:
            memory.patterns = memory.patterns[-8:]

        if patterns:
            logger.info(f"Learned {len(patterns)} new patterns for {agent_id}")
        self.save_memory(agent_id)
