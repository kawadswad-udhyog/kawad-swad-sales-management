import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const backendTarget = process.env.VITE_API_URL || 'https://kawad-swad-sales-backend.onrender.com';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        secure: true,
      },
      '/health': {
        target: backendTarget,
        changeOrigin: true,
        secure: true,
      },
    },
  },
});
