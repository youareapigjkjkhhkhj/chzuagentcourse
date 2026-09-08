import { useState, useEffect } from 'react'
import { useAgentSocket } from '../hooks/useAgentSocket'
import { WorkflowCanvas } from '../components/Workflow/WorkflowCanvas'
import { AgentChatPanel } from '../components/Workflow/AgentChatPanel'
import { StateInspector } from '../components/Workflow/StateInspector'
import { fetchProducts } from '../lib/api'
import { Play, RefreshCw, Activity, Bot, Radio, Wallet, Truck, BadgePercent } from 'lucide-react'
import styles from './WorkflowVisualizer.module.css'

const AGENTS = [
  { id: 'inventory_monitor', label: '库存监控', description: '监控库存水平并检测风险' },
  { id: 'demand_forecast', label: '需求预测', description: '基于历史数据预测未来需求' },
  { id: 'procurement', label: '采购', description: '创建采购申请单' },
  { id: 'vendor_negotiation', label: '供应商谈判', description: '模拟供应商议价过程' },
  { id: 'logistics', label: '物流', description: '优化运输与交付方案' },
]

export function WorkflowVisualizer() {
  const [sessionId] = useState(() => `session_${Date.now()}`)
  const [selectedSKU, setSelectedSKU] = useState('SKU-001')
  const [products, setProducts] = useState<{ sku: string; name: string }[]>([])
  const { agentStatuses, workflowResult, isConnected, startWorkflow, events } = useAgentSocket(sessionId)

  useEffect(() => {
    fetchProducts().then((data) => setProducts(data.slice(0, 5)))
  }, [])

  const handleStartWorkflow = () => {
    startWorkflow(selectedSKU)
  }

  const completedAgents = Object.values(agentStatuses).filter(
    (status) => status.status === 'completed'
  ).length

  const workflowKpis = [
    {
      label: '网络状态',
      value: isConnected ? '在线' : '离线',
      icon: Radio,
    },
    {
      label: '已完成智能体',
      value: `${completedAgents}/${AGENTS.length}`,
      icon: Bot,
    },
    {
      label: '事件吞吐量',
      value: events.length.toString(),
      icon: Activity,
    },
    {
      label: '预估支出',
      value: workflowResult?.final_recommendation?.total_cost
        ? `$${workflowResult.final_recommendation.total_cost.toLocaleString()}`
        : '待定',
      icon: Wallet,
    },
    {
      label: '相比预估节省',
      value:
        workflowResult?.purchase_requisition?.estimated_unit_price &&
        workflowResult?.negotiation_result?.negotiated_price
          ? `${Math.max(
              0,
              (((workflowResult.purchase_requisition.estimated_unit_price -
                workflowResult.negotiation_result.negotiated_price) /
                workflowResult.purchase_requisition.estimated_unit_price) *
                100)
            ).toFixed(1)}%`
          : '待定',
      icon: BadgePercent,
    },
    {
      label: '交付预计到达',
      value: workflowResult?.logistics_plan?.delivery_timeline
        ? `${workflowResult.logistics_plan.delivery_timeline} 天`
        : '待定',
      icon: Truck,
    },
  ]

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>智能体工作流可视化</h1>
          <p className={styles.subtitle}>实时 LangGraph 执行：涵盖库存、计划、采购、谈判与物流</p>
        </div>
        <div className={styles.controls}>
          <select
            value={selectedSKU}
            onChange={(e) => setSelectedSKU(e.target.value)}
            className={styles.select}
          >
            {products.map((p) => (
              <option key={p.sku} value={p.sku}>
                {p.sku} - {p.name}
              </option>
            ))}
          </select>
          <button
            className={styles.startButton}
            onClick={handleStartWorkflow}
            disabled={!isConnected}
          >
            <Play size={18} />
            启动工作流
          </button>
          <div className={`${styles.connectionStatus} ${isConnected ? styles.connected : ''}`}>
            <div className={styles.statusDot} />
            {isConnected ? '已连接' : '未连接'}
          </div>
        </div>
      </div>

      <div className={styles.kpiRow}>
        {workflowKpis.map(({ label, value, icon: Icon }) => (
          <div key={label} className={styles.kpiCard}>
            <Icon size={16} />
            <div>
              <span className={styles.kpiLabel}>{label}</span>
              <strong className={styles.kpiValue}>{value}</strong>
            </div>
          </div>
        ))}
      </div>

      <div className={styles.main}>
        <div className={styles.canvasSection}>
          <WorkflowCanvas agents={AGENTS} agentStatuses={agentStatuses} />

          <div className={styles.eventLog}>
            <div className={styles.eventLogHeader}>
              <RefreshCw size={14} />
              <span>事件流</span>
            </div>
            <div className={styles.eventList}>
              {events.slice(-5).map((event, i) => (
                <div key={i} className={`${styles.eventItem} ${styles[event.type.replace('_', '-')]}`}>
                  <span className={styles.eventType}>{event.type}</span>
                   <span className={styles.eventAgent}>{event.data?.agent || event.data?.sku || '系统'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className={styles.sidePanel}>
          <StateInspector agentStatuses={agentStatuses} result={workflowResult} />
          <AgentChatPanel events={events} />
        </div>
      </div>
    </div>
  )
}
