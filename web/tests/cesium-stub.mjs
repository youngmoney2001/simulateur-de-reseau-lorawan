// Remplace le module `cesium` par le faux de `tests/faux-cesium.mjs`, pour les tests.
//
// Sans cela, `map3d.js` ne serait vérifiable que dans un navigateur avec WebGL, donc
// nulle part dans l'intégration continue. Le faux ne prétend pas rendre : il retient les
// décisions de la carte, qui sont seules en cause ici.
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

const ici = dirname(fileURLToPath(import.meta.url));
const faux = pathToFileURL(join(ici, "faux-cesium.mjs")).href;

registerHooks({
  resolve(specifier, context, next) {
    if (specifier === "cesium") return { url: faux, shortCircuit: true };
    return next(specifier, context);
  },
});

// `window` : `map3d.js` y pose CESIUM_BASE_URL au chargement du module.
globalThis.window ??= globalThis;
// La carte recale son canevas après une frame et observe la taille de son conteneur.
globalThis.requestAnimationFrame ??= (cb) => setTimeout(() => cb(Date.now()), 0);
globalThis.ResizeObserver ??= class { observe() {} disconnect() {} };
