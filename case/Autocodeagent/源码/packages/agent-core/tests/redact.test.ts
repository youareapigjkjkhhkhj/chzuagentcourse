/** P6 任务 2：日志脱敏中间件单测（验收：脱敏断言，Key 不出现在任何日志） */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearSecrets, logger, redact, registerSecret } from '../src/redact';

afterEach(() => clearSecrets());

describe('redact 脱敏', () => {
  it('已登记敏感串全部替换为 ***（多次出现均替换）', () => {
    registerSecret('sk-live-abcdef123456');
    expect(redact('key=sk-live-abcdef123456 & again sk-live-abcdef123456')).toBe('key=*** & again ***');
  });

  it('多个敏感串叠加脱敏', () => {
    registerSecret('sk-first-secret-01');
    registerSecret('${TOKEN}-resolved-value');
    expect(redact('a=sk-first-secret-01 b=${TOKEN}-resolved-value')).toBe('a=*** b=***');
  });

  it('长度 <6 的值不登记（避免误伤短词造成日志大面积替换）', () => {
    registerSecret('abc');
    expect(redact('abc abc')).toBe('abc abc');
  });

  it('空 / undefined 登记忽略', () => {
    registerSecret('');
    registerSecret(undefined);
    registerSecret(null);
    expect(redact('hello world')).toBe('hello world');
  });

  it('clearSecrets 后恢复原文', () => {
    registerSecret('super-secret-value-99');
    clearSecrets();
    expect(redact('super-secret-value-99')).toBe('super-secret-value-99');
  });
});

describe('logger 统一出口', () => {
  it('字符串参数先脱敏再交 console；非字符串原样透传', () => {
    registerSecret('super-secret-value-99');
    const spy = vi.spyOn(console, 'info').mockImplementation(() => undefined);
    logger.info('leak: super-secret-value-99', { code: 1 });
    expect(spy).toHaveBeenCalledWith('leak: ***', { code: 1 });
    spy.mockRestore();
  });

  it('warn / error 同样脱敏', () => {
    registerSecret('another-secret-value');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    logger.warn('w another-secret-value');
    logger.error('e another-secret-value');
    expect(warn).toHaveBeenCalledWith('w ***');
    expect(error).toHaveBeenCalledWith('e ***');
    warn.mockRestore();
    error.mockRestore();
  });
});
