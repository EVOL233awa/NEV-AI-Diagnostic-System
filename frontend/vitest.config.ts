import { defineConfig } from 'vitest/config'

// 独立于 vite.config.ts：单测不需要 legacy/生产构建插件，保持启动轻量
export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    css: false,
  },
})
