"""
Base Entity Extractor

LLM-powered Named Entity Recognition with self-annotation.
Uses JSON-LD schemas for MCP tool discovery.
"""

import json
from typing import Any

import structlog

from corpus_core.models.entity import ExtractedEntity

logger = structlog.get_logger()


class BaseEntityExtractor:
    """
    Extract entities from text using LLM with schema-guided prompts.

    Self-annotates entities with JSON-LD schemas and Cypher query templates
    for MCP tool discovery.
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        entity_types: list[dict[str, Any]] | None = None,
        domain: str = "generic",
    ):
        """
        Initialize extractor.

        Args:
            ollama_url: Ollama server URL
            model: LLM model to use
            entity_types: List of entity type definitions for prompts
            domain: Domain name for extracted entities
        """
        self.ollama_url = ollama_url
        self.model = model
        self.domain = domain

        # Default entity types if none provided
        self.entity_types = entity_types or [
            {"name": "PERSON", "description": "A person's name"},
            {"name": "ORGANIZATION", "description": "An organization or company"},
            {"name": "LOCATION", "description": "A geographic location"},
            {"name": "DATE", "description": "A date or time reference"},
            {"name": "MONEY", "description": "A monetary value"},
        ]

        # Build entity type descriptions for prompts
        self._entity_descriptions = self._build_entity_descriptions()

    def _build_entity_descriptions(self) -> str:
        """Build entity type descriptions for LLM prompts."""
        descriptions = []
        for entity_type in self.entity_types:
            name = entity_type.get("name", "Unknown")
            desc = entity_type.get("description", "")
            props = entity_type.get("properties", [])

            if props:
                prop_lines = [f"- {p.get('name', '')}: {p.get('description', '')}" for p in props[:5]]
                descriptions.append(f"""
{name}:
  Description: {desc}
  Key properties:
{chr(10).join(prop_lines)}
""")
            else:
                descriptions.append(f"{name}: {desc}")

        return "\n".join(descriptions)

    def _build_extraction_prompt(self, text: str) -> str:
        """Build the entity extraction prompt."""
        type_names = ", ".join(et.get("name", "") for et in self.entity_types)

        return f"""You are an expert at extracting structured entities from text.

Extract all entities from the following text. For each entity, identify:
1. The entity type (one of: {type_names})
2. Key properties that can be extracted from the text
3. Relationships to other entities mentioned

Entity Type Definitions:
{self._entity_descriptions}

TEXT TO ANALYZE:
{text}

Respond with a JSON array of extracted entities. Each entity should have:
- "type": the entity type
- "properties": object with extracted property values
- "relationships": array of {{"target_type", "target_id", "relationship_type"}}
- "confidence": number 0-1 indicating extraction confidence
- "source_span": the text span this was extracted from

Example response:
[
  {{
    "type": "ORGANIZATION",
    "properties": {{
      "name": "Example Corp",
      "industry": "Technology"
    }},
    "relationships": [
      {{"target_type": "PERSON", "target_id": "John Smith", "relationship_type": "EMPLOYS"}}
    ],
    "confidence": 0.95,
    "source_span": "Example Corp, a technology company led by John Smith"
  }}
]

JSON RESPONSE:"""

    async def extract_from_text(self, text: str) -> list[ExtractedEntity]:
        """
        Extract entities from text using LLM.

        Returns entities annotated with JSON-LD schemas.
        """
        import httpx

        prompt = self._build_extraction_prompt(text)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout=120.0,
            )
            response.raise_for_status()
            result = response.json()

        try:
            raw_entities = json.loads(result.get("response", "[]"))
        except json.JSONDecodeError:
            logger.error("llm_json_parse_error", response=result.get("response", "")[:500])
            return []

        entities = []
        for raw in raw_entities:
            entity = self._annotate_entity(raw)
            if entity:
                entities.append(entity)

        logger.info("entities_extracted", count=len(entities))
        return entities

    def _annotate_entity(self, raw: dict[str, Any]) -> ExtractedEntity | None:
        """
        Annotate raw extracted entity with JSON-LD schema.

        Adds:
        - @type and @context for JSON-LD
        - mcp:tools for query discovery
        - Cypher query templates
        """
        entity_type = raw.get("type")
        if not entity_type:
            return None

        # Find matching entity type definition
        type_def = next(
            (et for et in self.entity_types if et.get("name") == entity_type),
            None
        )

        # Build JSON-LD annotation
        jsonld_schema = {
            "@context": {
                "@vocab": "https://schema.org/",
                "mcp": "https://mcp.anthropic.com/schema/",
                "kg": "https://knowledge-graph.local/",
            },
            "@type": type_def.get("schema_org_type", "Thing") if type_def else "Thing",
            "kg:entityType": entity_type,
            "kg:domain": self.domain,
        }

        # Add MCP tools if defined
        if type_def and "mcp_tools" in type_def:
            jsonld_schema["mcp:tools"] = [
                {
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                    "cypher": tool.get("cypher_template"),
                    "parameters": tool.get("parameters"),
                }
                for tool in type_def["mcp_tools"]
            ]

        return ExtractedEntity(
            entity_type=entity_type,
            properties=raw.get("properties", {}),
            relationships=raw.get("relationships", []),
            confidence=raw.get("confidence", 0.5),
            source_span=raw.get("source_span", ""),
            jsonld_schema=jsonld_schema,
            domain=self.domain,
        )

    def extract_from_text_sync(self, text: str) -> list[ExtractedEntity]:
        """Synchronous wrapper for extract_from_text."""
        import asyncio
        return asyncio.run(self.extract_from_text(text))
