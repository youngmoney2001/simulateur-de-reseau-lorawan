"""Service des sessions du panneau d'étude (`docs/STUDY_PANEL_SPEC.md` §6-7).

Une session regroupe des équipements (topologie, un état CLI par passerelle), peut être liée à un
exercice et à des simulations. Elle se simule elle-même : `simulate` compile la topologie et les
configurations en scénario (`study_compile`) et crée le run par le service des runs.

Persistance : chaque modification est écrite dans `study_store` (SQLite) sous le verrou du service ;
au démarrage, les sessions non expirées sont rechargées. Les sessions expirent après
`SESSION_TTL_S` d'inactivité, à partir de l'horloge injectée (`time.time` en production).

Tout accès est filtré par propriétaire ; un identifiant d'un autre compte renvoie « inconnue »
(404), jamais « interdite ». Les équipements appartiennent à leur session : aucun n'est partagé.
Les limites sont vérifiées et appliquées sous le même verrou : pas de dépassement en concurrence.

Le service ne connaît pas le serveur HTTP : `api_server` traduit `StudyError` en réponse.
"""

from __future__ import annotations

import dataclasses
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Container, Optional

from lsim import study_cli, study_exercises
from lsim.study_compile import CompileError, Compiled, compile_session
from lsim.study_contract import (
    MAX_NODES, AttemptList, AttemptOut, CliError, CliRequest, CliResponse, CriterionResult,
    GatewayLink, GatewaySettings, HintOut, Node, NodeState, Position, SensorSettings,
    SessionCreate, SessionList, SessionOut, SessionSummary, SessionTopology, SimulationBind,
    SimulationBound, SubmitResult,
    EnvironmentSettings, EnvironmentChoice,)
from lsim.materials import MATERIAL_NAMES
from lsim.study_store import StudyStore

SESSION_TTL_S = 4 * 3600
MAX_SESSIONS_PER_OWNER = 8
MAX_SESSIONS_TOTAL = 256
MAX_OUTPUT = 8000
CLI_NODE_KINDS = ("relay", "border")
MAX_ATTEMPTS = 50                  # journal borné par session (les plus anciennes sont retirées)
MAX_COMPILED = 16                  # liaisons de compilation gardées par session
TOUCH_PERSIST_S = 60.0             # une lecture n'est écrite qu'à cette fréquence (expiration)


class StudyError(Exception):
    def __init__(self, status: int, code: str, message: str, field_name: Optional[str] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field_name


# Sérialisation (la configuration CLI ne porte aucun secret : voir study_cli) -------------------

def _cfg_to_dict(cfg: study_cli.GatewayConfig) -> dict:
    lw = cfg.lorawan
    return {
        "hostname": cfg.hostname,
        "lora": dataclasses.asdict(cfg.lora),
        "mesh": dataclasses.asdict(cfg.mesh),
        "eth": dataclasses.asdict(cfg.eth),
        "lorawan": {
            "net_id": lw.net_id,
            "server": list(lw.server) if lw.server is not None else None,
            "transport": lw.transport,
            "location": list(lw.location) if lw.location is not None else None,
        },
    }


def _cfg_from_dict(d: dict) -> study_cli.GatewayConfig:
    lw = d["lorawan"]
    return study_cli.GatewayConfig(
        hostname=d["hostname"],
        lora=study_cli.LoraIf(**d["lora"]),
        mesh=study_cli.MeshIf(**d["mesh"]),
        eth=study_cli.EthIf(**d["eth"]),
        lorawan=study_cli.LorawanCfg(
            net_id=lw["net_id"],
            server=tuple(lw["server"]) if lw["server"] is not None else None,
            transport=lw["transport"],
            location=tuple(lw["location"]) if lw["location"] is not None else None))


def _cli_to_dict(s: study_cli.Session) -> dict:
    return {"config": _cfg_to_dict(s.config), "startup": _cfg_to_dict(s.startup), "mode": s.mode,
            "iface": s.iface, "simulation": s.simulation, "closed": s.closed}


def _cli_from_dict(node_id: str, d: dict) -> study_cli.Session:
    return study_cli.Session(node_id=node_id, config=_cfg_from_dict(d["config"]),
                             startup=_cfg_from_dict(d["startup"]), mode=d["mode"], iface=d["iface"],
                             simulation=d["simulation"], closed=d["closed"])


@dataclass
class _Study:
    owner: str
    last_used: float
    saved_used: float = 0.0            # dernière valeur de `last_used` écrite en base
    exercise_id: Optional[str] = None
    nodes: dict = field(default_factory=dict)       # id -> Node
    cli: dict = field(default_factory=dict)         # id -> study_cli.Session
    reports: dict = field(default_factory=dict)     # id -> rapport de passerelle lié
    sf_par_equipement: dict = field(default_factory=dict)  # groupe -> {SF depart, SF final}
    # Options de protocole du run. Demandées ici, **effectivement simulées** selon ce que le
    # moteur accepte : la jointure et l'ADR s'excluent (`mac_loop.check_closed_loop`).
    join: bool = False
    confirmed: bool = False
    # Nature des événements du dernier run lié (`join_request`, `join_accept`, `uplink`, `ack`).
    # Comptée par le serveur à la fin du run, donc exacte : noter un exercice sur un compte
    # partiel reviendrait à noter un run qu'on n'a pas entièrement lu.
    echanges: dict = field(default_factory=dict)
    run_id: Optional[str] = None
    terrain_id: Optional[str] = None   # relief applique aux runs ; None = pas choisi, pas « plat »
    # Environnement radio : obstacles, shadowing, hauteurs d'antennes. Vierge par défaut —
    # un scénario compilé sans environnement n'émet aucun bloc, et garde son empreinte.
    environment: EnvironmentSettings = field(default_factory=EnvironmentSettings)
    # ADR du serveur (LinkADRReq). Demande de l'utilisateur, pas un constat : la session peut
    # le vouloir sans qu'il soit possible, et la raison est alors affichée, pas tue.
    adr: bool = False
    hints_revealed: dict = field(default_factory=dict)   # exercice -> nombre d'indices révélés
    attempts: deque = field(default_factory=lambda: deque(maxlen=MAX_ATTEMPTS))
    attempt_count: int = 0
    compiled: dict = field(default_factory=dict)    # run_id -> [GatewayLink] (compilation)
    # Historique annuler/rétablir : piles de (libellé, instantané). Volontairement **non
    # persisté** — un historique survit à la session en mémoire, pas à un redémarrage, et le
    # faire durer gonflerait la base pour un bénéfice que personne ne réclame.
    defaire: list = field(default_factory=list)
    refaire: list = field(default_factory=list)


def _adr_etat(st: _Study) -> tuple[bool, str]:
    """L'ADR est-il simulable sur cette session, et sinon pourquoi.

    Sorti de `compile_session` pour être lisible **avant** le run : l'atelier grise le réglage
    avec sa raison au lieu de laisser l'utilisateur compiler pour découvrir le refus.
    """
    from lsim.study_compile import adr_possible
    return adr_possible(list(st.nodes.values()), {nid: c.config for nid, c in st.cli.items()})


def _join_etat(st: _Study) -> tuple[bool, str]:
    """La jointure OTAA est-elle simulable, et sinon pourquoi. Lisible **avant** le run."""
    from lsim.study_compile import join_possible
    return join_possible(list(st.nodes.values()), {nid: c.config for nid, c in st.cli.items()},
                         st.adr)


def _confirmed_etat(st: _Study) -> tuple[bool, str]:
    """Les trames confirmées sont-elles simulables, et sinon pourquoi."""
    from lsim.study_compile import confirmed_possible
    return confirmed_possible(list(st.nodes.values()),
                              {nid: c.config for nid, c in st.cli.items()}, st.adr)


MAX_UNDO = 50   # profondeur d'historique : au-delà, on oublie le plus ancien


def _instantane(st: _Study) -> dict:
    """Copie de tout ce qu'une opération peut changer, l'équipement et sa console compris.

    La console est copiée **par valeur** (`_cli_to_dict`) : c'est la configuration de
    l'équipement, et annuler une commande `region US915` doit la restaurer. Sans elle,
    annuler remettrait la case de l'interface sans remettre l'état du CLI — deux vérités.
    """
    return {
        "nodes": {nid: n.model_dump(mode="json") for nid, n in st.nodes.items()},
        "cli": {nid: _cli_to_dict(c) for nid, c in st.cli.items()},
        "terrain_id": st.terrain_id,
        "environment": st.environment.model_dump(mode="json"),
        "adr": st.adr,
        "join": st.join,
        "confirmed": st.confirmed,
    }


def _restaurer(st: _Study, instantane: dict) -> None:
    st.nodes = {nid: Node.model_validate(n) for nid, n in instantane["nodes"].items()}
    st.cli = {nid: _cli_from_dict(nid, c) for nid, c in instantane["cli"].items()}
    st.terrain_id = instantane["terrain_id"]
    st.environment = EnvironmentSettings.model_validate(instantane["environment"])
    st.adr = instantane["adr"]
    st.join = instantane["join"]
    st.confirmed = instantane["confirmed"]


def _push(st: _Study, libelle: str, instantane: Optional[dict] = None) -> None:
    """Empile l'état courant avant une opération, et oublie le futur.

    Le futur est oublié : après une opération nouvelle, il n'y a plus rien à rétablir —
    c'est la règle de tout éditeur, et l'enfreindre rendrait « rétablir » imprévisible.

    L'instantané porte le libellé de l'opération **à venir** : c'est lui que l'interface
    annoncera (« annuler le déplacement de capteur-1 »).

    `instantane` : état à retenir, quand il doit être pris **avant** l'opération alors
    qu'on ne saura qu'après si elle comptait — c'est le cas d'une commande CLI, dont on ne
    connaît l'effet qu'une fois exécutée.
    """
    libelle = libelle.strip()[:120]
    st.defaire.append((libelle, _instantane(st) if instantane is None else instantane, None))
    if len(st.defaire) > MAX_UNDO:
        del st.defaire[0]
    st.refaire.clear()


def _encode(st: _Study) -> dict:
    return {
        "exercise_id": st.exercise_id,
        "nodes": {nid: n.model_dump(mode="json") for nid, n in st.nodes.items()},
        "cli": {nid: _cli_to_dict(c) for nid, c in st.cli.items()},
        "reports": st.reports,
        "sf_par_equipement": st.sf_par_equipement,
        "run_id": st.run_id,
        "terrain_id": st.terrain_id,
        "environment": st.environment.model_dump(mode="json"),
        "adr": st.adr,
        "join": st.join,
        "confirmed": st.confirmed,
        "echanges": st.echanges,
        "hints_revealed": st.hints_revealed,
        "attempt_count": st.attempt_count,
        "compiled": {rid: [link.model_dump(mode="json") for link in links]
                     for rid, links in st.compiled.items()},
    }


def _decode(owner: str, last_used: float, body: dict, attempts: list[dict]) -> _Study:
    st = _Study(owner=owner, last_used=last_used, saved_used=last_used,
                exercise_id=body["exercise_id"],
                nodes={nid: Node.model_validate(n) for nid, n in body["nodes"].items()},
                cli={nid: _cli_from_dict(nid, c) for nid, c in body["cli"].items()},
                reports=body["reports"], run_id=body["run_id"],
                sf_par_equipement=body.get("sf_par_equipement") or {},
                join=bool(body.get("join")), confirmed=bool(body.get("confirmed")),
                echanges=dict(body.get("echanges") or {}),
                hints_revealed=body["hints_revealed"], attempt_count=body["attempt_count"],
                compiled={rid: [GatewayLink.model_validate(x) for x in links]
                          for rid, links in body["compiled"].items()},
                terrain_id=body.get("terrain_id"), adr=body.get("adr", False),
                # Une session enregistrée avant l'environnement radio n'a pas la clé : elle
                # rouvre avec un environnement vierge, donc des runs à l'identique.
                environment=EnvironmentSettings.model_validate(
                    body["environment"]) if "environment" in body else EnvironmentSettings())
    st.attempts.extend(AttemptOut.model_validate(a) for a in attempts)
    return st


class StudyService:
    def __init__(self, *, clock: Callable[[], float] = time.time,
                 store: Optional[StudyStore] = None) -> None:
        self._clock = clock                 # horloge murale : expiration et horodatage du journal
        self._lock = threading.Lock()
        self._store = store if store is not None else StudyStore(":memory:")
        self._sessions: dict[str, _Study] = {}
        now = self._clock()
        for sid, owner, used, body in self._store.load_sessions():
            if now - used > SESSION_TTL_S:
                self._store.delete_session(sid)
                continue
            self._sessions[sid] = _decode(owner, used, body, self._store.attempts(sid))

    def close(self) -> None:
        self._store.close()

    # Accès et persistance (verrou tenu par l'appelant) ----------------------------------------

    def _save(self, sid: str, st: _Study) -> None:
        st.saved_used = st.last_used
        self._store.save_session(sid, st.owner, st.last_used, _encode(st))

    def _purge_locked(self) -> None:
        now = self._clock()
        for sid in [k for k, st in self._sessions.items() if now - st.last_used > SESSION_TTL_S]:
            del self._sessions[sid]
            self._store.delete_session(sid)

    def _get_locked(self, owner: str, sid: str) -> _Study:
        self._purge_locked()
        st = self._sessions.get(sid)
        if st is None or st.owner != owner:
            raise StudyError(404, "not_found", "session inconnue")
        st.last_used = self._clock()
        if st.last_used - st.saved_used >= TOUCH_PERSIST_S:
            self._save(sid, st)
        return st

    # Sessions -----------------------------------------------------------------------------------

    def create(self, owner: str, req: SessionCreate) -> SessionOut:
        nodes = list(req.nodes)
        if req.exercise_id is not None:
            exercise = study_exercises.get(req.exercise_id)
            if exercise is None:
                raise StudyError(422, "validation_error", "exercice inconnu", "exercise_id")
            if nodes:
                raise StudyError(422, "validation_error",
                                 "la topologie vient de l'exercice : nodes doit être vide",
                                 "nodes")
            nodes = list(exercise.start_nodes)
        ids = [n.id for n in nodes]
        if len(set(ids)) != len(ids):
            raise StudyError(422, "validation_error", "identifiants d'équipements en double",
                             "nodes")
        with self._lock:
            self._purge_locked()
            owned = sum(1 for st in self._sessions.values() if st.owner == owner)
            if owned >= MAX_SESSIONS_PER_OWNER:
                raise StudyError(429, "limit_exceeded", "trop de sessions pour ce compte")
            if len(self._sessions) >= MAX_SESSIONS_TOTAL:
                raise StudyError(429, "limit_exceeded", "capacité des sessions atteinte")
            sid = secrets.token_urlsafe(16)
            st = _Study(owner=owner, last_used=self._clock(), exercise_id=req.exercise_id,
                        nodes={n.id: n for n in nodes},
                        cli={n.id: study_cli.new_session(n.id) for n in nodes})
            self._sessions[sid] = st
            self._save(sid, st)
        return SessionOut(session_id=sid, exercise_id=req.exercise_id)

    def _topology_locked(self, sid: str, st: _Study) -> SessionTopology:
        nodes = list(st.nodes.values())
        states = []
        for node in nodes:
            cli = st.cli[node.id]
            states.append(NodeState(
                node_id=node.id, hostname=cli.config.hostname,
                region=cli.config.lora.region,
                configured=cli.config != study_cli.new_session(node.id).config,
                gateway=_gateway_state(node, cli)))
        ok, raison = _adr_etat(st)
        join_ok, join_raison = _join_etat(st)
        conf_ok, conf_raison = _confirmed_etat(st)
        return SessionTopology(session_id=sid, nodes=nodes, states=states,
                                terrain_id=st.terrain_id, adr=st.adr,
                                environment=st.environment,
                                adr_possible=ok, adr_raison=raison,
                                join=st.join, join_possible=join_ok, join_raison=join_raison,
                                confirmed=st.confirmed, confirmed_possible=conf_ok,
                                confirmed_raison=conf_raison,
                                can_undo=bool(st.defaire), can_redo=bool(st.refaire),
                                undo_label=st.defaire[-1][0] if st.defaire else "",
                                redo_label=st.refaire[-1][0] if st.refaire else "")

    def topology(self, owner: str, sid: str) -> SessionTopology:
        with self._lock:
            st = self._get_locked(owner, sid)
            return self._topology_locked(sid, st)

    # Topologie : ajout, retrait, réglages de capteur ------------------------------------------

    def add_node(self, owner: str, sid: str, node: Node) -> SessionTopology:
        with self._lock:
            st = self._get_locked(owner, sid)
            if node.id in st.nodes:
                raise StudyError(422, "validation_error", "identifiant d'équipement déjà utilisé",
                                 "id")
            if len(st.nodes) >= MAX_NODES:
                raise StudyError(422, "limit_exceeded",
                                 f"au plus {MAX_NODES} équipements par session", "nodes")
            _push(st, f"ajout de {node.id}")
            st.nodes[node.id] = node
            st.cli[node.id] = study_cli.new_session(node.id)
            self._save(sid, st)
            return self._topology_locked(sid, st)

    def move_node(self, owner: str, sid: str, node_id: str, pos: Position) -> SessionTopology:
        with self._lock:
            st = self._get_locked(owner, sid)
            node = st.nodes.get(node_id)
            if node is None:
                raise StudyError(404, "not_found", "équipement inconnu dans cette session")
            # Un déplacement qui ne déplace rien ne doit pas entrer dans l'historique :
            # annuler pour découvrir qu'aucun pixel n'a bougé use la confiance dans le bouton.
            if node.x_m == pos.x_m and node.y_m == pos.y_m:
                return self._topology_locked(sid, st)
            _push(st, f"déplacement de {node_id}")
            st.nodes[node_id] = node.model_copy(update={"x_m": pos.x_m, "y_m": pos.y_m})
            self._save(sid, st)
            return self._topology_locked(sid, st)

    def list_sessions(self, owner: str) -> SessionList:
        """Sessions du compte, les plus récentes d'abord. Jamais celles d'un autre compte."""
        with self._lock:
            self._purge_locked()
            now = self._clock()
            mine = [(sid, st) for sid, st in self._sessions.items() if st.owner == owner]
            mine.sort(key=lambda item: item[1].last_used, reverse=True)
            return SessionList(items=[
                SessionSummary(session_id=sid, exercise_id=st.exercise_id,
                               nodes=len(st.nodes), idle_s=max(0, int(now - st.last_used)))
                for sid, st in mine])

    def delete_session(self, owner: str, sid: str) -> None:
        with self._lock:
            self._get_locked(owner, sid)            # 404 si inconnue ou d'un autre compte
            del self._sessions[sid]
            self._store.delete_session(sid)

    def remove_node(self, owner: str, sid: str, node_id: str) -> None:
        with self._lock:
            st = self._get_locked(owner, sid)
            if node_id not in st.nodes:
                raise StudyError(404, "not_found", "équipement inconnu dans cette session")
            _push(st, f"retrait de {node_id}")
            del st.nodes[node_id], st.cli[node_id]
            st.reports.pop(node_id, None)
            self._save(sid, st)

    def set_sensor(self, owner: str, sid: str, node_id: str,
                   settings: SensorSettings) -> SessionTopology:
        with self._lock:
            st = self._get_locked(owner, sid)
            node = st.nodes.get(node_id)
            if node is None:
                raise StudyError(404, "not_found", "équipement inconnu dans cette session")
            if node.kind != "sensor":
                raise StudyError(422, "validation_error", "réglages capteur : équipement non capteur",
                                 "node_id")
            _push(st, f"réglages de {node_id}")
            st.nodes[node_id] = node.model_copy(update={"sensor": settings})
            self._save(sid, st)
            return self._topology_locked(sid, st)

    def set_gateway(self, owner: str, sid: str, node_id: str,
                    settings: GatewaySettings) -> SessionTopology:
        """Réglages passerelle depuis l'atelier 3D.

        Écrit dans `Session.config`, c'est-à-dire **la même configuration que le CLI** : un
        réglage posé dans la fenêtre apparaît dans `show running-config`, et réciproquement.
        Les deux chemins ne divergent pas parce qu'il n'y a qu'un seul état.

        Seuls les champs présents sont appliqués : une fenêtre qui n'affiche pas l'antenne ne
        doit pas pouvoir l'effacer.
        """
        with self._lock:
            st = self._get_locked(owner, sid)
            node = st.nodes.get(node_id)
            if node is None:
                raise StudyError(404, "not_found", "équipement inconnu dans cette session")
            if node.kind not in CLI_NODE_KINDS:
                raise StudyError(422, "validation_error",
                                 "réglages passerelle : équipement sans interface configurable",
                                 "node_id")
            cfg = st.cli[node_id].config
            # Une sous-bande n'existe que sur US915 / AU915 : même refus, mêmes mots que le
            # CLI, pour que l'apprenant n'ait pas deux vérités selon le chemin emprunté.
            # La région retenue est celle du payload si elle y est, sinon celle déjà posée :
            # c'est ce qui permet d'écrire la sous-bande après la région en deux envois.
            region = settings.region if settings.region is not None else cfg.lora.region
            if settings.sub_band is not None and region not in study_cli.SUB_BAND_REGIONS:
                raise StudyError(422, "validation_error",
                                 "sous-bande : région US915 ou AU915 requise", "sub_band")
            # Les autres champs écrivent la configuration CLI, celle-là même que la console
            # affiche : annuler doit la restaurer. L'instantané est pris **avant** la
            # première écriture, une seule fois pour tous les champs de l'envoi.
            if any(settings.model_fields_set & {"region", "sub_band", "tx_power_dbm",
                                                "mesh_mode", "mesh_max_hops",
                                                "mesh_bandwidth_khz"}):
                _push(st, f"réglages de {node_id}")
            if settings.region is not None:
                cfg.lora.region = settings.region
                if settings.region not in study_cli.SUB_BAND_REGIONS:
                    cfg.lora.sub_band = None   # la sous-bande n'a plus de sens hors US915/AU915
            if settings.sub_band is not None:
                cfg.lora.sub_band = settings.sub_band
            if settings.tx_power_dbm is not None:
                cfg.lora.tx_power_dbm = settings.tx_power_dbm
            if settings.mesh_mode is not None:
                cfg.mesh.mode = settings.mesh_mode
            if settings.mesh_max_hops is not None:
                cfg.mesh.max_hops = settings.mesh_max_hops
            if settings.mesh_bandwidth_khz is not None:
                cfg.mesh.bandwidth_khz = settings.mesh_bandwidth_khz
            # Le modèle n'est pas un réglage du CLI : c'est le matériel, il vit sur le nœud.
            # Il se règle ici quand même, même endroit que les autres réglages passerelle,
            # sinon une passerelle posée depuis la palette resterait au seuil de référence.
            # Vide explicite = retour à la référence ; champ absent = rien ne change.
            if "gateway_profile" in settings.model_fields_set:
                _push(st, f"modèle de {node_id}")
                st.nodes[node_id] = node.model_copy(
                    update={"gateway_profile": settings.gateway_profile})
            self._save(sid, st)
            return self._topology_locked(sid, st)

    def cli(self, owner: str, sid: str, req: CliRequest) -> CliResponse:
        with self._lock:
            st = self._get_locked(owner, sid)
            node = st.nodes.get(req.node_id)
            if node is None:
                raise StudyError(404, "not_found", "équipement inconnu dans cette session")
            if node.kind not in CLI_NODE_KINDS:
                raise StudyError(422, "validation_error",
                                 "pas de CLI pour ce type d'équipement", "node_id")
            cli = st.cli[node.id]
            avant = _cli_to_dict(cli)
            # L'instantané est pris **avant** : on ne saura qu'après si la commande comptait,
            # et le prendre à ce moment-là retiendrait l'état d'après — une annulation qui
            # ne remettrait rien.
            avant_instantane = _instantane(st)
            result = study_cli.execute(cli, req.command)
            output = result.output
            # Seule une commande qui **change la configuration** entre dans l'historique.
            # `enable`, `configure terminal`, `interface lora 0`, `end` et les `show` ne
            # touchent que le mode ou n'affichent rien : en faire des étapes obligerait à
            # annuler quatre fois pour effacer une région, et l'on ne saurait jamais où
            # s'arrêter. L'état restauré les remet de lui-même, puisque le mode fait partie
            # de l'instantané.
            if (_cli_to_dict(cli)["config"] != avant["config"]
                    or _cli_to_dict(cli)["startup"] != avant["startup"]):
                _push(st, f"{node.id} : {req.command[:60].strip()}", avant_instantane)
            if cli.closed:  # « exit » au niveau utilisateur : la console redémarre en mode utilisateur
                cli.closed, cli.mode = False, "user"
                output = "% Session console fermée ; retour au mode utilisateur."
            if len(output) > MAX_OUTPUT:
                output = output[:MAX_OUTPUT - 40] + "\n% sortie tronquée"
            error = None
            if result.error is not None:
                column, message = result.error
                error = CliError(column=min(column, 256), message=message[:200])
            self._save(sid, st)
        return CliResponse(node_id=node.id, mode=result.mode, prompt=result.prompt,
                           output=output, error=error)

    # Simulation de la session -----------------------------------------------------------------

    def compile(self, owner: str, sid: str, seed: int) -> Compiled:
        """Compile la topologie et les configurations courantes. Lève `StudyError` (422)."""
        with self._lock:
            st = self._get_locked(owner, sid)
            nodes = list(st.nodes.values())
            configs = {nid: cli.config.copy() for nid, cli in st.cli.items()}
        try:
            return compile_session(nodes, configs, seed, terrain_id=st.terrain_id,
                                        environment=st.environment,
                                        adr=st.adr, join=st.join, confirmed=st.confirmed)
        except CompileError as exc:
            raise StudyError(422, "validation_error", exc.message, exc.field) from None

    def set_protocol(self, owner: str, sid: str, join: bool, confirmed: bool) -> SessionTopology:
        """Règle la jointure OTAA et les trames confirmées.

        Comme pour l'ADR, le souhait est gardé même quand il n'est pas simulable, et c'est la
        topologie qui décide : la raison revient dans la réponse plutôt que dans un refus.
        """
        with self._lock:
            st = self._get_locked(owner, sid)
            # Recliquer une case déjà cochée n'est pas une opération : l'entrer dans
            # l'historique ferait un « annuler » qui ne change rien.
            if (st.join, st.confirmed) != (bool(join), bool(confirmed)):
                _push(st, "jointure et trames confirmées")
            st.join = bool(join)
            st.confirmed = bool(confirmed)
            return self._topology_locked(sid, st)

    def set_adr(self, owner: str, sid: str, adr: bool) -> SessionTopology:
        """Active ou désactive l'ADR du serveur.

        Le souhait est toujours enregistré, même quand la topologie ne le permet pas : la
        session garde l'intention et la raison est affichée. Effacer le souhait au motif qu'il
        n'est pas réalisable ferait perdre à l'utilisateur ce qu'il voulait faire, sans rien lui
        apprendre de plus.
        """
        with self._lock:
            st = self._get_locked(owner, sid)
            if st.adr != bool(adr):
                _push(st, "ADR du serveur")
            st.adr = bool(adr)
            return self._topology_locked(sid, st)

    def set_terrain(self, owner: str, sid: str, terrain_id: Optional[str],
                    known: Container[str]) -> SessionTopology:
        """Relief appliqué aux runs de la session.

        `known` est l'ensemble des identifiants du catalogue serveur, injecté par l'appelant :
        le service d'étude n'a pas à connaître le service des runs. Un relief inconnu est
        refusé ici, et non au moment du run — une erreur au lancement d'une simulation
        arrive trop tard, elle laisse croire que le reste est prêt.
        """
        with self._lock:
            st = self._get_locked(owner, sid)
            if terrain_id is not None and terrain_id not in known:
                raise StudyError(422, "validation_error",
                                 f"relief « {terrain_id} » inconnu du catalogue", "terrain_id")
            if st.terrain_id != terrain_id:
                _push(st, "relief")
            st.terrain_id = terrain_id
            self._save(sid, st)
            return self._topology_locked(sid, st)

    def set_environment(self, owner: str, sid: str,
                        settings: EnvironmentChoice) -> SessionTopology:
        """Environnement radio de la session : obstacles, shadowing, hauteurs d'antennes.

        Seuls les champs présents sont appliqués, comme sur `set_gateway` : régler le
        shadowing ne doit pas démolir les murs déjà posés. Un environnement **vierge** —
        aucun obstacle, sigma nul, hauteurs au défaut du moteur — n'émet aucun bloc
        `environment` : le scénario compilé est alors exactement celui d'avant, et son
        empreinte avec.

        Le matériau est vérifié contre le catalogue du moteur ici, et non au run : un nom
        inconnu doit être refusé à la pose du mur, pas à la simulation.
        """
        with self._lock:
            st = self._get_locked(owner, sid)
            for o in settings.obstacles or []:
                if o.material is not None and o.material not in MATERIAL_NAMES:
                    raise StudyError(422, "validation_error",
                                     f"matériau inconnu : {o.material}", "obstacles")
            actuel = st.environment
            suivant = EnvironmentSettings(
                shadowing_sigma_db=settings.shadowing_sigma_db
                if settings.shadowing_sigma_db is not None else actuel.shadowing_sigma_db,
                gateway_height_m=settings.gateway_height_m
                if settings.gateway_height_m is not None else actuel.gateway_height_m,
                device_height_m=settings.device_height_m
                if settings.device_height_m is not None else actuel.device_height_m,
                obstacles=settings.obstacles if settings.obstacles is not None
                else actuel.obstacles)
            # Renvoyer l'environnement qu'on a déjà n'est pas une opération : l'entrer dans
            # l'historique ferait un « annuler » qui ne change rien, la même règle que pour
            # une case ADR recliquée telle quelle.
            if suivant != actuel:
                _push(st, "environnement radio")
                st.environment = suivant
                self._save(sid, st)
            return self._topology_locked(sid, st)

    def undo(self, owner: str, sid: str) -> SessionTopology:
        """Annule la dernière opération, console de l'équipement comprise.

        Une commande CLI tapée puis annulée redevient une commande jamais tapée : c'est la
        configuration de l'équipement qui est restaurée, pas seulement ce que l'interface en
        montrait. Rien à annuler : 409, avec un message qui le dit — c'est un état, pas une
        erreur de l'utilisateur, mais ce n'est pas non plus un succès silencieux.
        """
        with self._lock:
            st = self._get_locked(owner, sid)
            if not st.defaire:
                raise StudyError(409, "nothing_to_undo", "rien à annuler")
            libelle, avant, _ = st.defaire.pop()
            st.refaire.append((libelle, _instantane(st), None))
            _restaurer(st, avant)
            self._save(sid, st)
            return self._topology_locked(sid, st)

    def redo(self, owner: str, sid: str) -> SessionTopology:
        """Rétablit la dernière opération annulée. Rien à rétablir : 409."""
        with self._lock:
            st = self._get_locked(owner, sid)
            if not st.refaire:
                raise StudyError(409, "nothing_to_redo", "rien à rétablir")
            libelle, apres, _ = st.refaire.pop()
            st.defaire.append((libelle, _instantane(st), None))
            _restaurer(st, apres)
            self._save(sid, st)
            return self._topology_locked(sid, st)

    def record_simulation(self, owner: str, sid: str, run_id: str, links: list[dict]) -> None:
        """Mémorise les liaisons d'un run créé par `compile` (appelé après sa création)."""
        with self._lock:
            st = self._get_locked(owner, sid)
            st.compiled[run_id] = [GatewayLink.model_validate(x) for x in links]
            while len(st.compiled) > MAX_COMPILED:
                del st.compiled[next(iter(st.compiled))]
            st.run_id = run_id
            self._save(sid, st)

    # Liaison à une simulation -------------------------------------------------------------------

    def bind_run(self, owner: str, sid: str, req: SimulationBind, summary: dict,
                 sf_par_equipement: Optional[dict] = None) -> SimulationBound:
        """Lie le résumé d'un run terminé selon les associations de la requête, ou, sans
        association, selon la compilation de la session si le run en vient.

        Tout est validé avant la moindre modification : une association invalide ne laisse aucun
        équipement à moitié lié. `summary` vient de `RunService.summary` (propriétaire vérifié).

        `sf_par_equipement` : SF de départ et de fin par groupe, lu dans les lignes de
        dispositifs. Il n'est pas dans le résumé, et c'est pourtant la seule pièce qui dise si
        le serveur a changé le débit d'un capteur — donc la seule qui permette de noter un
        exercice sur l'ADR sans interroger une case de formulaire.

        `summary["event_kinds"]` : nature des événements, comptée par le serveur à la fin du
        run. C'est ce qui permet de noter une jointure sur les join-accept **observés**.
        """
        gateways = {g["name"]: g for g in summary.get("gateways") or []}
        # Un run ADR n'a **aucune passerelle nommée** : la session y compile en forme
        # `gateway` (singulier), seule forme que le moteur accepte avec un MAC actif. Il n'y a
        # donc rien à lier, et ce n'est pas une erreur de l'utilisateur — c'est le coût assumé
        # de l'ADR. On accepte la liaison sans lien plutôt que de la refuser : sinon l'atelier
        # échouerait sur **chaque** run ADR, y compris celui qui vient d'être lancé.
        #
        # En revanche, un run qui nomme des passerelles reste strict : un nom absent du run est
        # une faute de l'utilisateur, et le refus le lui dit.
        sans_passerele_nommee = not gateways
        seen_nodes: set[str] = set()
        seen_gateways: set[str] = set()
        with self._lock:
            st = self._get_locked(owner, sid)
            if req.links:
                # Liaison explicite : jamais avalée en silence. Un nom absent du run est une
                # faute de l'utilisateur, et le refus le lui dit — même si le run n'en nomme
                # aucun. C'est la seule voie qui doive rester stricte.
                links = list(req.links)
            elif sans_passerele_nommee:
                links = []          # rien à lier : le run ne nomme aucune passerelle
            else:
                links = [link for link in st.compiled.get(req.run_id, [])
                         if link.node_id in st.nodes]
            for link in links:
                node = st.nodes.get(link.node_id)
                if node is None:
                    raise StudyError(422, "validation_error",
                                     f"équipement inconnu : {link.node_id}", "links")
                if node.kind not in CLI_NODE_KINDS:
                    raise StudyError(422, "validation_error",
                                     f"équipement sans passerelle : {link.node_id}", "links")
                if link.gateway not in gateways:
                    raise StudyError(422, "validation_error",
                                     f"passerelle absente du run : {link.gateway}", "links")
                if link.node_id in seen_nodes or link.gateway in seen_gateways:
                    raise StudyError(422, "validation_error",
                                     "équipement ou passerelle associé deux fois", "links")
                seen_nodes.add(link.node_id)
                seen_gateways.add(link.gateway)
            st.reports = {}
            linked = []
            for link in links:
                report = gateways[link.gateway]
                st.reports[link.node_id] = dict(report)
                st.cli[link.node_id].simulation = study_cli.counters_text(report)
                linked.append(link.node_id)
            for node_id, cli in st.cli.items():
                if node_id not in seen_nodes:
                    cli.simulation = None
            st.run_id = req.run_id
            st.sf_par_equipement = dict(sf_par_equipement or {})
            st.echanges = dict(summary.get("event_kinds") or {})
            unlinked = [n for n in st.nodes if n not in seen_nodes]
            self._save(sid, st)
        return SimulationBound(session_id=sid, run_id=req.run_id, linked=linked, unlinked=unlinked)

    # Exercices ----------------------------------------------------------------------------------

    @staticmethod
    def _exercise_for_session(st: _Study, exercise_id: str, field_name: str):
        exercise = study_exercises.get(exercise_id)
        if exercise is None:
            raise StudyError(404, "not_found", "exercice inconnu")
        if st.exercise_id != exercise_id:
            raise StudyError(422, "validation_error",
                             "session non liée à cet exercice", field_name)
        return exercise

    def hint(self, owner: str, sid: str, exercise_id: str) -> HintOut:
        """Révèle l'indice suivant de l'exercice lié à la session. Chaque indice coûte des points."""
        with self._lock:
            st = self._get_locked(owner, sid)
            exercise = self._exercise_for_session(st, exercise_id, "exercise_id")
            used = st.hints_revealed.get(exercise_id, 0)
            if used >= len(exercise.hints):
                raise StudyError(409, "conflict", "plus d'indice disponible pour cet exercice")
            st.hints_revealed[exercise_id] = used + 1
            self._save(sid, st)
        return HintOut(exercise_id=exercise_id, number=used + 1,
                       text=exercise.hints[used], penalty=study_exercises.HINT_PENALTY)

    def submit(self, owner: str, exercise_id: str, sid: str) -> SubmitResult:
        """Note la session pour l'exercice. Seul l'état détenu par le serveur est évalué.

        Chaque indice révélé retire `HINT_PENALTY` points (plancher 0). La tentative est
        journalisée avec ses résultats seulement : ni commande CLI, ni secret.
        """
        with self._lock:
            st = self._get_locked(owner, sid)
            exercise = self._exercise_for_session(st, exercise_id, "session_id")
            state = study_exercises.State(
                configs={nid: cli.config.copy() for nid, cli in st.cli.items()},
                reports={nid: dict(r) for nid, r in st.reports.items()},
                devices={k: dict(v) for k, v in st.sf_par_equipement.items()},
                adr=st.adr, join=st.join, echanges=dict(st.echanges))
            hints_used = st.hints_revealed.get(exercise_id, 0)
        graded = study_exercises.grade(exercise, state)
        criteria = [CriterionResult(id=c.id, label=c.label, passed=ok,
                                    points=c.points if ok else 0, max_points=c.points)
                    for c, ok in graded]
        score = max(0, sum(c.points for c in criteria)
                    - hints_used * study_exercises.HINT_PENALTY)
        result = SubmitResult(exercise_id=exercise_id, score=score,
                              max_score=exercise.max_points, hints_used=hints_used,
                              criteria=criteria)
        with self._lock:
            st = self._get_locked(owner, sid)
            st.attempt_count += 1
            attempt = AttemptOut(
                number=st.attempt_count, at=int(self._clock()), exercise_id=exercise_id,
                score=score, max_score=exercise.max_points, hints_used=hints_used,
                passed=[c.id for c in criteria if c.passed])
            st.attempts.append(attempt)
            self._store.add_attempt(sid, attempt.number, attempt.model_dump(mode="json"),
                                    keep=MAX_ATTEMPTS)
            self._save(sid, st)
        return result

    def attempts(self, owner: str, sid: str) -> AttemptList:
        with self._lock:
            st = self._get_locked(owner, sid)
            items = list(st.attempts)
        return AttemptList(items=items)


def _gateway_state(node: Any, cli: Any) -> Optional["GatewaySettings"]:
    """Réglages exposés d'un équipement, relus depuis la configuration du CLI.

    `None` pour un capteur ou un serveur : ils n'ont pas d'interface configurable, ce qui
    n'est pas la même chose que « configuré par défaut ». La fenêtre s'appuie sur cette
    distinction pour ne pas afficher de formulaire vide là où il n'y a rien à régler.
    """
    if node.kind not in CLI_NODE_KINDS:
        return None
    return GatewaySettings(
        region=cli.config.lora.region, sub_band=cli.config.lora.sub_band,
        tx_power_dbm=cli.config.lora.tx_power_dbm, mesh_mode=cli.config.mesh.mode,
        mesh_max_hops=cli.config.mesh.max_hops,
        mesh_bandwidth_khz=cli.config.mesh.bandwidth_khz)
