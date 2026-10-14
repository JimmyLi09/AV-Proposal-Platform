import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时把 /api 转给本机 FastAPI（python -m app）
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8081" } },
});
