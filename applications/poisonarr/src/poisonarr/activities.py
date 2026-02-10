"""Browsing activities for traffic generation."""

import asyncio
import logging
import random
from typing import List, Optional

from playwright.async_api import Browser, Page

from .config import Config
from .llm import LLMClient

logger = logging.getLogger(__name__)


class BrowsingActivities:
    """Collection of browsing activities for traffic generation."""

    def __init__(self, config: Config, llm: LLMClient):
        """Initialize with configuration and LLM client."""
        self.config = config
        self.llm = llm

    async def _create_page(self, browser: Browser) -> Page:
        """Create a new browser page with realistic settings."""
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id=self.config.timezone,
        )
        return await context.new_page()

    async def _simulate_reading(self, page: Page) -> None:
        """Simulate reading behavior with scrolling and pauses."""
        behavior = self.llm.generate_scroll_behavior()

        for _ in range(behavior["scroll_count"]):
            # Scroll down
            scroll_amount = random.randint(200, 600)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")

            # Wait as if reading
            await asyncio.sleep(behavior["scroll_delay"])

            # Occasionally pause longer (as if reading something interesting)
            if random.random() < behavior["pause_probability"]:
                await asyncio.sleep(behavior["pause_duration"])

    async def _click_random_link(self, page: Page) -> bool:
        """Click a random link on the page."""
        try:
            links = await page.query_selector_all("a[href]:not([href^='#'])")
            if not links:
                return False

            # Filter to visible, reasonable links
            valid_links = []
            for link in links[:50]:  # Limit to first 50
                try:
                    if await link.is_visible():
                        href = await link.get_attribute("href")
                        if href and not href.startswith(("javascript:", "mailto:")):
                            valid_links.append(link)
                except Exception:
                    continue

            if valid_links:
                link = random.choice(valid_links)
                await link.click()
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
                return True
        except Exception as e:
            logger.debug(f"Failed to click link: {e}")
        return False

    async def visit_news_site(self, browser: Browser) -> None:
        """Visit a news site and browse articles."""
        sites = self.config.sites.get("news", ["cnn.com"])
        site = random.choice(sites)

        logger.info(f"Visiting news site: {site}")
        page = await self._create_page(browser)

        try:
            await page.goto(f"https://{site}", timeout=60000)
            await self._simulate_reading(page)

            # Maybe click into an article
            if random.random() < 0.6:
                if await self._click_random_link(page):
                    await self._simulate_reading(page)

        except Exception as e:
            logger.warning(f"News browsing error: {e}")
        finally:
            await page.context.close()

    async def browse_shopping(self, browser: Browser) -> None:
        """Browse shopping sites."""
        sites = self.config.sites.get("shopping", ["amazon.com"])
        site = random.choice(sites)

        logger.info(f"Browsing shopping site: {site}")
        page = await self._create_page(browser)

        try:
            await page.goto(f"https://{site}", timeout=60000)
            await self._simulate_reading(page)

            # Browse a few products
            for _ in range(random.randint(1, 3)):
                if await self._click_random_link(page):
                    await self._simulate_reading(page)
                    await asyncio.sleep(random.uniform(2, 5))

        except Exception as e:
            logger.warning(f"Shopping browsing error: {e}")
        finally:
            await page.context.close()

    async def browse_tech(self, browser: Browser) -> None:
        """Browse tech/developer sites."""
        sites = self.config.sites.get("tech", ["github.com"])
        site = random.choice(sites)

        logger.info(f"Browsing tech site: {site}")
        page = await self._create_page(browser)

        try:
            await page.goto(f"https://{site}", timeout=60000)
            await self._simulate_reading(page)

            # Explore a bit
            if random.random() < 0.5:
                if await self._click_random_link(page):
                    await self._simulate_reading(page)

        except Exception as e:
            logger.warning(f"Tech browsing error: {e}")
        finally:
            await page.context.close()

    async def perform_search(self, browser: Browser) -> None:
        """Perform a search query on a search engine."""
        engines = self.config.sites.get("search_engines", ["google.com"])
        engine = random.choice(engines)

        # Get category for context
        categories = list(self.config.activities.keys())
        category = random.choice(categories) if categories else "general"
        query = self.llm.generate_search_query(category)

        logger.info(f"Searching on {engine}: {query}")
        page = await self._create_page(browser)

        try:
            if "google" in engine:
                await page.goto("https://www.google.com", timeout=60000)
                await page.fill('textarea[name="q"]', query)
                await page.press('textarea[name="q"]', "Enter")
            elif "duckduckgo" in engine:
                await page.goto("https://duckduckgo.com", timeout=60000)
                await page.fill('input[name="q"]', query)
                await page.press('input[name="q"]', "Enter")
            elif "bing" in engine:
                await page.goto("https://www.bing.com", timeout=60000)
                await page.fill('input[name="q"]', query)
                await page.press('input[name="q"]', "Enter")

            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            await self._simulate_reading(page)

            # Maybe click a result
            if random.random() < 0.4:
                if await self._click_random_link(page):
                    await self._simulate_reading(page)

        except Exception as e:
            logger.warning(f"Search error: {e}")
        finally:
            await page.context.close()

    async def browse_social(self, browser: Browser) -> None:
        """Browse social media (read-only)."""
        sites = self.config.sites.get("social", ["reddit.com"])
        site = random.choice(sites)

        logger.info(f"Browsing social site: {site}")
        page = await self._create_page(browser)

        try:
            await page.goto(f"https://{site}", timeout=60000)
            await self._simulate_reading(page)

            # Browse a few posts/threads
            for _ in range(random.randint(1, 2)):
                if await self._click_random_link(page):
                    await self._simulate_reading(page)

        except Exception as e:
            logger.warning(f"Social browsing error: {e}")
        finally:
            await page.context.close()

    async def watch_video(self, browser: Browser) -> None:
        """Watch a video partially."""
        sites = self.config.sites.get("video", ["youtube.com"])
        site = random.choice(sites)

        logger.info(f"Visiting video site: {site}")
        page = await self._create_page(browser)

        try:
            await page.goto(f"https://{site}", timeout=60000)
            await self._simulate_reading(page)

            # Click on a video
            if await self._click_random_link(page):
                # Watch for a random duration (30s - 3min)
                watch_time = random.uniform(30, 180)
                logger.info(f"Watching video for {watch_time:.0f}s")
                await asyncio.sleep(watch_time)

        except Exception as e:
            logger.warning(f"Video browsing error: {e}")
        finally:
            await page.context.close()

    def get_random_activity(self):
        """Get a random activity based on configured weights."""
        activities = self.config.activities
        if not activities:
            activities = {
                "news": 25,
                "shopping": 20,
                "tech": 20,
                "search": 25,
                "social": 10,
            }

        activity_map = {
            "news": self.visit_news_site,
            "shopping": self.browse_shopping,
            "tech": self.browse_tech,
            "search": self.perform_search,
            "social": self.browse_social,
            "video": self.watch_video,
        }

        names = list(activities.keys())
        weights = [activities[name] for name in names]

        chosen = random.choices(names, weights=weights, k=1)[0]
        return activity_map.get(chosen, self.visit_news_site)
