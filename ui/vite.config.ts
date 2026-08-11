import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    exclude: ["lucide-react"],
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  server: {
    port: 5174,
    strictPort: true,
    host: true,
    proxy: {
      // 本地开发只代理到同机 FastAPI；生产环境仍由 VITE_API_URL 或反向代理决定。
      '^/(ai|capabilities|companies|research|generate-pdf|jobs|reports|pdfs)(/|$)': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
        secure: false,
      },
    },
  },
});
