import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout/Layout'
import { Dashboard } from './pages/Dashboard'
import { WorkflowVisualizer } from './pages/WorkflowVisualizer'
import { VendorNegotiation } from './pages/VendorNegotiation'
import { ScenarioLab } from './pages/ScenarioLab'
import { GovernanceCenter } from './pages/GovernanceCenter'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="scenarios" element={<ScenarioLab />} />
          <Route path="workflow" element={<WorkflowVisualizer />} />
          <Route path="governance" element={<GovernanceCenter />} />
          <Route path="negotiation" element={<VendorNegotiation />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
