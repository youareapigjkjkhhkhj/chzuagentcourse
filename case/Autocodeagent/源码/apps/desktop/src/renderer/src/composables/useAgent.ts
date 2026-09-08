/**
 * 对话状态与流式事件订阅（AGENTS §18：事件驱动，禁止轮询）。
 * P1：tool_start / tool_result 驱动 Tool Trace 卡片；
 * permission_request 挂起权限询问，permission.resolve 回灌决策。
 * P2：diff_ready 驱动右栏审阅面板；plan 静态渲染计划块。
 */
import { onMounted, onUnmounted, ref } from 'vue';
import type { ChatMessage, NormalizedUsage, StreamEvent, TodoItem } from '@agentbuddy/shared';
import { agent } from '../api/bridge';

export interface PendingPermission {
  requestId: string;
  callId: string;
  name: string;
  risk: string;
  detail: string;
}

/** P4：todo_write 任务清单（模块级共享：侧栏计划面板与对话视图同源；plan 事件实时更新，回放从 session.todos 恢复） */
export const planTodos = ref<TodoItem[]>([]);

export function useAgent() {
  const messages = ref<ChatMessage[]>([]);
  const busy = ref(false);
  /** 思考等待态：发送后等首字 / 工具执行完等下一轮（主流 Agent 同款“思考中”指示） */
  const thinking = ref(false);
  const error = ref('');
  /** P1 2.3：非致命提醒（如 MCP 工具超额丢弃）——琥珀横幅，可手动关闭，不打断回合 */
  const notice = ref('');
  const lastUsage = ref<NormalizedUsage | null>(null);
  const sessionId = ref<string | null>(null);
  const pendingPermission = ref<PendingPermission | null>(null);
  /** P2：最新一次落盘变更信号（驱动右栏自动打开） */
  const diffSignal = ref<{ callId: string; changeId: string } | null>(null);
  /** 正在流式输出的 assistant 消息 id：仅 token 到达期间有效，工具执行期清空（光标不挂在气泡上假卡） */
  const streamingId = ref<string | null>(null);
  let unsubscribe: (() => void) | null = null;

  function onEvent(event: StreamEvent): void {
    if (event.type === 'mcp') return; // P5：连接器状态广播（无 sessionId），由管理页 / 输入卡自行订阅
    if (event.type === 'nav') return; // 应用菜单导航广播（无 sessionId），由 App.vue 全局订阅路由
    if (event.sessionId !== sessionId.value) return;

    if (event.type === 'token') {
      thinking.value = false;
      const msg = messages.value.find((m) => m.id === event.messageId);
      if (msg) msg.content += event.delta;
      return;
    }
    if (event.type === 'tool_start') {
      thinking.value = false;
      streamingId.value = null; // 模型本轮输出已结束 → 收掉流式光标，工具卡自带「执行中」指示
      if (!messages.value.some((m) => m.id === event.callId)) {
        messages.value.push({
          id: event.callId,
          role: 'tool',
          content: '',
          createdAt: Date.now(),
          toolCallId: event.callId,
          toolName: event.name,
          toolArgs: event.argsSummary,
        });
      }
      return;
    }
    if (event.type === 'tool_result') {
      const msg = messages.value.find((m) => m.id === event.callId);
      if (msg) {
        msg.content = event.summary;
        msg.toolOk = event.ok;
        msg.toolMs = event.ms;
      }
      thinking.value = true; // 工具完成 → 模型继续思考下一轮
      return;
    }
    if (event.type === 'permission_request') {
      // 模型本轮输出已停顿在工具调用上（等用户决策），收掉上条气泡的流式尾迹/光标，避免「显示不全有阴影」
      streamingId.value = null;
      pendingPermission.value = {
        requestId: event.requestId,
        callId: event.callId,
        name: event.name,
        risk: event.risk,
        detail: event.detail,
      };
      return;
    }
    if (event.type === 'diff_ready') {
      const msg = messages.value.find((m) => m.id === event.callId);
      if (msg) msg.toolChangeId = event.changeId; // 回放时从落盘消息恢复也可，双保险
      diffSignal.value = { callId: event.callId, changeId: event.changeId };
      return;
    }
    if (event.type === 'plan') {
      planTodos.value = event.todos;
      return;
    }
    // P1 2.3：notice / title 必须显式早退——落到末尾 fallback 会被当 error 处理（busy=false 破坏回合态）
    if (event.type === 'notice') {
      notice.value = event.message;
      return;
    }
    if (event.type === 'title') return; // 标题更新由 App.vue 全局订阅刷新侧栏，本视图无需处理
    if (event.type === 'done') {
      busy.value = false;
      thinking.value = false;
      lastUsage.value = event.usage;
      streamingId.value = null;
      return;
    }
    if (event.type === 'interrupted') {
      busy.value = false;
      thinking.value = false;
      streamingId.value = null;
      return;
    }
    busy.value = false;
    thinking.value = false;
    streamingId.value = null;
    error.value = event.message;
  }

  async function openSession(id: string): Promise<void> {
    sessionId.value = id;
    error.value = '';
    notice.value = '';
    thinking.value = false;
    pendingPermission.value = null;
    diffSignal.value = null;
    planTodos.value = [];
    const res = await agent().session.get(id);
    if (res.ok && res.data) {
      messages.value = res.data.messages;
      planTodos.value = res.data.todos ?? []; // P4：回放恢复 Checklist 勾选状态
    }
  }

  async function send(text: string, skillName?: string): Promise<void> {
    if (!sessionId.value || busy.value || !text.trim()) return;
    error.value = '';
    notice.value = '';
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text.trim(),
      createdAt: Date.now(),
    };
    messages.value.push(userMessage);
    busy.value = true;
    thinking.value = true; // 发送即进入思考等待态，首字到达后自动消失
    const res = await agent().agent.ask({ sessionId: sessionId.value, message: userMessage.content, skillName });
    if (!res.ok) {
      busy.value = false;
      error.value = res.error ?? '发送失败';
    }
  }

  async function stop(): Promise<void> {
    if (!sessionId.value) return;
    pendingPermission.value = null;
    await agent().agent.abort(sessionId.value);
  }

  async function resolvePermission(allow: boolean, remember: boolean): Promise<void> {
    const pending = pendingPermission.value;
    if (!pending) return;
    pendingPermission.value = null;
    await agent().permission.resolve({ requestId: pending.requestId, allow, remember });
  }

  /** 流开始：Main 首个 token 事件前，先插入空的 assistant 占位气泡 */
  function ensureStreamingBubble(messageId: string): void {
    if (streamingId.value === messageId) return;
    streamingId.value = messageId;
    if (!messages.value.some((m) => m.id === messageId)) {
      messages.value.push({ id: messageId, role: 'assistant', content: '', createdAt: Date.now() });
    }
  }

  function onEventWrapped(event: StreamEvent): void {
    if (event.type === 'token') ensureStreamingBubble(event.messageId);
    onEvent(event);
  }

  onMounted(() => {
    unsubscribe = agent().onStream(onEventWrapped);
  });
  onUnmounted(() => {
    unsubscribe?.();
  });

  return {
    messages, busy, thinking, error, notice, lastUsage, sessionId,
    pendingPermission, diffSignal, todos: planTodos, streamingId,
    openSession, send, stop, resolvePermission,
  };
}
