import { AlertTriangle, ArrowUp, ArrowDown } from 'lucide-react'
import styles from './RiskAlertFeed.module.css'

interface RiskAlert {
  sku: string
  name: string
  risk_status: 'critical' | 'low' | 'excess' | 'normal'
  total_quantity: number
  reorder_point: number
}

interface RiskAlertFeedProps {
  risks: RiskAlert[]
}

export function RiskAlertFeed({ risks }: RiskAlertFeedProps) {
  const getSeverityIcon = (status: string) => {
    switch (status) {
      case 'critical':
        return <AlertTriangle size={16} />
      case 'low':
        return <ArrowDown size={16} />
      case 'excess':
        return <ArrowUp size={16} />
      default:
        return null
    }
  }

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>风险预警动态</h3>
      <div className={styles.feed}>
        {risks.length === 0 ? (
          <div className={styles.empty}>暂无活跃风险预警</div>
        ) : (
          risks.map((risk, index) => (
            <div
              key={risk.sku}
              className={`${styles.alert} ${styles[risk.risk_status]}`}
              style={{ animationDelay: `${index * 100}ms` }}
            >
              <div className={`${styles.iconWrapper} ${styles[risk.risk_status]}`}>
                {getSeverityIcon(risk.risk_status)}
              </div>
              <div className={styles.content}>
                <div className={styles.header}>
                  <span className={styles.productName}>{risk.name}</span>
                  <span className={`${styles.badge} ${styles[risk.risk_status]}`}>
                    {risk.risk_status}
                  </span>
                </div>
                <div className={styles.details}>
                  <span className={styles.sku}>{risk.sku}</span>
                  <span className={styles.qty}>
                    {risk.total_quantity} / {risk.reorder_point} 单位
                  </span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
