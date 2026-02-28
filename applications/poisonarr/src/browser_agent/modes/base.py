"""Base class for agent modes."""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import pytz
from playwright.async_api import async_playwright

from ..config import BrowserAgentConfig
from ..core.code_navigator import CodeNavigator
from ..core.browser import BrowserController
from ..reasoning.reasoner import Reasoner

if TYPE_CHECKING:
    from ..server import UIServer
    from ..memory import MemoryManager

logger = logging.getLogger(__name__)


class AgentMode(ABC):
    """Base class for all agent modes.

    Agent modes define different behaviors:
    - Poisonarr: Traffic noise generation
    - Researcher: Information extraction
    - Monitor: Page change detection
    - etc.

    Each mode has access to:
    - Navigator: Small/fast model for browser actions
    - Reasoner: Large/smart model for content understanding
    - BrowserController: Playwright browser management
    - Memory: Persistent state across sessions
    """

    # Mode identifier (override in subclass)
    MODE_NAME: str = "base"
    MODE_DESCRIPTION: str = "Base agent mode"

    def __init__(
        self,
        config: BrowserAgentConfig,
        ui_server: Optional["UIServer"] = None,
        agent_id: str = "agent-1",
    ):
        self.config = config
        self.ui_server = ui_server
        self.agent_id = agent_id

        # Timezone for active hours
        self.tz = pytz.timezone(config.timezone)

        # Core components (initialized in setup)
        self.navigator: Optional[CodeNavigator] = None
        self.reasoner: Optional[Reasoner] = None
        self.browser: Optional[BrowserController] = None
        self.memory: Optional["MemoryManager"] = None

        # Session tracking
        self.session_count = 0
        self._running = False
        self._paused = False

    def setup(self):
        """Initialize components. Called before run()."""
        logger.info(f"Setting up {self.MODE_NAME} mode...")

        # Check if graph mode is enabled
        use_graph = getattr(self.config, 'graph', None)
        use_graph = use_graph.enabled if use_graph else False

        # Create CodeNavigator (generates Playwright code instead of rigid commands)
        self.navigator = CodeNavigator(
            model=self.config.navigator_model,
            ui_server=self.ui_server,
            agent_id=self.agent_id,
            use_graph=use_graph,
            config=self.config,
        )

        # Create Reasoner (large/smart model) - only if mode needs it OR reflexion is enabled
        reflexion_config = getattr(self.config, 'reflexion', None)
        needs_reasoner = self.uses_reasoner or (reflexion_config and reflexion_config.enabled and reflexion_config.use_reasoner_model)

        if needs_reasoner:
            self.reasoner = Reasoner(
                model=self.config.reasoner_model,
                ui_server=self.ui_server,
                agent_id=self.agent_id,
            )

        # Browser controller
        self.browser = BrowserController(
            user_data_dir=self.config.browser.user_data_dir if self.config.browser.persist_sessions else None,
            headless=self.config.browser.headless,
        )

        # Register with UI server
        if self.ui_server:
            self.ui_server.register_agent(self.agent_id)
            self.ui_server.set_current_model(self.config.navigator_model)

        logger.info(f"{self.MODE_NAME} mode setup complete")

    @property
    def uses_reasoner(self) -> bool:
        """Whether this mode uses the Reasoner. Override if needed."""
        return False

    def is_active_hours(self) -> bool:
        """Check if current time is within active hours."""
        now = datetime.now(self.tz)
        current_time = now.strftime("%H:%M")

        start = self.config.active_hours.start
        end = self.config.active_hours.end

        if start <= end:
            return start <= current_time <= end
        else:
            return current_time >= start or current_time <= end

    def is_paused(self) -> bool:
        """Check if agent is paused (includes interactive mode)."""
        if self.ui_server:
            return self.ui_server.is_paused(self.agent_id)
        return self._paused

    def is_interactive_mode(self) -> bool:
        """Check if agent is in interactive chat mode."""
        if self.ui_server:
            return self.ui_server.is_interactive_mode(self.agent_id)
        return False

    def get_pending_chat_goal(self) -> Optional[str]:
        """Get pending chat goal from interactive mode."""
        if self.ui_server:
            return self.ui_server.get_pending_chat_goal(self.agent_id)
        return None

    async def add_chat_response(self, content: str, role: str = "assistant"):
        """Add a response to the chat."""
        if self.ui_server:
            await self.ui_server.add_chat_response(self.agent_id, content, role)

    def check_restart_requested(self) -> bool:
        """Check if restart was requested."""
        if self.ui_server:
            return self.ui_server.check_restart_requested(self.agent_id)
        return False

    async def _log(self, level: str, message: str):
        """Log to UI and logger."""
        log_fn = getattr(logger, level, logger.info)
        log_fn(f"[{self.MODE_NAME}] {message}")

        if self.ui_server:
            await self.ui_server.add_log(self.agent_id, level, message)

    async def _update_status(self, status: str):
        """Update agent status in UI."""
        if self.ui_server:
            await self.ui_server.update_status(self.agent_id, status)

    def update_models(self):
        """Check for model updates from UI server."""
        if self.ui_server and self.navigator:
            ui_model = self.ui_server.get_current_model()
            nav_model = self.navigator.model
            if ui_model and ui_model != nav_model:
                logger.info(f"Model change detected: {nav_model} -> {ui_model}")
                self.navigator.update_model(ui_model)

    @abstractmethod
    async def run_session(self) -> bool:
        """Run a single session. Override in subclass.

        Returns:
            True if session was successful
        """
        pass

    def get_session_delay(self) -> float:
        """Get delay between sessions. Override for custom timing."""
        import random

        min_delay = self.config.min_delay_seconds
        max_delay = self.config.max_delay_seconds

        # Human-like delay distribution
        if random.random() < 0.1:
            return random.uniform(max_delay * 2, max_delay * 4)
        elif random.random() < 0.2:
            return random.uniform(min_delay, min_delay * 2)
        else:
            return random.uniform(min_delay, max_delay)

    async def run_interactive_goal(self, goal: str, page) -> str:
        """Run a user-provided goal in interactive mode.

        Returns:
            Summary of what was accomplished
        """
        logger.info(f"[INTERACTIVE] Processing goal: {goal[:50]}...")
        await self._update_status("browsing")

        try:
            success, summary, _ = await self.navigator.navigate(
                page=page,
                goal=goal,
                max_steps=30,
                timeout=300,
                reasoner=self.reasoner,  # Pass reasoner for reflexion
            )

            await self._update_status("interactive")
            return summary if success else f"Failed: {summary}"
        except Exception as e:
            await self._update_status("interactive")
            return f"Error: {str(e)[:100]}"

    async def run(self):
        """Main run loop. Calls run_session() repeatedly."""
        self._running = True
        self.setup()

        logger.info("=" * 60)
        logger.info(f"Browser Agent - {self.MODE_NAME} Mode")
        logger.info("=" * 60)
        logger.info(f"Navigator: {self.config.navigator_model}")
        if self.uses_reasoner:
            logger.info(f"Reasoner: {self.config.reasoner_model}")
        logger.info(f"Active hours: {self.config.active_hours.start} - {self.config.active_hours.end}")
        logger.info("=" * 60)

        async with async_playwright() as p:
            await self.browser.launch(p.chromium)

            # Keep a page open for interactive mode
            interactive_context = None
            interactive_page = None

            try:
                while self._running:
                    # Handle interactive mode
                    if self.is_interactive_mode():
                        # Ensure we have a page for interactive mode
                        if interactive_page is None:
                            logger.info("[INTERACTIVE] Creating browser page...")
                            interactive_context = await self.browser.get_context()
                            interactive_page = await interactive_context.new_page()
                            await interactive_page.goto("about:blank")
                            logger.info("[INTERACTIVE] Browser ready for commands")
                            await self.add_chat_response("Browser ready. Send me a goal!")

                        # Check for pending chat goal
                        chat_goal = self.get_pending_chat_goal()
                        if chat_goal:
                            logger.info(f"[INTERACTIVE] Got goal: {chat_goal[:50]}...")
                            await self.add_chat_response(f"Working on: {chat_goal[:100]}...")
                            result = await self.run_interactive_goal(chat_goal, interactive_page)
                            logger.info(f"[INTERACTIVE] Result: {result[:50]}...")
                            await self.add_chat_response(result)

                            # Update screenshot
                            if self.ui_server:
                                screenshot = await interactive_page.screenshot(type="png")
                                await self.ui_server.update_screenshot(
                                    self.agent_id,
                                    screenshot,
                                    interactive_page.url
                                )
                        else:
                            await asyncio.sleep(0.3)  # Small delay when waiting for input
                        continue

                    # Clean up interactive page when exiting interactive mode
                    if interactive_page is not None:
                        try:
                            await interactive_page.close()
                            await interactive_context.close()
                        except Exception:
                            pass
                        interactive_page = None
                        interactive_context = None

                    # Check if paused (non-interactive pause)
                    while self.is_paused() and not self.is_interactive_mode():
                        logger.debug("Agent paused, waiting...")
                        await asyncio.sleep(2)

                    if self.is_active_hours():
                        self.session_count += 1
                        logger.info(f"\n{'='*60}")
                        logger.info(f"SESSION {self.session_count}")
                        logger.info(f"{'='*60}")

                        try:
                            # Check for model updates
                            self.update_models()

                            # Run session
                            success = await self.run_session()

                            if self.ui_server:
                                await self.ui_server.record_session_result(self.agent_id, success)

                        except Exception as e:
                            logger.error(f"Session failed: {e}")
                            await self._log("error", f"Session failed: {str(e)[:50]}")

                        # Delay between sessions
                        delay = self.get_session_delay()
                        logger.info(f"Next session in {delay:.0f}s...")

                        waited = 0
                        while waited < delay:
                            if self.check_restart_requested():
                                logger.info("Restart requested")
                                break
                            if self.is_paused() or self.is_interactive_mode():
                                await asyncio.sleep(2)
                                if self.is_interactive_mode():
                                    break  # Exit delay loop for interactive mode
                                continue
                            await asyncio.sleep(min(2, delay - waited))
                            waited += 2

                    else:
                        logger.info("Outside active hours, sleeping 5 min")
                        await asyncio.sleep(300)

            except asyncio.CancelledError:
                logger.info("Shutdown requested")
            finally:
                # Cleanup interactive resources
                if interactive_page:
                    try:
                        await interactive_page.close()
                    except Exception:
                        pass
                if interactive_context:
                    try:
                        await interactive_context.close()
                    except Exception:
                        pass
                await self.browser.close()
                logger.info(f"Done. {self.session_count} sessions completed.")

    def stop(self):
        """Stop the agent."""
        self._running = False
