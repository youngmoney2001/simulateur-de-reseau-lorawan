# Archive D3.15 — jeu historique avant recalibrage

- **Date d'archivage** : 2026-11-06
- **Commit de reference** : `72fc6cb925d3f65bb5a3ee2848066fc2f70e9a57` (`72fc6cb`)
- **Branche** : `arena/fdc94521-simulateur-de-reseau-lorawan`
- **Nature** : **copie integrale**. Aucun fichier d'origine n'a ete supprime, deplace ni modifie.

## Motif

Le jeu de reference D3.15 emploie des charges que les fenetres descendantes ne peuvent
pas porter : N vaut au plus 222 dans les sept regions, et au plus 51 pour les fenetres
RX2. Les scenes historiques utilisent 20, 60, 120 et 240 octets. Les conclusions qui en
decoulent sont donc, pour partie, invalides ou non demontrees (voir `d315-STATUT.md`).

## Contenu

| Fichier | Lignes | SHA-256 |
|---|---|---|
| `python/tests/test_d315_global.py` | 1033 | `0746df132bb43a1d…` |
| `python/tests/test_d315_causal_envelope.py` | 541 | `38b5f410f78ec237…` |
| `scripts/preuves/b_d315_charge.py` | 97 | `f389abdeb632b4ef…` |
| `scripts/preuves/b_d315_effet_correctifs.py` | 142 | `0da21c7e3d9e4318…` |

> **Banniere.** Jeu historique — archive le 2026-11-06. Certaines conclusions reposent sur des
> charges non conformes a N. Voir `d315-STATUT.md`.
