import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0f172a",
        mist: "#eef4ff",
        line: "#d7e1f5",
        glow: "#4f46e5",
        teal: "#0f766e",
        sand: "#f4ede1",
        gold: "#b88a44",
      },
      boxShadow: {
        soft: "0 20px 45px rgba(15, 23, 42, 0.08)",
        lift: "0 28px 60px rgba(15, 23, 42, 0.12)",
      },
      backgroundImage: {
        "hero-grid":
          "linear-gradient(to right, rgba(148,163,184,0.12) 1px, transparent 1px), linear-gradient(to bottom, rgba(148,163,184,0.12) 1px, transparent 1px)",
      },
      animation: {
        floaty: "floaty 7s ease-in-out infinite",
        shimmer: "shimmer 2.8s ease-in-out infinite",
        rise: "rise 0.55s ease-out both",
      },
      keyframes: {
        floaty: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-8px)" },
        },
        shimmer: {
          "0%, 100%": { opacity: "0.9" },
          "50%": { opacity: "1" },
        },
        rise: {
          from: { opacity: "0", transform: "translateY(14px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
