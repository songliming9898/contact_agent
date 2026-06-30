import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { createRequire } from 'module'

const _require = createRequire(import.meta.url)

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  css: {
    postcss: {
      plugins: [
        _require('postcss-px-to-viewport-8-plugin')({
          viewportWidth: 375,
          unitPrecision: 5,
          viewportUnit: 'vw',
          selectorBlackList: [],
          minPixelValue: 1,
          mediaQuery: false,
        }),
      ],
    },
  },
})
