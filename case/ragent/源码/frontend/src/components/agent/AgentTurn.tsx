import * as React from "react";
import { format } from "date-fns";

import { AgentMarkdownRenderer } from "@/components/agent/AgentMarkdownRenderer";
import { useAgentChatStore } from "@/stores/agentChatStore";
import type { AgentBlockUI, AgentMessage } from "@/types/agent";

export interface AgentTurn {
  id: string;
  index: number;
  user?: AgentMessage;
  assistant?: AgentMessage;
}

type Channel = "user" | "reasoning" | "tool" | "answer" | "hint" | "error";

const GLYPH: Record<Channel, string> = {
  user: "▷",
  reasoning: "○",
  tool: "●",
  answer: "▮",
  hint: "·",
  error: "✕"
};

const NAME: Record<Channel, string> = {
  user: "you",
  reasoning: "reasoning",
  tool: "tool",
  answer: "answer",
  hint: "hint",
  error: "error"
};

interface TraceRow {
  key: string;
  channel: Channel;
  ts: string;
  text?: string;
  block?: AgentBlockUI;
  // 连续同名同结果的工具行折叠计数
  count: number;
  streaming?: boolean;
}

function toHms(value?: string) {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : format(parsed, "HH:mm:ss");
}

/** 耗时刻度：10s 内留一位小数 1m 起转 m/s 复合 */
function fmtDur(ms?: number): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "";
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)}s`;
  const secs = Math.round(ms / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m${String(secs % 60).padStart(2, "0")}s`;
}

/**
 * 一轮的轨迹行：用户行 + 助手时间线块 依消息态补 等待/错误 合成行
 * 连续、同名、同结果的工具块折叠成一条 ×N（同错刷屏收成一行）
 */
function buildRows(turn: AgentTurn): TraceRow[] {
  const rows: TraceRow[] = [];
  if (turn.user) {
    rows.push({
      key: `u-${turn.user.id}`,
      channel: "user",
      ts: toHms(turn.user.createdAt),
      text: turn.user.content,
      count: 1
    });
  }
  const assistant = turn.assistant;
  if (!assistant) return rows;

  const blocks = assistant.blocks ?? [];
  const isStreaming = assistant.status === "streaming";

  blocks.forEach((block, i) => {
    const channel: Channel =
      block.kind === "tool"
        ? "tool"
        : block.kind === "reasoning"
          ? "reasoning"
          : block.kind === "hint"
            ? "hint"
            : "answer";
    const last = rows[rows.length - 1];
    if (
      channel === "tool" &&
      last?.channel === "tool" &&
      last.block?.name === block.name &&
      last.block?.result === block.result &&
      last.block?.status === block.status
    ) {
      last.count += 1;
      return;
    }
    rows.push({
      key: `b-${block.id}`,
      channel,
      ts: block.at,
      text: block.text,
      block,
      count: 1,
      // 最后一个块在流式中即活动轨迹 节点呼吸
      streaming: isStreaming && i === blocks.length - 1
    });
  });

  if (isStreaming && blocks.length === 0) {
    rows.push({
      key: `wait-${assistant.id}`,
      channel: "hint",
      ts: "",
      text: "等待响应…",
      count: 1,
      streaming: true
    });
  }
  if (assistant.status === "error") {
    rows.push({
      key: `err-${assistant.id}`,
      channel: "error",
      ts: "",
      text: "生成失败，请稍后重试",
      count: 1
    });
  }
  return rows;
}

interface AgentTurnItemProps {
  turn: AgentTurn;
  /** 卡头旁注 目前只有待机空态的预演卡用它标「示例」 */
  note?: string;
}

/** 一轮用户↔助手收进一张卡：轮次头 + 各通道轨迹行 示波器时间轴在卡内贯穿 */
export function AgentTurnItem({ turn, note }: AgentTurnItemProps) {
  const rows = buildRows(turn);
  const headTs = rows[0]?.ts || "";
  const assistantId = turn.assistant?.id;
  // 流式中不显示总耗时 收尾实测或回放差值就绪后才亮
  const elapsed =
    turn.assistant?.status === "streaming" ? "" : fmtDur(turn.assistant?.elapsedMs);

  return (
    <section className="agent-turn">
      <header className="agent-turn-head">
        <span className="agent-turn-no">TURN {turn.index}</span>
        {note ? <span className="agent-turn-note">{note}</span> : null}
        <span className="agent-turn-ts">
          {headTs}
          {elapsed ? <span className="agent-turn-dur"> · {elapsed}</span> : null}
        </span>
      </header>
      {rows.map((row, i) => (
        <TraceRowItem key={row.key} row={row} messageId={assistantId} showTs={i > 0} />
      ))}
    </section>
  );
}

function TraceRowItem({
  row,
  messageId,
  showTs
}: {
  row: TraceRow;
  messageId?: string;
  showTs: boolean;
}) {
  const failed = row.channel === "tool" && row.block?.status === "failed";
  const interrupted = row.channel === "tool" && row.block?.status === "interrupted";
  const running = row.channel === "tool" && row.block?.status === "running";

  return (
    <div
      className="agent-row"
      data-channel={row.channel}
      data-failed={failed}
      data-streaming={Boolean(row.streaming || running)}
    >
      <div className="agent-row-rail">
        <span className="agent-node">{GLYPH[row.channel]}</span>
      </div>
      <div className="agent-row-content">
        <div className="agent-meta-line">
          <span className="agent-channel">{NAME[row.channel]}</span>
          {row.channel === "tool" && row.block?.name ? (
            <span className="agent-tool-chip">{row.block.name}</span>
          ) : null}
          {row.channel === "tool" &&
          row.block?.displayName &&
          row.block.displayName !== row.block.name ? (
            <span className="text-[color:var(--agent-muted)]">{row.block.displayName}</span>
          ) : null}
          {failed ? <span className="agent-status-err">失败</span> : null}
          {interrupted ? <span className="agent-status-err">已中断</span> : null}
          {row.channel === "tool" && row.block?.status === "done" ? (
            <span className="agent-status-ok">完成</span>
          ) : null}
          {running ? <span className="agent-status-run">运行中</span> : null}
          {row.block?.durationMs != null ? (
            <span className="agent-row-dur">· {fmtDur(row.block.durationMs)}</span>
          ) : null}
          {row.count > 1 ? <span className="agent-row-count">×{row.count}</span> : null}
          {showTs ? <span className="agent-row-ts">{row.ts}</span> : null}
        </div>
        <RowBody row={row} messageId={messageId} />
      </div>
    </div>
  );
}

function RowBody({ row, messageId }: { row: TraceRow; messageId?: string }) {
  if (row.channel === "tool" && row.block) {
    return <ToolCallBox block={row.block} messageId={messageId} />;
  }
  if (row.channel === "reasoning" && row.block) {
    return <ReasoningRow block={row.block} messageId={messageId} streaming={row.streaming} />;
  }
  if (row.channel === "answer") {
    return (
      <div className="agent-answer-form">
        <AgentMarkdownRenderer content={row.text ?? ""} />
      </div>
    );
  }
  return <div className="agent-row-text">{row.text}</div>;
}

/**
 * 思考轨迹：正在想时强制展开实时滚字 块结束自动收成一行摘要 点开可重看
 */
function ReasoningRow({
  block,
  messageId,
  streaming
}: {
  block: AgentBlockUI;
  messageId?: string;
  streaming?: boolean;
}) {
  const toggleBlockOpen = useAgentChatStore((state) => state.toggleBlockOpen);
  const open = Boolean(block.open) || Boolean(streaming);

  return (
    <div>
      <button
        type="button"
        className="agent-reasoning-toggle"
        onClick={() => {
          if (messageId) toggleBlockOpen(messageId, block.id);
        }}
        aria-expanded={open}
      >
        <span className="agent-caret">{open ? "▾" : "▸"}</span>
        <span className="agent-reasoning-peek">{peek(block.text ?? "")}</span>
      </button>
      {open ? (
        <div className="agent-reasoning-body">
          <AgentMarkdownRenderer content={block.text ?? ""} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * 工具块：一行结果摘要 + 展开看完整返回 失败时错因直接显在摘要位（不展开也看得到）
 */
function ToolCallBox({ block, messageId }: { block: AgentBlockUI; messageId?: string }) {
  const toggleBlockOpen = useAgentChatStore((state) => state.toggleBlockOpen);
  const open = Boolean(block.open);
  const failed = block.status === "failed";
  const raw = block.result ?? "";
  const parsed = React.useMemo(() => tryParse(raw), [raw]);

  if (block.status === "running") {
    return (
      <div className="agent-toolbox">
        <div className="agent-tool-summary">
          <span className="agent-caret">▸</span>
          <span className="agent-tool-preview">执行中…</span>
        </div>
      </div>
    );
  }

  const summary = failed ? errorSummary(raw) : summarize(parsed, raw);
  const full = parsed != null ? stringify(parsed) : raw;

  return (
    <div className="agent-toolbox">
      <button
        type="button"
        className="agent-tool-summary"
        onClick={() => {
          if (messageId) toggleBlockOpen(messageId, block.id);
        }}
        aria-expanded={open}
      >
        <span className="agent-caret">{open ? "▾" : "▸"}</span>
        <span className="agent-tool-preview">{summary}</span>
      </button>
      {open ? <pre className="agent-pre">{full || "（空返回）"}</pre> : null}
    </div>
  );
}

/** 单行去 markdown 记号：标题/列表前缀与强调符 折叠摘要不该露原始符号 */
function stripMdMarks(line: string): string {
  return line
    .replace(/^#{1,6}\s*/, "")
    .replace(/^[-*+]\s+/, "")
    .replace(/[*_`>]/g, "")
    .trim();
}

/** 压平 markdown 文本为一行：丢分隔线 逐行去记号后以空格拼接 */
function flattenMd(text: string): string {
  return text
    .split("\n")
    .map((s) => s.trim())
    .filter((s) => s && !/^(-{3,}|\*{3,}|_{3,})$/.test(s))
    .map(stripMdMarks)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

/** 取首个非空行、去掉 markdown 记号 作为思考折叠态的一行摘要 */
function peek(text: string): string {
  const line =
    text
      .split("\n")
      .map((s) => s.trim())
      .find(Boolean) ?? "";
  const clean = stripMdMarks(line);
  return clean.length > 84 ? `${clean.slice(0, 84)}…` : clean || "思考中";
}

function tryParse(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** 去掉可能的 Error 前缀 只留人能看懂的错因 */
function errorSummary(text: string): string {
  const t = text.replace(/^\s*error[:：]\s*/i, "").trim();
  return t.length > 120 ? `${t.slice(0, 120)}…` : t || "工具执行出错";
}

function summarize(json: unknown, text: string): string {
  if (json == null) {
    const t = flattenMd(text);
    return t.length > 96 ? `${t.slice(0, 96)}…` : t || "（空返回）";
  }
  if (Array.isArray(json)) return `数组 · ${json.length} 项`;
  if (typeof json === "object") {
    const compact = JSON.stringify(json);
    if (compact.length <= 96) return compact;
    const keys = Object.keys(json as object);
    return `对象 · ${keys.slice(0, 4).join(", ")}${keys.length > 4 ? "…" : ""}`;
  }
  return String(json);
}

function stringify(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}
