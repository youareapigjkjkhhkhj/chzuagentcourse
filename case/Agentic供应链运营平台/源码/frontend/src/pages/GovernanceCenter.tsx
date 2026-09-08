import { Shield, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useGovernanceHub } from '../hooks/usePlatform'
import styles from './GovernanceCenter.module.css'

export function GovernanceCenter() {
  const { data, loading, error } = useGovernanceHub()

  if (loading) {
    return <div className={styles.state}>正在加载治理控制...</div>
  }

  if (error || !data) {
    return <div className={styles.state}>无法加载治理控制。</div>
  }

  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}>治理中心</span>
          <h1>自主运行，配合明确的审批路径、阈值与可追溯性。</h1>
        </div>
        <div className={styles.policy}>
          <ShieldCheck size={18} />
          <span>{data.policy_posture}</span>
        </div>
      </section>

      <section className={styles.grid}>
        <div className={styles.panel}>
          <div className={styles.sectionHeader}>
            <Shield size={16} />
            <h2>审批队列</h2>
          </div>
          <div className={styles.list}>
            {data.approval_queues.map((queue) => (
              <div key={queue.name} className={styles.row}>
                <div>
                  <strong>{queue.name}</strong>
                  <span>{queue.threshold}</span>
                </div>
                <div className={styles.numeric}>
                  <strong>{queue.pending}</strong>
                  <span>{queue.sla}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.sectionHeader}>
            <ShieldAlert size={16} />
            <h2>护栏规则</h2>
          </div>
          <div className={styles.guardrails}>
            {data.guardrails.map((guardrail) => (
              <div key={guardrail} className={styles.guardrail}>
                {guardrail}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.panel}>
        <div className={styles.sectionHeader}>
          <ShieldCheck size={16} />
          <h2>智能体可靠性登记表</h2>
        </div>
        <div className={styles.registry}>
          {data.agent_registry.map((agent) => (
            <div key={agent.agent} className={styles.agentCard}>
              <div className={styles.agentTop}>
                <strong>{agent.agent}</strong>
                <span className={`${styles.status} ${styles[agent.status]}`}>{agent.status}</span>
              </div>
              <p>{agent.last_decision}</p>
              <div className={styles.reliabilityBar}>
                <div style={{ width: `${Math.round(agent.reliability * 100)}%` }} />
              </div>
              <span className={styles.reliabilityLabel}>{Math.round(agent.reliability * 100)}% 可靠性</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
