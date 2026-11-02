import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const rawBackendTarget = process.env.VITE_API_URL || 'https://kawad-swad-sales-dev.onrender.com';
const backendTarget = rawBackendTarget.trim().replace(/\/$/, '');

function createProxyRule(prefix: string) {
  return {
    target: backendTarget,
    changeOrigin: true,
    secure: true,
    configure: (proxy: any) => {
      proxy.on('proxyReq', (proxyReq: any, req: any) => {
        const fullTarget = `${backendTarget}${req.url}`;
        console.log(`[Vite Proxy -> Backend] ${req.method} ${req.url} -> ${fullTarget}`);
      });
      proxy.on('proxyRes', (proxyRes: any, req: any) => {
        const status = proxyRes.statusCode;
        const color = status >= 500 ? '\x1b[31m' : status >= 400 ? '\x1b[33m' : '\x1b[32m';
        console.log(
          `[Vite Proxy <- Backend] ${req.method} ${req.url} -> ${color}HTTP ${status}\x1b[0m`
        );
      });
      proxy.on('error', (err: any, req: any, res: any) => {
        console.warn(
          `[Vite Proxy Notice] Target ${backendTarget} unreachable for ${req.method} ${req.url}: ${err.message}`
        );
        if (res && !res.headersSent && typeof res.writeHead === 'function') {
          if (req.url && req.url.includes('/health')) {
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(
              JSON.stringify({
                status: 'standby',
                service: 'kawad-swad-sales-dev',
                google_sheets_connected: false,
                persistent_writes_enabled: false,
                last_connection_error: `Backend at ${backendTarget} is currently offline or sleeping. Operating in Standby Mode.`,
                backend: { status: 'STANDBY', service: 'kawad-swad-sales-dev', version: '1.0.0' },
                google_sheets: { status: 'STANDBY', connected: false, message: 'Standby Mode active.' },
                required_sheets: { status: 'STANDBY', total_managed_tabs: 28 },
              })
            );
          } else {
            res.writeHead(503, { 'Content-Type': 'application/json' });
            res.end(
              JSON.stringify({
                detail: `Backend server at ${backendTarget} is unreachable or offline. Local Standby Mode active.`,
              })
            );
          }
        }
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': createProxyRule('/api'),
      '/health': createProxyRule('/health'),
      '/auth': createProxyRule('/auth'),
    },
  },
});
