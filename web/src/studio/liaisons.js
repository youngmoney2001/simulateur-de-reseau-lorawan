// Liaisons observées d'un run : qui a réellement parlé à qui.
//
// Ce module est volontairement étroit, et l'étroitesse est le sujet.
//
// Une liaison n'est dessinée que si le run l'a **observée** :
//   - « mesh » : un relais a livré des trames à une frontière (`mesh_inbound` du résumé).
//
// Les liaisons radio « capteur → passerelle » ne sont **pas** tracées, et c'est une décision
// mesurée, pas un report. Un événement de trace porte `gateway_index = best_gateway` : la
// meilleure passerelle de la trame, une seule, alors que plusieurs peuvent l'avoir décodée.
// Vérifié sur un run à deux passerelles et six capteurs : les événements attribuent chaque
// trame à une seule passerelle, quand les compteurs montrent que **les deux** ont reçu les
// vingt-quatre. Tracer d'après les événements dessinerait « ce capteur n'est entendu que par
// gw-nord », ce qui est faux — et qui masque la macro-diversité, une propriété que LoRaWAN
// cultive précisément. La matrice par couple (capteur, passerelle) n'existe pas dans l'API :
// on ne peut donc pas tracer juste, et tracer faux serait pire que ne pas tracer.
//
// Dès qu'une liaison est tracée, elle porte son chiffre : un trait sans nombre n'apprend rien
// qu'une couleur ne dirait déjà.

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
      out.push({ de, vers, livrees: entrant.delivered });
    }
  }
  // Ordre décroissant : sur un plan chargé, les liaisons qui comptent se voient d'abord.
  return out.sort((a, b) => b.livrees - a.livrees || (a.de < b.de ? -1 : 1));
}

/** Une seule ligne par couple : le run peut compter plusieurs sens, la carte n'en montre qu'un. */
export function cumulerLiaisons(liaisons = []) {
  const parCouple = new Map();
  for (const l of liaisons) {
    // Le couple est orienté : relais -> frontière. On ne fusionne pas l'aller et le retour.
    const cle = `${l.de}\u0000${l.vers}`;
    const avant = parCouple.get(cle);
    if (avant) avant.livrees += l.livrees;
    else parCouple.set(cle, { ...l });
  }
  return [...parCouple.values()].sort((a, b) => b.livrees - a.livrees || (a.de < b.de ? -1 : 1));
}

/**
 * Ce qu'on écrit sur le trait. Un chiffre seul ne dit pas ce qu'il compte : « 12 » pourrait
 * être des trames, des sauts ou des décibels.
 */
export function etiquetteLiaison(liaison) {
  const n = liaison?.livrees ?? 0;
  return n >= 2 ? `${n} trames relayées` : "1 trame relayée";
}
