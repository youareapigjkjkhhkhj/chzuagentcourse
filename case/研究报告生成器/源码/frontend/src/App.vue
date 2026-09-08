<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import {
  BookOpen,
  Brain,
  Download,
  FileDown,
  History,
  KeyRound,
  Play,
  RefreshCw,
  ServerCog,
  Settings2,
  Sparkles
} from "@lucide/vue";
import EvidenceList from "./components/EvidenceList.vue";
import PaperCard from "./components/PaperCard.vue";
import ProgressTimeline from "./components/ProgressTimeline.vue";
import ReportPreview from "./components/ReportPreview.vue";
import { createReport, downloadUrl, getReport, listReports } from "./services/api";

const API_SETTINGS_KEY = "research-assistant-api-settings";

const providerDefaults = {
  deepseek: {
    label: "DeepSeek",
    model: "deepseek-chat",
    base_url: "https://api.deepseek.com"
  },
  openai: {
    label: "OpenAI",
    model: "gpt-5-mini",
    base_url: ""
  },
  custom: {
    label: "自定义兼容接口",
    model: "",
    base_url: ""
  }
};

const form = reactive({
  topic: "Quantum Computing Advances 2025",
  max_results: 5,
  years_back: 0,
  paper_source: "arxiv",
  max_chars_per_paper: 5000,
  top_k: 8,
  language: "auto",
  use_rag: true
});

const apiSettings = reactive({
  provider: "openai",
  api_key: "",
  model: providerDefaults.openai.model,
  base_url: providerDefaults.openai.base_url,
  remember: false
});

const job = ref(null);
const jobs = ref([]);
const loading = ref(false);
const error = ref("");
const pollTimer = ref(null);

const isRunning = computed(() => ["queued", "running"].includes(job.value?.status));
const canDownloadPdf = computed(() => Boolean(job.value?.files?.pdf));
const canDownloadMarkdown = computed(() => Boolean(job.value?.files?.markdown));
const selectedProvider = computed(() => providerDefaults[apiSettings.provider]);

onMounted(async () => {
  restoreApiSettings();
  await refreshJobs({ selectLatest: true });
});

onUnmounted(() => {
  stopPolling();
});

function restoreApiSettings() {
  const saved = window.localStorage.getItem(API_SETTINGS_KEY);
  if (!saved) return;

  try {
    const parsed = JSON.parse(saved);
    const provider = parsed.provider in providerDefaults ? parsed.provider : "openai";
    const defaults = providerDefaults[provider];
    Object.assign(apiSettings, {
      provider,
      api_key: parsed.api_key || "",
      model: parsed.model || defaults.model,
      base_url: parsed.base_url || defaults.base_url,
      remember: true
    });
  } catch {
    window.localStorage.removeItem(API_SETTINGS_KEY);
  }
}

function onProviderChange() {
  const defaults = providerDefaults[apiSettings.provider];
  apiSettings.model = defaults.model;
  apiSettings.base_url = defaults.base_url;
}

function persistApiSettings() {
  if (!apiSettings.remember) {
    window.localStorage.removeItem(API_SETTINGS_KEY);
    return;
  }

  window.localStorage.setItem(
    API_SETTINGS_KEY,
    JSON.stringify({
      provider: apiSettings.provider,
      api_key: apiSettings.api_key,
      model: apiSettings.model,
      base_url: apiSettings.base_url
    })
  );
}

async function refreshJobs(options = {}) {
  try {
    const result = await listReports();
    jobs.value = result.jobs || [];
    if (options.selectLatest && !job.value && jobs.value.length) {
      await openJob(jobs.value[0].id);
    }
  } catch {
    jobs.value = [];
  }
}

function buildPayload() {
  return {
    ...form,
    topic: form.topic.trim(),
    llm: {
      provider: apiSettings.provider,
      api_key: apiSettings.api_key.trim(),
      model: apiSettings.model.trim(),
      base_url: apiSettings.base_url.trim()
    }
  };
}

async function submit() {
  if (!form.topic.trim()) {
    error.value = "请输入研究主题";
    return;
  }

  if (apiSettings.provider === "custom" && !apiSettings.base_url.trim()) {
    error.value = "自定义接口需要填写 Base URL";
    return;
  }

  persistApiSettings();
  loading.value = true;
  error.value = "";
  stopPolling();

  try {
    const result = await createReport(buildPayload());
    job.value = result.job;
    await refreshJobs();
    startPolling(result.report_id);
  } catch (err) {
    error.value = err.message || "创建任务失败";
  } finally {
    loading.value = false;
  }
}

function startPolling(id) {
  pollTimer.value = window.setInterval(async () => {
    try {
      job.value = await getReport(id);
      if (!["queued", "running"].includes(job.value.status)) {
        stopPolling();
        await refreshJobs();
      }
    } catch (err) {
      error.value = err.message || "更新任务状态失败";
      stopPolling();
    }
  }, 1400);
}

function stopPolling() {
  if (pollTimer.value) {
    window.clearInterval(pollTimer.value);
    pollTimer.value = null;
  }
}

async function openJob(id) {
  error.value = "";
  stopPolling();
  job.value = await getReport(id);
  if (["queued", "running"].includes(job.value.status)) {
    startPolling(id);
  }
}
</script>

<template>
  <main class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark"><Brain :size="22" /></span>
        <div>
          <strong>Research Assistant</strong>
          <span>Multi-agent RAG workspace</span>
        </div>
      </div>

      <section class="control-surface">
        <div class="section-heading">
          <Sparkles :size="18" />
          <h1>新研究</h1>
        </div>

        <label class="field">
          <span>研究主题</span>
          <textarea v-model="form.topic" rows="4" maxlength="200" />
        </label>

        <label class="field">
          <span>论文源</span>
          <select v-model="form.paper_source">
            <option value="arxiv">arXiv</option>
            <option value="semantic_scholar">Semantic Scholar</option>
            <option value="europe_pmc">Europe PMC</option>
            <option value="crossref">Crossref</option>
            <option value="all_open">综合开放源</option>
          </select>
        </label>

        <div class="field-grid">
          <label class="field">
            <span>论文数</span>
            <input v-model.number="form.max_results" type="number" min="1" max="10" />
          </label>
          <label class="field">
            <span>证据数</span>
            <input v-model.number="form.top_k" type="number" min="1" max="20" />
          </label>
        </div>

        <label class="field">
          <span>发表时间范围</span>
          <select v-model.number="form.years_back">
            <option :value="0">不限时间</option>
            <option :value="1">近 1 年</option>
            <option :value="2">近 2 年</option>
            <option :value="3">近 3 年</option>
            <option :value="5">近 5 年</option>
          </select>
        </label>

        <label class="field">
          <span>每篇读取字符</span>
          <input v-model.number="form.max_chars_per_paper" type="range" min="1000" max="20000" step="1000" />
          <b>{{ form.max_chars_per_paper.toLocaleString() }}</b>
        </label>

        <label class="field">
          <span>报告语言</span>
          <select v-model="form.language">
            <option value="auto">跟随主题</option>
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </label>

        <label class="toggle-row">
          <input v-model="form.use_rag" type="checkbox" />
          <span>启用本地 RAG 证据检索</span>
        </label>
      </section>

      <section class="control-surface">
        <div class="section-heading">
          <KeyRound :size="18" />
          <h2>模型 API</h2>
        </div>

        <label class="field">
          <span>服务商</span>
          <select v-model="apiSettings.provider" @change="onProviderChange">
            <option value="deepseek">DeepSeek</option>
            <option value="openai">OpenAI</option>
            <option value="custom">自定义 OpenAI-compatible</option>
          </select>
        </label>

        <label class="field">
          <span>API Key</span>
          <input v-model="apiSettings.api_key" type="password" autocomplete="off" placeholder="留空则使用后端 .env" />
        </label>

        <label class="field">
          <span>模型</span>
          <input v-model="apiSettings.model" type="text" :placeholder="selectedProvider.model || 'model-name'" />
        </label>

        <label v-if="apiSettings.provider !== 'openai'" class="field">
          <span>Base URL</span>
          <input v-model="apiSettings.base_url" type="url" :placeholder="selectedProvider.base_url || 'https://api.example.com/v1'" />
        </label>

        <label class="toggle-row">
          <input v-model="apiSettings.remember" type="checkbox" />
          <span>记住在本机浏览器</span>
        </label>

        <p class="muted-note">
          Key 只发送到本地后端用于本次生成；任务记录不会保存明文 Key。
        </p>

        <button class="primary-action" :disabled="loading || isRunning" @click="submit">
          <Play v-if="!loading" :size="18" />
          <RefreshCw v-else :size="18" class="spin" />
          {{ loading || isRunning ? "研究中" : "生成报告" }}
        </button>

        <p v-if="error" class="error">{{ error }}</p>
      </section>

      <section class="history-panel">
        <div class="section-heading">
          <History :size="18" />
          <h2>任务记录</h2>
        </div>
        <button
          v-for="item in jobs.slice(0, 8)"
          :key="item.id"
          class="history-item"
          :class="{ active: item.id === job?.id }"
          @click="openJob(item.id)"
        >
          <span>{{ item.topic }}</span>
          <small>{{ item.status }} · {{ item.progress }}%</small>
        </button>
        <div v-if="!jobs.length" class="empty-mini">暂无记录</div>
      </section>
    </aside>

    <section class="workspace">
      <header class="workspace-header">
        <div>
          <span class="eyebrow"><Settings2 :size="15" /> Agent pipeline</span>
          <h2>{{ job?.topic || "准备开始一份新报告" }}</h2>
          <p>{{ job?.stage || "设置主题、模型 API 和检索参数后开始生成。" }}</p>
        </div>
        <div class="download-group">
          <a
            class="icon-button"
            :class="{ disabled: !canDownloadMarkdown }"
            :href="canDownloadMarkdown ? downloadUrl(job.id, 'markdown') : undefined"
          >
            <Download :size="18" />
            Markdown
          </a>
          <a
            class="icon-button"
            :class="{ disabled: !canDownloadPdf }"
            :href="canDownloadPdf ? downloadUrl(job.id, 'pdf') : undefined"
          >
            <FileDown :size="18" />
            PDF
          </a>
        </div>
      </header>

      <section class="status-band">
        <ProgressTimeline :job="job" />
        <div class="status-number">{{ job?.progress || 0 }}%</div>
      </section>

      <div v-if="job?.llm" class="model-strip">
        <ServerCog :size="17" />
        <span>{{ job.llm.provider }}</span>
        <strong>{{ job.llm.model || "env default" }}</strong>
        <small>{{ job.llm.has_api_key ? "使用前端输入 Key" : "使用后端环境变量" }}</small>
      </div>

      <div v-if="job?.search" class="model-strip">
        <BookOpen :size="17" />
        <span>论文检索</span>
        <strong>{{ job.search.source_label || "arXiv" }}</strong>
        <small>{{ job.search.years_back ? `近 ${job.search.years_back} 年` : "不限时间" }}</small>
        <small>按来源支持的日期字段过滤</small>
      </div>

      <div v-if="job?.warnings?.length" class="warning-strip">
        <strong>提示</strong>
        <span>{{ job.warnings.join("；") }}</span>
      </div>
      <div v-if="job?.status === 'failed'" class="error-strip">
        <strong>任务失败</strong>
        <span>{{ job.error }}</span>
      </div>

      <div class="content-grid">
        <section class="report-panel">
          <div class="section-heading">
            <BookOpen :size="18" />
            <h2>报告预览</h2>
          </div>
          <ReportPreview :content="job?.report || ''" />
        </section>

        <aside class="insight-column">
          <EvidenceList :evidence="job?.evidence || []" />

          <section class="paper-list">
            <div class="section-heading">
              <BookOpen :size="18" />
              <h2>检索论文</h2>
            </div>
            <div v-if="!job?.papers?.length" class="empty-panel">暂无论文结果</div>
            <PaperCard v-for="paper in job?.papers || []" :key="paper.arxiv_url" :paper="paper" />
          </section>

          <section class="log-panel">
            <h2>运行日志</h2>
            <ol>
              <li v-for="entry in job?.logs || []" :key="entry.time + entry.message">
                {{ entry.message }}
              </li>
            </ol>
          </section>
        </aside>
      </div>
    </section>
  </main>
</template>
