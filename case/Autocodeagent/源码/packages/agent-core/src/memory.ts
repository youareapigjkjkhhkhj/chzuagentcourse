/**
 * 工作区级持久记忆（Tier3「越用越懂这个工作区」）：<ws>/.AgentBuddy/memory.md 单文件、条目带日期、追加式。
 * - appendMemory：remember 工具追加一条（首次创建写文件头，mkdir -p .AgentBuddy）；
 * - readMemory：assembleContext 每轮读取注入系统提示（缺失/空→null；超上限保近端尾部，新记忆更相关）。
 * 与 SkillHub 项目级目录 <ws>/.AgentBuddy/skills 同处 .AgentBuddy（工作区级 app 数据约定）。
 * memory 是工作区独立文件（非会话态），故 agent-core 自持读写，无需经 todo_write 那样的外层回调落盘。
 */
import { appendFile, mkdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';

export const MEMORY_DIR = '.AgentBuddy';
export const MEMORY_FILE = 'memory.md';
/** 注入系统提示的记忆正文上限（字符）：超出保近端尾部；与 PROJECT_INSTRUCTION_LIMIT 同量级 */
const MEMORY_LIMIT = 8000;
/** 首次创建写入的文件头（说明用途 + 可手动编辑） */
const MEMORY_HEADER = '# AgentBuddy 工作区记忆\n\n<!-- 由 remember 工具自动追加，可手动编辑；每条以 [日期] 开头，新条目在末尾。 -->\n\n';

/** 工作区记忆文件绝对路径 */
export function memoryPath(workspace: string): string {
  return join(workspace, MEMORY_DIR, MEMORY_FILE);
}

/** 本地日期戳 YYYY-MM-DD（记忆按天可追溯，对齐「memory-09-21」的日粒度直觉） */
function dateStamp(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * 追加一条记忆：mkdir -p .AgentBuddy → 文件不存在则先写头 → append `- [日期] 文本`。
 * 返回写入的整行（供工具回执）。多行文本压成单行以保持「一条 = 一个 bullet」的结构。
 */
export async function appendMemory(workspace: string, text: string): Promise<string> {
  const dir = join(workspace, MEMORY_DIR);
  const file = join(dir, MEMORY_FILE);
  await mkdir(dir, { recursive: true });
  const oneLine = text.replace(/\s*[\r\n]+\s*/g, ' ').trim();
  const line = `- [${dateStamp()}] ${oneLine}\n`;
  const exists = await readFile(file, 'utf-8').then(
    () => true,
    () => false,
  );
  await appendFile(file, exists ? line : `${MEMORY_HEADER}${line}`, 'utf-8');
  return line.trimEnd();
}

/**
 * 读取记忆供注入：缺失/空 → null；超 MEMORY_LIMIT 保近端尾部并对齐到行首（新记忆更相关），前置省略提示。
 */
export async function readMemory(workspace: string): Promise<string | null> {
  const raw = await readFile(memoryPath(workspace), 'utf-8').catch(() => null);
  if (raw === null) return null;
  const body = raw.trim();
  if (!body) return null;
  if (body.length <= MEMORY_LIMIT) return body;
  const tail = body.slice(-MEMORY_LIMIT);
  const nl = tail.indexOf('\n');
  return `…（较早记忆已省略，仅保留最近部分）\n${nl >= 0 ? tail.slice(nl + 1) : tail}`;
}
