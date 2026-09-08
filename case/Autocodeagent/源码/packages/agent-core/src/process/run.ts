/**
 * 进程管理（bash 专用，技术方案 §4.9 / AGENTS §16）：
 * run() 统一入口：cwd 强制工作区、超时、输出 ≤ limit 截断、平台化杀树。
 * AbortController 无法杀死 OS 进程树，超时与手动停止共用同一杀树路径。
 */
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';

export interface RunOptions {
  cwd: string;
  timeoutMs: number;
  /** stdout+stderr 合计上限（字节），超出截断 */
  outputLimit: number;
  signal?: AbortSignal;
}

export interface RunResult {
  output: string;
  exitCode: number | null;
  truncated: boolean;
  timedOut: boolean;
  ms: number;
}

export const DEFAULT_OUTPUT_LIMIT = 20 * 1024;

export function run(command: string, opts: RunOptions): Promise<RunResult> {
  const started = Date.now();
  const child: ChildProcessWithoutNullStreams =
    process.platform === 'win32'
      ? spawn('cmd.exe', ['/d', '/s', '/c', command], { cwd: opts.cwd, windowsHide: true })
      : spawn('/bin/sh', ['-c', command], { cwd: opts.cwd, detached: true });

  let output = '';
  let bytes = 0;
  let truncated = false;
  let timedOut = false;
  let settled = false;

  const feed = (chunk: Buffer): void => {
    if (truncated) return; // 超限后只排空不累积，避免背压阻塞子进程
    const remain = opts.outputLimit - bytes;
    if (chunk.length > remain) {
      truncated = true;
      output += chunk.toString('utf-8', 0, Math.max(0, remain));
      bytes = opts.outputLimit;
    } else {
      output += chunk.toString('utf-8');
      bytes += chunk.length;
    }
  };
  child.stdout.on('data', feed);
  child.stderr.on('data', feed);

  const timer = setTimeout(() => {
    timedOut = true;
    killTree(child);
  }, opts.timeoutMs);

  const onAbort = (): void => {
    killTree(child);
  };
  opts.signal?.addEventListener('abort', onAbort, { once: true });

  return new Promise<RunResult>((resolvePromise) => {
    child.on('error', (e) => {
      finish();
      resolvePromise({ output: `启动命令失败: ${e.message}`, exitCode: null, truncated, timedOut, ms: Date.now() - started });
    });
    child.on('close', (code) => {
      finish();
      resolvePromise({ output, exitCode: code, truncated, timedOut, ms: Date.now() - started });
    });

    function finish(): void {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      opts.signal?.removeEventListener('abort', onAbort);
    }
  });
}

/** 平台化杀树：Windows taskkill /T /F；POSIX 进程组 kill（spawn detached + kill(-pgid)） */
export function killTree(child: ChildProcessWithoutNullStreams): void {
  const pid = child.pid;
  if (!pid || child.exitCode !== null) return;
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true });
    } else {
      process.kill(-pid, 'SIGKILL');
    }
  } catch {
    try {
      child.kill('SIGKILL');
    } catch {
      /* 进程已退出 */
    }
  }
}
