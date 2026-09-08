/**
 * MCP 环境变量占位符解析（P5 任务 4）：
 * `${VAR}` 从系统环境变量注入；缺失时报错（仅提变量名，不泄露任何值）；
 * 解析结果只用于子进程启动参数，不落盘、不进日志。
 */
const PLACEHOLDER = /\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g;

export function resolveEnv(
  env: Record<string, string> | undefined,
  source: NodeJS.ProcessEnv = process.env,
): Record<string, string> {
  const out: Record<string, string> = {};
  if (!env) return out;
  for (const [key, raw] of Object.entries(env)) {
    out[key] = raw.replace(PLACEHOLDER, (_all, name: string) => {
      const value = source[name];
      if (value === undefined || value === '') {
        throw new Error(`环境变量未定义：\${${name}}（请在系统中设置该变量后重连）`);
      }
      return value;
    });
  }
  return out;
}
