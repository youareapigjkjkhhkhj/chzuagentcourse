<script setup>
import { SearchCheck } from "@lucide/vue";

defineProps({
  evidence: {
    type: Array,
    default: () => []
  }
});

function relevancePercent(score) {
  const value = Number(score || 0);
  return Math.round(Math.max(0, Math.min(1, value)) * 100);
}
</script>

<template>
  <section class="evidence-list">
    <div class="section-heading">
      <SearchCheck :size="18" />
      <h2>RAG 证据</h2>
    </div>
    <div v-if="!evidence.length" class="empty-panel">暂无检索证据</div>
    <article v-for="item in evidence" :key="item.id" class="evidence-item">
      <div class="evidence-meta">
        <strong>{{ item.title }}</strong>
        <span>{{ item.relevance || "可参考" }} · 本次相关度 {{ relevancePercent(item.score) }}%</span>
      </div>
      <p>{{ item.text }}</p>
      <a v-if="item.arxiv_url" :href="item.arxiv_url" target="_blank" rel="noreferrer">查看来源</a>
    </article>
  </section>
</template>
