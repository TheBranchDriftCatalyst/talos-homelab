"""Navigator - Small/fast model for browser navigation actions.

Uses a lightweight model (7-8B) to:
- Observe page state
- Decide on browser actions (click, type, scroll, goto)
- Execute navigation sequences

This is the "hands" of the browser agent - fast, reactive, action-oriented.
"""

import asyncio
import logging
import re
import textwrap
from typing import Optional, List, Tuple, TYPE_CHECKING

from playwright.async_api import Page

from .browser import BrowserTools
from ..utils.tokens import TokenTracker, count_message_tokens
from ..prompts import load_prompt

try:
    from langchain_ollama import ChatOllama
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

if TYPE_CHECKING:
    from ..server import UIServer

logger = logging.getLogger(__name__)
prompt_logger = logging.getLogger(f"{__name__}.prompts")


class PromptDebugger:
    """Debug logger for LLM prompts and responses."""

    SEPARATOR = "-" * 80
    DOUBLE_SEP = "=" * 80

    @classmethod
    def log_request(cls, messages: List[dict], model: str, step: int):
        """Log the outgoing prompt to the LLM."""
        if not prompt_logger.isEnabledFor(logging.DEBUG):
            return

        lines = [
            "",
            cls.DOUBLE_SEP,
            f"[NAV] LLM REQUEST (Step {step}) | Model: {model}",
            cls.DOUBLE_SEP,
        ]

        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")

            role_emoji = {"SYSTEM": "SYS", "USER": "USR", "ASSISTANT": "AST"}.get(role, "???")
            lines.append(f"\n[{role_emoji}]")
            lines.append(cls.SEPARATOR)

            if len(content) > 500:
                wrapped = content[:300] + "\n... [truncated] ...\n" + content[-100:]
            else:
                wrapped = content

            for line in wrapped.split('\n'):
                lines.append(f"  {line}")

        lines.append(cls.SEPARATOR)
        prompt_logger.debug('\n'.join(lines))

    @classmethod
    def log_response(cls, response_text: str, step: int, parsed_action: Optional[tuple] = None):
        """Log the LLM response with parsed action."""
        if not prompt_logger.isEnabledFor(logging.DEBUG):
            return

        lines = [
            "",
            cls.DOUBLE_SEP,
            f"[NAV] LLM RESPONSE (Step {step})",
            cls.DOUBLE_SEP,
        ]

        thought_match = re.search(r'THOUGHT:\s*(.+?)(?:ACTION:|$)', response_text, re.IGNORECASE | re.DOTALL)
        if thought_match:
            lines.append("\n[THOUGHT]")
            lines.append(cls.SEPARATOR)
            thought = thought_match.group(1).strip()
            for line in textwrap.wrap(thought, width=76):
                lines.append(f"  {line}")

        action_match = re.search(r'ACTION:\s*(.+?)(?:\n|$)', response_text, re.IGNORECASE)
        if action_match:
            lines.append("\n[ACTION]")
            lines.append(cls.SEPARATOR)
            lines.append(f"  Raw: {action_match.group(1).strip()}")

            if parsed_action:
                tool_name, args = parsed_action
                lines.append(f"  Tool: {tool_name}")
                if args:
                    lines.append(f"  Args: {args}")

        if not thought_match and not action_match:
            lines.append("\n[RAW]")
            lines.append(cls.SEPARATOR)
            for line in response_text.split('\n')[:20]:
                lines.append(f"  {line}")

        lines.append(cls.SEPARATOR)
        prompt_logger.debug('\n'.join(lines))

    @classmethod
    def log_tool_result(cls, tool_name: str, args: list, result: str, step: int):
        """Log tool execution result."""
        if not prompt_logger.isEnabledFor(logging.DEBUG):
            return

        lines = [
            "",
            cls.SEPARATOR,
            f"[NAV] TOOL RESULT (Step {step})",
            cls.SEPARATOR,
            f"  Tool: {tool_name}",
            f"  Args: {args}",
            f"  Result: {result[:500]}{'...' if len(result) > 500 else ''}",
            cls.SEPARATOR,
        ]
        prompt_logger.debug('\n'.join(lines))




class Navigator:
    """Browser navigation agent using a small/fast model.

    Handles the reactive navigation loop:
    1. Observe page state
    2. Decide on action
    3. Execute action
    4. Repeat until goal achieved
    """

    # Context window management settings
    MAX_CONTEXT_MESSAGES = 20  # Keep last N messages
    MAX_MESSAGE_LENGTH = 2000  # Truncate long messages
    SUMMARIZE_THRESHOLD = 15  # Summarize when exceeding this

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        base_url: str = "http://localhost:11434",
        ui_server: Optional["UIServer"] = None,
        agent_id: str = "agent-1",
    ):
        self.model = model
        self.base_url = base_url
        self.ui_server = ui_server
        self.agent_id = agent_id
        self.history: List[dict] = []

        self.llm = self._create_llm(model)
        self.token_tracker = TokenTracker(model=model)

    def _create_llm(self, model: str):
        """Create LLM client."""
        model_name = model.split("/")[-1] if "/" in model else model
        logger.info(f"Navigator LLM: ChatOllama ({model_name}) with 32K context")
        return ChatOllama(
            model=model_name,
            temperature=0.1,
            num_predict=1000,   # Max output tokens (responses are short action commands)
            num_ctx=32000,      # 32K context window for large accessibility trees
        )

    def update_model(self, model: str):
        """Update the model used by this navigator."""
        if model != self.model:
            logger.info(f"Updating Navigator model: {self.model} -> {model}")
            self.model = model
            self.llm = self._create_llm(model)

    async def _set_stage(self, stage: str):
        """Update ReAct stage in UI."""
        if self.ui_server:
            await self.ui_server.update_react_stage(self.agent_id, stage)

    def _check_restart(self) -> bool:
        """Check if restart/skip was requested."""
        if self.ui_server:
            return self.ui_server.check_restart_requested(self.agent_id)
        return False

    def _truncate_message(self, content: str) -> str:
        """Truncate a message to MAX_MESSAGE_LENGTH."""
        if len(content) <= self.MAX_MESSAGE_LENGTH:
            return content
        # Keep beginning and end for context
        half = self.MAX_MESSAGE_LENGTH // 2 - 20
        return content[:half] + "\n...[truncated]...\n" + content[-half:]

    def _manage_context(self, messages: List[dict]) -> List[dict]:
        """Manage context window by truncating/summarizing old messages.

        Best practice: Prevent unbounded context growth by:
        1. Truncating individual long messages
        2. Keeping only recent conversation turns
        3. Preserving system prompt and goal
        """
        if len(messages) <= 3:  # system + goal + maybe one exchange
            return messages

        # Always keep: system prompt (0) and initial goal (1)
        system_msg = messages[0]
        goal_msg = messages[1]

        # Get conversation messages (after system + goal)
        conversation = messages[2:]

        # Truncate individual messages
        for msg in conversation:
            if isinstance(msg.get("content"), str):
                msg["content"] = self._truncate_message(msg["content"])

        # If too many messages, keep only recent ones
        if len(conversation) > self.MAX_CONTEXT_MESSAGES:
            # Create a summary of dropped messages
            dropped_count = len(conversation) - self.MAX_CONTEXT_MESSAGES
            summary = f"[Previous {dropped_count} exchanges summarized: Agent navigated and took actions]"

            # Keep system, goal, summary, and recent messages
            recent = conversation[-self.MAX_CONTEXT_MESSAGES:]
            return [
                system_msg,
                goal_msg,
                {"role": "user", "content": summary},
            ] + recent

        return [system_msg, goal_msg] + conversation

    def _parse_action(self, text: str) -> Optional[Tuple[str, list]]:
        """Parse ACTION: tool|||arg1|||arg2 format from LLM response.

        Handles edge cases:
        - Multiple ACTION lines (takes first valid one)
        - Malformed separators
        - Extra whitespace
        """
        # Find all ACTION lines
        action_matches = re.findall(r'ACTION:\s*(.+?)(?:\n|$)', text, re.IGNORECASE)

        if not action_matches:
            return None

        # Warn if multiple actions found
        if len(action_matches) > 1:
            logger.warning(f"Multiple actions in response, using first: {action_matches}")

        # Parse the first action
        action_line = action_matches[0].strip()

        # Handle edge case where model adds extra text after action
        # e.g., "page_info|||WAIT FOR PAGE" should just be "page_info"
        if "|||" in action_line:
            parts = action_line.split('|||')
            tool_name = parts[0].strip().lower()
            args = [p.strip() for p in parts[1:] if p.strip()]
        else:
            # No separator, just tool name
            tool_name = action_line.split()[0].strip().lower() if action_line else ""
            args = []

        # Validate tool name (remove any trailing garbage)
        tool_name = re.sub(r'[^a-z_].*', '', tool_name)

        if not tool_name:
            return None

        return tool_name, args

    async def _execute_tool(self, browser_tools: BrowserTools, tool_name: str, args: list) -> str:
        """Execute a tool with given arguments."""
        try:
            if tool_name == "page_info":
                return await browser_tools.get_page_info()
            elif tool_name == "click" and args:
                return await browser_tools.click(args[0])
            elif tool_name == "type_text" and len(args) >= 2:
                return await browser_tools.type_text(args[0], args[1])
            elif tool_name == "scroll":
                direction = args[0] if args else "down"
                return await browser_tools.scroll(direction)
            elif tool_name == "goto" and args:
                return await browser_tools.goto(args[0])
            elif tool_name == "back":
                return await browser_tools.go_back()
            elif tool_name == "wait":
                seconds = float(args[0]) if args else 2
                return await browser_tools.wait_seconds(seconds)
            elif tool_name == "dismiss_popups":
                return await browser_tools.dismiss_popups()
            elif tool_name == "done":
                return "DONE:" + (args[0] if args else "Task completed")
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            return f"Tool error: {str(e)[:100]}"

    async def navigate(
        self,
        page: Page,
        goal: str,
        max_steps: int = 20,
        timeout: int = 300,
    ) -> Tuple[bool, str, BrowserTools]:
        """Navigate to achieve a goal.

        Args:
            page: Playwright page to control
            goal: What to achieve (e.g., "search for python tutorials")
            max_steps: Maximum navigation steps
            timeout: Session timeout in seconds

        Returns:
            Tuple of (success, summary, browser_tools)
        """
        logger.info(f"Navigator goal: {goal[:50]}...")
        self.history = []

        browser_tools = BrowserTools(page, self.ui_server, self.agent_id)

        # Set up DOM observer for enhanced observations
        await browser_tools.setup_dom_observer()

        # Load system prompt from markdown file
        system_prompt = load_prompt("navigator")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Your goal: {goal}"}
        ]

        summary = "No actions taken"

        try:
            async with asyncio.timeout(timeout):
                for step in range(max_steps):
                    await self._set_stage("reason")

                    if self._check_restart():
                        await self._set_stage("idle")
                        return False, "Skipped by user", browser_tools

                    # Debug: log outgoing request
                    PromptDebugger.log_request(messages, self.model, step)

                    # Get LLM response
                    response = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self.llm.invoke(messages)
                    )

                    text = response.content if hasattr(response, 'content') else str(response)
                    logger.debug(f"Step {step}: LLM response: {text[:150]}")

                    # Parse action first for debug log
                    action = self._parse_action(text)
                    PromptDebugger.log_response(text, step, action)

                    # Log thought to UI
                    thought_match = re.search(r'THOUGHT:\s*(.+?)(?:ACTION:|$)', text, re.IGNORECASE | re.DOTALL)
                    if thought_match and self.ui_server:
                        thought = thought_match.group(1).strip()[:100]
                        await self.ui_server.add_log(self.agent_id, "info", f"[NAV] {thought}")

                    if not action:
                        logger.warning(f"No action parsed from: {text[:100]}")
                        messages.append({"role": "assistant", "content": text})
                        messages.append({"role": "user", "content": "Please respond with ACTION: followed by the tool and arguments."})
                        continue

                    tool_name, args = action
                    logger.info(f"Executing: {tool_name}({args})")

                    if self.ui_server:
                        args_str = ', '.join(str(a)[:30] for a in args)
                        await self.ui_server.add_log(self.agent_id, "debug", f"[NAV] {tool_name}({args_str})")

                    await self._set_stage("act")

                    # Execute tool
                    result = await self._execute_tool(browser_tools, tool_name, args)
                    logger.debug(f"Tool result: {result[:100]}")

                    PromptDebugger.log_tool_result(tool_name, args, result, step)

                    # Check for done
                    if result.startswith("DONE:"):
                        summary = result[5:]
                        logger.info(f"Navigator done: {summary[:100]}")
                        break

                    # Check for blocked/error conditions and add recovery hints
                    recovery_hint = ""
                    if result.startswith("BLOCKED:"):
                        recovery_hint = "\n\n⚠️ RECOVERY REQUIRED: The site is blocked. Use 'back' to go back or 'goto' to navigate directly to a working site like cnn.com, github.com, or amazon.com."
                        logger.warning(f"Navigation blocked, adding recovery hint")
                    elif result.startswith("ERROR_PAGE:"):
                        recovery_hint = "\n\n⚠️ RECOVERY REQUIRED: You hit an error page. Use 'back' immediately to return to the previous page."
                        logger.warning(f"Error page detected, adding recovery hint")
                    elif "PAGE PROBLEM:" in result:
                        recovery_hint = "\n\n⚠️ RECOVERY REQUIRED: This page has a problem. Use 'back' to leave."
                        logger.warning(f"Page problem detected, adding recovery hint")

                    # Add to conversation
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": f"Result: {result[:1000]}{recovery_hint}"})

                    # Manage context window to prevent unbounded growth
                    messages = self._manage_context(messages)

                    # Record stats with accurate token counting
                    self.token_tracker.record_messages(messages, text)
                    if self.ui_server:
                        stats = self.token_tracker.get_stats()
                        await self.ui_server.record_llm_call(
                            self.agent_id,
                            prompt_tokens=stats["prompt_tokens"],
                            completion_tokens=stats["completion_tokens"],
                            context_size=count_message_tokens(messages, self.model)
                        )

                await self._set_stage("idle")

                self.history.append({
                    "goal": goal,
                    "output": summary,
                    "actions_taken": browser_tools.action_count,
                    "urls_visited": browser_tools.visited_urls,
                })

                return True, summary, browser_tools

        except asyncio.TimeoutError:
            logger.warning(f"Navigator timeout after {timeout}s")
            await self._set_stage("idle")
            return False, "Session timeout", browser_tools
        except Exception as e:
            logger.error(f"Navigator error: {e}")
            await self._set_stage("idle")
            return False, f"Error: {str(e)[:50]}", browser_tools

    async def search_and_click(
        self,
        page: Page,
        query: str,
        max_results: int = 3,
    ) -> List[str]:
        """Search for something and return URLs of clicked results.

        Useful for gathering pages to process with the Reasoner.
        """
        goal = f"Search for '{query}' and click on the top {max_results} relevant results"
        success, summary, tools = await self.navigate(page, goal)
        return tools.visited_urls
