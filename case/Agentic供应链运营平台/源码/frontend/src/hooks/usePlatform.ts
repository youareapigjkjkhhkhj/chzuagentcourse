import { useEffect, useState } from 'react'
import { fetchControlTower, fetchGovernance, fetchScenarios } from '../lib/api'

export interface ControlTowerSnapshot {
  headline: {
    platform_name: string
    autonomy_score: number
    resilience_score: number
    network_health: string
    avg_vendor_lead_time_days: number
  }
  kpis: {
    total_skus: number
    active_risks: number
    pending_pos: number
    pending_po_value: number
  }
  priority_recommendations: Array<{
    title: string
    impact: string
    action: string
    confidence: number
  }>
  replenishment_candidates: Array<{
    sku: string
    name: string
    category: string
    available_units: number
    reorder_point: number
    recommended_buy: number
    inventory_health: number
  }>
  warehouse_network: Array<{
    warehouse: string
    utilization_band: 'low' | 'medium' | 'high'
    units: number
  }>
  risk_digest: Array<{
    sku: string
    name: string
    risk_status: 'critical' | 'low' | 'excess' | 'normal'
    total_quantity: number
    reorder_point: number
    reorder_quantity: number
  }>
}

export interface ScenarioLabData {
  simulation_window: string
  recommended_playbook: string
  scenarios: Array<{
    id: string
    name: string
    severity: 'medium' | 'high' | 'critical'
    probability: number
    inventory_impact_pct: number
    margin_impact_pct: number
    recommended_response: string
  }>
}

export interface GovernanceHub {
  policy_posture: string
  approval_queues: Array<{
    name: string
    pending: number
    sla: string
    threshold: string
  }>
  guardrails: string[]
  agent_registry: Array<{
    agent: string
    status: 'healthy' | 'watch'
    last_decision: string
    reliability: number
  }>
}

export function usePlatformData<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await loader()
        if (active) {
          setData(result)
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : '加载平台数据失败')
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    load()

    return () => {
      active = false
    }
  }, [loader])

  return { data, loading, error }
}

export function useControlTower() {
  return usePlatformData<ControlTowerSnapshot>(fetchControlTower)
}

export function useScenarioLab() {
  return usePlatformData<ScenarioLabData>(fetchScenarios)
}

export function useGovernanceHub() {
  return usePlatformData<GovernanceHub>(fetchGovernance)
}
