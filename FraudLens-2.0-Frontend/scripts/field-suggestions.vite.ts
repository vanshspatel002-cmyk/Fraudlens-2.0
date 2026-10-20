// Isolated component rehearsal; does not load the application SSR/worker stack.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    entries: ["scripts/field-suggestions-harness.tsx"],
    include: ["react", "react-dom/client", "react/jsx-runtime"],
  },
  server: { host: "127.0.0.1", port: 5174, strictPort: true },
});
