"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

type Theme = "light" | "dark";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const current = (document.documentElement.getAttribute("data-theme") as Theme) || "light";
    setTheme(current);
    setMounted(true);
  }, []);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("cloudsite-theme", next); } catch {}
  };

  return (
    <button
      className="topbar-icon theme-toggle"
      onClick={toggle}
      aria-label="切换浅色/暗色主题"
      title={theme === "dark" ? "切换到浅色" : "切换到暗色"}
      suppressHydrationWarning
    >
      {mounted && theme === "dark" ? <Sun /> : <Moon />}
    </button>
  );
}
