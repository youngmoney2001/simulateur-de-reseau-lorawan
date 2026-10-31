# Journal de recherche — `R2B_CLOTURE_AUDIT_ANOMALIES.md`

**Objet** : retrouver le fichier `R2B_CLOTURE_AUDIT_ANOMALIES.md` (704 lignes, SHA-256
`1d2f5ad06e0f042630796325426643704cf670b5810ef125a0af907c272cc03e`).
**Date** : 2026-10-31 · **Résultat** : **non trouvé**.
**Aucune reconstruction** n'a été faite : ce journal ne consigne que des recherches.

---

## 1. Référence de l'objet recherché

Source unique de la métadonnée : `R2B_PHASE1_INCIDENT_ESPACE_TRAVAIL.md`, §2.2, ligne 166.

```
| `R2B_CLOTURE_AUDIT_ANOMALIES.md` (704 l.) | `1d2f5ad06e0f042630796325426643704cf670b5810ef125a0af907c272cc03e` |
```

Aucun extrait, aucun résumé, aucune citation de ce document n'existe ailleurs : la recherche
`grep -rn "704\|extrait\|résumé de l'audit"` sur les deux rapports d'incident ne renvoie que cette
ligne d'inventaire.

---

## 2. Dépôts Git

### 2.1 `recovery` — recherche par nom dans toutes les refs

```bash
git -C /home/user/recovery log --all --oneline -- '*CLOTURE*' '*AUDIT*'
git -C /home/user/recovery rev-list --objects --all | grep -i "cloture\|audit"
```
**Sortie : vide.** (`--all` couvre les branches locales, `refs/remotes/origin/…` et les tags.)

### 2.2 `recovery` — recherche par contenu dans tous les blobs

```bash
git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype) %(objectsize)' \
  | awk '$2=="blob" && $3>10000 && $3<200000 {print $1}' | wc -l
# → 694
# puis, pour chaque blob :
git cat-file blob "$o" | grep -aq "CLOTURE_AUDIT\|R2B_CLOTURE"
```
**Sortie : aucune occurrence** sur 694 blobs (plage 10–200 Ko, qui couvre 704 lignes de texte).
`--batch-all-objects` inclut les objets **inaccessibles** : un blob orphelin aurait été vu.

### 2.3 Dépôt principal `/home/user/simulateur-de-reseau-lorawan`

Mêmes deux commandes.
**Sortie : vide.** Aucun objet, aucun blob ne contient le titre.

### 2.4 Les 9 bundles

```bash
for b in /home/user/sauvegardes/*.bundle; do git bundle list-heads "$b"; done
```
**Sortie** : uniquement des commits déjà connus — `68176d6`, `c77f8eb`, `2202782`, `9686c25`,
`c46d531`, `1f43370` (et deux refs distantes anciennes `d67ca5ff`, `e2b61318`). **Aucun commit
inconnu** susceptible de porter le document.

---

## 3. Archives tar

```bash
for f in /home/user/sauvegardes/*.tar.gz; do
  d=/tmp/search_tars/$(basename "$f" .tar.gz); mkdir -p "$d"; tar xzf "$f" -C "$d"; done
find /tmp/search_tars -type f -not -path '*/.git/*' | wc -l          # → 4035
find /tmp/search_tars -type f -not -path '*/.git/*' -print0 \
  | xargs -0 sha256sum | grep "1d2f5ad0"                             # → vide
find /tmp/search_tars -iname '*anomal*' -o -iname '*cloture*' -o -iname '*audit*'   # → vide
```
**Sortie : 4 035 fichiers hachés, aucune correspondance ; aucun nom approchant.**
Recherche complémentaire par longueur (650–760 lignes) sur tous les `.md` : un seul fichier,
`mbedtls-src/docs/architecture/psa-shared-memory.md` (685 l.), sans rapport.

---

## 4. Système de fichiers

| Commande | Volume | Sortie |
|---|---|---|
| `find /home/user -type f` (hors `.git`, `.venv*`, `node_modules`, `.cache`, `.local`) + `sha256sum` | **3 293 fichiers** | aucune correspondance |
| `find … \( -name '*.md' -o -name '*.txt' \)` + `sha256sum` | **184 fichiers** | aucune correspondance |
| `grep -rl "1d2f5ad0\|CLOTURE_AUDIT" /home/user/.cache /home/user/.local` | répertoires cachés | vide (`.arena` inexistant) |
| `find /tmp … + sha256sum` (hors builds, `mbedtls`, `node_modules`) | tous les répertoires de travail | aucune correspondance |
| `find / -xdev -iname '*cloture*'` (hors `/usr`, `/var/lib`, `recovery-build`) | tout le système | aucun fichier |
| `grep -rl "1d2f5ad0" /home /tmp /opt /srv` | — | **4 fichiers** : l'inventaire d'incident + mes 3 rapports d'audit |

---

## 5. Artefacts de session

| Emplacement | Nature | Résultat |
|---|---|---|
| `/tmp/arena-workspace/coding.patch` | 1 013 602 o, diff de session | 0 occurrence du titre ou de l'empreinte ; ne touche que des chemins `a/…` du dépôt |
| `/tmp/arena-workspace/coding.diff` | identique au patch | idem |
| `/tmp/arena-workspace/coding-numstat.txt` | 3 293 o | idem |
| `/tmp/arena-coding-uploads/` | 28 PDF (spécifications LoRaWAN, SX126x, RAK) + 1 PNG | aucun rapport |

---

## 6. Conclusion

1. Le document **n'existe plus** dans aucun espace accessible : ni dépôt, ni historique Git, ni
   bundle, ni archive, ni répertoire temporaire, ni artefact de session.
2. Il n'a **pas** été reconstruit. Toute reconstitution serait une hypothèse, pas une preuve : la
   consigne d'origine est respectée.
3. **Conséquence sur l'audit** : M1 et M4 restent **non identifiables**.
   Pour **M2**, seule l'invariance `d0` sans relief est **observée** dans le périmètre de la sonde
   rejouée ; elle ne suffit pas à établir l'anomalie globale.
   Pour **M3**, le refus d'une configuration RF partielle est **observé** dans le chemin v4, sans
   démontrer le comportement correspondant dans le chemin mesh.
   Les écarts F6 associés restent **non reproduits**.
4. **Seule voie de récupération** : un exports de la session antérieure ou une copie détenue hors
   de cet espace. Si le fichier est fourni, la **première** action sera `sha256sum` comparé à
   `1d2f5ad0…` ; en cas d'écart, il sera signalé et **non utilisé**.
