import { useState, useEffect, useCallback, useRef } from 'react'
import { createWorkflowSocket } from '../lib/api'

export interface WorkflowEvent {
  type: string
  data: any
  session_id: string
}

export interface AgentStatus {
  agent: string
  status: 'idle' | 'active' | 'completed' | 'error'
  message: string
  state?: any
}

export function useAgentSocket(sessionId: string | null) {
  const initialStatuses = {
    inventory_monitor: { agent: 'inventory_monitor', status: 'idle', message: '' },
    demand_forecast: { agent: 'demand_forecast', status: 'idle', message: '' },
    procurement: { agent: 'procurement', status: 'idle', message: '' },
    vendor_negotiation: { agent: 'vendor_negotiation', status: 'idle', message: '' },
    logistics: { agent: 'logistics', status: 'idle', message: '' },
  } satisfies Record<string, AgentStatus>
  const [events, setEvents] = useState<WorkflowEvent[]>([])
  const [agentStatuses, setAgentStatuses] = useState<Record<string, AgentStatus>>(initialStatuses)
  const [workflowResult, setWorkflowResult] = useState<any>(null)
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  const startWorkflow = useCallback((sku: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setEvents([])
      setWorkflowResult(null)
      setAgentStatuses(initialStatuses)
      wsRef.current.send(JSON.stringify({ action: 'start_workflow', sku }))
    }
  }, [])

  useEffect(() => {
    if (!sessionId) return

    const ws = createWorkflowSocket(sessionId)
    wsRef.current = ws

    ws.onopen = () => setIsConnected(true)
    ws.onclose = () => setIsConnected(false)
    ws.onerror = () => setIsConnected(false)

    ws.onmessage = (event) => {
      const data: WorkflowEvent = JSON.parse(event.data)
      setEvents((prev) => [...prev, data])

      if (data.type === 'workflow_started') {
        setAgentStatuses(initialStatuses)
        setWorkflowResult(null)
      } else if (data.type === 'agent_started') {
        setAgentStatuses((prev) => ({
          ...prev,
          [data.data.agent]: {
            agent: data.data.agent,
            status: 'active',
            message: data.data.status,
          },
        }))
      } else if (data.type === 'agent_completed') {
        setAgentStatuses((prev) => ({
          ...prev,
          [data.data.agent]: {
            agent: data.data.agent,
            status: 'completed',
            message: data.data.status,
            state: data.data.state,
          },
        }))
      } else if (data.type === 'workflow_completed') {
        setWorkflowResult(data.data.result)
      }
    }

    return () => {
      ws.close()
    }
  }, [sessionId])

  return { events, agentStatuses, workflowResult, isConnected, startWorkflow }
}
