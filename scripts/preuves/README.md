# Preuves reproductibles

Scripts de vérification des résultats d'audit. **Aucun n'écrit dans le dépôt** : les fichiers
temporaires vont dans `mktemp -d` et sont supprimés à la sortie.

Interpréteur conseillé pour les scripts Python : celui du projet
(`/home/user/.venv-lsim/bin/python`, à défaut `python3` avec les dépendances installées).
Les scripts qui chargent le cœur natif exigent `LSIM_LIBRARY` (chemin de `liblsim_core.so`).

| Script | Objet | Attendu au commit `68176d6` |
|---|---|---|
| `verifier_abi_layout.sh` | Compile et exécute le harnais de dispositions ABI en x86-64 ; compile en i386 | `structures vérifiées : 53, grandeurs : 454` ; i386 : objet produit (aucune exécution) |
| `verifier_symboles.sh LIB [REF]` | Liste triée des symboles `lsim_*` et comparaison à une référence | **95** symboles, SHA-256 `e8b97058ca45d79bb902c69aeac666e6eaa3a4d25e3bfa1a9ff99e115494e234` |
| `verifier_empreintes.sh` | Rejoue `scripts/mac_baseline_dump.py` et compare aux empreintes gelées | `d2cb0fac6c2d9950…` / `ed126d7ff5aac3b0…` |
| `verifier_assertions_lp64.py` | Tableau des 14 assertions ABI en littéraux, verdict par ABI | 14 assertions, **0** échec x86-64, **11** échecs i386 |
| `sonde_d0.py` | Effet de `reference_distance_m` avec et sans relief (F6 / M2) | sans relief : identique ; avec relief : différent |
| `balayage_graines.py [--seeds N]` | Échecs de convergence du chemin de trace (F1) | 240 runs pour 40 graines × 3 exemples × 2 options, **0** échec — F1 reste **non reproduit** |
| `verifier_sauvegarde.sh TAR [BUNDLE]` | Empreinte, extraction, arbre, commit, clone d'une sauvegarde | arbre identique, commit `68176d6`, 332 fichiers, 0 modifié |

### `verifier_sauvegarde.sh` — ce que le script contrôle, et dans quel ordre

Le script enchaîne cinq contrôles, du plus fort au plus faible :

| Étape | Statut | Effet sur le code retour |
|---|---|---|
| empreinte (`sha256sum -c`) | **bloquant** | échec ⇒ code non nul |
| extraction (`tar xzf`) | **bloquant** | échec ⇒ code non nul |
| arbre de travail (hors `.git`, `__pycache__`, `.pytest_cache`, `build`) | **bloquant** | divergence ⇒ code non nul |
| commit (`HEAD` de l'archive = `HEAD` du dépôt) | **bloquant** | différence ⇒ code non nul |
| références distantes (`.git/refs/remotes`) | **informatif** | n'influence jamais le code retour |

**Précondition de l'attendu « arbre identique ».** Ce résultat n'est attendu que si l'arbre
comparé est **au même état de contenu que l'archive**. Une archive antérieure à la Phase A
comparée à l'arbre documentaire modifié pendant cette phase **doit** présenter des différences ;
cela ne constitue pas, à lui seul, une anomalie du script. Pour comparer une archive historique,
pointer le contrôle sur un arbre au même commit : `PREUVES_ROOT=/chemin/vers/clone`. Ce même
paramètre permet aussi de vérifier un arbre de référence sans toucher au dépôt courant.

**Références Git.** Une différence dans `.git/refs/remotes` est signalée mais **ne fait jamais
échouer** le script : une archive prise avant un push, ou un clone frais, présente légitimement
une référence distante différente sans que le contenu soit en cause.

## Exemples

```bash
# contrôles ne nécessitant pas de compilation
python3 scripts/preuves/verifier_assertions_lp64.py
bash   scripts/preuves/verifier_abi_layout.sh

# contrôles nécessitant le cœur compilé
bash   scripts/preuves/verifier_symboles.sh build/liblsim_core.so
LSIM_LIBRARY=build/liblsim_core.so bash scripts/preuves/verifier_empreintes.sh
LSIM_LIBRARY=build/liblsim_core.so python3 scripts/preuves/sonde_d0.py
LSIM_LIBRARY=build/liblsim_core.so python3 scripts/preuves/balayage_graines.py --seeds 40

# sauvegarde
bash scripts/preuves/verifier_sauvegarde.sh /home/user/sauvegardes/<archive>.tar.gz
```

## Ce que ces scripts ne prouvent pas

- `verifier_abi_layout.sh` **n'exécute rien en i386** : l'environnement n'a ni CRT, ni libc, ni
  libstdc++ 32 bits. Les dispositions i386 sont vérifiées à la compilation, pas le moteur.
- `balayage_graines.py` documente une **absence de reproduction** de F1, jamais une absence de
  défaut : la paramétrisation du balayage d'origine n'est pas connue.
- `sonde_d0.py` constate un comportement ; il ne dit pas quel modèle est correct — cette décision
  appartient à la phase F.
