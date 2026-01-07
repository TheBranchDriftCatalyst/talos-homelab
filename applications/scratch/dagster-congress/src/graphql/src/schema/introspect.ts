/**
 * Neo4j Schema Introspection
 *
 * Uses @neo4j/introspector to auto-generate GraphQL types from Neo4j.
 * Augments with custom types for semantic search.
 */

import { toGraphQLTypeDefs } from '@neo4j/introspector';
import { Driver } from 'neo4j-driver';

/**
 * Generate GraphQL schema from Neo4j database
 */
export async function generateSchema(driver: Driver): Promise<string> {
  const session = driver.session({ database: 'neo4j' });

  try {
    // Introspect Neo4j to get base types
    const introspectedTypeDefs = await toGraphQLTypeDefs(
      session.executeRead.bind(session)
    );

    // Add custom types and queries for semantic search
    const customTypeDefs = `
      # Custom scalar for JSON data
      scalar JSON

      # Semantic search result
      type SearchResult {
        entity: Entity!
        score: Float!
      }

      # Generic entity wrapper
      type Entity {
        id: ID!
        entityType: String!
        domain: String!
        properties: JSON!
      }

      # Tool definition for MCP discovery
      type MCPTool {
        name: String!
        description: String!
        cypherTemplate: String!
        parameters: JSON!
        entityType: String!
        domain: String!
      }

      # Extend Query with custom operations
      type Query {
        # Semantic search across all entities
        semanticSearch(
          query: String!
          limit: Int = 10
          entityType: String
          minScore: Float = 0.0
        ): [SearchResult!]!

        # Discover available MCP tools
        discoverTools: [MCPTool!]!

        # Get entity by ID
        getEntity(id: ID!, entityType: String): Entity

        # Custom full-text search
        searchBills(query: String!, limit: Int = 20): [Bill!]!
        searchMembers(query: String!, limit: Int = 20): [Member!]!
      }

      # Extend Subscription for real-time updates
      type Subscription {
        # Subscribe to new entities
        entityAdded(entityType: String, domain: String): Entity!
      }
    `;

    // Combine introspected and custom types
    return `
      ${introspectedTypeDefs}

      ${customTypeDefs}
    `;
  } finally {
    await session.close();
  }
}

/**
 * Custom resolvers for semantic search and MCP tools
 */
export const customResolvers = {
  Query: {
    semanticSearch: async (
      _: unknown,
      args: { query: string; limit: number; entityType?: string; minScore: number },
      context: { driver: Driver }
    ) => {
      // This would call the embedding service and Neo4j vector search
      // For now, return empty array (implement with actual embedding service)
      console.log('Semantic search:', args.query);
      return [];
    },

    discoverTools: async () => {
      // Import tools from ontology (would be loaded at startup)
      // For now, return sample tools
      return [
        {
          name: 'get_bill',
          description: 'Get bill details by number',
          cypherTemplate: 'MATCH (b:Bill {number: $number}) RETURN b',
          parameters: { number: 'string', congress: 'integer' },
          entityType: 'Bill',
          domain: 'congressional',
        },
        {
          name: 'find_sponsors',
          description: 'Find sponsors of a bill',
          cypherTemplate: 'MATCH (m:Member)-[:SPONSORS]->(b:Bill {number: $number}) RETURN m',
          parameters: { number: 'string' },
          entityType: 'Member',
          domain: 'congressional',
        },
      ];
    },

    getEntity: async (
      _: unknown,
      args: { id: string; entityType?: string },
      context: { driver: Driver }
    ) => {
      const session = context.driver.session();
      try {
        const typeFilter = args.entityType ? `:${args.entityType}` : '';
        const result = await session.run(
          `MATCH (n${typeFilter} {id: $id}) RETURN n, labels(n) as labels`,
          { id: args.id }
        );

        if (result.records.length === 0) return null;

        const record = result.records[0];
        const node = record.get('n');
        const labels = record.get('labels') as string[];

        return {
          id: node.properties.id,
          entityType: labels[0],
          domain: node.properties.domain || 'congressional',
          properties: node.properties,
        };
      } finally {
        await session.close();
      }
    },

    searchBills: async (
      _: unknown,
      args: { query: string; limit: number },
      context: { driver: Driver }
    ) => {
      const session = context.driver.session();
      try {
        const result = await session.run(
          `
          CALL db.index.fulltext.queryNodes('bill_title_fulltext', $query)
          YIELD node, score
          RETURN node
          ORDER BY score DESC
          LIMIT $limit
          `,
          { query: args.query, limit: args.limit }
        );

        return result.records.map((record) => record.get('node').properties);
      } finally {
        await session.close();
      }
    },

    searchMembers: async (
      _: unknown,
      args: { query: string; limit: number },
      context: { driver: Driver }
    ) => {
      const session = context.driver.session();
      try {
        const result = await session.run(
          `
          CALL db.index.fulltext.queryNodes('member_name_fulltext', $query)
          YIELD node, score
          RETURN node
          ORDER BY score DESC
          LIMIT $limit
          `,
          { query: args.query, limit: args.limit }
        );

        return result.records.map((record) => record.get('node').properties);
      } finally {
        await session.close();
      }
    },
  },
};

// CLI for generating schema to file
if (import.meta.url === `file://${process.argv[1]}`) {
  import('neo4j-driver').then(async (neo4j) => {
    const driver = neo4j.default.driver(
      process.env.NEO4J_URI || 'bolt://localhost:7687',
      neo4j.default.auth.basic(
        process.env.NEO4J_USER || 'neo4j',
        process.env.NEO4J_PASSWORD || 'neo4j-password'
      )
    );

    try {
      const schema = await generateSchema(driver);
      console.log(schema);
    } finally {
      await driver.close();
    }
  });
}
