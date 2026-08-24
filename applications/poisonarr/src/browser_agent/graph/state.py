"""Agent state definitions for LangGraph orchestration.

This module defines the state schema used by the graph nodes to track
the agent's progress through a browser automation session.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

from typing_extensions import Annotated


class ExecutionMode(str, Enum):
    """How the agent approaches the current goal."""

    REACT = "react"
    """Pure ReAct: observe -> think -> act loop. Used for unknown tasks."""

    PLAN_EXECUTE = "plan_execute"
    """Plan then execute: create upfront plan, follow steps. For known patterns."""

    REFLEXION = "reflexion"
    """Reflexion mode: actively recovering from failures with self-critique."""


class PerceptionMode(str, Enum):
    """How the agent perceives the page state."""

    ACCESSIBILITY = "accessibility"
    """Use accessibility tree (fast, structured, default)."""

    VISION = "vision"
    """Use screenshot + vision model (slower, for visual understanding)."""

    HYBRID = "hybrid"
    """Try accessibility first, fallback to vision on failures."""


class StepStatus(str, Enum):
    """Status of a single step in execution."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """A single step in a pre-planned execution sequence."""

    index: int
    """Step index (0-based)."""

    description: str
    """What this step should accomplish."""

    action_hint: str = ""
    """Hint for what action to take (e.g., 'click_button', 'fill_form')."""

    selector_hint: str = ""
    """Suggested selector or element description."""

    status: StepStatus = StepStatus.PENDING
    """Current status of this step."""

    attempts: int = 0
    """Number of execution attempts."""

    error: str = ""
    """Error message if failed."""

    code_executed: str = ""
    """The code that was executed for this step."""


@dataclass
class StepState:
    """State for a single observe->think->act cycle."""

    step_number: int
    """Which step this is (1-indexed for display)."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    """When this step started."""

    # Observation
    page_url: str = ""
    """Current page URL."""

    page_title: str = ""
    """Current page title."""

    observation: str = ""
    """Page state observation (accessibility tree or vision description)."""

    observation_mode: PerceptionMode = PerceptionMode.ACCESSIBILITY
    """How the observation was obtained."""

    # Thinking
    thought: str = ""
    """LLM's reasoning about what to do."""

    code: str = ""
    """Generated Playwright code."""

    # Acting
    success: bool = False
    """Whether the code executed successfully."""

    output: str = ""
    """Execution output or error message."""

    # Metrics
    prompt_tokens: int = 0
    completion_tokens: int = 0
    execution_time_ms: int = 0


@dataclass
class ReflexionState:
    """State for a reflexion (self-critique) cycle."""

    trigger_step: int
    """Which step triggered reflexion."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Analysis
    error_analysis: str = ""
    """Analysis of what went wrong."""

    root_cause: str = ""
    """Identified root cause."""

    # Fix
    fix_strategy: str = ""
    """Strategy to fix the issue."""

    learned_pattern: str = ""
    """Pattern learned for future avoidance."""

    # Outcome
    fix_applied: bool = False
    recovery_successful: bool = False


@dataclass
class AgentState:
    """Complete state for a browser automation session.

    This is the main state object passed through the LangGraph nodes.
    It tracks everything about the current session.
    """

    # === Identity ===
    agent_id: str = "agent-1"
    """Unique identifier for this agent instance."""

    mode_name: str = "poisonarr"
    """Which mode is running (poisonarr, researcher, monitor)."""

    goal: str = ""
    """The goal we're trying to achieve."""

    # === Execution Mode ===
    execution_mode: ExecutionMode = ExecutionMode.REACT
    """Current execution mode."""

    # === Plan (for PLAN_EXECUTE mode) ===
    plan: List[PlanStep] = field(default_factory=list)
    """Pre-planned steps (populated when using PLAN_EXECUTE mode)."""

    plan_step_index: int = 0
    """Current step in the plan (0-indexed)."""

    plan_confidence: float = 0.0
    """Confidence that the plan matches this goal (0.0-1.0)."""

    # === Step History ===
    steps: List[StepState] = field(default_factory=list)
    """History of all observe->think->act cycles."""

    current_step: int = 0
    """Current step number (0 = not started)."""

    max_steps: int = 25
    """Maximum steps before giving up."""

    # === Reflexion ===
    reflexions: List[ReflexionState] = field(default_factory=list)
    """History of reflexion cycles."""

    consecutive_failures: int = 0
    """Number of consecutive failed steps (triggers reflexion)."""

    reflexion_threshold: int = 2
    """Consecutive failures before entering reflexion."""

    max_reflexions: int = 5
    """Maximum reflexion cycles per session."""

    # === Perception ===
    perception_mode: PerceptionMode = PerceptionMode.ACCESSIBILITY
    """How to observe the page."""

    vision_fallback_count: int = 0
    """Number of times we've fallen back to vision."""

    # === Terminal State ===
    done: bool = False
    """Whether the goal is achieved or we've given up."""

    success: bool = False
    """Whether we achieved the goal."""

    summary: str = ""
    """Summary of what was accomplished."""

    extracted_data: Dict[str, Any] = field(default_factory=dict)
    """Any data extracted during the session."""

    # === Session Metadata ===
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    """Session start timestamp."""

    ended_at: str = ""
    """Session end timestamp."""

    total_tokens: int = 0
    """Total tokens used in this session."""

    urls_visited: List[str] = field(default_factory=list)
    """All URLs visited during the session."""

    # === Error Context ===
    last_error: str = ""
    """Most recent error message."""

    error_context: str = ""
    """Injected context about known error patterns."""

    def get_current_step(self) -> Optional[StepState]:
        """Get the current step state, if any."""
        if self.steps and self.current_step > 0:
            return self.steps[-1]
        return None

    def get_current_plan_step(self) -> Optional[PlanStep]:
        """Get the current plan step, if in PLAN_EXECUTE mode."""
        if self.execution_mode == ExecutionMode.PLAN_EXECUTE:
            if 0 <= self.plan_step_index < len(self.plan):
                return self.plan[self.plan_step_index]
        return None

    def should_reflexion(self) -> bool:
        """Check if we should enter reflexion mode."""
        return (
            self.consecutive_failures >= self.reflexion_threshold
            and len(self.reflexions) < self.max_reflexions
        )

    def record_step_success(self):
        """Record a successful step execution."""
        self.consecutive_failures = 0
        if self.steps:
            self.steps[-1].success = True

    def record_step_failure(self, error: str):
        """Record a failed step execution."""
        self.consecutive_failures += 1
        self.last_error = error
        if self.steps:
            self.steps[-1].success = False
            self.steps[-1].output = error

    def add_step(self, step: StepState):
        """Add a new step to history."""
        self.steps.append(step)
        self.current_step = step.step_number
        self.total_tokens += step.prompt_tokens + step.completion_tokens

    def add_reflexion(self, reflexion: ReflexionState):
        """Add a reflexion cycle to history."""
        self.reflexions.append(reflexion)
        if reflexion.recovery_successful:
            self.consecutive_failures = 0

    def finalize(self, success: bool, summary: str):
        """Mark session as complete."""
        self.done = True
        self.success = success
        self.summary = summary
        self.ended_at = datetime.now().isoformat()


# TypedDict version for LangGraph compatibility
class AgentStateDict(TypedDict, total=False):
    """TypedDict version of AgentState for LangGraph."""

    agent_id: str
    mode_name: str
    goal: str
    execution_mode: str
    plan: List[Dict[str, Any]]
    plan_step_index: int
    plan_confidence: float
    steps: List[Dict[str, Any]]
    current_step: int
    max_steps: int
    reflexions: List[Dict[str, Any]]
    consecutive_failures: int
    reflexion_threshold: int
    max_reflexions: int
    perception_mode: str
    vision_fallback_count: int
    done: bool
    success: bool
    summary: str
    extracted_data: Dict[str, Any]
    started_at: str
    ended_at: str
    total_tokens: int
    urls_visited: List[str]
    last_error: str
    error_context: str
    # Runtime objects (not serialized)
    page: Any  # Playwright Page
    ui_server: Any  # UIServer instance
    navigator: Any  # CodeNavigator instance
    error_tracker: Any  # PlaywrightErrorTracker instance


def state_to_dict(state: AgentState) -> Dict[str, Any]:
    """Convert AgentState to dict for serialization."""
    return {
        "agent_id": state.agent_id,
        "mode_name": state.mode_name,
        "goal": state.goal,
        "execution_mode": state.execution_mode.value,
        "plan": [
            {
                "index": s.index,
                "description": s.description,
                "action_hint": s.action_hint,
                "selector_hint": s.selector_hint,
                "status": s.status.value,
                "attempts": s.attempts,
                "error": s.error,
                "code_executed": s.code_executed,
            }
            for s in state.plan
        ],
        "plan_step_index": state.plan_step_index,
        "plan_confidence": state.plan_confidence,
        "steps": [
            {
                "step_number": s.step_number,
                "timestamp": s.timestamp,
                "page_url": s.page_url,
                "page_title": s.page_title,
                "observation": s.observation[:500] if s.observation else "",  # Truncate
                "observation_mode": s.observation_mode.value,
                "thought": s.thought,
                "code": s.code,
                "success": s.success,
                "output": s.output[:200] if s.output else "",  # Truncate
                "prompt_tokens": s.prompt_tokens,
                "completion_tokens": s.completion_tokens,
                "execution_time_ms": s.execution_time_ms,
            }
            for s in state.steps
        ],
        "current_step": state.current_step,
        "max_steps": state.max_steps,
        "reflexions": [
            {
                "trigger_step": r.trigger_step,
                "timestamp": r.timestamp,
                "error_analysis": r.error_analysis,
                "root_cause": r.root_cause,
                "fix_strategy": r.fix_strategy,
                "learned_pattern": r.learned_pattern,
                "fix_applied": r.fix_applied,
                "recovery_successful": r.recovery_successful,
            }
            for r in state.reflexions
        ],
        "consecutive_failures": state.consecutive_failures,
        "perception_mode": state.perception_mode.value,
        "vision_fallback_count": state.vision_fallback_count,
        "done": state.done,
        "success": state.success,
        "summary": state.summary,
        "extracted_data": state.extracted_data,
        "started_at": state.started_at,
        "ended_at": state.ended_at,
        "total_tokens": state.total_tokens,
        "urls_visited": state.urls_visited,
        "last_error": state.last_error,
    }


def dict_to_state(data: Dict[str, Any]) -> AgentState:
    """Convert dict back to AgentState."""
    state = AgentState(
        agent_id=data.get("agent_id", "agent-1"),
        mode_name=data.get("mode_name", "poisonarr"),
        goal=data.get("goal", ""),
        execution_mode=ExecutionMode(data.get("execution_mode", "react")),
        plan_step_index=data.get("plan_step_index", 0),
        plan_confidence=data.get("plan_confidence", 0.0),
        current_step=data.get("current_step", 0),
        max_steps=data.get("max_steps", 25),
        consecutive_failures=data.get("consecutive_failures", 0),
        perception_mode=PerceptionMode(data.get("perception_mode", "accessibility")),
        vision_fallback_count=data.get("vision_fallback_count", 0),
        done=data.get("done", False),
        success=data.get("success", False),
        summary=data.get("summary", ""),
        extracted_data=data.get("extracted_data", {}),
        started_at=data.get("started_at", ""),
        ended_at=data.get("ended_at", ""),
        total_tokens=data.get("total_tokens", 0),
        urls_visited=data.get("urls_visited", []),
        last_error=data.get("last_error", ""),
    )

    # Restore plan
    for p in data.get("plan", []):
        state.plan.append(PlanStep(
            index=p["index"],
            description=p["description"],
            action_hint=p.get("action_hint", ""),
            selector_hint=p.get("selector_hint", ""),
            status=StepStatus(p.get("status", "pending")),
            attempts=p.get("attempts", 0),
            error=p.get("error", ""),
            code_executed=p.get("code_executed", ""),
        ))

    # Restore steps
    for s in data.get("steps", []):
        state.steps.append(StepState(
            step_number=s["step_number"],
            timestamp=s.get("timestamp", ""),
            page_url=s.get("page_url", ""),
            page_title=s.get("page_title", ""),
            observation=s.get("observation", ""),
            observation_mode=PerceptionMode(s.get("observation_mode", "accessibility")),
            thought=s.get("thought", ""),
            code=s.get("code", ""),
            success=s.get("success", False),
            output=s.get("output", ""),
            prompt_tokens=s.get("prompt_tokens", 0),
            completion_tokens=s.get("completion_tokens", 0),
            execution_time_ms=s.get("execution_time_ms", 0),
        ))

    # Restore reflexions
    for r in data.get("reflexions", []):
        state.reflexions.append(ReflexionState(
            trigger_step=r["trigger_step"],
            timestamp=r.get("timestamp", ""),
            error_analysis=r.get("error_analysis", ""),
            root_cause=r.get("root_cause", ""),
            fix_strategy=r.get("fix_strategy", ""),
            learned_pattern=r.get("learned_pattern", ""),
            fix_applied=r.get("fix_applied", False),
            recovery_successful=r.get("recovery_successful", False),
        ))

    return state
