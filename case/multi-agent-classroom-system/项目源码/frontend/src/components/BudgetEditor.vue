<script setup lang="ts">
/**
 * 预算（P5-F5-8）—— 设置页「成本」那一档的中间一截。
 *
 * **这是整套设置里唯一一个会拦住别的操作的模块**：超了日预算就开不了新课。
 * 所以界面上要把三件事说清楚，缺一个用户就会觉得「我明明还有额度它却说超了」：
 *
 * 1. **0 表示不限**，不是「限额为零」。用它把某一条关掉 —— 那比删掉更好，
 *    因为删掉与「从没设过」在库里长得一样。
 * 2. **告警线只让界面变黄，不拦任何事**（服务端 `alert_ratio`）。真的拒人
 *    只有超过上限那一下。
 * 3. **每次判断三个作用域都要过**：今天的、这门课的、总共的，取最严的那个。
 *
 * 超没超由服务端算（每行带 `over` / `alert`），前端不拿用量去比 0 —— 那条
 * 「0 = 不限」的规则在两边各写一遍，迟早会出现设置页说没超、生成却说你超了。
 */
import { computed, onMounted, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'

import * as api from '@/api'
import { describeError } from '@/stores/settings'
import type { BudgetPatch, BudgetPayload, BudgetRow, CourseCard } from '@/types/api'
import { BUDGET_SCOPE_LABELS } from '@/utils/labels'
import { formatCost } from '@/utils/voice'

/** 一行可编辑的草稿。数字框给的是字符串来源，这里统一成数字。 */
interface Draft {
  limitCost: number
  limitTokens: number
  alertRatio: number
  enabled: boolean
}

const data = ref<BudgetPayload | null>(null)
const courses = ref<CourseCard[]>([])
const drafts = ref<Record<string, Draft>>({})
const loading = ref(false)
const saving = ref(false)
const error = ref('')

/** 新增一条单课预算时的两个输入。 */
const newCourseId = ref('')
const newCost = ref(0)

const keyOf = (row: Pick<BudgetRow, 'scope' | 'refId'>) => `${row.scope}:${row.refId}`

/** 课程的显示名。课被删了就退回 id —— 这条预算仍然管着那门课的账。 */
function courseName(courseId: string): string {
  const found = courses.value.find((item) => item.id === courseId)
  return found?.title || courseId
}

/** 还没配过预算的课，用来铺「加一条」的下拉 —— 已有的那条改就行了。 */
const budgetedCourses = computed(() => new Set((data.value?.budgets ?? []).map((row) => row.refId)))
const freeCourses = computed(() =>
  courses.value
    .filter((course) => !budgetedCourses.value.has(course.id))
    .map((course) => ({ label: course.title, value: course.id })),
)

async function load(): Promise<void> {
  loading.value = true
  try {
    const [payload, list] = await Promise.all([api.fetchBudget(), api.fetchCourses()])
    data.value = payload
    courses.value = list.items
    drafts.value = Object.fromEntries(
      payload.budgets.map((row) => [
        keyOf(row),
        {
          limitCost: row.limitCost,
          limitTokens: row.limitTokens,
          alertRatio: row.alertRatio,
          enabled: row.enabled,
        },
      ]),
    )
    error.value = ''
  } catch {
    data.value = null
    error.value = '预算读取失败，稍后再试'
  } finally {
    loading.value = false
  }
}

onMounted(load)

/** 改过哪几行。只把动过的发出去，别的行保持原样（省得一次误点把所有行都覆盖）。 */
const dirtyRows = computed<BudgetPatch[]>(() => {
  const rows = data.value?.budgets ?? []
  const out: BudgetPatch[] = []
  for (const row of rows) {
    const draft = drafts.value[keyOf(row)]
    if (!draft) continue
    const changed =
      draft.limitCost !== row.limitCost ||
      draft.limitTokens !== row.limitTokens ||
      draft.alertRatio !== row.alertRatio ||
      draft.enabled !== row.enabled
    if (!changed) continue
    out.push({
      scope: row.scope,
      refId: row.refId || undefined,
      limitTokens: draft.limitTokens,
      limitCost: draft.limitCost,
      alertRatio: draft.alertRatio,
      enabled: draft.enabled,
    })
  }
  return out
})

const dirty = computed(() => dirtyRows.value.length > 0)

async function save(): Promise<void> {
  if (!dirty.value) return
  saving.value = true
  try {
    // PUT 回的就是新的全量（`budget.update` 返回 `get_all()`）——
    // 用它覆盖本地那份，省得再问一次，也保证界面上的数与服务端一致。
    data.value = await api.saveBudget({ budgets: dirtyRows.value })
    MessagePlugin.success('预算已保存')
  } catch (err) {
    MessagePlugin.error(describeError(err))
  } finally {
    saving.value = false
  }
}

function reset(): void {
  void load()
}

/** 新增一条单课预算。**必须带课程 id**：不带就是「所有课程」，那是总额的意思。 */
async function addCourse(): Promise<void> {
  if (!newCourseId.value) {
    MessagePlugin.warning('先选一门课程')
    return
  }
  saving.value = true
  try {
    data.value = await api.saveBudget({
      budgets: [
        {
          scope: 'course',
          refId: newCourseId.value,
          limitCost: newCost.value,
          // 只配金额：token 那条留 0（不限），用户要的话在表格里再补
          limitTokens: 0,
        },
      ],
    })
    newCourseId.value = ''
    newCost.value = 0
    MessagePlugin.success('已加一条单课预算')
    await load() // 新那一行要进草稿表，重新铺一遍
  } catch (err) {
    MessagePlugin.error(describeError(err))
  } finally {
    saving.value = false
  }
}

/** 一条预算现在的样子：用了多少 / 上限多少。 */
function usageText(row: BudgetRow): string {
  const draft = drafts.value[keyOf(row)]
  const cost = draft?.limitCost ?? row.limitCost
  const tokens = draft?.limitTokens ?? row.limitTokens
  const bits: string[] = []
  if (cost) bits.push(`${formatCost(row.usedCost)} / ${formatCost(cost)}`)
  else bits.push(`已用 ${formatCost(row.usedCost)}`)
  if (tokens) bits.push(`${row.usedTokens} / ${tokens} tokens`)
  return bits.join(' · ')
}
</script>

<template>
  <section class="panel">
    <h3 class="panel__title">预算</h3>
    <p class="panel__desc">
      上限填 <strong>0 表示不限</strong>。三个作用域每次都要过一遍（今天的、单门课的、
      全部的），取最严的那个；到告警线只会让这里变黄，只有真的超了才会拦住下一次生成。
    </p>

    <p v-if="loading && !data" class="bg-hint">读取中…</p>
    <p v-else-if="error" class="bg-hint is-error">{{ error }}</p>

    <template v-else-if="data">
      <div class="bg-table">
        <div class="bg-table__head">
          <span>作用域</span><span>对象</span><span>金额上限（元）</span><span>token 上限</span>
          <span>告警线</span><span>启用</span>
        </div>

        <div
          v-for="row in data.budgets"
          :key="keyOf(row)"
          class="bg-table__row"
          :class="{ 'is-over': row.over, 'is-alert': row.alert }"
        >
          <span class="bg-scope">{{ BUDGET_SCOPE_LABELS[row.scope] }}</span>
          <span class="bg-target" :title="row.refId">
            {{ row.scope === 'course' ? courseName(row.refId) : '—' }}
          </span>

          <t-input-number
            v-model="drafts[keyOf(row)].limitCost"
            theme="column"
            size="small"
            :min="0"
            :step="1"
            :decimal-places="2"
          />
          <t-input-number
            v-model="drafts[keyOf(row)].limitTokens"
            theme="column"
            size="small"
            :min="0"
            :step="1000"
          />
          <t-slider
            v-model="drafts[keyOf(row)].alertRatio"
            :min="0"
            :max="1"
            :step="0.05"
            :label="false"
          />
          <t-switch v-model="drafts[keyOf(row)].enabled" size="small" />

          <p class="bg-usage">
            {{ usageText(row) }}
            <span v-if="row.over" class="bg-flag">已超上限，下一次生成会被拒</span>
            <span v-else-if="row.alert" class="bg-flag is-warn">接近上限</span>
          </p>
        </div>
      </div>

      <div class="bg-actions">
        <t-button
          theme="primary"
          size="small"
          :disabled="!dirty"
          :loading="saving"
          @click="save"
        >
          保存预算
        </t-button>
        <t-button size="small" variant="text" :disabled="!dirty" @click="reset">还原</t-button>
      </div>

      <div class="bg-add">
        <span class="bg-add__label">加一条单课预算</span>
        <t-select
          v-model="newCourseId"
          size="small"
          placeholder="选一门课程"
          :options="freeCourses"
          class="bg-add__select"
        />
        <t-input-number v-model="newCost" theme="column" size="small" :min="0" :step="1" />
        <t-button size="small" variant="outline" :loading="saving" @click="addCourse">添加</t-button>
      </div>

      <p class="bg-note">{{ data.note }}</p>
    </template>
  </section>
</template>

<style scoped>
.bg-hint {
  font-size: 13px;
  color: var(--td-text-placeholder);
}

.bg-hint.is-error {
  color: var(--td-error-color);
}

.bg-table {
  margin-top: 10px;
}

.bg-table__head,
.bg-table__row {
  display: grid;
  grid-template-columns: 56px minmax(90px, 1fr) 120px 120px 110px 52px;
  gap: 10px;
  align-items: center;
}

.bg-table__head {
  padding: 4px 0 8px;
  font-size: 12px;
  color: var(--td-text-placeholder);
  border-bottom: 1px solid var(--td-component-stroke);
}

.bg-table__row {
  padding: 8px 0;
  border-bottom: 1px dashed var(--td-component-stroke);
  font-size: 13px;
}

.bg-table__row.is-alert {
  background: var(--td-warning-color-light);
}

.bg-table__row.is-over {
  background: var(--td-error-color-light);
}

.bg-scope {
  font-weight: 600;
}

.bg-target {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bg-usage {
  grid-column: 1 / -1;
  font-size: 11px;
  color: var(--td-text-placeholder);
}

.bg-flag {
  margin-left: 8px;
  color: var(--td-error-color);
}

.bg-flag.is-warn {
  color: var(--td-warning-color);
}

.bg-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}

.bg-add {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--td-component-stroke);
  font-size: 13px;
}

.bg-add__label {
  color: var(--td-text-secondary);
}

.bg-add__select {
  width: 200px;
}

.bg-note {
  margin-top: 10px;
  font-size: 11px;
  color: var(--td-text-placeholder);
}
</style>
