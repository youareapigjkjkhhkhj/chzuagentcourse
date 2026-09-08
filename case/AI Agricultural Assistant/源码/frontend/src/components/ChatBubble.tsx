import { useState } from "react";
import { ChatMessage } from "@/store/chatStore";
import { User, Bot, Sparkles, ThumbsUp, ThumbsDown } from "lucide-react";
import { format } from "date-fns";
import { cn } from "@/lib/utils";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { submitFeedback } from "@/api/agriApi";
import { toast } from "sonner";

interface ChatBubbleProps {
  message: ChatMessage;
  index?: number;
}

const ChatBubble = ({ message, index = 0 }: ChatBubbleProps) => {
  const isUser = message.role === "user";
  const [feedback, setFeedback] = useState<"positive" | "negative" | null>(null);

  const handleFeedback = async (value: "positive" | "negative") => {
    if (feedback || !message.requestId) return;
    try {
      await submitFeedback(message.requestId, value, "chat");
      setFeedback(value);
      toast.success("Thanks for your feedback!");
    } catch {
      toast.error("Failed to submit feedback");
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ 
        duration: 0.4, 
        delay: index * 0.05,
        ease: [0.25, 0.46, 0.45, 0.94]
      }}
      className={cn(
        "flex gap-3 mb-5",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ delay: index * 0.05 + 0.1, type: "spring", stiffness: 200 }}
        className={cn(
          "flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center shadow-md",
          isUser 
            ? "bg-gradient-to-br from-primary to-primary/80" 
            : "bg-gradient-to-br from-accent/90 to-accent/70"
        )}
      >
        {isUser ? (
          <User className="w-5 h-5 text-primary-foreground" />
        ) : (
          <Bot className="w-5 h-5 text-accent-foreground" />
        )}
      </motion.div>

      <div
        className={cn(
          "flex flex-col max-w-[85%] md:max-w-[75%]",
          isUser ? "items-end" : "items-start"
        )}
      >
        <motion.div
          initial={{ opacity: 0, x: isUser ? 20 : -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: index * 0.05 + 0.15 }}
          className={cn(
            "rounded-2xl px-4 py-3 shadow-md break-words overflow-hidden",
            isUser
              ? "bg-gradient-to-br from-primary to-primary/90 text-primary-foreground rounded-tr-md"
              : "bg-card border border-border/80 text-card-foreground rounded-tl-md"
          )}
        >
          {message.imageUrl && (
            <motion.img
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              src={message.imageUrl}
              alt="Uploaded"
              className="max-w-full max-h-64 object-cover rounded-xl mb-3 border border-border/50"
            />
          )}

          {message.content && (
            <div
              className={cn(
                "prose prose-sm max-w-none leading-relaxed",
                isUser
                  ? "prose-invert"
                  : "dark:prose-invert"
              )}
            >
              <ReactMarkdown 
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ node, ...props }) => (
                    <a {...props} target="_blank" rel="noopener noreferrer" className="underline font-medium hover:opacity-80 transition-opacity" />
                  ),
                  p: ({ node, ...props }) => (
                    <p {...props} className="mb-2 last:mb-0" />
                  ),
                  ul: ({ node, ...props }) => (
                    <ul {...props} className="list-disc pl-4 mb-2 space-y-1" />
                  ),
                  ol: ({ node, ...props }) => (
                    <ol {...props} className="list-decimal pl-4 mb-2 space-y-1" />
                  ),
                  code: ({ node, ...props }) => (
                    <code {...props} className="bg-muted/50 px-1.5 py-0.5 rounded text-xs font-mono" />
                  ),
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}

          {message.agent && !isUser && (
            <div className="flex items-center justify-between gap-2 text-xs mt-3 pt-2 border-t border-border/30 text-muted-foreground">
              <div className="flex items-center gap-1.5">
                <Sparkles className="w-3 h-3" />
                <span>{message.agent}</span>
              </div>
              {message.requestId && (
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => handleFeedback("positive")}
                    disabled={feedback !== null}
                    className={cn(
                      "p-1 rounded hover:bg-muted transition-colors",
                      feedback === "positive" && "text-green-600"
                    )}
                    aria-label="Helpful"
                  >
                    <ThumbsUp className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleFeedback("negative")}
                    disabled={feedback !== null}
                    className={cn(
                      "p-1 rounded hover:bg-muted transition-colors",
                      feedback === "negative" && "text-red-600"
                    )}
                    aria-label="Not helpful"
                  >
                    <ThumbsDown className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          )}
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: index * 0.05 + 0.25 }}
          className={cn(
            "text-[10px] text-muted-foreground mt-1.5 px-1",
            isUser ? "text-right" : "text-left"
          )}
        >
          {format(new Date(message.timestamp), "HH:mm")}
        </motion.div>
      </div>
    </motion.div>
  );
};

export default ChatBubble;
