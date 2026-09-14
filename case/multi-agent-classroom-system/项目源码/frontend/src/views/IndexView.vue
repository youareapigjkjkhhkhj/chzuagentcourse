<script setup lang="ts">
/**
 * 首页 —— 版式照抄 `产品原型/index.html`（hero + 生成器卡片 + 示例 + 最近课堂 + 能力）。
 *
 * 这一页只做两件事：把主题送出去（P1-A1），以及如实列出最近课堂（P1-A10）。
 * 卡片上的页数、时长、状态、进度全部照抄 `GET /api/courses` —— 页面不自己算
 * 一份，算出来的那份迟早和详情页对不上。
 *
 * 送出去的时候带上 `confirmOutline`：这一门课的第一个停点是工作台的大纲确认
 * （F1-3），用户过一眼、增删几页，点「确认大纲」才接着写页面。
 *
 * 还有一条：**生成中的卡片靠轮询刷新，而不是让 68% 慢慢往上爬**（P1-B5）。
 * 只有真的有课在生成时才轮询，全部就绪之后一个请求都不发。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useRouter } from 'vue-router'

import GeneratorCard from '@/components/home/GeneratorCard.vue'
import CourseCard from '@/components/home/CourseCard.vue'
import CapabilityPanel from '@/components/CapabilityPanel.vue'
import { usePolling } from '@/composables/usePolling'
import * as api from '@/api'
import { useCoursesStore } from '@/stores/courses'
import { describeError, useSettingsStore } from '@/stores/settings'
import { useUserStore } from '@/stores/user'
import type { CourseMode } from '@/types/api'

/** 生成中的课程多久问一次列表。快了没必要，慢了看着像卡住。 */
const LIST_POLL_MS = 5000

const router = useRouter()
const settings = useSettingsStore()
const courses = useCoursesStore()
const user = useUserStore()

const submitting = ref(false)

/** 课时估算：按经验一页讲稿约 2 分钟，跟原型「12 页 · 约 25 分钟」对得上。 */
const estimate = computed(() => {
  const pages = settings.generation?.pageCount ?? 12
  return { pages, minutes: Math.round(pages * 2) }
})

const polling = usePolling(() => void courses.load(), LIST_POLL_MS)
const pollingActive = computed(() => polling.running.value)

/** 有课在生成才轮询；全部就绪就停 —— 没有变化就没有请求。 */
watch(
  () => courses.generating,
  (generating) => {
    if (generating) polling.start()
    else polling.stop()
  },
)

/**
 * 开一门课，然后进工作台。
 *
 * `confirmOutline` 固定带上：首页是界面上唯一的生成入口，而工作台的大纲树
 * 只有停在这个确认点时才可编辑（增删改序 —— 生成跑起来之后服务端一律 409）。
 * 不带上它，「大纲先行」这件事在界面上就没有第二次机会。想一路写完，得走
 * API 显式传 `confirmOutline: false`。
 */
async function start(payload: {
  topic: string
  mode: CourseMode
  template?: string
}): Promise<void> {
  submitting.value = true
  try {
    const started = await api.startGeneration({ ...payload, confirmOutline: true })
    await router.push({
      name: 'workbench',
      query: { course: started.courseId, job: started.jobId },
    })
  } catch (error) {
    // 40201（没配模型）等错误在这里如实说出原因，而不是「操作成功」
    MessagePlugin.error(describeError(error))
  } finally {
    submitting.value = false
  }
}

function openCourse(course: { id: string; jobId: string }): void {
  void router.push({
    name: 'workbench',
    query: { course: course.id, ...(course.jobId ? { job: course.jobId } : {}) },
  })
}

async function removeCourse(id: string): Promise<void> {
  try {
    await courses.remove(id)
    MessagePlugin.success('已删除')
  } catch (error) {
    MessagePlugin.error(describeError(error))
  }
}

function onUpload(): void {
  MessagePlugin.info('材料上传将在 P4 阶段接入（现在只认主题）')
}

onMounted(async () => {
  void settings.loadAll()
  await courses.load()
})
</script>

<template>
  <div class="home">
    <section class="hero">
      <span class="hero__badge">
        <i class="dot" />
        多智能体 · 一键生成互动课堂
      </span>
      <h1>
        输入一个主题，<br />
        <em>AI 教师与 AI 同学</em>陪你上一堂完整的课
      </h1>
      <p class="hero__sub">
        自动生成幻灯片与讲稿，AI 教师语音授课，多位 AI 同学实时提问与讨论<br />
        支持上传课件资料、白板互动与一键导出
      </p>

      <GeneratorCard
        :estimate-pages="estimate.pages"
        :estimate-minutes="estimate.minutes"
        :submitting="submitting"
        @submit="start"
        @upload="onUpload"
      />
    </section>

    <section class="section">
      <div class="section__head">
        <h2>最近课堂</h2>
        <t-tag>共 {{ courses.total }} 门</t-tag>
        <span v-if="courses.lastError" class="text-placeholder load-error">
          列表没拉下来：{{ courses.lastError }}
        </span>
      </div>

      <div v-if="courses.items.length" class="course-grid">
        <CourseCard
          v-for="(course, index) in courses.items"
          :key="course.id"
          :course="course"
          :index="index"
          @open="openCourse(course)"
          @remove="removeCourse(course.id)"
        />
      </div>
      <div v-else class="panel empty-card">
        <t-empty
          title="还没有生成的课堂"
          description="在上面输入一个主题就能开工。生成过程可以随时在大纲确认点停下来改大纲。"
        />
      </div>

      <p v-if="pollingActive" class="text-placeholder polling">
        有课堂正在生成，进度每 {{ LIST_POLL_MS / 1000 }} 秒刷新一次
      </p>
    </section>

    <section class="section after">
      <div class="section__head">
        <h2>环境能力</h2>
      </div>
      <CapabilityPanel />
    </section>

    <section class="section after">
      <div class="section__head">
        <h2>课堂里有什么</h2>
      </div>
      <div class="features">
        <div class="panel feature">
          <div class="feature__icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5" />
            </svg>
          </div>
          <h3>AI 教师授课</h3>
          <p>根据主题自动撰写幻灯片与讲稿，配合激光笔、聚光灯等教具逐页讲解，支持随时打断提问。</p>
        </div>
        <div class="panel feature">
          <div class="feature__icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <circle cx="8" cy="9" r="3" />
              <circle cx="16.5" cy="9.5" r="2.5" />
              <path d="M2.5 19c.5-3 2.8-4.5 5.5-4.5s5 1.5 5.5 4.5M14.5 15c2.6 0 4.4 1.4 4.9 4" />
            </svg>
          </div>
          <h3>AI 同学共学</h3>
          <p>多位性格各异的 AI 同学实时听课、记笔记、提问与辩论，还原真实课堂的同伴学习氛围。</p>
        </div>
        <div class="panel feature">
          <div class="feature__icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3Z" />
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7" />
            </svg>
          </div>
          <h3>语音双向互动</h3>
          <p>教师语音合成授课，学生可通过语音识别举手发言，课堂讨论自然流畅、可听可说。</p>
        </div>
        <div class="panel feature">
          <div class="feature__icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M12 3v12M7 10l5 5 5-5" />
              <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
            </svg>
          </div>
          <h3>一键导出分享</h3>
          <p>课堂结束后可将课件导出为 PPTX、HTML 或 PDF，讲稿与讨论记录同步归档，随时回看。</p>
        </div>
      </div>
    </section>

    <!-- 环境与版本原来挂在 hero 的徽章上，占着最显眼的位置说一件没什么用的事；
         徽章换回原型那句话，这两个数挪到页脚，要找的时候找得到 -->
    <footer>
      EduAgentX · 多智能体互动课堂 —— 以 {{ user.name }} 的本地身份使用 ·
      数据保存在本机 SQLite · 环境 {{ settings.capabilities?.env ?? '—' }} ·
      v{{ settings.capabilities?.version ?? '—' }}
    </footer>
  </div>
</template>

<style scoped>
/* 以下版式取自 产品原型/index.html（生成器与卡片在各自组件里） */

.hero {
  padding: 72px 32px 0;
  text-align: center;
}

.hero__badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 14px;
  border-radius: var(--td-radius-round);
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 24px;
}

.hero__badge .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--td-success-color);
}

.hero h1 {
  font-size: 42px;
  font-weight: 600;
  letter-spacing: 0.5px;
  line-height: 1.35;
}

.hero h1 em {
  font-style: normal;
  color: var(--td-brand-color);
  background: linear-gradient(180deg, transparent 62%, var(--td-brand-color-focus) 62%);
  padding: 0 4px;
}

.hero__sub {
  margin-top: 16px;
  font-size: 16px;
  color: var(--td-text-secondary);
  line-height: 1.8;
}

.section {
  max-width: 1200px;
  margin: 0 auto;
  padding: 56px 32px 24px;
}

.section.after {
  padding-top: 24px;
}

.section__head {
  display: flex;
  align-items: baseline;
  gap: 16px;
  margin-bottom: 24px;
}

.section__head h2 {
  font-size: 22px;
  font-weight: 600;
}

.load-error {
  font-size: 13px;
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

@media (max-width: 1100px) {
  .course-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.empty-card {
  padding: 24px;
}

.polling {
  margin-top: 16px;
  font-size: 12px;
}

.features {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

@media (max-width: 1100px) {
  .features {
    grid-template-columns: repeat(2, 1fr);
  }
}

.feature {
  padding: 24px;
}

.feature__icon {
  width: 44px;
  height: 44px;
  border-radius: var(--td-radius-medium);
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}

.feature__icon svg {
  width: 22px;
  height: 22px;
}

.feature h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
}

.feature p {
  font-size: 13px;
  color: var(--td-text-secondary);
  line-height: 1.7;
}

footer {
  margin-top: 64px;
  padding: 28px 32px;
  text-align: center;
  font-size: 13px;
  color: var(--td-text-placeholder);
  border-top: 1px solid var(--td-component-stroke);
  background: var(--td-bg-container);
}
</style>
