import { useState } from 'react'
import { Send, Check, X } from 'lucide-react'
import styles from './NegotiationChat.module.css'

interface Message {
  id: string
  type: 'user' | 'vendor' | 'system'
  content: string
  timestamp: Date
}

interface NegotiationChatProps {
  messages: Message[]
  onSend: (content: string) => void
  onAccept: () => void
  onAbort: () => void
  isNegotiating: boolean
}

export function NegotiationChat({ messages, onSend, onAccept, onAbort, isNegotiating }: NegotiationChatProps) {
  const [input, setInput] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (input.trim()) {
      onSend(input)
      setInput('')
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.vendorAvatar}>V</div>
        <div className={styles.headerInfo}>
          <span className={styles.vendorName}>供应商代表</span>
          <span className={styles.status}>
            {isNegotiating ? '在线' : '等待谈判'}
          </span>
        </div>
      </div>

      <div className={styles.messages}>
        {messages.length === 0 ? (
          <div className={styles.empty}>
            <p>开始谈判即可与供应商进行对话。</p>
          </div>
        ) : (
          messages.map((message) => (
            <div key={message.id} className={`${styles.message} ${styles[message.type]}`}>
              {message.type === 'system' ? (
                <div className={styles.systemMessage}>{message.content}</div>
              ) : (
                <>
                  <div className={styles.bubble}>{message.content}</div>
                  <span className={styles.time}>
                    {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </>
              )}
            </div>
          ))
        )}
      </div>

      {isNegotiating && (
        <div className={styles.actions}>
          <button className={styles.acceptButton} onClick={onAccept}>
            <Check size={18} />
            接受交易
          </button>
          <button className={styles.abortButton} onClick={onAbort}>
            <X size={18} />
            终止
          </button>
        </div>
      )}

      {isNegotiating && (
        <form className={styles.inputArea} onSubmit={handleSubmit}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入您的消息..."
            className={styles.input}
          />
          <button type="submit" className={styles.sendButton} disabled={!input.trim()}>
            <Send size={18} />
          </button>
        </form>
      )}
    </div>
  )
}
