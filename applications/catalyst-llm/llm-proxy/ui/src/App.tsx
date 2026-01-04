import { useState, useEffect } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { Header } from './components/Header'
import { TabBar, type Tab } from './components/TabBar'
import { ControlPanel } from './components/ControlPanel'
import { IframeTab } from './components/IframeTab'
import type { TabInfo } from './types/api'

// Fallback tabs for dev mode
const fallbackTabs: Tab[] = [
  { id: 'control', label: 'Control Panel', icon: 'settings' },
  { id: 'chat', label: 'Open WebUI', icon: 'message-circle', url: 'http://chat.talos00' },
  { id: 'sillytavern', label: 'SillyTavern', icon: 'theater', url: 'http://sillytavern.talos00' },
  { id: 'lobe', label: 'Lobe Chat', icon: 'bot', url: 'http://lobe.talos00' },
  { id: 'rabbitmq', label: 'RabbitMQ', icon: 'rabbit', url: 'http://rabbitmq.talos00' },
]

export default function App() {
  const [activeTab, setActiveTab] = useState('control')
  const [tabs, setTabs] = useState<Tab[]>(fallbackTabs)
  const { status, logs, connected, reconnecting, sendControl, clearLogs } = useWebSocket()

  // Fetch tabs from API
  useEffect(() => {
    const fetchTabs = async () => {
      try {
        const res = await fetch('/_/tabs')
        if (res.ok) {
          const data: TabInfo[] = await res.json()
          setTabs(data)
        }
      } catch {
        // Keep fallback tabs on error
      }
    }
    fetchTabs()
    // Refresh tabs every 60 seconds
    const interval = setInterval(fetchTabs, 60000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="flex flex-col h-full">
      <Header
        status={status}
        connected={connected}
        reconnecting={reconnecting}
        onRoutingChange={(mode) => sendControl('set_routing', '', mode)}
      />

      <TabBar tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} />

      <div className="flex-1 overflow-hidden">
        {activeTab === 'control' ? (
          <ControlPanel
            status={status}
            logs={logs}
            onControl={sendControl}
            onClearLogs={clearLogs}
          />
        ) : (
          <IframeTab url={tabs.find((t) => t.id === activeTab)?.url || ''} />
        )}
      </div>
    </div>
  )
}
