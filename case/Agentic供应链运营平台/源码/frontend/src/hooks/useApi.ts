import { useState, useEffect, useCallback } from 'react'
import { fetchDashboardKPIs, fetchRisks, fetchInventory, fetchProducts } from '../lib/api'

interface KPIData {
  total_skus: number
  active_risks: number
  pending_pos: number
  pending_po_value: number
}

interface RiskAlert {
  sku: string
  name: string
  risk_status: 'critical' | 'low' | 'excess' | 'normal'
  total_quantity: number
  reorder_point: number
}

interface InventoryItem {
  sku: string
  product_name: string
  warehouse_name: string
  quantity: number
}

interface Product {
  sku: string
  name: string
  category: string
}

export function useDashboard() {
  const [kpis, setKpis] = useState<KPIData | null>(null)
  const [risks, setRisks] = useState<RiskAlert[]>([])
  const [inventory, setInventory] = useState<InventoryItem[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [kpisData, risksData, inventoryData, productsData] = await Promise.all([
        fetchDashboardKPIs(),
        fetchRisks(),
        fetchInventory(),
        fetchProducts(),
      ])
      setKpis(kpisData)
      setRisks(risksData)
      setInventory(inventoryData)
      setProducts(productsData)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { kpis, risks, inventory, products, loading, error, refresh }
}
