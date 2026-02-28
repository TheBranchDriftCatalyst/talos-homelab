"""Playwright Error Tracker - Learn from code execution failures.

Collects errors from generated Playwright code and builds a memory of:
- Common mistakes and their fixes
- Patterns that work vs fail
- Context-specific solutions

This memory is used to improve the code generation prompt over time.
"""

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class CodeError:
    """A single code execution error."""
    timestamp: str
    error_type: str  # e.g., "TypeError", "TimeoutError"
    error_message: str
    code_snippet: str  # The code that failed
    fix_applied: Optional[str] = None  # Code that fixed it (if any)
    page_url: str = ""
    selector: str = ""  # Extracted selector if relevant

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class ErrorPattern:
    """Aggregated pattern of similar errors."""
    error_type: str
    pattern: str  # Regex or key pattern
    description: str
    count: int = 0
    examples: List[str] = field(default_factory=list)
    fixes: List[str] = field(default_factory=list)
    last_seen: str = ""

    def add_occurrence(self, error: CodeError):
        """Record another occurrence of this pattern."""
        self.count += 1
        self.last_seen = error.timestamp
        if error.code_snippet and len(self.examples) < 3:
            self.examples.append(error.code_snippet[:200])
        if error.fix_applied and error.fix_applied not in self.fixes:
            self.fixes.append(error.fix_applied[:200])


class PlaywrightErrorTracker:
    """Track and learn from Playwright code execution errors.

    Maintains a memory of errors and their fixes to improve
    future code generation.
    """

    # Known error patterns to track
    KNOWN_PATTERNS = {
        "locator_await": {
            "pattern": r"object Locator can't be used in 'await' expression",
            "description": "Awaiting locator without method call",
            "fix": "Don't await page.locator() - it returns a sync Locator. Await methods on it like .click()"
        },
        "missing_await": {
            "pattern": r"coroutine.*was never awaited|'>' not supported between.*coroutine",
            "description": "Missing await on async method",
            "fix": "Add 'await' before async methods like .count(), .click(), .fill()"
        },
        "selector_timeout": {
            "pattern": r"Timeout \d+ms exceeded.*waiting for",
            "description": "Element not found within timeout",
            "fix": "Try alternative selectors or wait for page to load first"
        },
        "missing_argument": {
            "pattern": r"missing \d+ required positional argument",
            "description": "Method called without required arguments",
            "fix": "Check method signature - page.press() needs (selector, key)"
        },
        "element_not_found": {
            "pattern": r"No element matches|Element not found",
            "description": "Selector didn't match any elements",
            "fix": "Verify selector exists on page, try get_by_* methods"
        },
        "execution_timeout": {
            "pattern": r"Code execution timeout|execution timeout",
            "description": "Code took too long to execute",
            "fix": "NEVER use wait_for_load_state('networkidle') - use page.wait_for_timeout(2000) or wait_for_selector() instead"
        },
        "networkidle_timeout": {
            "pattern": r"wait_for_load_state.*networkidle|networkidle",
            "description": "Using networkidle which times out",
            "fix": "REMOVE wait_for_load_state('networkidle') completely! Use page.wait_for_timeout(2000) instead"
        },
        "undefined_import": {
            "pattern": r"name '(\w+)' is not defined",
            "description": "Using undefined variable or import",
            "fix": "Only use 'page' variable - don't import or use playwright module directly. Use built-in try/except for errors."
        },
        "strict_mode_violation": {
            "pattern": r"strict mode violation|resolved to \d+ elements",
            "description": "Selector matched multiple elements in strict mode",
            "fix": "Use .first, .nth(0), or more specific selector to match single element"
        },
        "wrong_site_selector": {
            "pattern": r"Google Custom Search|google\.com|bing\.com|duckduckgo",
            "description": "Using selectors for wrong site (probably on SearXNG)",
            "fix": "Check the page URL/title! On SearXNG use: get_by_placeholder('Search for...') for input, get_by_role('button', name='search') for submit"
        },
        "searxng_selectors": {
            "pattern": r"localhost:8888|searxng|SearXNG",
            "description": "SearXNG search engine",
            "fix": "SearXNG selectors: input=get_by_placeholder('Search for...'), submit=get_by_role('button', name='search'), results=locator('.result')"
        },
        "ssl_protocol_error": {
            "pattern": r"ERR_SSL_PROTOCOL_ERROR|SSL_ERROR|certificate",
            "description": "Using HTTPS on HTTP-only service",
            "fix": "Use http:// not https:// for localhost services. SearXNG is at http://localhost:8888 (no SSL)"
        },
        "wrong_protocol": {
            "pattern": r"https://localhost",
            "description": "Using HTTPS for localhost service",
            "fix": "Local services use HTTP not HTTPS. Use http://localhost:8888 for SearXNG"
        },
        "code_too_long": {
            "pattern": r"Code too long|2\d{3} chars|max 2000",
            "description": "Generated code exceeds 2000 character limit",
            "fix": "Keep code SHORT! Do ONE action per step. No comments, no print statements, no explanations. Just the minimal code needed for one interaction."
        },
    }

    def __init__(self, persist_path: Optional[Path] = None):
        """Initialize error tracker.

        Args:
            persist_path: Optional path to persist error memory
        """
        self.persist_path = persist_path
        self.errors: List[CodeError] = []
        self.patterns: Dict[str, ErrorPattern] = {}
        self.error_counts: Dict[str, int] = defaultdict(int)

        # Initialize known patterns
        for name, info in self.KNOWN_PATTERNS.items():
            self.patterns[name] = ErrorPattern(
                error_type=name,
                pattern=info["pattern"],
                description=info["description"],
                fixes=[info["fix"]] if "fix" in info else []
            )

        # Load persisted data if available
        if persist_path and persist_path.exists():
            self._load()

    def record_error(
        self,
        error_message: str,
        code: str,
        error_type: str = "",
        page_url: str = "",
    ) -> Optional[str]:
        """Record a code execution error.

        Args:
            error_message: The error message
            code: The code that caused the error
            error_type: Type of error (e.g., TypeError)
            page_url: URL where error occurred

        Returns:
            Suggested fix if known pattern matched, else None
        """
        # Extract error type from message if not provided
        if not error_type:
            type_match = re.search(r'(\w+Error|\w+Exception)', error_message)
            error_type = type_match.group(1) if type_match else "Unknown"

        # Extract selector if present
        selector = ""
        selector_match = re.search(r'["\']([^"\']+)["\']', code)
        if selector_match:
            selector = selector_match.group(1)[:100]

        error = CodeError(
            timestamp=datetime.now().isoformat(),
            error_type=error_type,
            error_message=error_message[:500],
            code_snippet=code[:500],
            page_url=page_url,
            selector=selector,
        )

        self.errors.append(error)
        self.error_counts[error_type] += 1

        # Keep last 100 errors
        if len(self.errors) > 100:
            self.errors = self.errors[-100:]

        # Match against known patterns
        suggested_fix = None
        for name, pattern in self.patterns.items():
            if re.search(pattern.pattern, error_message, re.IGNORECASE):
                pattern.add_occurrence(error)
                if pattern.fixes:
                    suggested_fix = pattern.fixes[0]
                logger.debug(f"Matched error pattern: {name}")
                break

        # Persist if path set
        if self.persist_path:
            self._save()

        return suggested_fix

    def record_fix(self, error_message: str, fix_code: str):
        """Record that a fix worked for an error.

        Args:
            error_message: Original error message
            fix_code: Code that successfully fixed the issue
        """
        # Find matching pattern and add fix
        for name, pattern in self.patterns.items():
            if re.search(pattern.pattern, error_message, re.IGNORECASE):
                if fix_code not in pattern.fixes:
                    pattern.fixes.append(fix_code[:300])
                    logger.info(f"Learned new fix for {name}: {fix_code[:50]}...")
                break

        # Also update last error if it matches
        for error in reversed(self.errors):
            if error.error_message in error_message or error_message in error.error_message:
                error.fix_applied = fix_code[:300]
                break

        if self.persist_path:
            self._save()

    def get_context_injection(self) -> str:
        """Get error context to inject into the prompt.

        Returns context about recent/common errors and their fixes.
        """
        lines = []

        # Get most common errors
        common_errors = sorted(
            [(name, p) for name, p in self.patterns.items() if p.count > 0],
            key=lambda x: x[1].count,
            reverse=True
        )[:5]

        if common_errors:
            lines.append("## Common Mistakes to Avoid")
            lines.append("")
            for name, pattern in common_errors:
                lines.append(f"**{pattern.description}** (seen {pattern.count}x)")
                if pattern.fixes:
                    lines.append(f"- Fix: {pattern.fixes[0]}")
                if pattern.examples:
                    lines.append(f"- Bad: `{pattern.examples[0][:80]}...`")
                lines.append("")

        # Recent errors from current session
        recent_errors = [e for e in self.errors[-5:] if not e.fix_applied]
        if recent_errors:
            lines.append("## Recent Errors This Session")
            for error in recent_errors:
                lines.append(f"- {error.error_type}: {error.error_message[:80]}")

        return "\n".join(lines) if lines else ""

    def get_reflexion_context(self, last_n_errors: int = 5) -> Dict[str, Any]:
        """Get error context formatted for reflexion analysis.

        Provides structured data for the reflexion node to analyze failures.

        Args:
            last_n_errors: Number of recent errors to include

        Returns:
            Dict with error context for reflexion
        """
        recent = self.errors[-last_n_errors:] if self.errors else []

        return {
            "recent_errors": [
                {
                    "error_type": e.error_type,
                    "message": e.error_message,
                    "code": e.code_snippet,
                    "selector": e.selector,
                    "url": e.page_url,
                    "fixed": e.fix_applied is not None,
                }
                for e in recent
            ],
            "common_patterns": [
                {
                    "name": name,
                    "description": p.description,
                    "count": p.count,
                    "known_fixes": p.fixes[:3],
                }
                for name, p in self.patterns.items()
                if p.count > 0
            ],
            "session_stats": {
                "total_errors": len(self.errors),
                "unique_types": len(set(e.error_type for e in self.errors)),
                "fixed_count": len([e for e in self.errors if e.fix_applied]),
            }
        }

    def record_reflexion_fix(
        self,
        error_message: str,
        fix_strategy: str,
        learned_pattern: str,
    ):
        """Record a fix discovered through reflexion.

        Args:
            error_message: The error that was fixed
            fix_strategy: The strategy that worked
            learned_pattern: General lesson learned
        """
        # Find matching pattern and add the fix
        for name, pattern in self.patterns.items():
            if re.search(pattern.pattern, error_message, re.IGNORECASE):
                if fix_strategy and fix_strategy not in pattern.fixes:
                    pattern.fixes.append(fix_strategy[:300])
                    logger.info(f"[REFLEXION] Learned fix for {name}: {fix_strategy[:50]}...")
                break

        # Also store in recent errors
        for error in reversed(self.errors):
            if error.error_message in error_message or error_message in error.error_message:
                error.fix_applied = fix_strategy[:300]
                break

        if self.persist_path:
            self._save()

    def get_stats(self) -> Dict[str, Any]:
        """Get error tracking statistics."""
        return {
            "total_errors": len(self.errors),
            "error_types": dict(self.error_counts),
            "patterns_matched": {
                name: p.count for name, p in self.patterns.items() if p.count > 0
            },
            "fixes_learned": sum(
                len(p.fixes) - 1 for p in self.patterns.values()  # -1 for initial fix
            ),
        }

    def clear_session(self):
        """Clear session-specific errors but keep patterns."""
        self.errors = []

    def _save(self):
        """Persist error data to file."""
        if not self.persist_path:
            return

        data = {
            "patterns": {
                name: asdict(p) for name, p in self.patterns.items()
            },
            "error_counts": dict(self.error_counts),
            "recent_errors": [asdict(e) for e in self.errors[-20:]],
        }

        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to persist error data: {e}")

    def _load(self):
        """Load persisted error data."""
        if not self.persist_path or not self.persist_path.exists():
            return

        try:
            data = json.loads(self.persist_path.read_text())

            # Restore pattern counts and fixes
            for name, pdata in data.get("patterns", {}).items():
                if name in self.patterns:
                    self.patterns[name].count = pdata.get("count", 0)
                    self.patterns[name].fixes = pdata.get("fixes", [])
                    self.patterns[name].examples = pdata.get("examples", [])
                    self.patterns[name].last_seen = pdata.get("last_seen", "")

            self.error_counts = defaultdict(int, data.get("error_counts", {}))
            logger.info(f"Loaded error memory: {sum(p.count for p in self.patterns.values())} patterns")

        except Exception as e:
            logger.warning(f"Failed to load error data: {e}")
