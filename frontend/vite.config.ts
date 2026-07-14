import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueClickToComponent from 'vue-click-to-component/vite-plugin'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vueClickToComponent(), vue()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.ts'],
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@docs': fileURLToPath(new URL('../docs', import.meta.url)),
    },
  },
  server: {
    fs: { allow: ['..'] },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router', 'pinia', 'vue-i18n'],
          'naive-ui': ['naive-ui'],
        },
      },
    },
  },
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
