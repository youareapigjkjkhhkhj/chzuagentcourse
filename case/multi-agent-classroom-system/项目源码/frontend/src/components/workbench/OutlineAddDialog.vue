<script setup lang="ts">
/**
 * 「+ 章节」/「+ 页」的弹窗（P1-A3 的增章与增页）。
 *
 * 为什么先问名字再落到树上，而不是先插一行再就地改名：新加的这一页**必须有
 * 标题** —— 标题会写进写页的提示词，叫「新页面」的一页生成出来就是「新页面」
 * 那一课。所以宁可在这里多问一句。
 *
 * 页型固定成 `concept`：九种页型里，封面 / 大纲页 / 测验页 / 小结都由管线按
 * 规则补齐（提交时也会被服务端摘掉重排），用户能自己决定的只有正文页。
 * 要换页型是生成完之后在页面编辑里的事。
 *
 * `attach="body"`：弹窗挂在 body 上，而不是留在工作台那三栏里头 ——
 * 那一层套着 `overflow: hidden` 的 flex 布局，弹窗跟着它走迟早会被谁裁掉。
 */
import { computed, ref, watch } from 'vue'

const props = defineProps<{
  visible: boolean
  mode: 'chapter' | 'page'
  /** 说明这一项会落在哪儿（加页时是那一章的标题） */
  context: string
  /** 现有章数，用来给新章起个「第 N 章」的名字 */
  chapterCount: number
}>()

const emit = defineEmits<{
  'update:visible': [visible: boolean]
  confirm: [payload: { chapterTitle: string; pageTitle: string }]
}>()

const chapterTitle = ref('')
const pageTitle = ref('')

const isChapter = computed(() => props.mode === 'chapter')
const header = computed(() => (isChapter.value ? '新增章节' : '新增页面'))

/** 每次打开都重新起名：上一次输了一半的标题不该跟着跑过来。 */
watch(
  () => props.visible,
  (visible) => {
    if (!visible) return
    chapterTitle.value = isChapter.value ? `第 ${props.chapterCount + 1} 章 · 新章节` : ''
    pageTitle.value = '新页面'
  },
  { immediate: true },
)

const filled = computed(
  () => pageTitle.value.trim().length > 0 && (!isChapter.value || chapterTitle.value.trim().length > 0),
)

function close(): void {
  emit('update:visible', false)
}

function submit(): void {
  if (!filled.value) return
  emit('confirm', {
    chapterTitle: chapterTitle.value.trim(),
    pageTitle: pageTitle.value.trim(),
  })
}
</script>

<template>
  <t-dialog
    :visible="visible"
    attach="body"
    :header="header"
    :confirm-btn="{ content: '添加', disabled: !filled }"
    cancel-btn="取消"
    width="440px"
    @update:visible="emit('update:visible', $event)"
    @confirm="submit"
    @cancel="close"
    @close="close"
  >
    <t-form :label-width="76" @submit.prevent>
      <t-form-item v-if="isChapter" label="章节名">
        <t-input v-model="chapterTitle" placeholder="例如：第三章 · 神经网络基础" />
      </t-form-item>
      <t-form-item :label="isChapter ? '第一页' : '页标题'">
        <t-input
          v-model="pageTitle"
          placeholder="这一页讲什么"
          @enter="submit"
        />
      </t-form-item>
    </t-form>

    <p class="hint">
      <template v-if="isChapter">
        新章节自带一页正文 —— 一章没有正文页，提交时会被服务端整章丢掉。
      </template>
      <template v-else>会加在{{ context }}的末尾。</template>
      页型是「概念讲解」，内容由模型在写页那一步生成。
    </p>
  </t-dialog>
</template>

<style scoped>
.hint {
  font-size: 12px;
  line-height: 1.8;
  color: var(--td-text-placeholder);
}
</style>
