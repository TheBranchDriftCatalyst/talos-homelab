import { useEffect, useRef, useCallback } from 'react';
import type { WebSocketMessage } from '../lib/types';

interface UseWebSocketOptions {
  onMessage?: (message: WebSocketMessage) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  reconnectInterval?: number;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const {
    onMessage,
    onConnect,
    onDisconnect,
    reconnectInterval = 3000,
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    // Determine WebSocket URL based on current location
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('[WS] Connected');
        onConnect?.();
      };

      ws.onclose = () => {
        console.log('[WS] Disconnected');
        onDisconnect?.();

        // Attempt to reconnect
        reconnectTimeoutRef.current = window.setTimeout(() => {
          console.log('[WS] Reconnecting...');
          connect();
        }, reconnectInterval);
      };

      ws.onerror = (error) => {
        console.error('[WS] Error:', error);
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          onMessage?.(message);
        } catch (err) {
          console.error('[WS] Failed to parse message:', err);
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('[WS] Failed to connect:', err);

      // Retry connection
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect();
      }, reconnectInterval);
    }
  }, [onMessage, onConnect, onDisconnect, reconnectInterval]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const send = useCallback((message: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  useEffect(() => {
    connect();

    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return { send, disconnect, reconnect: connect };
}
