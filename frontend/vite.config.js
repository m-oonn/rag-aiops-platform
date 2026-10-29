import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需：模板里的 el-* 自动引入组件与样式；dts 关闭避免生成类型声明
    AutoImport({ resolvers: [ElementPlusResolver()], dts: false }),
    Components({ resolvers: [ElementPlusResolver()], dts: false }),
  ],
  build: {
    // 拆出稳定的第三方依赖块：首屏并行加载 + 业务代码更新时缓存不失效
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('echarts') || id.includes('zrender')) return 'vendor-echarts'
          if (id.includes('element-plus')) return 'vendor-element'
          if (id.includes('marked') || id.includes('dompurify')) return 'vendor-markdown'
          if (id.includes('vue') || id.includes('pinia') || id.includes('vue-router')) return 'vendor-vue'
          return 'vendor'
        },
      },
    },
  },
  server: {
    // 端口 5273 避开 Windows 保留段(5145-5244 等,否则 EACCES 起不来)
    host: '127.0.0.1',
    port: 5273,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8200',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
