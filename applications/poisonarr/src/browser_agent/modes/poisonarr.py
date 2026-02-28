"""Poisonarr Mode - Traffic noise generation.

Generates realistic browsing traffic to obscure actual user activity.
Uses only the Navigator (small/fast model) - no reasoning needed.
"""

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from typing import Optional, List, TYPE_CHECKING

from .base import AgentMode
from ..memory import MemoryManager, SessionMemory

if TYPE_CHECKING:
    from ..server import UIServer

logger = logging.getLogger(__name__)


@dataclass
class BrowsingIntent:
    """A high-level browsing intent."""
    persona: str
    goal: str
    mood: str  # focused, casual, exploratory
    starting_point: str
    duration_minutes: int


# Prompt for generating browsing intents
INTENT_PROMPT = """Generate a realistic browsing intent for a person using the internet.

Return JSON with these fields:
{
    "persona": "brief description of the person (e.g., 'college student researching history')",
    "goal": "what they want to accomplish (e.g., 'find information about ancient Rome')",
    "mood": "one of: focused, casual, exploratory",
    "duration_minutes": 5-20
}

Be creative and varied. Real people browse for many reasons:
- Research and learning
- Shopping and comparing products
- Entertainment and news
- Work and productivity
- Hobbies and interests

Return ONLY valid JSON."""


class PoisonarrMode(AgentMode):
    """Traffic noise generation mode.

    Generates realistic web traffic to obscure browsing patterns.
    Only uses Navigator (small model) - no reasoning needed.
    """

    MODE_NAME = "poisonarr"
    MODE_DESCRIPTION = "Traffic noise generation - create realistic browsing activity"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._memory_manager: Optional[MemoryManager] = None
        self._current_browser_tools = None  # For exposing observations

    @property
    def uses_reasoner(self) -> bool:
        """Poisonarr doesn't need reasoning."""
        return False

    def _get_memory_manager(self) -> MemoryManager:
        """Get or create memory manager."""
        if self._memory_manager is None:
            storage_dir = self.config.browser.user_data_dir if self.config.browser.persist_sessions else None
            self._memory_manager = MemoryManager(storage_dir)
        return self._memory_manager

    def get_memory_context(self) -> str:
        """Get memory context for intent generation."""
        memory = self._get_memory_manager().get_memory(self.agent_id)
        return memory.get_context_for_llm()

    def _generate_intent(self) -> BrowsingIntent:
        """Generate a random browsing intent using LLM."""
        # Use SearXNG as starting point - no CAPTCHAs
        starting_site = "http://localhost:8888"

        try:
            memory_context = self.get_memory_context()

            prompt = INTENT_PROMPT
            prompt += "\n\nIMPORTANT: Generate a goal that involves SEARCHING for information."
            prompt += "\nThe user will start on a search engine and search for their topic."

            if memory_context and "No browsing history" not in memory_context:
                prompt = f"{prompt}\n\n## Previous Activity Context:\n{memory_context}\n\nGenerate a new, different intent:"

            # Use navigator's LLM for intent generation
            response = self.navigator.llm.invoke([
                {
                    "role": "system",
                    "content": "You generate realistic, diverse browsing scenarios. Return only valid JSON."
                },
                {"role": "user", "content": prompt}
            ])

            content = response.content if hasattr(response, 'content') else str(response)
            content = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', content)
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)

            if json_match:
                data = json.loads(json_match.group())
                intent = BrowsingIntent(
                    persona=data.get("persona", "internet user"),
                    goal=data.get("goal", "search for interesting topics"),
                    mood=data.get("mood", "casual"),
                    starting_point=starting_site,
                    duration_minutes=data.get("duration_minutes", 10),
                )
                logger.info(f"Generated intent: {intent.persona} - {intent.goal}")
                return intent

        except Exception as e:
            logger.warning(f"Failed to generate intent: {e}")

        # Fallback
        return BrowsingIntent(
            persona="curious internet user",
            goal="search for interesting news and articles",
            mood="exploratory",
            starting_point=starting_site,
            duration_minutes=10,
        )

    async def _capture_screenshots(self, page, interval: float = 2.0):
        """Capture screenshots periodically."""
        while True:
            try:
                if page.is_closed():
                    break
                screenshot = await page.screenshot(type="png")
                if self.ui_server:
                    await self.ui_server.update_screenshot(
                        self.agent_id, screenshot, page.url
                    )
            except Exception:
                pass
            await asyncio.sleep(interval)

    def _record_session(
        self,
        intent: BrowsingIntent,
        success: bool,
        summary: str,
        final_url: str,
        browser_tools,
    ):
        """Record completed session to memory."""
        try:
            sites_visited = []
            for action in self.navigator.history:
                if action.get("action") == "goto" and action.get("value"):
                    url = action["value"]
                    if "://" in url:
                        domain = url.split("://")[1].split("/")[0]
                        sites_visited.append(domain)

            if final_url and "://" in final_url:
                domain = final_url.split("://")[1].split("/")[0]
                if domain not in sites_visited:
                    sites_visited.append(domain)

            # Also add from browser_tools
            for url in browser_tools.visited_urls:
                if "://" in url:
                    domain = url.split("://")[1].split("/")[0]
                    if domain not in sites_visited:
                        sites_visited.append(domain)

            self._get_memory_manager().record_session(
                agent_id=self.agent_id,
                persona=intent.persona,
                goal=intent.goal,
                success=success,
                summary=summary,
                sites_visited=sites_visited,
                actions_taken=browser_tools.action_count,
            )
            logger.debug(f"Recorded session: {intent.goal[:30]} - {success}")
        except Exception as e:
            logger.warning(f"Failed to record session: {e}")

    async def run_session(self) -> bool:
        """Run a single noise generation session."""
        # Generate browsing intent
        intent = self._generate_intent()

        await self._update_status("planning")
        await self._log("info", f"Persona: {intent.persona}")
        await self._log("info", f"Goal: {intent.goal}")

        # Update UI with session info
        if self.ui_server:
            await self.ui_server.update_session(self.agent_id, {
                "persona": intent.persona,
                "intent": intent.goal,
                "mood": intent.mood,
                "steps": [{"action": "browse", "target": intent.starting_point, "description": intent.goal}],
            })

        context = None
        screenshot_task = None
        using_persistent = self.browser.is_persistent

        try:
            async with asyncio.timeout(360):  # 6 minute timeout
                context = await self.browser.get_context()
                page = await context.new_page()

                # Start screenshot capture
                screenshot_task = asyncio.create_task(self._capture_screenshots(page))

                await self._update_status("browsing")

                # Navigate to start
                start_url = intent.starting_point
                if not start_url.startswith("http"):
                    # Use a working search - SearXNG or direct site navigation
                    start_url = f"https://{intent.starting_point}"

                await self._log("info", f"Starting at: {start_url[:50]}")

                try:
                    await page.goto(start_url, timeout=30000)
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception as e:
                    await self._log("warning", f"Navigation failed: {str(e)[:30]}")
                    return False

                # Run navigation
                success, summary, browser_tools = await self.navigator.navigate(
                    page,
                    intent.goal,
                    max_steps=25,
                    timeout=240,
                    reasoner=self.reasoner,  # Pass reasoner for reflexion
                )

                # Store browser tools for observation access
                self._current_browser_tools = browser_tools

                if success:
                    await self._log("info", f"Success: {summary[:100]}")
                else:
                    await self._log("warning", f"Incomplete: {summary[:100]}")

                # Record to memory
                self._record_session(intent, success, summary, page.url, browser_tools)

                # Update memory stats in UI
                if self.ui_server:
                    memory = self._get_memory_manager().get_memory(self.agent_id)
                    await self.ui_server.update_memory_stats(
                        self.agent_id,
                        memory.total_sessions
                    )

                return success

        except asyncio.TimeoutError:
            logger.warning("Session timeout (360s)")
            await self._log("error", "Session timeout")
            return False
        except Exception as e:
            logger.error(f"Session error: {e}")
            await self._log("error", f"Error: {str(e)[:40]}")
            return False
        finally:
            if screenshot_task:
                screenshot_task.cancel()
                try:
                    await screenshot_task
                except asyncio.CancelledError:
                    pass

            # Clean up pages
            if context and not using_persistent:
                try:
                    await context.close()
                except Exception:
                    pass
            elif context and using_persistent:
                try:
                    for p in context.pages:
                        await p.close()
                except Exception:
                    pass

            await self._update_status("idle")

    def get_memory_data(self) -> dict:
        """Get memory data for API/UI."""
        memory = self._get_memory_manager().get_memory(self.agent_id)
        return {
            "agent_id": memory.agent_id,
            "created_at": memory.created_at,
            "total_sessions": memory.total_sessions,
            "successful_sessions": memory.successful_sessions,
            "historical_summary": memory.historical_summary,
            "recent_sessions": [
                {
                    "timestamp": s.timestamp,
                    "persona": s.persona,
                    "goal": s.goal,
                    "success": s.success,
                    "summary": s.summary,
                    "sites_visited": s.sites_visited,
                    "actions_taken": s.actions_taken,
                }
                for s in memory.recent_sessions
            ],
            "favorite_sites": memory.favorite_sites,
            "patterns": memory.patterns,
        }

    def get_observations_data(self) -> dict:
        """Get enhanced observations data for API/UI."""
        if hasattr(self, '_current_browser_tools') and self._current_browser_tools:
            return self._current_browser_tools.observations.to_dict()
        return {
            "console_logs": [],
            "network_requests": [],
            "dom_changes": [],
        }
