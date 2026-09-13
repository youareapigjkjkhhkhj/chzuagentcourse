<script setup lang="ts">
/**
 * 课堂记录回看页（P3-6 / F3-11 / P3-A14）。
 *
 * **只读**：这一页不建连接、不发上行、不碰 `classroomStore`。它只问一次
 * `GET /sessions/{id}/record`，把这一堂课留下来的东西摊开给人看 ——
 * 字幕全文、消息记录、板书快照、测验作答。
 *
 * 两件事是刻意的：
 *
 * 1. **数据来自数据库，不来自事件留档**（P3-C3）。留档到顶会从头砍最老的
 *    十分之一（那是「断线补发」的上限），而记录页读的是 `messages` /
 *    `board_strokes` / `quiz_attempts` 三张永不清理的表。所以重启服务、
 *    隔一天再来，看到的都是同一份东西。
 * 2. **还在上的课也能看**（拿到的是「到此刻」）。这时候顶上挂一条说明 ——
 *    不挂的话，人会以为这堂课就这么几页，而它其实还在讲。
 *
 * 字幕按页分组、消息按到达顺序铺开：回看的时候人要的是「那一页讲了什么」，
 * 而不是一长串没有边界的流水。
 */
import { computed, onMounted, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useRoute, useRouter } from 'vue-router'

import ClassroomBoard from '@/components/classroom/ClassroomBoard.vue'
import ExportPanel from '@/components/workbench/ExportPanel.vue'
import { fetchRecord } from '@/api/classroom'
import { describeError, useSettingsStore } from '@/stores/settings'
import {
  CLASSROOM_STATUS_LABELS,
  CLASSROOM_STATUS_THEMES,
  badgeOf,
  clockOf,
  isSystemMessage,
  memberColor,
  roleLookup,
} from '@/utils/classroom'
import { formatClock } from '@/utils/voice'
import type { ClassroomRecord, RecordSubtitle } from '@/types/classroom'

const route = useRoute()
const router = useRouter()
const settings = useSettingsStore()

const sessionId = computed(() => String(route.query.session ?? ''))
const record = ref<ClassroomRecord | null>(null)
const loading = ref(false)
const loadError = ref('')
const tab = ref('subtitle')
/** 导出面板开不开（F5-5：把这一节课的逐字稿与板书导成 Markdown / PDF）。 */
const exportVisible = ref(false)

/** 说话人的名与色（角色库是异步到的，做成 computed 之后到了一起换）。 */
const lookup = computed(() => roleLookup(settings.roles))

const summary = computed(() => record.value?.session ?? null)
const title = computed(() => record.value?.courseTitle || '课堂记录')
const status = computed(() => summary.value?.status ?? 'ended')
const running = computed(() => Boolean(summary.value) && status.value !== 'ended')

/** 统计条：一堂课上成什么样，先给四个数。 */
const stats = computed(() => {
  const data = record.value?.stats
  if (!data) return []
  return [
    { label: '时长', value: formatClock(data.durationMs) },
    { label: '字幕', value: `${data.subtitles} 句` },
    { label: '消息', value: `${data.messages} 条` },
    { label: '板书', value: `${data.boardPages} 页 ${data.strokes} 笔` },
    {
      label: '作答',
      value: data.quizAttempts
        ? `${data.quizAttempts} 次 · 对 ${data.quizCorrect}`
        : '未作答',
    },
  ]
})

/**
 * 字幕按页分组。
 *
 * 后端给的是**一整条正序数组**（按时间），不是按页分好的 —— 一堂课可能来回
 * 翻页，同一页会分成好几段。这里**只合并相邻的同一页**：把第 2 页的两段按
 * pageNo 归并到一处，读起来就与时间顺序对不上了（回看的人会以为第 2 页讲完
 * 又回过头来讲）。段与段之间那一页变了，就是当时的顺序。
 */
const subtitleGroups = computed(() => {
  const groups: { pageNo: number; items: RecordSubtitle[] }[] = []
  for (const item of record.value?.subtitles ?? []) {
    const last = groups[groups.length - 1]
    if (last && last.pageNo === item.pageNo) last.items.push(item)
    else groups.push({ pageNo: item.pageNo, items: [item] })
  }
  return groups
})

/**
 * 讨论记录。**默认把讲稿滤掉**：字幕那一栏已经逐句排好了，再混一遍进来，
 * 互动（提问、补充、答疑）就被淹没了 —— 而回看的人多半是来找它们的。
 * 想看全部就打开开关，那时条数与统计条上的「消息」对得上（P3-A14）。
 */
const showLecture = ref(false)
const feed = computed(() =>
  (record.value?.messages ?? []).filter(
    (message) => showLecture.value || message.type !== 'lecture',
  ),
)

/** 每页板书各自的重放计数（`ClassroomBoard` 看到它 +1 就重画一遍）。 */
const replayKeys = ref<Record<number, number>>({})
function replay(pageNo: number): void {
  replayKeys.value = { ...replayKeys.value, [pageNo]: (replayKeys.value[pageNo] ?? 0) + 1 }
}

function goBackToClass(): void {
  const courseId = summary.value?.courseId
  void router.push(courseId ? { path: '/classroom', query: { course: courseId } } : '/classroom')
}

/**
 * 「导出记录」（P5-F5-5）：打开导出面板，范围是**这一节课堂**。
 *
 * 面板要一个 `courseId` 落在地址栏上（导出记录挂在课程下面，作业文件也按课程
 * 分目录），所以取的是记录里那门课；记录还没读到时按钮本来就是灰的。
 */
function onExport(): void {
  if (!summary.value?.courseId) {
    MessagePlugin.warning('这份记录还没关联到课程，暂时不能导出')
    return
  }
  exportVisible.value = true
}

async function load(): Promise<void> {
  if (!sessionId.value) return
  loading.value = true
  loadError.value = ''
  try {
    record.value = await fetchRecord(sessionId.value)
  } catch (error) {
    record.value = null
    loadError.value = describeError(error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  // 说话人的名字在角色库里（消息只带 code）；记录本身不等它 —— 名单一到就换上真名
  void settings.loadRoles()
  void load()
})
</script>

<template>
  <div class="rec">
    <header class="rec-header">
      <span class="back" title="返回首页" @click="router.push('/')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M15 5l-7 7 7 7" />
        </svg>
      </span>
      <div class="rec-header__info">
        <div class="rec-header__title">{{ title }}</div>
        <div class="rec-header__meta">
          <t-tag variant="light" :theme="CLASSROOM_STATUS_THEMES[status]">
            {{ CLASSROOM_STATUS_LABELS[status] }}
          </t-tag>
          <t-tag v-if="summary" variant="light">课堂记录</t-tag>
        </div>
      </div>
      <span class="spacer" />
      <t-button variant="outline" :disabled="!record" @click="goBackToClass">回到课堂</t-button>
      <t-button variant="outline" :disabled="!record" @click="onExport">
        <template #icon>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M12 3v12M7 10l5 5 5-5" />
            <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
          </svg>
        </template>
        导出记录
      </t-button>
    </header>

    <!-- 没有课号：多半是从别处点进来的 -->
    <t-empty
      v-if="!sessionId"
      class="rec-empty"
      title="没有指定要回看的课堂"
      description="课堂记录从课堂页进来 —— 上完课会自动跳到这里。"
    >
      <t-button theme="primary" @click="router.push('/classroom')">去课堂</t-button>
    </t-empty>

    <div v-else-if="loading && !record" class="rec-empty">
      <t-loading text="正在读取课堂记录…" />
    </div>

    <!-- 读不出来（不存在 / 不是我的课 / 后端挂了）就说清是哪一种，别给一页空白 -->
    <t-empty
      v-else-if="loadError"
      class="rec-empty"
      title="这份课堂记录读不出来"
      :description="loadError"
    >
      <t-button @click="router.push('/classroom')">去课堂</t-button>
      <t-button theme="primary" @click="load">重试</t-button>
    </t-empty>

    <template v-else-if="record && summary">
      <!-- 还在上的课：记录是「到此刻」，不是最终结果（§4.1） -->
      <div v-if="running" class="rec-notice">
        <t-alert theme="info">
          <template #message>
            这堂课还在上（{{ CLASSROOM_STATUS_LABELS[status] }}），下面是到此刻为止的记录。
          </template>
        </t-alert>
      </div>

      <div class="rec-stats">
        <div v-for="item in stats" :key="item.label" class="rec-stat">
          <span class="rec-stat__label">{{ item.label }}</span>
          <span class="rec-stat__value">{{ item.value }}</span>
        </div>
      </div>

      <!-- 谁上过这堂课。名字来自 users 表，颜色与在线名单同一套取法 -->
      <div class="rec-people">
        <span class="rec-people__label">上过这堂课的人</span>
        <div v-for="member in record.participants" :key="member.userId" class="person">
          <t-avatar
            shape="circle"
            size="small"
            :style="{ background: memberColor(member, summary.ownerId, settings.roles) }"
          >
            {{ (member.name || '同学').slice(0, 1) }}
          </t-avatar>
          <span class="person__name">{{ member.name || member.userId }}</span>
          <t-tag v-if="member.userId === summary.ownerId" size="small" variant="light">开课的人</t-tag>
        </div>
        <span v-if="!record.participants.length" class="rec-people__empty">没有人进过这堂课</span>
      </div>

      <t-tabs v-model="tab" class="rec-tabs">
        <t-tab-panel value="subtitle" :label="`字幕全文（${record.stats.subtitles}）`">
          <div v-if="subtitleGroups.length" class="rec-scroll">
            <section v-for="(group, index) in subtitleGroups" :key="`${group.pageNo}-${index}`" class="page-block">
              <div class="page-block__head">
                <span class="page-block__no">第 {{ group.pageNo }} 页</span>
                <span class="page-block__count">{{ group.items.length }} 句</span>
              </div>
              <p v-for="line in group.items" :key="line.beatId + line.ts" class="line">
                <span class="line__who">{{ lookup.of(line.speaker).name }}</span>
                <span class="line__text">{{ line.text }}</span>
                <span class="line__time">{{ clockOf(line.ts) }}</span>
              </p>
            </section>
          </div>
          <t-empty v-else size="small" description="这堂课没有留下字幕。" />
        </t-tab-panel>

        <t-tab-panel value="feed" :label="`消息记录（${record.stats.messages}）`">
          <div class="rec-toolbar">
            <t-checkbox v-model="showLecture">连讲解一起显示</t-checkbox>
            <span class="rec-toolbar__hint">
              讲解已经有了单独的一栏（字幕全文），这里默认只看互动
            </span>
          </div>
          <div v-if="feed.length" class="rec-scroll rec-feed">
            <template v-for="message in feed" :key="message.id">
              <div v-if="isSystemMessage(message)" class="msg--sys">{{ message.text }}</div>
              <div v-else class="msg" :class="message.speakerKind === 'me' ? 'msg--me' : 'msg--other'">
                <div class="msg__head">
                  <t-avatar
                    shape="circle"
                    size="16px"
                    :style="{ background: lookup.of(message.speaker, message.speakerKind).color }"
                  >
                    {{ lookup.of(message.speaker, message.speakerKind).name.slice(0, 1) }}
                  </t-avatar>
                  <span class="msg__who">
                    {{ lookup.of(message.speaker, message.speakerKind).name }}
                  </span>
                  <t-tag size="small" variant="light" :theme="badgeOf(message).theme">
                    {{ badgeOf(message).text }}
                  </t-tag>
                  <span v-if="message.pageNo" class="msg__page">第 {{ message.pageNo }} 页</span>
                  <span class="msg__time">{{ clockOf(message.ts) }}</span>
                </div>
                <div class="msg__text">{{ message.text }}</div>
              </div>
            </template>
          </div>
          <t-empty v-else size="small" description="这堂课没有留下消息。" />
        </t-tab-panel>

        <t-tab-panel value="board" :label="`板书快照（${record.stats.boardPages}）`">
          <div v-if="record.boards.length" class="rec-scroll">
            <section v-for="item in record.boards" :key="item.pageNo" class="board-block">
              <div class="page-block__head">
                <span class="page-block__no">第 {{ item.pageNo }} 页</span>
                <span class="page-block__count">{{ item.strokes.length }} 笔</span>
                <span class="spacer" />
                <t-button size="small" variant="text" @click="replay(item.pageNo)">重放</t-button>
              </div>
              <div class="board-block__canvas">
                <ClassroomBoard
                  :strokes="item.strokes"
                  :replay-key="replayKeys[item.pageNo] ?? 0"
                  :live="false"
                  instant
                />
              </div>
            </section>
          </div>
          <t-empty v-else size="small" description="这堂课没有留下板书。" />
        </t-tab-panel>

        <t-tab-panel value="quiz" :label="`测验作答（${record.stats.quizAttempts}）`">
          <div v-if="record.quizzes.length" class="rec-scroll">
            <!-- 一次一行：答错重答是第二次作答，不合并（P6.1 要分开算两种答对率） -->
            <div v-for="(item, index) in record.quizzes" :key="index" class="attempt">
              <div class="attempt__head">
                <span class="attempt__no">第 {{ index + 1 }} 次</span>
                <span class="attempt__page">第 {{ item.pageNo }} 页</span>
                <t-tag size="small" :theme="item.correct ? 'success' : 'danger'" variant="light">
                  {{ item.correct ? '回答正确' : '回答错误' }}
                </t-tag>
                <span v-if="item.responseMs" class="attempt__ms">
                  用时 {{ (item.responseMs / 1000).toFixed(1) }} 秒
                </span>
                <span class="spacer" />
                <span class="attempt__time">{{ clockOf(item.ts) }}</span>
              </div>
              <div class="attempt__option">我选了：{{ item.option }}</div>
            </div>
          </div>
          <t-empty v-else size="small" description="这堂课没有作答记录。" />
        </t-tab-panel>
      </t-tabs>
    </template>

    <!-- scope=record：导的是这一节课的记录（F5-5），格式由服务端说（Markdown / PDF） -->
    <ExportPanel
      v-if="summary"
      v-model:visible="exportVisible"
      :course-id="summary.courseId"
      scope="record"
      :session-id="sessionId"
    />
  </div>
</template>

<style scoped>
.rec {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 60px);
  max-width: 1080px;
  margin: 0 auto;
  padding: 20px 24px 32px;
}

.rec-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.rec-header .back {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  cursor: pointer;
  color: var(--td-text-secondary);
}

.rec-header .back:hover {
  background: var(--td-bg-container-hover);
  color: var(--td-text-primary);
}

.rec-header__title {
  font-size: 18px;
  font-weight: 600;
  color: var(--td-text-primary);
}

.rec-header__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.spacer {
  flex: 1;
}

.rec-notice {
  margin-top: 14px;
}

.rec-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
}

.rec-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 96px;
  padding: 10px 14px;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
}

.rec-stat__label {
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.rec-stat__value {
  font-size: 15px;
  font-weight: 600;
  color: var(--td-text-primary);
  font-family: var(--td-font-mono);
}

.rec-people {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.rec-people__label {
  font-size: 13px;
  color: var(--td-text-placeholder);
}

.rec-people__empty {
  font-size: 13px;
  color: var(--td-text-placeholder);
}

.person {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px 3px 4px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 999px;
}

.person__name {
  font-size: 13px;
  color: var(--td-text-secondary);
}

.rec-tabs {
  margin-top: 16px;
}

/* 记录可以很长：给它自己的滚动区，页头与统计条一直看得见 */
.rec-scroll {
  max-height: calc(100vh - 360px);
  min-height: 160px;
  overflow-y: auto;
  padding: 4px 6px 8px;
}

.rec-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 6px 10px;
}

.rec-toolbar__hint {
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.page-block {
  margin-bottom: 18px;
}

.page-block__head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0 8px;
  border-bottom: 1px solid var(--td-component-stroke);
  margin-bottom: 8px;
}

.page-block__no {
  font-size: 13px;
  font-weight: 600;
  color: var(--td-brand-color);
}

.page-block__count {
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.line {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 0;
  padding: 6px 8px;
  border-radius: var(--td-radius-default);
  font-size: 14px;
  line-height: 1.75;
  color: var(--td-text-secondary);
}

.line:hover {
  background: var(--td-bg-container-hover);
}

.line__who {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--td-brand-color);
  font-size: 13px;
}

.line__text {
  flex: 1;
}

.line__time {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--td-text-placeholder);
  font-family: var(--td-font-mono);
}

/* --- 消息（与课堂页讨论区同一种读法）--- */

.rec-feed {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.msg {
  padding: 8px 10px;
  border-radius: var(--td-radius-medium);
  background: var(--td-bg-container);
}

.msg--me {
  background: var(--td-brand-color-light);
}

.msg--sys {
  align-self: center;
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.msg__head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.msg__who {
  font-size: 13px;
  font-weight: 600;
  color: var(--td-text-primary);
}

.msg__page,
.msg__time {
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.msg__time {
  margin-left: auto;
  font-family: var(--td-font-mono);
}

.msg__text {
  margin-top: 4px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--td-text-secondary);
  white-space: pre-wrap;
}

/* --- 板书 --- */

.board-block {
  margin-bottom: 18px;
}

.board-block__canvas {
  height: 320px;
  display: flex;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
  overflow: hidden;
}

/* --- 作答 --- */

.attempt {
  padding: 10px 12px;
  margin-bottom: 10px;
  background: var(--td-bg-container);
  border-radius: var(--td-radius-medium);
  box-shadow: var(--td-shadow-1);
}

.attempt__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.attempt__no {
  font-size: 13px;
  font-weight: 600;
  color: var(--td-text-primary);
}

.attempt__page,
.attempt__ms,
.attempt__time {
  font-size: 12px;
  color: var(--td-text-placeholder);
}

.attempt__option {
  margin-top: 6px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--td-text-secondary);
}

.rec-empty {
  margin-top: 80px;
}
</style>
