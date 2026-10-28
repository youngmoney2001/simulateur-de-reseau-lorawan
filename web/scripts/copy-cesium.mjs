// Copie les ressources statiques de CesiumJS (workers, assets, widgets) dans
// public/cesium, servi tel quel par Vite. Aucune ressource n'est chargée depuis
// un CDN tiers : la carte fonctionne sans accès à un service Cesium ion.
import { cp, mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "node_modules", "cesium", "Build", "Cesium");
const target = join(root, "public", "cesium");

if (!existsSync(source)) {
  console.error("CesiumJS introuvable : exécutez `npm install` dans web/");
  process.exit(1);
}
await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
for (const dir of ["Workers", "ThirdParty", "Assets", "Widgets"]) {
  await cp(join(source, dir), join(target, dir), { recursive: true });
}
console.log("CesiumJS : ressources copiées dans public/cesium");
