import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import styles from './TrendCharts.module.css'

const generateMockData = () => {
  const data = []
  for (let i = 30; i >= 0; i--) {
    const date = new Date()
    date.setDate(date.getDate() - i)
    data.push({
      date: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      forecast: Math.floor(Math.random() * 50 + 30),
      actual: Math.floor(Math.random() * 50 + 30),
    })
  }
  return data
}

export function TrendCharts() {
  const data = generateMockData()

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>需求预测 vs 实际销售</h3>
      <div className={styles.chartWrapper}>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data} margin={{ top: 20, right: 30, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="date"
              stroke="#6B7280"
              fontSize={12}
              tickLine={false}
            />
            <YAxis
              stroke="#6B7280"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                background: '#1F2937',
                border: '1px solid #374151',
                borderRadius: '8px',
                fontSize: '12px',
              }}
              labelStyle={{ color: '#F9FAFB' }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="forecast"
              stroke="#3B82F6"
              strokeWidth={2}
              dot={false}
              name="预测"
            />
            <Line
              type="monotone"
              dataKey="actual"
              stroke="#10B981"
              strokeWidth={2}
              dot={false}
              name="实际"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
