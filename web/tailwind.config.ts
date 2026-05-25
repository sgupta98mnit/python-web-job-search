import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0a0a0f",
        foreground: "#e8fff4",
        card: "#101018",
        "card-foreground": "#e8fff4",
        popover: "#101018",
        "popover-foreground": "#e8fff4",
        primary: "#00ff88",
        "primary-foreground": "#04130b",
        secondary: "#00d9ff",
        "secondary-foreground": "#031014",
        muted: "#161622",
        "muted-foreground": "#8aa39a",
        accent: "#00ff88",
        "accent-foreground": "#04130b",
        destructive: "#ff355e",
        "destructive-foreground": "#fff2f5",
        border: "#1f3d34",
        input: "#17241f",
        ring: "#00ff88",
        cyber: {
          bg: "#0a0a0f",
          panel: "#101018",
          panel2: "#121621",
          grid: "rgba(0,255,136,0.13)",
          accent: "#00ff88",
          cyan: "#00d9ff",
          magenta: "#ff2bd6",
          yellow: "#f9ff4a",
          red: "#ff355e",
          muted: "#8aa39a",
        },
      },
      fontFamily: {
        heading: ["var(--font-orbitron)", "monospace"],
        mono: ["var(--font-jetbrains)", "monospace"],
        label: ["var(--font-share-tech)", "monospace"],
      },
      boxShadow: {
        neon: "0 0 16px rgba(0,255,136,0.45), inset 0 0 20px rgba(0,255,136,0.08)",
        "neon-cyan": "0 0 18px rgba(0,217,255,0.4)",
        "neon-magenta": "0 0 18px rgba(255,43,214,0.35)",
        terminal: "0 0 0 1px rgba(0,255,136,0.35), 0 18px 60px rgba(0,0,0,0.45)",
      },
      keyframes: {
        blink: {
          "0%, 48%": { opacity: "1" },
          "49%, 100%": { opacity: "0" },
        },
        glitch: {
          "0%, 100%": { transform: "translate(0)" },
          "18%": { transform: "translate(-1px, 1px)" },
          "20%": { transform: "translate(1px, -1px)" },
          "22%": { transform: "translate(0)" },
          "66%": { transform: "translate(1px, 0)" },
          "68%": { transform: "translate(-1px, 0)" },
          "70%": { transform: "translate(0)" },
        },
        rgbShift: {
          "0%, 100%": { textShadow: "1px 0 #00d9ff, -1px 0 #ff2bd6, 0 0 16px rgba(0,255,136,0.6)" },
          "50%": { textShadow: "-1px 0 #00d9ff, 1px 0 #ff2bd6, 0 0 24px rgba(0,255,136,0.8)" },
        },
        scanline: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100vh)" },
        },
      },
      animation: {
        blink: "blink 1s steps(1) infinite",
        glitch: "glitch 2.6s infinite",
        "rgb-shift": "rgbShift 3.2s infinite",
        scanline: "scanline 6s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
