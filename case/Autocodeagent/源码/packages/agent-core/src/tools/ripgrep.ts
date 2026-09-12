/**
 * ripgrep 加速（可选增强）：探测系统 rg，命中则用其极速检索 + 原生 .gitignore/隐藏/二进制过滤；
 * 无 rg、调用失败或正则与 Rust 引擎不兼容时，由调用方（fsRead 的 grep/glob）回退内置 walk，行为不劣化。
 * 统一用 execFile（数组参数不经 shell → 免注入），cwd 锁工作区、超时 + 输出上限兜底、AbortSignal 可中断。
 */
import { execFile } from 'node:child_process';
import { relative } from 'node:path';

/** 与内置 walk 的 SKIP_DIRS 对齐：即便工作区无 .gitignore 也跳过噪音目录（rg 用 --glob 排除） */
const SKIP_GLOBS = ['!node_modules', '!.git', '!dist', '!.agent', '!.AgentBuddy'];
const RG_TIMEOUT_MS = 15000;
const RG_MAX_BUFFER = 16 * 1024 * 1024;

/** 探测缓存：整个进程只探一次（rg 是否安装不会在运行期变化） */
let rgAvailable: Promise<boolean> | null = null;

/** 探测系统 rg（一次，缓存）：--version 成功即视为可用 */
export function detectRipgrep(): Promise<boolean> {
  if (!rgAvailable) {
    rgAvailable = new Promise<boolean>((resolve) => {
      execFile('rg', ['--version'], { timeout: 3000, windowsHide: true }, (err) => resolve(!err));
    });
  }
  return rgAvailable;
}

/** 执行 rg：退出码 1（无匹配）视为空结果；其余非零 / 超时 / spawn 失败均抛错（调用方据此回退 walk） */
function execRg(args: string[], cwd: string, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new Error('已取消')); return; }
    const child = execFile(
      'rg',
      args,
      { cwd, timeout: RG_TIMEOUT_MS, maxBuffer: RG_MAX_BUFFER, windowsHide: true },
      (err, stdout) => {
        signal.removeEventListener('abort', onAbort);
        if (err) {
          // rg 退出码 1 = 无匹配（正常），返回空 stdout；ENOENT/超时/退出码 2 等交由调用方回退
          const code = (err as Error & { code?: number | string }).code;
          if (code === 1) { resolve(''); return; }
          reject(err);
          return;
        }
        resolve(stdout);
      },
    );
    function onAbort(): void { child.kill('SIGKILL'); }
    signal.addEventListener('abort', onAbort, { once: true });
  });
}

function skipGlobArgs(): string[] {
  const out: string[] = [];
  for (const g of SKIP_GLOBS) out.push('--glob', g);
  return out;
}

/** rg --json 内容检索 → 「相对路径:行号: 内容」（截断到 max，与内置 grep 输出同构） */
export async function rgGrep(opts: {
  pattern: string;
  dir: string;
  root: string;
  ignoreCase?: boolean;
  max: number;
  signal: AbortSignal;
}): Promise<string[]> {
  // --hidden：与内置 walk 一致地检索隐藏文件（如 .cursor/.github），.git 仍由 SKIP_GLOBS 排除
  const args = ['--json', '--hidden', '--no-messages', ...skipGlobArgs()];
  if (opts.ignoreCase) args.push('--ignore-case');
  args.push('--regexp', opts.pattern, '--', opts.dir);
  const out = await execRg(args, opts.dir, opts.signal);
  return parseRgJson(out, opts.root, opts.max);
}

/** 解析 rg --json：仅取 type=match 事件，path 相对化到 root；非 UTF-8 路径（bytes 形式）跳过 */
export function parseRgJson(out: string, root: string, max: number): string[] {
  const rows: string[] = [];
  for (const line of out.split('\n')) {
    if (rows.length >= max) break;
    const trimmed = line.trim();
    if (!trimmed) continue;
    let ev: { type?: string; data?: { path?: { text?: string }; line_number?: number; lines?: { text?: string } } };
    try {
      ev = JSON.parse(trimmed);
    } catch {
      continue; // --json 逐行独立，个别残行不影响整体
    }
    if (ev.type !== 'match') continue;
    const abs = ev.data?.path?.text;
    if (!abs) continue;
    const text = (ev.data?.lines?.text ?? '').replace(/\r?\n$/, '');
    rows.push(`${relative(root, abs).replace(/\\/g, '/')}:${ev.data?.line_number ?? 0}: ${text}`);
  }
  return rows;
}

/** rg --files 文件清单（.gitignore/隐藏/二进制感知）→ 相对 root 路径（截断到 max） */
export async function rgFiles(opts: { dir: string; root: string; max: number; signal: AbortSignal }): Promise<string[]> {
  const args = ['--files', '--hidden', '--no-messages', ...skipGlobArgs(), '--', opts.dir];
  const out = await execRg(args, opts.dir, opts.signal);
  return parseRgFileList(out, opts.root, opts.max);
}

/** 解析 rg --files：每行一个绝对路径，相对化到 root（仅去尾随 CR，保留路径内空格） */
export function parseRgFileList(out: string, root: string, max: number): string[] {
  const files: string[] = [];
  for (const line of out.split('\n')) {
    if (files.length >= max) break;
    const abs = line.replace(/\r$/, '');
    if (!abs) continue;
    files.push(relative(root, abs).replace(/\\/g, '/'));
  }
  return files;
}
