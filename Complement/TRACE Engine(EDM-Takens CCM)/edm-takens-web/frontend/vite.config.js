import { defineConfig } from 'vite'

export default defineConfig({
  // 使用相对路径，便于便携式部署（file:// 或子路径），避免绝对路径 /assets/... 在 file:// 下失效
  base: './',
  server: {
    port: Number(process.env.VITE_PORT || 5173),
    strictPort: true,
    host: true,
    allowedHosts: ['.trycloudflare.com', 'localhost', '127.0.0.1'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/api/results': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
