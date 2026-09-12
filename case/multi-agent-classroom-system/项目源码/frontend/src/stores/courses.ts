/**
 * 课程列表 store（P1-A10）。
 *
 * 卡片上的页数、时长、状态、进度**全部照抄接口**，前端不自己算一份 ——
 * 自己算的那份在重连、重试、删除之后就会和详情页对不上。
 *
 * 读吞异常、写抛异常（与设置 store 同一条纪律）：列表拉不到时页面照样
 * 渲染骨架并说明原因，而不是白屏；删除失败必须让调用方知道。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import * as api from '@/api'
import { describeError } from '@/stores/settings'
import type { CourseCard, CourseQuery } from '@/types/api'

export const useCoursesStore = defineStore('courses', () => {
  const items = ref<CourseCard[]>([])
  const total = ref(0)
  const loading = ref(false)
  const lastError = ref('')

  /** 有课在生成时首页才轮询：没有变化就没有请求。 */
  const generating = computed(() => items.value.some((item) => item.status === 'generating'))

  async function load(query: CourseQuery = {}): Promise<void> {
    loading.value = true
    lastError.value = ''
    try {
      const list = await api.fetchCourses(query)
      items.value = list.items ?? []
      total.value = list.total ?? 0
    } catch (error) {
      lastError.value = describeError(error)
    } finally {
      loading.value = false
    }
  }

  /** 软删。后端留着页面与版本，这里只是把它从列表里挪走。 */
  async function remove(id: string): Promise<void> {
    await api.deleteCourse(id)
    items.value = items.value.filter((item) => item.id !== id)
    total.value = Math.max(0, total.value - 1)
  }

  return { items, total, loading, lastError, generating, load, remove }
})
