"""Web UI server for Browser Agent monitoring."""

import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


@dataclass
class AgentStats:
    """Token and usage statistics for an agent."""
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    actions_taken: int = 0
    successful_sessions: int = 0
    failed_sessions: int = 0
    avg_tokens_per_call: float = 0.0
    context_size: int = 0  # Current context window usage
    memory_entries: int = 0  # Number of memory entries


@dataclass
class ChatMessage:
    """A chat message in interactive mode."""
    role: str  # user, assistant, system
    content: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class AgentState:
    """Current state of an agent."""

    agent_id: str
    status: str = "idle"  # idle, planning, browsing, paused, interactive
    react_stage: str = "idle"  # idle, observe, reason, act
    restart_requested: bool = False
    paused: bool = False
    interactive_mode: bool = False  # When True, autonomous loop pauses for chat
    pending_chat_goal: Optional[str] = None  # User's chat input to process
    chat_messages: List[ChatMessage] = field(default_factory=list)
    current_session: Optional[dict] = None
    current_step: Optional[dict] = None
    step_index: int = 0
    total_steps: int = 0
    screenshot_b64: Optional[str] = None
    current_url: str = ""
    session_count: int = 0
    logs: List[dict] = field(default_factory=list)
    stats: AgentStats = field(default_factory=AgentStats)

    def add_log(self, level: str, message: str):
        """Add a log entry."""
        self.logs.append({
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message
        })
        # Keep last 100 logs
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]

    def record_llm_call(self, prompt_tokens: int, completion_tokens: int, context_size: int = 0):
        """Record an LLM call with token usage."""
        self.stats.prompt_tokens += prompt_tokens
        self.stats.completion_tokens += completion_tokens
        self.stats.total_tokens += prompt_tokens + completion_tokens
        self.stats.llm_calls += 1
        self.stats.avg_tokens_per_call = self.stats.total_tokens / self.stats.llm_calls
        if context_size > 0:
            self.stats.context_size = context_size

    def record_action(self):
        """Record an action taken."""
        self.stats.actions_taken += 1

    def record_session_result(self, success: bool):
        """Record session success/failure."""
        if success:
            self.stats.successful_sessions += 1
        else:
            self.stats.failed_sessions += 1


class UIServer:
    """WebSocket server for Poisonarr monitoring UI."""

    def __init__(self, litellm_url: str = None):
        self.app = FastAPI(title="Poisonarr Monitor")
        self.agents: Dict[str, AgentState] = {}
        self.connections: List[WebSocket] = []
        self._current_model: str = "ollama/llama3.2"  # Default, updated from config
        self._litellm_url: str = litellm_url or "http://litellm.catalyst-llm.svc.cluster.local:4000/v1"
        self._setup_routes()

    def set_current_model(self, model: str):
        """Set the current model (called from agent setup)."""
        self._current_model = model

    def set_litellm_url(self, url: str):
        """Set the LiteLLM URL for fetching models."""
        self._litellm_url = url

    def set_memory_callback(self, callback):
        """Set callback to fetch memory data. Callback signature: (agent_id) -> dict"""
        self._memory_callback = callback

    def set_observations_callback(self, callback):
        """Set callback to fetch observations data. Callback signature: (agent_id) -> dict"""
        self._observations_callback = callback

    def get_current_model(self) -> str:
        """Get the current model."""
        return self._current_model

    def _setup_routes(self):
        """Set up FastAPI routes."""

        @self.app.get("/", response_class=HTMLResponse)
        async def index():
            return self._get_html()

        @self.app.post("/api/restart/{agent_id}")
        async def restart_agent(agent_id: str):
            if agent_id in self.agents:
                self.agents[agent_id].restart_requested = True
                await self.add_log(agent_id, "warning", "🔄 Restart requested...")
                await self.broadcast({"type": "restart_requested", "agent_id": agent_id})
                return {"status": "ok", "message": "Restart requested"}
            return {"status": "error", "message": "Agent not found"}

        @self.app.post("/api/skip/{agent_id}")
        async def skip_session(agent_id: str):
            if agent_id in self.agents:
                self.agents[agent_id].restart_requested = True  # Reuse flag to skip current session
                await self.add_log(agent_id, "info", "⏭️ Skipping to next session...")
                return {"status": "ok", "message": "Skip requested"}
            return {"status": "error", "message": f"Agent not found. Available: {list(self.agents.keys())}"}

        @self.app.post("/api/pause/{agent_id}")
        async def toggle_pause(agent_id: str):
            if agent_id in self.agents:
                agent = self.agents[agent_id]
                agent.paused = not agent.paused
                status = "paused" if agent.paused else "resumed"
                await self.add_log(agent_id, "info", f"⏸️ Agent {status}")
                await self.broadcast({"type": "pause_update", "agent_id": agent_id, "paused": agent.paused})
                return {"status": "ok", "paused": agent.paused}
            return {"status": "error", "message": "Agent not found"}

        @self.app.get("/api/agents")
        async def list_agents():
            return {"agents": list(self.agents.keys())}

        @self.app.get("/api/models")
        async def list_models():
            """Get available models from LiteLLM."""
            try:
                # Remove /v1 suffix for models endpoint
                base_url = self._litellm_url.rstrip("/")
                if base_url.endswith("/v1"):
                    base_url = base_url[:-3]
                models_url = f"{base_url}/v1/models"

                async with httpx.AsyncClient() as client:
                    resp = await client.get(models_url, timeout=10.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        # LiteLLM returns OpenAI-compatible format: {"data": [{"id": "model-name", ...}]}
                        models = [m["id"] for m in data.get("data", [])]
                        return {"models": models}
            except Exception as e:
                logger.warning(f"Failed to get models from LiteLLM: {e}")
            return {"models": []}

        @self.app.get("/api/current-model")
        async def get_current_model():
            """Get the current model being used."""
            return {"model": self._current_model}

        @self.app.post("/api/model/{model_name}")
        async def set_model(model_name: str):
            """Set the model to use (requires restart to take effect)."""
            self._current_model = model_name
            await self.broadcast({"type": "model_update", "model": model_name})
            return {"status": "ok", "model": model_name, "note": "Model change takes effect on next session"}

        @self.app.get("/api/memory/{agent_id}")
        async def get_memory(agent_id: str):
            """Get memory data for an agent."""
            logger.debug(f"Memory API called for agent: {agent_id}")
            logger.debug(f"Available agents: {list(self.agents.keys())}")

            if agent_id not in self.agents:
                logger.warning(f"Agent {agent_id} not found in {list(self.agents.keys())}")
                return {"error": f"Agent not found. Available: {list(self.agents.keys())}", "memory": None}

            # Get memory from the memory manager callback if set
            if hasattr(self, '_memory_callback') and self._memory_callback:
                try:
                    logger.debug("Calling memory callback...")
                    memory_data = self._memory_callback(agent_id)
                    logger.debug(f"Memory callback returned: {type(memory_data)}")
                    return {"memory": memory_data}
                except Exception as e:
                    logger.exception(f"Failed to get memory: {e}")
                    return {"error": str(e), "memory": None}
            else:
                logger.warning("No memory callback set")

            return {"error": "Memory callback not configured", "memory": None}

        @self.app.get("/api/observations/{agent_id}")
        async def get_observations(agent_id: str):
            """Get enhanced observations (console logs, network, DOM) for an agent."""
            if agent_id not in self.agents:
                return {"error": "Agent not found", "observations": None}

            # Get observations from callback if set
            if hasattr(self, '_observations_callback') and self._observations_callback:
                try:
                    obs_data = self._observations_callback(agent_id)
                    return {"observations": obs_data}
                except Exception as e:
                    logger.warning(f"Failed to get observations: {e}")
                    return {"error": str(e), "observations": None}

            return {"error": "Observations not available", "observations": None}

        @self.app.post("/api/interactive/{agent_id}")
        async def toggle_interactive_mode(agent_id: str):
            """Toggle interactive chat mode on/off."""
            if agent_id not in self.agents:
                return {"status": "error", "message": "Agent not found"}

            agent = self.agents[agent_id]
            agent.interactive_mode = not agent.interactive_mode

            if agent.interactive_mode:
                agent.status = "interactive"
                agent.paused = True  # Pause autonomous loop
                await self.add_log(agent_id, "info", "💬 Entering interactive mode - autonomous loop paused")
                # Add system message to chat
                agent.chat_messages.append(ChatMessage(
                    role="system",
                    content="Interactive mode enabled. You can now direct the browser. Type a goal like 'Go to github.com and search for Python projects' or a command like 'click the search button'."
                ))
            else:
                agent.status = "idle"
                agent.paused = False  # Resume autonomous loop
                await self.add_log(agent_id, "info", "🤖 Exiting interactive mode - resuming autonomous loop")
                agent.chat_messages.append(ChatMessage(
                    role="system",
                    content="Interactive mode disabled. Autonomous browsing will resume."
                ))

            await self.broadcast({
                "type": "interactive_mode",
                "agent_id": agent_id,
                "interactive_mode": agent.interactive_mode,
                "status": agent.status
            })
            await self._broadcast_chat(agent_id)

            return {"status": "ok", "interactive_mode": agent.interactive_mode}

        @self.app.post("/api/chat/{agent_id}")
        async def send_chat_message(agent_id: str, request: Request):
            """Send a chat message in interactive mode."""
            if agent_id not in self.agents:
                return {"status": "error", "message": "Agent not found"}

            agent = self.agents[agent_id]
            if not agent.interactive_mode:
                return {"status": "error", "message": "Not in interactive mode"}

            try:
                body = await request.json()
                user_message = body.get("content", "").strip()
            except Exception as e:
                logger.error(f"Failed to parse chat message: {e}")
                return {"status": "error", "message": "Invalid JSON body"}

            if not user_message:
                return {"status": "error", "message": "Empty message"}

            logger.info(f"[CHAT] Received message for {agent_id}: {user_message[:50]}...")

            # Add user message to chat
            agent.chat_messages.append(ChatMessage(role="user", content=user_message))

            # Set pending goal for agent to process
            agent.pending_chat_goal = user_message
            logger.info(f"[CHAT] Set pending_chat_goal: {agent.pending_chat_goal[:50]}...")

            await self._broadcast_chat(agent_id)
            await self.add_log(agent_id, "info", f"💬 User: {user_message[:50]}...")

            return {"status": "ok", "message": "Message sent"}

        @self.app.get("/api/chat/{agent_id}")
        async def get_chat_history(agent_id: str):
            """Get chat history for an agent."""
            if agent_id not in self.agents:
                return {"status": "error", "messages": []}

            agent = self.agents[agent_id]
            return {
                "status": "ok",
                "interactive_mode": agent.interactive_mode,
                "messages": [
                    {"role": m.role, "content": m.content, "timestamp": m.timestamp}
                    for m in agent.chat_messages[-50:]  # Last 50 messages
                ]
            }

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.connections.append(websocket)

            try:
                # Send current state
                await self._send_full_state(websocket)

                # Keep connection alive and handle messages
                while True:
                    try:
                        data = await asyncio.wait_for(
                            websocket.receive_text(),
                            timeout=30.0
                        )
                        # Handle client messages if needed
                        msg = json.loads(data)
                        if msg.get("type") == "ping":
                            await websocket.send_json({"type": "pong"})
                    except asyncio.TimeoutError:
                        # Send ping to keep alive
                        await websocket.send_json({"type": "ping"})

            except WebSocketDisconnect:
                pass
            finally:
                if websocket in self.connections:
                    self.connections.remove(websocket)

    async def _send_full_state(self, websocket: WebSocket):
        """Send full state to a websocket."""
        state = {
            "type": "full_state",
            "agents": {
                agent_id: {
                    "agent_id": agent.agent_id,
                    "status": agent.status,
                    "react_stage": agent.react_stage,
                    "current_session": agent.current_session,
                    "current_step": agent.current_step,
                    "step_index": agent.step_index,
                    "total_steps": agent.total_steps,
                    "screenshot_b64": agent.screenshot_b64,
                    "current_url": agent.current_url,
                    "session_count": agent.session_count,
                    "logs": agent.logs[-20:],  # Last 20 logs
                    "stats": {
                        "total_tokens": agent.stats.total_tokens,
                        "prompt_tokens": agent.stats.prompt_tokens,
                        "completion_tokens": agent.stats.completion_tokens,
                        "llm_calls": agent.stats.llm_calls,
                        "actions_taken": agent.stats.actions_taken,
                        "successful_sessions": agent.stats.successful_sessions,
                        "failed_sessions": agent.stats.failed_sessions,
                        "avg_tokens_per_call": round(agent.stats.avg_tokens_per_call, 1),
                        "context_size": agent.stats.context_size,
                        "memory_entries": agent.stats.memory_entries,
                    },
                }
                for agent_id, agent in self.agents.items()
            }
        }
        await websocket.send_json(state)

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        dead_connections = []
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.append(ws)

        for ws in dead_connections:
            if ws in self.connections:
                self.connections.remove(ws)

    def register_agent(self, agent_id: str) -> AgentState:
        """Register a new agent."""
        if agent_id not in self.agents:
            self.agents[agent_id] = AgentState(agent_id=agent_id)
            logger.info(f"Registered agent: {agent_id}")
        return self.agents[agent_id]

    def list_agents(self) -> list:
        """List all registered agents."""
        return list(self.agents.keys())

    async def update_status(self, agent_id: str, status: str):
        """Update agent status."""
        if agent_id in self.agents:
            self.agents[agent_id].status = status
            await self.broadcast({
                "type": "status_update",
                "agent_id": agent_id,
                "status": status
            })

    async def update_react_stage(self, agent_id: str, stage: str):
        """Update ReAct loop stage (observe, reason, act)."""
        if agent_id in self.agents:
            self.agents[agent_id].react_stage = stage
            await self.broadcast({
                "type": "react_stage",
                "agent_id": agent_id,
                "stage": stage
            })

    def check_restart_requested(self, agent_id: str) -> bool:
        """Check if restart was requested and clear the flag."""
        if agent_id in self.agents and self.agents[agent_id].restart_requested:
            self.agents[agent_id].restart_requested = False
            return True
        return False

    def is_paused(self, agent_id: str) -> bool:
        """Check if agent is paused."""
        if agent_id in self.agents:
            return self.agents[agent_id].paused
        return False

    async def update_session(self, agent_id: str, session: dict):
        """Update current session plan."""
        if agent_id in self.agents:
            agent = self.agents[agent_id]
            agent.current_session = session
            agent.session_count += 1
            agent.step_index = 0
            agent.total_steps = len(session.get("steps", []))
            await self.broadcast({
                "type": "session_update",
                "agent_id": agent_id,
                "session": session,
                "session_count": agent.session_count
            })

    async def update_step(self, agent_id: str, step: dict, index: int):
        """Update current step."""
        if agent_id in self.agents:
            agent = self.agents[agent_id]
            agent.current_step = step
            agent.step_index = index
            await self.broadcast({
                "type": "step_update",
                "agent_id": agent_id,
                "step": step,
                "step_index": index,
                "total_steps": agent.total_steps
            })

    async def update_screenshot(self, agent_id: str, screenshot_bytes: bytes, url: str):
        """Update browser screenshot."""
        if agent_id in self.agents:
            agent = self.agents[agent_id]
            agent.screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
            agent.current_url = url
            await self.broadcast({
                "type": "screenshot_update",
                "agent_id": agent_id,
                "screenshot_b64": agent.screenshot_b64,
                "current_url": url
            })

    async def add_log(self, agent_id: str, level: str, message: str):
        """Add a log entry."""
        if agent_id in self.agents:
            self.agents[agent_id].add_log(level, message)
            await self.broadcast({
                "type": "log",
                "agent_id": agent_id,
                "level": level,
                "message": message,
                "timestamp": datetime.now().isoformat()
            })

    async def record_llm_call(
        self,
        agent_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        context_size: int = 0
    ):
        """Record an LLM API call with token usage."""
        if agent_id in self.agents:
            self.agents[agent_id].record_llm_call(prompt_tokens, completion_tokens, context_size)
            await self._broadcast_stats(agent_id)

    async def record_action(self, agent_id: str):
        """Record an action taken by the agent."""
        if agent_id in self.agents:
            self.agents[agent_id].record_action()
            await self._broadcast_stats(agent_id)

    async def record_session_result(self, agent_id: str, success: bool):
        """Record session completion."""
        if agent_id in self.agents:
            self.agents[agent_id].record_session_result(success)
            await self._broadcast_stats(agent_id)

    async def update_memory_stats(self, agent_id: str, memory_entries: int):
        """Update memory statistics."""
        if agent_id in self.agents:
            self.agents[agent_id].stats.memory_entries = memory_entries
            await self._broadcast_stats(agent_id)

    async def _broadcast_stats(self, agent_id: str):
        """Broadcast updated stats to all clients."""
        if agent_id in self.agents:
            stats = self.agents[agent_id].stats
            await self.broadcast({
                "type": "stats_update",
                "agent_id": agent_id,
                "stats": {
                    "total_tokens": stats.total_tokens,
                    "prompt_tokens": stats.prompt_tokens,
                    "completion_tokens": stats.completion_tokens,
                    "llm_calls": stats.llm_calls,
                    "actions_taken": stats.actions_taken,
                    "successful_sessions": stats.successful_sessions,
                    "failed_sessions": stats.failed_sessions,
                    "avg_tokens_per_call": round(stats.avg_tokens_per_call, 1),
                    "context_size": stats.context_size,
                    "memory_entries": stats.memory_entries,
                }
            })

    async def broadcast_observations(self, agent_id: str, observations: dict):
        """Broadcast observations update to all clients."""
        await self.broadcast({
            "type": "observations_update",
            "agent_id": agent_id,
            "observations": observations,
        })

    async def _broadcast_chat(self, agent_id: str):
        """Broadcast chat history to all clients."""
        if agent_id in self.agents:
            agent = self.agents[agent_id]
            await self.broadcast({
                "type": "chat_update",
                "agent_id": agent_id,
                "interactive_mode": agent.interactive_mode,
                "messages": [
                    {"role": m.role, "content": m.content, "timestamp": m.timestamp}
                    for m in agent.chat_messages[-50:]
                ]
            })

    def is_interactive_mode(self, agent_id: str) -> bool:
        """Check if agent is in interactive mode."""
        if agent_id in self.agents:
            return self.agents[agent_id].interactive_mode
        return False

    def get_pending_chat_goal(self, agent_id: str) -> Optional[str]:
        """Get and clear the pending chat goal."""
        if agent_id in self.agents:
            goal = self.agents[agent_id].pending_chat_goal
            self.agents[agent_id].pending_chat_goal = None
            return goal
        return None

    async def add_chat_response(self, agent_id: str, content: str, role: str = "assistant"):
        """Add a response message to the chat."""
        if agent_id in self.agents:
            agent = self.agents[agent_id]
            agent.chat_messages.append(ChatMessage(role=role, content=content))
            # Keep last 100 messages
            if len(agent.chat_messages) > 100:
                agent.chat_messages = agent.chat_messages[-100:]
            await self._broadcast_chat(agent_id)

    def _get_html(self) -> str:
        """Return the monitoring UI HTML."""
        return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Poisonarr Monitor</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .log-info { color: #60a5fa; }
        .log-warning { color: #fbbf24; }
        .log-error { color: #f87171; }
        .log-debug { color: #9ca3af; }

        .status-idle { background: #374151; }
        .status-planning { background: #7c3aed; }
        .status-browsing { background: #059669; }
        .status-paused { background: #d97706; }

        .react-idle { background: #374151; }
        .react-observe { background: #3b82f6; }
        .react-reason { background: #8b5cf6; }
        .react-act { background: #10b981; }

        @keyframes pulse-stage {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        .react-active {
            animation: pulse-stage 0.8s ease-in-out infinite;
        }

        #screenshot {
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }

        .session-card {
            background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
        }

        .step-active {
            border-left: 3px solid #10b981;
            background: rgba(16, 185, 129, 0.1);
        }

        .step-complete {
            opacity: 0.5;
        }

        @keyframes pulse-border {
            0%, 100% { border-color: #10b981; }
            50% { border-color: #34d399; }
        }

        .recording {
            animation: pulse-border 1.5s ease-in-out infinite;
        }

        /* Expanded browser view */
        .browser-expanded {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 100;
            background: rgba(0, 0, 0, 0.95);
            padding: 20px;
            display: flex;
            flex-direction: column;
        }

        .browser-expanded #screenshot-container {
            flex: 1;
            max-height: none;
        }

        .browser-expanded #screenshot {
            max-height: 100%;
            width: auto;
            margin: auto;
        }

        /* Memory panel */
        .memory-panel {
            position: fixed;
            top: 0;
            right: -450px;
            width: 450px;
            height: 100vh;
            background: #1f2937;
            border-left: 1px solid #374151;
            z-index: 150;
            transition: right 0.3s ease;
            display: flex;
            flex-direction: column;
            box-shadow: -4px 0 20px rgba(0, 0, 0, 0.5);
        }

        .memory-panel.open {
            right: 0;
        }

        .memory-panel-header {
            padding: 16px;
            border-bottom: 1px solid #374151;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #111827;
        }

        .memory-panel-content {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
        }

        .memory-section {
            margin-bottom: 20px;
        }

        .memory-section h4 {
            color: #9ca3af;
            font-size: 12px;
            text-transform: uppercase;
            margin-bottom: 8px;
        }

        .memory-session {
            background: #374151;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 8px;
        }

        .memory-session.success {
            border-left: 3px solid #10b981;
        }

        .memory-session.failed {
            border-left: 3px solid #ef4444;
        }

        .memory-site-tag {
            display: inline-block;
            background: #4b5563;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            margin: 2px;
        }

        .memory-badge-clickable {
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }

        .memory-badge-clickable:hover {
            transform: scale(1.05);
            box-shadow: 0 0 10px rgba(236, 72, 153, 0.5);
        }

        .memory-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.5);
            z-index: 140;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }

        .memory-overlay.open {
            opacity: 1;
            pointer-events: auto;
        }
    </style>
</head>
<body class="bg-gray-900 text-white min-h-screen">
    <!-- Header -->
    <header class="bg-gray-800 border-b border-gray-700 px-6 py-4">
        <div class="flex items-center justify-between">
            <div class="flex items-center gap-4">
                <h1 class="text-2xl font-bold text-emerald-400">🧪 Poisonarr</h1>
                <span class="text-gray-400">Traffic Noise Generator</span>
            </div>
            <div class="flex items-center gap-4">
                <div class="flex items-center gap-2 mr-4">
                    <span class="text-gray-400 text-sm">Model:</span>
                    <select id="model-select" onchange="changeModel(this.value)" class="bg-gray-700 text-white text-sm rounded px-2 py-1 border border-gray-600">
                        <option value="">Loading...</option>
                    </select>
                </div>
                <div class="flex items-center gap-4">
                    <button id="btn-pause" onclick="togglePause()" class="px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-sm flex items-center gap-1">
                        ⏸️ Pause
                    </button>
                    <button id="btn-skip" onclick="skipSession()" class="px-3 py-1 bg-yellow-600 hover:bg-yellow-500 rounded text-sm flex items-center gap-1">
                        ⏭️ Skip
                    </button>
                    <button id="btn-restart" onclick="restartAgent()" class="px-3 py-1 bg-red-600 hover:bg-red-500 rounded text-sm flex items-center gap-1">
                        🔄 Restart
                    </button>
                    <div id="connection-status" class="flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-red-500"></span>
                        <span class="text-sm text-gray-400">Disconnected</span>
                    </div>
                </div>
            </div>
        </div>
    </header>

    <!-- Agent Tabs -->
    <div id="agent-tabs" class="bg-gray-800 border-b border-gray-700 px-6">
        <div class="flex gap-2 py-2">
            <button class="px-4 py-2 rounded-t bg-gray-700 text-white" data-agent="agent-1">
                Agent 1
            </button>
        </div>
    </div>

    <!-- Main Content -->
    <main class="flex h-[calc(100vh-120px)]">
        <!-- Left Panel: Browser View -->
        <div class="w-1/2 p-6 border-r border-gray-700 flex flex-col">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-lg font-semibold text-gray-300">Browser View</h2>
                <div class="flex items-center gap-2">
                    <button id="btn-expand" onclick="toggleExpand()" class="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm" title="Expand browser view">
                        ⛶
                    </button>
                    <div id="react-stage" class="px-3 py-1 rounded-full text-sm font-mono react-idle">
                        IDLE
                    </div>
                    <div id="agent-status" class="px-3 py-1 rounded-full text-sm status-idle">
                        Idle
                    </div>
                </div>
            </div>

            <!-- URL Bar -->
            <div class="bg-gray-800 rounded-lg px-4 py-2 mb-4 flex items-center gap-2">
                <span class="text-gray-500">🔗</span>
                <a id="current-url" href="#" target="_blank" rel="noopener noreferrer" class="text-blue-400 hover:text-blue-300 text-sm truncate hover:underline cursor-pointer">No page loaded</a>
            </div>

            <!-- Screenshot -->
            <div class="flex-1 bg-gray-800 rounded-lg overflow-hidden flex items-center justify-center border-2 border-gray-700" id="screenshot-container">
                <div id="no-screenshot" class="text-gray-500 text-center">
                    <div class="text-4xl mb-2">🖥️</div>
                    <div>Waiting for browser...</div>
                </div>
                <img id="screenshot" class="hidden" alt="Browser Screenshot">
            </div>

            <!-- Session Counter -->
            <div class="mt-4 text-center text-gray-400">
                Sessions completed: <span id="session-count" class="text-emerald-400 font-bold">0</span>
            </div>

            <!-- Stats Panel -->
            <div class="mt-4 bg-gray-800 rounded-lg p-4">
                <h3 class="text-sm font-semibold text-gray-400 mb-3">Agent Stats</h3>
                <div class="grid grid-cols-3 gap-3 text-sm">
                    <div class="bg-gray-700 rounded p-2">
                        <div class="text-gray-400 text-xs">Total Tokens</div>
                        <div id="stat-total-tokens" class="text-lg font-bold text-blue-400">0</div>
                    </div>
                    <div class="bg-gray-700 rounded p-2">
                        <div class="text-gray-400 text-xs">LLM Calls</div>
                        <div id="stat-llm-calls" class="text-lg font-bold text-purple-400">0</div>
                    </div>
                    <div class="bg-gray-700 rounded p-2">
                        <div class="text-gray-400 text-xs">Avg Tokens/Call</div>
                        <div id="stat-avg-tokens" class="text-lg font-bold text-cyan-400">0</div>
                    </div>
                    <div class="bg-gray-700 rounded p-2">
                        <div class="text-gray-400 text-xs">Context Size</div>
                        <div id="stat-context-size" class="text-lg font-bold text-yellow-400">0</div>
                    </div>
                    <div class="bg-gray-700 rounded p-2">
                        <div class="text-gray-400 text-xs">Actions</div>
                        <div id="stat-actions" class="text-lg font-bold text-emerald-400">0</div>
                    </div>
                    <div class="bg-gray-700 rounded p-2 memory-badge-clickable" onclick="toggleMemoryPanel()" title="Click to view memory">
                        <div class="text-gray-400 text-xs">Memory 📂</div>
                        <div id="stat-memory" class="text-lg font-bold text-pink-400">0</div>
                    </div>
                </div>
                <div class="mt-3 flex justify-center gap-6 text-sm">
                    <div class="flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
                        <span class="text-gray-400">Success:</span>
                        <span id="stat-success" class="text-emerald-400 font-bold">0</span>
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-red-500"></span>
                        <span class="text-gray-400">Failed:</span>
                        <span id="stat-failed" class="text-red-400 font-bold">0</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Right Panel: Planning & Logs -->
        <div class="w-1/2 p-6 flex flex-col overflow-hidden">
            <!-- Current Session -->
            <div class="mb-6">
                <h2 class="text-lg font-semibold text-gray-300 mb-3">Current Session</h2>
                <div id="session-info" class="session-card rounded-lg p-4">
                    <div id="no-session" class="text-gray-400 text-center py-8">
                        No active session
                    </div>
                    <div id="session-content" class="hidden">
                        <div class="flex items-start gap-3 mb-4">
                            <div class="text-3xl">🎭</div>
                            <div>
                                <div id="session-persona" class="font-medium text-white"></div>
                                <div id="session-intent" class="text-sm text-indigo-300 mt-1"></div>
                            </div>
                        </div>
                        <div class="flex gap-2 mb-4">
                            <span id="session-mood" class="px-2 py-1 rounded bg-indigo-600 text-xs"></span>
                            <span id="session-progress" class="px-2 py-1 rounded bg-gray-600 text-xs"></span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Steps -->
            <div class="mb-6 flex-shrink-0">
                <h2 class="text-lg font-semibold text-gray-300 mb-3">Session Steps</h2>
                <div id="steps-container" class="space-y-2 max-h-48 overflow-y-auto">
                    <div class="text-gray-500 text-sm">No steps</div>
                </div>
            </div>

            <!-- Activity Log / Observations / Chat Tabs -->
            <div class="flex-1 flex flex-col min-h-0">
                <div class="flex items-center gap-2 mb-3">
                    <button id="tab-logs" onclick="switchTab('logs')" class="px-3 py-1 rounded text-sm bg-gray-700 text-white">Activity Log</button>
                    <button id="tab-observations" onclick="switchTab('observations')" class="px-3 py-1 rounded text-sm bg-gray-800 text-gray-400 hover:text-white">Observations</button>
                    <button id="tab-chat" onclick="switchTab('chat')" class="px-3 py-1 rounded text-sm bg-gray-800 text-gray-400 hover:text-white">💬 Chat</button>
                    <div class="flex-1"></div>
                    <button id="btn-interactive" onclick="toggleInteractiveMode()" class="px-3 py-1 rounded text-sm bg-gray-600 hover:bg-gray-500 text-gray-300">
                        🎮 Interactive Mode
                    </button>
                </div>

                <!-- Activity Log Tab -->
                <div id="panel-logs" class="flex-1 bg-gray-800 rounded-lg p-4 overflow-y-auto font-mono text-xs leading-relaxed" style="word-break: break-word;">
                    <div class="text-gray-500">Waiting for activity...</div>
                </div>

                <!-- Observations Tab -->
                <div id="panel-observations" class="flex-1 bg-gray-800 rounded-lg p-4 overflow-y-auto hidden">
                    <div class="space-y-4">
                        <!-- Console Logs -->
                        <div>
                            <h4 class="text-xs font-semibold text-yellow-400 mb-2 flex items-center gap-1">
                                <span>&#128187;</span> Console Logs
                                <span id="obs-console-count" class="text-gray-500">(0)</span>
                            </h4>
                            <div id="obs-console" class="space-y-1 max-h-32 overflow-y-auto">
                                <div class="text-gray-500 text-xs">No console logs</div>
                            </div>
                        </div>

                        <!-- Network Requests -->
                        <div>
                            <h4 class="text-xs font-semibold text-blue-400 mb-2 flex items-center gap-1">
                                <span>&#127760;</span> Network Requests
                                <span id="obs-network-count" class="text-gray-500">(0)</span>
                            </h4>
                            <div id="obs-network" class="space-y-1 max-h-48 overflow-y-auto">
                                <div class="text-gray-500 text-xs">No network requests</div>
                            </div>
                        </div>

                        <!-- DOM Changes -->
                        <div>
                            <h4 class="text-xs font-semibold text-purple-400 mb-2 flex items-center gap-1">
                                <span>&#128736;</span> DOM Changes
                                <span id="obs-dom-count" class="text-gray-500">(0)</span>
                            </h4>
                            <div id="obs-dom" class="space-y-1 max-h-24 overflow-y-auto">
                                <div class="text-gray-500 text-xs">No DOM changes</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Chat Tab -->
                <div id="panel-chat" class="flex-1 bg-gray-800 rounded-lg flex flex-col hidden">
                    <!-- Chat header with interactive mode indicator -->
                    <div id="chat-header" class="px-4 py-2 border-b border-gray-700 flex items-center justify-between">
                        <div class="flex items-center gap-2">
                            <span id="chat-mode-indicator" class="w-2 h-2 rounded-full bg-gray-500"></span>
                            <span id="chat-mode-text" class="text-sm text-gray-400">Autonomous Mode</span>
                        </div>
                        <span class="text-xs text-gray-500">Enable Interactive Mode to chat</span>
                    </div>

                    <!-- Chat messages -->
                    <div id="chat-messages" class="flex-1 overflow-y-auto p-4 space-y-3">
                        <div class="text-gray-500 text-center text-sm py-4">
                            Enable Interactive Mode to chat with the agent and control the browser directly.
                        </div>
                    </div>

                    <!-- Chat input -->
                    <div class="p-4 border-t border-gray-700">
                        <form id="chat-form" onsubmit="sendChatMessage(event)" class="flex gap-2">
                            <input
                                type="text"
                                id="chat-input"
                                placeholder="Type a goal or command..."
                                class="flex-1 bg-gray-700 text-white rounded px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 focus:outline-none disabled:opacity-50"
                                disabled
                            >
                            <button
                                type="submit"
                                id="chat-send"
                                class="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded text-sm font-medium"
                                disabled
                            >
                                Send
                            </button>
                        </form>
                        <div class="mt-2 text-xs text-gray-500">
                            Examples: "Go to github.com" • "Search for Python tutorials" • "Click the login button"
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </main>

    <!-- Memory Panel Overlay -->
    <div id="memory-overlay" class="memory-overlay" onclick="toggleMemoryPanel()"></div>

    <!-- Memory Panel -->
    <div id="memory-panel" class="memory-panel">
        <div class="memory-panel-header">
            <h3 class="text-lg font-semibold text-pink-400">🧠 Agent Memory</h3>
            <button onclick="toggleMemoryPanel()" class="text-gray-400 hover:text-white text-xl">&times;</button>
        </div>
        <div class="memory-panel-content" id="memory-content">
            <div class="text-gray-500 text-center py-8">Loading memory...</div>
        </div>
    </div>

    <script>
        let ws = null;
        let currentAgentId = 'agent-1';
        let agents = {};

        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

            ws.onopen = () => {
                updateConnectionStatus(true);
                console.log('Connected to Poisonarr');
            };

            ws.onclose = () => {
                updateConnectionStatus(false);
                setTimeout(connect, 3000);
            };

            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };

            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                handleMessage(msg);
            };
        }

        function updateConnectionStatus(connected) {
            const el = document.getElementById('connection-status');
            if (connected) {
                el.innerHTML = `
                    <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
                    <span class="text-sm text-gray-400">Connected</span>
                `;
            } else {
                el.innerHTML = `
                    <span class="w-2 h-2 rounded-full bg-red-500"></span>
                    <span class="text-sm text-gray-400">Disconnected</span>
                `;
            }
        }

        function handleMessage(msg) {
            switch (msg.type) {
                case 'full_state':
                    agents = msg.agents;
                    updateUI();
                    break;
                case 'status_update':
                    if (agents[msg.agent_id]) {
                        agents[msg.agent_id].status = msg.status;
                    }
                    updateStatus(msg.status);
                    break;
                case 'react_stage':
                    if (agents[msg.agent_id]) {
                        agents[msg.agent_id].react_stage = msg.stage;
                    }
                    updateReactStage(msg.stage);
                    break;
                case 'session_update':
                    if (agents[msg.agent_id]) {
                        agents[msg.agent_id].current_session = msg.session;
                        agents[msg.agent_id].session_count = msg.session_count;
                    }
                    updateSession(msg.session, msg.session_count);
                    break;
                case 'step_update':
                    if (agents[msg.agent_id]) {
                        agents[msg.agent_id].current_step = msg.step;
                        agents[msg.agent_id].step_index = msg.step_index;
                        agents[msg.agent_id].total_steps = msg.total_steps;
                    }
                    updateCurrentStep(msg.step_index);
                    break;
                case 'screenshot_update':
                    if (agents[msg.agent_id]) {
                        agents[msg.agent_id].screenshot_b64 = msg.screenshot_b64;
                        agents[msg.agent_id].current_url = msg.current_url;
                    }
                    updateScreenshot(msg.screenshot_b64, msg.current_url);
                    break;
                case 'log':
                    addLog(msg.level, msg.message, msg.timestamp);
                    break;
                case 'stats_update':
                    if (agents[msg.agent_id]) {
                        agents[msg.agent_id].stats = msg.stats;
                    }
                    if (msg.agent_id === currentAgentId) {
                        updateStats(msg.stats);
                    }
                    break;
                case 'pause_update':
                    if (msg.agent_id === currentAgentId) {
                        updatePauseButton(msg.paused);
                    }
                    break;
                case 'observations_update':
                    if (msg.agent_id === currentAgentId && currentTab === 'observations') {
                        renderObservations(msg.observations);
                    }
                    break;
                case 'interactive_mode':
                    if (msg.agent_id === currentAgentId) {
                        updateInteractiveMode(msg.interactive_mode);
                    }
                    break;
                case 'chat_update':
                    if (msg.agent_id === currentAgentId) {
                        updateInteractiveMode(msg.interactive_mode);
                        if (currentTab === 'chat') {
                            renderChatMessages(msg.messages);
                        }
                    }
                    break;
                case 'ping':
                    ws.send(JSON.stringify({type: 'pong'}));
                    break;
            }
        }

        function updateUI() {
            const agent = agents[currentAgentId];
            if (!agent) return;

            updateStatus(agent.status);
            updateReactStage(agent.react_stage || 'idle');
            if (agent.current_session) {
                updateSession(agent.current_session, agent.session_count);
            }
            if (agent.screenshot_b64) {
                updateScreenshot(agent.screenshot_b64, agent.current_url);
            }
            if (agent.logs) {
                const logContainer = document.getElementById('panel-logs');
                logContainer.innerHTML = '';
                agent.logs.forEach(log => {
                    addLog(log.level, log.message, log.timestamp, false);
                });
            }
            if (agent.stats) {
                updateStats(agent.stats);
            }
        }

        function updateStats(stats) {
            document.getElementById('stat-total-tokens').textContent = formatNumber(stats.total_tokens);
            document.getElementById('stat-llm-calls').textContent = stats.llm_calls;
            document.getElementById('stat-avg-tokens').textContent = Math.round(stats.avg_tokens_per_call);
            document.getElementById('stat-context-size').textContent = formatNumber(stats.context_size);
            document.getElementById('stat-actions').textContent = stats.actions_taken;
            document.getElementById('stat-memory').textContent = stats.memory_entries;
            document.getElementById('stat-success').textContent = stats.successful_sessions;
            document.getElementById('stat-failed').textContent = stats.failed_sessions;
        }

        function formatNumber(num) {
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
            return num.toString();
        }

        function updateReactStage(stage) {
            const el = document.getElementById('react-stage');
            const labels = {
                'idle': 'IDLE',
                'observe': '👁 OBSERVE',
                'reason': '🧠 REASON',
                'act': '⚡ ACT'
            };
            el.textContent = labels[stage] || stage.toUpperCase();
            el.className = `px-3 py-1 rounded-full text-sm font-mono react-${stage}`;
            if (stage !== 'idle') {
                el.classList.add('react-active');
            }
        }

        function updateStatus(status) {
            const el = document.getElementById('agent-status');
            el.textContent = status.charAt(0).toUpperCase() + status.slice(1);
            el.className = `px-3 py-1 rounded-full text-sm status-${status}`;

            const container = document.getElementById('screenshot-container');
            if (status === 'browsing') {
                container.classList.add('recording');
            } else {
                container.classList.remove('recording');
            }
        }

        function updateSession(session, count) {
            document.getElementById('no-session').classList.add('hidden');
            document.getElementById('session-content').classList.remove('hidden');

            document.getElementById('session-persona').textContent = session.persona || 'Unknown';
            document.getElementById('session-intent').textContent = session.intent || '';
            document.getElementById('session-mood').textContent = session.mood || 'casual';
            document.getElementById('session-count').textContent = count;

            // Render steps
            const stepsContainer = document.getElementById('steps-container');
            const steps = session.steps || [];
            stepsContainer.innerHTML = steps.map((step, i) => `
                <div class="step p-2 rounded text-sm ${i === 0 ? 'step-active' : ''}" data-step="${i}">
                    <div class="flex items-center gap-2">
                        <span class="text-lg">${getActionEmoji(step.action)}</span>
                        <span class="font-medium">${step.action}</span>
                        <span class="text-gray-400">→</span>
                        <span class="text-gray-300 truncate">${step.target}</span>
                    </div>
                    <div class="text-xs text-gray-500 ml-7">${step.description}</div>
                </div>
            `).join('');
        }

        function updateCurrentStep(index) {
            const steps = document.querySelectorAll('.step');
            steps.forEach((step, i) => {
                step.classList.remove('step-active', 'step-complete');
                if (i < index) {
                    step.classList.add('step-complete');
                } else if (i === index) {
                    step.classList.add('step-active');
                }
            });

            const progressEl = document.getElementById('session-progress');
            const agent = agents[currentAgentId];
            if (agent) {
                progressEl.textContent = `Step ${index + 1}/${agent.total_steps}`;
            }
        }

        function updateScreenshot(b64, url) {
            const img = document.getElementById('screenshot');
            const noScreenshot = document.getElementById('no-screenshot');

            img.src = 'data:image/png;base64,' + b64;
            img.classList.remove('hidden');
            noScreenshot.classList.add('hidden');

            const urlEl = document.getElementById('current-url');
            urlEl.textContent = url || 'Unknown';
            urlEl.href = url || '#';
        }

        // Tab switching
        let currentTab = 'logs';
        let isInteractiveMode = false;

        function switchTab(tab) {
            currentTab = tab;
            const tabLogs = document.getElementById('tab-logs');
            const tabObs = document.getElementById('tab-observations');
            const tabChat = document.getElementById('tab-chat');
            const panelLogs = document.getElementById('panel-logs');
            const panelObs = document.getElementById('panel-observations');
            const panelChat = document.getElementById('panel-chat');

            // Reset all tabs
            [tabLogs, tabObs, tabChat].forEach(t => {
                t.className = 'px-3 py-1 rounded text-sm bg-gray-800 text-gray-400 hover:text-white';
            });
            [panelLogs, panelObs, panelChat].forEach(p => p.classList.add('hidden'));

            // Activate selected tab
            if (tab === 'logs') {
                tabLogs.className = 'px-3 py-1 rounded text-sm bg-gray-700 text-white';
                panelLogs.classList.remove('hidden');
            } else if (tab === 'observations') {
                tabObs.className = 'px-3 py-1 rounded text-sm bg-gray-700 text-white';
                panelObs.classList.remove('hidden');
                loadObservations();
            } else if (tab === 'chat') {
                tabChat.className = 'px-3 py-1 rounded text-sm bg-gray-700 text-white';
                panelChat.classList.remove('hidden');
                loadChatHistory();
            }
        }

        async function loadObservations() {
            try {
                const resp = await fetch(`/api/observations/${currentAgentId}`);
                const data = await resp.json();
                if (data.observations) {
                    renderObservations(data.observations);
                }
            } catch (e) {
                console.error('Failed to load observations:', e);
            }
        }

        function renderObservations(obs) {
            // Console logs
            const consoleEl = document.getElementById('obs-console');
            const consoleCountEl = document.getElementById('obs-console-count');
            if (obs.console_logs && obs.console_logs.length > 0) {
                consoleCountEl.textContent = `(${obs.console_logs.length})`;
                consoleEl.innerHTML = obs.console_logs.slice().reverse().map(log => {
                    const color = {
                        'error': 'text-red-400',
                        'warning': 'text-yellow-400',
                        'info': 'text-blue-400',
                        'log': 'text-gray-300',
                        'debug': 'text-gray-500'
                    }[log.type] || 'text-gray-300';
                    const time = new Date(log.timestamp).toLocaleTimeString('en-US', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'});
                    return `<div class="text-xs ${color}"><span class="text-gray-600">[${time}]</span> <span class="text-gray-500">[${log.type}]</span> ${log.text}</div>`;
                }).join('');
            } else {
                consoleCountEl.textContent = '(0)';
                consoleEl.innerHTML = '<div class="text-gray-500 text-xs">No console logs</div>';
            }

            // Network requests
            const networkEl = document.getElementById('obs-network');
            const networkCountEl = document.getElementById('obs-network-count');
            if (obs.network_requests && obs.network_requests.length > 0) {
                networkCountEl.textContent = `(${obs.network_requests.length})`;
                networkEl.innerHTML = obs.network_requests.slice().reverse().map(req => {
                    const statusColor = !req.status ? 'text-gray-500' :
                        req.status < 300 ? 'text-green-400' :
                        req.status < 400 ? 'text-yellow-400' : 'text-red-400';
                    const time = new Date(req.timestamp).toLocaleTimeString('en-US', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'});
                    const latency = req.response_time_ms ? `${Math.round(req.response_time_ms)}ms` : '-';
                    return `<div class="text-xs flex items-center gap-2">
                        <span class="text-gray-600">[${time}]</span>
                        <span class="${statusColor}">${req.status || '...'}</span>
                        <span class="text-gray-400">${req.method}</span>
                        <span class="text-gray-300 truncate flex-1">${req.url}</span>
                        <span class="text-gray-500">${latency}</span>
                    </div>`;
                }).join('');
            } else {
                networkCountEl.textContent = '(0)';
                networkEl.innerHTML = '<div class="text-gray-500 text-xs">No network requests</div>';
            }

            // DOM changes
            const domEl = document.getElementById('obs-dom');
            const domCountEl = document.getElementById('obs-dom-count');
            if (obs.dom_changes && obs.dom_changes.length > 0) {
                domCountEl.textContent = `(${obs.dom_changes.length})`;
                domEl.innerHTML = obs.dom_changes.slice().reverse().map(change => {
                    const icon = change.type === 'added' ? '+' : change.type === 'removed' ? '-' : '~';
                    const color = change.type === 'added' ? 'text-green-400' : change.type === 'removed' ? 'text-red-400' : 'text-yellow-400';
                    return `<div class="text-xs"><span class="${color}">${icon}</span> <span class="text-gray-300">${change.target}</span> <span class="text-gray-500">${change.details}</span></div>`;
                }).join('');
            } else {
                domCountEl.textContent = '(0)';
                domEl.innerHTML = '<div class="text-gray-500 text-xs">No DOM changes</div>';
            }
        }

        // Auto-refresh observations when on that tab
        setInterval(() => {
            if (currentTab === 'observations') {
                loadObservations();
            }
        }, 3000);

        // Chat functions
        async function toggleInteractiveMode() {
            try {
                const resp = await fetch(`/api/interactive/${currentAgentId}`, {method: 'POST'});
                const data = await resp.json();
                if (data.status === 'ok') {
                    updateInteractiveMode(data.interactive_mode);
                }
            } catch (e) {
                console.error('Toggle interactive mode failed:', e);
            }
        }

        function updateInteractiveMode(enabled) {
            isInteractiveMode = enabled;
            const btn = document.getElementById('btn-interactive');
            const indicator = document.getElementById('chat-mode-indicator');
            const modeText = document.getElementById('chat-mode-text');
            const chatInput = document.getElementById('chat-input');
            const chatSend = document.getElementById('chat-send');

            if (enabled) {
                btn.className = 'px-3 py-1 rounded text-sm bg-emerald-600 hover:bg-emerald-500 text-white';
                btn.innerHTML = '🎮 Interactive Mode ON';
                indicator.className = 'w-2 h-2 rounded-full bg-emerald-500 animate-pulse';
                modeText.textContent = 'Interactive Mode - Autonomous loop paused';
                modeText.className = 'text-sm text-emerald-400';
                chatInput.disabled = false;
                chatSend.disabled = false;
                chatInput.placeholder = 'Type a goal or command...';
            } else {
                btn.className = 'px-3 py-1 rounded text-sm bg-gray-600 hover:bg-gray-500 text-gray-300';
                btn.innerHTML = '🎮 Interactive Mode';
                indicator.className = 'w-2 h-2 rounded-full bg-gray-500';
                modeText.textContent = 'Autonomous Mode';
                modeText.className = 'text-sm text-gray-400';
                chatInput.disabled = true;
                chatSend.disabled = true;
                chatInput.placeholder = 'Enable Interactive Mode to chat...';
            }
        }

        async function loadChatHistory() {
            try {
                const resp = await fetch(`/api/chat/${currentAgentId}`);
                const data = await resp.json();
                if (data.status === 'ok') {
                    updateInteractiveMode(data.interactive_mode);
                    renderChatMessages(data.messages);
                }
            } catch (e) {
                console.error('Failed to load chat history:', e);
            }
        }

        function renderChatMessages(messages) {
            const container = document.getElementById('chat-messages');
            if (!messages || messages.length === 0) {
                container.innerHTML = `
                    <div class="text-gray-500 text-center text-sm py-4">
                        Enable Interactive Mode to chat with the agent and control the browser directly.
                    </div>
                `;
                return;
            }

            container.innerHTML = messages.map(msg => {
                const time = new Date(msg.timestamp).toLocaleTimeString('en-US', {hour12: false, hour: '2-digit', minute: '2-digit'});
                if (msg.role === 'user') {
                    return `
                        <div class="flex justify-end">
                            <div class="bg-blue-600 rounded-lg px-3 py-2 max-w-[80%]">
                                <div class="text-sm text-white">${escapeHtml(msg.content)}</div>
                                <div class="text-xs text-blue-200 mt-1">${time}</div>
                            </div>
                        </div>
                    `;
                } else if (msg.role === 'assistant') {
                    return `
                        <div class="flex justify-start">
                            <div class="bg-gray-700 rounded-lg px-3 py-2 max-w-[80%]">
                                <div class="text-sm text-gray-200">${escapeHtml(msg.content)}</div>
                                <div class="text-xs text-gray-500 mt-1">${time}</div>
                            </div>
                        </div>
                    `;
                } else {
                    // System message
                    return `
                        <div class="text-center">
                            <span class="text-xs text-gray-500 bg-gray-700 px-2 py-1 rounded">${escapeHtml(msg.content)}</span>
                        </div>
                    `;
                }
            }).join('');

            // Scroll to bottom
            container.scrollTop = container.scrollHeight;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function sendChatMessage(event) {
            event.preventDefault();
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message || !isInteractiveMode) return;

            input.value = '';
            input.disabled = true;
            document.getElementById('chat-send').disabled = true;

            try {
                const resp = await fetch(`/api/chat/${currentAgentId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({content: message})
                });
                const data = await resp.json();
                if (data.status !== 'ok') {
                    console.error('Failed to send message:', data.message);
                }
            } catch (e) {
                console.error('Failed to send chat message:', e);
            } finally {
                if (isInteractiveMode) {
                    input.disabled = false;
                    document.getElementById('chat-send').disabled = false;
                    input.focus();
                }
            }
        }

        function addLog(level, message, timestamp, scroll = true) {
            const container = document.getElementById('panel-logs');

            // Remove placeholder if exists
            const placeholder = container.querySelector('.text-gray-500');
            if (placeholder && placeholder.textContent === 'Waiting for activity...') {
                placeholder.remove();
            }

            const time = new Date(timestamp).toLocaleTimeString('en-US', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'});
            const div = document.createElement('div');
            div.className = `log-${level} mb-1 py-0.5`;
            div.innerHTML = `<span class="text-gray-500 text-xs">[${time}]</span> ${message}`;
            container.appendChild(div);

            if (scroll) {
                container.scrollTop = container.scrollHeight;
            }
        }

        function getActionEmoji(action) {
            const emojis = {
                'search': '🔍',
                'visit': '🌐',
                'shop': '🛒',
                'read': '📖',
                'watch': '📺'
            };
            return emojis[action] || '🔗';
        }

        async function restartAgent() {
            try {
                const resp = await fetch(`/api/restart/${currentAgentId}`, {method: 'POST'});
                const data = await resp.json();
                console.log('Restart:', data);
            } catch (e) {
                console.error('Restart failed:', e);
            }
        }

        async function skipSession() {
            try {
                const resp = await fetch(`/api/skip/${currentAgentId}`, {method: 'POST'});
                const data = await resp.json();
                console.log('Skip:', data);
            } catch (e) {
                console.error('Skip failed:', e);
            }
        }

        async function togglePause() {
            try {
                const resp = await fetch(`/api/pause/${currentAgentId}`, {method: 'POST'});
                const data = await resp.json();
                updatePauseButton(data.paused);
            } catch (e) {
                console.error('Pause toggle failed:', e);
            }
        }

        function updatePauseButton(paused) {
            const btn = document.getElementById('btn-pause');
            if (paused) {
                btn.innerHTML = '▶️ Resume';
                btn.className = 'px-3 py-1 bg-green-600 hover:bg-green-500 rounded text-sm flex items-center gap-1';
            } else {
                btn.innerHTML = '⏸️ Pause';
                btn.className = 'px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-sm flex items-center gap-1';
            }
        }

        function toggleExpand() {
            const panel = document.querySelector('main > div:first-child');
            const btn = document.getElementById('btn-expand');
            const isExpanded = panel.classList.toggle('browser-expanded');
            btn.textContent = isExpanded ? '✕' : '⛶';
            btn.title = isExpanded ? 'Close expanded view' : 'Expand browser view';
        }

        // Close expanded view or memory panel with Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                // Close memory panel first if open
                if (memoryPanelOpen) {
                    toggleMemoryPanel();
                    return;
                }
                // Then check browser expanded view
                const panel = document.querySelector('main > div:first-child');
                if (panel.classList.contains('browser-expanded')) {
                    toggleExpand();
                }
            }
        });

        // Load available models
        async function loadModels() {
            try {
                const [modelsResp, currentResp] = await Promise.all([
                    fetch('/api/models'),
                    fetch('/api/current-model')
                ]);
                const modelsData = await modelsResp.json();
                const currentData = await currentResp.json();

                const select = document.getElementById('model-select');
                select.innerHTML = modelsData.models.map(m =>
                    `<option value="${m}" ${m === currentData.model ? 'selected' : ''}>${m}</option>`
                ).join('');

                if (modelsData.models.length === 0) {
                    select.innerHTML = '<option value="">No models found</option>';
                }
            } catch (e) {
                console.error('Failed to load models:', e);
            }
        }

        async function changeModel(model) {
            if (!model) return;
            try {
                const resp = await fetch(`/api/model/${encodeURIComponent(model)}`, {method: 'POST'});
                const data = await resp.json();
                console.log('Model changed:', data);
            } catch (e) {
                console.error('Model change failed:', e);
            }
        }

        // Memory panel functions
        let memoryPanelOpen = false;

        function toggleMemoryPanel() {
            memoryPanelOpen = !memoryPanelOpen;
            const panel = document.getElementById('memory-panel');
            const overlay = document.getElementById('memory-overlay');

            if (memoryPanelOpen) {
                panel.classList.add('open');
                overlay.classList.add('open');
                loadMemory();
            } else {
                panel.classList.remove('open');
                overlay.classList.remove('open');
            }
        }

        async function loadMemory() {
            const content = document.getElementById('memory-content');
            content.innerHTML = '<div class="text-gray-500 text-center py-8">Loading memory...</div>';

            try {
                const resp = await fetch(`/api/memory/${currentAgentId}`);
                const data = await resp.json();

                if (data.error || !data.memory) {
                    content.innerHTML = `<div class="text-gray-500 text-center py-8">${data.error || 'No memory available'}</div>`;
                    return;
                }

                renderMemory(data.memory);
            } catch (e) {
                console.error('Failed to load memory:', e);
                content.innerHTML = '<div class="text-red-400 text-center py-8">Failed to load memory</div>';
            }
        }

        function renderMemory(memory) {
            const content = document.getElementById('memory-content');
            let html = '';

            // Stats section
            html += `
                <div class="memory-section">
                    <h4>Statistics</h4>
                    <div class="grid grid-cols-2 gap-2 text-sm">
                        <div class="bg-gray-700 rounded p-2">
                            <div class="text-gray-400 text-xs">Total Sessions</div>
                            <div class="text-emerald-400 font-bold">${memory.total_sessions}</div>
                        </div>
                        <div class="bg-gray-700 rounded p-2">
                            <div class="text-gray-400 text-xs">Success Rate</div>
                            <div class="text-blue-400 font-bold">${memory.total_sessions > 0 ? Math.round(memory.successful_sessions / memory.total_sessions * 100) : 0}%</div>
                        </div>
                    </div>
                </div>
            `;

            // Favorite sites section
            if (memory.favorite_sites && Object.keys(memory.favorite_sites).length > 0) {
                const sortedSites = Object.entries(memory.favorite_sites)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 10);

                html += `
                    <div class="memory-section">
                        <h4>Favorite Sites</h4>
                        <div class="flex flex-wrap">
                            ${sortedSites.map(([site, count]) =>
                                `<span class="memory-site-tag">${site} <span class="text-emerald-400">(${count})</span></span>`
                            ).join('')}
                        </div>
                    </div>
                `;
            }

            // Recent sessions section
            if (memory.recent_sessions && memory.recent_sessions.length > 0) {
                html += `
                    <div class="memory-section">
                        <h4>Recent Sessions (${memory.recent_sessions.length})</h4>
                        ${memory.recent_sessions.slice().reverse().map(session => `
                            <div class="memory-session ${session.success ? 'success' : 'failed'}">
                                <div class="flex items-center justify-between mb-1">
                                    <span class="text-sm font-medium">${session.persona.slice(0, 40)}</span>
                                    <span class="text-xs text-gray-500">${new Date(session.timestamp).toLocaleString()}</span>
                                </div>
                                <div class="text-sm text-gray-300 mb-2">${session.goal.slice(0, 100)}</div>
                                <div class="text-xs text-gray-400 mb-2">${session.summary.slice(0, 150)}${session.summary.length > 150 ? '...' : ''}</div>
                                <div class="flex items-center gap-2 text-xs">
                                    <span class="${session.success ? 'text-emerald-400' : 'text-red-400'}">${session.success ? '✓ Success' : '✗ Failed'}</span>
                                    <span class="text-gray-500">•</span>
                                    <span class="text-gray-400">${session.actions_taken} actions</span>
                                    ${session.sites_visited.length > 0 ? `<span class="text-gray-500">•</span><span class="text-gray-400">${session.sites_visited.length} sites</span>` : ''}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                `;
            }

            // Historical summary section
            if (memory.historical_summary) {
                html += `
                    <div class="memory-section">
                        <h4>Historical Summary</h4>
                        <div class="bg-gray-700 rounded p-3 text-xs text-gray-300 whitespace-pre-wrap max-h-48 overflow-y-auto">
${memory.historical_summary}
                        </div>
                    </div>
                `;
            }

            // Patterns section
            if (memory.patterns && memory.patterns.length > 0) {
                html += `
                    <div class="memory-section">
                        <h4>Behavioral Patterns</h4>
                        <ul class="text-sm text-gray-300 list-disc list-inside">
                            ${memory.patterns.map(p => `<li>${p}</li>`).join('')}
                        </ul>
                    </div>
                `;
            }

            // Created at
            html += `
                <div class="text-xs text-gray-500 text-center mt-4">
                    Memory created: ${new Date(memory.created_at).toLocaleString()}
                </div>
            `;

            content.innerHTML = html;
        }

        // Start connection and load models
        connect();
        loadModels();

        // Ping to keep connection alive
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: 'ping'}));
            }
        }, 25000);
    </script>
</body>
</html>'''


# Global server instance with thread-safe initialization
import threading
_server: Optional[UIServer] = None
_server_lock = threading.Lock()


def get_server() -> UIServer:
    """Get or create the UI server instance (thread-safe)."""
    global _server
    if _server is None:
        with _server_lock:
            if _server is None:  # Double-check after acquiring lock
                _server = UIServer()
                logger.info("Created UIServer singleton")
    return _server
