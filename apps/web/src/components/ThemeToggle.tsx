"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

type Theme = "light" | "dark";

function subscribeTheme(callback: () => void) {
  const observer = new MutationObserver(callback);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}
function getThemeSnapshot(): Theme {
  return (document.documentElement.getAttribute("data-theme") as Theme) || "light";
}
function getThemeServerSnapshot(): Theme {
  return "light";
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, getThemeSnapshot, getThemeServerSnapshot);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
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
      {theme === "dark" ? <Sun /> : <Moon />}
    </button>
  );
}
