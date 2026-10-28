// Garde-fou : aucune requête vers Cesium ion (jeton requis, non fourni ici).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = readFileSync(join(root, "src", "main.js"), "utf8");
if (/ion\.cesium|Ion\.defaultAccessToken|createWorldTerrain|createWorldImagery/.test(src)) {
  console.error("src/main.js référence Cesium ion : interdit sans contrat");
  process.exit(1);
}
console.log("aucune dépendance Cesium ion");
