"""Prompt loading utilities.

Load prompts from markdown files for better organization and maintainability.
"""

import logging
from pathlib import Path
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# Directory containing prompt files
PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def _load_prompt_file(name: str) -> str:
    """Load a prompt file by name (cached).

    Args:
        name: Prompt file name without .md extension

    Returns:
        Raw prompt content
    """
    path = PROMPTS_DIR / f"{name}.md"

    if not path.exists():
        logger.error(f"Prompt file not found: {path}")
        raise FileNotFoundError(f"Prompt file not found: {name}.md")

    content = path.read_text()

    # Strip markdown header (first line starting with #)
    lines = content.split('\n')
    if lines and lines[0].startswith('#'):
        content = '\n'.join(lines[1:]).strip()

    return content


def load_prompt(name: str, **kwargs) -> str:
    """Load and format a prompt from markdown file.

    Args:
        name: Prompt file name without .md extension
        **kwargs: Variables to substitute in the prompt

    Returns:
        Formatted prompt string

    Example:
        >>> load_prompt("reasoner_summarize", max_length=500)
        "You are a content summarizer..."
    """
    content = _load_prompt_file(name)

    # Format with provided variables
    if kwargs:
        try:
            content = content.format(**kwargs)
        except KeyError as e:
            logger.warning(f"Missing prompt variable: {e}")

    return content


def get_prompt_path(name: str) -> Path:
    """Get the path to a prompt file.

    Args:
        name: Prompt file name without .md extension

    Returns:
        Path to the prompt file
    """
    return PROMPTS_DIR / f"{name}.md"


def list_prompts() -> list[str]:
    """List all available prompt names.

    Returns:
        List of prompt names (without .md extension)
    """
    return [f.stem for f in PROMPTS_DIR.glob("*.md")]


# Pre-load commonly used prompts for faster access
def preload_prompts():
    """Preload all prompts into cache."""
    for name in list_prompts():
        try:
            _load_prompt_file(name)
            logger.debug(f"Preloaded prompt: {name}")
        except Exception as e:
            logger.warning(f"Failed to preload prompt {name}: {e}")
