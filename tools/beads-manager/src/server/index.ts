import express from 'express';
import cors from 'cors';
import { WebSocketServer, WebSocket } from 'ws';
import { createServer } from 'http';
import { watch } from 'chokidar';
import { exec } from 'child_process';
import path from 'path';
import fs from 'fs';

const app = express();
const PORT = process.env.PORT || 3001;

// Get workspace root (where .beads/ is located)
const WORKSPACE_ROOT = process.env.BEADS_WORKSPACE || process.cwd().replace('/tools/beads-manager', '');
const BEADS_DIR = path.join(WORKSPACE_ROOT, '.beads');
const JSONL_PATH = path.join(BEADS_DIR, 'issues.jsonl');

console.log(`[Server] Workspace root: ${WORKSPACE_ROOT}`);
console.log(`[Server] Beads directory: ${BEADS_DIR}`);

app.use(cors());
app.use(express.json());

// Helper to run bd commands async
function runBdAsync(args: string): Promise<string> {
  return new Promise((resolve, reject) => {
    exec(`bd ${args}`, {
      cwd: WORKSPACE_ROOT,
      encoding: 'utf-8',
      timeout: 30000,
    }, (error, stdout, _stderr) => {
      if (error) {
        console.error(`[bd] Error running: bd ${args}`, error.message);
        reject(error);
      } else {
        resolve(stdout);
      }
    });
  });
}

// Parse JSONL file for issues
function parseIssuesFromJsonl(): any[] {
  try {
    const content = fs.readFileSync(JSONL_PATH, 'utf-8');
    const lines = content.trim().split('\n').filter(Boolean);
    return lines.map((line: string) => JSON.parse(line));
  } catch (error) {
    console.error('[Server] Error reading JSONL:', error);
    return [];
  }
}

// REST API Routes

// List all issues
app.get('/api/issues', (_req, res) => {
  try {
    const issues = parseIssuesFromJsonl();
    res.json(issues);
  } catch (error: any) {
    res.status(500).json({ error: error.message });
  }
});

// Get single issue
app.get('/api/issues/:id', (req, res) => {
  try {
    const issues = parseIssuesFromJsonl();
    const issue = issues.find(i => i.id === req.params.id);
    if (issue) {
      res.json(issue);
    } else {
      res.status(404).json({ error: 'Issue not found' });
    }
  } catch (error: any) {
    res.status(500).json({ error: error.message });
  }
});

// Create issue
app.post('/api/issues', async (req, res) => {
  try {
    const { title, issue_type = 'task', description, priority = 2 } = req.body;

    if (!title) {
      return res.status(400).json({ error: 'Title is required' });
    }

    let args = `create --title="${title.replace(/"/g, '\\"')}" --type=${issue_type} --priority=${priority}`;
    if (description) {
      args += ` --description="${description.replace(/"/g, '\\"')}"`;
    }

    await runBdAsync(args);

    // Return the newly created issue (last in JSONL)
    const issues = parseIssuesFromJsonl();
    const newIssue = issues[issues.length - 1];
    res.json(newIssue);
  } catch (error: any) {
    res.status(500).json({ error: error.message });
  }
});

// Update issue
app.patch('/api/issues/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const changes = req.body;

    // Build update command
    let args = `update ${id}`;

    if (changes.status) args += ` --status=${changes.status}`;
    if (changes.priority !== undefined) args += ` --priority=${changes.priority}`;
    if (changes.title) args += ` --title="${changes.title.replace(/"/g, '\\"')}"`;
    if (changes.description !== undefined) {
      if (changes.description) {
        args += ` --description="${changes.description.replace(/"/g, '\\"')}"`;
      }
    }
    if (changes.assignee !== undefined) {
      if (changes.assignee) {
        args += ` --assignee="${changes.assignee}"`;
      }
    }
    if (changes.design !== undefined) {
      if (changes.design) {
        args += ` --design="${changes.design.replace(/"/g, '\\"')}"`;
      }
    }
    if (changes.acceptance_criteria !== undefined) {
      if (changes.acceptance_criteria) {
        args += ` --acceptance="${changes.acceptance_criteria.replace(/"/g, '\\"')}"`;
      }
    }

    await runBdAsync(args);

    // Return updated issue
    const issues = parseIssuesFromJsonl();
    const updatedIssue = issues.find(i => i.id === id);
    res.json(updatedIssue);
  } catch (error: any) {
    res.status(500).json({ error: error.message });
  }
});

// Close issue
app.post('/api/issues/:id/close', async (req, res) => {
  try {
    const { id } = req.params;
    const { reason } = req.body;

    let args = `close ${id}`;
    if (reason) {
      args += ` --reason="${reason.replace(/"/g, '\\"')}"`;
    }

    await runBdAsync(args);
    res.json({ success: true });
  } catch (error: any) {
    res.status(500).json({ error: error.message });
  }
});

// Reopen issue
app.post('/api/issues/:id/reopen', async (req, res) => {
  try {
    const { id } = req.params;
    await runBdAsync(`reopen ${id}`);
    res.json({ success: true });
  } catch (error: any) {
    res.status(500).json({ error: error.message });
  }
});

// Add dependency
app.post('/api/issues/:id/dependencies', async (req, res) => {
  try {
    const { id } = req.params;
    const { depends_on_id, type = 'blocks' } = req.body;

    if (!depends_on_id) {
      return res.status(400).json({ error: 'depends_on_id is required' });
    }

    await runBdAsync(`dep add ${id} ${depends_on_id} --type=${type}`);
    res.json({ success: true });
  } catch (error: any) {
    res.status(500).json({ error: error.message });
  }
});

// Get stats
app.get('/api/stats', (_req, res) => {
  try {
    const issues = parseIssuesFromJsonl();
    const stats = {
      total: issues.length,
      open: issues.filter(i => i.status === 'open').length,
      in_progress: issues.filter(i => i.status === 'in_progress').length,
      blocked: issues.filter(i => i.status === 'blocked').length,
      closed: issues.filter(i => i.status === 'closed').length,
    };
    res.json(stats);
  } catch (error: any) {
    res.status(500).json({ error: error.message });
  }
});

// Create HTTP server
const server = createServer(app);

// WebSocket server for real-time updates
const wss = new WebSocketServer({ server, path: '/ws' });

const clients = new Set<WebSocket>();

wss.on('connection', (ws) => {
  console.log('[WS] Client connected');
  clients.add(ws);

  ws.on('close', () => {
    console.log('[WS] Client disconnected');
    clients.delete(ws);
  });

  ws.on('error', (error) => {
    console.error('[WS] Error:', error);
    clients.delete(ws);
  });
});

// Broadcast to all connected clients
function broadcast(message: object) {
  const data = JSON.stringify(message);
  clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(data);
    }
  });
}

// Watch JSONL file for changes
const watcher = watch(JSONL_PATH, {
  persistent: true,
  ignoreInitial: true,
});

watcher.on('change', () => {
  console.log('[Watcher] JSONL file changed, broadcasting refresh');
  broadcast({ type: 'refresh' });
});

watcher.on('error', (error) => {
  console.error('[Watcher] Error:', error);
});

// Start server
server.listen(PORT, () => {
  console.log(`[Server] Bridge server running on http://localhost:${PORT}`);
  console.log(`[Server] WebSocket available at ws://localhost:${PORT}/ws`);
  console.log(`[Server] Watching ${JSONL_PATH} for changes`);
});

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('[Server] Shutting down...');
  watcher.close();
  wss.close();
  server.close();
  process.exit(0);
});
