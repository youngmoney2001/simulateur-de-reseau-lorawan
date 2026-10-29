import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

// Serveur d'API local pour le studio : `/api` est proxifié, le navigateur ne voit jamais l'API
// directement (pas d'hôte codé en dur côté client). Surchargeable pour un autre port.
const API_TARGET = process.env.LSIM_API_URL || "http://127.0.0.1:8765";

export default defineConfig({
  server: {
    // Accessible depuis l'aperçu distant : écoute sur toutes les interfaces.
    host: "0.0.0.0",
    port: 5173,
    // L'aperçu est servi sous un hôte distant : toute origine est acceptée
    // pour le serveur de développement uniquement.
    allowedHosts: true,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: false },
    },
  },
  build: {
    chunkSizeWarningLimit: 6000, // CesiumJS est volumineux par nature
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        studio: fileURLToPath(new URL("./studio.html", import.meta.url)),
      },
    },
  },
});
