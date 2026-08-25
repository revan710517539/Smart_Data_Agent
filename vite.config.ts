import { defineConfig, type ProxyOptions } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

// Port 8787 is commonly occupied by the separate STOS/Uvicorn runtime on this
// workstation. Smart Data Agent's local API runs on 8788, so keep the frontend
// proxy aligned with it unless an explicit environment override is supplied.
const apiProxyTarget = process.env.SMART_DATA_AGENT_API_PROXY_TARGET || 'http://127.0.0.1:8788'

export default defineConfig({
  plugins: [
    // The React and Tailwind plugins are both required for Make, even if
    // Tailwind is not being actively used – do not remove them
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      // Alias @ to the src directory
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router'],
        },
      },
    },
  },

  // File types to support raw imports. Never add .css, .tsx, or .ts files to this.
  assetsInclude: ['**/*.svg', '**/*.csv'],
  server: {
    proxy: {
      '/api': apiProxy(),
    },
  },
  preview: {
    proxy: {
      '/api': apiProxy(),
    },
  },
})

function apiProxy(): ProxyOptions {
  return {
    target: apiProxyTarget,
    changeOrigin: true,
    ws: true,
    configure(proxy) {
      proxy.on('error', (err, _req, res) => {
        if (!res.writeHead || res.headersSent) return
        res.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8', 'Retry-After': '2' })
        res.end(JSON.stringify({
          error: 'api_unavailable',
          message: 'Data Agent API 暂时无法连接，服务正在启动或重启，请稍后重试。',
          detail: String((err as Error & { code?: string }).code || err),
        }))
      })
    },
  }
}
