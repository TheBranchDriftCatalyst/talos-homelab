import { Rabbit, Layers, MessageSquare, Users, Inbox, Send } from 'lucide-react'
import type { BrokerStatus, QueueInfo } from '../types/api'

interface BrokerCardProps {
  broker: BrokerStatus
}

export function BrokerCard({ broker }: BrokerCardProps) {
  return (
    <div className="card">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <Rabbit className="w-5 h-5 text-[var(--accent-orange)]" />
          <h2 className="text-base font-semibold">RabbitMQ Broker</h2>
        </div>
        <span className={`badge ${broker.connected ? 'badge-success' : 'badge-error'}`}>
          {broker.connected ? '● Connected' : '○ Disconnected'}
        </span>
      </div>

      <div className="card-body space-y-4">
        {/* Connection Info */}
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-[var(--bg-tertiary)] rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-[var(--accent-orange)]">
              {broker.queues?.length || 0}
            </div>
            <div className="text-xs text-[var(--text-secondary)] flex items-center justify-center gap-1">
              <Inbox className="w-3 h-3" /> Queues
            </div>
          </div>
          <div className="bg-[var(--bg-tertiary)] rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-[var(--accent-blue)]">
              {broker.exchanges?.length || 0}
            </div>
            <div className="text-xs text-[var(--text-secondary)] flex items-center justify-center gap-1">
              <Layers className="w-3 h-3" /> Exchanges
            </div>
          </div>
        </div>

        {/* Exchanges List */}
        {broker.exchanges && broker.exchanges.length > 0 && (
          <div className="border border-[var(--border-color)] rounded-lg overflow-hidden">
            <div className="bg-[var(--bg-tertiary)] px-3 py-2 text-xs font-medium text-[var(--text-secondary)] uppercase flex items-center gap-2">
              <Layers className="w-3 h-3" />
              Exchanges
            </div>
            <div className="divide-y divide-[var(--border-color)]">
              {broker.exchanges.map((exchange) => (
                <div key={exchange} className="px-3 py-2 flex items-center gap-2">
                  <Send className="w-3 h-3 text-[var(--accent-blue)]" />
                  <span className="font-mono text-xs">{exchange}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Queues List */}
        {broker.queues && broker.queues.length > 0 && (
          <div className="border border-[var(--border-color)] rounded-lg overflow-hidden">
            <div className="bg-[var(--bg-tertiary)] px-3 py-2 text-xs font-medium text-[var(--text-secondary)] uppercase flex items-center gap-2">
              <Inbox className="w-3 h-3" />
              Queues
            </div>
            <div className="max-h-48 overflow-auto">
              <table className="w-full text-sm">
                <thead className="bg-[var(--bg-tertiary)] sticky top-0">
                  <tr className="text-left text-xs text-[var(--text-secondary)]">
                    <th className="px-3 py-2">Queue</th>
                    <th className="px-3 py-2 text-center" title="Messages">
                      <MessageSquare className="w-3 h-3 inline" />
                    </th>
                    <th className="px-3 py-2 text-center" title="Consumers">
                      <Users className="w-3 h-3 inline" />
                    </th>
                    <th className="px-3 py-2 text-center">Ready</th>
                    <th className="px-3 py-2 text-center">Unacked</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-color)]">
                  {broker.queues.map((queue) => (
                    <QueueRow key={queue.name} queue={queue} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Reply Queue */}
        {broker.reply_queue && (
          <div className="text-xs text-[var(--text-secondary)]">
            <span className="font-medium">Reply Queue:</span>{' '}
            <span className="font-mono">{broker.reply_queue}</span>
          </div>
        )}
      </div>
    </div>
  )
}

function QueueRow({ queue }: { queue: QueueInfo }) {
  const hasMessages = queue.messages > 0
  const hasUnacked = queue.messages_unacked > 0

  return (
    <tr className="hover:bg-[var(--bg-tertiary)]">
      <td className="px-3 py-2">
        <div className="flex flex-col">
          <span className="font-mono text-xs truncate max-w-[150px]" title={queue.name}>
            {queue.name}
          </span>
          {queue.routing_key && (
            <span className="text-[10px] text-[var(--text-secondary)]">
              key: {queue.routing_key}
            </span>
          )}
        </div>
      </td>
      <td className="px-3 py-2 text-center">
        <span className={hasMessages ? 'text-[var(--accent-yellow)] font-medium' : ''}>
          {queue.messages}
        </span>
      </td>
      <td className="px-3 py-2 text-center">
        <span className={queue.consumers > 0 ? 'text-[var(--accent-green)]' : 'text-[var(--text-secondary)]'}>
          {queue.consumers}
        </span>
      </td>
      <td className="px-3 py-2 text-center">
        <span className={hasMessages ? 'text-[var(--accent-blue)]' : 'text-[var(--text-secondary)]'}>
          {queue.messages_ready}
        </span>
      </td>
      <td className="px-3 py-2 text-center">
        <span className={hasUnacked ? 'text-[var(--accent-red)]' : 'text-[var(--text-secondary)]'}>
          {queue.messages_unacked}
        </span>
      </td>
    </tr>
  )
}
