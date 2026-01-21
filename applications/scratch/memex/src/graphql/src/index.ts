/**
 * GraphQL Apollo Server for Congress Knowledge Graph
 *
 * Features:
 * - Auto-generated schema from Neo4j via @neo4j/introspector
 * - Custom resolvers for semantic search
 * - WebSocket subscriptions for real-time updates
 * - Prometheus metrics
 */

import { ApolloServer } from '@apollo/server';
import { expressMiddleware } from '@apollo/server/express4';
import { ApolloServerPluginDrainHttpServer } from '@apollo/server/plugin/drainHttpServer';
import { Neo4jGraphQL } from '@neo4j/graphql';
import neo4j, { Driver } from 'neo4j-driver';
import express from 'express';
import cors from 'cors';
import http from 'http';
import { WebSocketServer } from 'ws';
import { useServer } from 'graphql-ws/lib/use/ws';
import { collectDefaultMetrics, Registry, Counter, Histogram } from 'prom-client';
import { generateSchema } from './schema/introspect.js';

// Configuration
const NEO4J_URI = process.env.NEO4J_URI || 'bolt://localhost:7687';
const NEO4J_USER = process.env.NEO4J_USER || 'neo4j';
const NEO4J_PASSWORD = process.env.NEO4J_PASSWORD || 'neo4j-password';
const PORT = parseInt(process.env.PORT || '4000', 10);

// Metrics
const register = new Registry();
collectDefaultMetrics({ register });

const queryCounter = new Counter({
  name: 'graphql_queries_total',
  help: 'Total GraphQL queries',
  labelNames: ['operation', 'status'],
  registers: [register],
});

const queryLatency = new Histogram({
  name: 'graphql_query_latency_seconds',
  help: 'GraphQL query latency',
  labelNames: ['operation'],
  registers: [register],
});

// Context type
interface Context {
  driver: Driver;
}

async function main() {
  // Create Neo4j driver
  const driver = neo4j.driver(
    NEO4J_URI,
    neo4j.auth.basic(NEO4J_USER, NEO4J_PASSWORD)
  );

  // Verify connection
  try {
    await driver.verifyConnectivity();
    console.log('Connected to Neo4j');
  } catch (error) {
    console.error('Failed to connect to Neo4j:', error);
    process.exit(1);
  }

  // Generate schema from Neo4j
  const typeDefs = await generateSchema(driver);

  // Create Neo4jGraphQL instance
  const neoSchema = new Neo4jGraphQL({
    typeDefs,
    driver,
  });

  // Build executable schema
  const schema = await neoSchema.getSchema();

  // Create Express app and HTTP server
  const app = express();
  const httpServer = http.createServer(app);

  // Create WebSocket server for subscriptions
  const wsServer = new WebSocketServer({
    server: httpServer,
    path: '/graphql',
  });

  const serverCleanup = useServer(
    {
      schema,
      context: async () => ({ driver }),
    },
    wsServer
  );

  // Create Apollo Server
  const server = new ApolloServer<Context>({
    schema,
    plugins: [
      ApolloServerPluginDrainHttpServer({ httpServer }),
      {
        async serverWillStart() {
          return {
            async drainServer() {
              await serverCleanup.dispose();
            },
          };
        },
      },
      // Metrics plugin
      {
        async requestDidStart() {
          const start = Date.now();
          return {
            async willSendResponse(requestContext) {
              const operation = requestContext.operationName || 'unknown';
              const status = requestContext.errors?.length ? 'error' : 'success';
              const duration = (Date.now() - start) / 1000;

              queryCounter.inc({ operation, status });
              queryLatency.observe({ operation }, duration);
            },
          };
        },
      },
    ],
  });

  await server.start();

  // Apply middleware
  app.use(cors());
  app.use(express.json());

  // Health endpoint
  app.get('/health', (_, res) => {
    res.json({ status: 'healthy', uptime: process.uptime() });
  });

  // Metrics endpoint
  app.get('/metrics', async (_, res) => {
    res.set('Content-Type', register.contentType);
    res.end(await register.metrics());
  });

  // GraphQL endpoint
  app.use(
    '/graphql',
    expressMiddleware(server, {
      context: async () => ({ driver }),
    })
  );

  // Start server
  httpServer.listen(PORT, () => {
    console.log(`GraphQL server ready at http://localhost:${PORT}/graphql`);
    console.log(`WebSocket subscriptions at ws://localhost:${PORT}/graphql`);
    console.log(`Metrics at http://localhost:${PORT}/metrics`);
  });

  // Graceful shutdown
  process.on('SIGTERM', async () => {
    console.log('Shutting down...');
    await server.stop();
    await driver.close();
    process.exit(0);
  });
}

main().catch((error) => {
  console.error('Failed to start server:', error);
  process.exit(1);
});
