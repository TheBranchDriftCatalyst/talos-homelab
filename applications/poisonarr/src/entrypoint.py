#!/usr/bin/env python3
"""Entrypoint for Browser Agent.

Supports multiple modes:
- poisonarr: Traffic noise generation
- researcher: Information extraction (coming soon)
- monitor: Page change detection (coming soon)
"""

import asyncio
import logging
import os
import signal
import sys
import threading

import uvicorn

from browser_agent.config import BrowserAgentConfig
from browser_agent.server import get_server
from browser_agent.modes import PoisonarrMode, ResearcherMode, MonitorMode

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("browser_agent")

# Reduce noise from other loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# Enable debug for navigator to see tool calls
logging.getLogger("browser_agent.core.navigator").setLevel(logging.DEBUG)

# Enable prompt debugging if BROWSER_AGENT_PROMPT_DEBUG is set
if os.environ.get("BROWSER_AGENT_PROMPT_DEBUG", "").lower() in ("1", "true", "yes"):
    logging.getLogger("browser_agent.core.navigator.prompts").setLevel(logging.DEBUG)
    logging.getLogger("browser_agent.reasoning.reasoner.prompts").setLevel(logging.DEBUG)
    logger.info("Prompt debugging enabled - will log full prompts and responses")


# Mode registry
MODES = {
    "poisonarr": PoisonarrMode,
    "researcher": ResearcherMode,
    "monitor": MonitorMode,
}


def handle_shutdown(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)


def run_ui_server(port: int = 8080):
    """Run the UI server in a separate thread."""
    server = get_server()
    config = uvicorn.Config(
        server.app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
    )
    uvicorn_server = uvicorn.Server(config)
    uvicorn_server.run()


async def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Load configuration
    logger.info("Loading configuration...")
    config = BrowserAgentConfig.load()

    # Set up LangSmith tracing if enabled
    if config.langsmith.enabled:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        if config.langsmith.api_key:
            os.environ["LANGCHAIN_API_KEY"] = config.langsmith.api_key
        if config.langsmith.project:
            os.environ["LANGCHAIN_PROJECT"] = config.langsmith.project
        if config.langsmith.endpoint:
            os.environ["LANGCHAIN_ENDPOINT"] = config.langsmith.endpoint
        logger.info(f"LangSmith tracing enabled for project: {config.langsmith.project}")

    # Get mode from config or environment
    mode_name = os.environ.get("AGENT_MODE", config.mode).lower()
    if mode_name not in MODES:
        logger.error(f"Unknown mode: {mode_name}. Available: {list(MODES.keys())}")
        sys.exit(1)

    logger.info(f"Starting in {mode_name} mode")

    # Get UI server port from env
    ui_port = int(os.environ.get("UI_PORT", "8080"))

    # Create UI server FIRST (before thread) to avoid race condition
    ui_server = get_server()
    logger.info("UI server singleton created")

    # Start UI server in background thread
    logger.info(f"Starting UI server on port {ui_port}...")
    ui_thread = threading.Thread(target=run_ui_server, args=(ui_port,), daemon=True)
    ui_thread.start()
    logger.info(f"UI available at: http://localhost:{ui_port}")

    # Create mode instance
    ModeClass = MODES[mode_name]
    agent = ModeClass(config, ui_server=ui_server, agent_id="agent-1")

    # Set up memory callback for UI
    if hasattr(agent, 'get_memory_data'):
        ui_server.set_memory_callback(lambda agent_id: agent.get_memory_data())

    # Set up observations callback for UI
    if hasattr(agent, 'get_observations_data'):
        ui_server.set_observations_callback(lambda agent_id: agent.get_observations_data())

    # Set LiteLLM URL for model dropdown
    ui_server.set_litellm_url(config.litellm_url)

    # Run the agent
    await agent.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
