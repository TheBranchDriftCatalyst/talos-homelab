import { useState } from 'react'
import { Settings, Pause, Play, Clock, Activity, Zap } from 'lucide-react'
import type { ScalerStatus } from '../types/api'

interface ScalerBackPanelProps {
  status: ScalerStatus | undefined
  onControl: (action: string, target?: string, data?: string) => void
}

const TTL_OPTIONS = [
  { value: '5m', label: '5 min' },
  { value: '15m', label: '15 min' },
  { value: '30m', label: '30 min' },
  { value: '1h', label: '1 hr' },
  { value: '2h', label: '2 hr' },
  { value: '4h', label: '4 hr' },
]

export function ScalerBackPanel({ status, onControl }: ScalerBackPanelProps) {
  const [selectedTTL, setSelectedTTL] = useState('15m')

  if (!status) {
    return (
      <div className="card h-full">
        <div className="card-header">
          <div className="flex items-center gap-2">
            <Settings className="w-5 h-5 text-[var(--accent-blue)]" />
            <h2 className="text-base font-semibold">Auto-Scale Config</h2>
          </div>
        </div>
        <div className="card-body animate-pulse">
          <div className="h-32 bg-[var(--bg-tertiary)] rounded" />
        </div>
      </div>
    )
  }

  const idleSeconds = parseDuration(status.idle)
  const timeoutSeconds = parseDuration(status.idle_timeout)
  const progress = timeoutSeconds > 0 ? Math.max(0, 100 - (idleSeconds / timeoutSeconds) * 100) : 100

  return (
    <div className="card h-full">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-[var(--accent-blue)]" />
          <h2 className="text-base font-semibold">Auto-Scale Config</h2>
        </div>
        <span className={`badge ${status.paused ? 'badge-warning' : 'badge-success'}`}>
          {status.paused ? '⏸ Paused' : '▶ Active'}
        </span>
      </div>

      <div className="card-body space-y-3">
        {/* Compact Stats */}
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-[var(--bg-tertiary)] rounded-lg p-2 text-center">
            <div className="text-lg font-bold text-[var(--accent-blue)]">{status.requests_total}</div>
            <div className="text-[10px] text-[var(--text-secondary)] flex items-center justify-center gap-1">
              <Activity className="w-2.5 h-2.5" /> Requests
            </div>
          </div>
          <div className="bg-[var(--bg-tertiary)] rounded-lg p-2 text-center">
            <div className="text-lg font-bold text-[var(--accent-yellow)]">{status.cold_starts}</div>
            <div className="text-[10px] text-[var(--text-secondary)] flex items-center justify-center gap-1">
              <Zap className="w-2.5 h-2.5" /> Cold Starts
            </div>
          </div>
          <div className="bg-[var(--bg-tertiary)] rounded-lg p-2 text-center">
            <div className="text-lg font-bold text-[var(--text-secondary)]">{status.idle}</div>
            <div className="text-[10px] text-[var(--text-secondary)] flex items-center justify-center gap-1">
              <Clock className="w-2.5 h-2.5" /> Idle
            </div>
          </div>
        </div>

        {/* TTL Progress */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs">
            <span className="text-[var(--text-secondary)]">TTL: {status.idle_timeout}</span>
            <span className={progress < 25 ? 'text-[var(--accent-red)]' : 'text-[var(--text-secondary)]'}>
              {status.until_shutdown} left
            </span>
          </div>
          <div className="h-1.5 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                progress < 25 ? 'bg-[var(--accent-red)]' : progress < 50 ? 'bg-[var(--accent-yellow)]' : 'bg-[var(--accent-green)]'
              }`}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* TTL Selector */}
        <div className="flex gap-1.5">
          {TTL_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => {
                setSelectedTTL(opt.value)
                onControl('set_ttl', '', opt.value)
              }}
              className={`flex-1 px-2 py-1.5 text-xs rounded transition-all ${
                selectedTTL === opt.value
                  ? 'bg-[var(--accent-blue)] text-white'
                  : 'bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Pause/Resume */}
        <div className="flex gap-2 pt-1">
          <button
            className="btn btn-warning flex-1 text-xs py-1.5"
            onClick={() => onControl('pause')}
            disabled={status.paused}
          >
            <Pause className="w-3.5 h-3.5" />
            Pause
          </button>
          <button
            className="btn btn-success flex-1 text-xs py-1.5"
            onClick={() => onControl('resume')}
            disabled={!status.paused}
          >
            <Play className="w-3.5 h-3.5" />
            Resume
          </button>
        </div>
      </div>
    </div>
  )
}

function parseDuration(s: string): number {
  if (!s) return 0
  let total = 0
  const hours = s.match(/(\d+)h/)
  const minutes = s.match(/(\d+)m/)
  const seconds = s.match(/(\d+)s/)
  if (hours) total += parseInt(hours[1]) * 3600
  if (minutes) total += parseInt(minutes[1]) * 60
  if (seconds) total += parseInt(seconds[1])
  return total
}
