import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import legacy from '@vitejs/plugin-legacy'

// 移动优先：基线取微信内置浏览器与 Android 8 级 WebView（X5/XWeb 约 Chromium 77+），
// 以及 iOS/Safari 13。Chrome 49 级老内核不在范围内——那类设备的系统信任库缺新根证书，
// HTTPS 握手先失败，ES5 产物也救不回来。
const MOBILE_TARGETS = 'Chrome >= 77, ChromeAndroid >= 77, Firefox >= 78, Safari >= 13, iOS >= 13, Edge >= 79'

export default defineConfig({
  plugins: [
    vue(),
    legacy({
      targets: MOBILE_TARGETS,
      // 只为现代产物补缺失 API，不再另产一套 SystemJS 的 ES5 包：
      // 目标设备都支持 <script type="module">，那套包约占 dist 一半且永远不执行。
      renderLegacyChunks: false,
      modernPolyfills: true,
      modernTargets: MOBILE_TARGETS,
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
    target: 'es2018',
    chunkSizeWarningLimit: 1500,
  },
})
