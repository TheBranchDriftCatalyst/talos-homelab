import { Settings, MessageCircle, Theater, Bot, Rabbit } from 'lucide-react'

export interface Tab {
  id: string
  label: string
  icon: string
  url?: string
}

interface TabBarProps {
  tabs: Tab[]
  activeTab: string
  onTabChange: (tabId: string) => void
}

const iconMap: Record<string, React.ReactNode> = {
  settings: <Settings className="w-4 h-4" />,
  'message-circle': <MessageCircle className="w-4 h-4" />,
  theater: <Theater className="w-4 h-4" />,
  bot: <Bot className="w-4 h-4" />,
  llama: <span className="text-base">🦙</span>,
}

export function TabBar({ tabs, activeTab, onTabChange }: TabBarProps) {
  return (
    <div className="flex bg-[var(--bg-secondary)] border-b border-[var(--border-color)] px-4 shrink-0">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onTabChange(tab.id)}
          className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-all ${
            activeTab === tab.id
              ? 'border-[var(--accent-blue)] text-[var(--text-primary)]'
              : 'border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-color)]'
          }`}
        >
          {iconMap[tab.icon]}
          {tab.label}
        </button>
      ))}
    </div>
  )
}
