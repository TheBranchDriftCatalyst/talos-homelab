package main

import (
	"net/http"
)

// UI serves a simple single-page dashboard
func (s *Scaler) UI(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(uiHTML))
}

const uiHTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LLM Scaler Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
      color: #eee;
      min-height: 100vh;
      padding: 20px;
    }
    .container { max-width: 600px; margin: 0 auto; }
    h1 {
      text-align: center;
      margin-bottom: 30px;
      font-size: 1.8em;
      color: #00d9ff;
      text-shadow: 0 0 20px rgba(0, 217, 255, 0.3);
    }
    .card {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 20px;
      backdrop-filter: blur(10px);
    }
    .status-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
    .status-row:last-child { border-bottom: none; }
    .status-label { color: #888; font-size: 0.9em; }
    .status-value { font-weight: 600; font-size: 1.1em; }
    .state-running { color: #00ff88; }
    .state-stopped { color: #ff6b6b; }
    .state-starting { color: #ffd93d; }
    .state-paused { color: #ff9f43; }
    .controls {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    button {
      padding: 14px 20px;
      border: none;
      border-radius: 8px;
      font-size: 1em;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }
    button:hover { transform: translateY(-2px); }
    button:active { transform: translateY(0); }
    button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
    .btn-start { background: linear-gradient(135deg, #00b894, #00cec9); color: white; }
    .btn-stop { background: linear-gradient(135deg, #d63031, #e17055); color: white; }
    .btn-pause { background: linear-gradient(135deg, #fdcb6e, #f39c12); color: #333; }
    .btn-resume { background: linear-gradient(135deg, #0984e3, #74b9ff); color: white; }
    .progress-container {
      margin-top: 15px;
      background: rgba(0, 0, 0, 0.3);
      border-radius: 8px;
      height: 8px;
      overflow: hidden;
    }
    .progress-bar {
      height: 100%;
      background: linear-gradient(90deg, #00d9ff, #00ff88);
      transition: width 0.5s ease;
    }
    .progress-label {
      text-align: center;
      margin-top: 8px;
      font-size: 0.85em;
      color: #888;
    }
    .indicator {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 8px;
      animation: pulse 2s infinite;
    }
    .indicator-running { background: #00ff88; box-shadow: 0 0 10px #00ff88; }
    .indicator-stopped { background: #ff6b6b; }
    .indicator-starting { background: #ffd93d; animation: blink 0.5s infinite; }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.5; }
    }
    @keyframes blink {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.3; }
    }
    .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .stat {
      text-align: center;
      padding: 15px;
      background: rgba(0, 0, 0, 0.2);
      border-radius: 8px;
    }
    .stat-value { font-size: 1.5em; font-weight: 700; color: #00d9ff; }
    .stat-label { font-size: 0.75em; color: #888; margin-top: 5px; }
    .last-update { text-align: center; color: #666; font-size: 0.8em; margin-top: 15px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>LLM Scaler</h1>

    <div class="card">
      <h2 style="margin-bottom: 15px; font-size: 1.1em; color: #00d9ff;">🏠 Local Ollama (talos06)</h2>
      <div class="status-row">
        <span class="status-label">Status</span>
        <span class="status-value" id="local-state">
          <span class="indicator" id="local-indicator"></span>
          <span id="local-state-text">Loading...</span>
        </span>
      </div>
      <div class="status-row">
        <span class="status-label">Endpoint</span>
        <span class="status-value" id="local-url" style="font-size: 0.8em; color: #888;">--</span>
      </div>
    </div>

    <div class="card">
      <h2 style="margin-bottom: 15px; font-size: 1.1em; color: #ff9f43;">☁️ Remote Bigboi (EC2)</h2>
      <div class="status-row">
        <span class="status-label">Status</span>
        <span class="status-value" id="remote-state">
          <span class="indicator" id="remote-indicator"></span>
          <span id="remote-state-text">Loading...</span>
        </span>
      </div>
      <div class="status-row">
        <span class="status-label">Endpoint</span>
        <span class="status-value" id="remote-url" style="font-size: 0.8em; color: #888;">--</span>
      </div>
    </div>

    <div class="card">
      <h2 style="margin-bottom: 15px; font-size: 1.1em; color: #aaa;">⚙️ Scaler Status</h2>
      <div class="status-row">
        <span class="status-label">Mode</span>
        <span class="status-value" id="paused">--</span>
      </div>
      <div class="status-row">
        <span class="status-label">Idle Time</span>
        <span class="status-value" id="idle">--</span>
      </div>
      <div class="progress-container">
        <div class="progress-bar" id="progress"></div>
      </div>
      <div class="progress-label" id="progress-label">Until auto-shutdown: --</div>
    </div>

    <div class="card stats">
      <div class="stat">
        <div class="stat-value" id="requests">0</div>
        <div class="stat-label">Requests</div>
      </div>
      <div class="stat">
        <div class="stat-value" id="blocked">0</div>
        <div class="stat-label">Cold Starts</div>
      </div>
      <div class="stat">
        <div class="stat-value" id="starts">0</div>
        <div class="stat-label">Spin-ups</div>
      </div>
    </div>

    <div class="card">
      <h2 style="margin-bottom: 15px; font-size: 1.1em; color: #aaa;">⏰ TTL Settings</h2>
      <div class="status-row">
        <span class="status-label">Current TTL</span>
        <span class="status-value" id="current-ttl">--</span>
      </div>
      <div style="display: flex; gap: 10px; margin-top: 15px;">
        <select id="ttl-select" style="flex: 1; padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.2); background: rgba(0,0,0,0.3); color: #eee; font-size: 1em;">
          <option value="15m">15 minutes</option>
          <option value="30m">30 minutes</option>
          <option value="1h">1 hour</option>
          <option value="2h">2 hours</option>
          <option value="4h">4 hours</option>
          <option value="8h">8 hours</option>
          <option value="24h">24 hours</option>
        </select>
        <button onclick="setTTL()" style="padding: 12px 20px; border-radius: 8px; border: none; background: linear-gradient(135deg, #6c5ce7, #a29bfe); color: white; font-weight: 600; cursor: pointer;">Set TTL</button>
      </div>
    </div>

    <div class="card controls">
      <button class="btn-start" id="btn-start" onclick="doAction('start')">Start Worker</button>
      <button class="btn-stop" id="btn-stop" onclick="doAction('stop')">Stop Worker</button>
      <button class="btn-pause" id="btn-pause" onclick="doAction('pause')">Pause Scaler</button>
      <button class="btn-resume" id="btn-resume" onclick="doAction('resume')">Resume Scaler</button>
    </div>

    <div class="last-update">Last updated: <span id="updated">--</span></div>
  </div>

  <script>
    async function fetchStatus() {
      try {
        const res = await fetch('/_/status');
        const data = await res.json();

        // Local backend status
        if (data.local) {
          const localState = data.local.state || 'unknown';
          document.getElementById('local-state-text').textContent = localState.charAt(0).toUpperCase() + localState.slice(1);
          document.getElementById('local-state-text').className = 'state-' + localState;
          document.getElementById('local-indicator').className = 'indicator indicator-' + localState;
          document.getElementById('local-url').textContent = data.local.url || '--';
        }

        // Remote backend status
        if (data.remote) {
          const remoteState = data.remote.state || 'unknown';
          let remoteLabel = remoteState.charAt(0).toUpperCase() + remoteState.slice(1);
          if (remoteState === 'not_configured') remoteLabel = 'Not Configured';
          document.getElementById('remote-state-text').textContent = remoteLabel;
          document.getElementById('remote-state-text').className = 'state-' + (remoteState === 'not_configured' ? 'stopped' : remoteState);
          document.getElementById('remote-indicator').className = 'indicator indicator-' + (remoteState === 'not_configured' ? 'stopped' : remoteState);
          document.getElementById('remote-url').textContent = data.remote.url || 'Not configured';
        }

        const paused = data.paused;
        const pausedEl = document.getElementById('paused');
        pausedEl.textContent = paused ? 'PAUSED' : 'Active';
        pausedEl.className = 'status-value ' + (paused ? 'state-paused' : 'state-running');

        document.getElementById('idle').textContent = data.idle || '--';
        document.getElementById('current-ttl').textContent = data.idle_timeout || '--';
        document.getElementById('requests').textContent = data.requests_total || 0;
        document.getElementById('blocked').textContent = data.requests_blocked || 0;
        document.getElementById('starts').textContent = data.cold_starts || 0;

        // Progress bar for idle timeout
        const idleSec = parseTime(data.idle);
        const timeoutSec = parseTime(data.idle_timeout);
        const remaining = timeoutSec - idleSec;
        const pct = Math.max(0, Math.min(100, (remaining / timeoutSec) * 100));

        const localReady = data.local && data.local.ready;
        document.getElementById('progress').style.width = pct + '%';
        document.getElementById('progress-label').textContent =
          localReady ? 'Until auto-shutdown: ' + data.until_shutdown :
          paused ? 'Auto-scaling paused' : 'Worker not running';

        // Update buttons
        const state = data.worker_state || 'unknown';
        document.getElementById('btn-start').disabled = state === 'running' || state === 'starting';
        document.getElementById('btn-stop').disabled = state === 'stopped' || state === 'stopping';
        document.getElementById('btn-pause').disabled = paused;
        document.getElementById('btn-resume').disabled = !paused;

        document.getElementById('updated').textContent = new Date().toLocaleTimeString();
      } catch (e) {
        console.error('Failed to fetch status:', e);
      }
    }

    function parseTime(str) {
      if (!str) return 0;
      const match = str.match(/(-?\d+)([hms])/g);
      if (!match) return 0;
      let seconds = 0;
      for (const m of match) {
        const val = parseInt(m);
        if (m.endsWith('h')) seconds += val * 3600;
        else if (m.endsWith('m')) seconds += val * 60;
        else if (m.endsWith('s')) seconds += val;
      }
      return seconds;
    }

    async function doAction(action) {
      try {
        const res = await fetch('/_/' + action, { method: 'POST' });
        const data = await res.json();
        console.log(action + ':', data);
        setTimeout(fetchStatus, 500);
      } catch (e) {
        console.error('Action failed:', e);
      }
    }

    async function setTTL() {
      const ttl = document.getElementById('ttl-select').value;
      try {
        const res = await fetch('/_/ttl?ttl=' + ttl, { method: 'POST' });
        const data = await res.json();
        console.log('setTTL:', data);
        setTimeout(fetchStatus, 500);
      } catch (e) {
        console.error('Set TTL failed:', e);
      }
    }

    // Initial fetch and periodic refresh
    fetchStatus();
    setInterval(fetchStatus, 3000);
  </script>
</body>
</html>
`
