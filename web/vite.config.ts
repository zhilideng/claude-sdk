import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0", // 绑定所有网卡，允许用局域网 IP 访问（原 127.0.0.1 只能本机访问）
    port: 5173,
    proxy: {
      "/v1": "http://127.0.0.1:8003",
    },
  },
  preview: {
    host: "0.0.0.0", // 同 server：preview 模式也允许局域网 IP 访问
    port: 4173,
  },
});
