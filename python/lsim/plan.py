"""Plan de canaux LoRaWAN pour le serveur (données et jointure), une région par déploiement.

Un `Plan` décrit, pour une région :
- les débits montants (chaîne « SF7BW125 » → indice DR) et descendants (indice DR → chaîne) ;
- les canaux montants par défaut, indexés comme le champ TxCh du MIC 1.1 ;
- la règle RX1 : canal, débit (RX1DROffset 0) ;
- la charge utile maximale par débit (N, sans FOpts, compatible répéteur) ;
- la valeur DLSettings du join-accept (RX2 par défaut).

Les valeurs sont celles de RP002-1.0.2 (EU863-870 §2.4 ; US902-928 §2.5), lues dans la section
EU ; US : tableaux DR et charges vérifiés sur la page TTN « US902-928 » (dérivée de RP002-1.0.4) et
la table RX1 RP002-1.0.1 ; voir les modules régionaux.
"""

from __future__ import annotations

import importlib
import re
from typing import Callable, Mapping

_BUILTIN_MODULES = ("lsim.eu868", "lsim.us915", "lsim.au915", "lsim.as923", "lsim.kr920", "lsim.in865", "lsim.ru864")

RECEIVE_DELAY1_US = 1_000_000        # RP002 §2.3 : RECEIVE_DELAY1 = 1 s, toutes régions
_CHANNEL_TOLERANCE_HZ = 1_000        # la passerelle rapporte la fréquence en Hz précis


class Plan:
    """Plan régional immuable. Toutes les méthodes lèvent ValueError hors plan."""

    def __init__(self, *, name: str,
                 uplink_datr: Mapping[str, int],
                 uplink_channels_hz: tuple[int, ...],
                 downlink_datr: Mapping[int, str],
                 rx1_dr: Mapping[int, int],
                 rx1_channel_hz: Callable[[int], int],
                 max_frm_payload: Mapping[int, int],
                 dl_settings: int, rx2_hz: int) -> None:
        self.name = name
        self._uplink_datr = dict(uplink_datr)
        self._uplink_channels = tuple(uplink_channels_hz)
        self._downlink_datr = dict(downlink_datr)
        self._rx1_dr = dict(rx1_dr)                  # DR montant -> DR RX1 (RX1DROffset 0)
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
        self.queue_payload_max = min(self._max_payload[dr] for dr in set(self._rx1_dr.values()))

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

    def rx1(self, tx_dr: int, tx_ch: int) -> tuple[float, str]:
        """Fréquence (MHz) et débit descendant de la fenêtre RX1 pour une émission donnée."""
        if tx_dr not in self._rx1_dr:
            raise ValueError(f"débit montant hors plan {self.name} : DR{tx_dr}")
        if not 0 <= tx_ch < len(self._uplink_channels):
            raise ValueError(f"canal hors plan {self.name} : {tx_ch}")
        rx1_dr = self._rx1_dr[tx_dr]
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
