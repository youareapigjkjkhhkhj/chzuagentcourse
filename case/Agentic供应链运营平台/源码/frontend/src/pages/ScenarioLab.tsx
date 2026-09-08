import { motion } from 'framer-motion'
import { AlertOctagon, TrendingDown, TrendingUp } from 'lucide-react'
import { useScenarioLab } from '../hooks/usePlatform'
import styles from './ScenarioLab.module.css'

export function ScenarioLab() {
  const { data, loading, error } = useScenarioLab()

  if (loading) {
    return <div className={styles.state}>正在加载场景模拟...</div>
  }

  if (error || !data) {
    return <div className={styles.state}>无法加载场景模拟。</div>
  }

  return (
    <div className={styles.page}>
      <section className={styles.header}>
        <div>
          <span className={styles.eyebrow}>场景实验室</span>
          <h1>在智能体执行前对供应冲击进行压力测试。</h1>
        </div>
        <p>{data.simulation_window}. {data.recommended_playbook}</p>
      </section>

      <section className={styles.grid}>
        {data.scenarios.map((scenario, index) => (
          <motion.article
            key={scenario.id}
            className={styles.card}
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: index * 0.07 }}
          >
            <div className={styles.topRow}>
              <span className={`${styles.badge} ${styles[scenario.severity]}`}>{scenario.severity}</span>
              <AlertOctagon size={16} />
            </div>
            <h2>{scenario.name}</h2>
            <dl className={styles.metrics}>
              <div>
                <dt>发生概率</dt>
                <dd>{Math.round(scenario.probability * 100)}%</dd>
              </div>
              <div>
                <dt>库存影响</dt>
                <dd>
                  <TrendingDown size={15} />
                  {scenario.inventory_impact_pct}%
                </dd>
              </div>
              <div>
                <dt>利润影响</dt>
                <dd>
                  <TrendingUp size={15} />
                  {scenario.margin_impact_pct}%
                </dd>
              </div>
            </dl>
            <p>{scenario.recommended_response}</p>
          </motion.article>
        ))}
      </section>
    </div>
  )
}
