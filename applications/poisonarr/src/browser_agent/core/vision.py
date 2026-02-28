"""Vision module for browser agent - integrates screenshots with vision-capable LLMs.

Uses Ollama's LLaVA or similar vision models to understand page content
when accessibility trees aren't sufficient.
"""

import asyncio
import base64
import json
import logging
import httpx
from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class VisionAnalyzer:
    """Analyzes page screenshots using vision-capable LLMs.

    Supports Ollama (llava, bakllava), OpenAI (gpt-4o), and Anthropic (claude-3).
    """

    # Supported vision models
    VISION_MODELS = [
        "gpt-4-vision-preview",
        "gpt-4o",
        "gpt-4-turbo",
        "claude-3-opus",
        "claude-3-sonnet",
        "claude-3-haiku",
        "llava",
        "llava:7b",
        "llava:13b",
        "llava:34b",
        "bakllava",
        "llava-llama3",
        "minicpm-v",
    ]

    def __init__(
        self,
        model: str = "llava:13b",
        base_url: str = "http://localhost:11434",
        api_key: Optional[str] = None,
        enabled: bool = True,
        provider: str = "ollama",
    ):
        """Initialize vision analyzer.

        Args:
            model: Vision-capable model name
            base_url: API base URL (Ollama default: localhost:11434)
            api_key: API key (for OpenAI/Anthropic)
            enabled: Whether vision analysis is enabled
            provider: "ollama", "openai", or "anthropic"
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.enabled = enabled
        self.provider = provider
        self._client: Optional[httpx.AsyncClient] = None

        if enabled:
            self._validate_model()
            logger.info(f"Vision analyzer enabled: {provider}/{model}")

    def _validate_model(self):
        """Validate that the model supports vision."""
        model_lower = self.model.lower()
        is_vision = any(vm in model_lower for vm in self.VISION_MODELS)
        if not is_vision:
            logger.warning(
                f"Model '{self.model}' may not support vision. "
                f"Supported models include: llava, gpt-4o, claude-3"
            )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def _invoke_vision_ollama(
        self,
        image_b64: str,
        prompt: str,
        max_tokens: int = 500,
    ) -> str:
        """Invoke Ollama vision model with image.

        Args:
            image_b64: Base64-encoded PNG image
            prompt: Text prompt about the image
            max_tokens: Maximum response tokens

        Returns:
            Model response
        """
        client = await self._get_client()

        try:
            # Ollama uses /api/chat for vision models
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                            "images": [image_b64],
                        }
                    ],
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                    }
                },
                timeout=90.0,
            )
            response.raise_for_status()
            data = response.json()
            # Response format: {"message": {"content": "..."}}
            message = data.get("message", {})
            return message.get("content", "")
        except httpx.TimeoutException:
            logger.warning("Vision API timeout")
            return "[Vision timeout - model may be loading]"
        except Exception as e:
            logger.error(f"Vision API error: {e}")
            return f"[Vision error: {str(e)[:50]}]"

    async def _invoke_vision_openai(
        self,
        image_b64: str,
        prompt: str,
        max_tokens: int = 500,
    ) -> str:
        """Invoke OpenAI vision model."""
        client = await self._get_client()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_b64}"}
                            }
                        ]
                    }],
                    "max_tokens": max_tokens,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenAI vision error: {e}")
            return f"[Vision error: {str(e)[:50]}]"

    async def _invoke_vision(
        self,
        image_b64: str,
        prompt: str,
        max_tokens: int = 500,
    ) -> str:
        """Invoke vision model with image.

        Args:
            image_b64: Base64-encoded PNG image
            prompt: Text prompt about the image
            max_tokens: Maximum response tokens

        Returns:
            Model response
        """
        if self.provider == "ollama":
            return await self._invoke_vision_ollama(image_b64, prompt, max_tokens)
        elif self.provider == "openai":
            return await self._invoke_vision_openai(image_b64, prompt, max_tokens)
        else:
            logger.warning(f"Unknown provider: {self.provider}")
            return "[Vision provider not supported]"

    async def describe_page(
        self,
        page: "Page",
        context: str = "",
    ) -> str:
        """Describe what's visible on a page.

        Args:
            page: Playwright page
            context: Additional context about what to look for

        Returns:
            Description of the page
        """
        if not self.enabled:
            return "[Vision disabled]"

        try:
            screenshot = await page.screenshot(type="png", full_page=False)
            image_b64 = base64.b64encode(screenshot).decode()

            prompt = f"""Describe this webpage screenshot concisely.

Focus on:
1. What type of page is this? (search results, article, form, etc.)
2. What interactive elements are visible? (buttons, links, inputs)
3. What is the main content?
4. Are there any popups or overlays?

{f"Context: {context}" if context else ""}

Be specific about element text/labels for automation purposes."""

            result = await self._invoke_vision(image_b64, prompt, max_tokens=400)
            logger.info(f"[VISION] Page description: {result[:100]}...")
            return result
        except Exception as e:
            logger.warning(f"Vision describe_page failed: {e}")
            return f"[Vision error: {str(e)[:50]}]"

    async def suggest_selectors(
        self,
        page: "Page",
        goal: str,
    ) -> str:
        """Suggest Playwright selectors based on visual analysis.

        Args:
            page: Playwright page
            goal: What we're trying to accomplish

        Returns:
            Selector suggestions
        """
        if not self.enabled:
            return "[Vision disabled]"

        try:
            screenshot = await page.screenshot(type="png", full_page=False)
            image_b64 = base64.b64encode(screenshot).decode()

            prompt = f"""Goal: {goal}

Looking at this webpage screenshot, suggest specific Playwright selectors to interact with.

For each interactive element relevant to the goal, provide:
- Element description
- Suggested Playwright selector (prefer get_by_role, get_by_text, get_by_placeholder)
- Alternative selector if first fails

Example format:
SEARCH INPUT: page.get_by_placeholder("Search") or page.locator("input[type='search']")
SUBMIT BUTTON: page.get_by_role("button", name="Search") or page.locator("button[type='submit']")

Focus only on elements needed for the goal."""

            result = await self._invoke_vision(image_b64, prompt, max_tokens=500)
            logger.info(f"[VISION] Selector suggestions: {result[:100]}...")
            return result
        except Exception as e:
            logger.warning(f"Vision suggest_selectors failed: {e}")
            return f"[Vision error: {str(e)[:50]}]"

    async def analyze_failure(
        self,
        page: "Page",
        failed_code: str,
        error_message: str,
    ) -> str:
        """Analyze why code failed by looking at the page.

        Args:
            page: Playwright page
            failed_code: Code that failed
            error_message: Error message

        Returns:
            Analysis and fix suggestions
        """
        if not self.enabled:
            return "[Vision disabled]"

        try:
            screenshot = await page.screenshot(type="png", full_page=False)
            image_b64 = base64.b64encode(screenshot).decode()

            prompt = f"""The following Playwright code failed:

```python
{failed_code[:500]}
```

Error: {error_message[:200]}

Looking at the current page screenshot:
1. Why did the code fail? (element not found, wrong page, popup blocking, etc.)
2. What elements ARE visible that we should use instead?
3. Suggest working Playwright code to achieve the same goal.

Be specific about visible element text/labels."""

            result = await self._invoke_vision(image_b64, prompt, max_tokens=600)
            logger.info(f"[VISION] Failure analysis: {result[:100]}...")
            return result
        except Exception as e:
            logger.warning(f"Vision analyze_failure failed: {e}")
            return f"[Vision error: {str(e)[:50]}]"

    async def find_element(
        self,
        page: "Page",
        description: str,
    ) -> Optional[Dict[str, Any]]:
        """Find an element by visual description.

        Args:
            page: Playwright page
            description: Natural language description of element to find

        Returns:
            Element info with selector suggestions, or None
        """
        if not self.enabled:
            return None

        try:
            screenshot = await page.screenshot(type="png", full_page=False)
            image_b64 = base64.b64encode(screenshot).decode()

            prompt = f"""Find this element in the screenshot: "{description}"

Return ONLY valid JSON (no markdown):
{{
    "found": true or false,
    "element_type": "button/link/input/text/image",
    "visible_text": "exact text shown on element",
    "playwright_selector": "suggested Playwright selector",
    "alternative_selector": "backup selector if first fails"
}}"""

            response = await self._invoke_vision(image_b64, prompt, max_tokens=200)

            # Try to parse JSON from response
            try:
                # Find JSON in response
                start = response.find("{")
                end = response.rfind("}") + 1
                if start >= 0 and end > start:
                    return json.loads(response[start:end])
            except json.JSONDecodeError:
                pass

            return None
        except Exception as e:
            logger.warning(f"Vision find_element failed: {e}")
            return None

    async def detect_popups(
        self,
        page: "Page",
    ) -> List[Dict[str, Any]]:
        """Detect popup/modal overlays visually.

        Args:
            page: Playwright page

        Returns:
            List of detected popups with dismiss suggestions
        """
        if not self.enabled:
            return []

        try:
            screenshot = await page.screenshot(type="png", full_page=False)
            image_b64 = base64.b64encode(screenshot).decode()

            prompt = """Are there any popups, modals, cookie banners, or overlays blocking the main content?

Return ONLY valid JSON array (no markdown):
[
    {
        "type": "cookie_banner/modal/popup/login_prompt/ad",
        "description": "what it says",
        "dismiss_selector": "Playwright selector to close it"
    }
]

Return empty array [] if no popups visible."""

            response = await self._invoke_vision(image_b64, prompt, max_tokens=300)

            # Try to parse JSON array from response
            try:
                start = response.find("[")
                end = response.rfind("]") + 1
                if start >= 0 and end > start:
                    return json.loads(response[start:end])
            except json.JSONDecodeError:
                pass

            return []
        except Exception as e:
            logger.warning(f"Vision detect_popups failed: {e}")
            return []

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


async def is_vision_available(
    model: str = "llava:13b",
    base_url: str = "http://localhost:11434",
) -> bool:
    """Check if vision model is available.

    Args:
        model: Vision model name
        base_url: Ollama API URL

    Returns:
        True if model is available and supports vision
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Check if Ollama is running
            response = await client.get(f"{base_url}/api/tags")
            if response.status_code != 200:
                return False

            # Check if model is available
            data = response.json()
            models = [m.get("name", "") for m in data.get("models", [])]

            # Check for exact match or prefix match
            model_name = model.split(":")[0] if ":" in model else model
            return any(model_name in m for m in models)
    except Exception as e:
        logger.debug(f"Vision availability check failed: {e}")
        return False


# Export for easy importing
__all__ = ["VisionAnalyzer", "is_vision_available"]
