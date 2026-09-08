import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  GitBranch,
  MessageSquare,
  ShieldCheck,
  Radar,
  Sparkles,
} from 'lucide-react'
import styles from './Sidebar.module.css'

const navItems = [
  { path: '/', icon: LayoutDashboard, label: '控制塔' },
  { path: '/scenarios', icon: Radar, label: '场景实验室' },
  { path: '/workflow', icon: GitBranch, label: '工作流网' },
  { path: '/governance', icon: ShieldCheck, label: '治理中心' },
  { path: '/negotiation', icon: MessageSquare, label: '供应商谈判' },
]

export function Sidebar() {
  return (
    <aside className={styles.sidebar}>
      <div className={styles.logoWrap}>
        <div className={styles.logo}>
          <div className={styles.logoIcon}>AT</div>
          <div>
            <span className={styles.logoText}>Atlas AI</span>
            <p className={styles.logoSubtext}>供应链网络平台</p>
          </div>
        </div>
        <div className={styles.missionCard}>
          <span className={styles.missionLabel}>决策平面</span>
          <strong>自主规划，受监督执行</strong>
        </div>
      </div>
      <div className={styles.sectionLabel}>运营中心</div>
      <nav className={styles.nav}>
        {navItems.map(({ path, icon: Icon, label }) => (
          <NavLink
            key={path}
            to={path}
            className={({ isActive }) =>
              `${styles.navItem} ${isActive ? styles.active : ''}`
            }
          >
            <Icon size={20} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className={styles.sectionLabel}>运行时</div>
      <div className={styles.runtimeCard}>
        <div className={styles.runtimeRow}>
          <span>LLM 策略带</span>
          <strong>在线</strong>
        </div>
        <div className={styles.runtimeRow}>
          <span>遥测路径</span>
          <strong>本地</strong>
        </div>
        <div className={styles.runtimeBadge}>
          <Sparkles size={14} />
          <span>已启用新型采购与谈判智能体</span>
        </div>
      </div>
      <div className={styles.footer}>
        <div className={styles.statusIndicator}>
          <div className={styles.statusDot} />
          <span>自主监督模式</span>
        </div>
      </div>
    </aside>
  )
}
