<template>
  <div class="qa-chat">
    <div class="chat-container">
      <!-- 聊天头部 -->
      <div class="chat-header">
        <div class="header-left">
          <div class="ai-avatar">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" fill="currentColor"/>
            </svg>
          </div>
          <div class="header-info">
            <h2>智能问答助手</h2>
            <span class="status">
              <span class="status-dot"></span>
              在线
            </span>
          </div>
        </div>
        <div class="header-actions">
          <button class="action-btn" @click="clearChat" title="清空对话">
            <el-icon><Delete /></el-icon>
          </button>
        </div>
      </div>
      
      <!-- 聊天消息列表 -->
      <div class="chat-messages" ref="messagesContainer">
        <!-- 欢迎消息 -->
        <div v-if="qaStore.chatMessages.length === 0" class="welcome-message">
          <div class="welcome-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" fill="currentColor"/>
            </svg>
          </div>
          <h3>你好！我是AI助手</h3>
          <p>我可以帮你回答关于运维知识的问题，试试问我一些问题吧！</p>
          <div class="suggestion-chips">
            <button 
              v-for="suggestion in suggestions" 
              :key="suggestion"
              class="suggestion-chip"
              @click="askSuggestion(suggestion)"
            >
              {{ suggestion }}
            </button>
          </div>
        </div>
        
        <!-- 消息列表 -->
        <div
          v-for="message in qaStore.chatMessages"
          :key="message.id"
          :class="['message', message.role]"
        >
          <div class="message-avatar">
            <el-avatar v-if="message.role === 'user'" :size="36" class="user-avatar">
              {{ authStore.user?.username?.charAt(0)?.toUpperCase() }}
            </el-avatar>
            <div v-else class="ai-avatar-small">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" fill="currentColor"/>
              </svg>
            </div>
          </div>
          
          <div class="message-content">
            <div class="message-header">
              <span class="sender-name">{{ message.role === 'user' ? '你' : 'AI助手' }}</span>
              <span class="message-time">{{ formatTime(message.timestamp) }}</span>
            </div>
            
            <div class="message-text" v-html="renderMarkdown(message.content)" />
            
            <!-- 来源引用 -->
            <div v-if="message.sources && message.sources.length > 0" class="message-sources">
              <div class="sources-header">
                <el-icon><Document /></el-icon>
                <span>参考来源 ({{ message.sources.length }})</span>
              </div>
              <div class="sources-list">
                <a
                  v-for="(source, index) in message.sources"
                  :key="index"
                  :href="`/documents/${source.document_id}`"
                  target="_blank"
                  class="source-item"
                >
                  <span class="source-id">#{{ source.document_id }}</span>
                  <span class="source-score">{{ (source.score * 100).toFixed(0) }}% 匹配</span>
                </a>
              </div>
            </div>
            
            <!-- 消息操作 -->
            <div v-if="message.role === 'assistant' && message.record_id" class="message-actions">
              <button 
                :class="['action-btn', { active: message.feedback === 'helpful' }]"
                @click="submitFeedback(message.record_id!, 'helpful')"
                title="有帮助"
              >
                <el-icon><CircleCheck /></el-icon>
                <span>有帮助</span>
              </button>
              <button 
                :class="['action-btn', { active: message.feedback === 'not_helpful' }]"
                @click="submitFeedback(message.record_id!, 'not_helpful')"
                title="无帮助"
              >
                <el-icon><CircleClose /></el-icon>
                <span>无帮助</span>
              </button>
              <span v-if="message.response_time" class="response-time">
                {{ message.response_time }}ms
              </span>
            </div>
          </div>
        </div>
        
        <!-- 加载中 -->
        <div v-if="qaStore.loading" class="message assistant">
          <div class="message-avatar">
            <div class="ai-avatar-small">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" fill="currentColor"/>
              </svg>
            </div>
          </div>
          <div class="message-content">
            <div class="typing-indicator">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 输入框 -->
      <div class="chat-input">
        <div class="input-wrapper">
          <textarea
            ref="inputRef"
            v-model="inputText"
            placeholder="输入你的问题..."
            rows="1"
            @keydown.enter.exact.prevent="sendMessage"
            @input="autoResize"
          ></textarea>
          <button 
            class="send-btn" 
            @click="sendMessage"
            :disabled="!inputText.trim() || qaStore.loading"
          >
            <el-icon v-if="!qaStore.loading"><Promotion /></el-icon>
            <el-icon v-else class="spinning"><Loading /></el-icon>
          </button>
        </div>
        <div class="input-hint">
          按 Enter 发送，Shift + Enter 换行
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { useQAStore } from '@/stores/qa'
import { useAuthStore } from '@/stores/auth'
import MarkdownIt from 'markdown-it'
import { 
  Delete, 
  Document, 
  CircleCheck, 
  CircleClose, 
  Promotion, 
  Loading 
} from '@element-plus/icons-vue'

const qaStore = useQAStore()
const authStore = useAuthStore()

const inputText = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const messagesContainer = ref<HTMLElement | null>(null)

const suggestions = [
  '如何重启Nginx服务？',
  'MySQL主从配置步骤',
  'Docker容器日志查看方法',
  'Linux系统内存排查'
]

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true
})

const renderMarkdown = (text: string) => {
  return md.render(text)
}

const formatTime = (timestamp: string) => {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const autoResize = () => {
  if (inputRef.value) {
    inputRef.value.style.height = 'auto'
    inputRef.value.style.height = Math.min(inputRef.value.scrollHeight, 120) + 'px'
  }
}

const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

const sendMessage = async () => {
  const question = inputText.value.trim()
  if (!question || qaStore.loading) return
  
  inputText.value = ''
  if (inputRef.value) {
    inputRef.value.style.height = 'auto'
  }
  
  await qaStore.askQuestion(question)
  await scrollToBottom()
}

const askSuggestion = (suggestion: string) => {
  inputText.value = suggestion
  sendMessage()
}

const clearChat = () => {
  qaStore.clearChat()
}

const submitFeedback = async (recordId: number, feedback: string) => {
  try {
    await qaStore.submitFeedback(recordId, feedback)
    const message = qaStore.chatMessages.find(m => m.record_id === recordId)
    if (message) {
      message.feedback = feedback as any
    }
  } catch (error) {
    console.error('Failed to submit feedback:', error)
  }
}

onMounted(() => {
  scrollToBottom()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.qa-chat {
  height: calc(100vh - 100px);
  padding: $space-4;
}

.chat-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: $bg-card;
  border: 1px solid $border-color;
  border-radius: $radius-xl;
  overflow: hidden;
}

// 聊天头部
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $space-4 $space-5;
  border-bottom: 1px solid $border-color;
  background: $dark-800;
}

.header-left {
  display: flex;
  align-items: center;
  gap: $space-3;
}

.ai-avatar {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: $gradient-primary;
  border-radius: $radius-md;
  color: white;
  
  svg {
    width: 24px;
    height: 24px;
  }
}

.header-info {
  h2 {
    font-size: $font-size-base;
    font-weight: 600;
    color: $text-primary;
    margin: 0;
  }
}

.status {
  display: flex;
  align-items: center;
  gap: $space-1;
  font-size: $font-size-xs;
  color: $text-muted;
}

.status-dot {
  width: 6px;
  height: 6px;
  background: $success-color;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

.header-actions {
  display: flex;
  gap: $space-2;
}

.action-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid $border-color;
  border-radius: $radius-md;
  color: $text-secondary;
  cursor: pointer;
  transition: all $transition-fast;
  
  &:hover {
    background: rgba(255, 255, 255, 0.05);
    border-color: $border-color-hover;
    color: $text-primary;
  }
}

// 消息列表
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: $space-5;
  display: flex;
  flex-direction: column;
  gap: $space-5;
}

// 欢迎消息
.welcome-message {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: $space-8;
}

.welcome-icon {
  width: 80px;
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: $gradient-primary;
  border-radius: $radius-xl;
  color: white;
  margin-bottom: $space-5;
  
  svg {
    width: 48px;
    height: 48px;
  }
}

.welcome-message h3 {
  font-size: $font-size-xl;
  font-weight: 600;
  color: $text-primary;
  margin: 0 0 $space-2 0;
}

.welcome-message p {
  font-size: $font-size-base;
  color: $text-secondary;
  margin: 0 0 $space-6 0;
}

.suggestion-chips {
  display: flex;
  flex-wrap: wrap;
  gap: $space-2;
  justify-content: center;
}

.suggestion-chip {
  padding: $space-2 $space-4;
  background: $dark-700;
  border: 1px solid $border-color;
  border-radius: $radius-full;
  color: $text-secondary;
  font-size: $font-size-sm;
  cursor: pointer;
  transition: all $transition-fast;
  
  &:hover {
    background: $dark-600;
    border-color: $border-color-hover;
    color: $text-primary;
  }
}

// 消息样式
.message {
  display: flex;
  gap: $space-3;
  max-width: 80%;
  
  &.user {
    margin-left: auto;
    flex-direction: row-reverse;
    
    .message-content {
      background: $gradient-primary;
      border-radius: $radius-lg $radius-lg $radius-sm $radius-lg;
    }
    
    .message-header {
      flex-direction: row-reverse;
    }
    
    .sender-name, .message-time {
      color: rgba(255, 255, 255, 0.8);
    }
    
    .message-text {
      color: white;
      
      :deep(p) {
        color: white;
      }
      
      :deep(code) {
        background: rgba(255, 255, 255, 0.2);
        color: white;
      }
      
      :deep(pre) {
        background: rgba(0, 0, 0, 0.3);
        
        code {
          background: transparent;
          color: white;
        }
      }
    }
  }
  
  &.assistant {
    .message-content {
      background: $dark-700;
      border-radius: $radius-lg $radius-lg $radius-lg $radius-sm;
    }
  }
}

.message-avatar {
  flex-shrink: 0;
}

.user-avatar {
  background: $gradient-primary !important;
  font-weight: 600;
}

.ai-avatar-small {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: $gradient-primary;
  border-radius: $radius-md;
  color: white;
  
  svg {
    width: 20px;
    height: 20px;
  }
}

.message-content {
  flex: 1;
  padding: $space-4;
}

.message-header {
  display: flex;
  align-items: center;
  gap: $space-2;
  margin-bottom: $space-2;
}

.sender-name {
  font-size: $font-size-sm;
  font-weight: 600;
  color: $text-primary;
}

.message-time {
  font-size: $font-size-xs;
  color: $text-muted;
}

.message-text {
  line-height: 1.7;
  color: $text-primary;
  
  :deep(p) {
    margin: 0 0 $space-3 0;
    color: $text-primary;
    
    &:last-child {
      margin-bottom: 0;
    }
  }
  
  :deep(code) {
    font-family: $font-mono;
    background: $dark-600;
    padding: 2px 6px;
    border-radius: $radius-sm;
    font-size: 0.9em;
    color: $primary-light;
  }
  
  :deep(pre) {
    background: $dark-800;
    padding: $space-4;
    border-radius: $radius-md;
    overflow-x: auto;
    border: 1px solid $border-color;
    margin: $space-3 0;
    
    code {
      background: transparent;
      padding: 0;
      color: $text-primary;
    }
  }
  
  :deep(ul), :deep(ol) {
    margin: $space-3 0;
    padding-left: $space-5;
    
    li {
      margin: $space-1 0;
    }
  }
  
  :deep(blockquote) {
    border-left: 3px solid $primary-color;
    margin: $space-3 0;
    padding: $space-3 $space-4;
    background: rgba(14, 165, 233, 0.1);
    border-radius: 0 $radius-md $radius-md 0;
  }
}

// 来源引用
.message-sources {
  margin-top: $space-4;
  padding-top: $space-4;
  border-top: 1px solid $border-color;
}

.sources-header {
  display: flex;
  align-items: center;
  gap: $space-2;
  font-size: $font-size-sm;
  color: $text-secondary;
  margin-bottom: $space-2;
}

.sources-list {
  display: flex;
  flex-wrap: wrap;
  gap: $space-2;
}

.source-item {
  display: flex;
  align-items: center;
  gap: $space-2;
  padding: $space-1 $space-3;
  background: rgba(14, 165, 233, 0.1);
  border: 1px solid rgba(14, 165, 233, 0.2);
  border-radius: $radius-full;
  font-size: $font-size-xs;
  text-decoration: none;
  transition: all $transition-fast;
  
  &:hover {
    background: rgba(14, 165, 233, 0.2);
    border-color: $primary-color;
  }
}

.source-id {
  color: $primary-light;
  font-weight: 500;
}

.source-score {
  color: $text-muted;
}

// 消息操作
.message-actions {
  display: flex;
  align-items: center;
  gap: $space-2;
  margin-top: $space-3;
  padding-top: $space-3;
  border-top: 1px solid $border-color;
  
  .action-btn {
    display: flex;
    align-items: center;
    gap: $space-1;
    padding: $space-1 $space-3;
    background: transparent;
    border: 1px solid $border-color;
    border-radius: $radius-full;
    color: $text-muted;
    font-size: $font-size-xs;
    cursor: pointer;
    transition: all $transition-fast;
    
    &:hover {
      background: rgba(255, 255, 255, 0.05);
      border-color: $border-color-hover;
      color: $text-primary;
    }
    
    &.active {
      background: rgba(16, 185, 129, 0.1);
      border-color: $success-color;
      color: $success-light;
    }
    
    span {
      display: none;
    }
    
    @media (min-width: 640px) {
      span {
        display: inline;
      }
    }
  }
}

.response-time {
  font-size: $font-size-xs;
  color: $text-muted;
  margin-left: auto;
}

// 打字指示器
.typing-indicator {
  display: flex;
  gap: $space-1;
  padding: $space-2 0;
  
  span {
    width: 8px;
    height: 8px;
    background: $text-muted;
    border-radius: 50%;
    animation: typing 1.4s infinite ease-in-out;
    
    &:nth-child(1) { animation-delay: 0s; }
    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
}

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-8px); opacity: 1; }
}

// 输入框
.chat-input {
  padding: $space-4 $space-5;
  border-top: 1px solid $border-color;
  background: $dark-800;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: $space-3;
  padding: $space-3 $space-4;
  background: $dark-700;
  border: 1px solid $border-color;
  border-radius: $radius-lg;
  transition: all $transition-fast;
  
  &:focus-within {
    border-color: $primary-color;
    box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.1);
  }
  
  textarea {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: $text-primary;
    font-size: $font-size-base;
    font-family: inherit;
    resize: none;
    max-height: 120px;
    line-height: 1.5;
    
    &::placeholder {
      color: $text-muted;
    }
  }
}

.send-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: $gradient-primary;
  border: none;
  border-radius: $radius-md;
  color: white;
  cursor: pointer;
  transition: all $transition-fast;
  flex-shrink: 0;
  
  &:hover:not(:disabled) {
    transform: scale(1.05);
    box-shadow: $shadow-glow;
  }
  
  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  .spinning {
    animation: spin 1s linear infinite;
  }
}

.input-hint {
  text-align: center;
  font-size: $font-size-xs;
  color: $text-muted;
  margin-top: $space-2;
}

// 响应式
@media (max-width: 640px) {
  .qa-chat {
    padding: 0;
    height: calc(100vh - 60px);
  }
  
  .chat-container {
    border-radius: 0;
    border: none;
  }
  
  .message {
    max-width: 90%;
  }
}
</style>