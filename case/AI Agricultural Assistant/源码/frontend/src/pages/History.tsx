import { useChatStore } from "@/store/chatStore";
import { Card } from "@/components/ui/card";
import { format } from "date-fns";
import { MessageSquare, Image, Layers, Clock, Inbox } from "lucide-react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

const History = () => {
  const { messages } = useChatStore();

  const userMessages = messages.filter((m) => m.role === "user");

  const getMessageType = (msg: typeof messages[0]) => {
    const hasText = msg.content && msg.content.trim() !== "";
    const hasImage = !!msg.imageUrl;

    if (hasText && hasImage)
      return { type: "Multimodal", icon: Layers, color: "text-accent", bg: "bg-accent/10" };
    if (hasImage)
      return { type: "Image", icon: Image, color: "text-farm-sky", bg: "bg-farm-sky/10" };
    return { type: "Text", icon: MessageSquare, color: "text-primary", bg: "bg-primary/10" };
  };

  const findAssistantReply = (userMsg: typeof messages[0]) => {
    return messages.find(
      (m) =>
        m.role === "assistant" &&
        new Date(m.timestamp).getTime() > new Date(userMsg.timestamp).getTime()
    );
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="min-h-[calc(100vh-8.5rem)] p-4 md:p-6"
    >
      <div className="max-w-4xl mx-auto space-y-6">
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="text-center"
        >
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-secondary text-foreground text-sm font-medium mb-4">
            <Clock className="w-4 h-4" />
            <span>Conversation History</span>
          </div>
          <h1 className="text-3xl md:text-4xl font-bold text-foreground mb-3">
            Your Chat History
          </h1>
          <p className="text-muted-foreground max-w-lg mx-auto">
            View your past queries and AI responses
          </p>
        </motion.div>

        {userMessages.length === 0 ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2 }}
          >
            <Card className="p-12 text-center border-border/60">
              <motion.div
                animate={{ y: [0, -5, 0] }}
                transition={{ duration: 2, repeat: Infinity }}
                className="w-20 h-20 bg-secondary rounded-2xl flex items-center justify-center mx-auto mb-6"
              >
                <Inbox className="w-10 h-10 text-muted-foreground" />
              </motion.div>
              <h3 className="text-xl font-semibold text-foreground mb-2">
                No history yet
              </h3>
              <p className="text-muted-foreground max-w-sm mx-auto">
                Start a conversation to see your chat history here. 
                Your queries and AI responses will be saved.
              </p>
            </Card>
          </motion.div>
        ) : (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.2 }}
            className="space-y-3"
          >
            {userMessages.map((msg, index) => {
              const typeInfo = getMessageType(msg);
              const Icon = typeInfo.icon;
              const assistantReply = findAssistantReply(msg);

              return (
                <motion.div
                  key={msg.id}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.05 }}
                >
                  <Card className="p-4 hover:shadow-md transition-all duration-200 border-border/60 hover:border-primary/20">
                    <div className="flex gap-4">
   
                      <div className={cn(
                        "flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center",
                        typeInfo.bg
                      )}>
                        <Icon className={cn("w-5 h-5", typeInfo.color)} />
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-2">
                          <span className={cn(
                            "text-xs font-medium px-2 py-0.5 rounded-full",
                            typeInfo.bg, typeInfo.color
                          )}>
                            {typeInfo.type}
                          </span>
                          <span className="text-xs text-muted-foreground flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {format(new Date(msg.timestamp), "PPp")}
                          </span>
                        </div>

                        {msg.content && (
                          <p className="text-sm font-medium text-foreground mb-2 line-clamp-2">
                            {msg.content}
                          </p>
                        )}

                        {assistantReply && (
                          <p className="text-xs text-muted-foreground line-clamp-2 pl-3 border-l-2 border-primary/30">
                            {assistantReply.content}
                          </p>
                        )}

                        {msg.imageUrl && (
                          <img
                            src={msg.imageUrl}
                            alt="Query image"
                            className="mt-3 max-h-20 rounded-lg border border-border object-cover"
                          />
                        )}
                      </div>
                    </div>
                  </Card>
                </motion.div>
              );
            })}
          </motion.div>
        )}
      </div>
    </motion.div>
  );
};

export default History;
