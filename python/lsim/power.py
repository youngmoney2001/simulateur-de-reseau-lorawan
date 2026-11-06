"""Puissance d'émission : conventions, conversions et configuration de la passerelle.

Quatre grandeurs sont distinguées ici, parce que le simulateur les confondait dans un
seul scalaire (`ProtocolOptions.gateway_tx_power_dbm`) :

1. **puissance du terminal** — `group.tx_power_dbm` (scénario) : puissance **conduite en
   sortie d'émetteur**, exprimée dans la base du plan régional
   (`RegionProfile.power_basis` : ``"eirp"``, ``"conducted"`` ou ``None``) ;
2. **puissance de la passerelle** — `gateway.tx_power_dbm` (scénario), à défaut
   `ProtocolOptions.gateway_tx_power_dbm` : puissance **conduite en sortie d'émetteur** ;
3. **gain d'antenne et perte de câble** — `rf` (frontal v4) ou `antenna_gain_dbi` :
   l'antenne est **réciproque**, la chaîne `gain − perte` est comptée **une seule fois** ;
4. **PIRE (EIRP)** et **PAR (ERP)** — grandeurs **réglementaires**, reliées par
   ``ERP = EIRP − 2,15 dB`` (antenne demi-onde ; `lsim.regions.ANTENNA_GAIN_DBI_TO_DBD`).

Convention du moteur (vérifiée dans `core/src/engine.cpp`, boucle fermée, et dans
`core/src/downlink_plan.cpp`) : les puissances `tx_power_dbm` sont **conduites en sortie
d'émetteur**, avant le câble et l'antenne de l'émetteur. Le bilan s'écrit donc

    RSSI montant  = P_terminal + (G_terminal − L_terminal) + (G_pass − L_pass) − affaiblissement
    RSSI descendant = RSSI montant − [P_terminal + (G_terminal − L_terminal)]
                      + P_pass + (G_terminal − L_terminal)
                    = P_pass + (G_pass − L_pass) + (G_terminal − L_terminal) − affaiblissement

Le gain d'antenne de la passerelle **s'annule** : il apparaît des deux côtés par
réciprocité. Il n'entre donc pas dans la formule du descendant, mais il entre bien dans
la PIRE, donc dans la sous-bande réglementaire : c'est tout l'enjeu de la séparation
ci-dessus.

Ce module ne change aucune valeur par défaut : `GATEWAY_TX_POWER_DEFAULT_DBM` reprend le
14,0 dBm historique pour ne modifier aucun scénario existant. Le plafond
`GATEWAY_TX_POWER_MAX_DBM` (27,0 dBm) est **publié** par les fiches constructeur du
catalogue (`lsim.gateway_profiles`), il n'est pas un défaut.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # évite un cycle d'import à l'exécution
    from .regions import RegionProfile

# ----------------------------------------------------------------- conversions

EIRP_MINUS_ERP_DB = 2.15  # ERP = EIRP − 2,15 dB (demi-onde) ; identique à
#                            `lsim.regions.ANTENNA_GAIN_DBI_TO_DBD`.


def dbm_to_mw(dbm: float) -> float:
    """Puissance en milliwatts depuis des dBm."""
    return 10.0 ** (float(dbm) / 10.0)


def mw_to_dbm(mw: float) -> float:
    """Puissance en dBm depuis des milliwatts (doit être strictement positive)."""
    if not (isinstance(mw, (int, float)) and not isinstance(mw, bool)) or float(mw) <= 0.0:
        raise ValueError("mw_to_dbm : la puissance doit être strictement positive")
    return 10.0 * math.log10(float(mw))


def erp_from_eirp(eirp_dbm: float) -> float:
    """PAR (ERP) depuis la PIRE (EIRP) : retrait de 2,15 dB."""
    return float(eirp_dbm) - EIRP_MINUS_ERP_DB


def eirp_from_erp(erp_dbm: float) -> float:
    """PIRE (EIRP) depuis la PAR (ERP) : ajout de 2,15 dB."""
    return float(erp_dbm) + EIRP_MINUS_ERP_DB


# ------------------------------------------------- configuration de la passerelle

#: Puissance conduite par défaut de la passerelle (dBm). **Inchangée** : c'est la valeur
#: historique de `ProtocolOptions.gateway_tx_power_dbm`. Elle est conservée pour ne
#: modifier aucun scénario existant ; elle ne correspond à aucune fiche constructeur.
GATEWAY_TX_POWER_DEFAULT_DBM = 14.0

#: Plafond de puissance conduite (dBm) retenu pour la validation des scénarios. Source :
#: fiches du catalogue `lsim.gateway_profiles` — RAK7249 « Tx max 27 dBm », RAK5146
#: « Tx jusqu'à 27 dBm », SX1303 « The power of the TX channel is 27 dBm ». C'est un
#: **plafond publié**, pas une valeur par défaut : aucun scénario n'en hérite.
GATEWAY_TX_POWER_MAX_DBM = 27.0

#: Borne basse de validation, reprise de `lsim.api_contract.ProtocolOptionsIn`.
GATEWAY_TX_POWER_MIN_DBM = -10.0


# --------------------------------------------------------------------- chaîne RF

@dataclass(frozen=True)
class TxChain:
    """Chaîne d'émission complète : puissance conduite, gain d'antenne, perte de câble.

    `conducted_dbm` est la puissance **en sortie d'émetteur**, avant câble et antenne :
    c'est la grandeur que le moteur attend (`radio.tx_power_dbm`,
    `options.gateway_tx_power_dbm`). Les grandeurs réglementaires en dérivent.
    """

    conducted_dbm: float
    antenna_gain_dbi: float = 0.0
    cable_loss_db: float = 0.0

    def __post_init__(self) -> None:
        for nom in ("conducted_dbm", "antenna_gain_dbi", "cable_loss_db"):
            v = getattr(self, nom)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                raise ValueError(f"{nom} doit être un nombre fini")
        if self.cable_loss_db < 0.0:
            raise ValueError("cable_loss_db doit être positif ou nul")

    @property
    def chain_db(self) -> float:
        """Chaîne `gain − perte`, appliquée une seule fois (antenne réciproque)."""
        return float(self.antenna_gain_dbi) - float(self.cable_loss_db)

    @property
    def eirp_dbm(self) -> float:
        """PIRE (EIRP) : puissance conduite + gain d'antenne − perte de câble."""
        return float(self.conducted_dbm) + self.chain_db

    @property
    def erp_dbm(self) -> float:
        """PAR (ERP) : PIRE moins 2,15 dB. C'est la grandeur des tableaux ETSI."""
        return erp_from_eirp(self.eirp_dbm)

    @property
    def eirp_mw(self) -> float:
        """PIRE en milliwatts."""
        return dbm_to_mw(self.eirp_dbm)

    @property
    def erp_mw(self) -> float:
        """PAR en milliwatts."""
        return dbm_to_mw(self.erp_dbm)

    @classmethod
    def from_eirp(cls, eirp_dbm: float, antenna_gain_dbi: float = 0.0,
                  cable_loss_db: float = 0.0) -> "TxChain":
        """Chaîne dont la PIRE vaut `eirp_dbm` : puissance conduite déduite."""
        return cls(float(eirp_dbm) - antenna_gain_dbi + cable_loss_db,
                   antenna_gain_dbi, cable_loss_db)

    @classmethod
    def from_erp(cls, erp_dbm: float, antenna_gain_dbi: float = 0.0,
                 cable_loss_db: float = 0.0) -> "TxChain":
        """Chaîne dont la PAR vaut `erp_dbm` : puissance conduite déduite."""
        return cls.from_eirp(eirp_from_erp(erp_dbm), antenna_gain_dbi, cable_loss_db)


def gateway_tx(gateway, fallback_dbm: float = GATEWAY_TX_POWER_DEFAULT_DBM) -> TxChain:
    """Chaîne d'émission d'une passerelle (modèle de scénario ou objet d'exécution).

    `gateway.tx_power_dbm` (`None` si absent) est la puissance conduite propre à la
    passerelle ; à défaut, `fallback_dbm` est appliqué — par défaut
    `GATEWAY_TX_POWER_DEFAULT_DBM`, c'est-à-dire la valeur historique de
    `ProtocolOptions.gateway_tx_power_dbm`. Le gain vient du frontal `rf` s'il est
    renseigné, sinon du scalaire `antenna_gain_dbi` (sémantique de `apply_gateway_rf`,
    `core/src/c_api_ext.cpp`).

    Fonctionne aussi bien avec `lsim.scenario.GatewayModel` qu'avec
    `lsim.simulator.Gateway` : les champs sont lus par attribut.
    """
    conduit = getattr(gateway, "tx_power_dbm", None)
    if conduit is None:
        conduit = float(fallback_dbm)
    gain = float(getattr(gateway, "antenna_gain_dbi", 0.0) or 0.0)
    perte = 0.0
    rf = getattr(gateway, "rf", None)
    if rf is not None:
        g = getattr(rf, "antenna_gain_dbi", None)
        if g is not None:
            gain = float(g)
        p = getattr(rf, "cable_loss_db", None)
        if p is not None:
            perte = float(p)
    return TxChain(float(conduit), gain, perte)


def device_tx(group) -> TxChain:
    """Chaîne d'émission d'un groupe de terminaux (modèle de scénario).

    `group.tx_power_dbm` est interprété comme la puissance **conduite en sortie
    d'émetteur**, comme le fait le moteur (`tx_dbm(device, power_index)` +
    `rf.chain_db()`). La PIRE du groupe en découle.
    """
    gain, perte = 0.0, 0.0
    rf = getattr(group, "rf", None)
    if rf is not None:
        g = getattr(rf, "antenna_gain_dbi", None)
        if g is not None:
            gain = float(g)
        p = getattr(rf, "cable_loss_db", None)
        if p is not None:
            perte = float(p)
    return TxChain(float(group.tx_power_dbm), gain, perte)


# ------------------------------------------------- limite réglementaire dérivée

def applicable_bands(profile: "RegionProfile", freq_hz: int, tx: TxChain):
    """Sous-bandes du profil applicables à une émission `tx` sur `freq_hz`.

    Le tri se fait sur la **PAR** (`SubBand.max_erp_dbm`) : les tableaux ETSI sont
    exprimés en PAR, d'où la conversion `erp_from_eirp`.
    """
    return profile.applicable(freq_hz, tx.erp_dbm)


def duty_cycle_limit(profile: "RegionProfile", freq_hz: int, tx: TxChain) -> Optional[float]:
    """Duty cycle maximal d'une émission `tx` sur `freq_hz`, ou `None` (profil sans bandes).

    C'est le point de passage unique entre la chaîne d'émission et la contrainte
    réglementaire : la PIRE de la chaîne est convertie en **PAR** avant la sélection de
    la sous-bande. Lève `ValueError` si l'émission est hors plan.
    """
    if not profile.sub_bands:
        return None
    return profile.duty_cycle_for(freq_hz, tx.eirp_dbm)
