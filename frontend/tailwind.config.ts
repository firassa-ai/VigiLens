import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["var(--font-display)"],
        sans: ["var(--font-body)"],
        mono: ["var(--font-mono)"],
      },
      colors: {
        surface: {
          root: "var(--bg-root)",
          panel: "var(--bg-panel)",
          card: "var(--bg-card)",
          elevated: "var(--bg-elevated)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          hover: "var(--accent-hover)",
          dim: "var(--accent-dim)",
        },
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "slide-in-right": {
          "0%": { opacity: "0", transform: "translateX(12px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        "scale-in": {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0 rgba(212, 149, 106, 0.3)" },
          "70%": { boxShadow: "0 0 0 6px rgba(212, 149, 106, 0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(212, 149, 106, 0)" },
        },
        "glow-pulse": {
          "0%, 100%": { opacity: "0.6" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        "fade-up": "fade-up 400ms ease-out both",
        "fade-rise": "fade-up 400ms ease-out both",
        "fade-in": "fade-in 300ms ease-out both",
        "slide-in-right": "slide-in-right 350ms ease-out both",
        "scale-in": "scale-in 300ms ease-out both",
        shimmer: "shimmer 2.2s linear infinite",
        "pulse-ring": "pulse-ring 1.5s ease infinite",
        "glow-pulse": "glow-pulse 2s ease-in-out infinite",
      },
      boxShadow: {
        panel: "0 1px 2px rgba(0, 0, 0, 0.3), 0 8px 24px -8px rgba(0, 0, 0, 0.4)",
        glow: "0 0 20px -4px rgba(212, 149, 106, 0.15)",
        "glow-lg": "0 0 40px -8px rgba(212, 149, 106, 0.2)",
      },
    },
  },
  plugins: [],
} satisfies Config;
