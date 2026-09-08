/**
 * 日志脱敏中间件（P6 任务 2）：
 * API Key / ${VAR} 解析值等敏感串经 registerSecret 登记后，
 * redact() 将其替换为 ***；Main 进程统一经 logger 输出，敏感值不出现在任何日志。
 */
const secrets = new Set<string>();

/** 登记敏感值（长度 < 6 忽略，避免误伤短词造成日志大面积替换） */
export function registerSecret(value: string | undefined | null): void {
  if (value && value.length >= 6) secrets.add(value);
}

/** 单测隔离用 */
export function clearSecrets(): void {
  secrets.clear();
}

/** 将文本中所有已登记敏感串替换为 *** */
export function redact(text: string): string {
  let out = text;
  for (const s of secrets) {
    if (out.includes(s)) out = out.split(s).join('***');
  }
  return out;
}

function scrub(arg: unknown): unknown {
  return typeof arg === 'string' ? redact(arg) : arg;
}

/** Main 进程统一日志出口：字符串参数先脱敏再交 console */
export const logger = {
  info(...args: unknown[]): void {
    console.info(...args.map(scrub));
  },
  warn(...args: unknown[]): void {
    console.warn(...args.map(scrub));
  },
  error(...args: unknown[]): void {
    console.error(...args.map(scrub));
  },
};
