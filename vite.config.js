import {defineConfig} from 'vite';import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],build:{sourcemap:false,chunkSizeWarningLimit:650},test:{environment:'jsdom',setupFiles:['./tests/setup.js'],exclude:['node_modules/**','dist/**']}});
