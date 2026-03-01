import { Activity, Server, Cloud, Laptop, Wifi, WifiOff, RefreshCw } from 'lucide-react'
import type { StatusUpdate, RoutingMode } from '../types/api'

interface HeaderProps {
  status: StatusUpdate | null
  connected: boolean
  reconnecting: boolean
  onRoutingChange: (mode: RoutingMode) => void
}

export function Header({ status, connected, reconnecting, onRoutingChange }: HeaderProps) {
  const scaler = status?.scaler
  const routingMode = scaler?.routing_mode || 'auto'
  const activeTarget = scaler?.active_target || 'none'
  const hasMac = scaler?.has_mac || false

  return (
    <header className="bg-[var(--bg-secondary)] border-b border-[var(--border-color)] px-6 py-3 flex items-center justify-between shrink-0">
      <div className="flex items-center gap-3">
        <Activity className="w-5 h-5 text-[var(--accent-blue)]" />
        <h1 className="text-lg font-semibold">LLM Control Panel</h1>
      </div>

      <div className="flex items-center gap-6">
        {/* Routing Stats */}
        <div className="flex items-center gap-4 px-4 py-2 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
          <RoutingStat label="Local" value={scaler?.local_routed || 0} color="var(--accent-green)" />
          <div className="w-px h-8 bg-[var(--border-color)]" />
          <RoutingStat label="Remote" value={scaler?.remote_routed || 0} color="var(--accent-yellow)" />
          {hasMac && (
            <>
              <div className="w-px h-8 bg-[var(--border-color)]" />
              <RoutingStat label="Mac" value={scaler?.mac_routed || 0} color="var(--accent-purple)" />
            </>
          )}
          {scaler?.broker_routed !== undefined && scaler.broker_routed > 0 && (
            <>
              <div className="w-px h-8 bg-[var(--border-color)]" />
              <RoutingStat label="Broker" value={scaler.broker_routed} color="var(--accent-orange)" />
            </>
          )}
        </div>

        {/* Routing Mode Dropdown */}
        <RoutingDropdown mode={routingMode} hasMac={hasMac} onChange={onRoutingChange} />

        {/* Active Target */}
        <ActiveTargetBadge target={activeTarget} />

        {/* Connection Status */}
        <ConnectionStatus connected={connected} reconnecting={reconnecting} />
      </div>
    </header>
  )
}

function RoutingStat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex flex-col items-center min-w-[50px]">
      <span className="text-base font-semibold" style={{ color }}>
        {value}
      </span>
      <span className="text-[10px] text-[var(--text-secondary)] uppercase">{label}</span>
    </div>
  )
}

interface RoutingDropdownProps {
  mode: RoutingMode
  hasMac: boolean
  onChange: (mode: RoutingMode) => void
}

function RoutingDropdown({ mode, hasMac, onChange }: RoutingDropdownProps) {
  const options: { value: RoutingMode; label: string; icon: React.ReactNode }[] = [
    { value: 'auto', label: 'Auto', icon: null },
    { value: 'local', label: 'Local', icon: <Server className="w-3 h-3" /> },
    { value: 'remote', label: 'Remote', icon: <Cloud className="w-3 h-3" /> },
    ...(hasMac ? [{ value: 'mac' as RoutingMode, label: 'Mac', icon: <Laptop className="w-3 h-3" /> }] : []),
  ]

  const colors: Record<RoutingMode, string> = {
    auto: 'var(--accent-blue)',
    local: 'var(--accent-green)',
    remote: 'var(--accent-yellow)',
    mac: 'var(--accent-purple)',
  }

  return (
    <div className="relative">
      <select
        value={mode}
        onChange={(e) => onChange(e.target.value as RoutingMode)}
        className="appearance-none bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-md px-3 py-1.5 pr-8 text-xs font-medium cursor-pointer focus:outline-none focus:ring-1 focus:ring-[var(--accent-blue)]"
        style={{ color: colors[mode] }}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <div className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none">
        <svg className="w-3 h-3 text-[var(--text-secondary)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </div>
  )
}

function ActiveTargetBadge({ target }: { target: string }) {
  const config: Record<string, { icon: React.ReactNode; label: string; color: string; dotClass: string }> = {
    local: {
      icon: <Server className="w-3 h-3" />,
      label: 'Local Active',
      color: 'var(--accent-green)',
      dotClass: 'bg-[var(--accent-green)] animate-pulse',
    },
    remote: {
      icon: <Cloud className="w-3 h-3" />,
      label: 'Remote Active',
      color: 'var(--accent-yellow)',
      dotClass: 'bg-[var(--accent-yellow)] animate-pulse',
    },
    mac: {
      icon: <Laptop className="w-3 h-3" />,
      label: 'Mac Active',
      color: 'var(--accent-purple)',
      dotClass: 'bg-[var(--accent-purple)] animate-pulse',
    },
    none: {
      icon: null,
      label: 'No Backend',
      color: 'var(--accent-red)',
      dotClass: 'bg-[var(--accent-red)]',
    },
  }

  const { icon, label, color, dotClass } = config[target] || config.none

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-[var(--bg-tertiary)] rounded-md text-xs">
      <div className={`w-2 h-2 rounded-full ${dotClass}`} />
      {icon}
      <span style={{ color }}>{label}</span>
    </div>
  )
}

function ConnectionStatus({ connected, reconnecting }: { connected: boolean; reconnecting: boolean }) {
  if (reconnecting) {
    return (
      <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
        <RefreshCw className="w-4 h-4 animate-spin text-[var(--accent-yellow)]" />
        <span>Reconnecting...</span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
      {connected ? (
        <>
          <Wifi className="w-4 h-4 text-[var(--accent-green)]" />
          <span>Connected</span>
        </>
      ) : (
        <>
          <WifiOff className="w-4 h-4 text-[var(--accent-red)]" />
          <span>Disconnected</span>
        </>
      )}
    </div>
  )
}
