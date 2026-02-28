"""LangGraph StateGraph builder for agent orchestration.

Constructs the graph that orchestrates observe->think->act->reflexion cycles.
"""

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from .state import (
    AgentState,
    StepState,
    ExecutionMode,
    PerceptionMode,
    state_to_dict,
    dict_to_state,
)
from .nodes import (
    planner_node,
    observe_node,
    think_node,
    act_node,
    reflexion_node,
    finalize_node,
    should_continue,
)
from .patterns import PatternLibrary

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..server import UIServer
    from ..core.error_tracker import PlaywrightErrorTracker

logger = logging.getLogger(__name__)

# Check if LangGraph is available
try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.base import BaseCheckpointSaver

    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    logger.warning("LangGraph not installed. Graph features will be simulated.")


def build_agent_graph(
    llm: Any,
    reasoner_llm: Optional[Any] = None,
    pattern_library: Optional[PatternLibrary] = None,
    system_prompt: str = "",
    checkpointer: Optional[Any] = None,
) -> Any:
    """Build the LangGraph StateGraph for agent orchestration.

    NOTE: Due to LangGraph's state serialization, non-serializable objects
    like Playwright Page must be passed through a runtime context, not state.
    For now, we use SimulatedGraph which handles this correctly.

    Args:
        llm: Navigator LLM for code generation
        reasoner_llm: Optional larger LLM for reflexion
        pattern_library: Optional pattern library for plan-and-execute
        system_prompt: System prompt for think node
        checkpointer: Optional LangGraph checkpointer for persistence

    Returns:
        SimulatedGraph (LangGraph integration deferred to Phase 2)
    """
    # NOTE: LangGraph's state serialization doesn't handle non-serializable
    # objects like Playwright Page. Using SimulatedGraph for now which
    # correctly passes the page through the node chain.
    #
    # TODO: Phase 2 - Use LangGraph with runtime context injection
    # for proper page handling while maintaining checkpointing benefits.

    logger.info("Using SimulatedGraph for browser automation (Phase 1)")
    return SimulatedGraph(
        llm=llm,
        reasoner_llm=reasoner_llm,
        pattern_library=pattern_library,
        system_prompt=system_prompt,
    )


class SimulatedGraph:
    """Simulated graph for browser automation.

    Implements the observe->think->act loop with proper state management.
    This handles non-serializable objects (like Playwright Page) correctly.
    """

    def __init__(
        self,
        llm: Any,
        reasoner_llm: Optional[Any] = None,
        pattern_library: Optional[PatternLibrary] = None,
        system_prompt: str = "",
    ):
        self.llm = llm
        self.reasoner_llm = reasoner_llm
        self.pattern_library = pattern_library
        self.system_prompt = system_prompt

    async def ainvoke(
        self,
        state: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run the graph simulation."""
        logger.info("[SimulatedGraph] Starting browser automation")

        # Validate required state
        if not state.get("page"):
            logger.error("[SimulatedGraph] No page in state!")
            state["done"] = True
            state["success"] = False
            state["summary"] = "Error: No browser page available"
            return state

        if not state.get("goal"):
            logger.error("[SimulatedGraph] No goal in state!")
            state["done"] = True
            state["success"] = False
            state["summary"] = "Error: No goal specified"
            return state

        # Run planner if needed
        if state.get("current_step", 0) == 0 and not state.get("execution_mode"):
            try:
                updates = await planner_node(state, self.pattern_library)
                state.update(updates)
            except Exception as e:
                logger.warning(f"[SimulatedGraph] Planner error: {e}, continuing with REACT mode")
                state["execution_mode"] = "react"

        max_steps = state.get("max_steps", 25)
        error_count = 0
        max_consecutive_errors = 5

        while not state.get("done") and state.get("current_step", 0) < max_steps:
            try:
                # Observe
                updates = await observe_node(state)
                if updates.get("last_error"):
                    error_count += 1
                    if error_count >= max_consecutive_errors:
                        logger.error(f"[SimulatedGraph] Too many consecutive errors ({error_count})")
                        break
                    continue
                state.update(updates)
                error_count = 0  # Reset on success

                # Think
                updates = await think_node(state, self.llm, self.system_prompt)
                if updates.get("last_error"):
                    error_count += 1
                    if error_count >= max_consecutive_errors:
                        break
                    continue
                state.update(updates)

                # Act
                updates = await act_node(state)
                state.update(updates)

                # Check if done
                if state.get("done"):
                    break

                # Route based on success/failure
                consecutive_failures = state.get("consecutive_failures", 0)
                next_node = should_continue(state)
                logger.info(f"[SimulatedGraph] After act: failures={consecutive_failures}, next={next_node}")

                if next_node == "finalize":
                    break
                elif next_node == "reflexion":
                    logger.info(f"[SimulatedGraph] Triggering REFLEXION after {consecutive_failures} failures")
                    if self.reasoner_llm:
                        updates = await reflexion_node(state, self.reasoner_llm)
                        state.update(updates)
                        logger.info("[SimulatedGraph] Reflexion complete, continuing")
                    else:
                        logger.warning("[SimulatedGraph] No reasoner LLM, skipping reflexion")
                        state["consecutive_failures"] = 0

            except Exception as e:
                logger.error(f"[SimulatedGraph] Step error: {e}")
                error_count += 1
                if error_count >= max_consecutive_errors:
                    state["last_error"] = str(e)
                    break

        # Finalize
        try:
            updates = await finalize_node(state)
            state.update(updates)
        except Exception as e:
            logger.error(f"[SimulatedGraph] Finalize error: {e}")
            state["done"] = True
            state["success"] = False
            state["summary"] = f"Error during finalization: {e}"

        logger.info(f"[SimulatedGraph] Complete: success={state.get('success')}, steps={state.get('current_step')}")
        return state


class GraphRunner:
    """High-level runner for the agent graph.

    Provides a clean interface for running sessions with the graph.
    """

    def __init__(
        self,
        llm: Any,
        reasoner_llm: Optional[Any] = None,
        pattern_library: Optional[PatternLibrary] = None,
        system_prompt: str = "",
        ui_server: Optional["UIServer"] = None,
        error_tracker: Optional["PlaywrightErrorTracker"] = None,
        checkpointer: Optional[Any] = None,
    ):
        """Initialize the graph runner.

        Args:
            llm: Navigator LLM for code generation
            reasoner_llm: Optional larger LLM for reflexion
            pattern_library: Optional pattern library for plan-and-execute
            system_prompt: System prompt for think node
            ui_server: Optional UI server for updates
            error_tracker: Optional error tracker
            checkpointer: Optional LangGraph checkpointer
        """
        self.llm = llm
        self.reasoner_llm = reasoner_llm
        self.pattern_library = pattern_library
        self.system_prompt = system_prompt
        self.ui_server = ui_server
        self.error_tracker = error_tracker

        # Build the graph
        self.graph = build_agent_graph(
            llm=llm,
            reasoner_llm=reasoner_llm,
            pattern_library=pattern_library,
            system_prompt=system_prompt,
            checkpointer=checkpointer,
        )

    async def run(
        self,
        page: "Page",
        goal: str,
        agent_id: str = "agent-1",
        mode_name: str = "poisonarr",
        max_steps: int = 25,
        timeout: int = 300,
    ) -> AgentState:
        """Run a browser automation session.

        Args:
            page: Playwright page to control
            goal: What to achieve
            agent_id: Agent identifier
            mode_name: Agent mode name
            max_steps: Maximum steps before giving up
            timeout: Session timeout in seconds

        Returns:
            Final agent state
        """
        logger.info(f"[GraphRunner] Starting session: {goal[:50]}...")

        # Get error context
        error_context = ""
        if self.error_tracker:
            error_context = self.error_tracker.get_context_injection()

        # Initialize state
        initial_state: Dict[str, Any] = {
            "agent_id": agent_id,
            "mode_name": mode_name,
            "goal": goal,
            "execution_mode": None,  # Will be set by planner
            "plan": [],
            "plan_step_index": 0,
            "plan_confidence": 0.0,
            "steps": [],
            "current_step": 0,
            "max_steps": max_steps,
            "reflexions": [],
            "consecutive_failures": 0,
            "reflexion_threshold": 2,
            "max_reflexions": 5,
            "perception_mode": PerceptionMode.ACCESSIBILITY.value,
            "vision_fallback_count": 0,
            "done": False,
            "success": False,
            "summary": "",
            "extracted_data": {},
            "urls_visited": [],
            "last_error": "",
            "error_context": error_context,
            # Runtime objects
            "page": page,
            "ui_server": self.ui_server,
            "error_tracker": self.error_tracker,  # Pass error tracker for learning
            # Vision config for fallback
            "vision_config": {
                "model": "llava:13b",
                "base_url": "http://localhost:11434",
                "provider": "ollama",
            },
        }

        # Run with timeout
        try:
            async with asyncio.timeout(timeout):
                final_state = await self.graph.ainvoke(
                    initial_state,
                    config={"recursion_limit": max_steps * 4},
                )
        except asyncio.TimeoutError:
            logger.warning(f"[GraphRunner] Session timeout after {timeout}s")
            final_state = initial_state
            final_state["done"] = True
            final_state["success"] = False
            final_state["summary"] = f"Session timeout ({timeout}s)"

        # Convert to AgentState
        result = dict_to_state(final_state)

        # Record errors if tracking enabled
        if self.error_tracker and final_state.get("last_error"):
            self.error_tracker.record_error(
                error_message=final_state["last_error"],
                code=final_state.get("steps", [{}])[-1].get("code", ""),
                page_url=page.url if page else "",
            )

        # Update pattern library stats
        if self.pattern_library:
            plan = final_state.get("plan", [])
            if plan:
                # Find which pattern was used
                match = self.pattern_library.find_match(goal)
                if match:
                    self.pattern_library.record_execution(
                        match.pattern.name,
                        final_state.get("success", False)
                    )

        logger.info(
            f"[GraphRunner] Session complete: success={result.success}, "
            f"steps={result.current_step}, tokens={result.total_tokens}"
        )

        return result

    async def run_interactive(
        self,
        page: "Page",
        goal: str,
        previous_state: Optional[AgentState] = None,
        agent_id: str = "agent-1",
        max_steps: int = 30,
        timeout: int = 300,
    ) -> tuple[bool, str, AgentState]:
        """Run an interactive session (for chat mode).

        Args:
            page: Playwright page to control
            goal: What to achieve
            previous_state: Optional previous state to continue from
            agent_id: Agent identifier
            max_steps: Maximum steps
            timeout: Session timeout

        Returns:
            Tuple of (success, summary, final_state)
        """
        result = await self.run(
            page=page,
            goal=goal,
            agent_id=agent_id,
            mode_name="interactive",
            max_steps=max_steps,
            timeout=timeout,
        )

        return result.success, result.summary, result


# Utility functions for CodeNavigator integration

def create_graph_runner_from_navigator(
    navigator: Any,  # CodeNavigator
    reasoner: Optional[Any] = None,  # Reasoner
    pattern_library_path: Optional[Path] = None,
) -> GraphRunner:
    """Create a GraphRunner from existing CodeNavigator.

    This allows easy migration from the old CodeNavigator to graph-based
    execution.

    Args:
        navigator: Existing CodeNavigator instance
        reasoner: Optional Reasoner instance for reflexion
        pattern_library_path: Optional path to persist patterns

    Returns:
        GraphRunner configured with navigator's settings
    """
    from ..prompts import load_prompt

    # Load the system prompt
    system_prompt = load_prompt("code_navigator")

    # Create pattern library
    pattern_library = None
    if pattern_library_path:
        pattern_library = PatternLibrary(persist_path=pattern_library_path)

    # Get reasoner LLM if available
    reasoner_llm = None
    if reasoner:
        reasoner_llm = reasoner.llm

    return GraphRunner(
        llm=navigator.llm,
        reasoner_llm=reasoner_llm,
        pattern_library=pattern_library,
        system_prompt=system_prompt,
        ui_server=navigator.ui_server,
        error_tracker=navigator.error_tracker,
    )
