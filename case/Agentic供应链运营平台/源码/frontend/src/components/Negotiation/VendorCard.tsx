import { Truck, Clock, DollarSign } from 'lucide-react'
import styles from './VendorCard.module.css'

interface Vendor {
  vendor_id: number
  name: string
  lead_time_days: number
  min_order_value: number
}

interface VendorCardProps {
  vendor: Vendor | null
}

export function VendorCard({ vendor }: VendorCardProps) {
  if (!vendor) {
    return (
      <div className={styles.container}>
        <div className={styles.empty}>未选择供应商</div>
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.avatar}>
          {vendor.name.split(' ').map((n) => n[0]).join('').slice(0, 2)}
        </div>
        <div className={styles.info}>
          <h3 className={styles.name}>{vendor.name}</h3>
          <span className={styles.id}>供应商 #{vendor.vendor_id}</span>
        </div>
      </div>

      <div className={styles.stats}>
        <div className={styles.stat}>
          <div className={styles.statIcon}>
            <Clock size={18} />
          </div>
          <div className={styles.statContent}>
            <span className={styles.statValue}>{vendor.lead_time_days} 天</span>
            <span className={styles.statLabel}>交货周期</span>
          </div>
        </div>

        <div className={styles.stat}>
          <div className={styles.statIcon}>
            <DollarSign size={18} />
          </div>
          <div className={styles.statContent}>
            <span className={styles.statValue}>${vendor.min_order_value.toLocaleString()}</span>
            <span className={styles.statLabel}>最小起订量</span>
          </div>
        </div>

        <div className={styles.stat}>
          <div className={styles.statIcon}>
            <Truck size={18} />
          </div>
          <div className={styles.statContent}>
            <span className={styles.statValue}>LTL + FTL</span>
            <span className={styles.statLabel}>运输方式</span>
          </div>
        </div>
      </div>

      <div className={styles.badges}>
        <span className={styles.badge}>认证供应商</span>
        <span className={styles.badge}>快速响应</span>
      </div>
    </div>
  )
}
