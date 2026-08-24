"""Token counting utilities for accurate context management.

Best practice: Accurate token accounting instead of character estimates.
"""

import logging
from functools import lru_cache
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Try to import tiktoken for accurate OpenAI token counting
try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False
    logger.debug("tiktoken not available, using character-based estimation")


@lru_cache(maxsize=8)
def get_encoder(model: str):
    """Get tiktoken encoder for a model (cached)."""
    if not HAS_TIKTOKEN:
        return None

    try:
        # Try exact model match first
        return tiktoken.encoding_for_model(model)
    except KeyError:
        pass

    # Map common models to their encoding
    model_lower = model.lower()

    if any(x in model_lower for x in ["gpt-4", "gpt4"]):
        return tiktoken.get_encoding("cl100k_base")
    elif any(x in model_lower for x in ["gpt-3.5", "gpt35"]):
        return tiktoken.get_encoding("cl100k_base")
    elif any(x in model_lower for x in ["claude", "anthropic"]):
        # Claude uses similar tokenization to cl100k
        return tiktoken.get_encoding("cl100k_base")
    elif any(x in model_lower for x in ["llama", "qwen", "mistral", "phi"]):
        # Most open models use similar tokenization
        return tiktoken.get_encoding("cl100k_base")

    # Default to cl100k_base (GPT-4 encoding)
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """Count tokens in text for a given model.

    Args:
        text: Text to count tokens for
        model: Model name for tokenization

    Returns:
        Token count (accurate if tiktoken available, estimated otherwise)
    """
    if not text:
        return 0

    encoder = get_encoder(model)
    if encoder:
        try:
            return len(encoder.encode(text))
        except Exception as e:
            logger.debug(f"Tiktoken encoding failed: {e}")

    # Fallback: Character-based estimation
    # Average ~4 characters per token for English text
    # Adjust for code/JSON which tends to be more token-dense
    char_count = len(text)

    # Heuristics for different content types
    if text.startswith('{') or text.startswith('['):
        # JSON is more token-dense
        return int(char_count / 3.5)
    elif '```' in text or 'def ' in text or 'function ' in text:
        # Code is more token-dense
        return int(char_count / 3.5)
    else:
        # Normal text
        return int(char_count / 4)


def count_message_tokens(messages: List[Dict], model: str = "gpt-4") -> int:
    """Count tokens in a list of chat messages.

    Args:
        messages: List of message dicts with 'role' and 'content'
        model: Model name for tokenization

    Returns:
        Total token count including message overhead
    """
    total = 0

    # Message format overhead (varies by model, ~4 tokens per message)
    message_overhead = 4

    for msg in messages:
        content = msg.get("content", "")
        role = msg.get("role", "user")

        # Count content tokens
        total += count_tokens(content, model)

        # Add message structure overhead
        total += message_overhead
        total += count_tokens(role, model)

    # Add response priming overhead
    total += 3

    return total


def estimate_remaining_context(
    messages: List[Dict],
    model: str = "gpt-4",
    max_context: int = 8192,
) -> int:
    """Estimate remaining context window tokens.

    Args:
        messages: Current conversation messages
        model: Model name
        max_context: Model's max context window

    Returns:
        Estimated remaining tokens
    """
    # Known context windows
    context_windows = {
        "gpt-4": 8192,
        "gpt-4-turbo": 128000,
        "gpt-4o": 128000,
        "gpt-3.5-turbo": 16384,
        "claude-3": 200000,
        "claude-2": 100000,
        "llama-3": 8192,
        "qwen2.5:7b": 32768,
        "qwen2.5:32b": 32768,
        "mistral": 32768,
    }

    # Try to find matching context window
    model_lower = model.lower()
    for known_model, window in context_windows.items():
        if known_model in model_lower:
            max_context = window
            break

    used = count_message_tokens(messages, model)
    remaining = max_context - used

    return max(0, remaining)


def truncate_to_token_limit(
    text: str,
    max_tokens: int,
    model: str = "gpt-4",
    suffix: str = "...[truncated]",
) -> str:
    """Truncate text to fit within a token limit.

    Args:
        text: Text to truncate
        max_tokens: Maximum allowed tokens
        model: Model name for tokenization
        suffix: Suffix to add if truncated

    Returns:
        Truncated text
    """
    current_tokens = count_tokens(text, model)

    if current_tokens <= max_tokens:
        return text

    # Binary search for the right length
    suffix_tokens = count_tokens(suffix, model)
    target_tokens = max_tokens - suffix_tokens

    # Start with character-based estimate
    ratio = target_tokens / current_tokens
    estimated_chars = int(len(text) * ratio * 0.9)  # 10% buffer

    truncated = text[:estimated_chars]

    # Refine with actual token count
    while count_tokens(truncated, model) > target_tokens and len(truncated) > 100:
        truncated = truncated[:int(len(truncated) * 0.9)]

    return truncated + suffix


class TokenTracker:
    """Track token usage across sessions for cost estimation."""

    def __init__(self, model: str = "gpt-4"):
        self.model = model
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_calls = 0

    def record_call(
        self,
        prompt: str,
        completion: str,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ):
        """Record an LLM call.

        Args:
            prompt: Input prompt/messages
            completion: Output completion
            prompt_tokens: Actual prompt tokens (if known from API)
            completion_tokens: Actual completion tokens (if known from API)
        """
        if prompt_tokens is not None:
            self.prompt_tokens += prompt_tokens
        else:
            self.prompt_tokens += count_tokens(prompt, self.model)

        if completion_tokens is not None:
            self.completion_tokens += completion_tokens
        else:
            self.completion_tokens += count_tokens(completion, self.model)

        self.total_calls += 1

    def record_messages(
        self,
        messages: List[Dict],
        completion: str,
    ):
        """Record an LLM call with message format."""
        prompt_tokens = count_message_tokens(messages, self.model)
        completion_tokens = count_tokens(completion, self.model)

        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_calls += 1

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.prompt_tokens + self.completion_tokens

    def get_stats(self) -> Dict:
        """Get usage statistics."""
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "total_calls": self.total_calls,
            "avg_tokens_per_call": (
                self.total_tokens / self.total_calls if self.total_calls > 0 else 0
            ),
        }

    def reset(self):
        """Reset counters."""
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_calls = 0
