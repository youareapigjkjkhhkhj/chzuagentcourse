import { useState, useEffect } from 'react'
import { NegotiationChat } from '../components/Negotiation/NegotiationChat'
import { VendorCard } from '../components/Negotiation/VendorCard'
import { TermsTimeline } from '../components/Negotiation/TermsTimeline'
import { fetchVendors, fetchProducts, runNegotiation } from '../lib/api'
import { BadgeDollarSign, Clock3, MessageSquareText, Percent } from 'lucide-react'
import styles from './VendorNegotiation.module.css'

interface Vendor {
  vendor_id: number
  name: string
  lead_time_days: number
  min_order_value: number
}

interface Message {
  id: string
  type: 'user' | 'vendor' | 'system'
  content: string
  timestamp: Date
}

interface TermSnapshot {
  price: number
  discount: number
  timestamp: Date
}

export function VendorNegotiation() {
  const [vendors, setVendors] = useState<Vendor[]>([])
  const [selectedVendor, setSelectedVendor] = useState<Vendor | null>(null)
  const [selectedSKU, setSelectedSKU] = useState('SKU-001')
  const [messages, setMessages] = useState<Message[]>([])
  const [termHistory, setTermHistory] = useState<TermSnapshot[]>([])
  const [isNegotiating, setIsNegotiating] = useState(false)
  const [strategyNote, setStrategyNote] = useState(
    '优先考虑总到岸成本，保护交货周期，推动对标基准的定价。'
  )

  useEffect(() => {
    fetchVendors().then((data) => {
      setVendors(data)
      if (data.length > 0) {
        setSelectedVendor(data[0])
      }
    })
    fetchProducts().then((data) => {
      if (data.length > 0) {
        setSelectedSKU(data[0].sku)
      }
    })
  }, [])

  const buildTranscriptMessages = (transcript: Array<{
    speaker: string
    message: string
  }>) => transcript.map((entry, index) => ({
    id: `${index}-${entry.speaker}`,
    type: entry.speaker === 'buyer' ? 'user' : entry.speaker === 'vendor' ? 'vendor' : 'system',
    content: entry.message,
    timestamp: new Date(),
  })) as Message[]

  const handleStartNegotiation = async () => {
    if (!selectedVendor) return

    setIsNegotiating(true)
    try {
      const result = await runNegotiation({
        vendor_id: selectedVendor.vendor_id,
        sku: selectedSKU,
        quantity: 250,
        initial_message: strategyNote,
      })

      const transcriptMessages = buildTranscriptMessages(result.transcript || [])
      setMessages([
        {
          id: 'system-start',
          type: 'system',
          content: `与 ${selectedVendor.name} 的实时谈判已完成。`,
          timestamp: new Date(),
        },
        ...transcriptMessages,
        {
          id: 'system-summary',
          type: 'system',
          content: result.result?.negotiation_summary || '谈判已结束。',
          timestamp: new Date(),
        },
      ])

      const transcript = result.transcript || []
      const history = transcript
        .filter((entry: any) => typeof entry.offer_price === 'number')
        .map((entry: any, index: number) => ({
          price: entry.offer_price,
          discount: entry.discount_percent || 0,
          timestamp: new Date(Date.now() + index * 60000),
        }))
      setTermHistory(history)
    } finally {
      setIsNegotiating(false)
    }
  }

  const handleAccept = () => {
    const finalTerms = termHistory[termHistory.length - 1]
    setMessages((prev) => [
      ...prev,
      {
        id: (Date.now() + 1).toString(),
        type: 'system',
        content: `交易达成！最终价格：$${finalTerms.price.toFixed(2)}，折扣 ${finalTerms.discount.toFixed(1)}%。`,
        timestamp: new Date(),
      },
    ])
    setIsNegotiating(false)
  }

  const latestTerms = termHistory[termHistory.length - 1]
  const initialTerms = termHistory[0]
  const negotiationKpis = [
    {
      label: '交货周期',
      value: selectedVendor ? `${selectedVendor.lead_time_days} 天` : '待定',
      icon: Clock3,
    },
    {
      label: '最小起订量',
      value: selectedVendor ? `$${selectedVendor.min_order_value.toLocaleString()}` : '待定',
      icon: BadgeDollarSign,
    },
    {
      label: '当前价格',
      value: latestTerms ? `$${latestTerms.price.toFixed(2)}` : '等待首轮报价',
      icon: MessageSquareText,
    },
    {
      label: '折扣收益',
      value:
        latestTerms && initialTerms
          ? `+${(latestTerms.discount - initialTerms.discount).toFixed(1)}%`
          : '0.0%',
      icon: Percent,
    },
  ]

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>供应商谈判工作台</h1>
          <p className={styles.subtitle}>实时采购策略、对话生成与后端智能体链的价格让步</p>
        </div>
      </div>

      <div className={styles.kpiRow}>
        {negotiationKpis.map(({ label, value, icon: Icon }) => (
          <div key={label} className={styles.kpiCard}>
            <Icon size={16} />
            <div>
              <span className={styles.kpiLabel}>{label}</span>
              <strong className={styles.kpiValue}>{value}</strong>
            </div>
          </div>
        ))}
      </div>

      <div className={styles.strategyPanel}>
        <label className={styles.strategyLabel}>谈判简报</label>
        <textarea
          className={styles.strategyInput}
          value={strategyNote}
          onChange={(e) => setStrategyNote(e.target.value)}
          disabled={isNegotiating}
        />
      </div>

      <div className={styles.main}>
        <div className={styles.leftPanel}>
          <div className={styles.controls}>
            <select
              value={selectedVendor?.vendor_id || ''}
              onChange={(e) => {
                const vendor = vendors.find((v) => v.vendor_id === Number(e.target.value))
                setSelectedVendor(vendor || null)
              }}
              className={styles.select}
              disabled={isNegotiating}
            >
              {vendors.map((v) => (
                <option key={v.vendor_id} value={v.vendor_id}>
                  {v.name}
                </option>
              ))}
            </select>
            <select
              value={selectedSKU}
              onChange={(e) => setSelectedSKU(e.target.value)}
              className={styles.select}
              disabled={isNegotiating}
            >
              <option value="SKU-001">SKU-001 - 工业轴承</option>
              <option value="SKU-002">SKU-002 - 液压泵</option>
              <option value="SKU-003">SKU-003 - 钢板</option>
            </select>
          </div>

          <VendorCard vendor={selectedVendor} />

          <TermsTimeline history={termHistory} />
        </div>

        <div className={styles.chatPanel}>
          <NegotiationChat
            messages={messages}
            onSend={() => {}}
            onAccept={handleAccept}
            onAbort={() => {
              setIsNegotiating(false)
              setMessages([])
              setTermHistory([])
            }}
            isNegotiating={false}
          />
        </div>
      </div>

      {!isNegotiating && messages.length === 0 && (
        <button className={styles.startButton} onClick={handleStartNegotiation}>
          开始与 {selectedVendor?.name} 的谈判
        </button>
      )}
    </div>
  )
}
