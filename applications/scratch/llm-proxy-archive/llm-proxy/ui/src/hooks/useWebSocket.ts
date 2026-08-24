import { useCallback, useEffect, useRef, useState } from 'react'
import type { ControlMessage, LogEntry, StatusUpdate } from '../types/api'

interface UseWebSocketOptions {
  url?: string
  reconnectInterval?: number
  maxReconnectAttempts?: number
}

interface UseWebSocketReturn {
  status: StatusUpdate | null
  logs: LogEntry[]
  connected: boolean
  reconnecting: boolean
  sendControl: (action: string, target?: string, data?: string) => void
  clearLogs: () => void
}

// In dev mode, connect directly to backend; in prod, use relative path
const getDefaultWsUrl = () => {
  if (import.meta.env.DEV) {
    return 'ws://localhost:8080/_/ws'
  }
  return `ws://${window.location.host}/_/ws`
}

export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketReturn {
  const {
    url = getDefaultWsUrl(),
    reconnectInterval = 3000,
    maxReconnectAttempts = 10,
  } = options

  const [status, setStatus] = useState<StatusUpdate | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [connected, setConnected] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const addLog = useCallback((level: LogEntry['level'], message: string) => {
    setLogs((prev) => {
      const newLog: LogEntry = {
        timestamp: new Date().toISOString(),
        level,
        message,
      }
      const updated = [...prev, newLog]
      // Keep last 100 logs
      return updated.slice(-100)
    })
  }, [])

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        setReconnecting(false)
        reconnectAttemptsRef.current = 0
        addLog('success', 'Connected to control panel')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          if (data.type === 'status') {
            setStatus(data as StatusUpdate)
          } else if (data.type === 'log') {
            addLog(data.level || 'info', data.message)
          } else if (data.type === 'response') {
            addLog(data.status === 'error' ? 'error' : 'info', data.message)
          }
        } catch {
          console.error('Failed to parse WebSocket message')
        }
      }

      ws.onclose = () => {
        setConnected(false)
        wsRef.current = null

        if (reconnectAttemptsRef.current < maxReconnectAttempts) {
          setReconnecting(true)
          reconnectAttemptsRef.current++
          addLog('warn', `Disconnected. Reconnecting (${reconnectAttemptsRef.current}/${maxReconnectAttempts})...`)

          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, reconnectInterval)
        } else {
          addLog('error', 'Max reconnection attempts reached')
        }
      }

      ws.onerror = () => {
        addLog('error', 'WebSocket error')
      }
    } catch (err) {
      console.error('WebSocket connection error:', err)
    }
  }, [url, reconnectInterval, maxReconnectAttempts, addLog])

  const sendControl = useCallback((action: string, target?: string, data?: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      addLog('error', 'Not connected')
      return
    }

    const message: ControlMessage = { action, target, data }
    wsRef.current.send(JSON.stringify(message))
    addLog('info', `Sending: ${action}${target ? ` on ${target}` : ''}`)
  }, [addLog])

  const clearLogs = useCallback(() => {
    setLogs([])
  }, [])

  useEffect(() => {
    connect()

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [connect])

  return {
    status,
    logs,
    connected,
    reconnecting,
    sendControl,
    clearLogs,
  }
}
