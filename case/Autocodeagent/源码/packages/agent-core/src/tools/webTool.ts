/**
 * 联网工具（借鉴 opencode webfetch/websearch）：
 * - webfetch：抓取网页并提取正文，内置零配置（进 createBuiltinBus）；
 * - websearch：Tavily 关键词搜索，需 API key，由外层工厂注入（不进 ToolContext、不硬编码于 Loop，AGENTS §13）。
 * 二者均 risk=NETWORK：权限矩阵 Plan 拒绝 / Ask·Auto 询问（§14），无需改 permission.ts。
 * 正文提取轻量自实现，不引入 HTML 解析依赖（§28）；apiKey 经 registerSecret 登记，绝不出现在日志/错误。
 */
import { registerSecret } from '../redact';
import { num, str, type Tool } from './types';

/** 抓取正文上限（防上下文膨胀）；超出截断并提示 */
const FETCH_MAX_CHARS = 20_000;
/** 响应体字节上限（5MB），下载中超限即中止，防大文件 OOM */
const FETCH_MAX_BYTES = 5 * 1024 * 1024;
/** 单次联网请求超时（ms）；orchestrator 另有 60s 外层工具超时兜底 */
const REQUEST_TIMEOUT_MS = 30_000;
/** 伪装浏览器 UA，规避部分站点对默认 fetch UA 的拦截 */
const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

/** fetch 第二参类型：从全局 fetch 推导，避免依赖 DOM/undici 具名类型（lib 仅 ES2022） */
type FetchInit = Parameters<typeof fetch>[1];

/* ─────────────────────────── webfetch ─────────────────────────── */

export const webfetchTool: Tool = {
  name: 'webfetch',
  description:
    '抓取指定 URL 的网页并提取正文（纯文本），用于阅读在线文档、文章、说明页等。仅支持 http/https；正文过长会截断。需要实时/最新信息请配合 websearch。',
  parameters: {
    type: 'object',
    properties: {
      url: { type: 'string', description: '完整 URL，须以 http:// 或 https:// 开头' },
    },
    required: ['url'],
  },
  risk: 'NETWORK',
  async execute(ctx, input) {
    const url = str(input, 'url').trim();
    assertHttpUrl(url);
    const res = await fetchLinked(url, ctx.signal, REQUEST_TIMEOUT_MS, {
      headers: { 'user-agent': UA, accept: 'text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8' },
    });
    if (!res.ok) throw await httpError(res, `抓取失败 ${url}`);

    const ctype = (res.headers.get('content-type') ?? '').toLowerCase();
    const raw = new TextDecoder().decode(await readBodyLimited(res, FETCH_MAX_BYTES));
    const isHtml = ctype.includes('html') || (!ctype.includes('json') && looksLikeHtml(raw));
    const body = (isHtml ? htmlToText(raw) : raw.trim()).replace(/\n{3,}/g, '\n\n');
    if (!body) {
      return { text: `（${url} 未提取到正文：可能是空页面、纯图片/附件，或内容需脚本渲染，webfetch 无法执行 JS）` };
    }
    const title = isHtml ? extractTitle(raw) : '';
    const truncated = body.length > FETCH_MAX_CHARS;
    const head = `URL: ${url}${title ? `\n标题: ${title}` : ''}\n${'─'.repeat(40)}\n`;
    return { text: head + (truncated ? body.slice(0, FETCH_MAX_CHARS) : body) + (truncated ? `\n…（正文过长，已截断至 ${FETCH_MAX_CHARS} 字）` : '') };
  },
};

/* ─────────────────────────── websearch（Tavily） ─────────────────────────── */

export interface WebSearchOptions {
  /** Tavily API key（tvly-…）；由外层从 KeyStore 解密注入 */
  apiKey: string;
  /** 预留多 provider 扩展；当前仅实现 tavily */
  provider?: 'tavily';
}

const TAVILY_ENDPOINT = 'https://api.tavily.com/search';
const SEARCH_MAX_RESULTS = 10;
const SEARCH_DEFAULT_RESULTS = 5;

interface TavilyResult {
  title?: string;
  url?: string;
  content?: string;
}
interface TavilyResponse {
  answer?: string;
  results?: TavilyResult[];
}

/**
 * 构造联网搜索工具（仿 createSkillTool 工厂：依赖构造时注入，Loop 无工具分支）。
 * 仅当用户在设置中开启联网搜索并配置了 Tavily key 时由 ChatService 注入。
 */
export function createWebSearchTool(opts: WebSearchOptions): Tool {
  registerSecret(opts.apiKey); // 登记脱敏：key 绝不进日志/错误文本
  return {
    name: 'websearch',
    description:
      '联网搜索实时信息（新闻、时效问答、文档、价格、版本等本地知识不足的场景），返回若干条结果（标题/链接/摘要）与一段直接答案。得到链接后可用 webfetch 抓取完整正文。',
    parameters: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '搜索关键词（自然语言即可）' },
        maxResults: { type: 'number', description: `返回结果条数（默认 ${SEARCH_DEFAULT_RESULTS}，最多 ${SEARCH_MAX_RESULTS}）` },
      },
      required: ['query'],
    },
    risk: 'NETWORK',
    async execute(ctx, input) {
      const query = str(input, 'query').trim();
      if (!query) throw new Error('参数 query 不能为空');
      const maxResults = Math.min(SEARCH_MAX_RESULTS, Math.max(1, num(input, 'maxResults', SEARCH_DEFAULT_RESULTS)));
      const res = await fetchLinked(TAVILY_ENDPOINT, ctx.signal, REQUEST_TIMEOUT_MS, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${opts.apiKey}` },
        body: JSON.stringify({ query, max_results: maxResults, search_depth: 'basic', include_answer: true }),
      });
      if (!res.ok) throw await searchHttpError(res);
      const data = (await res.json()) as TavilyResponse;
      return { text: formatSearchResults(query, data) };
    },
  };
}

function formatSearchResults(query: string, data: TavilyResponse): string {
  const results = Array.isArray(data.results) ? data.results : [];
  const answer = typeof data.answer === 'string' ? data.answer.trim() : '';
  if (results.length === 0 && !answer) return `（未找到与「${query}」相关的结果，可换关键词重试）`;
  const lines: string[] = [`搜索：${query}`];
  if (answer) lines.push(`\n答案：${answer}`);
  if (results.length > 0) {
    lines.push('\n结果：');
    results.forEach((r, i) => {
      const snippet = (r.content ?? '').replace(/\s+/g, ' ').trim().slice(0, 300);
      lines.push(`${i + 1}. ${r.title?.trim() || '(无标题)'}\n   ${r.url ?? ''}${snippet ? `\n   ${snippet}` : ''}`);
    });
    lines.push('\n（如需完整内容，用 webfetch 抓取上述链接）');
  }
  return lines.join('\n');
}

/* ─────────────────────────── HTML → 正文（轻量自实现） ─────────────────────────── */

/**
 * HTML → 可读纯文本（不引依赖）：移除脚本/样式/注释等不可见块 → 块级结束标签转换行 →
 * 剥除剩余标签 → 解 HTML 实体 → 压缩空白。目标是「够 LLM 理解页面主旨」，非完美还原排版。
 */
export function htmlToText(html: string): string {
  let s = html;
  // 1) 移除含内容的不可见/非正文块
  s = s.replace(/<(script|style|noscript|svg|head|template)\b[\s\S]*?<\/\1>/gi, ' ');
  s = s.replace(/<!--[\s\S]*?-->/g, ' ');
  // 2) 块级结束标签与 <br> → 换行，保留段落结构
  s = s.replace(/<\/(p|div|section|article|aside|li|tr|h[1-6]|blockquote|pre|ul|ol|dl|table|header|footer|figure|figcaption)\s*>/gi, '\n');
  s = s.replace(/<br\s*\/?>/gi, '\n');
  // 3) 剥除其余所有标签
  s = s.replace(/<[^>]+>/g, ' ');
  // 4) 解实体（数值实体先于命名实体，命名实体单趟解码，天然避免二次解码）
  s = decodeEntities(s);
  // 5) 压缩空白：行内多空白合一、去行首尾空白、多空行合一
  s = s.replace(/[ \t\r\f\v]+/g, ' ');
  s = s.split('\n').map((l) => l.trim()).join('\n');
  return s.replace(/\n{3,}/g, '\n\n').trim();
}

const NAMED_ENTITIES: Record<string, string> = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  hellip: '…', mdash: '—', ndash: '–', middot: '·', bull: '•',
  lsquo: '\u2018', rsquo: '\u2019', ldquo: '\u201C', rdquo: '\u201D',
  copy: '©', reg: '®', trade: '™', times: '×', divide: '÷', deg: '°',
};

function decodeEntities(s: string): string {
  return s
    .replace(/&#x([0-9a-f]+);/gi, (_, h: string) => fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d: string) => fromCodePoint(parseInt(d, 10)))
    .replace(/&([a-z][a-z0-9]*);/gi, (m, name: string) => NAMED_ENTITIES[name.toLowerCase()] ?? m);
}

function fromCodePoint(code: number): string {
  if (!Number.isFinite(code) || code < 0 || code > 0x10ffff) return '';
  try {
    return String.fromCodePoint(code);
  } catch {
    return '';
  }
}

function extractTitle(html: string): string {
  const m = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html);
  return m ? decodeEntities(m[1]!).replace(/\s+/g, ' ').trim().slice(0, 200) : '';
}

function looksLikeHtml(text: string): boolean {
  return /^\s*<(?:!doctype\s+html|html|head|body|div|p)\b/i.test(text);
}

/* ─────────────────────────── HTTP 辅助 ─────────────────────────── */

function assertHttpUrl(url: string): void {
  if (!/^https?:\/\//i.test(url)) throw new Error(`URL 必须以 http:// 或 https:// 开头：${url}`);
  try {
    // eslint-disable-next-line no-new
    new URL(url);
  } catch {
    throw new Error(`URL 非法：${url}`);
  }
}

/**
 * fetch + 超时 + 用户取消联动：手动 AbortController 同时挂接外层 signal 与超时定时器，
 * 完成后清理定时器与监听（不依赖 AbortSignal.any，兼容更广）。超时以带原因的 abort 抛出可读错误。
 */
async function fetchLinked(url: string, signal: AbortSignal, timeoutMs: number, init: FetchInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error(`联网请求超时（${timeoutMs / 1000}s）：${url}`)), timeoutMs);
  const onAbort = (): void => controller.abort(signal.reason);
  if (signal.aborted) controller.abort(signal.reason);
  else signal.addEventListener('abort', onAbort, { once: true });
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', onAbort);
  }
}

/** 按字节上限流式读取响应体，超限即取消并抛错（防大文件撑爆内存/上下文） */
async function readBodyLimited(res: Response, maxBytes: number): Promise<Uint8Array> {
  if (!res.body) return new Uint8Array();
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel().catch(() => undefined);
      throw new Error(`响应体超过 ${Math.round(maxBytes / 1024 / 1024)}MB 上限，已中止读取`);
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.byteLength;
  }
  return out;
}

/** 读取错误响应体作根因（截断防刷屏）；不含任何密钥 */
async function readDetail(res: Response): Promise<string> {
  try {
    return (await res.text()).replace(/\s+/g, ' ').trim().slice(0, 300);
  } catch {
    return '';
  }
}

async function httpError(res: Response, prefix: string): Promise<Error> {
  const detail = await readDetail(res);
  const hint =
    res.status === 401 || res.status === 403 ? '（可能需要登录或被反爬拦截）'
    : res.status === 404 ? '（页面不存在）'
    : res.status === 429 ? '（触发限流，请稍后重试）'
    : res.status >= 500 ? '（目标站点服务端错误）'
    : '';
  return new Error(`${prefix}：HTTP ${res.status}${hint}${detail ? ` — ${detail}` : ''}`);
}

async function searchHttpError(res: Response): Promise<Error> {
  const detail = await readDetail(res);
  const hint =
    res.status === 401 ? '（Tavily API key 无效或已过期，请在「设置 → 联网搜索」检查）'
    : res.status === 429 ? '（Tavily 触发限流或额度用尽，请稍后重试）'
    : res.status === 432 || res.status === 433 ? '（Tavily 账号/额度异常，请检查订阅状态）'
    : '';
  return new Error(`联网搜索失败：HTTP ${res.status}${hint}${detail ? ` — ${detail}` : ''}`);
}
