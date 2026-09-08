/**
 * MCP env ${VAR} 占位符解析单测（P5 任务 4）：
 * 替换 / 多占位 / 缺失抛错（仅提变量名）/ 无占位透传 / 空入参。
 */
import { describe, expect, it } from 'vitest';
import { resolveEnv } from '../src/mcp/env';

const SOURCE = { GITHUB_TOKEN: 'tok-123', REGION: 'cn-east' };

describe('resolveEnv', () => {
  it('单个 ${VAR} 占位替换为环境变量值', () => {
    expect(resolveEnv({ TOKEN: '${GITHUB_TOKEN}' }, SOURCE)).toEqual({ TOKEN: 'tok-123' });
  });

  it('同一值内多个占位均可替换', () => {
    expect(resolveEnv({ MIXED: 'a-${GITHUB_TOKEN}-b-${REGION}' }, SOURCE)).toEqual({
      MIXED: 'a-tok-123-b-cn-east',
    });
  });

  it('无占位的值原样透传', () => {
    expect(resolveEnv({ PLAIN: 'hello', NUM: '42' }, SOURCE)).toEqual({ PLAIN: 'hello', NUM: '42' });
  });

  it('变量未定义 → 抛错且错误信息只提变量名（不泄露任何值）', () => {
    expect(() => resolveEnv({ TOKEN: '${MISSING_VAR}' }, SOURCE)).toThrow(/\$\{MISSING_VAR\}/);
    expect(() => resolveEnv({ TOKEN: '${MISSING_VAR}' }, SOURCE)).toThrow('环境变量未定义');
  });

  it('变量值为空串视同未定义', () => {
    expect(() => resolveEnv({ TOKEN: '${EMPTY}' }, { EMPTY: '' })).toThrow(/\$\{EMPTY\}/);
  });

  it('undefined / 空入参返回空映射', () => {
    expect(resolveEnv(undefined, SOURCE)).toEqual({});
    expect(resolveEnv({}, SOURCE)).toEqual({});
  });
});
