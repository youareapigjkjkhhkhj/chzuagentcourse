/**
 * 「火力全开 · 联动」模型档位滑块 —— 对齐 Claude Code / Codex「选模型即用、可拖到最大」的体验。
 *
 * 一个档位（0..POWER_MAX）同时联动两项高级参数，用户无需理解 token 细节：
 *   - contextWindow（上下文窗口）：8K → 1M，拖到最大 = 尽量吃满模型的长上下文能力；
 *   - maxTokens（单次输出上限）：2K → 32K，拖到最大 = 推理模型思考链不被过早截断。
 *
 * 为什么可以「无脑拖到最大」：orchestrator 已内置 400 自愈（learnedWindows 探测真实窗口 +
 * clampOutputTokens 收敛输出上限），档位高于模型真实能力时会被自动回退，不会报错中断。
 * 因此这里只负责把「意图档位」翻译成两个参数并持久化，无需感知每个模型的真实上限。
 */

/** 档位 → 上下文窗口（token）。末档 1M = 「火力全开」；索引 4 = 128K，对齐 ipc.ts 默认值。 */
export const CW_STEPS = [8_000, 16_000, 32_000, 64_000, 128_000, 200_000, 256_000, 512_000, 1_000_000];
/** 档位 → 单次输出上限（token），与 CW_STEPS 同索引联动。 */
export const MT_STEPS = [2_000, 2_000, 4_000, 4_000, 8_000, 8_000, 16_000, 16_000, 32_000];
/** 滑块最大档位（0..POWER_MAX，共 9 档）。 */
export const POWER_MAX = CW_STEPS.length - 1;
/** 缺省档位：对齐 ipc.ts 默认值 contextWindow=128K / maxTokens=8K（新配置模型的初始滑块位置）。 */
export const DEFAULT_LEVEL = 4;

function clampLevel(level: number): number {
  if (!Number.isFinite(level)) return DEFAULT_LEVEL;
  return Math.min(POWER_MAX, Math.max(0, Math.round(level)));
}

/** 档位 → contextWindow（token）。clampLevel 已把索引收敛到 [0, POWER_MAX]，故断言非空。 */
export function levelToContextWindow(level: number): number {
  return CW_STEPS[clampLevel(level)]!;
}

/** 档位 → maxTokens（单次输出上限，token） */
export function levelToMaxTokens(level: number): number {
  return MT_STEPS[clampLevel(level)]!;
}

/**
 * 已存 contextWindow → 最接近的档位（对数距离），用于滑块初始定位。
 * 任意窗口值（如模型中心写入的 128000、或厂商真实的 131072）都会吸附到最贴近的档位。
 */
export function contextWindowToLevel(cw: number): number {
  const v = Number.isFinite(cw) && cw > 0 ? cw : CW_STEPS[DEFAULT_LEVEL]!;
  const target = Math.log(v);
  let best = DEFAULT_LEVEL;
  let bestDist = Infinity;
  for (let i = 0; i < CW_STEPS.length; i += 1) {
    const dist = Math.abs(Math.log(CW_STEPS[i]!) - target);
    if (dist < bestDist) {
      bestDist = dist;
      best = i;
    }
  }
  return best;
}

/** 展示：token 数格式化为 8K / 128K / 1M 形态。 */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) {
    const m = n / 1_000_000;
    return `${Number.isInteger(m) ? m : m.toFixed(1)}M`;
  }
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}
