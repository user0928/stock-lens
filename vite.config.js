import { defineConfig } from "vite";
export default defineConfig({
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  build: {
    outDir: "dist",
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("/node_modules/zrender/")) return "renderer";
          if (id.includes("/node_modules/echarts/")) return "charts";
          if (id.includes("/node_modules/react")) return "react";
        },
      },
    },
  },
});
