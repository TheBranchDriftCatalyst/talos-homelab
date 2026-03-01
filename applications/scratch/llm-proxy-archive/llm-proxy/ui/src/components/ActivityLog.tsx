import { useEffect, useRef } from 'react'
import { ScrollText, Trash2 } from 'lucide-react'
import type { LogEntry } from '../types/api'

interface ActivityLogProps {
  logs: LogEntry[]
  onClear: () => void
}

export function ActivityLog({ logs, onClear }: ActivityLogProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new logs
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [logs])

  return (
    <div className="card lg:col-span-2 xl:col-span-1">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <ScrollText className="w-5 h-5 text-[var(--accent-purple)]" />
          <h2 className="text-base font-semibold">Activity Log</h2>
          <span className="text-xs text-[var(--text-secondary)]">({logs.length})</span>
        </div>
        <button
          onClick={onClear}
          className="btn btn-secondary px-2 py-1"
          title="Clear logs"
        >
          <Trash2 className="w-3 h-3" />
        </button>
      </div>

      <div
        ref={containerRef}
        className="h-64 overflow-auto divide-y divide-[var(--border-color)]"
      >
        {logs.length === 0 ? (
          <div className="h-full flex items-center justify-center text-[var(--text-secondary)] text-sm">
            No activity yet
          </div>
        ) : (
          logs.map((log, i) => <LogRow key={i} log={log} />)
        )}
      </div>
    </div>
  )
}

function LogRow({ log }: { log: LogEntry }) {
  const time = new Date(log.timestamp).toLocaleTimeString()

  const levelColors: Record<string, string> = {
    info: 'text-[var(--accent-blue)]',
    warn: 'text-[var(--accent-yellow)]',
    error: 'text-[var(--accent-red)]',
    success: 'text-[var(--accent-green)]',
  }

  const levelIcons: Record<string, string> = {
    info: 'ℹ️',
    warn: '⚠️',
    error: '❌',
    success: '✅',
  }

  return (
    <div className="px-4 py-2 flex items-start gap-3 hover:bg-[var(--bg-tertiary)]">
      <span className="text-xs text-[var(--text-secondary)] font-mono shrink-0">[{time}]</span>
      <span className="shrink-0">{levelIcons[log.level] || 'ℹ️'}</span>
      <span className={`text-sm ${levelColors[log.level] || ''}`}>{log.message}</span>
    </div>
  )
}
