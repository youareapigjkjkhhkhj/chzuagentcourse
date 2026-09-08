import { Check, Loader, AlertCircle } from 'lucide-react'
import styles from './AgentNode.module.css'

interface Agent {
  id: string
  label: string
  description: string
}

interface AgentNodeProps {
  agent: Agent
  status: 'idle' | 'active' | 'completed' | 'error'
  message: string
}

export function AgentNode({ agent, status, message }: AgentNodeProps) {
  const getStatusIcon = () => {
    switch (status) {
      case 'active':
        return <Loader size={18} className={styles.spinner} />
      case 'completed':
        return <Check size={18} />
      case 'error':
        return <AlertCircle size={18} />
      default:
        return null
    }
  }

  return (
    <div className={`${styles.node} ${styles[status]}`}>
      <div className={styles.header}>
        <span className={styles.label}>{agent.label}</span>
        <div className={`${styles.statusIcon} ${styles[status]}`}>
          {getStatusIcon()}
        </div>
      </div>
      <p className={styles.description}>{agent.description}</p>
      {message && <p className={styles.message}>{message}</p>}
    </div>
  )
}
