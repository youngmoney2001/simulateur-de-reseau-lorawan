"""CLI d'un équipement du panneau d'étude (`docs/STUDY_PANEL_SPEC.md` §4), côté serveur.

Une session = un équipement (une passerelle). Modes IOS : utilisateur (`gw1>`), privilégié
(`gw1#`), configuration (`gw1(config)#`), interface (`gw1(config-if)#`). La grammaire est une table
de commandes ; chaque commande est une suite de mots-clés et d'arguments typés. Un mot-clé
s'abrège par préfixe non ambigu, comme IOS.

Erreurs : `CliResult.error` porte la colonne fautive (marqueur `^`) et un message. Les messages ne
reproduisent pas ceux de Cisco (§4.1). Aucun secret n'existe encore dans la configuration ; si un
champ secret est ajouté, `render_config` doit le masquer (voir `MASK`).
"""

from __future__ import annotations

import dataclasses
import ipaddress
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

MASK = "******"
REGIONS = ("EU868", "US915", "AU915", "AS923", "KR920", "IN865", "RU864")
SUB_BAND_REGIONS = ("US915", "AU915")
MESH_BANDWIDTHS_KHZ = ("203", "406", "812", "1625")  # comme `MeshModel` (scénario)
HOSTNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,62}$")
MODES = ("user", "privileged", "config", "config-if")


# Arguments typés ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Arg:
    """Argument typé. `check` renvoie la valeur normalisée ou lève ValueError (message court)."""

    kind: str
    lo: float = 0
    hi: float = 0
    choices: tuple = ()

    def describe(self) -> str:
        if self.kind == "enum":
            return "|".join(self.choices)
        if self.kind == "int":
            return f"<{int(self.lo)}-{int(self.hi)}>"
        if self.kind == "float":
            return f"<{self.lo:g}..{self.hi:g}>"
        return {"hex6": "<HEX6>", "addr": "<A.B.C.D>", "port": "<1-65535>",
                "hostname": "<nom>"}[self.kind]

    def check(self, token: str):
        if self.kind == "enum":
            for c in self.choices:
                if token.lower() == c.lower():
                    return c
            raise ValueError("valeur non reconnue")
        if self.kind in ("int", "port"):
            if not token.isdigit():
                raise ValueError("entier attendu")
            value = int(token)
            lo, hi = (1, 65535) if self.kind == "port" else (self.lo, self.hi)
            if not lo <= value <= hi:
                raise ValueError("hors bornes")
            return value
        if self.kind == "float":
            try:
                value = float(token)
            except ValueError:
                raise ValueError("nombre attendu") from None
            if not self.lo <= value <= self.hi:
                raise ValueError("hors bornes")
            return value
        if self.kind == "hex6":
            if not re.fullmatch(r"[0-9A-Fa-f]{6}", token):
                raise ValueError("6 chiffres hexadécimaux attendus")
            return token.upper()
        if self.kind == "addr":
            try:
                return str(ipaddress.IPv4Address(token))
            except ValueError:
                raise ValueError("adresse IPv4 attendue") from None
        if self.kind == "hostname":
            if not HOSTNAME_RE.fullmatch(token):
                raise ValueError("nom d'hôte invalide")
            return token
        raise AssertionError(self.kind)


def ENUM(*choices: str) -> Arg:
    return Arg("enum", choices=tuple(choices))


def INT(lo: int, hi: int) -> Arg:
    return Arg("int", lo=lo, hi=hi)


def FLOAT(lo: float, hi: float) -> Arg:
    return Arg("float", lo=lo, hi=hi)


PORT = Arg("port")
HEX6 = Arg("hex6")
ADDR = Arg("addr")
HOSTNAME = Arg("hostname")

Part = Union[str, Arg]


# Configuration -------------------------------------------------------------------------------------

@dataclass
class LoraIf:
    region: Optional[str] = None
    sub_band: Optional[int] = None
    tx_power_dbm: Optional[float] = None
    antenna_gain_dbi: Optional[float] = None
    frequency_mhz: Optional[float] = None
    shutdown: bool = False


@dataclass
class MeshIf:
    mode: Optional[str] = None
    frequency_mhz: Optional[float] = None
    spreading_factor: Optional[int] = None
    bandwidth_khz: Optional[str] = None
    max_hops: Optional[int] = None
    tx_power_dbm: Optional[float] = None
    shutdown: bool = False


@dataclass
class EthIf:
    shutdown: bool = False


@dataclass
class LorawanCfg:
    net_id: Optional[str] = None
    server: Optional[tuple[str, int, int]] = None  # adresse, port montant, port descendant
    transport: Optional[str] = None
    location: Optional[tuple[float, float]] = None


@dataclass
class GatewayConfig:
    hostname: str = "gw1"
    lora: LoraIf = field(default_factory=LoraIf)
    mesh: MeshIf = field(default_factory=MeshIf)
    eth: EthIf = field(default_factory=EthIf)
    lorawan: LorawanCfg = field(default_factory=LorawanCfg)

    def copy(self) -> "GatewayConfig":
        return GatewayConfig(hostname=self.hostname, lora=dataclasses.replace(self.lora),
                             mesh=dataclasses.replace(self.mesh), eth=dataclasses.replace(self.eth),
                             lorawan=dataclasses.replace(self.lorawan))


# Session et commandes -------------------------------------------------------------------------------

class CommandError(Exception):
    """Commande bien formée mais refusée ; `index` = indice du mot fautif."""

    def __init__(self, message: str, index: int) -> None:
        super().__init__(message)
        self.message, self.index = message, index


@dataclass
class CliResult:
    node_id: str
    mode: str
    prompt: str
    output: str = ""
    error: Optional[tuple[int, str]] = None   # (colonne du marqueur `^`, message)
    closed: bool = False                      # `exit` au niveau utilisateur


@dataclass
class Session:
    """État d'un équipement. `simulation` : résultats de simulation (None : aucun)."""

    node_id: str
    config: GatewayConfig = field(default_factory=GatewayConfig)
    startup: GatewayConfig = field(default_factory=GatewayConfig)
    mode: str = "user"
    iface: Optional[str] = None
    simulation: Optional[dict] = None
    closed: bool = False

    def prompt(self) -> str:
        host = self.config.hostname
        return {"user": f"{host}>", "privileged": f"{host}#", "config": f"{host}(config)#",
                "config-if": f"{host}(config-if)#"}[self.mode]

    def result(self, output: str = "", error: Optional[tuple[int, str]] = None) -> CliResult:
        return CliResult(node_id=self.node_id, mode=self.mode, prompt=self.prompt(),
                         output=output, error=error, closed=self.closed)


@dataclass(frozen=True)
class Command:
    modes: frozenset
    parts: tuple
    run: Callable
    iface: Optional[str] = None   # « lora », « mesh » ou « eth » (mode config-if seulement)


def _target(sess: Session):
    return {"lora": sess.config.lora, "mesh": sess.config.mesh, "eth": sess.config.eth}[sess.iface]


def _set(attr: str) -> Callable:
    def run(sess: Session, args: list) -> str:
        setattr(_target(sess), attr, args[0])
        return ""

    return run


def _shutdown(value: bool) -> Callable:
    def run(sess: Session, args: list) -> str:
        _target(sess).shutdown = value
        return ""

    return run


def _region(sess: Session, args: list) -> str:
    sess.config.lora.region = args[0]
    if args[0] not in SUB_BAND_REGIONS:
        sess.config.lora.sub_band = None  # une sous-bande n'a de sens que sur US915 / AU915
    return ""


def _sub_band(sess: Session, args: list) -> str:
    if sess.config.lora.region not in SUB_BAND_REGIONS:
        raise CommandError("sous-bande : région US915 ou AU915 requise", 0)
    sess.config.lora.sub_band = args[0]
    return ""


def _interface(sess: Session, args: list) -> str:
    sess.mode, sess.iface = "config-if", args[0]
    return ""


def _hostname(sess: Session, args: list) -> str:
    sess.config.hostname = args[0]
    return ""


def _net_id(sess: Session, args: list) -> str:
    sess.config.lorawan.net_id = args[0]
    return ""


def _server(sess: Session, args: list) -> str:
    sess.config.lorawan.server = (args[0], args[1], args[2])
    return ""


def _transport(sess: Session, args: list) -> str:
    sess.config.lorawan.transport = args[0]
    return ""


def _location(sess: Session, args: list) -> str:
    sess.config.lorawan.location = (args[0], args[1])
    return ""


def _enable(sess: Session, args: list) -> str:
    sess.mode = "privileged"
    return ""


def _disable(sess: Session, args: list) -> str:
    sess.mode = "user"
    return ""


def _configure(sess: Session, args: list) -> str:
    sess.mode = "config"
    return ""


def _end(sess: Session, args: list) -> str:
    sess.mode, sess.iface = "privileged", None
    return ""


def _exit(sess: Session, args: list) -> str:
    if sess.mode == "config-if":
        sess.mode, sess.iface = "config", None
    elif sess.mode == "config":
        sess.mode = "privileged"
    elif sess.mode == "privileged":
        sess.mode = "user"
    else:
        sess.closed = True
    return ""


def _copy(sess: Session, args: list) -> str:
    sess.startup = sess.config.copy()
    return "Building configuration...\n[OK]"


def _reload(sess: Session, args: list) -> str:
    sess.config = sess.startup.copy()
    sess.mode, sess.iface = "user", None
    return "Rechargement : configuration de démarrage appliquée."


def _write_erase(sess: Session, args: list) -> str:
    sess.config = GatewayConfig()
    sess.startup = GatewayConfig()
    return "Équipement réinitialisé."


def render_config(cfg: GatewayConfig) -> list[str]:
    """Lignes de `show running-config` : seuls les paramètres positionnés."""
    lines = [f"hostname {cfg.hostname}", "!"]
    lo = cfg.lora
    lora = []
    if lo.region:
        lora.append(f" region {lo.region}")
    if lo.sub_band:
        lora.append(f" sub-band {lo.sub_band}")
    if lo.tx_power_dbm is not None:
        lora.append(f" tx-power {lo.tx_power_dbm:g}")
    if lo.antenna_gain_dbi is not None:
        lora.append(f" antenna gain {lo.antenna_gain_dbi:g}")
    if lo.frequency_mhz is not None:
        lora.append(f" frequency {lo.frequency_mhz:g}")
    lora.append(" shutdown" if lo.shutdown else " no shutdown")
    lines += ["interface lora 0", *lora, "!"]
    me = cfg.mesh
    mesh = []
    if me.mode:
        mesh.append(f" mode {me.mode}")
    if me.frequency_mhz is not None:
        mesh.append(f" frequency {me.frequency_mhz:g}")
    if me.spreading_factor is not None:
        mesh.append(f" spreading-factor {me.spreading_factor}")
    if me.bandwidth_khz:
        mesh.append(f" bandwidth {me.bandwidth_khz}")
    if me.max_hops is not None:
        mesh.append(f" max-hops {me.max_hops}")
    if me.tx_power_dbm is not None:
        mesh.append(f" tx-power {me.tx_power_dbm:g}")
    mesh.append(" shutdown" if me.shutdown else " no shutdown")
    lines += ["interface mesh 0", *mesh, "!"]
    lines += ["interface eth 0", " shutdown" if cfg.eth.shutdown else " no shutdown", "!"]
    lw = cfg.lorawan
    if lw.net_id:
        lines.append(f"lorawan net-id {lw.net_id}")
    if lw.server:
        lines.append(f"lorawan server {lw.server[0]} up-port {lw.server[1]} "
                     f"down-port {lw.server[2]}")
    if lw.transport:
        lines.append(f"lorawan transport {lw.transport}")
    if lw.location:
        lines.append(f"lorawan location {lw.location[0]:g} {lw.location[1]:g}")
    return lines


def _show_running(sess: Session, args: list) -> str:
    return "\n".join(render_config(sess.config))


def _show_startup(sess: Session, args: list) -> str:
    return "\n".join(render_config(sess.startup))


def _show_version(sess: Session, args: list) -> str:
    return "lsim : panneau d'étude (brouillon), équipement passerelle"


def _show_interfaces(sess: Session, args: list) -> str:
    def state(off: bool) -> str:
        return "administratively down" if off else "up"

    return "\n".join([
        f"lora 0 is {state(sess.config.lora.shutdown)}",
        f"mesh 0 is {state(sess.config.mesh.shutdown)}",
        f"eth 0 is {state(sess.config.eth.shutdown)}",
    ])


def _from_simulation(key: str) -> Callable:
    """`show` sur les résultats liés à l'équipement (`sess.simulation`, rempli par la session)."""

    def run(sess: Session, args: list) -> str:
        if sess.simulation is None or key not in sess.simulation:
            return ("% Aucun résultat pour cet équipement : liez une simulation terminée à la "
                    "session, en associant cet équipement à une passerelle du run.")
        return str(sess.simulation[key])

    return run


U = frozenset({"user"})
P = frozenset({"privileged"})
C = frozenset({"config"})
CI = frozenset({"config-if"})
ALL = frozenset(MODES)
PC = P | C | CI

COMMANDS: tuple[Command, ...] = (
    Command(U, ("enable",), _enable),
    Command(U, ("show", "version"), _show_version),
    Command(U, ("show", "interfaces"), _show_interfaces),
    Command(P, ("disable",), _disable),
    Command(P, ("configure", "terminal"), _configure),
    Command(P, ("show", "running-config"), _show_running),
    Command(P, ("show", "startup-config"), _show_startup),
    Command(P, ("show", "version"), _show_version),
    Command(P, ("show", "interfaces"), _show_interfaces),
    Command(P, ("show", "lorawan", "counters"), _from_simulation("lorawan_counters")),
    Command(P, ("show", "mesh", "counters"), _from_simulation("mesh_counters")),
    Command(P, ("copy", "running-config", "startup-config"), _copy),
    Command(P, ("reload",), _reload),
    Command(P, ("write", "erase"), _write_erase),
    Command(C, ("hostname", HOSTNAME), _hostname),
    Command(C, ("interface", ENUM("lora", "mesh", "eth"), INT(0, 0)), _interface),
    Command(C, ("lorawan", "net-id", HEX6), _net_id),
    Command(C, ("lorawan", "server", ADDR, "up-port", PORT, "down-port", PORT), _server),
    Command(C, ("lorawan", "transport", ENUM("udp", "basicstation")), _transport),
    Command(C, ("lorawan", "location", FLOAT(-1e6, 1e6), FLOAT(-1e6, 1e6)), _location),
    Command(CI, ("region", ENUM(*REGIONS)), _region, "lora"),
    Command(CI, ("sub-band", INT(1, 8)), _sub_band, "lora"),
    Command(CI, ("tx-power", FLOAT(-10, 30)), _set("tx_power_dbm"), "lora"),
    Command(CI, ("antenna", "gain", FLOAT(0, 20)), _set("antenna_gain_dbi"), "lora"),
    Command(CI, ("frequency", FLOAT(137, 3000)), _set("frequency_mhz"), "lora"),
    Command(CI, ("shutdown",), _shutdown(True), "lora"),
    Command(CI, ("no", "shutdown"), _shutdown(False), "lora"),
    Command(CI, ("mode", ENUM("relay", "border")), _set("mode"), "mesh"),
    Command(CI, ("frequency", FLOAT(137, 3000)), _set("frequency_mhz"), "mesh"),
    Command(CI, ("spreading-factor", INT(7, 12)), _set("spreading_factor"), "mesh"),
    Command(CI, ("bandwidth", ENUM(*MESH_BANDWIDTHS_KHZ)), _set("bandwidth_khz"), "mesh"),
    Command(CI, ("max-hops", INT(1, 8)), _set("max_hops"), "mesh"),
    Command(CI, ("tx-power", FLOAT(-10, 30)), _set("tx_power_dbm"), "mesh"),
    Command(CI, ("shutdown",), _shutdown(True), "mesh"),
    Command(CI, ("no", "shutdown"), _shutdown(False), "mesh"),
    Command(CI, ("shutdown",), _shutdown(True), "eth"),
    Command(CI, ("no", "shutdown"), _shutdown(False), "eth"),
    Command(ALL, ("exit",), _exit),
    Command(PC, ("end",), _end),
)


# Analyse ------------------------------------------------------------------------------------------

def _tokens(line: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group()) for m in re.finditer(r"\S+", line)]


def _candidates(sess: Session) -> list[Command]:
    return [c for c in COMMANDS if sess.mode in c.modes and (c.iface is None or c.iface == sess.iface)]


def _match(cmd: Command, toks: list[tuple[int, str]]):
    """(état, indice, valeurs, message). État : ok, bad (mot i invalide), incomplete, extra."""
    values: list = []
    i = 0
    for part in cmd.parts:
        if i >= len(toks):
            return "incomplete", i, None, None
        word = toks[i][1]
        if isinstance(part, str):
            if not part.startswith(word.lower()):
                return "bad", i, None, None
        else:
            try:
                values.append(part.check(word))
            except ValueError as exc:
                return "bad", i, None, str(exc)
        i += 1
    if i < len(toks):
        return "extra", i, None, None
    return "ok", i, values, None


def new_session(node_id: str) -> Session:
    """Session d'équipement neuve : nom d'hôte = identifiant du nœud, configuration par défaut."""
    return Session(node_id=node_id, config=GatewayConfig(hostname=node_id),
                   startup=GatewayConfig(hostname=node_id))


def counters_text(report: dict) -> dict[str, str]:
    """Compteurs d'une passerelle (`GatewayReportOut` du résumé de run) en texte de `show`."""
    observation = report["observation_ns"]
    utilization = (100.0 * report["busy_ns"] / observation) if observation else 0.0
    lorawan = "\n".join([
        f"received {report['received']}",
        f"lost sensitivity {report['lost_sensitivity']}",
        f"lost collision {report['lost_collision']}",
        f"lost gateway-busy {report['lost_gateway_busy']}",
        f"audible frames {report['audible_frames']}",
        f"busy {report['busy_ns'] / 1e9:.3f} s (utilisation {utilization:.2f} %, "
        f"pic simultané {report['peak_concurrent']})",
    ])
    out = {"lorawan_counters": lorawan}
    if report.get("mesh_transmissions") is not None:
        out["mesh_counters"] = "\n".join([
            f"transmissions {report['mesh_transmissions']}",
            f"busy {report['mesh_busy_ns'] / 1e9:.3f} s",
            f"lost collision {report['mesh_lost_collision']}",
            f"lost half-duplex {report['mesh_lost_half_duplex']}",
            f"suppressed {report['mesh_suppressed']}",
        ])
    return out


def execute(sess: Session, line: str) -> CliResult:
    """Exécute une ligne dans le mode courant. Une erreur ne modifie pas l'état."""
    if sess.closed:
        return sess.result("% Session fermée.")
    toks = _tokens(line)
    if not toks:
        return sess.result()
    matches = [(c, *_match(c, toks)) for c in _candidates(sess)]
    ok = [(c, vals) for c, state, _, vals, _ in matches if state == "ok"]
    if len({c.parts for c, _ in ok}) > 1:
        return sess.result(error=(toks[0][0], "% Commande ambiguë."))
    if ok:
        cmd, values = ok[0]
        try:
            output = cmd.run(sess, values)
        except CommandError as exc:
            return sess.result(error=(toks[min(exc.index, len(toks) - 1)][0], f"% {exc.message}"))
        return sess.result(output)
    # Erreur : la position la plus avancée décide du marqueur, comme IOS.
    best = max(matches, key=lambda m: (m[2], m[1] == "incomplete"))
    _, state, index, _, message = best
    if state == "incomplete":
        return sess.result(error=(len(line.rstrip()), "% Commande incomplète."))
    column = toks[index][0] if index < len(toks) else len(line)
    detail = f" ({message})" if message else ""
    return sess.result(error=(column, f"% Entrée invalide au marqueur '^'.{detail}"))


def help_for(sess: Session, line: str) -> list[str]:
    """Aide contextuelle (`?`) : mots suivants possibles, arguments décrits, `<cr>` si complet."""
    toks = _tokens(line)
    at_space = (not line) or line[-1].isspace()
    done = toks if at_space else toks[:-1]
    partial = "" if at_space else toks[-1][1]
    options: set[str] = set()
    for cmd in _candidates(sess):
        if len(done) > len(cmd.parts):
            continue
        if any(_match_prefix(part, word) is False for part, (_, word) in zip(cmd.parts, done)):
            continue
        if len(done) == len(cmd.parts):
            if not partial:
                options.add("<cr>")
            continue
        nxt = cmd.parts[len(done)]
        if isinstance(nxt, str):
            if nxt.startswith(partial.lower()):
                options.add(nxt)
        else:
            options.add(nxt.describe())
    return sorted(options)


def _match_prefix(part: Part, word: str) -> bool:
    if isinstance(part, str):
        return part.startswith(word.lower())
    try:
        part.check(word)
        return True
    except ValueError:
        return False


def complete(sess: Session, line: str) -> tuple[str, list[str]]:
    """Tabulation : complète un mot-clé s'il est unique ; sinon renvoie les choix possibles."""
    toks = _tokens(line)
    at_space = (not line) or line[-1].isspace()
    done = toks if at_space else toks[:-1]
    partial = "" if at_space else toks[-1][1]
    options: set[str] = set()
    for cmd in _candidates(sess):
        if len(done) >= len(cmd.parts):
            continue
        if any(not _match_prefix(part, word) for part, (_, word) in zip(cmd.parts, done)):
            continue
        nxt = cmd.parts[len(done)]
        if isinstance(nxt, str) and nxt.startswith(partial.lower()):
            options.add(nxt)
    if len(options) == 1:
        word = next(iter(options))
        head = line if at_space else line[:toks[-1][0]]
        return f"{head}{word} ", []
    return line, sorted(options)
