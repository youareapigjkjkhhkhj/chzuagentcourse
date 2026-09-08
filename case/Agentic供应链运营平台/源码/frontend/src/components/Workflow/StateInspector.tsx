import { AgentStatus } from '../../hooks/useAgentSocket'
import styles from './StateInspector.module.css'

interface StateInspectorProps {
  agentStatuses: Record<string, AgentStatus>
  result: any
}

export function StateInspector({ agentStatuses, result }: StateInspectorProps) {
  const negotiationPrice = result?.negotiation_result?.negotiated_price
  const logisticsCost = result?.final_recommendation?.logistics_cost

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>状态检查器</h3>
      <div className={styles.content}>
        <div className={styles.section}>
          <h4 className={styles.sectionTitle}>智能体状态</h4>
          <div className={styles.stateGrid}>
            {Object.entries(agentStatuses).map(([key, status]) => (
              <div key={key} className={`${styles.stateItem} ${styles[status.status]}`}>
                <span className={styles.stateLabel}>{key.replace('_', ' ')}</span>
                <span className={styles.stateValue}>{status.status}</span>
              </div>
            ))}
          </div>
        </div>

        {result && (
          <div className={styles.section}>
            <h4 className={styles.sectionTitle}>最终推荐</h4>
            <div className={styles.recommendation}>
              <div className={styles.recItem}>
                <span className={styles.recLabel}>操作</span>
                <span className={styles.recValue}>{result.final_recommendation?.action}</span>
              </div>
              <div className={styles.recItem}>
                <span className={styles.recLabel}>供应商</span>
                <span className={styles.recValue}>ID {result.final_recommendation?.vendor_id}</span>
              </div>
              <div className={styles.recItem}>
                <span className={styles.recLabel}>数量</span>
                <span className={styles.recValue}>{result.final_recommendation?.quantity}</span>
              </div>
              <div className={styles.recItem}>
                <span className={styles.recLabel}>单价</span>
                <span className={styles.recValue}>${result.final_recommendation?.unit_price?.toFixed(2)}</span>
              </div>
              <div className={styles.recItem}>
                <span className={styles.recLabel}>总成本</span>
                <span className={`${styles.recValue} ${styles.highlight}`}>
                  ${result.final_recommendation?.total_cost?.toLocaleString()}
                </span>
              </div>
              <div className={styles.recItem}>
                <span className={styles.recLabel}>谈判价格</span>
                <span className={styles.recValue}>
                  {typeof negotiationPrice === 'number' ? `$${negotiationPrice.toFixed(2)}` : '待定'}
                </span>
              </div>
              <div className={styles.recItem}>
                <span className={styles.recLabel}>物流成本</span>
                <span className={styles.recValue}>
                  {typeof logisticsCost === 'number' ? `$${logisticsCost.toLocaleString()}` : '待定'}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
