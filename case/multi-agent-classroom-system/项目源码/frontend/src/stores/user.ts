/**
 * 当前用户（P0 用固定本地用户）。
 *
 * 为什么现在就有这个 store：`courses.owner_id` 从 P0 就落库了，
 * 越权校验（AGENTS.md §4.1）也是按 owner_id 做的。后端迟早要认人，
 * 前端若到那时才引入「我在以谁的身份操作」这个概念，就得回头改所有请求。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/** P0 的固定本地用户。等接入登录后由后端返回替换。 */
const LOCAL_USER = { id: 'local-teacher', name: '我', role: 'teacher' as const }

export const useUserStore = defineStore('user', () => {
  const id = ref(LOCAL_USER.id)
  const name = ref(LOCAL_USER.name)
  const role = ref<'teacher' | 'student' | 'admin'>(LOCAL_USER.role)

  const isTeacher = computed(() => role.value === 'teacher')
  /** 头像上的那个字 */
  const initial = computed(() => name.value.slice(0, 1))

  return { id, name, role, isTeacher, initial }
})
