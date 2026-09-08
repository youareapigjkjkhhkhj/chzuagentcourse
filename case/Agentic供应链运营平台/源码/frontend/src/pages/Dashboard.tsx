import { motion } from 'framer-motion'
import {
  Activity,
  ArrowRight,
  Boxes,
  CircleDollarSign,
  Clock3,
  LineChart,
  ShieldAlert,
  TimerReset,
} from 'lucide-react'
import { useControlTower } from '../hooks/usePlatform'
import styles from './Dashboard.module.css'

const kpiMeta = [
  { key: 'total_skus', label: '追踪 SKU 数', icon: Boxes },
  { key: 'active_risks', label: '活跃风险', icon: ShieldAlert },
  { key: 'pending_pos', label: '待处理采购单', icon: Activity },
  { key: 'pending_po_value', label: '待处理采购金额', icon: CircleDollarSign },
] as const

export function Dashboard() {
  const { data, loading, error } = useControlTower()

  if (loading) {
    return <div className={styles.state}>正在加载控制塔快照...</div>
  }

  if (error || !data) {
    return <div className={styles.state}>无法加载控制塔数据。</div>
  }

  const highestRisk = data.risk_digest.find((risk) => risk.risk_status === 'critical') ?? data.risk_digest[0]
  const impactMetrics = [
    {
      label: '服务连续性',
      value: `${Math.max(91, data.headline.resilience_score)}%`,
      detail: '执行活跃策略后的预估履约保护率',
      icon: Activity,
    },
    {
      label: '交货周期压缩',
      value: `${Math.max(2, Math.round(data.headline.avg_vendor_lead_time_days * 0.18))}天`,
      detail: '本周期可用的谈判与路由杠杆',
      icon: Clock3,
    },
    {
      label: '风险敞口资金',
      value: `$${Math.round(data.kpis.pending_po_value * 0.17).toLocaleString()}`,
      detail: '需要策略感知执行的未结承诺',
      icon: CircleDollarSign,
    },
    {
      label: '利润护盾',
      value: `${Math.round(data.headline.autonomy_score * 0.12)} 基点`,
      detail: '对标基准采购行动的预期收益',
      icon: LineChart,
    },
  ]

  return (
    <div className={styles.page}>
      <motion.section
        className={styles.hero}
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45 }}
      >
        <div className={styles.heroCopy}>
          <span className={styles.kicker}>{data.headline.platform_name}</span>
          <h1 className={styles.heroTitle}>更清晰地洞察供应风险、智能体建议与受控行动。</h1>
          <p className={styles.heroText}>
            Atlas AI 正在追踪库存风险敞口，准备采购决策，并通过策略感知工作流路由高影响变更。
          </p>
          <div className={styles.heroSummary}>
            <div>
              <span className={styles.summaryLabel}>当前态势</span>
              <strong>{data.headline.network_health}</strong>
            </div>
            <div>
              <span className={styles.summaryLabel}>优先通道</span>
              <strong>{highestRisk?.sku ?? '无'}</strong>
            </div>
          </div>
        </div>
        <div className={styles.heroMetrics}>
          <div>
            <span className={styles.metricLabel}>自主评分</span>
            <strong>{data.headline.autonomy_score}</strong>
          </div>
          <div>
            <span className={styles.metricLabel}>韧性评分</span>
            <strong>{data.headline.resilience_score}</strong>
          </div>
          <div>
            <span className={styles.metricLabel}>平均交货周期</span>
            <strong>{data.headline.avg_vendor_lead_time_days}天</strong>
          </div>
        </div>
      </motion.section>

      <section className={styles.impactGrid}>
        {impactMetrics.map(({ label, value, detail, icon: Icon }) => (
          <article key={label} className={styles.impactCard}>
            <div className={styles.impactIcon}>
              <Icon size={16} />
            </div>
            <div>
              <span className={styles.panelEyebrow}>{label}</span>
              <strong>{value}</strong>
              <p>{detail}</p>
            </div>
          </article>
        ))}
      </section>

      <section className={styles.kpiGrid}>
        {kpiMeta.map(({ key, label, icon: Icon }, index) => (
          <motion.article
            key={key}
            className={styles.kpi}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: 0.05 * index }}
          >
            <Icon size={18} />
            <div>
              <span>{label}</span>
              <strong>
                {key === 'pending_po_value'
                  ? `$${data.kpis[key].toLocaleString()}`
                  : data.kpis[key].toLocaleString()}
              </strong>
            </div>
          </motion.article>
        ))}
      </section>

      <section className={styles.mainGrid}>
        <div className={styles.primaryColumn}>
          <div className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <span className={styles.panelEyebrow}>推荐行动</span>
                <h2>决策剧本</h2>
              </div>
            </div>
            <div className={styles.recommendationList}>
              {data.priority_recommendations.map((item) => (
                <div key={item.title} className={styles.recommendation}>
                  <div>
                    <h3>{item.title}</h3>
                    <p>{item.impact}</p>
                  </div>
                  <div className={styles.recommendationMeta}>
                    <span>{Math.round(item.confidence * 100)}% 置信度</span>
                    <strong>{item.action}</strong>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <span className={styles.panelEyebrow}>补货队列</span>
                <h2>优先 SKU 通道</h2>
              </div>
              <TimerReset size={16} />
            </div>
            <div className={styles.table}>
              {data.replenishment_candidates.map((item) => (
                <div key={item.sku} className={styles.tableRow}>
                  <div>
                    <strong>{item.name}</strong>
                    <span>{item.sku}</span>
                  </div>
                  <div>
                    <span>健康度</span>
                    <strong>{item.inventory_health}%</strong>
                  </div>
                  <div>
                    <span>可用数量</span>
                    <strong>{item.available_units}</strong>
                  </div>
                  <div>
                    <span>建议采购</span>
                    <strong>{item.recommended_buy}</strong>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className={styles.secondaryColumn}>
          <div className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <span className={styles.panelEyebrow}>网络平衡</span>
                <h2>仓库负载分布</h2>
              </div>
            </div>
            <div className={styles.stackList}>
              {data.warehouse_network.map((warehouse) => (
                <div key={warehouse.warehouse} className={styles.stackItem}>
                  <div>
                    <strong>{warehouse.warehouse}</strong>
                    <span>{warehouse.utilization_band} 压力</span>
                  </div>
                  <div className={styles.barTrack}>
                    <div
                      className={`${styles.barFill} ${styles[warehouse.utilization_band]}`}
                      style={{ width: `${Math.min(100, warehouse.units / 6)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <span className={styles.panelEyebrow}>风险摘要</span>
                <h2>范围内的风险升级</h2>
              </div>
            </div>
            <div className={styles.riskList}>
              {data.risk_digest.map((risk) => (
                <div key={risk.sku} className={styles.riskItem}>
                  <div>
                    <strong>{risk.name}</strong>
                    <span>{risk.sku}</span>
                  </div>
                  <span className={`${styles.riskBadge} ${styles[risk.risk_status]}`}>
                    {risk.risk_status}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className={styles.signalPanel}>
            <span className={styles.panelEyebrow}>关键信号</span>
            <h2>{highestRisk?.name ?? '当前无关键风险'}</h2>
            <p>
              {highestRisk
                ? `${highestRisk.sku} 是当前最高关注通道，共 ${highestRisk.total_quantity} 单位，再订货点为 ${highestRisk.reorder_point}。`
                : '当前快照中没有活跃的即时短缺事件。'}
            </p>
            <div className={styles.signalFooter}>
              <span>建议目的地</span>
              <strong>工作流网</strong>
            </div>
          </div>

          <div className={styles.linkPanel}>
            <span className={styles.panelEyebrow}>后续入口</span>
            <h2>场景实验室和治理中心已关联至同一运营上下文。</h2>
            <p>压力测试中断场景、审查审批阈值，并验证哪些环节仍需人工审核后方可执行。</p>
            <div className={styles.linkRow}>
              <span>请从左侧导航打开更多模块。</span>
              <ArrowRight size={18} />
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
