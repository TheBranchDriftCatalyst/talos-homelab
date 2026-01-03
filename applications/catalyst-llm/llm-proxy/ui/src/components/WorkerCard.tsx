import { ExternalLink, Play, Square, HardDrive } from 'lucide-react'
import type { WorkerInfo } from '../types/api'

interface WorkerCardProps {
  worker: WorkerInfo
  icon: string
  subtitle: string
  onControl: (action: string, target?: string, data?: string) => void
  showControls?: boolean
}

export function WorkerCard({ worker, icon, subtitle, onControl, showControls }: WorkerCardProps) {
  const isRunning = worker.state === 'running' && worker.ready
  const isStarting = worker.state === 'starting'
  const isStopping = worker.state === 'stopping'

  return (
    <div className="card">
      <div className="card-header">
        <div className="flex items-center gap-3">
          <div
            className={`w-10 h-10 rounded-lg flex items-center justify-center text-xl ${
              worker.type === 'local'
                ? 'bg-green-500/20'
                : worker.type === 'mac'
                ? 'bg-purple-500/20'
                : 'bg-yellow-500/20'
            }`}
          >
            {icon}
          </div>
          <div>
            <h2 className="text-base font-semibold">{worker.name}</h2>
            <div className="text-xs text-[var(--text-secondary)]">{subtitle}</div>
          </div>
        </div>

        <div className="flex gap-2">
          {worker.ec2 && (
            <>
              <EC2StateBadge state={worker.ec2.state} />
              <OllamaReadyBadge ready={worker.ec2.ollama_ready} />
            </>
          )}
          {!worker.ec2 && <StateBadge state={worker.state} ready={worker.ready} />}
        </div>
      </div>

      <div className="card-body space-y-4">
        {/* Info Rows */}
        <div className="space-y-2">
          <InfoRow label="Endpoint" value={worker.url} />
          <InfoRow label="Models Loaded" value={worker.stats.models_loaded.toString()} />
          {worker.ec2 && (
            <>
              <InfoRow label="Instance ID" value={worker.ec2.instance_id} />
              <div className="flex justify-between items-center text-sm">
                <span className="text-[var(--text-secondary)]">AWS Console</span>
                <a
                  href={worker.ec2.console_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--accent-blue)] hover:underline flex items-center gap-1"
                >
                  Open Console <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            </>
          )}
        </div>

        {/* Models List */}
        <div className="border border-[var(--border-color)] rounded-lg overflow-hidden">
          <div className="bg-[var(--bg-tertiary)] px-3 py-2 text-xs font-medium text-[var(--text-secondary)] uppercase flex items-center gap-2">
            <HardDrive className="w-3 h-3" />
            Models
          </div>
          <div className="max-h-32 overflow-auto">
            {worker.models && worker.models.length > 0 ? (
              <div className="divide-y divide-[var(--border-color)]">
                {worker.models.map((model) => (
                  <div
                    key={model.name}
                    className="px-3 py-2 flex items-center justify-between text-sm"
                  >
                    <span className="font-mono text-xs">{model.name}</span>
                    <span className="text-[var(--text-secondary)] text-xs">{model.size}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="px-3 py-4 text-center text-[var(--text-secondary)] text-sm">
                {isRunning ? 'No models loaded' : 'Worker offline'}
              </div>
            )}
          </div>
        </div>

        {/* Controls */}
        {showControls && (
          <div className="flex gap-2 pt-2">
            <button
              className="btn btn-success flex-1"
              onClick={() => onControl('start', worker.type)}
              disabled={isRunning || isStarting}
            >
              <Play className="w-4 h-4" />
              Start Worker
            </button>
            <button
              className="btn btn-danger flex-1"
              onClick={() => onControl('stop', worker.type)}
              disabled={!isRunning || isStopping}
            >
              <Square className="w-4 h-4" />
              Stop Worker
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center text-sm">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <span className="font-mono text-xs">{value || '--'}</span>
    </div>
  )
}

function StateBadge({ state, ready }: { state: string; ready: boolean }) {
  if (ready) {
    return <span className="badge badge-success">● Running</span>
  }
  if (state === 'starting') {
    return <span className="badge badge-warning">⟳ Starting</span>
  }
  if (state === 'stopping') {
    return <span className="badge badge-warning">⟳ Stopping</span>
  }
  return <span className="badge badge-error">○ Stopped</span>
}

function EC2StateBadge({ state }: { state: string }) {
  const badges: Record<string, { class: string; label: string }> = {
    running: { class: 'badge-success', label: '⚡ Running' },
    stopped: { class: 'badge-error', label: '⚡ Stopped' },
    pending: { class: 'badge-warning', label: '⚡ Pending' },
    stopping: { class: 'badge-warning', label: '⚡ Stopping' },
    'shutting-down': { class: 'badge-warning', label: '⚡ Shutting Down' },
  }

  const badge = badges[state] || { class: 'badge-info', label: `⚡ ${state}` }
  return <span className={`badge ${badge.class}`} title="EC2 Instance">{badge.label}</span>
}

function OllamaReadyBadge({ ready }: { ready: boolean }) {
  return (
    <span className={`badge ${ready ? 'badge-success' : 'badge-error'}`} title="Ollama Service">
      🦙 {ready ? 'Ready' : 'Offline'}
    </span>
  )
}
