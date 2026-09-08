import { create } from "zustand";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  imageUrl?: string;
  agent?: string;
  requestId?: string;
}

interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;

  addMessage: (
    message: Omit<ChatMessage, "id" | "timestamp">
  ) => void;

  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;

  clearChat: () => void;

  addImageMessage: (file: File) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isLoading: false,
  error: null,

  addMessage: (message) =>
    set((state) => {
      const limited = state.messages.slice(-200);

      return {
        messages: [
          ...limited,
          {
            ...message,
            id: crypto.randomUUID(),
            timestamp: new Date().toISOString(),
          },
        ],
      };
    }),

  setLoading: (loading) => set({ isLoading: loading }),

  setError: (error) => set({ error }),

  clearChat: () => {
    set((state) => {
      state.messages.forEach((msg) => {
        if (msg.imageUrl?.startsWith("blob:")) {
          URL.revokeObjectURL(msg.imageUrl);
        }
      });
      return { messages: [], error: null };
    });
  },

  addImageMessage: (file) =>
    set((state) => {
      const imageUrl = URL.createObjectURL(file);

      return {
        messages: [
          ...state.messages,
          {
            id: crypto.randomUUID(),
            role: "user",
            content: "",
            timestamp: new Date().toISOString(),
            imageUrl,
          },
        ],
      };
    }),
}));
