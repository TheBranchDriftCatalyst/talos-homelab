"""LangGraph-based agent orchestration.

This package provides a production-grade state machine for browser automation
using LangGraph. It wraps the existing CodeNavigator with:

- Reflexion: Self-critique and learning from failures
- Plan-and-Execute: Upfront planning for known workflow patterns
- Vision: Screenshot fallback when accessibility trees fail
- Checkpointing: Session resume and recovery

Architecture:
    SESSION START
         |
         v
    PLANNER NODE
    - Check PatternLibrary for known workflows
    - Known -> PLAN_EXECUTE mode (upfront plan)
    - Unknown -> REACT mode (exploratory)
         |
         v
    OBSERVE NODE
    - Primary: Accessibility tree (95% of cases)
    - Fallback: Vision + Set-of-Mark (on selector failures)
         |
         v
    THINK NODE (Code Generation)
    - Navigator model generates Playwright code
    - Injects error context from PlaywrightErrorTracker
    - Plan-guided OR pure ReAct depending on mode
         |
         v
    ACT NODE (Execution)
    - Execute code with timeout
    - Track success/failure
         |
    +----+----+
    |    |    |
   [OK] [ERR] [DONE]
    |    |      |
    |    v      v
    | REFLEXION  FINALIZE
    |  (Reasoner)
    |    |
    +----+
         |
         v
    CONTINUE -> OBSERVE (loop)
"""

from .state import (
    AgentState,
    StepState,
    ReflexionState,
    PlanStep,
    ExecutionMode,
    PerceptionMode,
)
from .builder import build_agent_graph, GraphRunner
from .nodes import (
    planner_node,
    observe_node,
    think_node,
    act_node,
    reflexion_node,
    finalize_node,
)
from .patterns import PatternLibrary, WorkflowPattern

__all__ = [
    # State
    "AgentState",
    "StepState",
    "ReflexionState",
    "PlanStep",
    "ExecutionMode",
    "PerceptionMode",
    # Builder
    "build_agent_graph",
    "GraphRunner",
    # Nodes
    "planner_node",
    "observe_node",
    "think_node",
    "act_node",
    "reflexion_node",
    "finalize_node",
    # Patterns
    "PatternLibrary",
    "WorkflowPattern",
]
