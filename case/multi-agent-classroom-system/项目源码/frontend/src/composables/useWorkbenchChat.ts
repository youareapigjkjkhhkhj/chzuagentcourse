/**
 * 工作台对话（P4-A9~A12 / F4-10~F4-12）。
 *
 * 三条纪律与生成流一致（见 `useGenerationStream`），只是对象从「一次生成」
 * 换成了「一门课的会话」：
 *
 * 1. **消息以服务端为准**。流里收到的那些字只是「它正一个字一个字出现」的样子，
 *    一轮结束（`agent.done`）之后立刻重问一次消息列表 —— 库里那条才是归档，
 *    也才有 `tokens` 与技能清单。
 * 2. **技能卡在跑的时候就得看得见**。`agent.skill` 一到就插一张转圈的卡，
 *    `agent.skill_done` 再把它填成结果或失败 —— 这是 P4-A10 的「禁止静默修改课程」
 *    在界面上的样子：用户永远能看见 Agent 正在动哪一页。
 * 3. **回退是删上下文，不是撤销**。理由在 `chat.py` 里写死了，前端只负责把
 *    服务端那句 `pageNotice`（「课程内容没有跟着回退」）原样说出来。
 */

import { computed, onScopeDispose, ref, watch, type Ref } from 'vue'

import * as api from '@/api'
import type {
  ChatMessageItem,
  SkillCatalogue,
  SkillInfo,
  SkillStatus,
  SlideSource,
} from '@/types/api'

/**
 * 操作卡要画的那几个字段。
 *
 * 两种来路共用一副样子：**跑的时候**是事件流里的帧（`LiveSkill`，带 `args`
 * 与 `why`），**跑完之后**是消息里落库的 `skillCalls`（只有结果）。卡片组件
 * 因此按可选的读 —— 历史消息里那几张卡只是没有「为什么」这一行。
 */
export interface CardView {
  skill: string
  args?: Record<string, unknown>
  why?: string
  status: SkillStatus
  result?: Record<string, unknown> | null
  error?: string
  durationMs?: number
}

/** 流里那张还在跑的操作卡。跑的时候先出现、再填结果，所以它是可变的一条。 */
export interface LiveSkill extends CardView {
  skillId: string
  args: Record<string, unknown>
  why: string
  result: Record<string, unknown> | null
  error: string
  durationMs: number
}

/** 技能名 → 中文名的兜底表。**清单以 `GET /skills` 为准**，它只是首屏没拉到时的退路。 */
const FALLBACK_TITLES: Record<string, string> = {
  revise_outline: '改大纲',
  rewrite_page: '重写某页',
  add_quiz: '加随堂测验',
  add_page: '加一页',
  remove_page: '删一页',
  change_tone: '换语气',
  summarize_material: '讲材料',
}

/** 一帧 `page.rewritten` 的要点：改的是哪一页、是不是删掉了、新的 rev 与出处。 */
export interface PageRewrite {
  pageNo: number
  /** 这一页被删了（`remove_page`）：工作台要把它从选中状态里摘出去。 */
  removed: boolean
  rev: number
  sources: SlideSource[]
}

interface Options {
  /** 某一页被改了：工作台据此刷新预览与大纲树（`page.rewritten`）。 */
  onPageRewritten?: (info: PageRewrite) => void
}

export function useWorkbenchChat(courseId: Ref<string>, options: Options = {}) {
  const messages = ref<ChatMessageItem[]>([])
  const skills = ref<SkillInfo[]>([])
  const maxActions = ref(4)
  /** 正在流式出现的那一条（`messageId` 与已经收到的字）。 */
  const draftId = ref('')
  const draftText = ref('')
  /** 未落库的操作卡：`messageId` → 这一轮调过的技能。 */
  const liveSkills = ref<Record<string, LiveSkill[]>>({})
  /**
   * 刚发出去、还没从消息列表里读回来的那一句。
   *
   * 服务端要落库、前端要再取一次列表，这中间有小半秒 —— 不本地回显的话，
   * 用户按了回车之后会看到输入框清了、屏幕上什么也没多出来。它只活到
   * `load()` 从列表里认出这句话为止（认法就是「内容一模一样」）。
   */
  const pendingUser = ref<{ text: string; refPageNo: number } | null>(null)
  const running = ref(false)
  const connected = ref(false)
  const error = ref('')
  const loaded = ref(false)

  let source: EventSource | null = null

  const titles = computed<Record<string, string>>(() =>
    Object.fromEntries([
      ...Object.entries(FALLBACK_TITLES),
      ...skills.value.map((item) => [item.name, item.title]),
    ]),
  )

  const canSend = computed(() => Boolean(courseId.value))

  // --- 读 ---

  async function load(): Promise<void> {
    const id = courseId.value
    if (!id) {
      messages.value = []
      loaded.value = false
      return
    }
    try {
      const data = await api.fetchChatMessages(id)
      messages.value = data.items
      // 服务端说这一轮在跑：界面按「跑着」渲染，别让刷新页面之后的输入框
      // 误以为可以再发一句（同一会话同一时刻只跑一轮）。
      running.value = data.running
      error.value = ''
      loaded.value = true
      if (
        pendingUser.value &&
        data.items.some(
          (item) => item.role === 'user' && item.content === pendingUser.value?.text,
        )
      ) {
        pendingUser.value = null // 已经能看到它了，本地那份回显可以撤了
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  async function loadSkills(): Promise<void> {
    const id = courseId.value
    if (!id) return
    try {
      const data: SkillCatalogue = await api.fetchSkills(id)
      skills.value = data.items
      maxActions.value = data.maxActions
    } catch {
      // 清单拉不到不影响对话本身：按钮提示退回内置的那份中文名
    }
  }

  // --- 写 ---

  /** 发一句话。本地先把用户那条插进去（乐观渲染），服务端那份回来之后以它为准。 */
  async function send(text: string, refPageNo = 0): Promise<boolean> {
    const id = courseId.value
    const body = text.trim()
    if (!id || !body || running.value) return false
    running.value = true
    error.value = ''
    pendingUser.value = { text: body, refPageNo }
    try {
      const sent = await api.sendChatMessage(id, {
        text: body,
        ...(refPageNo ? { refPageNo } : {}),
      })
      draftId.value = sent.messageId
      draftText.value = ''
      await load()
      return true
    } catch (err) {
      running.value = false
      pendingUser.value = null // 没发出去：本地那条回显跟着撤，别留在屏幕上
      error.value = err instanceof Error ? err.message : String(err)
      return false
    }
  }

  /** 回退到某条消息之前（`messageId` 那条本身也会被丢掉）。 */
  async function rollback(messageId: string): Promise<string> {
    const id = courseId.value
    if (!id) return ''
    try {
      const result = await api.rollbackChat(id, { messageId })
      draftId.value = ''
      draftText.value = ''
      liveSkills.value = {}
      pendingUser.value = null
      await load()
      return result.pageNotice
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      return ''
    }
  }

  // --- 流 ---

  function skillCard(messageId: string, skillId: string): LiveSkill | null {
    return (liveSkills.value[messageId] ?? []).find((card) => card.skillId === skillId) ?? null
  }

  const HANDLERS: Record<string, (payload: Record<string, unknown>) => void> = {
    'agent.delta': (payload) => {
      const messageId = String(payload.messageId ?? '')
      if (messageId && messageId !== draftId.value) {
        draftId.value = messageId
        draftText.value = ''
      }
      draftText.value += String(payload.text ?? '')
    },

    'agent.skill': (payload) => {
      const messageId = String(payload.messageId ?? '')
      const skillId = String(payload.skillId ?? payload.skill ?? '')
      if (!messageId || !skillId) return
      const cards = liveSkills.value[messageId] ?? []
      if (cards.some((card) => card.skillId === skillId)) return
      liveSkills.value = {
        ...liveSkills.value,
        [messageId]: [
          ...cards,
          {
            skillId,
            skill: String(payload.skill ?? ''),
            args: (payload.args ?? {}) as Record<string, unknown>,
            why: String(payload.why ?? ''),
            status: 'running',
            result: null,
            error: '',
            durationMs: 0,
          },
        ],
      }
    },

    'agent.skill_done': (payload) => {
      const messageId = String(payload.messageId ?? '')
      const skillId = String(payload.skillId ?? payload.skill ?? '')
      const card = messageId ? skillCard(messageId, skillId) : null
      if (card) {
        card.status = (payload.status as SkillStatus) ?? 'ok'
        card.result = (payload.result ?? null) as Record<string, unknown> | null
        card.error = String(payload.error ?? '')
        card.durationMs = Number(payload.durationMs ?? 0)
        // 换一个引用，Vue 才看得见这条卡的变化（卡片本身是原地改的）
        liveSkills.value = { ...liveSkills.value }
      }
    },

    'page.rewritten': (payload) => {
      const pageNo = Number(payload.pageNo ?? 0)
      if (!pageNo) return
      options.onPageRewritten?.({
        pageNo,
        removed: Boolean(payload.removed),
        rev: Number(payload.rev ?? 0),
        sources: (payload.sources ?? []) as SlideSource[],
      })
    },

    'agent.done': (payload) => {
      draftId.value = ''
      draftText.value = ''
      running.value = false
      void load() // 归档以库里那条为准：它有 tokens 与技能清单
      if (payload.error) error.value = String(payload.error)
    },
  }

  function close(): void {
    const current = source
    source = null
    connected.value = false
    current?.close()
  }

  function connect(id: string): void {
    close()
    if (!id) return
    const stream = new EventSource(api.chatStreamUrl(id))
    source = stream
    connected.value = true
    for (const [name, handler] of Object.entries(HANDLERS)) {
      stream.addEventListener(name, (event) => {
        const raw = (event as MessageEvent).data
        if (typeof raw !== 'string' || !raw) return
        try {
          const payload = JSON.parse(raw) as unknown
          if (payload && typeof payload === 'object') {
            handler(payload as Record<string, unknown>)
          }
        } catch {
          // 一条坏帧不该把整条流打断（重连之后新的一轮照样收得到）
        }
      })
    }
    stream.onerror = () => {
      // 浏览器自己会重连。一轮结束之后服务端会主动断开，那次断开也走这里 ——
      // 所以这里只是把「连着」标成「没连着」，不做任何重连动作。
      connected.value = false
    }
    stream.onopen = () => {
      connected.value = true
    }
  }

  watch(
    courseId,
    (id) => {
      messages.value = []
      liveSkills.value = {}
      draftId.value = ''
      draftText.value = ''
      pendingUser.value = null
      running.value = false
      error.value = ''
      loaded.value = false
      connect(id)
      void load()
      void loadSkills()
    },
    { immediate: true },
  )

  onScopeDispose(close)

  return {
    messages,
    skills,
    maxActions,
    titles,
    draftId,
    draftText,
    liveSkills,
    pendingUser,
    running,
    connected,
    error,
    loaded,
    canSend,
    send,
    rollback,
    reload: load,
    close,
  }
}
