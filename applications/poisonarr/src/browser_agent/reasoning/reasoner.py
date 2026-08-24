"""Reasoner - Large/smart model for content understanding and extraction.

Uses a powerful model (32B+) to:
- Understand page content deeply
- Extract structured data
- Answer questions about content
- Make decisions requiring reasoning

This is the "brain" of the browser agent - slow, thoughtful, analytical.
"""

import json
import logging
import re
from typing import Optional, List, Dict, Any, TYPE_CHECKING

try:
    from langchain_ollama import ChatOllama
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

from ..prompts import load_prompt

if TYPE_CHECKING:
    from ..server import UIServer

logger = logging.getLogger(__name__)
prompt_logger = logging.getLogger(f"{__name__}.prompts")


def extract_json_robust(text: str) -> Optional[Any]:
    """Robustly extract JSON from LLM response.

    Best practice: Handle various LLM output formats:
    - JSON in markdown code blocks
    - JSON with leading/trailing text
    - Nested JSON objects
    - Arrays
    """
    if not text:
        return None

    # Clean the text
    text = text.strip()

    # Try 1: Direct parse (if response is pure JSON)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try 2: Extract from markdown code blocks
    code_block_patterns = [
        r'```json\s*([\s\S]*?)\s*```',
        r'```\s*([\s\S]*?)\s*```',
    ]
    for pattern in code_block_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

    # Try 3: Find JSON object with brace matching (handles nested)
    def find_json_object(s: str, start_char: str = '{', end_char: str = '}') -> Optional[str]:
        start = s.find(start_char)
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape_next = False

        for i, char in enumerate(s[start:], start):
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == start_char:
                depth += 1
            elif char == end_char:
                depth -= 1
                if depth == 0:
                    return s[start:i+1]
        return None

    # Try object
    json_str = find_json_object(text, '{', '}')
    if json_str:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Try array
    json_str = find_json_object(text, '[', ']')
    if json_str:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Try 4: Line-by-line for simple key-value extraction
    # This handles malformed JSON with missing quotes, etc.
    lines = text.split('\n')
    result = {}
    for line in lines:
        if ':' in line:
            parts = line.split(':', 1)
            if len(parts) == 2:
                key = parts[0].strip().strip('"\'{}[]')
                value = parts[1].strip().strip(',').strip('"\'')
                if key and value:
                    # Try to parse value as JSON primitive
                    try:
                        result[key] = json.loads(value)
                    except json.JSONDecodeError:
                        result[key] = value
    if result:
        return result

    return None


class Reasoner:
    """Content reasoning agent using a large/smart model.

    Handles:
    - Content extraction and summarization
    - Question answering about page content
    - Decision making requiring deep understanding
    - Structured data extraction
    """

    def __init__(
        self,
        model: str = "qwen2.5:32b",
        base_url: str = "http://localhost:11434",
        ui_server: Optional["UIServer"] = None,
        agent_id: str = "agent-1",
    ):
        self.model = model
        self.base_url = base_url
        self.ui_server = ui_server
        self.agent_id = agent_id

        self.llm = self._create_llm(model)

    def _create_llm(self, model: str):
        """Create LLM client."""
        model_name = model.split("/")[-1] if "/" in model else model
        logger.info(f"Reasoner LLM: ChatOllama ({model_name}) with 32K context")
        return ChatOllama(
            model=model_name,
            temperature=0.3,  # Slightly higher for reasoning variety
            num_predict=2000,  # More tokens for detailed responses
            num_ctx=32000,     # 32K context window for large page content
        )

    def update_model(self, model: str):
        """Update the model used by this reasoner."""
        if model != self.model:
            logger.info(f"Updating Reasoner model: {self.model} -> {model}")
            self.model = model
            self.llm = self._create_llm(model)

    async def _log_ui(self, level: str, message: str):
        """Log to UI if available."""
        if self.ui_server:
            await self.ui_server.add_log(self.agent_id, level, f"[REASON] {message}")

    def _invoke_sync(self, messages: List[dict]) -> str:
        """Synchronous LLM invocation."""
        response = self.llm.invoke(messages)
        return response.content if hasattr(response, 'content') else str(response)

    async def _invoke(self, messages: List[dict]) -> str:
        """Async LLM invocation."""
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._invoke_sync(messages)
        )

    async def summarize(self, content: str, max_length: int = 500) -> str:
        """Summarize page content.

        Args:
            content: Raw page text content
            max_length: Maximum summary length

        Returns:
            Summarized content
        """
        await self._log_ui("info", "Summarizing content...")

        messages = [
            {
                "role": "system",
                "content": load_prompt("reasoner_summarize", max_length=max_length)
            },
            {
                "role": "user",
                "content": f"Summarize this content:\n\n{content[:8000]}"
            }
        ]

        summary = await self._invoke(messages)
        await self._log_ui("info", f"Summary: {summary[:100]}...")
        return summary

    async def extract(
        self,
        content: str,
        schema: Dict[str, Any],
        instructions: str = "",
    ) -> Dict[str, Any]:
        """Extract structured data from content.

        Args:
            content: Raw page text content
            schema: Expected output schema (e.g., {"title": str, "price": float})
            instructions: Additional extraction instructions

        Returns:
            Extracted data matching schema
        """
        await self._log_ui("info", "Extracting structured data...")

        schema_desc = json.dumps(schema, indent=2)

        messages = [
            {
                "role": "system",
                "content": load_prompt("reasoner_extract", schema=schema_desc, instructions=instructions)
            },
            {
                "role": "user",
                "content": f"Extract data from this content:\n\n{content[:8000]}"
            }
        ]

        response = await self._invoke(messages)

        # Parse JSON from response using robust extraction
        data = extract_json_robust(response)
        if data and isinstance(data, dict):
            await self._log_ui("info", f"Extracted: {str(data)[:100]}...")
            return data

        await self._log_ui("warning", "Failed to extract structured data")
        return {}

    async def answer(self, content: str, question: str) -> str:
        """Answer a question about content.

        Args:
            content: Raw page text content
            question: Question to answer

        Returns:
            Answer to the question
        """
        await self._log_ui("info", f"Answering: {question[:50]}...")

        messages = [
            {
                "role": "system",
                "content": load_prompt("reasoner_answer")
            },
            {
                "role": "user",
                "content": f"Content:\n{content[:8000]}\n\nQuestion: {question}"
            }
        ]

        answer = await self._invoke(messages)
        await self._log_ui("info", f"Answer: {answer[:100]}...")
        return answer

    async def decide(
        self,
        content: str,
        decision: str,
        options: List[str],
    ) -> str:
        """Make a decision based on content.

        Args:
            content: Context for the decision
            decision: What decision needs to be made
            options: Available options to choose from

        Returns:
            Chosen option
        """
        await self._log_ui("info", f"Deciding: {decision[:50]}...")

        options_str = "\n".join(f"- {opt}" for opt in options)

        messages = [
            {
                "role": "system",
                "content": load_prompt("reasoner_decide", options=options_str)
            },
            {
                "role": "user",
                "content": f"Context:\n{content[:6000]}\n\nDecision needed: {decision}"
            }
        ]

        choice = await self._invoke(messages)
        choice = choice.strip()

        # Validate choice is one of the options
        for opt in options:
            if opt.lower() in choice.lower() or choice.lower() in opt.lower():
                await self._log_ui("info", f"Decision: {opt}")
                return opt

        # Default to first option if no match
        await self._log_ui("warning", f"Invalid choice '{choice}', defaulting to first option")
        return options[0]

    async def analyze_page(
        self,
        content: str,
        url: str,
        goal: str,
    ) -> Dict[str, Any]:
        """Analyze a page in context of a research goal.

        Args:
            content: Page text content
            url: Page URL
            goal: Research goal

        Returns:
            Analysis with relevance, key_points, next_steps
        """
        await self._log_ui("info", f"Analyzing page for: {goal[:50]}...")

        messages = [
            {
                "role": "system",
                "content": load_prompt("reasoner_analyze")
            },
            {
                "role": "user",
                "content": f"Goal: {goal}\n\nURL: {url}\n\nContent:\n{content[:8000]}"
            }
        ]

        response = await self._invoke(messages)

        # Use robust JSON extraction
        analysis = extract_json_robust(response)
        if analysis and isinstance(analysis, dict):
            await self._log_ui("info", f"Relevance: {analysis.get('relevance', '?')}%")
            return analysis

        logger.warning(f"Failed to parse analysis from: {response[:200]}")
        return {
            "relevance": 0,
            "key_points": [],
            "data_found": {},
            "next_steps": [],
            "summary": "Failed to analyze page"
        }

    async def generate_search_queries(
        self,
        goal: str,
        context: str = "",
        count: int = 3,
    ) -> List[str]:
        """Generate search queries to achieve a research goal.

        Args:
            goal: Research goal
            context: Additional context (e.g., previous findings)
            count: Number of queries to generate

        Returns:
            List of search queries
        """
        await self._log_ui("info", f"Generating search queries for: {goal[:50]}...")

        messages = [
            {
                "role": "system",
                "content": load_prompt("reasoner_queries", count=count)
            },
            {
                "role": "user",
                "content": f"Goal: {goal}\n\nContext: {context}" if context else f"Goal: {goal}"
            }
        ]

        response = await self._invoke(messages)

        # Use robust JSON extraction
        queries = extract_json_robust(response)
        if queries and isinstance(queries, list):
            # Filter to strings only
            queries = [q for q in queries if isinstance(q, str)]
            await self._log_ui("info", f"Generated {len(queries)} queries")
            return queries[:count]

        # Fallback: split response by newlines
        queries = [q.strip().strip('"').strip("'") for q in response.split('\n') if q.strip()]
        return queries[:count]
