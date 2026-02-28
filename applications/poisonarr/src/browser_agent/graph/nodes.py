"""Graph nodes for the LangGraph agent orchestration.

Each node is a function that takes the current state and returns updates.
The graph routes between nodes based on conditions.
"""

import asyncio
import logging
import re
import time
import traceback
from typing import Any, Dict, Optional, TYPE_CHECKING

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from .state import (
    AgentState,
    StepState,
    ReflexionState,
    PlanStep,
    ExecutionMode,
    PerceptionMode,
    StepStatus,
)

if TYPE_CHECKING:
    from ..core.code_navigator import CodeNavigator
    from ..core.error_tracker import PlaywrightErrorTracker
    from ..server import UIServer
    from .patterns import PatternLibrary

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================

def _extract_code(response: str) -> Optional[str]:
    """Extract Python code from LLM response."""
    code_match = re.search(r'```python\s*(.*?)\s*```', response, re.DOTALL)
    if code_match:
        return code_match.group(1).strip()

    code_match = re.search(r'```\s*(.*?)\s*```', response, re.DOTALL)
    if code_match:
        code = code_match.group(1).strip()
        if 'await' in code or 'page.' in code:
            return code

    return None


def _extract_thought(response: str) -> Optional[str]:
    """Extract thought/reasoning from response."""
    thought_match = re.search(r'THOUGHT:\s*(.+?)(?:```|$)', response, re.IGNORECASE | re.DOTALL)
    if thought_match:
        return thought_match.group(1).strip()[:200]
    return None


def _fix_common_code_mistakes(code: str) -> str:
    """Fix common LLM code generation mistakes."""
    lines = code.split('\n')
    fixed_lines = []

    for line in lines:
        original = line

        locator_patterns = [
            r'page\.locator\([^)]*(?:\([^)]*\)[^)]*)*\)',
            r'page\.get_by_\w+\([^)]*\)',
        ]

        for pattern in locator_patterns:
            full_pattern = rf'await\s+({pattern}(?:\.first|\.nth\(\d+\)|\.last)?)\s*$'
            if re.search(full_pattern, line.strip()):
                line = re.sub(rf'await\s+({pattern}(?:\.first|\.nth\(\d+\)|\.last)?)', r'\1', line)

        for pattern in locator_patterns:
            assign_pattern = rf'(\w+)\s*=\s*await\s+({pattern}(?:\.first|\.nth\(\d+\)|\.last)?)\s*$'
            if re.search(assign_pattern, line.strip()):
                line = re.sub(rf'=\s*await\s+({pattern})', r'= \1', line)

        if '.count()' in line and 'await' not in line:
            line = re.sub(r'(\w+\.count\(\))', r'await \1', line)
            line = re.sub(r'(page\.locator\([^)]*\)\.count\(\))', r'await \1', line)

        if '.inner_text()' in line and 'await' not in line and '=' in line:
            line = re.sub(r'=\s*(\w+\.inner_text\(\))', r'= await \1', line)

        if '.is_visible()' in line and 'await' not in line:
            line = re.sub(r'(\w+\.is_visible\(\))', r'await \1', line)

        if line != original:
            logger.debug(f"Fixed code: {original.strip()} -> {line.strip()}")

        fixed_lines.append(line)

    return '\n'.join(fixed_lines)


async def _get_accessibility_tree(page: Page, max_depth: int = 3) -> str:
    """Get accessibility tree snapshot from page."""
    try:
        snapshot = await page.accessibility.snapshot()
        if snapshot:
            return _format_a11y_tree(snapshot, max_depth=max_depth)
        return "(No accessibility tree available)"
    except Exception as e:
        return f"(Accessibility error: {e})"


def _format_a11y_tree(node: dict, depth: int = 0, max_depth: int = 3) -> str:
    """Format accessibility tree for LLM consumption."""
    if depth > max_depth:
        return ""

    lines = []
    indent = "  " * depth

    role = node.get("role", "")
    name = node.get("name", "")[:50]

    if role in ("generic", "none") and not name:
        pass
    elif role or name:
        line = f"{indent}- {role}"
        if name:
            line += f': "{name}"'
        lines.append(line)

    for child in node.get("children", []):
        child_text = _format_a11y_tree(child, depth + 1, max_depth)
        if child_text:
            lines.append(child_text)

    return "\n".join(lines)


async def _execute_code(
    code: str,
    page: Page,
    result: Dict[str, Any],
    timeout: int = 30,
    max_length: int = 2000,
) -> tuple[bool, str]:
    """Execute generated code safely."""
    if len(code) > max_length:
        return False, f"Code too long ({len(code)} chars, max {max_length})"

    namespace = {
        'page': page,
        'result': result,
        'asyncio': asyncio,
        'PlaywrightTimeout': PlaywrightTimeout,
    }

    wrapped_code = f"""
async def __execute__():
{chr(10).join('    ' + line for line in code.split(chr(10)))}
"""

    try:
        exec(compile(wrapped_code, '<generated>', 'exec'), namespace)

        await asyncio.wait_for(
            namespace['__execute__'](),
            timeout=timeout
        )

        if result.get("error"):
            return False, f"Code error: {result['error']}"

        return True, result.get("message", "Code executed successfully")

    except asyncio.TimeoutError:
        return False, f"Code execution timeout ({timeout}s)"
    except PlaywrightTimeout as e:
        return False, f"Playwright timeout: {str(e)[:100]}"
    except Exception as e:
        tb = traceback.format_exc()
        logger.warning(f"Code execution error: {e}\n{tb}")
        return False, f"Execution error: {str(e)[:150]}"


# =============================================================================
# Graph Nodes
# =============================================================================

async def planner_node(
    state: Dict[str, Any],
    pattern_library: Optional["PatternLibrary"] = None,
) -> Dict[str, Any]:
    """Planner node: decide execution mode based on goal.

    Checks PatternLibrary for known workflows. If found with high confidence,
    switches to PLAN_EXECUTE mode with pre-built plan.

    Args:
        state: Current agent state dict
        pattern_library: Optional pattern library for known workflows

    Returns:
        Updated state dict with execution_mode and plan
    """
    goal = state.get("goal", "")
    logger.info(f"[PLANNER] Analyzing goal: {goal[:50]}...")

    updates: Dict[str, Any] = {}

    if pattern_library:
        match = pattern_library.find_match(goal)
        if match and match.confidence >= 0.8:
            logger.info(f"[PLANNER] Found pattern match: {match.pattern.name} (conf={match.confidence:.2f})")
            updates["execution_mode"] = ExecutionMode.PLAN_EXECUTE.value
            updates["plan_confidence"] = match.confidence
            updates["plan"] = [
                {
                    "index": i,
                    "description": step.description,
                    "action_hint": step.action_hint,
                    "selector_hint": step.selector_hint,
                    "status": StepStatus.PENDING.value,
                    "attempts": 0,
                    "error": "",
                    "code_executed": "",
                }
                for i, step in enumerate(match.pattern.steps)
            ]
            updates["plan_step_index"] = 0
            return updates

    logger.info("[PLANNER] No pattern match, using ReAct mode")
    updates["execution_mode"] = ExecutionMode.REACT.value
    updates["plan"] = []
    updates["plan_confidence"] = 0.0

    return updates


async def observe_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Observe node: capture current page state.

    Gets accessibility tree (primary) or falls back to vision (secondary).
    Vision fallback triggers when:
    - Accessibility tree is too small
    - We have consecutive failures (selectors not working)
    - Hybrid mode is enabled

    Args:
        state: Current agent state dict (must include 'page')

    Returns:
        Updated state with new step containing observation
    """
    page: Page = state.get("page")
    if not page:
        logger.error("[OBSERVE] No page in state!")
        return {"last_error": "No page available"}

    current_step = state.get("current_step", 0) + 1
    perception_mode = PerceptionMode(state.get("perception_mode", "accessibility"))
    consecutive_failures = state.get("consecutive_failures", 0)
    goal = state.get("goal", "")

    logger.info(f"[OBSERVE] Step {current_step}, mode={perception_mode.value}")

    # Update UI stage
    ui_server = state.get("ui_server")
    agent_id = state.get("agent_id", "agent-1")
    if ui_server:
        try:
            await ui_server.update_react_stage(agent_id, "observe")
        except Exception:
            pass

    # Capture page info
    try:
        url = page.url
        title = await page.title()
    except Exception as e:
        url = "unknown"
        title = f"(error: {e})"

    # Get observation based on perception mode
    observation = ""
    actual_mode = perception_mode
    vision_context = ""

    # Always get accessibility tree first
    a11y_tree = await _get_accessibility_tree(page, max_depth=3)
    observation = a11y_tree

    # Determine if we need vision fallback (be selective to avoid slowdowns)
    need_vision = False
    if perception_mode == PerceptionMode.VISION:
        need_vision = True
    elif perception_mode == PerceptionMode.HYBRID:
        need_vision = True
    elif consecutive_failures >= 2:
        # Only use vision after 2+ failures (not 1) to avoid slowdowns
        need_vision = True
        logger.info(f"[OBSERVE] Using vision fallback after {consecutive_failures} failures")

    # Check if accessibility tree is too small (very strict threshold)
    if len(a11y_tree) < 30 or "error" in a11y_tree.lower():
        need_vision = True
        logger.info("[OBSERVE] Accessibility tree too small, using vision")

    # Get vision analysis if needed
    if need_vision:
        try:
            from ..core.vision import VisionAnalyzer

            # Get vision config from state or use defaults
            vision_config = state.get("vision_config", {})
            vision = VisionAnalyzer(
                model=vision_config.get("model", "llava:13b"),
                base_url=vision_config.get("base_url", "http://localhost:11434"),
                enabled=True,
                provider=vision_config.get("provider", "ollama"),
            )

            # Get page description
            actual_mode = PerceptionMode.HYBRID if a11y_tree else PerceptionMode.VISION
            logger.info(f"[OBSERVE] Getting vision analysis for: {goal[:50]}...")

            # Get selector suggestions for the goal
            vision_context = await vision.suggest_selectors(page, goal)

            if vision_context and "[Vision" not in vision_context:
                observation = f"{a11y_tree}\n\n## Vision Analysis (Selector Suggestions)\n{vision_context}"
                logger.info(f"[OBSERVE] Vision added context: {len(vision_context)} chars")

            # Track vision usage
            vision_fallback_count = state.get("vision_fallback_count", 0) + 1

            await vision.close()

        except Exception as e:
            logger.warning(f"[OBSERVE] Vision fallback error: {e}")
            vision_fallback_count = state.get("vision_fallback_count", 0)

    else:
        vision_fallback_count = state.get("vision_fallback_count", 0)

    # Create step state
    new_step = {
        "step_number": current_step,
        "page_url": url,
        "page_title": title,
        "observation": observation,
        "observation_mode": actual_mode.value,
        "thought": "",
        "code": "",
        "success": False,
        "output": "",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "execution_time_ms": 0,
    }

    # Update visited URLs
    urls_visited = state.get("urls_visited", [])
    if url not in urls_visited:
        urls_visited = urls_visited + [url]

    return {
        "current_step": current_step,
        "steps": state.get("steps", []) + [new_step],
        "urls_visited": urls_visited,
        "vision_fallback_count": vision_fallback_count,
    }


async def think_node(
    state: Dict[str, Any],
    llm: Any = None,
    system_prompt: str = "",
) -> Dict[str, Any]:
    """Think node: generate code to achieve goal.

    Uses the navigator LLM to generate Playwright code based on
    current observation and goal.

    Args:
        state: Current agent state dict
        llm: LangChain-compatible LLM
        system_prompt: System prompt for code generation

    Returns:
        Updated state with thought and code
    """
    if not llm:
        logger.error("[THINK] No LLM provided!")
        return {"last_error": "No LLM available"}

    goal = state.get("goal", "")
    steps = state.get("steps", [])
    execution_mode = ExecutionMode(state.get("execution_mode", "react"))
    error_context = state.get("error_context", "")

    if not steps:
        logger.error("[THINK] No steps in state!")
        return {"last_error": "No observation available"}

    current_step = steps[-1]
    observation = current_step.get("observation", "")

    logger.info(f"[THINK] Generating code for step {current_step.get('step_number')}")

    # Update UI stage
    ui_server = state.get("ui_server")
    agent_id = state.get("agent_id", "agent-1")
    if ui_server:
        try:
            await ui_server.update_react_stage(agent_id, "think")
        except Exception:
            pass

    # Build prompt with error context
    full_prompt = system_prompt
    if error_context:
        full_prompt = f"{system_prompt}\n\n{error_context}"

    # Build messages
    messages = [
        {"role": "system", "content": full_prompt},
        {"role": "user", "content": f"**Goal:** {goal}"},
    ]

    # Add plan context if in PLAN_EXECUTE mode
    if execution_mode == ExecutionMode.PLAN_EXECUTE:
        plan = state.get("plan", [])
        plan_idx = state.get("plan_step_index", 0)
        if plan and plan_idx < len(plan):
            plan_step = plan[plan_idx]
            messages.append({
                "role": "user",
                "content": f"**Plan Step {plan_idx + 1}/{len(plan)}:** {plan_step.get('description', '')}\n"
                          f"Hint: {plan_step.get('action_hint', 'N/A')}"
            })

    # Add observation with site-specific hints
    page_url = current_step.get('page_url', '')
    page_title = current_step.get('page_title', '')

    # Site-specific selector hints
    site_hints = """
**CRITICAL CODE RULES:**
- Keep code SHORT (under 1500 chars). Do ONE action per step.
- NO comments, NO print statements, NO explanations in code.
- NEVER use wait_for_load_state('networkidle') - it times out!
- NEVER use :contains() - it's jQuery not CSS! Use get_by_text() instead.
- Use page.wait_for_timeout(2000) or wait_for_selector() instead.
"""
    if "localhost:8888" in page_url or "searxng" in page_title.lower():
        site_hints += """
**SearXNG SELECTORS (NOT Google!):**
- Search input: `page.get_by_placeholder("Search for...")`
- Search button: `page.get_by_role("button", name="search")`
- Results: `page.locator(".result")` or `page.locator("article")`
"""

    messages.append({
        "role": "user",
        "content": f"## Current Page State\nURL: {page_url}\nTitle: {page_title}\n{site_hints}\n{observation}"
    })

    # Add recent history context (last few steps)
    if len(steps) > 1:
        recent = steps[-4:-1]  # Last 3 steps before current
        for s in recent:
            if s.get("code"):
                messages.append({"role": "assistant", "content": f"```python\n{s['code']}\n```"})
                result_msg = "Success" if s.get("success") else f"Failed: {s.get('output', '')[:100]}"
                messages.append({"role": "user", "content": result_msg})

    # Invoke LLM
    start_time = time.time()
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: llm.invoke(messages)
        )
        response_text = response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        logger.error(f"[THINK] LLM error: {e}")
        return {"last_error": f"LLM error: {e}"}

    elapsed_ms = int((time.time() - start_time) * 1000)

    # Extract thought and code
    thought = _extract_thought(response_text)
    code = _extract_code(response_text)

    if code:
        code = _fix_common_code_mistakes(code)

    # Update current step
    current_step["thought"] = thought or ""
    current_step["code"] = code or ""
    current_step["prompt_tokens"] = len(str(messages)) // 4  # Rough estimate
    current_step["completion_tokens"] = len(response_text) // 4

    # Replace last step with updated one
    updated_steps = steps[:-1] + [current_step]

    return {
        "steps": updated_steps,
    }


async def act_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Act node: execute generated code.

    Runs the Playwright code generated by think_node.

    Args:
        state: Current agent state dict (must include 'page')

    Returns:
        Updated state with execution results
    """
    page: Page = state.get("page")
    if not page:
        logger.error("[ACT] No page in state!")
        return {"last_error": "No page available"}

    steps = state.get("steps", [])
    if not steps:
        logger.error("[ACT] No steps in state!")
        return {"last_error": "No steps available"}

    current_step = steps[-1]
    code = current_step.get("code", "")

    if not code:
        logger.warning("[ACT] No code to execute")
        current_step["success"] = False
        current_step["output"] = "No code generated"
        return {
            "steps": steps[:-1] + [current_step],
            "consecutive_failures": state.get("consecutive_failures", 0) + 1,
            "last_error": "No code generated",
        }

    code_preview = code[:80].replace('\n', ' ')
    logger.info(f"[ACT] Executing code ({len(code)} chars): {code_preview}...")

    # Result dict for code to populate
    result: Dict[str, Any] = {
        "done": False,
        "summary": "",
        "extracted": None,
    }

    start_time = time.time()
    success, output = await _execute_code(code, page, result)
    elapsed_ms = int((time.time() - start_time) * 1000)

    current_step["success"] = success
    current_step["output"] = output
    current_step["execution_time_ms"] = elapsed_ms

    if success:
        logger.info(f"[ACT] Success: {output[:100]}")
    else:
        logger.warning(f"[ACT] Failed: {output[:150]}")

    # Update step in state
    updated_steps = steps[:-1] + [current_step]

    updates: Dict[str, Any] = {
        "steps": updated_steps,
    }

    # Get error tracker from state
    error_tracker = state.get("error_tracker")

    if success:
        updates["consecutive_failures"] = 0

        # Record successful fix if we had previous failures
        if error_tracker and state.get("last_error"):
            error_tracker.record_fix(state.get("last_error"), code)
            logger.info(f"[ACT] Recorded fix for previous error")

        # Check if goal is done
        if result.get("done"):
            updates["done"] = True
            updates["success"] = True
            updates["summary"] = result.get("summary", "Goal achieved")
            if result.get("extracted"):
                updates["extracted_data"] = result["extracted"]
    else:
        updates["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        updates["last_error"] = output

        # Record error for learning
        if error_tracker:
            suggested_fix = error_tracker.record_error(
                error_message=output,
                code=code,
                page_url=page.url,
            )
            if suggested_fix:
                logger.info(f"[ACT] Error tracker suggests: {suggested_fix[:80]}...")
                # Add fix hint to error context for next think
                error_context = state.get("error_context", "")
                updates["error_context"] = f"{error_context}\n\nPrevious error fix hint: {suggested_fix}"

    # Update UI server if available
    ui_server = state.get("ui_server")
    agent_id = state.get("agent_id", "agent-1")
    if ui_server:
        try:
            # Update screenshot
            screenshot = await page.screenshot(type="png")
            await ui_server.update_screenshot(agent_id, screenshot, page.url)

            # Update ReAct stage
            await ui_server.update_react_stage(agent_id, "idle" if state.get("done") else "act")

            # Record LLM call stats from the current step
            steps = state.get("steps", [])
            if steps:
                last_step = steps[-1]
                prompt_tokens = last_step.get("prompt_tokens", 0)
                completion_tokens = last_step.get("completion_tokens", 0)
                if prompt_tokens or completion_tokens:
                    await ui_server.record_llm_call(
                        agent_id,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        context_size=prompt_tokens,
                    )
        except Exception as e:
            logger.debug(f"UI update error: {e}")

    return updates


async def reflexion_node(
    state: Dict[str, Any],
    reasoner_llm: Any = None,
) -> Dict[str, Any]:
    """Reflexion node: analyze failures and generate recovery strategy.

    Uses the larger reasoner model to analyze what went wrong and
    learn site-specific patterns from the page structure.

    Args:
        state: Current agent state dict
        reasoner_llm: LangChain-compatible LLM (should be larger/smarter)

    Returns:
        Updated state with reflexion analysis
    """
    if not reasoner_llm:
        logger.warning("[REFLEXION] No reasoner LLM, skipping reflexion")
        return {"consecutive_failures": 0}  # Reset and continue

    steps = state.get("steps", [])
    goal = state.get("goal", "")
    last_error = state.get("last_error", "")
    page = state.get("page")

    logger.info(f"[REFLEXION] Analyzing failure: {last_error[:50]}...")

    # Get current page structure for context
    page_context = ""
    vision_analysis = ""

    if page:
        try:
            url = page.url
            # Get relevant part of accessibility tree
            snapshot = await page.accessibility.snapshot()
            if snapshot:
                page_context = f"\n## Current Page Structure (URL: {url})\n"
                page_context += _format_a11y_tree(snapshot, max_depth=2)[:1500]

            # Get vision analysis for better understanding
            try:
                from ..core.vision import VisionAnalyzer

                vision_config = state.get("vision_config", {})
                vision = VisionAnalyzer(
                    model=vision_config.get("model", "llava:13b"),
                    base_url=vision_config.get("base_url", "http://localhost:11434"),
                    enabled=True,
                    provider=vision_config.get("provider", "ollama"),
                )

                # Get the last failed code
                failed_code = ""
                for s in reversed(steps):
                    if not s.get("success") and s.get("code"):
                        failed_code = s.get("code", "")
                        break

                if failed_code:
                    vision_analysis = await vision.analyze_failure(page, failed_code, last_error)
                    if vision_analysis and "[Vision" not in vision_analysis:
                        page_context += f"\n\n## Vision Analysis of Failure\n{vision_analysis}"
                        logger.info(f"[REFLEXION] Vision analysis added")

                await vision.close()

            except Exception as ve:
                logger.debug(f"[REFLEXION] Vision analysis skipped: {ve}")

        except Exception as e:
            page_context = f"\n## Page context unavailable: {e}"

    # Build context from recent failed steps
    failed_steps = [s for s in steps[-5:] if not s.get("success")]
    context_parts = []
    for s in failed_steps:
        context_parts.append(f"Step {s.get('step_number')}:")
        context_parts.append(f"  Code: {s.get('code', '')[:200]}")
        context_parts.append(f"  Error: {s.get('output', '')[:200]}")
    failure_context = "\n".join(context_parts)

    # Reflexion prompt with page structure
    prompt = f"""Analyze this browser automation failure and learn from the page structure.

## Goal
{goal}

## Recent Failed Steps
{failure_context}
{page_context}

## Analysis Required
1. What is the root cause of the failure?
2. Looking at the ACTUAL page structure above, what selectors/elements should be used?
3. What site-specific pattern should be remembered for this domain?

IMPORTANT: Base your fix strategy on the ACTUAL elements shown in the page structure, not assumptions.

Respond with:
ROOT_CAUSE: <brief description>
FIX_STRATEGY: <specific code fix based on actual page elements>
LEARNED_PATTERN: <site-specific lesson, e.g. "On SearXNG, use .press('Enter') not click('Submit')">
SITE_SELECTORS: <key selectors that work on this site, e.g. "search: input[type='search'], submit: press Enter">
"""

    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: reasoner_llm.invoke([{"role": "user", "content": prompt}])
        )
        response_text = response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        logger.error(f"[REFLEXION] LLM error: {e}")
        return {"consecutive_failures": 0}

    # Parse response
    root_cause = ""
    fix_strategy = ""
    learned_pattern = ""
    site_selectors = ""

    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("ROOT_CAUSE:"):
            root_cause = line.replace("ROOT_CAUSE:", "").strip()
        elif line.startswith("FIX_STRATEGY:"):
            fix_strategy = line.replace("FIX_STRATEGY:", "").strip()
        elif line.startswith("LEARNED_PATTERN:"):
            learned_pattern = line.replace("LEARNED_PATTERN:", "").strip()
        elif line.startswith("SITE_SELECTORS:"):
            site_selectors = line.replace("SITE_SELECTORS:", "").strip()

    logger.info(f"[REFLEXION] Root cause: {root_cause[:80]}")
    logger.info(f"[REFLEXION] Fix strategy: {fix_strategy[:80]}")
    logger.info(f"[REFLEXION] Learned: {learned_pattern[:80]}")

    # Record to error tracker for persistent learning
    error_tracker = state.get("error_tracker")
    if error_tracker and fix_strategy:
        error_tracker.record_reflexion_fix(
            error_message=last_error,
            fix_strategy=fix_strategy,
            learned_pattern=learned_pattern,
        )
        logger.info("[REFLEXION] Recorded fix to error tracker for future sessions")

    # Create reflexion record
    reflexion = {
        "trigger_step": state.get("current_step", 0),
        "error_analysis": last_error[:500],
        "root_cause": root_cause[:200],
        "fix_strategy": fix_strategy[:300],
        "learned_pattern": learned_pattern[:200],
        "site_selectors": site_selectors[:200],
        "fix_applied": True,
        "recovery_successful": False,  # Will be updated based on next steps
    }

    reflexions = state.get("reflexions", []) + [reflexion]

    # Inject fix strategy and site-specific knowledge into error context
    error_context = state.get("error_context", "")
    if fix_strategy or site_selectors:
        error_context = f"{error_context}\n\n## Recovery Strategy\n{fix_strategy}"
        if site_selectors:
            error_context += f"\n\n## Site-Specific Selectors\n{site_selectors}"
        if learned_pattern:
            error_context += f"\n\n## Learned Pattern\n{learned_pattern}"

    return {
        "reflexions": reflexions,
        "consecutive_failures": 0,  # Reset after reflexion
        "error_context": error_context,
        "execution_mode": ExecutionMode.REFLEXION.value,
    }


async def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Finalize node: complete the session.

    Called when goal is achieved or max steps reached.

    Args:
        state: Current agent state dict

    Returns:
        Final state updates
    """
    from datetime import datetime

    done = state.get("done", False)
    success = state.get("success", False)
    current_step = state.get("current_step", 0)
    max_steps = state.get("max_steps", 25)
    goal = state.get("goal", "")

    # Determine final status
    if not done:
        if current_step >= max_steps:
            success = False
            summary = f"Max steps ({max_steps}) reached without completing goal"
        else:
            success = False
            summary = state.get("last_error", "Session ended without completing goal")
    else:
        summary = state.get("summary", "Goal completed")

    logger.info(f"[FINALIZE] Session complete: success={success}, steps={current_step}")

    # Calculate total tokens
    total_tokens = sum(
        s.get("prompt_tokens", 0) + s.get("completion_tokens", 0)
        for s in state.get("steps", [])
    )

    return {
        "done": True,
        "success": success,
        "summary": summary,
        "ended_at": datetime.now().isoformat(),
        "total_tokens": total_tokens,
    }


# =============================================================================
# Routing Functions
# =============================================================================

def should_continue(state: Dict[str, Any]) -> str:
    """Determine next node after act.

    Returns:
        "observe" to continue loop
        "reflexion" to analyze failures
        "finalize" to end session
    """
    if state.get("done"):
        return "finalize"

    current_step = state.get("current_step", 0)
    max_steps = state.get("max_steps", 25)

    if current_step >= max_steps:
        return "finalize"

    consecutive_failures = state.get("consecutive_failures", 0)
    reflexion_threshold = state.get("reflexion_threshold", 2)
    max_reflexions = state.get("max_reflexions", 5)
    reflexions = state.get("reflexions", [])

    logger.debug(f"should_continue: failures={consecutive_failures}, threshold={reflexion_threshold}, reflexions={len(reflexions)}/{max_reflexions}")

    if consecutive_failures >= reflexion_threshold and len(reflexions) < max_reflexions:
        logger.info(f"[ROUTING] Triggering reflexion: {consecutive_failures} >= {reflexion_threshold}")
        return "reflexion"

    return "observe"


def should_skip_plan(state: Dict[str, Any]) -> str:
    """Determine if we should skip planning.

    Returns:
        "observe" to skip planning
        "planner" to run planner
    """
    # Skip if already planned or in reflexion mode
    execution_mode = state.get("execution_mode")
    if execution_mode in (ExecutionMode.PLAN_EXECUTE.value, ExecutionMode.REFLEXION.value):
        return "observe"

    # Run planner for new sessions
    return "planner"
