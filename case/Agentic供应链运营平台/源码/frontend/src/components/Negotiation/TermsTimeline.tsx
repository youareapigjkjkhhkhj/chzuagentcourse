import { DollarSign, Percent } from 'lucide-react'
import styles from './TermsTimeline.module.css'

interface TermSnapshot {
  price: number
  discount: number
  timestamp: Date
}

interface TermsTimelineProps {
  history: TermSnapshot[]
}

export function TermsTimeline({ history }: TermsTimelineProps) {
  if (history.length === 0) {
    return (
      <div className={styles.container}>
        <h3 className={styles.title}>条款演变</h3>
        <div className={styles.empty}>开始谈判以查看条款演变</div>
      </div>
    )
  }

  const latest = history[history.length - 1]
  const initial = history[0]
  const priceChange = ((initial.price - latest.price) / initial.price) * 100
  const discountChange = latest.discount - initial.discount

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>条款演变</h3>

      <div className={styles.current}>
        <div className={styles.currentItem}>
          <DollarSign size={20} />
          <div className={styles.currentContent}>
            <span className={styles.currentValue}>${latest.price.toFixed(2)}</span>
            <span className={styles.currentLabel}>当前价格</span>
          </div>
        </div>
        <div className={styles.currentItem}>
          <Percent size={20} />
          <div className={styles.currentContent}>
            <span className={styles.currentValue}>{latest.discount.toFixed(1)}%</span>
            <span className={styles.currentLabel}>折扣</span>
          </div>
        </div>
      </div>

      <div className={styles.changes}>
        <div className={`${styles.change} ${priceChange > 0 ? styles.positive : ''}`}>
          <span className={styles.changeLabel}>价格变动</span>
          <span className={styles.changeValue}>
            {priceChange > 0 ? '↓' : '↑'} {Math.abs(priceChange).toFixed(1)}%
          </span>
        </div>
        <div className={`${styles.change} ${discountChange > 0 ? styles.positive : ''}`}>
          <span className={styles.changeLabel}>折扣收益</span>
          <span className={styles.changeValue}>+{discountChange.toFixed(1)}%</span>
        </div>
      </div>

      <div className={styles.timeline}>
        {history.map((snapshot, i) => (
          <div key={i} className={styles.timelineItem}>
            <div className={styles.timelineDot} />
            <div className={styles.timelineContent}>
              <span className={styles.timelinePrice}>${snapshot.price.toFixed(2)}</span>
              <span className={styles.timelineDiscount}>{snapshot.discount.toFixed(1)}% 优惠</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
