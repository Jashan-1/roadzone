import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// dev: `uv run python -m zonegen serve` on 8600 answers /api and /zone; vite serves the page with hot reload
const api = 'http://127.0.0.1:8600';
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': api, '/zone': api } },
});
