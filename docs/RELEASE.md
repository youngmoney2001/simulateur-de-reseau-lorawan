# Politique de version et de release

## Numérotation

Versions `MAJEUR.MINEUR.CORRECTIF` (SemVer). Tant que le majeur vaut 0, un changement
mineur peut casser l'API : il est alors signalé dans `CHANGELOG.md`.

## Où la version est écrite

Les trois endroits doivent porter le même numéro (contrôlé par `python/tests/test_release.py`) :

- `python/pyproject.toml` (`version`) ;
- `python/lsim/__init__.py` (`__version__`) ;
- `web/package.json` (`version`).

## Procédure

1. Mettre à jour `CHANGELOG.md` (section de la version, date).
2. Changer les trois numéros ci-dessus.
3. Lancer les tests : `ctest --test-dir build` (ou `./build/lsim_tests`), `pytest python/tests`,
   `npm test` et `npm run build` dans `web/`.
4. Produire le paquet natif : `scripts/package_native.sh` (archive + SHA-256 dans `dist/`).
5. Étiqueter le commit `vX.Y.Z` et publier l'archive et son empreinte.

## Ce qui n'est pas publié

- `dist/`, `build*/`, `web/dist/` et les jeux de données bruts : hors Git.
- Les paramètres de référence (`python/lsim/reference/`) sont sous CC BY 4.0 : l'attribution
  figure dans `THIRD_PARTY_NOTICES.md` et doit accompagner toute diffusion.
