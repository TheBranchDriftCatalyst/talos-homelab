"""LiteLLM integration for generating realistic browsing behavior."""

import logging
import random
from typing import Optional

from openai import OpenAI

from .config import Config

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for LLM-powered content generation."""

    def __init__(self, config: Config):
        """Initialize LLM client with configuration."""
        self.config = config
        self.client = OpenAI(
            base_url=config.litellm_url,
            api_key="not-needed",  # Internal cluster access
        )
        self.model = config.model

    def _generate(
        self, system_prompt: str, user_prompt: str, max_tokens: int = 50
    ) -> Optional[str]:
        """Generate text using the LLM."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.9,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}")
            return None

    def generate_search_query(self, category: str) -> str:
        """Generate a realistic search query based on category."""
        system_prompt = """You are simulating a real person's search behavior.
Generate a single, natural search query that someone might type.
Be specific and varied. Include typos occasionally.
Only output the search query, nothing else."""

        category_contexts = {
            "news": "current events, politics, world news, local news",
            "shopping": "products to buy, deals, reviews, comparisons",
            "tech": "programming, software, gadgets, tech news",
            "social": "trending topics, entertainment, sports, memes",
            "general": "random curiosity, how-to questions, facts",
        }

        context = category_contexts.get(category, category_contexts["general"])
        user_prompt = f"Generate a search query about: {context}"

        result = self._generate(system_prompt, user_prompt, max_tokens=30)
        if result:
            return result

        # Fallback queries
        fallbacks = {
            "news": [
                "latest news today",
                "breaking news",
                "world news updates",
            ],
            "shopping": [
                "best deals online",
                "product reviews",
                "cheap electronics",
            ],
            "tech": [
                "python tutorial",
                "javascript frameworks",
                "best laptop 2024",
            ],
            "social": [
                "trending topics",
                "viral videos",
                "funny memes",
            ],
        }
        return random.choice(fallbacks.get(category, ["interesting facts"]))

    def generate_scroll_behavior(self) -> dict:
        """Generate realistic scroll behavior parameters."""
        # Randomize reading behavior
        return {
            "scroll_count": random.randint(2, 8),
            "scroll_delay": random.uniform(1.5, 5.0),
            "pause_probability": random.uniform(0.2, 0.5),
            "pause_duration": random.uniform(3.0, 15.0),
        }

    def decide_next_action(self, current_page: str) -> str:
        """Decide what action to take on current page."""
        system_prompt = """You are simulating browsing behavior.
Given a page URL, decide the next action.
Respond with exactly one of: scroll, click_link, search, leave
Only output the action word, nothing else."""

        result = self._generate(
            system_prompt,
            f"Current page: {current_page}",
            max_tokens=10,
        )

        valid_actions = ["scroll", "click_link", "search", "leave"]
        if result and result.lower() in valid_actions:
            return result.lower()

        # Fallback to random weighted choice
        return random.choices(
            valid_actions,
            weights=[40, 30, 10, 20],
            k=1,
        )[0]
