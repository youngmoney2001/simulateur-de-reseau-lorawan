// Liaisons observées d'un run : qui a réellement parlé à qui.
//
// Ce module est volontairement étroit, et l'étroitesse est le sujet.
//
// Une liaison n'est dessinée que si le run l'a **observée** :
//   - « mesh »  : un relais a livré des trames à une frontière (`mesh_inbound` du résumé) ;
//   - « radio » : une passerelle a décodé des trames d'un capteur (`rx_matrix` du résumé).
//
// Les liaisons radio ont longtemps été écartées, et pour une raison mesurée : un événement de
// trace porte `gateway_index = best_gateway`, la **meilleure** passerelle de la trame, une
// seule, alors que plusieurs peuvent l'avoir décodée. Vérifié sur un run à trois passerelles :
// les événements attribuent chaque trame à `gw-ouest` quand trois passerelles les ont toutes
// décodées. Tracer d'après les événements dessinerait « ce capteur n'est entendu que par
// gw-ouest », ce qui est faux — et masque la macro-diversité, une propriété que LoRaWAN
// cultive précisément.
//
// Ce qui manquait n'était pas une précaution, c'était la donnée. Le moteur calcule
// `decoded_mask` (bit g : la passerelle g a décodé) ; il n'était pas exposé. L'API publie
// désormais `rx_matrix`, et la liaison radio se trace — vérifiée contre `audible_frames`,
// compteur indépendant.
//
// Dès qu'une liaison est tracée, elle porte son chiffre : un trait sans nombre n'apprend rien
// qu'une couleur ne dirait déjà.

import { metresVersDegres as toLonLat } from "./geo.js";

/**
 * Liaisons mesh observées, en identifiants d'équipements de la session.
 *
 * @param passerelles `summary.gateways` : chaque entrée porte `name` et, sur un run mesh,
 *                    `mesh_inbound` = [{ from_gateway, delivered }].
 * @param liens       `GatewayLink[]` du run : { node_id, gateway }. Traduit le nom de passerelle
 *                    du run en identifiant d'équipement de la session, seul repère de la carte.
 * @param noeuds      identifiants connus de la session. Une liaison dont un bout est inconnu
 *                    n'est pas dessinée : on ne pose pas un trait dans le vide.
 * @returns [{ de, vers, livrees }], les mieux fournies d'abord.
 */
export function liaisonsMesh({ passerelles = [], liens = [], noeuds = null } = {}) {
  const connus = noeuds === null ? null : new Set(noeuds);
  // Le run nomme ses passerelles ; la session nomme ses équipements. Les deux se
  // correspondent par `GatewayLink`, et le nom du run reste un repli honnête quand la
  // liaison n'a pas été déclarée (run lancé hors session).
  const parNomDuRun = new Map(liens.map((l) => [l.gateway, l.node_id]));
  const versSession = (nom) => parNomDuRun.get(nom) ?? nom;

  const out = [];
  for (const g of passerelles) {
    const vers = versSession(g?.name);
    for (const entrant of g?.mesh_inbound ?? []) {
      // Un lien qui n'a rien livré n'a pas été observé : le dessiner promettrait une
      // liaison que le run n'a pas vue.
      if (!(entrant?.delivered >= 1)) continue;
      const de = versSession(entrant.from_gateway);
      if (de === vers) continue;                        // un équipement ne se relaie pas lui-même
      if (connus && (!connus.has(de) || !connus.has(vers))) continue;
      out.push({ de, vers, genre: "mesh", compte: entrant.delivered });
    }
  }
  // Ordre décroissant : sur un plan chargé, les liaisons qui comptent se voient d'abord.
  return out.sort((a, b) => b.compte - a.compte || (a.de < b.de ? -1 : 1));
}

/**
 * Liaisons radio observées : une passerelle qui a **décodé** des trames d'un capteur.
 *
 * `rx_matrix[d][g]` compte les trames décodées par la passerelle `g` pour le dispositif `d`.
 * Deux correspondances à faire, et elles ne sont pas interchangeables :
 *   - les colonnes suivent l'ordre de `summary.gateways`, pas un ordre alphabétique ;
 *   - les dispositifs suivent `device_index`, et le nom du groupe est l'identifiant du
 *     capteur (`study_compile.py` nomme un groupe par capteur, un dispositif chacun).
 *
 * Le masque dit « a décodé », pas « a entendu » : c'est la granularité à laquelle une liaison
 * radio est significative. Une trame décodée par trois passerelles compte trois liaisons.
 *
 * @returns [{ de, vers, genre, compte }], les mieux fournies d'abord.
 */
export function liaisonsRadio({ rxMatrix = null, gateways = [], deviceRows = [], liens = [],
                                noeuds = null } = {}) {
  if (!Array.isArray(rxMatrix) || rxMatrix.length === 0) return [];
  const connus = noeuds === null ? null : new Set(noeuds);
  const parNomDuRun = new Map(liens.map((l) => [l.gateway, l.node_id]));
  const versSession = (nom) => parNomDuRun.get(nom) ?? nom;
  // Colonnes dans l'ordre de `gateways` : c'est celui que le serveur garantit, et c'est le
  // seul. Reconstruire cet ordre depuis les noms le perdrait.
  const colonnes = gateways.map((g) => versSession(g?.name));

  const out = [];
  for (let d = 0; d < rxMatrix.length; d += 1) {
    const ligne = rxMatrix[d];
    if (!Array.isArray(ligne)) continue;
    // Au-delà de `MAX_METRIC_DEVICES`, les lignes par dispositif ne sont pas rapatriées : la
    // matrice peut alors compter plus de lignes que `deviceRows`. Un dispositif qu'on ne sait
    // pas nommer ne se trace pas — on préfère un trait absent à un trait posé au hasard.
    const de = deviceRows[d]?.group ?? null;
    if (!de) continue;
    for (let g = 0; g < ligne.length && g < colonnes.length; g += 1) {
      const compte = ligne[g];
      // Rien décodé, rien observé : le dessiner promettrait une portée que le run n'a pas vue.
      if (!(compte >= 1)) continue;
      const vers = colonnes[g];
      if (!vers || de === vers) continue;
      if (connus && (!connus.has(de) || !connus.has(vers))) continue;
      out.push({ de, vers, genre: "radio", compte });
    }
  }
  return out.sort((a, b) => b.compte - a.compte || (a.de < b.de ? -1 : 1));
}

/** Une seule ligne par couple : le run peut compter plusieurs sens, la carte n'en montre qu'un. */
export function cumulerLiaisons(liaisons = []) {
  const parCouple = new Map();
  for (const l of liaisons) {
    // Le couple est orienté : relais -> frontière. On ne fusionne pas l'aller et le retour.
    // Le genre entre dans la clé : un relais peut être capteur sur une autre session, et deux
    // liaisons de nature différente ne s'additionnent pas — « 3 relayées + 5 décodées » n'est
    // un total de rien.
    const cle = `${l.genre}\u0000${l.de}\u0000${l.vers}`;
    const avant = parCouple.get(cle);
    if (avant) avant.compte += l.compte;
    else parCouple.set(cle, { ...l });
  }
  return [...parCouple.values()].sort((a, b) => b.compte - a.compte || (a.de < b.de ? -1 : 1));
}

/**
 * Les liaisons observées d'un run, toutes natures confondues, prêtes à tracer.
 *
 * Fonction pure, sans accès à `state` : c'est ce qui permet de la vérifier hors navigateur.
 * Le calcul complet — les deux natures, leur cumul, leur ordre — se teste donc sans Chromium,
 * et seule l'affectation des cinq entrées reste du ressort de la vue.
 *
 * @returns [{ de, vers, genre, compte }], les mieux fournies d'abord.
 */
export function liaisonsObservees({ passerelles = [], liens = [], noeuds = null,
                                    rxMatrix = null, deviceRows = [] } = {}) {
  return cumulerLiaisons([
    ...liaisonsMesh({ passerelles, liens, noeuds }),
    ...liaisonsRadio({ rxMatrix, gateways: passerelles, deviceRows, liens, noeuds }),
  ]);
}

/**
 * Bouts géographiques d'une liaison, en degrés, prêts pour la carte 3D.
 *
 * @param noeuds Map id -> { x_m, y_m } (le plan et la carte partagent ces mètres).
 * @returns null quand la liaison n'est pas traçable : bout inconnu, ou position
 *          inexploitable. La carte préfère un trait absent à un trait faux — et à une
 *          erreur anonyme de Cesium qui interromprait le tracé du reste du réseau.
 */
export function boutsLiaison(liaison, noeuds, origine) {
  const a = noeuds?.get(liaison?.de);
  const b = noeuds?.get(liaison?.vers);
  if (!a || !b) return null;
  const de = toLonLat(a.x_m, a.y_m, origine);
  const vers = toLonLat(b.x_m, b.y_m, origine);
  const finis = [de.lat, de.lon, vers.lat, vers.lon].every(Number.isFinite);
  return finis ? { de, vers } : null;
}

/**
 * Ce qu'on écrit sur le trait. Un chiffre seul ne dit pas ce qu'il compte : « 12 » pourrait
 * être des trames, des sauts ou des décibels.
 *
 * Et le verbe doit suivre la nature du lien : une trame décodée n'est pas une trame relayée.
 * Les confondre ferait croire à un relais là où il n'y a qu'une portée.
 */
export function etiquetteLiaison(liaison) {
  const n = liaison?.compte ?? 0;
  if (liaison?.genre === "radio") return n >= 2 ? `${n} trames décodées` : "1 trame décodée";
  return n >= 2 ? `${n} trames relayées` : "1 trame relayée";
}
