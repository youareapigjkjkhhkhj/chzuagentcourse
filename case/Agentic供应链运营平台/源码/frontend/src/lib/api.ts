const API_BASE = '/api'

export async function fetchDashboardKPIs() {
  const res = await fetch(`${API_BASE}/dashboard/kpis`)
  return res.json()
}

export async function fetchInventory(sku?: string) {
  const url = sku ? `${API_BASE}/inventory/${sku}` : `${API_BASE}/inventory`
  const res = await fetch(url)
  return res.json()
}

export async function fetchRisks() {
  const res = await fetch(`${API_BASE}/risks`)
  return res.json()
}

export async function fetchProducts() {
  const res = await fetch(`${API_BASE}/products`)
  return res.json()
}

export async function fetchVendors() {
  const res = await fetch(`${API_BASE}/vendors`)
  return res.json()
}

export async function fetchControlTower() {
  const res = await fetch(`${API_BASE}/platform/control-tower`)
  return res.json()
}

export async function fetchScenarios() {
  const res = await fetch(`${API_BASE}/platform/scenarios`)
  return res.json()
}

export async function fetchGovernance() {
  const res = await fetch(`${API_BASE}/platform/governance`)
  return res.json()
}

export async function analyzeSKU(sku: string) {
  const res = await fetch(`${API_BASE}/analyze/${sku}`, { method: 'POST' })
  return res.json()
}

export async function runNegotiation(payload: {
  vendor_id: number
  sku: string
  quantity: number
  initial_message?: string
}) {
  const res = await fetch(`${API_BASE}/negotiate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return res.json()
}

export function createWorkflowSocket(sessionId: string) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return new WebSocket(`${protocol}//${window.location.host}/ws/workflow/${sessionId}`)
}
