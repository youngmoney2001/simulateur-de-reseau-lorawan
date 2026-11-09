// Rapport de l'audit clavier, en Markdown.
//
// Module séparé du script d'audit, pour la même raison que `rapport-audit.mjs` : le script
// lève « CHROME_PATH requis » dès son import, donc une fonction enfouie là ne serait
// vérifiable nulle part hors CI — c'est-à-dire nulle part depuis un poste sans Chromium.
//
// Trois défauts sont recherchés, et ils sont de nature différente :
//   - **non atteignable** : un élément interactif que la tabulation n'atteint jamais. La
//     souris le touche, le clavier non ; c'est le défaut qui rend une interface inutilisable
//     sans souris, et il est invisible à la lecture du code ;
//   - **sans indicateur** : l'élément prend le focus, mais rien ne change à l'écran. On tape
//     alors dans le vide sans savoir où l'on est ;
//   - **invisible** : l'élément prend le focus alors qu'il n'est pas affiché. Le focus part
//     dans une zone que l'utilisateur ne voit pas, et la tabulation semble « sauter ».
//
// Le quatrième contrôle, les flèches sur un groupe d'onglets, est mesuré à part : il ne
// concerne pas la tabulation mais le motif ARIA « tablist ».

/**
 * Le rapport, en Markdown.
 *
 * @param {{etats?: Array, problemes?: Array, total?: number}} donnees
 * @returns le Markdown, terminé par un saut de ligne.
 */
export function rapportClavier(donnees = {}) {
  const etats = donnees.etats ?? [];
  const horsEtat = donnees.problemes ?? [];
  const lignes = [];
  const dire = (t = "") => lignes.push(t);
  const total = etats.reduce((s, e) => s + (e.problemes?.length ?? 0), 0)
    + horsEtat.length;

  dire("# Audit clavier du studio");
  dire();
  dire("Généré par `web/tests/e2e/audit-clavier.mjs`.");
  dire();
  dire(`**${total} problème(s)** sur ${etats.length} états mesurés `
    + `et ${etats.reduce((s, e) => s + (e.ordre?.length ?? 0), 0)} éléments atteints.`);
  dire();

  // Les défauts qui ne tiennent pas à un état : groupes d'onglets sourds aux flèches.
  if (horsEtat.length > 0) {
    dire("## Défauts hors état");
    dire();
    dire("| type | élément | détail |");
    dire("|---|---|---|");
    for (const p of horsEtat) dire(`| ${p.type} | ${p.quoi} | ${p.detail} |`);
    dire();
  }

  for (const bloc of etats) {
    const p = bloc.problemes ?? [];
    dire(`## ${bloc.etat}`);
    dire();
    dire(`${p.length} problème(s) · ${bloc.ordre?.length ?? 0} élément(s) dans l'ordre de tabulation`);
    dire();
    if (p.length > 0) {
      const parType = {};
      for (const x of p) (parType[x.type] ??= []).push(x);
      for (const [type, liste] of Object.entries(parType)) {
        dire(`### ${type} (${liste.length})`);
        dire();
        dire("| élément | détail |");
        dire("|---|---|");
        for (const x of liste) dire(`| ${x.quoi} | ${x.detail} |`);
        dire();
      }
    } else {
      dire("Aucun problème.");
      dire();
    }
    dire("<details><summary>ordre de tabulation</summary>");
    dire();
    dire("| rang | élément | rôle | nom accessible | indicateur |");
    dire("|---|---|---|---|---|");
    for (const e of bloc.ordre ?? []) {
      dire(`| ${e.rang} | ${e.quoi} | ${e.role} | ${echapper(e.nom || "—")} `
        + `| ${e.indicateur} |`);
    }
    dire();
    dire("</details>");
    dire();
  }

  dire(`TOTAL : ${total} problème(s)`);
  return lignes.join("\n") + "\n";
}

/** Un nom accessible peut contenir un « | », qui casserait le tableau Markdown. */
function echapper(texte) {
  return String(texte).replace(/\|/g, "\\|").slice(0, 60);
}
