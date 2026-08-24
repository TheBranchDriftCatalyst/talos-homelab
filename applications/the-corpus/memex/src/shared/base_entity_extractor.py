"""
Base Entity Extractor

LLM-powered Named Entity Recognition with self-annotation.
Uses JSON-LD schemas for MCP tool discovery.
"""

import json
from typing import Any

import structlog

from shared.models.entity import ExtractedEntity
from schema.ontology import NodeType, get_all_node_types

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
        node_types: list[NodeType] | None = None,
    ):
        self.ollama_url = ollama_url
        self.model = model
        self.node_types = node_types or get_all_node_types()

        # Build entity type descriptions for prompts
        self._entity_descriptions = self._build_entity_descriptions()

    def _build_entity_descriptions(self) -> str:
        """Build entity type descriptions for LLM prompts."""
        descriptions = []
        for node_type in self.node_types:
            props = [f"- {p.name}: {p.description}" for p in node_type.properties[:5]]
            desc = f"""
{node_type.name}:
  Description: {node_type.description}
  Key properties:
{chr(10).join(props)}
"""
            descriptions.append(desc)
        return "\n".join(descriptions)

    def _build_extraction_prompt(self, text: str) -> str:
        """Build the entity extraction prompt."""
        return f"""You are an expert at extracting structured entities from text about US Congress.

Extract all entities from the following text. For each entity, identify:
1. The entity type (one of: {', '.join(nt.name for nt in self.node_types)})
2. Key properties that can be extracted from the text
3. Relationships to other entities mentioned

Entity Type Definitions:
{self._entity_descriptions}

TEXT TO ANALYZE:
{text}

Respond with a JSON array of extracted entities. Each entity should have:
- "type": the entity type
- "properties": object with extracted property values
- "relationships": array of {{target_type, target_id, relationship_type}}
- "confidence": number 0-1 indicating extraction confidence
- "source_span": the text span this was extracted from

Example response:
[
  {{
    "type": "Bill",
    "properties": {{
      "number": "H.R.1234",
      "title": "Example Bill Title",
      "congress": 118
    }},
    "relationships": [
      {{"target_type": "Member", "target_id": "Smith", "relationship_type": "SPONSORS"}}
    ],
    "confidence": 0.95,
    "source_span": "H.R.1234, the Example Bill Title, sponsored by Rep. Smith"
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

        # Find matching node type
        node_type = next(
            (nt for nt in self.node_types if nt.name == entity_type),
            None
        )
        if not node_type:
            logger.warning("unknown_entity_type", type=entity_type)
            return None

        # Build JSON-LD annotation
        jsonld_schema = {
            "@context": {
                "@vocab": "https://schema.org/",
                "mcp": "https://mcp.anthropic.com/schema/",
                "kg": "https://knowledge-graph.local/",
            },
            "@type": node_type.schema_org_type or "Thing",
            "kg:entityType": node_type.name,
            "kg:domain": node_type.domain,
            # MCP tools for this entity type
            "mcp:tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "cypher": tool.cypher_template,
                    "parameters": tool.parameters,
                }
                for tool in node_type.mcp_tools
            ],
        }

        return ExtractedEntity(
            entity_type=entity_type,
            properties=raw.get("properties", {}),
            relationships=raw.get("relationships", []),
            confidence=raw.get("confidence", 0.5),
            source_span=raw.get("source_span", ""),
            jsonld_schema=jsonld_schema,
            domain=node_type.domain,
        )

    def extract_from_text_sync(self, text: str) -> list[ExtractedEntity]:
        """Synchronous wrapper for extract_from_text."""
        import asyncio
        return asyncio.run(self.extract_from_text(text))
