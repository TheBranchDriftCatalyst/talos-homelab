import { useState, type ReactNode } from 'react'
import { RotateCcw } from 'lucide-react'

interface FlipCardProps {
  front: ReactNode
  back: ReactNode
  className?: string
}

export function FlipCard({ front, back, className = '' }: FlipCardProps) {
  const [isFlipped, setIsFlipped] = useState(false)

  return (
    <div className={`flip-card ${className}`}>
      <div className={`flip-card-inner ${isFlipped ? 'flipped' : ''}`}>
        <div className="flip-card-front">
          {front}
          <button
            onClick={() => setIsFlipped(true)}
            className="flip-btn"
            title="Show configuration"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </div>
        <div className="flip-card-back">
          {back}
          <button
            onClick={() => setIsFlipped(false)}
            className="flip-btn"
            title="Show details"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
