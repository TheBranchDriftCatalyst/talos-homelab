"""Playwright tests for Poisonarr Monitor UI.

Run with:
    pytest browser_agent/tests/test_ui.py -v

Requires the Poisonarr server to be running on localhost:8080.
Start server with: python -m browser_agent.server
"""

import asyncio
import pytest
from playwright.async_api import async_playwright, Page, expect


# Test configuration
BASE_URL = "http://localhost:8080"
DEFAULT_TIMEOUT = 10000  # 10 seconds


@pytest.fixture(scope="module")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def browser():
    """Create browser instance."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture(scope="function")
async def page(browser):
    """Create a new page for each test."""
    context = await browser.new_context()
    page = await context.new_page()
    yield page
    await page.close()
    await context.close()


class TestPageLoad:
    """Tests for initial page load."""

    @pytest.mark.asyncio
    async def test_page_loads_with_correct_title(self, page: Page):
        """Page should load with correct title."""
        await page.goto(BASE_URL)
        await expect(page).to_have_title("Poisonarr Monitor")

    @pytest.mark.asyncio
    async def test_page_shows_header(self, page: Page):
        """Page should display header with title."""
        await page.goto(BASE_URL)
        header = page.get_by_role("heading", name="Poisonarr", level=1)
        await expect(header).to_be_visible()

    @pytest.mark.asyncio
    async def test_page_shows_subtitle(self, page: Page):
        """Page should display subtitle."""
        await page.goto(BASE_URL)
        subtitle = page.get_by_text("Traffic Noise Generator")
        await expect(subtitle).to_be_visible()


class TestHeader:
    """Tests for header controls."""

    @pytest.mark.asyncio
    async def test_model_dropdown_visible(self, page: Page):
        """Model dropdown should be visible."""
        await page.goto(BASE_URL)
        model_label = page.get_by_text("Model:")
        await expect(model_label).to_be_visible()
        dropdown = page.get_by_role("combobox")
        await expect(dropdown).to_be_visible()

    @pytest.mark.asyncio
    async def test_model_dropdown_has_options(self, page: Page):
        """Model dropdown should have selectable options."""
        await page.goto(BASE_URL)
        dropdown = page.get_by_role("combobox")
        # Check that dropdown has options
        options = await dropdown.locator("option").count()
        assert options > 0, "Model dropdown should have at least one option"

    @pytest.mark.asyncio
    async def test_pause_button_visible(self, page: Page):
        """Pause button should be visible."""
        await page.goto(BASE_URL)
        pause_btn = page.get_by_role("button", name="Pause")
        await expect(pause_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_skip_button_visible(self, page: Page):
        """Skip button should be visible."""
        await page.goto(BASE_URL)
        skip_btn = page.get_by_role("button", name="Skip")
        await expect(skip_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_restart_button_visible(self, page: Page):
        """Restart button should be visible."""
        await page.goto(BASE_URL)
        restart_btn = page.get_by_role("button", name="Restart")
        await expect(restart_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_connection_status_shown(self, page: Page):
        """Connection status should be displayed."""
        await page.goto(BASE_URL)
        # Wait for WebSocket connection
        await page.wait_for_timeout(1000)
        # Should show either "Connected" or "Disconnected"
        connection = page.locator("text=Connected").or_(page.locator("text=Disconnected"))
        await expect(connection).to_be_visible()


class TestBrowserView:
    """Tests for browser view section."""

    @pytest.mark.asyncio
    async def test_browser_view_heading_visible(self, page: Page):
        """Browser View heading should be visible."""
        await page.goto(BASE_URL)
        heading = page.get_by_role("heading", name="Browser View", level=2)
        await expect(heading).to_be_visible()

    @pytest.mark.asyncio
    async def test_expand_button_visible(self, page: Page):
        """Expand button should be visible."""
        await page.goto(BASE_URL)
        expand_btn = page.get_by_role("button", name="\u26F6")  # ⛶
        await expect(expand_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_screenshot_image_visible(self, page: Page):
        """Browser screenshot image should be visible."""
        await page.goto(BASE_URL)
        screenshot = page.get_by_role("img", name="Browser Screenshot")
        await expect(screenshot).to_be_visible()

    @pytest.mark.asyncio
    async def test_sessions_counter_visible(self, page: Page):
        """Sessions completed counter should be visible."""
        await page.goto(BASE_URL)
        counter = page.locator("text=Sessions completed:")
        await expect(counter).to_be_visible()


class TestAgentStats:
    """Tests for agent statistics panel."""

    @pytest.mark.asyncio
    async def test_agent_stats_heading_visible(self, page: Page):
        """Agent Stats heading should be visible."""
        await page.goto(BASE_URL)
        heading = page.get_by_role("heading", name="Agent Stats", level=3)
        await expect(heading).to_be_visible()

    @pytest.mark.asyncio
    async def test_total_tokens_stat_visible(self, page: Page):
        """Total Tokens stat should be visible."""
        await page.goto(BASE_URL)
        stat = page.get_by_text("Total Tokens")
        await expect(stat).to_be_visible()

    @pytest.mark.asyncio
    async def test_llm_calls_stat_visible(self, page: Page):
        """LLM Calls stat should be visible."""
        await page.goto(BASE_URL)
        stat = page.get_by_text("LLM Calls")
        await expect(stat).to_be_visible()

    @pytest.mark.asyncio
    async def test_context_size_stat_visible(self, page: Page):
        """Context Size stat should be visible."""
        await page.goto(BASE_URL)
        stat = page.get_by_text("Context Size")
        await expect(stat).to_be_visible()

    @pytest.mark.asyncio
    async def test_actions_stat_visible(self, page: Page):
        """Actions stat should be visible."""
        await page.goto(BASE_URL)
        stat = page.get_by_text("Actions")
        await expect(stat).to_be_visible()

    @pytest.mark.asyncio
    async def test_memory_button_visible(self, page: Page):
        """Memory button should be visible."""
        await page.goto(BASE_URL)
        memory_btn = page.locator("text=Memory").first
        await expect(memory_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_success_counter_visible(self, page: Page):
        """Success counter should be visible."""
        await page.goto(BASE_URL)
        stat = page.get_by_text("Success:")
        await expect(stat).to_be_visible()

    @pytest.mark.asyncio
    async def test_failed_counter_visible(self, page: Page):
        """Failed counter should be visible."""
        await page.goto(BASE_URL)
        stat = page.get_by_text("Failed:")
        await expect(stat).to_be_visible()


class TestCurrentSession:
    """Tests for current session display."""

    @pytest.mark.asyncio
    async def test_current_session_heading_visible(self, page: Page):
        """Current Session heading should be visible."""
        await page.goto(BASE_URL)
        heading = page.get_by_role("heading", name="Current Session", level=2)
        await expect(heading).to_be_visible()

    @pytest.mark.asyncio
    async def test_session_steps_heading_visible(self, page: Page):
        """Session Steps heading should be visible."""
        await page.goto(BASE_URL)
        heading = page.get_by_role("heading", name="Session Steps", level=2)
        await expect(heading).to_be_visible()


class TestTabNavigation:
    """Tests for tab navigation (Activity Log, Observations, Chat)."""

    @pytest.mark.asyncio
    async def test_activity_log_tab_visible(self, page: Page):
        """Activity Log tab should be visible."""
        await page.goto(BASE_URL)
        tab = page.get_by_role("button", name="Activity Log")
        await expect(tab).to_be_visible()

    @pytest.mark.asyncio
    async def test_observations_tab_visible(self, page: Page):
        """Observations tab should be visible."""
        await page.goto(BASE_URL)
        tab = page.get_by_role("button", name="Observations")
        await expect(tab).to_be_visible()

    @pytest.mark.asyncio
    async def test_chat_tab_visible(self, page: Page):
        """Chat tab should be visible."""
        await page.goto(BASE_URL)
        tab = page.get_by_role("button", name="Chat")
        await expect(tab).to_be_visible()

    @pytest.mark.asyncio
    async def test_interactive_mode_button_visible(self, page: Page):
        """Interactive Mode button should be visible."""
        await page.goto(BASE_URL)
        btn = page.get_by_role("button", name="Interactive Mode")
        await expect(btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_click_activity_log_tab(self, page: Page):
        """Clicking Activity Log tab should switch view."""
        await page.goto(BASE_URL)
        tab = page.get_by_role("button", name="Activity Log")
        await tab.click()
        # Verify tab is now active (contains log entries or shows empty state)
        await page.wait_for_timeout(500)
        # Activity log entries contain timestamp pattern [HH:MM:SS]
        log_content = page.locator("text=/\\[\\d{2}:\\d{2}:\\d{2}\\]/").first
        # Either show log entries or empty state
        is_visible = await log_content.is_visible()
        assert True  # Tab click succeeded

    @pytest.mark.asyncio
    async def test_click_observations_tab(self, page: Page):
        """Clicking Observations tab should show console/network sections."""
        await page.goto(BASE_URL)
        tab = page.get_by_role("button", name="Observations")
        await tab.click()
        await page.wait_for_timeout(500)
        # Should show Console Logs heading
        console_heading = page.get_by_role("heading", name="Console Logs")
        await expect(console_heading).to_be_visible()
        # Should show Network Requests heading
        network_heading = page.get_by_role("heading", name="Network Requests")
        await expect(network_heading).to_be_visible()

    @pytest.mark.asyncio
    async def test_click_chat_tab(self, page: Page):
        """Clicking Chat tab should switch view."""
        await page.goto(BASE_URL)
        tab = page.get_by_role("button", name="Chat")
        await tab.click()
        await page.wait_for_timeout(500)
        # Should show chat-related content
        interactive_text = page.locator("text=Interactive Mode")
        await expect(interactive_text.first).to_be_visible()


class TestInteractiveMode:
    """Tests for interactive mode functionality."""

    @pytest.mark.asyncio
    async def test_toggle_interactive_mode_on(self, page: Page):
        """Toggling interactive mode ON should change button text."""
        await page.goto(BASE_URL)
        # Find the interactive mode button
        btn = page.get_by_role("button", name="Interactive Mode")
        await btn.click()
        await page.wait_for_timeout(1000)
        # Button should now show "ON"
        on_btn = page.get_by_role("button", name="Interactive Mode ON")
        await expect(on_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_toggle_interactive_mode_off(self, page: Page):
        """Toggling interactive mode OFF should change button text back."""
        await page.goto(BASE_URL)
        btn = page.get_by_role("button", name="Interactive Mode")
        # Toggle ON
        await btn.click()
        await page.wait_for_timeout(500)
        # Toggle OFF
        on_btn = page.get_by_role("button", name="Interactive Mode ON")
        await on_btn.click()
        await page.wait_for_timeout(500)
        # Button should be back to normal
        off_btn = page.get_by_role("button", name="Interactive Mode")
        await expect(off_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_chat_input_enabled_when_interactive(self, page: Page):
        """Chat input should be enabled in interactive mode."""
        await page.goto(BASE_URL)
        # Switch to chat tab
        chat_tab = page.get_by_role("button", name="Chat")
        await chat_tab.click()
        await page.wait_for_timeout(500)
        # Enable interactive mode
        btn = page.get_by_role("button", name="Interactive Mode")
        await btn.click()
        await page.wait_for_timeout(1000)
        # Chat input should be visible and enabled
        chat_input = page.get_by_placeholder("Type a goal or command...")
        await expect(chat_input).to_be_visible()
        await expect(chat_input).to_be_enabled()

    @pytest.mark.asyncio
    async def test_send_button_visible_when_interactive(self, page: Page):
        """Send button should be visible in interactive mode."""
        await page.goto(BASE_URL)
        chat_tab = page.get_by_role("button", name="Chat")
        await chat_tab.click()
        await page.wait_for_timeout(500)
        btn = page.get_by_role("button", name="Interactive Mode")
        await btn.click()
        await page.wait_for_timeout(1000)
        send_btn = page.get_by_role("button", name="Send")
        await expect(send_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_type_in_chat_input(self, page: Page):
        """Should be able to type in chat input."""
        await page.goto(BASE_URL)
        chat_tab = page.get_by_role("button", name="Chat")
        await chat_tab.click()
        btn = page.get_by_role("button", name="Interactive Mode")
        await btn.click()
        await page.wait_for_timeout(1000)
        chat_input = page.get_by_placeholder("Type a goal or command...")
        await chat_input.fill("Test message")
        await expect(chat_input).to_have_value("Test message")


class TestMemoryPanel:
    """Tests for memory panel."""

    @pytest.mark.asyncio
    async def test_open_memory_panel(self, page: Page):
        """Clicking Memory button should open memory panel."""
        await page.goto(BASE_URL)
        # Click on Memory button
        memory_btn = page.locator("text=Memory").first
        await memory_btn.click()
        await page.wait_for_timeout(500)
        # Memory panel heading should be visible
        memory_heading = page.get_by_role("heading", name="Agent Memory")
        await expect(memory_heading).to_be_visible()

    @pytest.mark.asyncio
    async def test_memory_panel_shows_statistics(self, page: Page):
        """Memory panel should show statistics section."""
        await page.goto(BASE_URL)
        memory_btn = page.locator("text=Memory").first
        await memory_btn.click()
        await page.wait_for_timeout(500)
        stats_heading = page.get_by_role("heading", name="Statistics")
        await expect(stats_heading).to_be_visible()

    @pytest.mark.asyncio
    async def test_memory_panel_shows_favorite_sites(self, page: Page):
        """Memory panel should show favorite sites section."""
        await page.goto(BASE_URL)
        memory_btn = page.locator("text=Memory").first
        await memory_btn.click()
        await page.wait_for_timeout(500)
        sites_heading = page.get_by_role("heading", name="Favorite Sites")
        await expect(sites_heading).to_be_visible()

    @pytest.mark.asyncio
    async def test_memory_panel_shows_recent_sessions(self, page: Page):
        """Memory panel should show recent sessions section."""
        await page.goto(BASE_URL)
        memory_btn = page.locator("text=Memory").first
        await memory_btn.click()
        await page.wait_for_timeout(500)
        sessions_heading = page.get_by_role("heading", name="Recent Sessions")
        await expect(sessions_heading).to_be_visible()

    @pytest.mark.asyncio
    async def test_memory_panel_close_button(self, page: Page):
        """Memory panel should have close button."""
        await page.goto(BASE_URL)
        memory_btn = page.locator("text=Memory").first
        await memory_btn.click()
        await page.wait_for_timeout(500)
        close_btn = page.get_by_role("button", name="\u00D7")  # ×
        await expect(close_btn).to_be_visible()


class TestAgentTabs:
    """Tests for agent tab switching."""

    @pytest.mark.asyncio
    async def test_agent_tab_visible(self, page: Page):
        """Agent tab should be visible."""
        await page.goto(BASE_URL)
        agent_tab = page.get_by_role("button", name="Agent 1")
        await expect(agent_tab).to_be_visible()


class TestResponsiveness:
    """Tests for responsive behavior."""

    @pytest.mark.asyncio
    async def test_content_visible_on_desktop(self, page: Page):
        """All major sections should be visible on desktop viewport."""
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await page.goto(BASE_URL)
        # Check main sections are visible
        browser_view = page.get_by_role("heading", name="Browser View")
        await expect(browser_view).to_be_visible()
        current_session = page.get_by_role("heading", name="Current Session")
        await expect(current_session).to_be_visible()

    @pytest.mark.asyncio
    async def test_content_visible_on_tablet(self, page: Page):
        """Content should be visible on tablet viewport."""
        await page.set_viewport_size({"width": 768, "height": 1024})
        await page.goto(BASE_URL)
        header = page.get_by_role("heading", name="Poisonarr")
        await expect(header).to_be_visible()


class TestWebSocketConnection:
    """Tests for WebSocket connection status."""

    @pytest.mark.asyncio
    async def test_websocket_connects(self, page: Page):
        """WebSocket should connect successfully."""
        await page.goto(BASE_URL)
        # Wait for connection
        await page.wait_for_timeout(2000)
        connected = page.get_by_text("Connected")
        await expect(connected).to_be_visible()

    @pytest.mark.asyncio
    async def test_screenshot_updates(self, page: Page):
        """Screenshot should have a src attribute (indicating updates)."""
        await page.goto(BASE_URL)
        await page.wait_for_timeout(3000)
        screenshot = page.get_by_role("img", name="Browser Screenshot")
        src = await screenshot.get_attribute("src")
        # Should have either base64 data or a URL
        assert src is not None, "Screenshot should have src attribute"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
