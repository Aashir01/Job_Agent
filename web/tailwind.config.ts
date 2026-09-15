import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces: cool graphite, tinted so the greys read as authored.
        ink: "#0a0c11",
        panel: "#11141b",
        raised: "#171b24",
        edge: "#232a38",
        "edge-strong": "#333c4f",

        // Text ramp. Three steps, each obviously apart.
        fg: "#e8ebf2",
        muted: "#96a0b5",
        faint: "#6b7488",

        // The one interaction colour. Chrome only: focus, selection, links.
        accent: "#7aa2ff",
        "accent-dim": "#2b3a63",

        // State. Never the only signal: every use carries an icon or a word.
        fast: "#3fcf8e",
        standard: "#e9b949",
        marginal: "#f2748a",
      },
      fontFamily: {
        sans: [
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
        xs: ["0.75rem", { lineHeight: "1.125rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.9375rem", { lineHeight: "1.5rem" }],
        lg: ["1.0625rem", { lineHeight: "1.5rem" }],
        xl: ["1.25rem", { lineHeight: "1.75rem" }],
        "2xl": ["1.625rem", { lineHeight: "2rem", letterSpacing: "-0.01em" }],
      },
      borderRadius: {
        lg: "10px",
        xl: "14px",
        "2xl": "18px",
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 1px 2px rgba(0,0,0,0.5)",
        raised: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 12px 32px -16px rgba(0,0,0,0.8)",
        pop: "0 24px 64px -24px rgba(0,0,0,0.9)",
        "accent-glow": "0 0 0 1px rgba(122,162,255,0.35), 0 8px 24px -12px rgba(122,162,255,0.5)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "pulse-dot": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        "fade-up": "fade-up 200ms cubic-bezier(0.22, 1, 0.36, 1) both",
        "fade-in": "fade-in 150ms cubic-bezier(0.22, 1, 0.36, 1) both",
        "pulse-dot": "pulse-dot 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
