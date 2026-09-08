<script setup>
import { computed } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";

const props = defineProps({
  content: {
    type: String,
    default: ""
  }
});

marked.setOptions({
  breaks: true,
  gfm: true
});

const html = computed(() => DOMPurify.sanitize(marked.parse(props.content || "")));
</script>

<template>
  <article v-if="content" class="report-preview" v-html="html"></article>
  <div v-else class="empty-report">
    <strong>报告预览</strong>
    <span>提交主题后，生成内容会显示在这里。</span>
  </div>
</template>
