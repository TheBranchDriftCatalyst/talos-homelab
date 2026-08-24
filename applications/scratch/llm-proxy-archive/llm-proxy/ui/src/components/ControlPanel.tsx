import type { StatusUpdate, LogEntry } from '../types/api'
import { WorkerCard } from './WorkerCard'
import { FlipCard } from './FlipCard'
import { ScalerBackPanel } from './ScalerBackPanel'
import { BrokerCard } from './BrokerCard'
import { ActivityLog } from './ActivityLog'

interface ControlPanelProps {
  status: StatusUpdate | null
  logs: LogEntry[]
  onControl: (action: string, target?: string, data?: string) => void
  onClearLogs: () => void
}

export function ControlPanel({ status, logs, onControl, onClearLogs }: ControlPanelProps) {
  const workers = status?.workers || []
  const localWorker = workers.find((w) => w.type === 'local')
  const remoteWorker = workers.find((w) => w.type === 'remote')
  const macWorker = workers.find((w) => w.type === 'mac')

  return (
    <div className="h-full overflow-auto p-6">
      <div className="max-w-7xl mx-auto">
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
          {/* Local Worker */}
          {localWorker && (
            <WorkerCard
              worker={localWorker}
              icon="🏠"
              subtitle="talos06 • Intel Arc 140T"
              onControl={onControl}
            />
          )}

          {/* Remote Worker (EC2) with Scaler Config on flip */}
          {remoteWorker && (
            <FlipCard
              front={
                <WorkerCard
                  worker={remoteWorker}
                  icon="☁️"
                  subtitle={`${remoteWorker.ec2?.instance_type || 'r5.2xlarge'} • ${remoteWorker.ec2?.region || 'us-west-2'}`}
                  onControl={onControl}
                  showControls
                />
              }
              back={<ScalerBackPanel status={status?.scaler} onControl={onControl} />}
            />
          )}

          {/* Mac Worker (if present) */}
          {macWorker && (
            <WorkerCard
              worker={macWorker}
              icon="🍎"
              subtitle="Mac Dev Endpoint"
              onControl={onControl}
            />
          )}

          {/* Broker Status */}
          {status?.broker?.enabled && <BrokerCard broker={status.broker} />}

          {/* Activity Log */}
          <ActivityLog logs={logs} onClear={onClearLogs} />
        </div>
      </div>
    </div>
  )
}
