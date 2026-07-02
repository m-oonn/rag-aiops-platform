import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    // 端口 5273 避开 Windows 保留段(5145-5244 等,否则 EACCES 起不来)
    host: '127.0.0.1',
    port: 5273,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8200',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
