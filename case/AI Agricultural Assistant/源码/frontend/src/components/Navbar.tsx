import { Link, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { Sprout, MessageSquare, Image, History, Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { Button } from "@/components/ui/button";

const Navbar = () => {
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const navItems = [
    { path: "/", label: "Chat", icon: MessageSquare },
    { path: "/image", label: "Diagnosis", icon: Image },
    { path: "/history", label: "History", icon: History },
  ];

  const isActivePath = (path: string) => location.pathname === path;

  return (
    <motion.nav
      initial={{ y: -100 }}
      animate={{ y: 0 }}
      transition={{ type: "spring", stiffness: 100, damping: 20 }}
      className="bg-card/95 backdrop-blur-md border-b border-border sticky top-0 z-50 shadow-sm"
    >
      <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">

        <Link to="/" className="flex items-center gap-3 group">
          <motion.div
            whileHover={{ scale: 1.05, rotate: 5 }}
            whileTap={{ scale: 0.95 }}
            className="w-11 h-11 bg-gradient-hero rounded-xl flex items-center justify-center shadow-md group-hover:shadow-glow transition-shadow duration-300"
          >
            <Sprout className="w-6 h-6 text-primary-foreground" />
          </motion.div>
          <div className="hidden sm:block">
            <h1 className="text-xl font-bold text-foreground leading-tight tracking-tight">
              Agri<span className="text-primary">GPT</span>
            </h1>
            <p className="text-[10px] text-muted-foreground font-medium tracking-wide uppercase">
              Smart Farming Assistant
            </p>
          </div>
        </Link>

        <div className="hidden md:flex items-center gap-1 p-1 rounded-xl bg-secondary/50">
          {navItems.map(({ path, label, icon: Icon }) => (
            <Link key={path} to={path}>
              <motion.div
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                className={cn(
                  "relative flex items-center gap-2 px-4 py-2.5 rounded-lg transition-all duration-200",
                  isActivePath(path)
                    ? "text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                )}
              >
                {isActivePath(path) && (
                  <motion.div
                    layoutId="activeTab"
                    className="absolute inset-0 bg-primary rounded-lg shadow-md"
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                  />
                )}
                <Icon className="w-4 h-4 relative z-10" />
                <span className="text-sm font-medium relative z-10">{label}</span>
              </motion.div>
            </Link>
          ))}
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        >
          {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </Button>
      </div>

      {mobileMenuOpen && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          className="md:hidden border-t border-border bg-card/95 backdrop-blur-md"
        >
          <div className="px-4 py-3 space-y-1">
            {navItems.map(({ path, label, icon: Icon }) => (
              <Link
                key={path}
                to={path}
                onClick={() => setMobileMenuOpen(false)}
                className={cn(
                  "flex items-center gap-3 px-4 py-3 rounded-xl transition-all",
                  isActivePath(path)
                    ? "bg-primary text-primary-foreground shadow-md"
                    : "text-foreground hover:bg-secondary"
                )}
              >
                <Icon className="w-5 h-5" />
                <span className="font-medium">{label}</span>
              </Link>
            ))}
          </div>
        </motion.div>
      )}
    </motion.nav>
  );
};

export default Navbar;
