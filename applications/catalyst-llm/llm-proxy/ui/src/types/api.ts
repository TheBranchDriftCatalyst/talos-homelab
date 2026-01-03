// WebSocket API Types - matches Go structs in websocket.go

export interface StatusUpdate {
  type: 'status' | 'log' | 'error' | 'response'
  timestamp: string
  scaler: ScalerStatus
  workers: WorkerInfo[]
  broker: BrokerStatus
}

export interface ScalerStatus {
  paused: boolean
  idle_timeout: string
  idle: string
  until_shutdown: string
  requests_total: number
  cold_starts: number
  routing_mode: RoutingMode
  active_target: 'local' | 'remote' | 'mac' | 'none'
  local_routed: number
  remote_routed: number
  mac_routed: number
  broker_routed: number
  has_mac: boolean
}

export type RoutingMode = 'auto' | 'local' | 'remote' | 'mac'

export interface WorkerInfo {
  name: string
  type: 'local' | 'remote' | 'mac'
  url: string
  state: 'running' | 'stopped' | 'starting' | 'stopping'
  ready: boolean
  models?: ModelInfo[]
  stats: WorkerStats
  ec2?: EC2Info
  last_check: string
}

export interface ModelInfo {
  name: string
  size: string
  modified_at: string
}

export interface WorkerStats {
  uptime?: string
  requests_total: number
  models_loaded: number
}

export interface EC2Info {
  instance_id: string
  instance_type: string
  region: string
  console_url: string
  state: string
  ollama_ready: boolean
  public_ip?: string
  launch_time?: string
}

export interface BrokerStatus {
  connected: boolean
  enabled: boolean
  queues?: QueueInfo[]
  exchanges?: string[]
  reply_queue?: string
}

export interface QueueInfo {
  name: string
  messages: number
  consumers: number
  routing_key: string
  messages_ready: number
  messages_unacked: number
}

export interface ControlMessage {
  action: string
  target?: string
  data?: string
}

export interface LogEntry {
  timestamp: string
  level: 'info' | 'warn' | 'error' | 'success'
  message: string
}
