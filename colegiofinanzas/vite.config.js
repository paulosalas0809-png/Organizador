import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// La app compilada la sirve el servidor de Python desde /static/colegio/ (ruta pública: /colegio).
// En desarrollo, `npm run dev` reenvía /api al backend local (py -m organizador.web, puerto 8000).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/colegio/",
  build: { outDir: "../organizador/static/colegio", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { proxy: { "/api": "http://localhost:8000" } },
});
