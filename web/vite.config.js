import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // Accessible depuis l'aperçu distant : écoute sur toutes les interfaces.
    host: "0.0.0.0",
    port: 5173,
    // L'aperçu est servi sous un hôte distant : toute origine est acceptée
    // pour le serveur de développement uniquement.
    allowedHosts: true,
  },
  build: {
    chunkSizeWarningLimit: 6000, // CesiumJS est volumineux par nature
  },
});
