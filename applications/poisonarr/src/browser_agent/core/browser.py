"""Browser controller and tools for Playwright automation."""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING, Dict, Any

from playwright.async_api import Browser, BrowserContext, BrowserType, Page

if TYPE_CHECKING:
    from ..server import UIServer

logger = logging.getLogger(__name__)

# Sites that block bots or require CAPTCHAs - never navigate to these
BLOCKED_DOMAINS = frozenset([
    "google.com", "www.google.com",
    "bing.com", "www.bing.com",
    "duckduckgo.com", "www.duckduckgo.com",
    "yahoo.com", "search.yahoo.com",
    "yandex.com", "www.yandex.com",
    "baidu.com", "www.baidu.com",
    # Social media login walls
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
    "twitter.com", "x.com",
    "linkedin.com", "www.linkedin.com",
])

# Error page patterns to detect
ERROR_PAGE_PATTERNS = [
    "404", "not found", "page not found",
    "403", "forbidden", "access denied",
    "418", "blocked", "captcha",
    "error", "something went wrong",
    "sorry, we couldn't",
    "this page isn't available",
]


def is_blocked_url(url: str) -> bool:
    """Check if URL is in blocked domains list."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Check exact match and subdomain match
        for blocked in BLOCKED_DOMAINS:
            if domain == blocked or domain.endswith(f".{blocked}"):
                return True
        return False
    except Exception:
        return False


def is_error_page(title: str, content: str = "") -> bool:
    """Check if page appears to be an error page."""
    combined = f"{title} {content}".lower()
    for pattern in ERROR_PAGE_PATTERNS:
        if pattern in combined:
            return True
    return False


async def retry_async(
    func,
    max_retries: int = 3,
    base_delay: float = 0.5,
    exceptions: tuple = (Exception,),
):
    """Retry an async function with exponential backoff.

    Best practice: Add resilience for transient failures.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return await func()
        except exceptions as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.debug(f"Retry {attempt + 1}/{max_retries} after {delay}s: {e}")
                await asyncio.sleep(delay)
    raise last_error


@dataclass
class ConsoleMessage:
    """Captured console message."""
    timestamp: str
    type: str  # log, error, warning, info, debug
    text: str
    location: str = ""


@dataclass
class NetworkRequest:
    """Captured network request."""
    timestamp: str
    method: str
    url: str
    resource_type: str
    status: Optional[int] = None
    response_time_ms: Optional[float] = None


@dataclass
class DOMChange:
    """Captured DOM mutation."""
    timestamp: str
    type: str  # added, removed, modified
    target: str
    details: str = ""


@dataclass
class EnhancedObservation:
    """Container for all observation types."""
    console_logs: List[ConsoleMessage] = field(default_factory=list)
    network_requests: List[NetworkRequest] = field(default_factory=list)
    dom_changes: List[DOMChange] = field(default_factory=list)
    last_screenshot_b64: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "console_logs": [
                {"timestamp": c.timestamp, "type": c.type, "text": c.text[:200], "location": c.location}
                for c in self.console_logs[-20:]  # Last 20
            ],
            "network_requests": [
                {
                    "timestamp": n.timestamp,
                    "method": n.method,
                    "url": n.url[:150],
                    "resource_type": n.resource_type,
                    "status": n.status,
                    "response_time_ms": n.response_time_ms,
                }
                for n in self.network_requests[-30:]  # Last 30
            ],
            "dom_changes": [
                {"timestamp": d.timestamp, "type": d.type, "target": d.target[:100], "details": d.details[:100]}
                for d in self.dom_changes[-10:]  # Last 10
            ],
        }

    def get_summary(self) -> str:
        """Get a summary of observations for LLM context."""
        parts = []

        # Console errors/warnings
        errors = [c for c in self.console_logs if c.type in ("error", "warning")]
        if errors:
            parts.append(f"Console: {len(errors)} errors/warnings")
            for e in errors[-3:]:
                parts.append(f"  [{e.type}] {e.text[:80]}")

        # Network summary
        if self.network_requests:
            failed = [n for n in self.network_requests if n.status and n.status >= 400]
            if failed:
                parts.append(f"Network: {len(failed)} failed requests")
                for f in failed[-3:]:
                    parts.append(f"  {f.status} {f.method} {f.url[:60]}")

        return "\n".join(parts) if parts else ""


class BrowserTools:
    """Async Playwright browser operations - the action layer."""

    def __init__(
        self,
        page: Page,
        ui_server: Optional["UIServer"] = None,
        agent_id: str = "agent-1"
    ):
        self.page = page
        self.ui_server = ui_server
        self.agent_id = agent_id
        self.action_count = 0
        self.visited_urls: List[str] = []
        self.observations = EnhancedObservation()
        self._request_start_times: Dict[str, float] = {}

        # Set up event listeners for enhanced observations
        self._setup_observers()

    def _setup_observers(self):
        """Set up Playwright event listeners for console, network, dialogs, etc."""

        # Dialog handler (alert, confirm, prompt, beforeunload)
        def handle_dialog(dialog):
            """Auto-dismiss browser dialogs."""
            asyncio.create_task(self._handle_dialog(dialog))

        self.page.on("dialog", handle_dialog)

        # Console message handler
        def handle_console(msg):
            try:
                self.observations.console_logs.append(ConsoleMessage(
                    timestamp=datetime.now().isoformat(),
                    type=msg.type,
                    text=msg.text[:500],
                    location=f"{msg.location.get('url', '')}:{msg.location.get('lineNumber', '')}",
                ))
                # Keep last 100
                if len(self.observations.console_logs) > 100:
                    self.observations.console_logs = self.observations.console_logs[-100:]
            except Exception:
                pass

        # Network request handler
        def handle_request(request):
            try:
                self._request_start_times[request.url] = asyncio.get_event_loop().time()
                self.observations.network_requests.append(NetworkRequest(
                    timestamp=datetime.now().isoformat(),
                    method=request.method,
                    url=request.url[:300],
                    resource_type=request.resource_type,
                ))
            except Exception:
                pass

        # Network response handler
        def handle_response(response):
            try:
                # Find and update the matching request
                for req in reversed(self.observations.network_requests):
                    if req.url == response.url[:300] and req.status is None:
                        req.status = response.status
                        start_time = self._request_start_times.get(response.url)
                        if start_time:
                            req.response_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                        break
                # Keep last 100
                if len(self.observations.network_requests) > 100:
                    self.observations.network_requests = self.observations.network_requests[-100:]
            except Exception:
                pass

        # Register handlers
        self.page.on("console", handle_console)
        self.page.on("request", handle_request)
        self.page.on("response", handle_response)

    async def _handle_dialog(self, dialog):
        """Handle browser dialogs (alert, confirm, prompt, beforeunload)."""
        try:
            dialog_type = dialog.type
            message = dialog.message[:100] if dialog.message else ""
            logger.debug(f"Dialog [{dialog_type}]: {message}")

            # Accept confirmations, dismiss alerts
            if dialog_type in ("confirm", "beforeunload"):
                await dialog.accept()
            else:
                await dialog.dismiss()

            self.observations.console_logs.append(ConsoleMessage(
                timestamp=datetime.now().isoformat(),
                type="info",
                text=f"[Dialog dismissed] {dialog_type}: {message}",
                location="browser-dialog",
            ))
        except Exception as e:
            logger.debug(f"Failed to handle dialog: {e}")

    async def dismiss_popups(self) -> str:
        """Attempt to dismiss common popups (cookie banners, modals, etc.)."""
        dismissed = []

        # Common popup selectors to try clicking (accept/dismiss buttons)
        popup_selectors = [
            # Cookie consent - accept buttons
            'button[id*="accept"]',
            'button[id*="cookie"]',
            'button[class*="accept"]',
            'button[class*="cookie"]',
            '[aria-label*="Accept"]',
            '[aria-label*="accept"]',
            '[aria-label*="cookie"]',
            'button:has-text("Accept")',
            'button:has-text("Accept All")',
            'button:has-text("Accept Cookies")',
            'button:has-text("I Accept")',
            'button:has-text("Got it")',
            'button:has-text("OK")',
            'button:has-text("Agree")',
            'button:has-text("Allow")',
            'button:has-text("Allow All")',
            'button:has-text("Continue")',
            # GDPR
            'button:has-text("I Understand")',
            'button:has-text("Consent")',
            # Modal close buttons
            '[aria-label="Close"]',
            '[aria-label="close"]',
            'button[class*="close"]',
            'button[class*="dismiss"]',
            '.modal-close',
            '.popup-close',
            '[data-dismiss="modal"]',
            # Newsletter popups
            'button:has-text("No Thanks")',
            'button:has-text("No, thanks")',
            'button:has-text("Maybe Later")',
            'button:has-text("Not Now")',
        ]

        for selector in popup_selectors:
            try:
                # Check if element exists and is visible
                element = self.page.locator(selector).first
                if await element.is_visible(timeout=500):
                    await element.click(timeout=1000)
                    dismissed.append(selector)
                    logger.debug(f"Dismissed popup with: {selector}")
                    # Small delay to let animations complete
                    await asyncio.sleep(0.3)
                    break  # Usually one popup at a time
            except Exception:
                continue

        # Also try pressing Escape to close modals
        if not dismissed:
            try:
                await self.page.keyboard.press("Escape")
                # Check if something closed by looking for common modal overlays
                overlay = self.page.locator('[class*="overlay"], [class*="modal"], [class*="popup"]').first
                if not await overlay.is_visible(timeout=300):
                    dismissed.append("Escape key")
            except Exception:
                pass

        if dismissed:
            result = f"Dismissed popup(s): {', '.join(dismissed)}"
            self.observations.console_logs.append(ConsoleMessage(
                timestamp=datetime.now().isoformat(),
                type="info",
                text=result,
                location="popup-handler",
            ))
            return result
        return "No popups found to dismiss"

    async def wait_and_dismiss_popups(self, wait_seconds: float = 1.5) -> str:
        """Wait for page to settle, then dismiss any popups."""
        await asyncio.sleep(wait_seconds)
        return await self.dismiss_popups()

    async def setup_dom_observer(self):
        """Set up DOM mutation observer on the page."""
        try:
            await self.page.evaluate("""
                () => {
                    if (window._poisonarrObserver) return;

                    window._domChanges = [];

                    window._poisonarrObserver = new MutationObserver((mutations) => {
                        for (const mutation of mutations) {
                            if (mutation.type === 'childList') {
                                if (mutation.addedNodes.length > 0) {
                                    for (const node of mutation.addedNodes) {
                                        if (node.nodeType === 1) {  // Element node
                                            window._domChanges.push({
                                                type: 'added',
                                                target: node.tagName + (node.id ? '#' + node.id : '') + (node.className ? '.' + node.className.split(' ')[0] : ''),
                                                details: (node.textContent || '').slice(0, 100)
                                            });
                                        }
                                    }
                                }
                                if (mutation.removedNodes.length > 0) {
                                    for (const node of mutation.removedNodes) {
                                        if (node.nodeType === 1) {
                                            window._domChanges.push({
                                                type: 'removed',
                                                target: node.tagName + (node.id ? '#' + node.id : ''),
                                                details: ''
                                            });
                                        }
                                    }
                                }
                            } else if (mutation.type === 'attributes') {
                                window._domChanges.push({
                                    type: 'modified',
                                    target: mutation.target.tagName + (mutation.target.id ? '#' + mutation.target.id : ''),
                                    details: mutation.attributeName + ' changed'
                                });
                            }
                        }
                        // Keep last 50
                        if (window._domChanges.length > 50) {
                            window._domChanges = window._domChanges.slice(-50);
                        }
                    });

                    window._poisonarrObserver.observe(document.body, {
                        childList: true,
                        subtree: true,
                        attributes: true,
                        attributeFilter: ['class', 'style', 'hidden', 'disabled']
                    });
                }
            """)
        except Exception as e:
            logger.debug(f"Failed to set up DOM observer: {e}")

    async def get_dom_changes(self) -> List[DOMChange]:
        """Get DOM changes from the page and clear the buffer."""
        try:
            changes = await self.page.evaluate("""
                () => {
                    const changes = window._domChanges || [];
                    window._domChanges = [];
                    return changes;
                }
            """)
            result = []
            for c in changes:
                result.append(DOMChange(
                    timestamp=datetime.now().isoformat(),
                    type=c.get("type", "unknown"),
                    target=c.get("target", "unknown"),
                    details=c.get("details", ""),
                ))
            self.observations.dom_changes.extend(result)
            # Keep last 50
            if len(self.observations.dom_changes) > 50:
                self.observations.dom_changes = self.observations.dom_changes[-50:]
            return result
        except Exception:
            return []

    async def get_enhanced_page_info(self) -> str:
        """Get page info with enhanced observations."""
        basic_info = await self.get_page_info()

        # Get any DOM changes
        await self.get_dom_changes()

        # Get observation summary
        obs_summary = self.observations.get_summary()

        if obs_summary:
            return f"{basic_info}\n\n--- Observations ---\n{obs_summary}"
        return basic_info

    async def _record_action(self):
        """Record action to UI stats."""
        self.action_count += 1
        if self.ui_server:
            await self.ui_server.record_action(self.agent_id)

    async def click(self, selector: str, auto_dismiss_popups: bool = True, retries: int = 2) -> str:
        """Click an element on the page with retry logic."""
        async def do_click():
            old_url = self.page.url
            await self.page.click(selector, timeout=15000)
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
            return old_url

        try:
            old_url = await retry_async(
                do_click,
                max_retries=retries,
                exceptions=(Exception,),
            )
            await self._record_action()

            # If navigation occurred, try to dismiss popups
            new_url = self.page.url
            if auto_dismiss_popups and new_url != old_url:
                popup_result = await self.wait_and_dismiss_popups(wait_seconds=1.0)
                if "Dismissed" in popup_result:
                    return f"Clicked '{selector}'. Navigated to {new_url}. {popup_result}"

            return f"Clicked '{selector}'. Current URL: {new_url}"
        except Exception as e:
            return f"Click failed: {str(e)[:100]}"

    async def type_text(self, selector: str, text: str) -> str:
        """Type text into an input field."""
        try:
            await self.page.fill(selector, text, timeout=10000)
            await self._record_action()
            return f"Typed '{text[:30]}' into '{selector}'"
        except Exception as e:
            return f"Type failed: {str(e)[:100]}"

    async def scroll(self, direction: str) -> str:
        """Scroll the page."""
        try:
            if direction == "down":
                await self.page.evaluate("window.scrollBy(0, 500)")
            elif direction == "up":
                await self.page.evaluate("window.scrollBy(0, -500)")
            else:
                amount = int(direction) if direction.lstrip('-').isdigit() else 500
                await self.page.evaluate(f"window.scrollBy(0, {amount})")
            await self._record_action()
            return f"Scrolled {direction}"
        except Exception as e:
            return f"Scroll failed: {str(e)[:100]}"

    async def goto(self, url: str, auto_dismiss_popups: bool = True, retries: int = 2) -> str:
        """Navigate to a URL with retry logic and blocked domain checking."""
        if not url.startswith("http"):
            url = f"https://{url}"

        # Check if URL is blocked BEFORE attempting navigation
        if is_blocked_url(url):
            logger.warning(f"Blocked navigation to: {url}")
            return f"BLOCKED: {url} is a known CAPTCHA/login-wall site. Use a different site."

        async def do_navigate():
            await self.page.goto(url, timeout=30000)
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)

        try:
            await retry_async(
                do_navigate,
                max_retries=retries,
                exceptions=(Exception,),
            )

            final_url = self.page.url
            self.visited_urls.append(final_url)
            await self._record_action()

            # Check if we were redirected to a blocked domain
            if is_blocked_url(final_url):
                logger.warning(f"Redirected to blocked domain: {final_url}")
                return f"BLOCKED: Redirected to {final_url} which is a CAPTCHA site. Go back."

            # Check for error pages (404, 418, etc.)
            title = await self.page.title()
            if is_error_page(title):
                logger.warning(f"Landed on error page: {title}")
                return f"ERROR_PAGE: {title}. The page returned an error. Go back and try a different URL."

            # Auto-dismiss popups after navigation
            if auto_dismiss_popups:
                popup_result = await self.wait_and_dismiss_popups(wait_seconds=1.0)
                if "Dismissed" in popup_result:
                    return f"Navigated to {final_url}. {popup_result}"

            return f"Navigated to {final_url}"
        except Exception as e:
            return f"Navigation failed: {str(e)[:100]}"

    async def go_back(self) -> str:
        """Go back to previous page."""
        try:
            await self.page.go_back(timeout=15000)
            await self._record_action()
            return f"Went back. Current URL: {self.page.url}"
        except Exception as e:
            return f"Back failed: {str(e)[:100]}"

    async def wait_seconds(self, seconds: float) -> str:
        """Wait for a specified time."""
        seconds = min(float(seconds), 10)
        await asyncio.sleep(seconds)
        return f"Waited {seconds} seconds"

    async def get_accessibility_snapshot(self) -> str:
        """Get page structure using Accessibility Tree (AOM) - more stable than DOM.

        Uses Playwright's aria_snapshot() which returns ARIA-based tree representation.
        """
        try:
            # Playwright 1.58+ uses locator.aria_snapshot() instead of page.accessibility.snapshot()
            snapshot = await self.page.locator("body").aria_snapshot()

            if not snapshot:
                return "No accessibility tree available"

            # aria_snapshot returns a formatted string, limit size
            lines = snapshot.split("\n")
            if len(lines) > 80:
                lines = lines[:80] + [f"... ({len(lines) - 80} more lines)"]

            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Accessibility snapshot failed: {e}")
            return ""  # Return empty string to not clutter output

    async def check_page_validity(self) -> tuple[bool, str]:
        """Check if current page is valid and has meaningful content.

        Returns:
            Tuple of (is_valid, reason)
        """
        try:
            url = self.page.url
            title = await self.page.title()

            # Check for blocked domains
            if is_blocked_url(url):
                return False, f"Blocked domain: {url}"

            # Check for error pages
            if is_error_page(title):
                return False, f"Error page detected: {title}"

            # Check for empty/minimal content
            content_length = await self.page.evaluate("""
                () => document.body?.innerText?.trim().length || 0
            """)
            if content_length < 100:
                return False, "Page has minimal content (likely blocked or loading)"

            # Check for common block messages in body
            body_text = await self.page.evaluate("""
                () => (document.body?.innerText || '').toLowerCase().slice(0, 2000)
            """)
            block_indicators = [
                "please enable javascript",
                "enable cookies",
                "access denied",
                "you have been blocked",
                "captcha",
                "verify you are human",
                "unusual traffic",
                "too many requests",
                "rate limit",
            ]
            for indicator in block_indicators:
                if indicator in body_text:
                    return False, f"Page blocked: detected '{indicator}'"

            return True, "Page appears valid"
        except Exception as e:
            return False, f"Error checking page: {str(e)[:50]}"

    async def get_page_info(self) -> str:
        """Get current page information using content analysis."""
        try:
            url = self.page.url
            title = await self.page.title()

            # Check page validity first
            is_valid, validity_reason = await self.check_page_validity()
            if not is_valid:
                return f"URL: {url}\nTitle: {title}\n\n⚠️ PAGE PROBLEM: {validity_reason}\n\nAction: Use 'back' to go to previous page, or 'goto' to try a different URL."

            # Extract page content using JS to get meaningful elements
            page_content = await self.page.evaluate("""
                () => {
                    const results = [];

                    // Find input fields
                    document.querySelectorAll('input[type="text"], input[type="search"], input:not([type])').forEach(el => {
                        const name = el.name || el.id || el.placeholder || '';
                        if (name) results.push(`[input] name="${name}" placeholder="${el.placeholder || ''}"`);
                    });

                    // Find search results - SearXNG uses article elements, Google uses .g, etc.
                    document.querySelectorAll('article, .result, .g, .search-result').forEach((el, i) => {
                        if (i >= 10) return; // Limit to 10 results
                        // Find first link with actual URL
                        const links = el.querySelectorAll('a[href]');
                        let mainLink = null;
                        for (const link of links) {
                            if (link.href && !link.href.includes('cache') && !link.href.startsWith('#')) {
                                mainLink = link;
                                break;
                            }
                        }
                        const href = mainLink?.href || '';
                        // Find title from h3, h4, or the link text
                        const titleEl = el.querySelector('h3 a, h4 a, h3, h4');
                        const title = titleEl?.textContent?.trim()?.slice(0, 100) || mainLink?.textContent?.trim()?.slice(0, 100) || '';
                        // Find snippet
                        const snippet = el.querySelector('p')?.textContent?.trim()?.slice(0, 150) || '';

                        if (title && href && href.startsWith('http')) {
                            results.push(`[result] "${title}"`);
                            results.push(`         URL: ${href}`);
                            if (snippet) results.push(`         ${snippet.slice(0, 100)}...`);
                        }
                    });

                    // Find regular links if no results found
                    if (results.length < 3) {
                        document.querySelectorAll('a[href]').forEach((el, i) => {
                            if (i >= 15) return;
                            const text = el.textContent?.trim().slice(0, 60);
                            const href = el.href;
                            if (text && text.length > 3 && href && href.startsWith('http') && !href.includes('cache')) {
                                results.push(`[link] "${text}" -> ${href}`);
                            }
                        });
                    }

                    // Find buttons (limit to important ones)
                    document.querySelectorAll('button[aria-label]').forEach((el, i) => {
                        if (i >= 3) return;
                        const label = el.getAttribute('aria-label') || '';
                        if (label) results.push(`[button] aria-label="${label}"`);
                    });

                    return results.join('\\n');
                }
            """)

            # Also get accessibility snapshot for more reliable element targeting
            a11y_snapshot = await self.get_accessibility_snapshot()

            result = f"URL: {url}\nTitle: {title}\n\nPage Elements:\n{page_content[:3000]}"

            # Only include accessibility tree if we got one
            if a11y_snapshot:
                result += f"\n\nAccessibility Tree:\n{a11y_snapshot[:1500]}"

            return result
        except Exception as e:
            return f"Error getting page info: {str(e)[:100]}"

    async def take_screenshot_b64(self) -> str:
        """Take a screenshot and return as base64 string for vision models."""
        try:
            screenshot_bytes = await self.page.screenshot(type="png", full_page=False)
            import base64
            return base64.b64encode(screenshot_bytes).decode()
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
            return ""

    async def get_page_content(self) -> str:
        """Get full page text content for reasoning."""
        try:
            content = await self.page.evaluate("""
                () => {
                    // Remove script, style, and hidden elements
                    const clone = document.body.cloneNode(true);
                    clone.querySelectorAll('script, style, noscript, [hidden]').forEach(el => el.remove());
                    return clone.innerText;
                }
            """)
            return content[:10000]  # Limit content size
        except Exception as e:
            return f"Error getting page content: {str(e)[:100]}"


class BrowserController:
    """Manages browser lifecycle and context."""

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    ]

    def __init__(
        self,
        browser_type: Optional[BrowserType] = None,
        user_data_dir: Optional[str] = None,
        headless: bool = True,
    ):
        self.browser_type = browser_type
        self.user_data_dir = user_data_dir
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._persistent_context: Optional[BrowserContext] = None

    async def get_context(self) -> BrowserContext:
        """Get or create a browser context."""
        # Persistent context
        if self.user_data_dir and self.browser_type:
            if self._persistent_context and self._persistent_context.browser.is_connected():
                return self._persistent_context

            logger.info(f"Creating persistent browser context: {self.user_data_dir}")
            self._persistent_context = await self.browser_type.launch_persistent_context(
                self.user_data_dir,
                headless=self.headless,
                viewport={
                    "width": random.choice([1366, 1440, 1920]),
                    "height": random.choice([768, 900, 1080]),
                },
                user_agent=random.choice(self.USER_AGENTS),
                locale="en-US",
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                ],
            )
            return self._persistent_context

        # Ephemeral context
        if not self._browser or not self._browser.is_connected():
            raise RuntimeError("Browser not initialized. Call launch() first.")

        return await self._browser.new_context(
            viewport={
                "width": random.choice([1366, 1440, 1920]),
                "height": random.choice([768, 900, 1080]),
            },
            user_agent=random.choice(self.USER_AGENTS),
            locale="en-US",
        )

    async def launch(self, browser_type: BrowserType):
        """Launch browser (for non-persistent mode)."""
        self.browser_type = browser_type
        if not self.user_data_dir:
            self._browser = await browser_type.launch(
                headless=self.headless,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                ],
            )
            logger.info("Launched ephemeral browser")

    async def close(self):
        """Close browser and contexts."""
        if self._persistent_context:
            try:
                await self._persistent_context.close()
            except Exception:
                pass
            self._persistent_context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

    @property
    def is_persistent(self) -> bool:
        """Check if using persistent context."""
        return bool(self.user_data_dir)
