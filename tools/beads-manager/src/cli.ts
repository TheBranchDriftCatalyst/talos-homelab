#!/usr/bin/env node

import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Find .beads directory by searching up from cwd
function findBeadsDir(startDir: string): string | null {
  let currentDir = startDir;

  while (currentDir !== path.dirname(currentDir)) {
    const beadsPath = path.join(currentDir, '.beads');
    if (fs.existsSync(beadsPath) && fs.statSync(beadsPath).isDirectory()) {
      return currentDir;
    }
    currentDir = path.dirname(currentDir);
  }

  return null;
}

// Open browser cross-platform
function openBrowser(url: string) {
  const platform = process.platform;
  let cmd: string;
  let args: string[];

  if (platform === 'darwin') {
    cmd = 'open';
    args = [url];
  } else if (platform === 'win32') {
    cmd = 'cmd';
    args = ['/c', 'start', url];
  } else {
    cmd = 'xdg-open';
    args = [url];
  }

  spawn(cmd, args, { detached: true, stdio: 'ignore' }).unref();
}

async function main() {
  const cwd = process.cwd();
  const port = process.env.PORT || '3333';

  // Find .beads directory
  const workspaceRoot = findBeadsDir(cwd);

  if (!workspaceRoot) {
    console.error('\x1b[31mError:\x1b[0m No .beads directory found in current directory or any parent.');
    console.error('');
    console.error('Make sure you\'re in a project that has beads initialized.');
    console.error('Run \x1b[36mbd init\x1b[0m to initialize beads in the current directory.');
    process.exit(1);
  }

  const beadsDir = path.join(workspaceRoot, '.beads');
  const issuesPath = path.join(beadsDir, 'issues.jsonl');

  if (!fs.existsSync(issuesPath)) {
    console.error('\x1b[31mError:\x1b[0m No issues.jsonl found in .beads directory.');
    console.error('');
    console.error('The beads database appears to be empty or corrupted.');
    process.exit(1);
  }

  console.log('\x1b[36m  _                    _     \x1b[0m');
  console.log('\x1b[36m | |__   ___  __ _  __| |___ \x1b[0m');
  console.log('\x1b[36m | \'_ \\ / _ \\/ _` |/ _` / __|\x1b[0m');
  console.log('\x1b[36m | |_) |  __/ (_| | (_| \\__ \\\x1b[0m');
  console.log('\x1b[36m |_.__/ \\___|\\__,_|\\__,_|___/\x1b[0m');
  console.log('');
  console.log('\x1b[90m  Issue Manager UI\x1b[0m');
  console.log('');
  console.log(`\x1b[90mWorkspace:\x1b[0m ${workspaceRoot}`);
  console.log(`\x1b[90mBeads dir:\x1b[0m ${beadsDir}`);
  console.log('');

  // Set environment variables
  process.env.BEADS_WORKSPACE = workspaceRoot;
  process.env.PORT = port;

  // Dynamically import and start the server
  const serverPath = path.join(__dirname, 'server', 'index.js');

  if (!fs.existsSync(serverPath)) {
    // We're running in development mode, use tsx
    console.log('\x1b[33mDevelopment mode detected, starting with tsx...\x1b[0m');
    console.log('');

    const serverTsPath = path.join(__dirname, 'server', 'index.ts');
    const tsx = spawn('npx', ['tsx', serverTsPath], {
      env: { ...process.env },
      stdio: 'inherit',
      cwd: path.join(__dirname, '..'),
    });

    tsx.on('error', (err) => {
      console.error('Failed to start server:', err);
      process.exit(1);
    });

    // Wait a bit then open browser
    setTimeout(() => {
      const url = `http://localhost:${port}`;
      console.log(`\x1b[32mOpening browser at ${url}\x1b[0m`);
      openBrowser(url);
    }, 2000);

    return;
  }

  // Production mode - import the compiled server
  console.log(`\x1b[32mStarting server on port ${port}...\x1b[0m`);
  console.log('');

  // Import and run the server
  await import(serverPath);

  // Wait for server to start then open browser
  setTimeout(() => {
    const url = `http://localhost:${port}`;
    console.log(`\x1b[32mOpening browser at ${url}\x1b[0m`);
    openBrowser(url);
  }, 1000);
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
