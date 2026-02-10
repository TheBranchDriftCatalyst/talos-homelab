"""Main browsing agent for Poisonarr."""

import asyncio
import logging
import random
from datetime import datetime

import pytz
from playwright.async_api import async_playwright

from .activities import BrowsingActivities
from .config import Config
from .llm import LLMClient

logger = logging.getLogger(__name__)


class PoisonarrAgent:
    """Main agent that orchestrates browsing activities."""

    def __init__(self, config: Config):
        """Initialize agent with configuration."""
        self.config = config
        self.llm = LLMClient(config)
        self.activities = BrowsingActivities(config, self.llm)
        self.tz = pytz.timezone(config.timezone)

    def is_active_hours(self) -> bool:
        """Check if current time is within active hours."""
        now = datetime.now(self.tz)
        current_time = now.strftime("%H:%M")

        start = self.config.active_hours.start
        end = self.config.active_hours.end

        # Handle overnight ranges (e.g., 22:00 - 06:00)
        if start <= end:
            return start <= current_time <= end
        else:
            return current_time >= start or current_time <= end

    def get_random_delay(self) -> float:
        """Get a random delay between activities."""
        min_delay = self.config.min_delay_seconds
        max_delay = self.config.max_delay_seconds

        # Use a distribution that favors shorter delays
        # but occasionally has longer pauses
        if random.random() < 0.1:
            # 10% chance of extra long pause
            return random.uniform(max_delay, max_delay * 2)
        else:
            return random.uniform(min_delay, max_delay)

    async def run(self) -> None:
        """Run the main agent loop."""
        logger.info("Starting Poisonarr agent")
        logger.info(f"Active hours: {self.config.active_hours.start} - {self.config.active_hours.end}")
        logger.info(f"Timezone: {self.config.timezone}")
        logger.info(f"LLM endpoint: {self.config.litellm_url}")

        async with async_playwright() as p:
            # Launch browser once, reuse for all activities
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                ],
            )

            try:
                while True:
                    if self.is_active_hours():
                        try:
                            # Get and execute random activity
                            activity = self.activities.get_random_activity()
                            logger.info(f"Starting activity: {activity.__name__}")
                            await activity(browser)
                            logger.info(f"Completed activity: {activity.__name__}")
                        except Exception as e:
                            logger.error(f"Activity failed: {e}")

                        # Wait between activities
                        delay = self.get_random_delay()
                        logger.debug(f"Waiting {delay:.0f}s until next activity")
                        await asyncio.sleep(delay)
                    else:
                        # Outside active hours, check less frequently
                        logger.debug("Outside active hours, sleeping for 5 minutes")
                        await asyncio.sleep(300)

            except asyncio.CancelledError:
                logger.info("Agent shutdown requested")
            finally:
                await browser.close()
                logger.info("Browser closed")
