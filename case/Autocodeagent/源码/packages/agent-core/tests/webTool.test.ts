/**
 * 联网工具单测（借鉴 opencode webfetch/websearch）：
 * htmlToText 正文提取、webfetch 抓取/校验/截断/错误/取消联动、websearch(Tavily) 请求构造/参数校验/密钥不泄漏。
 * fetch 用 vi.stubGlobal 打桩 + 真实 Response，不发起真实网络请求；apiKey 登记后由 clearSecrets 复位防污染。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearSecrets, redact } from '../src/redact';
import { ReadState, type ToolContext } from '../src/tools/types';
import { createWebSearchTool, htmlToText, webfetchTool } from '../src/tools/webTool';

afterEach(() => {
  clearSecrets();
  vi.unstubAllGlobals();
});

function ctx(signal: AbortSignal = new AbortController().signal): ToolContext {
  return {
    workspace: null,
    signal,
    readState: new ReadState(),
    snapshot: async () => null,
    resolvePath: async (p) => p,
  };
}

/** 打桩全局 fetch，responder 返回真实 Response；返回 mock 以便断言调用次数/参数 */
function stubFetch(responder: (url: string, init: Record<string, any>) => Response | Promise<Response>) {
  const mock = vi.fn(async (url: string, init: Record<string, any>) => responder(url, init));
  vi.stubGlobal('fetch', mock);
  return mock;
}

describe('htmlToText 正文提取', () => {
  it('剥离脚本/样式/注释，块级标签转换行，清除其余标签', () => {
    const html =
      '<html><head><style>.a{color:red}</style><script>var secret=1;</script></head>' +
      '<body><h1>大标题</h1><p>第一段</p><!-- 隐藏注释 --><p>第二段</p></body></html>';
    const text = htmlToText(html);
    expect(text).not.toContain('color:red');
    expect(text).not.toContain('secret');
    expect(text).not.toContain('隐藏注释');
    expect(text).not.toContain('<');
    expect(text).toContain('大标题');
    expect(text).toContain('第一段');
    expect(text).toContain('第二段');
  });

  it('解码命名/数值实体，且 &amp;lt; 只解一层不二次解码', () => {
    expect(htmlToText('<p>a &amp; b &lt; c &gt; d &quot;e&quot;</p>')).toContain('a & b < c > d "e"');
    expect(htmlToText('<p>&#65;&#x42;</p>')).toBe('AB'); // 十进制 65=A，十六进制 42=B
    const once = htmlToText('<p>&amp;lt;</p>');
    expect(once).toContain('&lt;'); // 解一层得字面 &lt;
    expect(once).not.toContain('<'); // 不再二次解码为 <
  });

  it('压缩行内多空白与多余空行', () => {
    expect(htmlToText('<p>a    b\t\tc</p>\n\n\n<p>d</p>')).toBe('a b c\n\nd');
  });
});

describe('webfetch', () => {
  it('非 http/https URL 抛错且不触发 fetch', async () => {
    const mock = stubFetch(() => new Response('x', { status: 200 }));
    await expect(webfetchTool.execute(ctx(), { url: 'ftp://example.com/f' })).rejects.toThrow(/http/);
    await expect(webfetchTool.execute(ctx(), { url: 'file:///etc/passwd' })).rejects.toThrow(/http/);
    expect(mock).not.toHaveBeenCalled();
  });

  it('url 缺失/非字符串抛错', async () => {
    stubFetch(() => new Response('x', { status: 200 }));
    await expect(webfetchTool.execute(ctx(), {})).rejects.toThrow(/url/);
    await expect(webfetchTool.execute(ctx(), { url: 123 })).rejects.toThrow(/url/);
  });

  it('抓取 HTML：提取标题与正文，剥除标签', async () => {
    const html =
      '<html><head><title>页面标题</title></head><body><h1>你好世界</h1><p>这是正文内容。</p></body></html>';
    stubFetch(() => new Response(html, { status: 200, headers: { 'content-type': 'text/html; charset=utf-8' } }));
    const res = await webfetchTool.execute(ctx(), { url: 'https://example.com/a' });
    expect(res.text).toContain('URL: https://example.com/a');
    expect(res.text).toContain('标题: 页面标题');
    expect(res.text).toContain('你好世界');
    expect(res.text).toContain('这是正文内容。');
    expect(res.text).not.toContain('<h1>');
  });

  it('content-type=application/json：按纯文本返回，不剥标签', async () => {
    const json = '{"ok":true,"html":"<b>raw</b>"}';
    stubFetch(() => new Response(json, { status: 200, headers: { 'content-type': 'application/json' } }));
    const res = await webfetchTool.execute(ctx(), { url: 'https://api.example.com/x' });
    expect(res.text).toContain('{"ok":true');
    expect(res.text).toContain('<b>raw</b>');
  });

  it('正文超过 20000 字截断并提示', async () => {
    const big = `<p>${'x'.repeat(30000)}</p>`;
    stubFetch(() => new Response(big, { status: 200, headers: { 'content-type': 'text/html' } }));
    const res = await webfetchTool.execute(ctx(), { url: 'https://example.com/big' });
    expect(res.text).toContain('已截断至 20000 字');
    expect(res.text.length).toBeLessThan(21000);
  });

  it('HTTP 404 抛出含状态码的错误', async () => {
    stubFetch(() => new Response('not found', { status: 404 }));
    await expect(webfetchTool.execute(ctx(), { url: 'https://example.com/404' })).rejects.toThrow(/404/);
  });

  it('ctx.signal 已取消 → 传给 fetch 的 signal 联动为已取消', async () => {
    const ac = new AbortController();
    ac.abort();
    let passed: AbortSignal | undefined;
    stubFetch((_url, init) => {
      passed = init.signal as AbortSignal;
      throw new Error('aborted'); // 真实 fetch 在 signal 中止时会拒绝
    });
    await expect(webfetchTool.execute(ctx(ac.signal), { url: 'https://example.com/x' })).rejects.toThrow();
    expect(passed?.aborted).toBe(true);
  });
});

describe('websearch（Tavily）', () => {
  const KEY = 'tvly-super-secret-key-999';

  it('构造 Tavily 请求：POST + Bearer 头 + 正确 body，并格式化结果', async () => {
    let capturedUrl = '';
    let capturedInit: Record<string, any> = {};
    const mock = stubFetch((url, init) => {
      capturedUrl = url;
      capturedInit = init;
      return new Response(
        JSON.stringify({ answer: '直接答案', results: [{ title: '结果一', url: 'https://a.com', content: '摘要内容' }] }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    });
    const tool = createWebSearchTool({ apiKey: KEY });
    const res = await tool.execute(ctx(), { query: '今天天气' });

    expect(mock).toHaveBeenCalledTimes(1);
    expect(capturedUrl).toBe('https://api.tavily.com/search');
    expect(capturedInit.method).toBe('POST');
    expect(capturedInit.headers.authorization).toBe(`Bearer ${KEY}`);
    expect(JSON.parse(capturedInit.body as string)).toMatchObject({
      query: '今天天气',
      max_results: 5,
      search_depth: 'basic',
      include_answer: true,
    });
    expect(res.text).toContain('直接答案');
    expect(res.text).toContain('结果一');
    expect(res.text).toContain('https://a.com');
    expect(res.text).toContain('摘要内容');
  });

  it('空/空白 query 抛错且不触发 fetch', async () => {
    const mock = stubFetch(() => new Response('{}', { status: 200 }));
    const tool = createWebSearchTool({ apiKey: KEY });
    await expect(tool.execute(ctx(), { query: '   ' })).rejects.toThrow(/query/);
    expect(mock).not.toHaveBeenCalled();
  });

  it('maxResults 被夹到 [1,10]', async () => {
    const bodies: any[] = [];
    stubFetch((_url, init) => {
      bodies.push(JSON.parse(init.body as string));
      return new Response(JSON.stringify({ results: [] }), { status: 200 });
    });
    const tool = createWebSearchTool({ apiKey: KEY });
    await tool.execute(ctx(), { query: 'a', maxResults: 99 });
    await tool.execute(ctx(), { query: 'b', maxResults: 0 });
    expect(bodies[0].max_results).toBe(10);
    expect(bodies[1].max_results).toBe(1);
  });

  it('401 错误不含 apiKey；key 已登记可被 redact 打码', async () => {
    stubFetch(() => new Response('invalid auth', { status: 401 }));
    const tool = createWebSearchTool({ apiKey: KEY });
    const err = await tool.execute(ctx(), { query: 'x' }).then(
      () => null,
      (e: unknown) => e as Error,
    );
    expect(err).toBeInstanceOf(Error);
    expect(err!.message).toContain('401');
    expect(err!.message).not.toContain(KEY);
    expect(redact(`泄漏 ${KEY} 了`)).toBe('泄漏 *** 了');
  });

  it('无结果无答案时给出可换词提示', async () => {
    stubFetch(() => new Response(JSON.stringify({ results: [] }), { status: 200 }));
    const tool = createWebSearchTool({ apiKey: KEY });
    const res = await tool.execute(ctx(), { query: '冷门关键词' });
    expect(res.text).toContain('未找到');
    expect(res.text).toContain('冷门关键词');
  });
});
