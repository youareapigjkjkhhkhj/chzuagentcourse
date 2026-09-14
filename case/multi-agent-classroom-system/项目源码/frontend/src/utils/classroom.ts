/**
 * 课堂的「怎么显示」：状态文案、说话人名色、消息徽标、时间。
 *
 * **为什么不放在各自的组件里**：课堂页（实时）与课堂记录页（回看）看的是
 * 同一批数据 —— 同一张 `messages` 表、同一份会话行。同一句话在两页上写出
 * 两个颜色、两个徽标，看的人会以为是两回事。所以读法只有这一份。
 *
 * 这里只做显示，不碰状态：没有一个函数会推算课堂讲到哪了（那条纪律见
 * `stores/classroom.ts` 开头）。
 */

import type { AgentRole } from '@/types/api'
import type { ClassroomMessage, ClassroomStatus, MessageType } from '@/types/classroom'

/** 状态机（§2.1）→ 顶栏那个标签上的两个字。 */
export const CLASSROOM_STATUS_LABELS: Record<ClassroomStatus, string> = {
  idle: '待开讲',
  lecture: '讲解中',
  discussing: '讨论中',
  quiz_wait: '答题中',
  board_show: '看板书',
  paused: '已暂停',
  ended: '已下课',
}

/** 状态标签的配色。终态与「停住了」用灰，正在走的三拍用主色。 */
export const CLASSROOM_STATUS_THEMES: Record<
  ClassroomStatus,
  'primary' | 'success' | 'warning' | 'default'
> = {
  idle: 'default',
  lecture: 'primary',
  discussing: 'success',
  quiz_wait: 'warning',
  board_show: 'primary',
  paused: 'default',
  ended: 'default',
}

/**
 * 「我」的头像色。
 *
 * 真人学生不在角色库里（`speakerKind === 'me'`），所以单独给一个灰 ——
 * 它是**灰色的那个自己**，与课堂上任何一个 AI 都不该是同一种颜色。
 */
export const ME_COLOR = 'linear-gradient(135deg,#333,#666)'

/** 查不到角色时的兜底色。 */
export const UNKNOWN_COLOR = '#888'

/** 消息类型徽标（F3-5：插话带 `type` 徽标）。讲稿也有一枚，记录页要按它筛。 */
export const TYPE_LABELS: Record<
  MessageType,
  { text: string; theme: 'primary' | 'success' | 'warning' | 'default' }
> = {
  lecture: { text: '讲解', theme: 'default' },
  question: { text: '提问', theme: 'primary' },
  supplement: { text: '补充', theme: 'success' },
  reflect: { text: '思考', theme: 'warning' },
  answer: { text: '答疑', theme: 'primary' },
  comment: { text: '发言', theme: 'default' },
  system: { text: '系统', theme: 'default' },
}

/**
 * 消息徽标。**老师发的「提问」显示成「追问」**：那是引导式答疑里的那一步
 * （`scaffold.ASK_TYPE`，或者讨论里老师顺着学生的话往下问）。它与学生的提问
 * 用的是同一个 `type`，但在课堂上是**相反方向的同一件事** —— 都写成「提问」，
 * 回看的人分不清这一句是学生问的，还是老师接着学生的话问回去的。
 */
export function badgeOf(message: ClassroomMessage) {
  if (message.speakerKind === 'teacher' && message.type === 'question') {
    return { text: '追问', theme: 'warning' as const }
  }
  return TYPE_LABELS[message.type] ?? TYPE_LABELS.comment
}

/** 系统提示（居中、不带头像的那一类）。 */
export const isSystemMessage = (message: ClassroomMessage): boolean =>
  message.speakerKind === 'system' || message.type === 'system'

/** 消息里的时间。只取时分 —— 时间线上的秒在这里是噪声。 */
export function clockOf(ts: string): string {
  const match = /T(\d{2}):(\d{2})/.exec(ts || '')
  return match ? `${match[1]}:${match[2]}` : ''
}

/**
 * 「说话人 → 名字 + 头像色」的查表器。
 *
 * 键是角色的 `code`（后端 `_speak_text` 发的就是它）。名字不能拿 code 顶上
 * —— 消息里只有 code，**名字只在角色库里**，而角色库是设置页那份
 * （`GET /roles`）。所以要现查一次。
 *
 * 返回的是**查表器而不是查表结果**：角色库是异步到的（`loadRoles` 落在
 * 挂载之后），做成 computed 查表器之后，名单一到，屏幕上已经在的那几条
 * 消息跟着换成真名，不必重新拉一次记录。
 *
 * 记录页也要它：字幕行里的 `speaker` 同样只是个 code。那一份没有
 * `speakerKind`（字幕只有老师与 AI 同学），所以 `of` 的第二个参数可省。
 */
export function roleLookup(roles: AgentRole[]) {
  const byCode = new Map<string, { name: string; color: string }>()
  for (const role of roles) {
    byCode.set(role.code, { name: role.name, color: role.avatarColor || UNKNOWN_COLOR })
  }
  const of = (speaker: string, kind = ''): { name: string; color: string } => {
    if (kind === 'me') return { name: '我', color: ME_COLOR }
    return byCode.get(speaker) ?? { name: speaker || '课堂', color: UNKNOWN_COLOR }
  }
  return { of }
}

/** 消息列表用的那一份：把 `speaker` / `speakerKind` 拆出来交给 `roleLookup`。 */
export function speakerNamer(
  roles: AgentRole[],
): (message: ClassroomMessage) => { name: string; color: string } {
  const lookup = roleLookup(roles)
  return (message) => lookup.of(message.speaker, message.speakerKind)
}

/** 没有头像色的人依次拿这里的颜色（同一个 id 永远拿同一个，见 `avatarColor`）。 */
const PALETTE = [
  '#0052d9',
  '#0594fa',
  '#2ba471',
  '#834ec2',
  '#d54941',
  '#e37318',
  '#0f766e',
  '#b45309',
]

/**
 * 没有角色库可查的人（真人学生）的头像色：按 id 定一个。
 *
 * **不按「第几个到的」取色**：那样同一堂课刷新一次，同一个人的颜色就换了，
 * 而记录页（回看）与课堂页会给出不同的颜色。按 id 算哈希是稳定的 ——
 * 两页、两个标签页、两次刷新，看到的都是同一个色。
 */
export function avatarColor(key: string): string {
  let hash = 0
  for (const char of key || '') hash = (hash * 31 + (char.codePointAt(0) ?? 0)) % 100_000
  return PALETTE[hash % PALETTE.length]
}

/**
 * 在线名单里某个人（或记录页的参与者）的头像色。
 *
 * 三种人三种取色：开课的人 = 「我」的灰、能对上角色库的（AI 同学）= 角色的
 * 头像色、剩下的真人学生 = `avatarColor`。**中间那一档至今没派上用场** ——
 * 参与表里的 `role` 是 `owner` / `member`（谁在这堂课里的身份），不是角色
 * 代码，所以真人都走第三条。留着它是因为在线名单的 `role` 将来若换成角色代码，
 * 这一处不必再改一遍。
 */
export function memberColor(
  member: { userId: string; role: string },
  ownerId: string,
  roles: AgentRole[],
): string {
  if (member.userId && member.userId === ownerId) return ME_COLOR
  const byCode = roles.find((role) => role.code === member.role)
  if (byCode) return byCode.avatarColor || UNKNOWN_COLOR
  return avatarColor(member.userId || member.role)
}
