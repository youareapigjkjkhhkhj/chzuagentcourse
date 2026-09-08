/** httpError：从错误响应体提取服务端具体原因（vLLM/OpenAI 的 {"error":{"message"}}），
 *  不再只报 statusText——离线 vLLM 的 400「maximum context length」等根因此前被吞掉。 */
import { describe, expect, it } from 'vitest';
import { httpError } from '../src/llm/client';

describe('httpError 提取响应体根因', () => {
  it('vLLM 400：附加 error.message（上下文超窗的具体原因）', async () => {
    const body = JSON.stringify({
      object: 'error',
      message: "This model's maximum context length is 32768 tokens. However, you requested 40000 tokens.",
      type: 'BadRequestError',
      code: 400,
    });
    const err = await httpError(new Response(body, { status: 400, statusText: 'Bad Request' }));
    expect(err.message).toContain('400');
    expect(err.message).toContain('maximum context length');
  });

  it('OpenAI 风格 {message} 顶层字段也能提取', async () => {
    const err = await httpError(new Response(JSON.stringify({ message: 'invalid tools schema' }), { status: 400 }));
    expect(err.message).toContain('invalid tools schema');
  });

  it('非 JSON body（代理 HTML/纯文本）：回退原始文本', async () => {
    const err = await httpError(new Response('upstream connect error', { status: 502, statusText: 'Bad Gateway' }));
    expect(err.message).toContain('upstream connect error');
  });

  it('401 附 Key 排查提示；空 body 不报错', async () => {
    const err = await httpError(new Response('', { status: 401, statusText: 'Unauthorized' }));
    expect(err.message).toContain('API Key');
  });
});
