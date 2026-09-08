import { useState, useRef, KeyboardEvent, ChangeEvent } from "react";
import { Send, Image as ImageIcon, X, Paperclip, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (text: string, image?: File) => void;
  isLoading: boolean;
  onClear?: () => void;
}

const MAX_FILE_SIZE = 8 * 1024 * 1024;
const ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png"];

const ChatInput = ({ onSend, isLoading, onClear }: ChatInputProps) => {
  const [text, setText] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [isFocused, setIsFocused] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const validateImage = (file: File) => {
    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      toast.error("Please select a JPG or PNG image (max 8MB)");
      return false;
    }
    if (file.size > MAX_FILE_SIZE) {
      toast.error("Image size must be less than 8MB");
      return false;
    }
    return true;
  };

  const handleImageSelect = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!validateImage(file)) return;

    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
  };

  const removeImage = () => {
    setImageFile(null);
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImagePreview(null);

    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleSend = () => {
    const trimmed = text.trim();

    if (!trimmed && !imageFile) {
      toast.error("Please enter a message or select an image");
      return;
    }

    onSend(trimmed, imageFile || undefined);

    setText("");
    removeImage();
    textareaRef.current?.focus();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleTextChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    const textarea = e.target;
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px";
  };

  const canSend = text.trim() || imageFile;

  return (
    <motion.div
      initial={{ y: 100, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ type: "spring", stiffness: 100, damping: 20 }}
      className="border-t border-border/50 bg-gradient-to-t from-background via-background to-background/80 backdrop-blur-sm p-4"
    >
      <div className="max-w-4xl mx-auto">
        <AnimatePresence>
          {imagePreview && (
            <motion.div
              initial={{ opacity: 0, height: 0, marginBottom: 0 }}
              animate={{ opacity: 1, height: "auto", marginBottom: 12 }}
              exit={{ opacity: 0, height: 0, marginBottom: 0 }}
              className="overflow-hidden"
            >
              <div className="relative inline-block">
                <img
                  src={imagePreview}
                  alt="Preview"
                  className="max-h-28 rounded-xl border-2 border-primary/30 shadow-lg"
                />
                <motion.button
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                  onClick={removeImage}
                  className="absolute -top-2 -right-2 w-6 h-6 bg-destructive text-destructive-foreground rounded-full flex items-center justify-center shadow-md"
                >
                  <X className="w-3.5 h-3.5" />
                </motion.button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <motion.div
          animate={{
            boxShadow: isFocused 
              ? "0 0 0 2px hsl(var(--primary) / 0.2), 0 4px 20px hsl(var(--primary) / 0.1)" 
              : "0 2px 10px hsl(var(--foreground) / 0.05)"
          }}
          className={cn(
            "relative flex items-end gap-2 p-2 rounded-2xl bg-card border transition-all duration-300",
            isFocused ? "border-primary/40" : "border-border"
          )}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png"
            onChange={handleImageSelect}
            className="hidden"
          />

          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            disabled={isLoading}
            onClick={() => fileInputRef.current?.click()}
            className="flex-shrink-0 text-muted-foreground hover:text-foreground hover:bg-secondary rounded-xl"
            aria-label="Upload image"
          >
            <Paperclip className="w-5 h-5" />
          </Button>

          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={text}
              disabled={isLoading}
              placeholder="Ask about crops, pests, diseases, or upload an image..."
              onChange={handleTextChange}
              onKeyDown={handleKeyDown}
              onFocus={() => setIsFocused(true)}
              onBlur={() => setIsFocused(false)}
              rows={1}
              className={cn(
                "w-full bg-transparent border-0 resize-none focus:outline-none focus:ring-0",
                "text-foreground placeholder:text-muted-foreground/60",
                "py-2.5 px-1 text-sm leading-relaxed",
                "scrollbar-hide"
              )}
              style={{ maxHeight: "200px" }}
            />
          </div>

          <motion.div
            animate={{ 
              scale: canSend ? 1 : 0.9,
              opacity: canSend ? 1 : 0.5
            }}
          >
            <Button
              type="button"
              size="icon"
              variant="send"
              onClick={handleSend}
              disabled={isLoading || !canSend}
              className={cn(
                "flex-shrink-0 w-10 h-10 rounded-xl transition-all duration-200",
                canSend && !isLoading && "hover:scale-105"
              )}
              aria-label="Send message"
            >
              {isLoading ? (
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                >
                  <Sparkles className="w-5 h-5" />
                </motion.div>
              ) : (
                <Send className="w-5 h-5" />
              )}
            </Button>
          </motion.div>
        </motion.div>

        <div className="flex items-center justify-between mt-2 px-2">
          <p className="text-[10px] text-muted-foreground">
            <kbd className="px-1.5 py-0.5 bg-secondary rounded text-[9px] font-mono">Enter</kbd> to send · <kbd className="px-1.5 py-0.5 bg-secondary rounded text-[9px] font-mono">Shift+Enter</kbd> for new line
          </p>
          
          {onClear && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isLoading}
              onClick={onClear}
              className="text-xs text-muted-foreground hover:text-foreground h-auto py-1"
            >
              Clear chat
            </Button>
          )}
        </div>
      </div>
    </motion.div>
  );
};

export default ChatInput;
