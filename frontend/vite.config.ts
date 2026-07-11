import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const v2Target = process.env.VITE_DEV_API_PROXY_TARGET || process.env.MATTS_V2_API_PROXY_TARGET || 'http://127.0.0.1:18182';
const legacyTarget = process.env.VITE_LEGACY_API_PROXY_TARGET || process.env.MATTS_LEGACY_API_PROXY_TARGET || 'http://127.0.0.1:18181';

function packageChunk(id: string): string | undefined {
  if (!id.includes('/node_modules/')) return undefined;
  if (id.includes('/node_modules/react') || id.includes('/node_modules/react-dom') || id.includes('/node_modules/@tanstack/')) return 'vendor-react';
  return undefined;
}

export default defineConfig({
  plugins: [react()],
  build: {
    modulePreload: false,
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks: packageChunk
      }
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: false,
    proxy: {
      '/v2': { target: v2Target, ws: true },
      '/api': { target: legacyTarget, ws: false },
      '/ws': { target: legacyTarget, ws: true }
    }
  }
});
