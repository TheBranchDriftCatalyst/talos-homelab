import { useState } from 'react'
import { Settings, Pause, Play, Clock } from 'lucide-react'
import type { ScalerStatus } from '../types/api'

interface ScalerCardProps {
  status: ScalerStatus | undefined
  onControl: (action: string, target?: string, data?: string) => void
}

const TTL_OPTIONS = [
  { value: '5m', label: '5 minutes' },
  { value: '15m', label: '15 minutes' },
  { value: '30m', label: '30 minutes' },
  { value: '1h', label: '1 hour' },
  { value: '2h', label: '2 hours' },
  { value: '4h', label: '4 hours' },
  { value: '8h', label: '8 hours' },
  { value: '24h', label: '24 hours' },
]

export function ScalerCard({ status, onControl }: ScalerCardProps) {
  const [selectedTTL, setSelectedTTL] = useState('15m')

  if (!status) {
    return (
      <div className="card animate-pulse">
        <div className="card-header">
          <h2 className="text-base font-semibold">⚙️ Scaler Configuration</h2>
        </div>
        <div className="card-body h-48 bg-[var(--bg-tertiary)]" />
      </div>
    )
  }

  // Calculate progress percentage for TTL bar
  const idleSeconds = parseDuration(status.idle)
  const timeoutSeconds = parseDuration(status.idle_timeout)
  const progress = timeoutSeconds > 0 ? Math.max(0, 100 - (idleSeconds / timeoutSeconds) * 100) : 100

  return (
    <div className="card">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-[var(--accent-blue)]" />
          <h2 className="text-base font-semibold">Scaler Configuration</h2>
        </div>
        <span className={`badge ${status.paused ? 'badge-warning' : 'badge-success'}`}>
          {status.paused ? '⏸ Paused' : '▶ Active'}
        </span>
      </div>

      <div className="card-body space-y-4">
        {/* Stats Grid */}
        <div className="grid grid-cols-3 gap-4">
          <Stat label="Total Requests" value={status.requests_total} color="var(--accent-blue)" />
          <Stat label="Cold Starts" value={status.cold_starts} color="var(--accent-yellow)" />
          <Stat label="Idle Time" value={status.idle} color="var(--text-secondary)" />
        </div>

        {/* TTL Info */}
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-[var(--text-secondary)] flex items-center gap-1">
              <Clock className="w-3 h-3" /> Current TTL
            </span>
            <span>{status.idle_timeout}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-[var(--text-secondary)]">Until Shutdown</span>
            <span className={progress < 25 ? 'text-[var(--accent-red)]' : ''}>{status.until_shutdown}</span>
          </div>

          {/* Progress Bar */}
          <div className="h-2 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                progress < 25
                  ? 'bg-[var(--accent-red)]'
                  : progress < 50
                  ? 'bg-[var(--accent-yellow)]'
                  : 'bg-[var(--accent-green)]'
              }`}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* TTL Control */}
        <div className="flex gap-2">
          <select
            value={selectedTTL}
            onChange={(e) => setSelectedTTL(e.target.value)}
            className="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-md px-3 py-2 text-sm"
          >
            {TTL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            className="btn btn-primary"
            onClick={() => onControl('set_ttl', '', selectedTTL)}
          >
            Set TTL
          </button>
        </div>

        {/* Pause/Resume Controls */}
        <div className="flex gap-2 pt-2">
          <button
            className="btn btn-warning flex-1"
            onClick={() => onControl('pause')}
            disabled={status.paused}
          >
            <Pause className="w-4 h-4" />
            Pause Auto-Scale
          </button>
          <button
            className="btn btn-success flex-1"
            onClick={() => onControl('resume')}
            disabled={!status.paused}
          >
            <Play className="w-4 h-4" />
            Resume Auto-Scale
          </button>
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: number | string; color: string }) {
  return (
    <div className="text-center">
      <div className="text-2xl font-bold" style={{ color }}>
        {value}
      </div>
      <div className="text-xs text-[var(--text-secondary)]">{label}</div>
    </div>
  )
}

function parseDuration(s: string): number {
  if (!s) return 0
  // Parse Go duration strings like "5m30s", "1h2m3s"
  let total = 0
  const hours = s.match(/(\d+)h/)
  const minutes = s.match(/(\d+)m/)
  const seconds = s.match(/(\d+)s/)

  if (hours) total += parseInt(hours[1]) * 3600
  if (minutes) total += parseInt(minutes[1]) * 60
  if (seconds) total += parseInt(seconds[1])

  return total
}
