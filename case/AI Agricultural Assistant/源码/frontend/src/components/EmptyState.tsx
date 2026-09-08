import { motion } from "framer-motion";
import { MessageSquare, Camera, Leaf, Bug, Cloud } from "lucide-react";

const suggestions = [
  {
    icon: Leaf,
    title: "Crop Advice",
    description: "Best practices for healthy crops",
    example: "What's the best time to plant tomatoes?",
  },
  {
    icon: Bug,
    title: "Pest Control",
    description: "Identify and manage pests",
    example: "How do I deal with aphids on my plants?",
  },
  {
    icon: Cloud,
    title: "Weather Tips",
    description: "Weather-based farming decisions",
    example: "Should I water my crops before rain?",
  },
];

interface EmptyStateProps {
  onSuggestionClick?: (text: string) => void;
}

const EmptyState = ({ onSuggestionClick }: EmptyStateProps) => {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4"
    >
      <motion.div
        initial={{ scale: 0, rotate: -180 }}
        animate={{ scale: 1, rotate: 0 }}
        transition={{ type: "spring", stiffness: 100, damping: 15, delay: 0.1 }}
        className="mb-6"
      >
        <div className="w-24 h-24 bg-gradient-to-br from-primary/20 to-accent/20 rounded-3xl flex items-center justify-center shadow-lg">
          <span className="text-5xl">🌾</span>
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mb-8"
      >
        <h2 className="text-3xl font-bold text-foreground mb-3">
          Welcome to <span className="text-primary">AgriGPT</span>
        </h2>
        <p className="text-muted-foreground max-w-md text-balance">
          Your intelligent farming companion. Ask questions, upload images for diagnosis, 
          or get expert agricultural advice instantly.
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl w-full mb-8"
      >
        <motion.div
          whileHover={{ scale: 1.02, y: -2 }}
          className="flex items-start gap-4 p-4 rounded-2xl bg-card border border-border shadow-sm text-left"
        >
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
            <MessageSquare className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h3 className="font-semibold text-foreground mb-1">Ask Questions</h3>
            <p className="text-sm text-muted-foreground">
              Get expert advice on farming, crops, and agriculture
            </p>
          </div>
        </motion.div>

        <motion.div
          whileHover={{ scale: 1.02, y: -2 }}
          className="flex items-start gap-4 p-4 rounded-2xl bg-card border border-border shadow-sm text-left"
        >
          <div className="w-10 h-10 rounded-xl bg-accent/20 flex items-center justify-center flex-shrink-0">
            <Camera className="w-5 h-5 text-accent" />
          </div>
          <div>
            <h3 className="font-semibold text-foreground mb-1">Image Diagnosis</h3>
            <p className="text-sm text-muted-foreground">
              Upload photos to identify plant diseases and pests
            </p>
          </div>
        </motion.div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="w-full max-w-2xl"
      >
        <p className="text-sm text-muted-foreground mb-3">Try asking:</p>
        <div className="flex flex-wrap justify-center gap-2">
          {suggestions.map((suggestion, index) => {
            const Icon = suggestion.icon;
            return (
              <motion.button
                key={index}
                whileHover={{ scale: 1.03, y: -1 }}
                whileTap={{ scale: 0.98 }}
                onClick={() => onSuggestionClick?.(suggestion.example)}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-secondary/60 hover:bg-secondary border border-border/50 text-sm text-foreground transition-colors"
              >
                <Icon className="w-4 h-4 text-primary" />
                <span>{suggestion.title}</span>
              </motion.button>
            );
          })}
        </div>
      </motion.div>
    </motion.div>
  );
};

export default EmptyState;
