import { Package, AlertTriangle, FileText, DollarSign } from 'lucide-react'
import styles from './KPICards.module.css'

interface KPIData {
  total_skus: number
  active_risks: number
  pending_pos: number
  pending_po_value: number
}

interface KPICardsProps {
  kpis: KPIData | null
}

const kpiConfig = [
  {
    key: 'total_skus' as const,
    label: 'SKU 总数',
    icon: Package,
    color: 'blue',
    format: (v: number) => v.toString(),
  },
  {
    key: 'active_risks' as const,
    label: '活跃风险',
    icon: AlertTriangle,
    color: 'red',
    format: (v: number) => v.toString(),
  },
  {
    key: 'pending_pos' as const,
    label: '待处理采购单',
    icon: FileText,
    color: 'amber',
    format: (v: number) => v.toString(),
  },
  {
    key: 'pending_po_value' as const,
    label: '待处理采购金额',
    icon: DollarSign,
    color: 'green',
    format: (v: number) => `$${v.toLocaleString()}`,
  },
]

export function KPICards({ kpis }: KPICardsProps) {
  if (!kpis) return null

  return (
    <div className={styles.container}>
      {kpiConfig.map(({ key, label, icon: Icon, color, format }) => (
        <div key={key} className={`${styles.card} ${styles[color]}`}>
          <div className={styles.iconWrapper}>
            <Icon size={24} />
          </div>
          <div className={styles.content}>
            <span className={styles.value}>{format(kpis[key])}</span>
            <span className={styles.label}>{label}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
