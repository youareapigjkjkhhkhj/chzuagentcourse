import { AgentStatus } from '../../hooks/useAgentSocket'
import { AgentNode } from './AgentNode'
import styles from './WorkflowCanvas.module.css'

interface Agent {
  id: string
  label: string
  description: string
}

interface WorkflowCanvasProps {
  agents: Agent[]
  agentStatuses: Record<string, AgentStatus>
}

export function WorkflowCanvas({ agents, agentStatuses }: WorkflowCanvasProps) {
  return (
    <div className={styles.container}>
      <div className={styles.canvas}>
        <div className={styles.startNode}>
          <div className={styles.startPulse} />
          <span>SKU 输入</span>
        </div>

        <div className={styles.connector} />

        <div className={styles.nodes}>
          {agents.map((agent, index) => (
            <div key={agent.id} className={styles.nodeWrapper}>
              <AgentNode
                agent={agent}
                status={agentStatuses[agent.id]?.status || 'idle'}
                message={agentStatuses[agent.id]?.message || ''}
              />
              {index < agents.length - 1 && (
                <div className={styles.nodeConnector}>
                  <svg width="100%" height="40" viewBox="0 0 200 40">
                    <path
                      d="M 0 20 L 200 20"
                      stroke="var(--border-color)"
                      strokeWidth="2"
                      strokeDasharray="4 4"
                      fill="none"
                    />
                    <polygon
                      points="195,15 200,20 195,25"
                      fill="var(--border-color)"
                    />
                  </svg>
                </div>
              )}
            </div>
          ))}
        </div>

        <div className={styles.connector} />

        <div className={styles.endNode}>
          <div className={styles.checkmark}>✓</div>
          <span>推荐结果</span>
        </div>
      </div>
    </div>
  )
}
