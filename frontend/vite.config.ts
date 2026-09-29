import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import legacy from '@vitejs/plugin-legacy'

// legacy 插件产出 ES2015 级兼容产物（决策 #16：给老内核车机 WebView 留后路）。
// browserslist 不接受字面量 "es2015"，用等价的保守浏览器版本表达同一目标。
export default defineConfig({
  plugins: [
    vue(),
    legacy({
      targets: ['Chrome >= 49', 'Firefox >= 45', 'Safari >= 9', 'Edge >= 15', 'Android >= 6'],
      modernPolyfills: true,
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8600',
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
})
