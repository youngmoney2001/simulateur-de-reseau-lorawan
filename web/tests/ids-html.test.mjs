// Les identifiants que `main.js` demande au DOM doivent exister dans `studio.html`.
//
// `$("inconnu")` renvoie `null` sans broncher : la faute n'apparaît qu'au moment où le code
// touche l'élément, c'est-à-dire au clic, dans un navigateur, sur un état précis. C'est le
// genre de défaut qu'aucun test de module pur ne peut voir — et qu'un simple rapprochement
// entre deux fichiers attrape immédiatement.
//
// Ce test ne remplace pas le navigateur : il ne dit rien de la mise en page. Il dit seulement
// que le câblage par identifiant est complet, ce qui est vérifiable sans affichage.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const lire = (p) => readFileSync(new URL(p, import.meta.url), "utf-8");

const html = lire("../studio.html");
const js = lire("../src/studio/main.js");

/** Identifiants présents dans le balisage, attribut `id="..."`. */
function idsDuHtml(texte) {
  const ids = new Set();
  for (const m of texte.matchAll(/\sid="([^"]+)"/g)) ids.add(m[1]);
  return ids;
}

/** Identifiants demandés par le code : `$("x")` et `getElementById("x")`. */
function idsDuJs(texte) {
  const ids = new Set();
  for (const m of texte.matchAll(/\$\("([^"]+)"\)/g)) ids.add(m[1]);
  for (const m of texte.matchAll(/getElementById\("([^"]+)"\)/g)) ids.add(m[1]);
  // `$(\`x-${i}\`)` : identifiant composé, on garde le préfixe connu du HTML.
  return ids;
}

test("tout identifiant demandé par main.js existe dans studio.html", () => {
  const connus = idsDuHtml(html);
  const demandes = [...idsDuJs(js)].sort();
  assert.ok(demandes.length > 40, `peu d'identifiants trouvés (${demandes.length}) : motif cassé`);
  const manquants = demandes.filter((id) => !connus.has(id));
  assert.deepEqual(manquants, [],
    `identifiant(s) demandé(s) par main.js et absent(s) de studio.html : ${manquants.join(", ")}`);
});

test("l'encadré du débit commandé par le serveur est câblé", () => {
  // Le bloc n'existe que dans le HTML : c'est le rendu qui le remplit. S'il manquait, le run
  // se terminerait correctement et l'utilisateur ne verrait jamais le changement de débit.
  const connus = idsDuHtml(html);
  for (const id of ["adr-bilan", "adr-bilan-liste", "adr-bilan-aide"]) {
    assert.ok(connus.has(id), `#${id} absent de studio.html`);
    assert.ok(js.includes(`"${id}"`), `#${id} n'est jamais utilisé par main.js`);
  }
});
