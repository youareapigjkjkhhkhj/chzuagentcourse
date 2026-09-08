<script setup>
import { computed } from "vue";
import { Check, Circle, Loader2 } from "@lucide/vue";

const props = defineProps({
  job: {
    type: Object,
    default: null
  }
});

const stages = [
  { label: "规划", at: 8 },
  { label: "搜索", at: 22 },
  { label: "阅读", at: 42 },
  { label: "RAG", at: 58 },
  { label: "分析", at: 72 },
  { label: "撰写", at: 86 },
  { label: "保存", at: 94 },
  { label: "完成", at: 100 }
];

const progress = computed(() => props.job?.progress || 0);

function stateFor(stage) {
  if (!props.job) return "pending";
  if (props.job?.status === "failed") return "failed";
  if (progress.value >= stage.at) return "done";
  const previous = stages[stages.indexOf(stage) - 1];
  if (!previous || progress.value >= previous.at) return "active";
  return "pending";
}
</script>

<template>
  <div class="timeline" aria-label="任务进度">
    <div class="progress-rail">
      <div class="progress-fill" :style="{ width: `${progress}%` }"></div>
    </div>
    <div
      v-for="stage in stages"
      :key="stage.label"
      class="timeline-step"
      :class="stateFor(stage)"
    >
      <span class="step-icon">
        <Check v-if="stateFor(stage) === 'done'" :size="15" />
        <Loader2 v-else-if="stateFor(stage) === 'active'" :size="15" class="spin" />
        <Circle v-else :size="12" />
      </span>
      <span>{{ stage.label }}</span>
    </div>
  </div>
</template>
