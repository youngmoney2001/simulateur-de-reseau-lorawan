"""Plan de canaux LoRaWAN pour le serveur (données et jointure), une région par déploiement.

Un `Plan` décrit, pour une région :
- les débits montants (chaîne « SF7BW125 » → indice DR) et descendants (indice DR → chaîne) ;
- les canaux montants par défaut, indexés comme le champ TxCh du MIC 1.1 ;
- la règle RX1 : canal, débit — **fonction de RX1DROffset** ;
- la charge utile maximale par débit (N, sans FOpts, compatible répéteur) ;
- la valeur DLSettings du join-accept (RX2 par défaut).

Les tables de débits et la règle RX1 sont celles de **RP002-1.0.4**, vérifiées région par
région par `tools/verifier_rx1_rp002.py` (0 écart sur les 7 régions). La table RX1 est
**indexée par RX1DROffset** : elle n'est plus réduite à l'offset 0. Voir
`docs/I5_C_RX1_DROFFSET.md` pour la provenance des valeurs et la chaîne de preuve.
"""

from __future__ import annotations

import importlib
import re
from typing import Callable, Mapping, Sequence

_BUILTIN_MODULES = ("lsim.eu868", "lsim.us915", "lsim.au915", "lsim.as923", "lsim.kr920", "lsim.in865", "lsim.ru864")

RECEIVE_DELAY1_US = 1_000_000        # RP002 §2.3 : RECEIVE_DELAY1 = 1 s, toutes régions
_CHANNEL_TOLERANCE_HZ = 1_000        # la passerelle rapporte la fréquence en Hz précis


class UnsupportedUplinkDataRateError(ValueError):
    """Aucun DR montant du plan régional ne correspond au (SF, bande) demandé.

    Levée **avant la simulation**, à la construction de la radio : il n'y a donc ni
    chronologie à défaire ni repli à tenter.

    Aucun DR de substitution n'est inventé, et **aucun repli silencieux vers une modulation
    générique** ne subsiste : c'est précisément le comportement que cette exception remplace.
    Un terminal réglé sur un SF absent de sa région est une erreur de configuration, pas une
    scène lente — la simuler reviendrait à produire une chronologie qui ne correspond à rien.

    `available` porte les SF montants réellement offerts par la région, à seule fin de rendre
    le diagnostic actionnable.
    """

    def __init__(self, region: str, spreading_factor: int, bandwidth_hz: int,
                 available: tuple[int, ...]) -> None:
        self.region = region
        self.spreading_factor = spreading_factor
        self.bandwidth_hz = bandwidth_hz
        self.available = tuple(available)
        super().__init__(
            f"{region} : aucun DR montant pour SF{spreading_factor} "
            f"@{bandwidth_hz // 1000} kHz. "
            f"SF montants disponibles dans cette région : "
            f"{', '.join(f'SF{s}' for s in sorted(self.available))}."
        )


def rx1_clamp_table(uplink_drs: tuple[int, ...], dr_max: int, offsets: int) -> dict[int, tuple[int, ...]]:
    """Table RX1 des régions à règle arithmétique : `RX1_DR = clamp(DR − offset, 0, dr_max)`.

    RP002-1.0.4 : EU868, EU433, RU864, IN865 et AS923 (sans temps de séjour) suivent toutes
    cette règle, avec `dr_max` = 7 ; KR920 la suit avec `dr_max` = 5. Seules US915, AU915 et
    CN470 ont une table explicitement énumérée.

    Les valeurs sont calculées plutôt qu'écrites à la main : c'est la règle qui est normative,
    et une table de 42 nombres recopiés serait une occasion d'erreur sans gain de lisibilité.
    """
    return {dr: tuple(max(0, min(dr - o, dr_max)) for o in range(offsets))
            for dr in uplink_drs}


class Rx1DrOffsetOutOfRangeError(ValueError):
    """RX1DROffset hors des bornes de la région.

    Levé **avant la simulation**, sans repli : une valeur hors bornes n'est pas saturée
    silencieusement à la borne la plus proche, elle est refusée en nommant la région et la
    borne, de sorte que le diagnostic soit actionnable (arbitrage **bbb3**).
    """

    def __init__(self, region: str, offset: int, offset_max: int) -> None:
        self.region = region
        self.offset = offset
        self.offset_max = offset_max
        super().__init__(
            f"{region} : RX1DROffset {offset} hors bornes "
            f"(0..{offset_max} dans cette région, RP002-1.0.4)."
        )


class Plan:
    """Plan régional immuable. Toutes les méthodes lèvent ValueError hors plan."""

    def __init__(self, *, name: str,
                 uplink_datr: Mapping[str, int],
                 uplink_channels_hz: tuple[int, ...],
                 downlink_datr: Mapping[int, str],
                 rx1_dr_table: Mapping[int, Sequence[int]],
                 rx1_channel_hz: Callable[[int], int],
                 max_frm_payload: Mapping[int, int],
                 dl_settings: int, rx2_hz: int) -> None:
        self.name = name
        self._uplink_datr = dict(uplink_datr)
        self._uplink_channels = tuple(uplink_channels_hz)
        self._downlink_datr = dict(downlink_datr)
        # DR montant -> DR RX1, **indexé par RX1DROffset**. La largeur des lignes donne la
        # borne haute d'offset de la région (4 valeurs = offsets 0..3, 6 = offsets 0..5).
        self._rx1_dr_table = {dr: tuple(row) for dr, row in rx1_dr_table.items()}
        self._rx1_channel_hz = rx1_channel_hz        # indice de canal montant -> fréquence RX1 (Hz)
        self._max_payload = dict(max_frm_payload)    # DR -> N
        self.dl_settings = dl_settings               # RX2 par défaut, RX1DROffset 0
        self._rx2_hz = rx2_hz
        # Table DR -> débit (montant et descendant). Un même indice doit désigner le même débit.
        table: dict[int, str] = {}
        for datr, dr in self._uplink_datr.items():
            table[dr] = datr
        for dr, datr in self._downlink_datr.items():
            if table.get(dr, datr) != datr:
                raise ValueError(f"{name} : DR{dr} désigne deux débits")
            table[dr] = datr
        self._dr_table = table
        # Une charge en file doit tenir dans toutes les fenêtres RX1 atteignables.
        # Une charge en file doit tenir dans la fenêtre RX1 la plus étroite **pour l'offset
        # effectif du terminal**. `queue_payload_max` conserve le sens historique (offset 0,
        # réglage du serveur) afin de ne rien changer au comportement par défaut ; la borne
        # exacte pour un offset donné se demande à `queue_payload_max_for`.
        self.queue_payload_max = self.queue_payload_max_for(0)

    def data_rate_index(self, datr: str) -> int:
        try:
            return self._uplink_datr[datr]
        except KeyError:
            raise ValueError(f"débit montant hors plan {self.name} : {datr!r}") from None

    def channel_index(self, freq_mhz: float) -> int:
        hz = round(freq_mhz * 1_000_000)
        for index, centre in enumerate(self._uplink_channels):
            if abs(hz - centre) <= _CHANNEL_TOLERANCE_HZ:
                return index
        raise ValueError(f"canal montant hors plan {self.name} : {freq_mhz} MHz")

    @property
    def rx1_dr_offset_max(self) -> int:
        """Plus grand RX1DROffset admis par la région (RP002-1.0.4).

        Porté par la largeur des lignes de la table RX1 : une région dont les lignes ont
        quatre valeurs admet les offsets 0..3, six valeurs les offsets 0..5. La borne vit donc
        avec les données, elle n'est pas déclarée deux fois.
        """
        return max(len(row) for row in self._rx1_dr_table.values()) - 1

    def queue_payload_max_for(self, rx1_dr_offset: int = 0) -> int:
        """Plus petite charge utile N des fenêtres RX1 atteignables avec cet offset.

        Un terminal réglé sur un offset non nul peut voir ses descentes RX1 tomber sur un DR
        plus bas — donc sur une N plus faible — qu'à l'offset 0. C'est le cas de US915 : DR8
        (N = 53) n'est atteint qu'à partir de l'offset 2, d'où une borne de 222 à l'offset 0
        mais de 53 à l'offset 2.
        """
        drs = {self.rx1_dr_for(dr, rx1_dr_offset) for dr in self._rx1_dr_table}
        return min(self._max_payload[dr] for dr in drs)

    def rx1_dr_for(self, tx_dr: int, rx1_dr_offset: int = 0) -> int:
        """DR de la fenêtre RX1 pour un DR montant et un RX1DROffset donné."""
        row = self._rx1_dr_table.get(tx_dr)
        if row is None:
            raise ValueError(f"débit montant hors plan {self.name} : DR{tx_dr}")
        if not 0 <= rx1_dr_offset < len(row):
            raise Rx1DrOffsetOutOfRangeError(self.name, rx1_dr_offset, len(row) - 1)
        return row[rx1_dr_offset]

    def rx1(self, tx_dr: int, tx_ch: int, rx1_dr_offset: int = 0) -> tuple[float, str]:
        """Fréquence (MHz) et débit descendant de la fenêtre RX1 pour une émission donnée.

        `rx1_dr_offset` est le RX1DROffset en vigueur pour le terminal — 0 par défaut, ce qui
        reproduit exactement le comportement antérieur. Une valeur hors bornes pour la région
        est refusée, jamais saturée.
        """
        if tx_dr not in self._rx1_dr_table:
            raise ValueError(f"débit montant hors plan {self.name} : DR{tx_dr}")
        if not 0 <= tx_ch < len(self._uplink_channels):
            raise ValueError(f"canal hors plan {self.name} : {tx_ch}")
        rx1_dr = self.rx1_dr_for(tx_dr, rx1_dr_offset)
        return self._rx1_channel_hz(tx_ch) / 1_000_000, self._downlink_datr[rx1_dr]

    def dr_datr(self, dr: int) -> str:
        """Débit (ex. « SF7BW125 ») de l'indice DR, montant ou descendant."""
        try:
            return self._dr_table[dr]
        except KeyError:
            raise ValueError(f"DR hors plan {self.name} : {dr}") from None

    def dr_of_downlink_datr(self, datr: str) -> int:
        """Indice DR d'un débit descendant (RX1 ou RX2) du plan."""
        for dr, value in self._downlink_datr.items():
            if value == datr:
                return dr
        raise ValueError(f"débit descendant hors plan {self.name} : {datr!r}")

    def dr_table(self) -> list[tuple[int, int, int]]:
        """16 entrées (SF, BW en kHz, DNONLY) pour `router_config` ; 0 = non défini (FSK)."""
        rows: list[tuple[int, int, int]] = []
        for dr in range(16):
            datr = self._dr_table.get(dr)
            if datr is None:
                rows.append((0, 0, 0))
                continue
            sf, bw_khz = _parse_datr(datr)
            rows.append((sf, bw_khz, 0 if dr in self._uplink_datr.values() else 1))
        return rows

    def rx2(self) -> tuple[int, str]:
        """Fréquence (Hz) et débit de la fenêtre RX2 par défaut (DLSettings)."""
        return self._rx2_hz, self._downlink_datr[self.dl_settings & 0x0F]

    def rx2_spreading_factor(self) -> int:
        """Facteur d'étalement du débit RX2 par défaut (repli des descentes)."""
        return _parse_datr(self.rx2()[1])[0]

    def uplink_channels_hz(self) -> tuple[int, ...]:
        return self._uplink_channels

    def freq_range_hz(self) -> tuple[int, int]:
        """Bornes du spectre utilisé (montant et descendant) pour `router_config`."""
        freqs = list(self._uplink_channels)
        freqs += [self._rx1_channel_hz(i) for i in range(len(self._uplink_channels))]
        freqs.append(self._rx2_hz)
        return min(freqs), max(freqs)

    def max_frm_payload(self, dr: int) -> int:
        """N : charge applicative maximale sans FOpts pour le débit DR."""
        if dr not in self._max_payload:
            raise ValueError(f"DR hors plan {self.name} : {dr}")
        return self._max_payload[dr]


_DATR_RE = re.compile(r"^SF(\d{1,2})BW(\d{3})$")


def _parse_datr(datr: str) -> tuple[int, int]:
    """« SF7BW125 » -> (7, 125)."""
    match = _DATR_RE.match(datr)
    if match is None:
        raise ValueError(f"débit non reconnu : {datr!r}")
    return int(match.group(1)), int(match.group(2))


_PLANS: dict[str, "Plan"] = {}


def register(plan: Plan) -> Plan:
    _PLANS[plan.name] = plan
    return plan


def _load_builtin() -> None:
    # Les régions s'enregistrent à l'import ; charger ici évite un import circulaire.
    for module in _BUILTIN_MODULES:
        importlib.import_module(module)


def get_plan(name: str) -> Plan:
    _load_builtin()
    try:
        return _PLANS[name]
    except KeyError:
        raise ValueError(f"plan régional non supporté : {name!r} (disponibles : "
                         f"{', '.join(sorted(_PLANS))})") from None


def plan_names() -> list[str]:
    _load_builtin()
    return sorted(_PLANS)
