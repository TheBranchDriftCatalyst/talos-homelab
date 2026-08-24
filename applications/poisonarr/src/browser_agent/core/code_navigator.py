"""Code Navigator - LLM generates Playwright code for browser automation.

Instead of rigid tool commands, the LLM generates actual Python/Playwright code
that gets executed against the page. This allows for:
- Flexible selector strategies with fallbacks
- Chained actions (click + fill + submit)
- Error handling with try/except
- JavaScript evaluation for complex DOM manipulation
- Smart waits and assertions

Supports two execution modes:
- Classic: Direct ReAct loop (observe->think->act)
- Graph: LangGraph-based orchestration with reflexion and planning
"""

import asyncio
import logging
import re
import traceback
from typing import Optional, List, Tuple, Dict, Any, TYPE_CHECKING

from playwright.async_api import Page, Locator, TimeoutError as PlaywrightTimeout

from pathlib import Path

from .browser import BrowserTools
from .error_tracker import PlaywrightErrorTracker
from ..utils.tokens import TokenTracker, count_message_tokens
from ..prompts import load_prompt

try:
    from langchain_ollama import ChatOllama
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

# Check for graph support
try:
    from ..graph import GraphRunner, PatternLibrary
    from ..graph.builder import create_graph_runner_from_navigator
    HAS_GRAPH = True
except ImportError:
    HAS_GRAPH = False

if TYPE_CHECKING:
    from ..server import UIServer
    from ..config import BrowserAgentConfig

logger = logging.getLogger(__name__)


class CodeExecutionError(Exception):
    """Error during code execution."""
    pass


class CodeNavigator:
    """Navigator that uses LLM-generated Playwright code.

    Supports two execution modes:
    - Classic (use_graph=False): Direct ReAct loop
    - Graph (use_graph=True): LangGraph orchestration with reflexion/planning
    """

    MAX_STEPS = 25
    MAX_CODE_LENGTH = 2000
    EXECUTION_TIMEOUT = 30  # seconds per code block

    def __init__(
        self,
        model: str = "ollama/qwen2.5:14b",
        base_url: str = "http://localhost:11434",
        ui_server: Optional["UIServer"] = None,
        agent_id: str = "agent-1",
        error_persist_path: Optional[Path] = None,
        use_graph: bool = False,
        config: Optional["BrowserAgentConfig"] = None,
    ):
        self.model = model
        self.base_url = base_url
        self.ui_server = ui_server
        self.agent_id = agent_id
        self.history: List[dict] = []
        self.use_graph = use_graph and HAS_GRAPH
        self.config = config

        self.llm = self._create_llm(model)
        self.token_tracker = TokenTracker(model=model)

        # Error tracker for learning from mistakes
        persist_path = error_persist_path or Path("/tmp/poisonarr-error-memory.json")
        self.error_tracker = PlaywrightErrorTracker(persist_path=persist_path)
        self._last_failed_code: Optional[str] = None

        # Graph runner (lazy initialized)
        self._graph_runner: Optional["GraphRunner"] = None
        self._pattern_library: Optional["PatternLibrary"] = None

        if self.use_graph:
            logger.info("CodeNavigator: Graph mode enabled")
        else:
            logger.info("CodeNavigator: Classic ReAct mode")

    def _get_graph_runner(self, reasoner=None) -> "GraphRunner":
        """Get or create the graph runner.

        Args:
            reasoner: Optional Reasoner instance for reflexion

        Returns:
            GraphRunner instance
        """
        # Get reasoner LLM
        reasoner_llm = None
        if reasoner and hasattr(reasoner, 'llm'):
            reasoner_llm = reasoner.llm
            logger.info(f"[GRAPH] Reasoner LLM available: {reasoner.model}")

        if self._graph_runner is None:
            from ..graph import GraphRunner, PatternLibrary

            # Create pattern library
            pattern_path = None
            if self.config and self.config.planning.enabled:
                pattern_path = Path(self.config.planning.pattern_library_path)
            elif self.config:
                pattern_path = Path("/tmp/poisonarr-patterns.json")

            if pattern_path:
                self._pattern_library = PatternLibrary(persist_path=pattern_path)

            # Load system prompt
            system_prompt = load_prompt("code_navigator")

            self._graph_runner = GraphRunner(
                llm=self.llm,
                reasoner_llm=reasoner_llm,
                pattern_library=self._pattern_library,
                system_prompt=system_prompt,
                ui_server=self.ui_server,
                error_tracker=self.error_tracker,
            )
        elif reasoner_llm and self._graph_runner.reasoner_llm is None:
            # Update reasoner if it wasn't available before
            logger.info("[GRAPH] Updating graph runner with reasoner LLM")
            self._graph_runner.reasoner_llm = reasoner_llm
            self._graph_runner.graph.reasoner_llm = reasoner_llm

        return self._graph_runner

    def _create_llm(self, model: str):
        """Create LLM client."""
        model_name = model.split("/")[-1] if "/" in model else model
        logger.info(f"CodeNavigator LLM: ChatOllama ({model_name}) with 32K context")
        return ChatOllama(
            model=model_name,
            temperature=0.1,
            num_predict=1500,   # More tokens for code generation
            num_ctx=32000,      # 32K context window
        )

    def update_model(self, model: str):
        """Update the model used by this navigator."""
        if model != self.model:
            logger.info(f"Updating CodeNavigator model: {self.model} -> {model}")
            self.model = model
            self.llm = self._create_llm(model)

    async def _log(self, level: str, message: str):
        """Log to UI and logger."""
        log_fn = getattr(logger, level, logger.info)
        log_fn(f"[CODE-NAV] {message}")
        if self.ui_server:
            await self.ui_server.add_log(self.agent_id, level, f"[CODE] {message}")

    async def _update_stage(self, stage: str):
        """Update ReAct stage in UI."""
        if self.ui_server:
            await self.ui_server.update_react_stage(self.agent_id, stage)

    def _extract_code(self, response: str) -> Optional[str]:
        """Extract Python code from LLM response."""
        # Look for code blocks
        code_match = re.search(r'```python\s*(.*?)\s*```', response, re.DOTALL)
        if code_match:
            code = code_match.group(1).strip()
            return self._fix_common_mistakes(code)

        # Try generic code block
        code_match = re.search(r'```\s*(.*?)\s*```', response, re.DOTALL)
        if code_match:
            code = code_match.group(1).strip()
            # Check if it looks like Python
            if 'await' in code or 'page.' in code:
                return self._fix_common_mistakes(code)

        return None

    def _fix_common_mistakes(self, code: str) -> str:
        """Fix common LLM code generation mistakes.

        The LLM often makes these errors:
        1. await page.locator(...) - locator creation is sync
        2. await page.locator(...).first - .first is sync property
        3. locator.count() without await - count() is async
        4. await page.get_by_*(...) without method call - these return locators
        """
        lines = code.split('\n')
        fixed_lines = []

        for line in lines:
            original = line

            # Pattern to match locator calls (handles nested quotes/brackets)
            # Matches: page.locator(...), page.get_by_role(...), etc.
            locator_patterns = [
                r'page\.locator\([^)]*(?:\([^)]*\)[^)]*)*\)',
                r'page\.get_by_\w+\([^)]*\)',
            ]

            # Fix: "await page.locator(...)" or "await page.locator(...).first" without action
            # Locator creation and .first/.nth() are sync
            for pattern in locator_patterns:
                # Match: await <locator>(.first|.nth(N))? at end of line (no method call)
                full_pattern = rf'await\s+({pattern}(?:\.first|\.nth\(\d+\)|\.last)?)\s*$'
                if re.search(full_pattern, line.strip()):
                    line = re.sub(rf'await\s+({pattern}(?:\.first|\.nth\(\d+\)|\.last)?)', r'\1', line)

            # Fix: "var = await page.locator(...)" - assignment to locator
            for pattern in locator_patterns:
                assign_pattern = rf'(\w+)\s*=\s*await\s+({pattern}(?:\.first|\.nth\(\d+\)|\.last)?)\s*$'
                if re.search(assign_pattern, line.strip()):
                    line = re.sub(rf'=\s*await\s+({pattern})', r'= \1', line)

            # Fix: ".count()" without await
            if '.count()' in line and 'await' not in line:
                # Add await before the expression that ends in .count()
                line = re.sub(r'(\w+\.count\(\))', r'await \1', line)
                # Handle page.locator(...).count()
                line = re.sub(r'(page\.locator\([^)]*\)\.count\(\))', r'await \1', line)

            # Fix: ".inner_text()" without await
            if '.inner_text()' in line and 'await' not in line and '=' in line:
                line = re.sub(r'=\s*(\w+\.inner_text\(\))', r'= await \1', line)

            # Fix: ".is_visible()" without await
            if '.is_visible()' in line and 'await' not in line:
                line = re.sub(r'(\w+\.is_visible\(\))', r'await \1', line)

            if line != original:
                logger.debug(f"Fixed code: {original.strip()} -> {line.strip()}")

            fixed_lines.append(line)

        return '\n'.join(fixed_lines)

    def _extract_thought(self, response: str) -> Optional[str]:
        """Extract thought/reasoning from response."""
        thought_match = re.search(r'THOUGHT:\s*(.+?)(?:```|$)', response, re.IGNORECASE | re.DOTALL)
        if thought_match:
            return thought_match.group(1).strip()[:200]
        return None

    async def _execute_code(
        self,
        code: str,
        page: Page,
        result: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Execute generated code safely.

        Args:
            code: Python code to execute
            page: Playwright page object
            result: Dict for storing results

        Returns:
            Tuple of (success, output_message)
        """
        if len(code) > self.MAX_CODE_LENGTH:
            return False, f"Code too long ({len(code)} chars, max {self.MAX_CODE_LENGTH})"

        # Create execution namespace with allowed objects
        namespace = {
            'page': page,
            'result': result,
            'asyncio': asyncio,
            'PlaywrightTimeout': PlaywrightTimeout,
        }

        # Wrap code in async function
        wrapped_code = f"""
async def __execute__():
{chr(10).join('    ' + line for line in code.split(chr(10)))}
"""

        try:
            # Compile and execute
            exec(compile(wrapped_code, '<generated>', 'exec'), namespace)

            # Run the async function with timeout
            await asyncio.wait_for(
                namespace['__execute__'](),
                timeout=self.EXECUTION_TIMEOUT
            )

            # Check what happened
            if result.get("error"):
                return False, f"Code error: {result['error']}"

            return True, result.get("message", "Code executed successfully")

        except asyncio.TimeoutError:
            return False, f"Code execution timeout ({self.EXECUTION_TIMEOUT}s)"
        except PlaywrightTimeout as e:
            return False, f"Playwright timeout: {str(e)[:100]}"
        except Exception as e:
            tb = traceback.format_exc()
            logger.warning(f"Code execution error: {e}\n{tb}")
            return False, f"Execution error: {str(e)[:150]}"

    async def _get_page_state(self, page: Page) -> str:
        """Get current page state for LLM context."""
        try:
            url = page.url
            title = await page.title()

            # Get visible text content (truncated)
            try:
                # Get accessibility tree snapshot
                snapshot = await page.accessibility.snapshot()
                if snapshot:
                    state = self._format_a11y_tree(snapshot, max_depth=3)
                else:
                    # Fallback to visible text
                    text = await page.evaluate("""
                        () => {
                            const walker = document.createTreeWalker(
                                document.body,
                                NodeFilter.SHOW_TEXT,
                                null,
                                false
                            );
                            let text = '';
                            let node;
                            while (node = walker.nextNode()) {
                                const t = node.textContent.trim();
                                if (t && t.length > 2) text += t + ' ';
                                if (text.length > 2000) break;
                            }
                            return text.slice(0, 2000);
                        }
                    """)
                    state = f"Page text: {text[:1500]}"
            except Exception as e:
                state = f"(Could not get page content: {e})"

            return f"""## Current Page State
URL: {url}
Title: {title}

{state}"""

        except Exception as e:
            return f"Error getting page state: {e}"

    def _format_a11y_tree(self, node: dict, depth: int = 0, max_depth: int = 3) -> str:
        """Format accessibility tree for LLM consumption."""
        if depth > max_depth:
            return ""

        lines = []
        indent = "  " * depth

        role = node.get("role", "")
        name = node.get("name", "")[:50]

        # Skip generic containers without useful info
        if role in ("generic", "none") and not name:
            pass
        elif role or name:
            line = f"{indent}- {role}"
            if name:
                line += f': "{name}"'
            lines.append(line)

        # Process children
        for child in node.get("children", []):
            child_text = self._format_a11y_tree(child, depth + 1, max_depth)
            if child_text:
                lines.append(child_text)

        return "\n".join(lines)

    async def navigate(
        self,
        page: Page,
        goal: str,
        max_steps: int = 25,
        timeout: int = 300,
        reasoner=None,
    ) -> Tuple[bool, str, "BrowserTools"]:
        """Navigate to achieve a goal using generated code.

        Args:
            page: Playwright page to control
            goal: What to achieve
            max_steps: Maximum code execution steps
            timeout: Session timeout in seconds
            reasoner: Optional Reasoner instance for reflexion (graph mode)

        Returns:
            Tuple of (success, summary, browser_tools)
        """
        logger.info(f"CodeNavigator goal: {goal[:50]}...")

        # Use graph mode if enabled
        if self.use_graph:
            return await self._navigate_with_graph(
                page=page,
                goal=goal,
                max_steps=max_steps,
                timeout=timeout,
                reasoner=reasoner,
            )

        browser_tools = BrowserTools(page, self.ui_server, self.agent_id)
        await browser_tools.setup_dom_observer()

        result: Dict[str, Any] = {
            "done": False,
            "summary": "",
            "extracted": None,
        }

        # Load system prompt from markdown file
        system_prompt = load_prompt("code_navigator")

        # Inject learned error patterns into prompt
        error_context = self.error_tracker.get_context_injection()
        if error_context:
            system_prompt = f"{system_prompt}\n\n{error_context}"

        # Clear session tracking
        self._last_failed_code = None

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"**Goal:** {goal}"}
        ]

        try:
            async with asyncio.timeout(timeout):
                for step in range(1, max_steps + 1):
                    if result.get("done"):
                        break

                    # Check for user interrupt
                    if self.ui_server and self.ui_server.check_restart_requested(self.agent_id):
                        return False, "Interrupted by user", browser_tools

                    await self._update_stage("observe")
                    await self._log("info", f"Step {step}/{max_steps}")

                    # Get current page state
                    page_state = await self._get_page_state(page)

                    # Log observation size for debugging
                    page_state_lines = len(page_state.split('\n'))
                    await self._log("debug", f"Observation: {page_state_lines} lines, {len(page_state)} chars")

                    messages.append({"role": "user", "content": page_state})

                    # Get LLM response
                    await self._update_stage("think")

                    try:
                        response = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: self.llm.invoke(messages)
                        )
                        response_text = response.content if hasattr(response, 'content') else str(response)
                    except Exception as e:
                        logger.error(f"LLM error: {e}")
                        messages.append({"role": "user", "content": f"LLM error: {e}. Please try again."})
                        continue

                    # Extract thought and code
                    thought = self._extract_thought(response_text)
                    code = self._extract_code(response_text)

                    if thought:
                        await self._log("info", thought[:100])

                    if not code:
                        logger.warning(f"No code in response: {response_text[:200]}")
                        messages.append({"role": "assistant", "content": response_text})
                        messages.append({"role": "user", "content": "Please provide Python code in a ```python block."})
                        continue

                    # Log the code being executed
                    code_preview = code[:100].replace('\n', ' ')
                    await self._log("debug", f"Executing: {code_preview}...")

                    # Execute the code
                    await self._update_stage("act")
                    success, output = await self._execute_code(code, page, result)

                    # Record action
                    browser_tools.action_count += 1
                    if page.url not in browser_tools.visited_urls:
                        browser_tools.visited_urls.append(page.url)

                    # Update screenshot
                    if self.ui_server:
                        try:
                            screenshot = await page.screenshot(type="png")
                            await self.ui_server.update_screenshot(
                                self.agent_id, screenshot, page.url
                            )
                        except Exception:
                            pass

                    # Add to conversation
                    messages.append({"role": "assistant", "content": response_text})

                    if success:
                        messages.append({"role": "user", "content": f"Code executed successfully. {output}"})

                        # If previous code failed, record this as a fix
                        if self._last_failed_code:
                            self.error_tracker.record_fix(
                                self._last_failed_code,
                                code
                            )
                            self._last_failed_code = None
                    else:
                        # Record the error and get suggested fix
                        suggested_fix = self.error_tracker.record_error(
                            error_message=output,
                            code=code,
                            page_url=page.url,
                        )
                        self._last_failed_code = output

                        fix_hint = f"\n\nHint: {suggested_fix}" if suggested_fix else ""
                        messages.append({"role": "user", "content": f"Code failed: {output}{fix_hint}\nPlease try a different approach."})

                    # Track tokens
                    self.token_tracker.record_messages(messages, response_text)
                    if self.ui_server:
                        stats = self.token_tracker.get_stats()
                        await self.ui_server.record_llm_call(
                            self.agent_id,
                            prompt_tokens=stats["prompt_tokens"],
                            completion_tokens=stats["completion_tokens"],
                            context_size=count_message_tokens(messages, self.model)
                        )

                    # Manage context - keep it reasonable
                    if len(messages) > 20:
                        # Keep system, goal, and recent messages
                        messages = messages[:2] + messages[-16:]

                await self._update_stage("idle")

                summary = result.get("summary", "Navigation completed")
                if result.get("extracted"):
                    summary += f"\nExtracted: {str(result['extracted'])[:200]}"

                self.history.append({
                    "goal": goal,
                    "output": summary,
                    "actions_taken": browser_tools.action_count,
                    "urls_visited": browser_tools.visited_urls,
                })

                return result.get("done", False), summary, browser_tools

        except asyncio.TimeoutError:
            logger.warning(f"CodeNavigator timeout after {timeout}s")
            await self._update_stage("idle")
            return False, "Session timeout", browser_tools
        except Exception as e:
            logger.error(f"CodeNavigator error: {e}")
            await self._update_stage("idle")
            return False, f"Error: {str(e)[:50]}", browser_tools

    async def _navigate_with_graph(
        self,
        page: Page,
        goal: str,
        max_steps: int = 25,
        timeout: int = 300,
        reasoner=None,
    ) -> Tuple[bool, str, "BrowserTools"]:
        """Navigate using LangGraph orchestration.

        This provides:
        - Reflexion: Self-critique on failures using larger model
        - Plan-and-Execute: Upfront planning for known patterns
        - Better state management and checkpointing

        Args:
            page: Playwright page to control
            goal: What to achieve
            max_steps: Maximum steps
            timeout: Session timeout
            reasoner: Optional Reasoner for reflexion

        Returns:
            Tuple of (success, summary, browser_tools)
        """
        logger.info(f"[GRAPH] Starting graph-based navigation: {goal[:50]}...")

        browser_tools = BrowserTools(page, self.ui_server, self.agent_id)
        await browser_tools.setup_dom_observer()

        try:
            # Get or create graph runner
            graph_runner = self._get_graph_runner(reasoner)

            # Run the graph
            result = await graph_runner.run(
                page=page,
                goal=goal,
                agent_id=self.agent_id,
                mode_name="code_navigator",
                max_steps=max_steps,
                timeout=timeout,
            )

            # Update browser tools with results
            browser_tools.action_count = result.current_step
            browser_tools.visited_urls = result.urls_visited

            # Build summary
            summary = result.summary
            if result.extracted_data:
                summary += f"\nExtracted: {str(result.extracted_data)[:200]}"

            # Add to history
            self.history.append({
                "goal": goal,
                "output": summary,
                "actions_taken": browser_tools.action_count,
                "urls_visited": browser_tools.visited_urls,
                "execution_mode": result.execution_mode.value if hasattr(result.execution_mode, 'value') else str(result.execution_mode),
                "reflexions": len(result.reflexions),
                "total_tokens": result.total_tokens,
            })

            await self._update_stage("idle")
            return result.success, summary, browser_tools

        except Exception as e:
            logger.error(f"[GRAPH] Error: {e}")
            await self._update_stage("idle")
            return False, f"Graph error: {str(e)[:50]}", browser_tools
