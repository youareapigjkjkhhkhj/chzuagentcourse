<script setup>
import { ExternalLink } from "@lucide/vue";

defineProps({
  paper: {
    type: Object,
    required: true
  }
});
</script>

<template>
  <article class="paper-card">
    <div>
      <h3>{{ paper.title }}</h3>
      <p>{{ paper.authors }}</p>
      <span>{{ paper.source || "论文源" }} · {{ paper.published }}</span>
    </div>
    <p v-if="paper.search_query" class="query-chip">
      检索词：{{ paper.search_query }}
    </p>
    <p class="abstract">{{ paper.abstract }}</p>
    <a v-if="paper.arxiv_url" :href="paper.arxiv_url" target="_blank" rel="noreferrer">
      <ExternalLink :size="15" />
      原文
    </a>
  </article>
</template>
