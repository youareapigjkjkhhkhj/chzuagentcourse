import { create } from "zustand";
import { toast } from "sonner";
import { format } from "date-fns";

import type {
  AgentBlockUI,
  AgentCompletionPayload,
  AgentHintPayload,
  AgentMessage,
  AgentMessageDelta,
  AgentMetaPayload,
  AgentRawFrame,
  AgentSession,
  AgentToolProgress
} from "@/types/agent";
import {
  batchDeleteAgentSessions,
  deleteAgentSession,
  listAgentMessages,
  listAgentSessions,
  renameAgentSession,
  stopAgentTask
} from "@/services/agentService";
import { buildQuery } from "@/utils/helpers";
import { createAgentStreamResponse } from "@/hooks/useAgentStream";
import { storage } from "@/utils/storage";

interface AgentChatState {
  sessions: AgentSession[];
  currentSessionId: string | null;
  messages: AgentMessage[];
  isLoading: boolean;
  sessionsLoaded: boolean;
  inputFocusKey: number;
  // 欢迎页示例问题点击后预填输入框 key 保证同文重复点击也能触发
  draft: { text: string; key: number } | null;
  isStreaming: boolean;
  isCreatingNew: boolean;
  streamTaskId: string | null;
  streamAbort: (() => void) | null;
  streamingMessageId: string | null;
  // 当前接收增量的文本块 工具事件与换段都会将其封口
  streamOpenBlockId: number | null;
  cancelRequested: boolean;
  // 原始帧抽屉：本次连接收到的全部 SSE 帧 换会话即清
  frames: AgentRawFrame[];
  loadSessions: () => Promise<void>;
  loadMessages: (sessionId: string) => Promise<void>;
  renameSession: (sessionId: string, title: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  batchDeleteSessions: (sessionIds: string[]) => Promise<void>;
  startNewChat: () => void;
  updateSessionTitle: (sessionId: string, title: string) => void;
  setDraft: (text: string) => void;
  toggleBlockOpen: (messageId: string, blockId: number) => void;
  sendMessage: (question: string) => Promise<void>;
  cancelGeneration: () => void;
}

let blockSeq = 0;
const nextBlockId = () => ++blockSeq;

let frameSeq = 0;
// 原始帧上限：超长会话防内存膨胀 抽屉是调试面 截尾可接受
const MAX_FRAMES = 2000;

function nowHms() {
  return format(new Date(), "HH:mm:ss");
}

function toHms(value?: string) {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : format(parsed, "HH:mm:ss");
}

// 块时刻两种历史形态都要认：新数据是 yyyy-MM-ddTHH:mm:ss 老数据只有 HH:mm:ss
function toBlockHms(value?: string) {
  if (!value) return "";
  return /^\d{2}:\d{2}:\d{2}$/.test(value) ? value : toHms(value);
}

function upsertSession(sessions: AgentSession[], next: AgentSession) {
  const index = sessions.findIndex((session) => session.id === next.id);
  const updated = [...sessions];
  if (index >= 0) {
    updated[index] = { ...sessions[index], ...next };
  } else {
    updated.unshift(next);
  }
  return updated.sort((a, b) => {
    const timeA = a.lastTime ? new Date(a.lastTime).getTime() : 0;
    const timeB = b.lastTime ? new Date(b.lastTime).getTime() : 0;
    return timeB - timeA;
  });
}

// 封口敞开的文本块 思考块闭合即自动折叠 封口时落实测耗时
function sealOpenBlock(blocks: AgentBlockUI[], openBlockId: number | null) {
  if (openBlockId == null) return blocks;
  return blocks.map((block) => {
    if (block.id !== openBlockId) return block;
    const sealed =
      block.startMs != null && block.durationMs == null
        ? { ...block, durationMs: Date.now() - block.startMs }
        : block;
    return sealed.kind === "reasoning" ? { ...sealed, open: false } : sealed;
  });
}

// 收尾：残留 running 工具置为给定终态 敞开思考块折叠 未封口块补实测耗时
function settleBlocks(blocks: AgentBlockUI[] | undefined, toolStatus: "done" | "interrupted") {
  if (!blocks) return blocks;
  return blocks.map((block) => {
    let next = block;
    if (next.startMs != null && next.durationMs == null) {
      next = { ...next, durationMs: Date.now() - next.startMs };
    }
    if (next.kind === "tool" && next.status === "running") {
      next = { ...next, status: toolStatus };
    }
    if (next.kind === "reasoning" && next.open) {
      next = { ...next, open: false };
    }
    return next;
  });
}

// 回放轮次总耗时：assistant 落库时刻减去前一条 user 的落库时刻
function replayElapsed(userTime?: string, assistantTime?: string): number | undefined {
  if (!userTime || !assistantTime) return undefined;
  const start = new Date(userTime).getTime();
  const end = new Date(assistantTime).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return undefined;
  return end - start;
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export const useAgentChatStore = create<AgentChatState>((set, get) => {
  // 文本增量按块规则落位：敞开块同类则追加 否则封口旧块并新开
  const appendText = (kind: "reasoning" | "answer", delta: string) => {
    if (!delta) return;
    set((state) => {
      let nextOpenId = state.streamOpenBlockId;
      const messages = state.messages.map((message) => {
        if (message.id !== state.streamingMessageId) return message;
        if (message.status === "cancelled" || message.status === "error") return message;
        let blocks = [...(message.blocks ?? [])];
        const idx = nextOpenId != null ? blocks.findIndex((b) => b.id === nextOpenId) : -1;
        if (idx >= 0 && blocks[idx].kind === kind) {
          blocks[idx] = { ...blocks[idx], text: (blocks[idx].text ?? "") + delta };
        } else {
          blocks = sealOpenBlock(blocks, nextOpenId);
          const created: AgentBlockUI = {
            id: nextBlockId(),
            kind,
            at: nowHms(),
            startMs: Date.now(),
            text: delta,
            // 流式思考块自动展开实时滚字
            open: kind === "reasoning" ? true : undefined
          };
          blocks.push(created);
          nextOpenId = created.id;
        }
        return {
          ...message,
          blocks,
          content: kind === "answer" ? message.content + delta : message.content,
          thinking: kind === "reasoning" ? `${message.thinking ?? ""}${delta}` : message.thinking
        };
      });
      return { messages, streamOpenBlockId: nextOpenId };
    });
  };

  return {
    sessions: [],
    currentSessionId: null,
    messages: [],
    isLoading: false,
    sessionsLoaded: false,
    inputFocusKey: 0,
    draft: null,
    isStreaming: false,
    isCreatingNew: false,
    streamTaskId: null,
    streamAbort: null,
    streamingMessageId: null,
    streamOpenBlockId: null,
    cancelRequested: false,
    frames: [],
    loadSessions: async () => {
      set({ isLoading: true });
      try {
        const data = await listAgentSessions();
        const sessions = data
          .map((item) => ({
            id: item.conversationId,
            title: item.title || "新对话",
            lastTime: item.lastTime,
            turns: item.turns
          }))
          .sort((a, b) => {
            const timeA = a.lastTime ? new Date(a.lastTime).getTime() : 0;
            const timeB = b.lastTime ? new Date(b.lastTime).getTime() : 0;
            return timeB - timeA;
          });
        set({ sessions });
      } catch (error) {
        toast.error((error as Error).message || "加载会话失败");
      } finally {
        set({ isLoading: false, sessionsLoaded: true });
      }
    },
    loadMessages: async (sessionId) => {
      if (!sessionId) return;
      if (get().currentSessionId === sessionId && get().messages.length > 0) return;
      if (get().isStreaming) {
        get().cancelGeneration();
      }
      set({
        isLoading: true,
        currentSessionId: sessionId,
        isCreatingNew: false,
        frames: []
      });
      try {
        const data = await listAgentMessages(sessionId);
        if (get().currentSessionId !== sessionId) {
          return;
        }
        // 轮次总耗时按相邻 user→assistant 配对补齐 配对即消费防跨轮误配
        let prevUserTime: string | undefined;
        const mapped: AgentMessage[] = data.map((item) => {
          const isAssistant = item.role === "assistant";
          let blocks: AgentBlockUI[] | undefined;
          if (isAssistant) {
            if (Array.isArray(item.blocks) && item.blocks.length > 0) {
              blocks = item.blocks.map((block) => ({
                id: nextBlockId(),
                kind: block.kind,
                at: toBlockHms(block.at),
                text: block.text ?? undefined,
                name: block.name ?? undefined,
                displayName: block.displayName ?? undefined,
                status: block.status ?? (block.kind === "tool" ? "done" : undefined),
                result: block.result ?? undefined,
                open: false
              }));
            } else {
              // 旧数据无块结构 由持久化字段合成
              const at = toHms(item.createTime);
              blocks = [];
              if (item.thinkingContent) {
                blocks.push({
                  id: nextBlockId(),
                  kind: "reasoning",
                  at,
                  text: item.thinkingContent,
                  open: false
                });
              }
              if (item.content) {
                blocks.push({ id: nextBlockId(), kind: "answer", at, text: item.content });
              }
            }
          }
          const elapsedMs = isAssistant ? replayElapsed(prevUserTime, item.createTime) : undefined;
          prevUserTime = isAssistant ? undefined : item.createTime;
          return {
            id: String(item.id),
            role: isAssistant ? ("assistant" as const) : ("user" as const),
            content: item.content,
            thinking: item.thinkingContent || undefined,
            blocks,
            createdAt: item.createTime,
            elapsedMs,
            status: "done" as const,
            messageStatus: item.messageStatus ?? "NORMAL"
          };
        });
        set({ messages: mapped });
      } catch (error) {
        toast.error((error as Error).message || "加载消息失败");
      } finally {
        if (get().currentSessionId !== sessionId) {
          set({ isLoading: false });
        } else {
          set({
            isLoading: false,
            isStreaming: false,
            streamTaskId: null,
            streamAbort: null,
            streamingMessageId: null,
            streamOpenBlockId: null,
            cancelRequested: false
          });
        }
      }
    },
    renameSession: async (sessionId, title) => {
      const trimmed = title.trim();
      if (!trimmed) return;
      try {
        await renameAgentSession(sessionId, trimmed);
        get().updateSessionTitle(sessionId, trimmed);
      } catch (error) {
        toast.error((error as Error).message || "重命名失败");
      }
    },
    deleteSession: async (sessionId) => {
      try {
        await deleteAgentSession(sessionId);
        set((state) => ({
          sessions: state.sessions.filter((session) => session.id !== sessionId),
          messages: state.currentSessionId === sessionId ? [] : state.messages,
          currentSessionId: state.currentSessionId === sessionId ? null : state.currentSessionId
        }));
        toast.success("删除成功");
      } catch (error) {
        toast.error((error as Error).message || "删除会话失败");
      }
    },
    batchDeleteSessions: async (sessionIds) => {
      if (sessionIds.length === 0) return;
      try {
        await batchDeleteAgentSessions(sessionIds);
        const removed = new Set(sessionIds);
        set((state) => ({
          sessions: state.sessions.filter((session) => !removed.has(session.id)),
          messages: state.currentSessionId && removed.has(state.currentSessionId) ? [] : state.messages,
          currentSessionId:
            state.currentSessionId && removed.has(state.currentSessionId) ? null : state.currentSessionId
        }));
        toast.success(`已删除 ${sessionIds.length} 条会话`);
      } catch (error) {
        toast.error((error as Error).message || "批量删除失败");
      }
    },
    startNewChat: () => {
      const state = get();
      if (state.messages.length === 0 && !state.currentSessionId) {
        set({ isCreatingNew: true, isLoading: false });
        return;
      }
      if (state.isStreaming) {
        get().cancelGeneration();
      }
      set({
        currentSessionId: null,
        messages: [],
        isStreaming: false,
        isLoading: false,
        isCreatingNew: true,
        streamTaskId: null,
        streamAbort: null,
        streamingMessageId: null,
        streamOpenBlockId: null,
        cancelRequested: false,
        frames: []
      });
    },
    updateSessionTitle: (sessionId, title) => {
      set((state) => ({
        sessions: state.sessions.map((session) =>
          session.id === sessionId ? { ...session, title } : session
        )
      }));
    },
    setDraft: (text) => {
      set({ draft: { text, key: Date.now() } });
    },
    toggleBlockOpen: (messageId, blockId) => {
      set((state) => ({
        messages: state.messages.map((message) =>
          message.id === messageId && message.blocks
            ? {
                ...message,
                blocks: message.blocks.map((block) =>
                  block.id === blockId ? { ...block, open: !block.open } : block
                )
              }
            : message
        )
      }));
    },
    sendMessage: async (question) => {
      const trimmed = question.trim();
      if (!trimmed) return;
      if (get().isStreaming) return;
      const inputFocusKey = Date.now();
      // 轮次计时起点 收尾时实测总耗时
      const startedMs = Date.now();

      const userMessage: AgentMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: trimmed,
        status: "done",
        createdAt: new Date().toISOString()
      };
      const assistantId = `assistant-${Date.now()}`;
      const assistantMessage: AgentMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        blocks: [],
        status: "streaming",
        createdAt: new Date().toISOString()
      };

      set((state) => ({
        messages: [...state.messages, userMessage, assistantMessage],
        isStreaming: true,
        streamingMessageId: assistantId,
        streamOpenBlockId: null,
        inputFocusKey,
        streamTaskId: null,
        cancelRequested: false
      }));

      const conversationId = get().currentSessionId;
      const query = buildQuery({
        question: trimmed,
        conversationId: conversationId || undefined
      });
      const url = `${API_BASE_URL}/agent/v1/chat${query}`;
      const token = storage.getToken();

      const handlers = {
        // 每一条 SSE 帧原样进抽屉 供深度核对
        onEvent: (event: string, payload: unknown) => {
          set((state) => ({
            frames: [
              ...(state.frames.length >= MAX_FRAMES ? state.frames.slice(1) : state.frames),
              { id: ++frameSeq, ts: format(new Date(), "HH:mm:ss"), name: event, data: payload }
            ]
          }));
        },
        onMeta: (payload: AgentMetaPayload) => {
          if (get().streamingMessageId !== assistantId) return;
          const nextId = payload.conversationId || get().currentSessionId;
          if (!nextId) return;
          const lastTime = new Date().toISOString();
          const existing = get().sessions.find((session) => session.id === nextId);
          set((state) => ({
            currentSessionId: nextId,
            isCreatingNew: false,
            streamTaskId: payload.taskId,
            sessions: upsertSession(state.sessions, {
              id: nextId,
              title: existing?.title || "新对话",
              lastTime
            })
          }));
          // meta 前用户已点停止：此刻才拿到 taskId 补发停止指令
          if (get().cancelRequested) {
            stopAgentTask(payload.taskId).catch(() => null);
          }
        },
        onMessage: (payload: AgentMessageDelta) => {
          if (!payload || typeof payload !== "object") return;
          if (payload.type !== "response") return;
          if (get().streamingMessageId !== assistantId) return;
          appendText("answer", payload.delta);
        },
        onThinking: (payload: AgentMessageDelta) => {
          if (!payload || typeof payload !== "object") return;
          if (payload.type !== "think") return;
          if (get().streamingMessageId !== assistantId) return;
          appendText("reasoning", payload.delta);
        },
        onTool: (payload: AgentToolProgress) => {
          if (!payload || typeof payload !== "object" || !payload.name) return;
          if (get().streamingMessageId !== assistantId) return;
          set((state) => ({
            // 任何工具事件都封口当前文本块 与后端分段规则保持一致
            streamOpenBlockId: null,
            messages: state.messages.map((message) => {
              if (message.id !== state.streamingMessageId) return message;
              if (message.status === "cancelled" || message.status === "error") return message;
              const blocks = sealOpenBlock([...(message.blocks ?? [])], state.streamOpenBlockId);
              if (payload.status === "start") {
                blocks.push({
                  id: nextBlockId(),
                  kind: "tool",
                  at: nowHms(),
                  startMs: Date.now(),
                  name: payload.name,
                  displayName: payload.displayName || payload.name,
                  status: "running"
                });
                return { ...message, blocks };
              }
              // 无 toolCallId 按名字配对 后进先出闭合最近未完成的同名调用
              for (let i = blocks.length - 1; i >= 0; i -= 1) {
                const block = blocks[i];
                if (block.kind === "tool" && block.name === payload.name && block.status === "running") {
                  blocks[i] = {
                    ...block,
                    // ok 缺省视为成功 兼容旧后端事件
                    status: payload.ok === false ? "failed" : "done",
                    durationMs: block.startMs != null ? Date.now() - block.startMs : undefined,
                    result: payload.result ?? undefined
                  };
                  return { ...message, blocks };
                }
              }
              return { ...message, blocks };
            })
          }));
        },
        // 运行提示（如迭代熔断预告）单独成行 不落库 回放自然消失
        onHint: (payload: AgentHintPayload) => {
          if (!payload?.text) return;
          if (get().streamingMessageId !== assistantId) return;
          set((state) => ({
            streamOpenBlockId: null,
            messages: state.messages.map((message) => {
              if (message.id !== state.streamingMessageId) return message;
              if (message.status === "cancelled" || message.status === "error") return message;
              const blocks = sealOpenBlock([...(message.blocks ?? [])], state.streamOpenBlockId);
              blocks.push({ id: nextBlockId(), kind: "hint", at: nowHms(), text: payload.text });
              return { ...message, blocks };
            })
          }));
        },
        onFinish: (payload: AgentCompletionPayload) => {
          if (get().streamingMessageId !== assistantId) return;
          if (!payload) return;
          const currentId = get().currentSessionId;
          if (currentId) {
            const lastTime = new Date().toISOString();
            const existingTitle =
              get().sessions.find((session) => session.id === currentId)?.title || "新对话";
            const nextTitle = payload.title || existingTitle;
            // 本地即时更新轮数徽标 与服务端 user 消息计数同口径
            const turns = get().messages.filter((message) => message.role === "user").length;
            set((state) => ({
              sessions: upsertSession(state.sessions, {
                id: currentId,
                title: nextTitle,
                lastTime,
                turns
              })
            }));
          }
          set((state) => ({
            streamOpenBlockId: null,
            messages: state.messages.map((message) =>
              message.id === state.streamingMessageId
                ? {
                    ...message,
                    id: payload.messageId ? String(payload.messageId) : message.id,
                    status: "done",
                    blocks: settleBlocks(message.blocks, "done"),
                    elapsedMs: Date.now() - startedMs,
                    messageStatus: payload.messageStatus ?? "NORMAL"
                  }
                : message
            )
          }));
        },
        onCancel: (payload: AgentCompletionPayload) => {
          if (get().streamingMessageId !== assistantId) return;
          if (payload?.title && get().currentSessionId) {
            get().updateSessionTitle(get().currentSessionId as string, payload.title);
          }
          set((state) => ({
            messages: state.messages.map((message) => {
              if (message.id !== state.streamingMessageId) return message;
              const suffix = message.content.includes("（已停止生成）") ? "" : "\n\n（已停止生成）";
              const nextId = payload?.messageId ? String(payload.messageId) : message.id;
              let blocks = settleBlocks(message.blocks, "interrupted") ?? [];
              if (suffix) {
                let appended = false;
                for (let i = blocks.length - 1; i >= 0; i -= 1) {
                  if (blocks[i].kind === "answer") {
                    blocks = [...blocks];
                    blocks[i] = { ...blocks[i], text: (blocks[i].text ?? "") + suffix };
                    appended = true;
                    break;
                  }
                }
                if (!appended) {
                  blocks = [
                    ...blocks,
                    { id: nextBlockId(), kind: "answer", at: nowHms(), text: "（已停止生成）" }
                  ];
                }
              }
              return {
                ...message,
                id: nextId,
                content: message.content + suffix,
                blocks,
                status: "cancelled",
                elapsedMs: Date.now() - startedMs,
                messageStatus: payload?.messageStatus ?? "INTERRUPTED"
              };
            }),
            isStreaming: false,
            streamTaskId: null,
            streamAbort: null,
            streamingMessageId: null,
            streamOpenBlockId: null,
            cancelRequested: false
          }));
        },
        onDone: () => {
          if (get().streamingMessageId !== assistantId) return;
          set({
            isStreaming: false,
            streamTaskId: null,
            streamAbort: null,
            streamingMessageId: null,
            streamOpenBlockId: null,
            cancelRequested: false
          });
        },
        onError: (error: Error) => {
          if (get().streamingMessageId !== assistantId) return;
          set((state) => ({
            isStreaming: false,
            streamTaskId: null,
            streamAbort: null,
            streamOpenBlockId: null,
            cancelRequested: false,
            messages: state.messages.map((message) =>
              message.id === state.streamingMessageId
                ? {
                    ...message,
                    status: "error",
                    blocks: settleBlocks(message.blocks, "interrupted")
                  }
                : message
            )
          }));
          toast.error(error.message || "生成失败");
        }
      };

      const { start, cancel } = createAgentStreamResponse(
        {
          url,
          headers: token ? { Authorization: token } : undefined,
          retryCount: 1
        },
        handlers
      );

      set({ streamAbort: cancel });

      try {
        await start();
      } catch (error) {
        if ((error as Error).name === "AbortError") {
          return;
        }
        handlers.onError?.(error as Error);
      } finally {
        if (get().streamingMessageId === assistantId) {
          set({
            isStreaming: false,
            streamTaskId: null,
            streamAbort: null,
            streamingMessageId: null,
            streamOpenBlockId: null,
            cancelRequested: false
          });
        }
      }
    },
    cancelGeneration: () => {
      const { isStreaming, streamTaskId } = get();
      if (!isStreaming) return;
      // 不中断 fetch：后端落库部分内容后回发 cancel + done 完成收尾
      set({ cancelRequested: true });
      if (streamTaskId) {
        stopAgentTask(streamTaskId).catch(() => null);
      }
    }
  };
});
