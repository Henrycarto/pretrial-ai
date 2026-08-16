import type { Config } from "tailwindcss";

/**
 * The palette is fixed by the product design brief and is not a starting
 * point to be adjusted per screen. Colours are declared here as named tokens
 * rather than as arbitrary hex values in class strings so that a component
 * cannot quietly introduce a fourth shade of navy.
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        shell: "#080F1A",
        surface: {
          DEFAULT: "#0E1B2E",
          raised: "#132540",
          sunken: "#0A1524",
        },
        edge: {
          DEFAULT: "#1C3049",
          strong: "#27415F",
          faint: "#152438",
        },
        ink: {
          DEFAULT: "#E6EDF7",
          muted: "#8FA4C0",
          dim: "#62789A",
        },
        accent: {
          DEFAULT: "#2563EB",
          bright: "#3B82F6",
          dim: "#1B3F8F",
        },
        signal: {
          pass: "#10B981",
          warn: "#F59E0B",
          fail: "#EF4444",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        // The signature FidelityScoreBadge number. Fixed at 48px by the brief.
        score: ["48px", { lineHeight: "1", letterSpacing: "-0.02em" }],
        micro: ["10px", { lineHeight: "1.4", letterSpacing: "0.08em" }],
      },
      borderRadius: {
        // Sharp by default. This is instrumentation, not a consumer app, and
        // rounded corners are the fastest way to make it read as one.
        DEFAULT: "2px",
        none: "0",
        sm: "2px",
        md: "3px",
        lg: "4px",
      },
      boxShadow: {
        // Deliberately empty of soft drop shadows. Separation comes from
        // 1px rules and background steps, not from floating cards.
        none: "none",
        inset: "inset 0 1px 0 0 rgba(255,255,255,0.03)",
      },
      spacing: {
        px2: "2px",
      },
    },
  },
  plugins: [],
};

export default config;
