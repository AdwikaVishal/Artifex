import { useEffect, useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useReactFlow,
  type Node,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import AgentNode from './AgentNode'
import AnimatedEdge from './AnimatedEdge'
import type { AgentType, AgentStatus } from '@/types/orchestration'

interface AgentState {
  id: string
  status: AgentStatus
  confidence: number
}

interface AgentNetworkGraphProps {
  agentStates: Record<AgentType, AgentState>
  activeEdges?: string[]
  completedEdges?: string[]
  showParticles?: boolean
}

const INITIAL_POSITIONS: Record<AgentType, { x: number; y: number }> = {
  intake: { x: 550, y: 30 },
  planner: { x: 550, y: 220 },
  risk: { x: 180, y: 440 },
  matching: { x: 550, y: 440 },
  fairness: { x: 920, y: 440 },
  approval: { x: 550, y: 670 },
  monitoring: { x: 550, y: 890 },
}

const EDGE_DEFINITIONS: { id: string; source: AgentType; target: AgentType }[] = [
  { id: 'e-intake-planner', source: 'intake', target: 'planner' },
  { id: 'e-planner-risk', source: 'planner', target: 'risk' },
  { id: 'e-planner-matching', source: 'planner', target: 'matching' },
  { id: 'e-planner-fairness', source: 'planner', target: 'fairness' },
  { id: 'e-risk-approval', source: 'risk', target: 'approval' },
  { id: 'e-matching-approval', source: 'matching', target: 'approval' },
  { id: 'e-fairness-approval', source: 'fairness', target: 'approval' },
  { id: 'e-approval-monitoring', source: 'approval', target: 'monitoring' },
]

function FitViewController({ nodes, edges }: { nodes: Node[]; edges: Edge[] }) {
  const { fitView } = useReactFlow()

  useEffect(() => {
    const timer = window.setTimeout(() => {
      fitView({ padding: 0.22, duration: 400, minZoom: 0.5 })
    }, 80)

    const handleResize = () => {
      fitView({ padding: 0.22, duration: 180, minZoom: 0.5 })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('resize', handleResize)
    }
  }, [fitView, nodes, edges])

  return null
}

export default function AgentNetworkGraph({
  agentStates,
  activeEdges = [],
  completedEdges = [],
  showParticles = false,
}: AgentNetworkGraphProps) {
  const nodeTypes = useMemo(() => ({ agentNode: AgentNode as any }), [])
  const edgeTypes = useMemo(() => ({ animatedEdge: AnimatedEdge as any }), [])

  const nodes: Node[] = useMemo(
    () =>
      (Object.keys(INITIAL_POSITIONS) as AgentType[]).map((type) => ({
        id: type,
        type: 'agentNode',
        position: INITIAL_POSITIONS[type],
        data: {
          id: type,
          name: type.charAt(0).toUpperCase() + type.slice(1) + ' Agent',
          type,
          status: agentStates[type]?.status ?? 'idle',
          confidence: agentStates[type]?.confidence ?? 0,
        },
        draggable: false,
        selectable: false,
        style: { width: 270, height: 150 },
      })),
    [agentStates]
  )

  const edges: Edge[] = useMemo(
    () =>
      EDGE_DEFINITIONS.map((def) => ({
        id: def.id,
        source: def.source,
        target: def.target,
        type: 'animatedEdge',
        animated: activeEdges.includes(def.id),
        data: {
          isActive: activeEdges.includes(def.id),
          isCompleted: completedEdges.includes(def.id),
          showParticle: showParticles && activeEdges.includes(def.id),
        },
        style: {
          stroke: activeEdges.includes(def.id)
            ? '#60a5fa'
            : completedEdges.includes(def.id)
              ? '#10b981'
              : '#2a2a3d',
          strokeWidth:
            activeEdges.includes(def.id) || completedEdges.includes(def.id) ? 2.8 : 1.8,
          strokeDasharray: activeEdges.includes(def.id) ? '8 6' : '4 8',
          transition: 'all 0.45s ease',
        },
        markerEnd: {
          type: 'arrowclosed',
          color: activeEdges.includes(def.id)
            ? '#60a5fa'
            : completedEdges.includes(def.id)
              ? '#10b981'
              : '#4b5563',
        },
      })),
    [activeEdges, completedEdges, showParticles]
  )

  return (
    <div className="h-full w-full rounded-[28px] border border-white/10 bg-[linear-gradient(145deg,rgba(8,10,20,0.96),rgba(14,18,32,0.88))] shadow-[0_24px_60px_rgba(15,23,42,0.45)] overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.22, minZoom: 0.5 }}
        minZoom={0.4}
        maxZoom={1.5}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        defaultViewport={{ x: 0, y: 0, zoom: 0.85 }}
        defaultEdgeOptions={{
          style: { stroke: '#2a2a3d', strokeWidth: 1.8 },
        }}
      >
        <FitViewController nodes={nodes} edges={edges} />
        <Background color="rgba(148,163,184,0.08)" gap={30} size={1.2} />
        <Controls
          showInteractive={false}
          className="!bg-surface/95 !border-white/10 !rounded-xl !shadow-[0_12px_30px_rgba(15,23,42,0.35)]"
        />
        <MiniMap
          nodeStrokeColor="#6366f1"
          nodeColor="rgba(99,102,241,0.16)"
          nodeBorderRadius={10}
          maskColor="rgba(8,10,15,0.78)"
          className="!bg-surface/95 !border-white/10 !rounded-xl !shadow-[0_12px_30px_rgba(15,23,42,0.35)]"
        />
      </ReactFlow>
    </div>
  )
}
