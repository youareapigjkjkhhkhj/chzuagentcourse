import { Search, Bell, ShieldCheck, Activity, DatabaseZap } from 'lucide-react'
import styles from './Header.module.css'

export function Header() {
  return (
    <header className={styles.header}>
      <div className={styles.titleBlock}>
        <div className={styles.metaRow}>
          <span className={styles.eyebrow}>Atlas AI 操作系统</span>
          <div className={styles.liveStrip}>
            <span><Activity size={12} /> 在线智能体</span>
            <span><DatabaseZap size={12} /> ClickHouse + MLflow</span>
          </div>
        </div>
        <div className={styles.searchContainer}>
          <Search size={18} className={styles.searchIcon} />
          <input
            type="text"
            placeholder="搜索 SKU、供应商、策略或政策..."
            className={styles.searchInput}
          />
          <kbd className={styles.kbd}>⌘K</kbd>
        </div>
      </div>
      <div className={styles.actions}>
        <div className={styles.statusPill}>
          <ShieldCheck size={14} />
          <span>策略护栏已启用</span>
        </div>
        <button className={styles.iconButton}>
          <Bell size={20} />
          <span className={styles.notificationBadge}>3</span>
        </button>
        <div className={styles.avatar}>AC</div>
      </div>
    </header>
  )
}
