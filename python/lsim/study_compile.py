"""Compilation d'une session du panneau d'étude en scénario de simulation (`docs/STUDY_PANEL_SPEC.md` §7).

Entrées : les équipements de la session (topologie) et la configuration CLI de chaque passerelle.
Sortie : le corps d'un `POST /api/v1/runs` (un scénario validé ensuite par le moteur), les liaisons
à appliquer au résultat, et des notes (défauts appliqués, réglages non modélisés).

Règles :
- une passerelle est un `border` (backhaul IP) ou un `relay` (mesh sans IP) ; chaque capteur est un
  groupe de simulation nommé comme lui, avec ses réglages `sensor` ;
- une passerelle dont l'interface `lora` est arrêtée n'entre pas dans le run ; un relais dont
  l'interface `mesh` est arrêtée reste une passerelle d'accès ordinaire ;
- avec des relais actifs, il faut exactement une frontière active, dont l'interface mesh est
  active ; les réglages mesh (SF, bande, sauts) sont ceux de la frontière et des relais ; deux
  valeurs réglées et différentes sont refusées, les sauts prennent la plus petite valeur réglée ;
- le plan régional et la sous-bande sont ceux des passerelles (identiques pour toutes) ; un capteur
  qui en déclare un autre est refusé ; un plan non réglé vaut EU868 (et une sous-bande non réglée
  vaut 1 sur US915 / AU915), avec une note ;
- un réglage du type `mode` qui ne correspond pas au rôle est refusé.

Le compilateur est pur : il ne lit ni n'écrit d'état, et les validations du moteur (scénario,
charge descendante sur le mesh) restent à la création du run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from lsim.channel_mask import sub_band_channels
from lsim.energy import profile as energy_profile_by_name
from lsim.energy_report import ENERGY_PROFILES
from lsim.gateway_profiles import get_profile, software_status
from lsim.plan import get_plan
from lsim.study_cli import SUB_BAND_REGIONS, GatewayConfig
from lsim.study_contract import EnvironmentSettings, Node, SensorSettings

DEFAULT_REGION = "EU868"
DEFAULT_SUB_BAND = 1
MESH_PROFILE = "rak5146-rak5148"  # relais : accès sous-GHz + lien mesh 2,4 GHz (gateway_profiles)
MESH_DEFAULTS = {"spreading_factor": 9, "bandwidth_khz": 203, "max_hops": 8}   # défauts de MeshModel
# Profil d'énergie des capteurs. Sans lui, le scénario ne calcule aucune énergie et le courant
# moyen reste à `None` : la mesure existe dans le moteur mais n'était jamais demandée. Le choix
# du matériel est un choix de modélisation, il est donc déclaré dans les notes plutôt que tu.
ENERGY_PROFILE = "rak4631"

NOT_MODELLED = ("puissance d'émission des passerelles d'accès", "sensibilité des récepteurs : décalage uniforme "
                "par profil en réception montante (decalage-uniforme-v1, non calibré), descente et mesh inchangés",
                "fréquence réglée sur les passerelles",
                "interface Ethernet", "serveur réseau (le LNS est implicite derrière la frontière)")


class CompileError(Exception):
    def __init__(self, message: str, field_name: str = "nodes") -> None:
        super().__init__(message)
        self.message, self.field = message, field_name


@dataclass(frozen=True)
class Compiled:
    body: dict                      # corps de POST /api/v1/runs
    links: list                    # [{"node_id": ..., "gateway": ...}] : une par passerelle du run
    notes: list[str] = field(default_factory=list)


def _default_channel(region: str, sub_band: Optional[int]) -> int:
    channels = get_plan(region).uplink_channels_hz()
    if sub_band is None:
        return channels[0]
    return channels[min(sub_band_channels(sub_band))]


def adr_possible(nodes: list[Node], configs: dict[str, GatewayConfig]) -> tuple[bool, str]:
    """L'ADR peut-il être simulé sur cette session ? Et sinon, pourquoi.

    Le couple (booléen, raison) est renvoyé tel quel à l'atelier : un réglage grisé sans
    explication est le genre de silence qui fait perdre une heure — la leçon du §1, où la
    sous-bande désactivée dit pourquoi elle l'est.

    Les trois conditions ne sont pas des précautions, ce sont des refus du schéma ou du moteur,
    chacun vérifié par exécution :
      - plusieurs passerelles : `mac.link_adr` est refusé (scenario.py) ;
      - un relais : la boucle fermée porte un seul `GatewayLoad`, le mesh est exclu ;
      - aucun plan régional : `mac_loop.py` lève « LinkADR exige un plan régional ».
    """
    gateways = [n for n in nodes if n.kind in ("relay", "border")]
    actives = [n for n in gateways if not configs[n.id].lora.shutdown]
    # Le relais est nommé d'abord : un relais **est** une passerelle pour le moteur, donc le
    # contrôle de comptage l'attraperait aussi — mais « 2 passerelles actives » laisserait
    # l'utilisateur chercher une seconde frontière qu'il n'a pas posée.
    relays = [n for n in actives if n.kind == "relay"]
    if relays:
        return False, ("l'ADR n'est pas simulé sur un réseau à relais "
                       f"({', '.join(n.id for n in relays)})")
    if len(actives) != 1:
        return False, (f"l'ADR n'est simulé qu'à passerelle unique "
                       f"({len(actives)} passerelles actives ici)")
    if configs[actives[0].id].lora.region is None:
        return False, "l'ADR exige un plan régional : réglez-le sur la passerelle"
    return True, ""



def join_possible(nodes: list[Node], configs: dict[str, GatewayConfig],
                  adr: bool) -> tuple[bool, str]:
    """La jointure OTAA peut-elle être simulée sur cette session ? Et sinon, pourquoi.

    Une seule condition, et elle est un refus du moteur, vérifié par exécution : la boucle
    fermée (ADR) lève « jointure non supportée » dans `mac_loop.check_closed_loop`. Les deux
    réglages s'excluent donc, et le dire avant le run évite un échec incompréhensible.

    `nodes` et `configs` sont pris pour garder la même signature que `adr_possible` : la
    jointure n'a aujourd'hui aucune condition de topologie, mais une nuit de réflexion sur
    le relais pourrait en ajouter une, et l'appelant n'aurait rien à changer.
    """
    if adr:
        return False, "la jointure et l'ADR s'excluent : le moteur refuse de simuler les deux"
    return True, ""


def confirmed_possible(nodes: list[Node], configs: dict[str, GatewayConfig],
                       adr: bool) -> tuple[bool, str]:
    """Les trames confirmées peuvent-elles être simulées ? Et sinon, pourquoi.

    Aucune condition aujourd'hui : le moteur accepte le couple avec l'ADR (mesuré : 120
    uplinks, 120 ACK et 3 LinkADRReq sur le même run). La fonction existe pour que l'atelier
    interroge les trois réglages de la même façon, plutôt que d'en câbler deux en dur et le
    troisième avec une raison.
    """
    return True, ""


def _bloc_environment(env: EnvironmentSettings) -> Optional[dict]:
    """Le bloc `environment` du scénario, ou `None` si l'utilisateur n'a rien réglé.

    `None` et non un bloc aux valeurs par défaut : un scénario compilé sans environnement est
    **le même fichier** qu'avant cette fonctionnalité, donc la même empreinte. C'est la règle
    qui tient depuis le début — un scénario écrit avant garde ses chiffres et son empreinte.
    """
    if env.est_vierge():
        return None
    obstacles = []
    for o in env.obstacles:
        bloc = {"x_min_m": o.x_min_m, "y_min_m": o.y_min_m,
                "x_max_m": o.x_max_m, "y_max_m": o.y_max_m,
                "height_m": o.height_m}
        if o.material is not None:
            bloc["material"] = o.material
            bloc["thickness_m"] = o.thickness_m
        else:
            bloc["attenuation_db"] = o.attenuation_db
        obstacles.append(bloc)
    return {"gateway_height_m": env.gateway_height_m,
            "device_height_m": env.device_height_m,
            "obstacles": obstacles}


def compile_session(nodes: list[Node], configs: dict[str, GatewayConfig], seed: int,
                    terrain_id: Optional[str] = None, adr: bool = False,
                    join: bool = False, confirmed: bool = False,
                    environment: Optional[EnvironmentSettings] = None) -> Compiled:
    """Compile la session en scénario.

    `adr` : la boucle fermée (LinkADRReq) est demandée. Elle n'existe qu'à passerelle unique,
    sans mesh et avec un plan régional ; le scénario prend alors la forme `gateway` au lieu de
    `gateways`, seule forme que le schéma accepte avec `mac`. Voir `adr_possible` pour les
    conditions et leurs raisons — elles sont affichées telles quelles dans l'atelier.

    `join` : jointure OTAA. Le premier message de chaque dispositif devient un join-request,
    au lieu d'un uplink de données ; le moteur répond d'un join-accept. Exclu par l'ADR.

    `confirmed` : uplinks de données confirmés, chacun attendant un ACK.

    Les trois passent par `protocol` du corps de run, et non par le scénario : le moteur les
    applique à tous les dispositifs du run, ou à aucun.

    `environment` : obstacles, shadowing et hauteurs d'antennes. Il entre dans le **scénario**
    (contrairement aux trois précédents) et seulement s'il a été réglé — voir
    `_bloc_environment`.
    """
    notes: list[str] = []
    gateways = [n for n in nodes if n.kind in ("relay", "border")]
    sensors = [n for n in nodes if n.kind == "sensor"]
    if not gateways:
        raise CompileError("aucune passerelle dans la session : ajoutez une frontière (border)")
    if not sensors:
        raise CompileError("aucun capteur dans la session : ajoutez au moins un capteur")

    for n in gateways:
        mode = configs[n.id].mesh.mode
        if mode is not None and mode != n.kind:
            raise CompileError(f"{n.id} : mode mesh « {mode} » ne correspond pas au rôle {n.kind}")

    borders = [n for n in gateways if n.kind == "border"]
    relays = [n for n in gateways if n.kind == "relay"]
    active = [n for n in gateways if not configs[n.id].lora.shutdown]
    mesh_relays = [n for n in relays if n in active and not configs[n.id].mesh.shutdown]
    mesh_nodes: list[Node] = []
    border: Optional[Node] = None
    if mesh_relays:
        if len(borders) != 1:
            raise CompileError("un réseau mesh exige exactement une frontière (border)")
        border = borders[0]
        if border not in active:
            raise CompileError(f"{border.id} : frontière arrêtée (interface lora) alors que des relais "
                               "sont actifs")
        if configs[border.id].mesh.shutdown:
            raise CompileError(f"{border.id} : interface mesh arrêtée alors que des relais sont actifs")
        mesh_nodes = [border] + mesh_relays
    if not active:
        raise CompileError("toutes les passerelles sont arrêtées")

    # Plan régional et sous-bande : identiques pour toutes les passerelles d'accès.
    regions: dict[str, str] = {}
    for n in active:
        region = configs[n.id].lora.region
        if region is None:
            region = DEFAULT_REGION
            notes.append(f"{n.id} : plan non réglé, {DEFAULT_REGION} appliqué")
        regions[n.id] = region
    if len(set(regions.values())) > 1:
        detail = ", ".join(f"{k} {v}" for k, v in regions.items())
        raise CompileError(f"plans régionaux différents sur les passerelles ({detail})")
    region = next(iter(regions.values()))

    sub_band: Optional[int] = None
    if region in SUB_BAND_REGIONS:
        bands = {configs[n.id].lora.sub_band for n in active}
        if len(bands) > 1:
            raise CompileError("sous-bandes différentes sur les passerelles")
        sub_band = next(iter(bands))
        if sub_band is None:
            sub_band = DEFAULT_SUB_BAND
            notes.append(f"sous-bande non réglée, {DEFAULT_SUB_BAND} appliquée")

    scenario_gateways = []
    for n in active:
        cfg = configs[n.id]
        gw = {"name": n.id, "x_m": n.x_m, "y_m": n.y_m,
              "antenna_gain_dbi": cfg.lora.antenna_gain_dbi or 0.0}
        if n in mesh_nodes:
            # Le modèle du relais : celui de l'équipement s'il est choisi, sinon la valeur
            # historique. Le scénario refuse de lui-même un modèle sans radio mesh
            # documentée — le refus Remonte tel quel, avec le nom du modèle fautif.
            gw["profile"] = n.gateway_profile or MESH_PROFILE
            gw["mesh"] = True
        elif n.gateway_profile is not None:
            # Passerelle d'accès : le modèle décale le seuil de réception de la différence
            # entre la sensibilité publiée et la référence du moteur au même point.
            gw["profile"] = n.gateway_profile
        scenario_gateways.append(gw)

    # L'ADR n'existe que sur la forme `gateway` (une seule passerelle, sans mesh). On ne
    # bascule que s'il est demandé **et** possible : la forme `gateways` reste le défaut, parce
    # qu'elle porte le relais et la matrice des réceptions du §3. Changer de forme n'est pas
    # un détail de sérialisation, c'est changer ce que le run peut simuler.
    forme_mono = False
    if adr:
        ok, raison = adr_possible(nodes, configs)
        if not ok:
            raise CompileError(f"ADR refusé : {raison}", "adr")
        forme_mono = True

    mesh_block = None
    if mesh_nodes:
        values = {key: {} for key in MESH_DEFAULTS}
        for n in mesh_nodes:
            m = configs[n.id].mesh
            if m.spreading_factor is not None:
                values["spreading_factor"][n.id] = m.spreading_factor
            if m.bandwidth_khz is not None:
                values["bandwidth_khz"][n.id] = int(m.bandwidth_khz)
            if m.max_hops is not None:
                values["max_hops"][n.id] = m.max_hops
        for key, label in (("spreading_factor", "SF mesh"), ("bandwidth_khz", "bande mesh")):
            distinct = set(values[key].values())
            if len(distinct) > 1:
                raise CompileError(f"{label} différent entre la frontière et les relais")
        mesh_block = {
            "border": border.id,
            "spreading_factor": next(iter(values["spreading_factor"].values()),
                                     MESH_DEFAULTS["spreading_factor"]),
            "bandwidth_khz": next(iter(values["bandwidth_khz"].values()),
                                  MESH_DEFAULTS["bandwidth_khz"]),
            "max_hops": min(values["max_hops"].values(), default=MESH_DEFAULTS["max_hops"]),
        }

    groups = []
    for s in sensors:
        r = s.sensor or SensorSettings()
        if r.region is not None and r.region != region:
            raise CompileError(f"{s.id} : plan {r.region} ≠ plan des passerelles ({region})")
        channel = r.channel_freq_hz or _default_channel(region, sub_band)
        group = {
            "name": s.id,
            "placement": {"type": "explicit", "positions": [[s.x_m, s.y_m]]},
            "spreading_factor": r.spreading_factor,
            "payload_bytes": r.payload_bytes,
            "tx_power_dbm": r.tx_power_dbm,
            "period_s": r.period_s,
            "messages": r.messages,
            "start_spread_s": r.start_spread_s,
            "region": region,
            "channel_freq_hz": channel,
        }
        if sub_band is not None:
            group["sub_band"] = sub_band
        # Modèle de matériel : posé seulement s'il est choisi. Sans lui, le groupe ne porte
        # rien et le profil du run s'applique — ce qui garde à un chantier antérieur ses
        # chiffres et son empreinte.
        if r.energy_profile is not None:
            group["energy"] = {"profile": r.energy_profile}
        groups.append(group)

    scenario: dict = {
        "schema_version": 1,
        "name": "Session d'étude",
        "seed": seed,
        "groups": groups,
    }
    if forme_mono:
        # Une seule passerelle, sans mesh : la forme que `mac` accepte. Le nom, le profil et
        # l'indicateur mesh sont retirés, non pas par coquetterie mais parce que le schéma les
        # refuse sur `gateway` (« nom, profil et mesh exigent gateways »).
        seule = scenario_gateways[0]
        scenario["gateway"] = {"x_m": seule["x_m"], "y_m": seule["y_m"],
                               "antenna_gain_dbi": seule["antenna_gain_dbi"]}
        scenario["mac"] = {"link_adr": True}
        notes.append("ADR du serveur activé : ce run ne simule ni relais ni liaisons radio "
                     "par couple (une seule passerelle)")
    else:
        scenario["gateways"] = scenario_gateways
    if mesh_block is not None:
        scenario["mesh"] = mesh_block
    if mesh_nodes:
        retenus = {(n.gateway_profile or MESH_PROFILE) for n in mesh_nodes}
        for cle in sorted(retenus):
            prof = get_profile(cle)
            if not prof.software_validated:
                notes.append(f"relais : profil {cle} ({software_status(prof)}) : compatibilité "
                             "logicielle non confirmée (essai ChirpStack Gateway OS ou confirmation RAK)")
    notes.append("non modélisés (ignorés) : " + ", ".join(NOT_MODELLED))
    # Le matériel du run, puis ceux qui s'en écartent : depuis qu'un capteur peut porter le
    # sien, annoncer seulement le profil du run décrit un run qui n'est plus le sien. Les
    # écarts sont nommés — un courant moyen se vérifie en sachant de quel matériel il vient.
    nom = energy_profile_by_name(ENERGY_PROFILES[ENERGY_PROFILE]).name
    propres = [(s.id, (s.sensor.energy_profile if s.sensor else None)) for s in sensors]
    propres = [(sid, p) for sid, p in propres if p is not None and p != ENERGY_PROFILE]
    note = (f"énergie des capteurs : profil {ENERGY_PROFILE} ({nom}) — le courant "
            "moyen est celui de ce matériel")
    if propres:
        noms = ", ".join(f"{sid} : {p} ({energy_profile_by_name(ENERGY_PROFILES[p]).name})"
                         for sid, p in propres)
        note += f" ; matériel propre à {noms}"
    notes.append(note)
    links = [{"node_id": n.id, "gateway": n.id} for n in active]
    # Le protocole effectif, pas le protocole demandé : une jointure demandée alors que l'ADR
    # est actif ne serait pas simulée, et l'écrire dans le corps laisserait croire à un run
    # qui joint. La raison, elle, est portée par `SessionTopology` et affichée avant le run.
    protocole = {}
    if join and join_possible(nodes, configs, adr)[0]:
        protocole["join"] = True
    if confirmed and confirmed_possible(nodes, configs, adr)[0]:
        protocole["confirmed_uplinks"] = True
    body: dict = {"scenario": scenario, "protocol": protocole,
                  "energy_profile": ENERGY_PROFILE}
    # L'environnement radio, de même : absent tant que rien n'a été réglé. Le shadowing
    # n'appartient pas au bloc `environment` mais à `propagation`, et n'est émis que s'il est
    # non nul — la clé absente, c'est le comportement d'avant.
    if environment is not None and not environment.est_vierge():
        scenario["environment"] = _bloc_environment(environment)
        if environment.shadowing_sigma_db > 0.0:
            scenario["propagation"] = {"shadowing_sigma_db": environment.shadowing_sigma_db}
        notes.append(
            f"environnement : {len(environment.obstacles)} obstacle(s), "
            f"shadowing sigma {environment.shadowing_sigma_db:g} dB, "
            f"antennes {environment.device_height_m:g} m / {environment.gateway_height_m:g} m "
            "— matériaux UIT-R P.2040-4, tirage log-normal par dispositif")
    # Le relief n'entre dans le corps que s'il a ete choisi : une cle absente et une cle a
    # `null` n'ont pas le meme sens cote serveur, et seul le choix doit se voir.
    if terrain_id is not None:
        body["terrain_id"] = terrain_id
    return Compiled(body=body, links=links, notes=notes)

