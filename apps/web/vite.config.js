import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const apiHost = process.env.API_PROXY_HOST || "127.0.0.1";
const apiPort = Number(process.env.API_PROXY_PORT || 8000);

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "0.0.0.0",
    port: Number(process.env.PORT || 5173),
    proxy: {
      "/api": {
        target: `http://${apiHost}:${apiPort}`,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
