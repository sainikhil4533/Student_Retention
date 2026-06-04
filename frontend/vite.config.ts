import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
  },
  build: {
    // Reduce initial bundle size
    target: "ES2020",
    minify: "terser",
    terserOptions: {
      compress: {
        drop_console: true,
      },
    },
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Core vendor chunks
          if (id.includes("node_modules/react")) {
            return "vendor-react";
          }
          if (id.includes("node_modules/react-router-dom")) {
            return "vendor-router";
          }
          if (id.includes("node_modules/@tanstack/react-query")) {
            return "vendor-query";
          }
          // UI & visualization
          if (id.includes("node_modules/recharts")) {
            return "vendor-charts";
          }
          if (id.includes("node_modules/lucide-react")) {
            return "vendor-icons";
          }
          if (id.includes("node_modules/framer-motion")) {
            return "vendor-motion";
          }
          // Page-specific chunks
          if (id.includes("/pages/admin")) {
            return "pages-admin";
          }
          if (id.includes("/pages/counsellor")) {
            return "pages-counsellor";
          }
          if (id.includes("/pages/student")) {
            return "pages-student";
          }
          if (id.includes("/pages/login")) {
            return "pages-auth";
          }
          if (id.includes("/pages/chat")) {
            return "pages-chat";
          }
          if (id.includes("/components")) {
            return "components";
          }
        },
      },
    },
  },
});
