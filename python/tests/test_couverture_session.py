"""Couverture d'une session : relief, obstacles, antenne, paliers de qualité.

Ces tests portent sur `StudyService.coverage`, le calcul que l'atelier et la carte
consomment pour tracer une zone. Ils tiennent lieu de réponse à une question simple :
est-ce que l'environnement qu'on dessine change vraiment quelque chose ?
"""

import shutil
from pathlib import Path

import pytest

from lsim.study_session import StudyService
from lsim.study_store import StudyStore
from lsim.study_contract import (EnvironmentChoice, GatewaySettings, AntennaSettings,
                                 Node, Obstacle, SensorSettings, SessionCreate)

ROOT = Path(__file__).resolve().parents[2]
MNT = ROOT / "examples" / "relief_quartier_dem.csv"


@pytest.fixture
def relief(tmp_path):
    """Le MNT d'exemple, chargé. `None` si le fichier n'est pas livré."""
    if not MNT.is_file():
        pytest.skip("MNT d'exemple absent")
    from lsim.environment import load_dem_csv
    copie = tmp_path / "quartier.csv"
    shutil.copy(MNT, copie)
    return load_dem_csv(copie)


def chantier(tmp_path, **kwargs):
    """Une session : une passerelle à l'origine, un capteur à 600 m à l'est."""
    svc = StudyService(store=StudyStore(str(tmp_path / "db.sqlite")))
    sid = svc.create(owner="o", req=SessionCreate(nodes=[
        Node(id="gw", kind="border", name="Passerelle", x_m=0, y_m=0),
        Node(id="c1", kind="sensor", name="Capteur", x_m=600, y_m=0,
             sensor=SensorSettings(spreading_factor=10, tx_power_dbm=14.0)),
    ])).session_id
    return svc, sid


def rayons(svc, sid, terrain=None):
    """Les rayons du palier « limite », un par azimut."""
    return svc.coverage(owner="o", sid=sid, terrain=terrain).gateways[0].paliers[-1].radii_m


# ------------------------------------------------------------ ce qui compte

def test_aucun_environnement_donne_un_disque(tmp_path):
    """Sans relief ni obstacle ni antenne : la portée log-distance, identique partout."""
    svc, sid = chantier(tmp_path)
    couv = svc.coverage(owner="o", sid=sid)
    assert couv.gateways[0].modele == "log_distance"
    r = rayons(svc, sid)
    assert max(r) - min(r) < 1e-6
    assert r[0] > 0


def test_un_obstacle_creuse_la_zone_dans_sa_seule_direction(tmp_path):
    """Un mur à l'est ne raccourcit que l'est : la zone n'est plus un disque."""
    svc, sid = chantier(tmp_path)
    avant = rayons(svc, sid)
    svc.set_environment(owner="o", sid=sid, settings=EnvironmentChoice(obstacles=[
        Obstacle(x_min_m=300, y_min_m=-400, x_max_m=330, y_max_m=400, height_m=40,
                 attenuation_db=30)]))
    apres = rayons(svc, sid)
    n = len(apres)
    assert apres[0] < avant[0] * 0.2                    # est : le mur
    assert apres[n // 2] == pytest.approx(avant[n // 2], abs=1.0)   # ouest : intact
    assert svc.coverage(owner="o", sid=sid).gateways[0].modele == "environment"


def test_le_relief_agit_meme_sans_aucun_obstacle(tmp_path, relief):
    """Le bug que ce test garde : le relief était ignoré tant qu'aucun mur n'était tracé.

    `compile_session` n'émet un bloc `environment` que s'il y a des obstacles. Sans ce
    bloc, `_build_environment` n'était jamais appelé et le MNT choisi dans l'atelier ne
    changeait rien à la zone — il fallait dessiner un mur pour que le relief compte.
    Le chemin du run, lui, y pourvoyait déjà (`_build_scenario`) : la couverture était
 donc la seule vue à mentir.
    """
    svc, sid = chantier(tmp_path)
    svc.set_terrain(owner="o", sid=sid, terrain_id="quartier", known={"quartier"})
    plat = rayons(svc, sid, terrain=None)
    modele = rayons(svc, sid, terrain=relief)
    assert max(plat) - min(plat) < 1e-6          # plat : disque
    # Un relief n'est pas uniforme : certaines directions sont fermées, d'autres pas.
    assert max(modele) - min(modele) > 100.0
    assert min(modele) < max(plat) * 0.9
    assert svc.coverage(owner="o", sid=sid, terrain=relief).gateways[0].modele == "environment"


def test_relief_et_obstacle_se_composent(tmp_path, relief):
    """Les deux effets se composent — mais pas toujours dans le même sens.

    Le relief ne fait pas qu'ajouter de la perte : en soulevant le sol, il peut aussi
    hausser un capteur et lui dégager la vue par-dessus un mur. Vérifié ici : à l'est,
    le mur seul ferme à 1380 m et le même mur sur le MNT laisse passer 1700 m. Une zone
    « relief + obstacles » n'est donc pas l'intersection des deux, et un test qui
    affirmerait que le relief ne peut que réduire serait faux.
    """
    svc, sid = chantier(tmp_path)
    svc.set_terrain(owner="o", sid=sid, terrain_id="quartier", known={"quartier"})
    svc.set_environment(owner="o", sid=sid, settings=EnvironmentChoice(obstacles=[
        Obstacle(x_min_m=300, y_min_m=-400, x_max_m=330, y_max_m=400, height_m=40,
                 attenuation_db=30)]))
    mur_seul = rayons(svc, sid, terrain=None)
    les_deux = rayons(svc, sid, terrain=relief)
    assert len(mur_seul) == len(les_deux)

    # Le relief agit encore : la zone des deux n'est celle du mur seul nulle part.
    assert any(abs(a - b) > 1.0 for a, b in zip(mur_seul, les_deux))
    # Et le mur agit encore : la zone des deux n'est pas celle du relief seul.
    svc.set_environment(owner="o", sid=sid, settings=EnvironmentChoice(obstacles=[]))
    relief_seul = rayons(svc, sid, terrain=relief)
    assert any(abs(a - b) > 1.0 for a, b in zip(relief_seul, les_deux))
    # Le relief seul reste la borne haute des deux : ajouter un mur ne peut qu'aider
    # personne, même si le relief, lui, peut aider.
    n = len(les_deux)
    assert mur_seul[0] < relief_seul[0]


# ------------------------------------------------------------ paliers

def test_les_paliers_sont_ordonnes_et_distincts(tmp_path):
    """Excellent < bon < limite : une zone uniforme ne dirait pas où la liaison tient."""
    svc, sid = chantier(tmp_path)
    couv = svc.coverage(owner="o", sid=sid)
    paliers = couv.gateways[0].paliers
    assert [p.qualite for p in paliers] == ["excellent", "bon", "limite"]
    for p in paliers:
        assert len(p.radii_m) == len(paliers[0].radii_m)
    for proche, lointain in zip(paliers, paliers[1:]):
        assert proche.marge_db > lointain.marge_db
        for a, b in zip(proche.radii_m, lointain.radii_m):
            assert a < b          # plus de marge exigée, moins de portée
    # Et l'écart est net : ce ne sont pas trois copies du même rayon.
    assert max(paliers[0].radii_m) < max(paliers[-1].radii_m) * 0.9


def test_le_capteur_de_reference_est_publie(tmp_path):
    """Une zone sans son capteur de référence ne veut rien dire : le dire est obligé."""
    svc, sid = chantier(tmp_path)
    couv = svc.coverage(owner="o", sid=sid)
    assert couv.source == "capteurs"        # pris sur le capteur de la session
    assert couv.sf == 10 and couv.tx_power_dbm == 14.0

    demande = svc.coverage(owner="o", sid=sid, sf=7, tx_power_dbm=14.0)
    assert demande.source == "demande" and demande.sf == 7
    # SF7 porte moins loin que SF10 : la zone rétrécit, c'est le même réseau.
    assert max(demande.gateways[0].paliers[-1].radii_m) < max(
        couv.gateways[0].paliers[-1].radii_m)


def test_le_capteur_le_plus_defavorable_est_retenu(tmp_path):
    """Celui qui borne le réseau, pas le mieux placé."""
    svc = StudyService(store=StudyStore(str(tmp_path / "db.sqlite")))
    sid = svc.create(owner="o", req=SessionCreate(nodes=[
        Node(id="gw", kind="border", name="P", x_m=0, y_m=0),
        Node(id="proche", kind="sensor", name="Aise", x_m=100, y_m=0,
             sensor=SensorSettings(spreading_factor=7, tx_power_dbm=14.0)),
        Node(id="loin", kind="sensor", name="Pénible", x_m=900, y_m=0,
             sensor=SensorSettings(spreading_factor=12, tx_power_dbm=14.0)),
    ])).session_id
    couv = svc.coverage(owner="o", sid=sid)
    assert couv.sf == 12


# ------------------------------------------------------------ antenne et zone

def test_l_antenne_est_rappelee_dans_la_zone(tmp_path):
    """La forme de la zone s'explique par elle : la publier n'est pas superflu."""
    svc, sid = chantier(tmp_path)
    assert svc.coverage(owner="o", sid=sid).gateways[0].antenna is None
    # Secteur de 60° pointé au nord : assez étroit pour que l'écart se voie. Un secteur
    # de 120° ne pénaliserait l'est que de 0,75 dB — 6 % de portée — parce que 120°
    # couvre déjà le tiers du tour.
    svc.set_gateway(owner="o", sid=sid, node_id="gw", settings=GatewaySettings(
        antenna=AntennaSettings(kind="sectorielle", beamwidth_deg=60, pointing_deg=90)))
    zone = svc.coverage(owner="o", sid=sid).gateways[0]
    assert zone.antenna is not None
    assert zone.antenna.kind == "sectorielle"
    r = zone.paliers[-1].radii_m
    n = len(r)
    assert r[n // 4] > r[n // 2] * 2.0      # nord (axe) contre ouest (dos du lobe)


def test_annuler_l_antenne_rend_le_disque(tmp_path):
    svc, sid = chantier(tmp_path)
    avant = rayons(svc, sid)
    svc.set_gateway(owner="o", sid=sid, node_id="gw", settings=GatewaySettings(
        antenna=AntennaSettings(kind="unidirectionnelle", beamwidth_deg=60, pointing_deg=0)))
    assert max(rayons(svc, sid)) - min(rayons(svc, sid)) > 100.0
    svc.undo(owner="o", sid=sid)
    apres = rayons(svc, sid)
    for a, b in zip(avant, apres):
        assert a == pytest.approx(b, abs=1e-6)


def test_un_capteur_ne_se_decouvre_pas_d_antenne(tmp_path):
    svc = StudyService(store=StudyStore(str(tmp_path / "db.sqlite")))
    with pytest.raises(Exception):
        svc.create(owner="o", req=SessionCreate(nodes=[
            Node(id="c", kind="sensor", name="C", x_m=0, y_m=0,
                 antenna=AntennaSettings(kind="sectorielle"))]))
