import { useState, useEffect } from "react";
import { Upload, X, Camera, CheckCircle, ThumbsUp, ThumbsDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { askImage, submitFeedback } from "@/api/agriApi";
import Loader from "@/components/Loader";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

const ImageDiagnosis = () => {
  const [selectedImage, setSelectedImage] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [lastRequestId, setLastRequestId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<"positive" | "negative" | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    processFile(file);
  };

  const   processFile = (file: File) => {
    const allowed = ["image/jpeg", "image/png"];
    if (!allowed.includes(file.type)) {
      toast.error("Please select a JPG or PNG image (max 8MB)");
      return;
    }

    if (file.size > 8 * 1024 * 1024) {
      toast.error("Image size must be less than 8MB");
      return;
    }

    setSelectedImage(file);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(URL.createObjectURL(file));
    setResult(null);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) processFile(file);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => setIsDragOver(false);

  const removeImage = () => {
    setSelectedImage(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setResult(null);
    setLastRequestId(null);
    setFeedback(null);
  };

  const handleFeedback = async (value: "positive" | "negative") => {
    if (feedback || !lastRequestId) return;
    try {
      await submitFeedback(lastRequestId, value, "image");
      setFeedback(value);
      toast.success("Thanks for your feedback!");
    } catch {
      toast.error("Failed to submit feedback");
    }
  };

  const extractErrorMessage = (error: any) => {
    const d = error?.response?.data;
    const detail = Array.isArray(d?.detail)
      ? d.detail.map((e: any) => e?.msg ?? String(e)).join("; ")
      : d?.detail;
    return (
      error?.message ??
      detail ??
      d?.error ??
      d?.message ??
      "Failed to diagnose image"
    );
  };

  const handleDiagnose = async () => {
    if (!selectedImage) {
      toast.error("Please select an image first");
      return;
    }

    try {
      setIsLoading(true);
      setFeedback(null);
      const response = await askImage(selectedImage);
      setResult(response?.analysis ?? "");
      setLastRequestId(response?.request_id ?? null);
      toast.success("Diagnosis complete");
    } catch (error: any) {
      console.error("Diagnosis error:", error);
      toast.error(extractErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
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
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary text-sm font-medium mb-4">
            <Camera className="w-4 h-4" />
            <span>AI-Powered Diagnosis</span>
          </div>
          <h1 className="text-3xl md:text-4xl font-bold text-foreground mb-3">
            Plant Image Diagnosis
          </h1>
          <p className="text-muted-foreground max-w-lg mx-auto text-balance">
            Upload an image of your crop to detect pests, diseases, or other issues. 
            Our AI will analyze and provide recommendations.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          <Card className="p-6 md:p-8 space-y-6 border-border/60 shadow-lg">
            <AnimatePresence mode="wait">
              {!previewUrl ? (
                <motion.label
                  key="dropzone"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  className={`flex flex-col items-center justify-center border-2 border-dashed rounded-2xl p-12 cursor-pointer transition-all duration-300 ${
                    isDragOver
                      ? "border-primary bg-primary/5 scale-[1.01]"
                      : "border-border hover:border-primary/50 hover:bg-secondary/30"
                  }`}
                >
                  <input
                    type="file"
                    accept="image/jpeg,image/png"
                    onChange={handleImageSelect}
                    className="hidden"
                  />
                  <motion.div
                    animate={{ y: isDragOver ? -5 : 0 }}
                    className="w-20 h-20 rounded-2xl bg-gradient-to-br from-primary/20 to-accent/20 flex items-center justify-center mb-6 shadow-md"
                  >
                    <Upload className={`w-10 h-10 ${isDragOver ? "text-primary" : "text-muted-foreground"}`} />
                  </motion.div>
                  <p className="text-lg font-semibold text-foreground mb-2">
                    {isDragOver ? "Drop your image here" : "Click or drag to upload"}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Supports JPG, PNG (max 8MB)
                  </p>
                </motion.label>
              ) : (
                <motion.div
                  key="preview"
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  className="space-y-6"
                >
    
                  <div className="relative group">
                    <motion.img
                      layoutId="cropImage"
                      src={previewUrl}
                      alt="Selected crop"
                      className="w-full max-h-[400px] object-contain rounded-2xl border-2 border-primary/20 shadow-xl bg-secondary/20"
                    />
                    <motion.button
                      whileHover={{ scale: 1.1 }}
                      whileTap={{ scale: 0.9 }}
                      onClick={removeImage}
                      className="absolute top-3 right-3 w-10 h-10 bg-destructive text-destructive-foreground rounded-xl flex items-center justify-center shadow-lg opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <X className="w-5 h-5" />
                    </motion.button>
                  </div>

    
                  <AnimatePresence mode="wait">
                    {!result && !isLoading && (
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                      >
                        <Button 
                          onClick={handleDiagnose} 
                          className="w-full" 
                          size="xl"
                          variant="hero"
                        >
                          <Camera className="w-5 h-5 mr-2" />
                          Analyze Image
                        </Button>
                      </motion.div>
                    )}

                    {isLoading && (
                      <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                      >
                        <Loader message="Analyzing your crop image..." />
                      </motion.div>
                    )}

                    {result && !isLoading && (
                      <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="bg-secondary/30 border border-border rounded-2xl p-6 space-y-4"
                      >
                        <div className="flex items-center gap-2 text-primary">
                          <CheckCircle className="w-5 h-5" />
                          <h3 className="text-lg font-bold">Diagnosis Result</h3>
                        </div>
                        
                        <div className="prose dark:prose-invert max-w-none text-card-foreground">
                          <ReactMarkdown 
                            remarkPlugins={[remarkGfm]}
                            components={{
                              a: ({ node, ...props }) => (
                                <a {...props} target="_blank" rel="noopener noreferrer" className="underline font-medium text-primary hover:opacity-80" />
                              ),
                              ul: ({ node, ...props }) => (
                                <ul {...props} className="list-disc pl-4 mb-2 space-y-1" />
                              ),
                              ol: ({ node, ...props }) => (
                                <ol {...props} className="list-decimal pl-4 mb-2 space-y-1" />
                              ),
                            }}
                          >
                            {result}
                          </ReactMarkdown>
                        </div>

                        {lastRequestId && (
                          <div className="flex items-center gap-2 mt-3 pt-3 border-t border-border/50">
                            <span className="text-xs text-muted-foreground">Was this helpful?</span>
                            <button
                              type="button"
                              onClick={() => handleFeedback("positive")}
                              disabled={feedback !== null}
                              className={cn(
                                "p-2 rounded-lg hover:bg-muted transition-colors",
                                feedback === "positive" && "text-green-600 bg-green-500/10"
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
                                "p-2 rounded-lg hover:bg-muted transition-colors",
                                feedback === "negative" && "text-red-600 bg-red-500/10"
                              )}
                              aria-label="Not helpful"
                            >
                              <ThumbsDown className="w-4 h-4" />
                            </button>
                          </div>
                        )}

                        <Button 
                          onClick={removeImage} 
                          variant="outline" 
                          className="w-full mt-4"
                        >
                          Analyze Another Image
                        </Button>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.div>
              )}
            </AnimatePresence>
          </Card>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="grid grid-cols-1 md:grid-cols-3 gap-4"
        >
          {[
            { icon: "📸", title: "Clear Photos", desc: "Use well-lit, focused images" },
            { icon: "🍃", title: "Close-ups", desc: "Capture affected leaves or stems" },
            { icon: "🔍", title: "Multiple Angles", desc: "Different views help accuracy" },
          ].map((tip, i) => (
            <motion.div
              key={i}
              whileHover={{ y: -2 }}
              className="flex items-start gap-3 p-4 rounded-xl bg-card border border-border/50"
            >
              <span className="text-2xl">{tip.icon}</span>
              <div>
                <p className="font-medium text-sm text-foreground">{tip.title}</p>
                <p className="text-xs text-muted-foreground">{tip.desc}</p>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </motion.div>
  );
};

export default ImageDiagnosis;
