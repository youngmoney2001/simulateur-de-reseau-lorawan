// Rapport de l'audit de mise en page, en Markdown.
//
// Module séparé du script d'audit, et c'est la raison d'être du fichier : `audit.mjs` lève
// « CHROME_PATH requis » dès son import, faute de navigateur. Une fonction enfouie là ne
// serait vérifiable nulle part hors CI — donc vérifiable nulle part du tout depuis un poste
// sans Chromium, ce qui est le cas ici.
//
// Longtemps, ce rapport n'a vécu que dans le journal du runner, hébergé hors de portée de
// l'outillage. « La CI est verte » ne voulait alors rien dire de plus que « aucune assertion
// n'a échoué », et l'audit est précisément fait pour répondre à des questions qu'aucune
// assertion ne pose. L'écrire dans le dépôt le rend relisible et diffable d'une tranche à
// l'autre.

/**
 * Le rapport, en Markdown.
 *
 * @param rapport blocs tels que `mesurer()` les renvoie, chacun portant `problemes`,
 *                `geometrie`, `scrollHorizontal`, et soit `etat` soit `largeur`.
 * @returns le Markdown, terminé par un saut de ligne.
 */
export function rapportMarkdown(rapport = []) {
  const lignes = [];
  const dire = (t = "") => lignes.push(t);
  const total = rapport.reduce((s, b) => s + (b.problemes?.length ?? 0), 0);

  dire("# Audit de mise en page");
  dire();
  dire("Généré par `web/tests/e2e/audit.mjs`.");
  dire();
  dire(`**${total} problème(s)** sur ${rapport.length} états mesurés.`);
  dire();

  for (const bloc of rapport ?? []) {
    const p = bloc.problemes ?? [];
    const titre = bloc.etat ?? `${bloc.largeur}px`;
    if (bloc.introuvable) {
      dire(`## ${titre} — état non atteint`);
      dire();
      continue;
    }
    dire(`## ${titre}`);
    dire();
    dire(`${p.length} problème(s) · défilement horizontal : ${bloc.scrollHorizontal ? "oui" : "non"}`);
    dire();
    if (p.length === 0) {
      dire("Aucun problème.");
      dire();
    } else {
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
    }
    dire("<details><summary>géométrie</summary>");
    dire();
    dire("| élément | x | y | largeur × hauteur |");
    dire("|---|---|---|---|");
    for (const g of bloc.geometrie ?? []) dire(`| ${g.quoi} | ${g.x} | ${g.y} | ${g.l}×${g.h} |`);
    dire();
    dire("</details>");
    dire();
  }
  dire(`TOTAL : ${total} problème(s)`);
  return lignes.join("\n") + "\n";
}
