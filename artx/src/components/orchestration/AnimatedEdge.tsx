import { memo } from 'react'
import { type EdgeProps, getBezierPath, EdgeLabelRenderer, BaseEdge } from '@xyflow/react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

interface AnimatedEdgeData extends Record<string, unknown> {
  isActive?: boolean
  isCompleted?: boolean
  showParticle?: boolean
}

function AnimatedEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<any>) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  })

  const isActive = data?.isActive ?? false
  const isCompleted = data?.isCompleted ?? false
  const showParticle = data?.showParticle ?? false

  const edgeColor = isCompleted
    ? '#10b981'
    : isActive
      ? '#3b82f6'
      : '#2a2a3d'

  const edgeWidth = isCompleted || isActive ? 2.5 : 1.5

  return (
    <>
      <BaseEdge
        id={String(id ?? '')}
        path={edgePath}
        style={{
          stroke: edgeColor,
          strokeWidth: edgeWidth,
          strokeDasharray: isActive ? '8 6' : '5 8',
          transition: 'stroke 0.5s ease, stroke-width 0.5s ease',
        }}
        className={cn(isActive && 'animate-pulse')}
      />

      {isActive && (
        <>
          <motion.path
            d={edgePath}
            fill="none"
            stroke="rgba(96,165,250,0.18)"
            strokeWidth={10}
            strokeLinecap="round"
            style={{ filter: 'blur(8px)' }}
            initial={{ pathLength: 0.15, opacity: 0.4 }}
            animate={{ pathLength: 1, opacity: 0.8 }}
            transition={{ duration: 1, ease: 'easeInOut' }}
          />
          <motion.path
            d={edgePath}
            fill="none"
            stroke="rgba(125,211,252,0.85)"
            strokeWidth={3.5}
            strokeLinecap="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.2, ease: 'easeInOut', repeat: Infinity, repeatType: 'reverse' }}
          />
        </>
      )}

      {showParticle && (
        <g>
          {[0, 1, 2].map((index) => (
            <motion.circle
              key={`${id}-${index}`}
              r={index === 0 ? 4 : 2.5}
              fill={index === 0 ? '#38bdf8' : 'rgba(224,242,254,0.9)'}
              style={{ filter: 'drop-shadow(0 0 8px rgba(56,189,248,0.75))' }}
            >
              <animateMotion
                dur={`${1.6 + index * 0.2}s`}
                repeatCount="indefinite"
                path={edgePath}
                begin={`${index * 0.25}s`}
              />
            </motion.circle>
          ))}
        </g>
      )}

      {isActive && (
        <EdgeLabelRenderer>
          <div
            className="absolute bg-info/10 backdrop-blur-md px-2 py-0.5 rounded text-[10px] text-info font-mono border border-info/20 pointer-events-none"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            }}
          >
            transmitting...
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

export default memo(AnimatedEdge)
