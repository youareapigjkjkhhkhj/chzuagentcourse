import { useEffect, useRef, useCallback } from "react";
import { useChatStore } from "@/store/chatStore";
import { askChat } from "@/api/agriApi";
import { motion, AnimatePresence } from "framer-motion";

import ChatBubble from "@/components/ChatBubble";
import ChatInput from "@/components/ChatInput";
import Loader from "@/components/Loader";
import EmptyState from "@/components/EmptyState";
import { toast } from "sonner";

const Chat = () => {
  const {
    messages,
    isLoading,
    addMessage,
    addImageMessage,
    setLoading,
    setError,
    clearChat
  } = useChatStore();

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const handleSend = async (text: string, image?: File) => {
    try {
      setLoading(true);
      setError(null);

      if (image) {
        addImageMessage(image);
      }

      if (text.trim().length > 0) {
        addMessage({
          role: "user",
          content: text
        });
      }

      const response = await askChat(text, image);

      addMessage({
        role: "assistant",
        content: response?.analysis ?? "",
        agent: "AgriGPT",
        requestId: response?.request_id,
      });

      toast.success("Response received");

    } catch (error: any) {
      console.error("Chat error:", error);
      const errorMessage =
        error?.message ??
        (error?.response?.data?.detail
          ? (Array.isArray(error.response.data.detail)
              ? error.response.data.detail.map((e: any) => e?.msg ?? String(e)).join("; ")
              : String(error.response.data.detail))
          : null) ??
        "Failed to get response";

      setError(errorMessage);
      toast.error(errorMessage);

    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    clearChat();
    toast.success("Chat cleared");
  };

  const handleSuggestionClick = (text: string) => {
    handleSend(text);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-8.5rem)]">
      <div 
        ref={chatContainerRef}
        className="flex-1 overflow-y-auto scrollbar-hide"
      >
        <div className="max-w-4xl mx-auto px-4 py-6">
          <AnimatePresence mode="wait">
            {messages.length === 0 ? (
              <EmptyState 
                key="empty" 
                onSuggestionClick={handleSuggestionClick}
              />
            ) : (
              <motion.div
                key="messages"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                {messages.map((msg, index) => (
                  <ChatBubble 
                    key={msg.id} 
                    message={msg} 
                    index={index}
                  />
                ))}

                <AnimatePresence>
                  {isLoading && <Loader message="AgriGPT is thinking..." />}
                </AnimatePresence>

                <div ref={messagesEndRef} className="h-4" />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <ChatInput
        onSend={handleSend}
        isLoading={isLoading}
        onClear={messages.length > 0 ? handleClear : undefined}
      />
    </div>
  );
};

export default Chat;
