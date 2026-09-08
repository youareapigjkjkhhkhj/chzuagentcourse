import { motion } from "framer-motion";
import { Sprout } from "lucide-react";

interface LoaderProps {
  message?: string;
}

const Loader = ({ message = "Processing your request..." }: LoaderProps) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="flex items-start gap-3 mb-5"
    >
      <motion.div
        animate={{ 
          scale: [1, 1.1, 1],
        }}
        transition={{ 
          duration: 2, 
          repeat: Infinity,
          ease: "easeInOut"
        }}
        className="flex-shrink-0 w-9 h-9 rounded-xl bg-gradient-to-br from-accent/90 to-accent/70 flex items-center justify-center shadow-md"
      >
        <Sprout className="w-5 h-5 text-accent-foreground" />
      </motion.div>

      <div className="flex flex-col items-start">
        <div className="bg-card border border-border/80 rounded-2xl rounded-tl-md px-5 py-4 shadow-md">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              {[0, 1, 2].map((i) => (
                <motion.div
                  key={i}
                  animate={{
                    y: [0, -8, 0],
                    opacity: [0.4, 1, 0.4],
                  }}
                  transition={{
                    duration: 0.8,
                    repeat: Infinity,
                    delay: i * 0.15,
                    ease: "easeInOut",
                  }}
                  className="w-2.5 h-2.5 rounded-full bg-primary"
                />
              ))}
            </div>

            <motion.p
              animate={{ opacity: [0.5, 1, 0.5] }}
              transition={{ duration: 2, repeat: Infinity }}
              className="text-sm text-muted-foreground"
            >
              {message}
            </motion.p>
          </div>
        </div>

        <motion.div
          initial={{ width: 0 }}
          animate={{ width: "100%" }}
          transition={{ duration: 2, repeat: Infinity }}
          className="h-0.5 mt-2 rounded-full bg-gradient-to-r from-transparent via-primary/30 to-transparent"
        />
      </div>
    </motion.div>
  );
};

export default Loader;
