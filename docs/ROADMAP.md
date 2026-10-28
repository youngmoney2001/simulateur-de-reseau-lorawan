# Feuille de route

Légende : ✅ fait · 🔧 en cours · ⬜ planifié

## Jalon 0 — Fondations (en cours)
- ✅ Dépôt, licence Apache-2.0, CI (C++ et Python)
- ✅ Cœur C++17 : temps d'antenne LoRa exact (entier nanosecondes, AN1200.13)
- ✅ Validation des entrées, statuts explicites, aucune exception traversant la frontière C
- ✅ API C stable + binding Python `ctypes` (aucun code de calcul en Python)
- ✅ Tests : valeurs de référence + différence avec une implémentation indépendante (1 008 cas)
- ⬜ Sensibilité par SF/BW (datasheet SX1276) et marge de liaison

## Jalon 1 — Couche radio et propagation
- ⬜ Modèles de propagation (log-distance, obstacles, masques de terrain)
- ⬜ Collisions et capture effect, orthogonalité inter-SF
- ⬜ Profils régionaux data-driven : EU868, US915, AS923, AU915, KR920, IN865, RU864
- ⬜ Duty cycle et temps d'attente réglementaires

## Jalon 2 — MAC LoRaWAN 1.1
- ⬜ Classes A, B, C
- ⬜ Dérivation de clés 1.1 (NwkSKey, AppSKey, JSEncKey, JSIntKey) et join OTAA
- ⬜ ADR, ACK, commandes MAC, rekey
- ⬜ Moteur d'événements discrets (file de priorité déterministe)

## Jalon 3 — Scénarios, résultats et analyse
- ⬜ Scénarios YAML validés (Pydantic)
- ⬜ Export Parquet, métriques (PDR, énergie, charge gateway)
- ⬜ Notebooks pour les bureaux d'études

## Jalon 4 — Visualisation 3D et produit
- ⬜ Carte 3D CesiumJS (Apache-2.0) : nœuds, gateways, zones de couverture
- ⬜ Rapports PDF/Excel, gestion multi-utilisateurs
- ⬜ Empaquetage, documentation, cycle de release
