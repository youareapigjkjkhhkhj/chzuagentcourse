import { WorkflowEvent } from '../../hooks/useAgentSocket'
import styles from './AgentChatPanel.module.css'

interface AgentChatPanelProps {
  events: WorkflowEvent[]
}

export function AgentChatPanel({ events }: AgentChatPanelProps) {
  const getAgentLabel = (agent: string) => {
    const labels: Record<string, string> = {
      inventory_monitor: '库存',
      demand_forecast: '需求',
      procurement: '采购',
      vendor_negotiation: '谈判',
      logistics: '物流',
    }
    return labels[agent] || '智能体'
  }

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>智能体消息</h3>
      <div className={styles.messages}>
        {events.length === 0 ? (
          <div className={styles.empty}>启动工作流以查看智能体消息</div>
        ) : (
          events.map((event, i) => {
            const data = event.data
            const isSystem = !data?.agent

            return (
              <div
                key={i}
                className={`${styles.message} ${isSystem ? styles.system : styles.agent}`}
              >
                {!isSystem && (
                  <span className={styles.badge}>{getAgentLabel(data.agent)}</span>
                )}
                <div className={styles.content}>
                  <span className={styles.agentName}>
                    {isSystem ? '系统' : data.agent.replace('_', ' ')}
                  </span>
                  <p className={styles.text}>
                    {data.status || data.message || JSON.stringify(data).slice(0, 50)}
                  </p>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
