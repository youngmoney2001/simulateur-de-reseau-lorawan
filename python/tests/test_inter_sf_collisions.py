"""Collisions entre SF différents : option `propagation.inter_sf`.

Le moteur traitait les spreading factors comme parfaitement orthogonaux : deux trames de SF
différents qui se chevauchent ne se gênaient jamais. C'est faux d'un vrai récepteur, et c'est
une limite que le manuel annonçait. `inter_sf: sx1276` comble le manque, `orthogonal`
(défaut) conserve le comportement d'origine — y compris l'empreinte des scénarios écrits avant.

Le seuil vient de la table « LoRa Demodulator SNR » du SX1276 (datasheet Rev. 4), celle-là
même qui sert déjà à l'ADR et à la sensibilité. Ce n'est **pas** une matrice d'isolement
mesurée entre deux SF : une telle matrice viendrait d'une campagne de mesures, et le seuil ne
dépend ici que du SF de la trame voulue. C'est l'approximation de la littérature, et les tests
le vérifient **par l'effet produit** — jamais en recopiant la table.

Aucun `parametrize` : chaque cas est une fonction nommée.
"""

import pathlib
import tempfile

import pytest

from lsim.radio import LogDistanceModel
from lsim.simulator import EndDevice, Gateway, Propagation, TxRecord, simulate_uplinks_trace

RECU = TxRecord.OUTCOME_RECEIVED
COLLISION = TxRecord.OUTCOME_LOST_COLLISION


def _propagation(inter_sf: str = "orthogonal") -> Propagation:
    """Propagation de référence : EU868, 868,1 MHz, d0 = 1 m, exposant 2,7."""
    return Propagation(frequency_hz=868.1e6, reference_distance_m=1.0, exponent=2.7,
                       inter_sf=inter_sf)


def _trames(d_a: float, d_b: float, sf_a: int, sf_b: int, inter_sf: str) -> list:
    """Deux trames émises au même instant, aux distances et SF donnés."""
    devices = [
        EndDevice(x_m=d_a, y_m=0.0, spreading_factor=sf_a, payload_bytes=10,
                  tx_power_dbm=14.0, period_ns=3600 * 10**9, messages=1),
        EndDevice(x_m=d_b, y_m=0.0, spreading_factor=sf_b, payload_bytes=10,
                  tx_power_dbm=14.0, period_ns=3600 * 10**9, messages=1),
    ]
    resultat = simulate_uplinks_trace(devices, Gateway(x_m=0.0, y_m=0.0),
                                      _propagation(inter_sf))
    return sorted(resultat.records, key=lambda r: r.device_index)


def _par_sf(records) -> dict:
    """Issue par SF. Réservé aux cas où les deux SF diffèrent (sinon la clé écrase)."""
    return {r.spreading_factor: r.outcome for r in records}


def _ecart_db(d_proche: float, d_lointaine: float) -> float:
    """De combien la trame proche est reçue plus fort que la lointaine (dB).

    Le modèle doit être **celui du run** (log-distance, exposant 2,7), pas l'espace
    libre : avec un exposant 2 l'écart 200/1600 m vaudrait 18,1 dB au lieu de 24,4, et
    le test croirait mesurer un seuil alors qu'il mesure une autre propagation.
    """
    modele = LogDistanceModel(frequency_hz=868.1e6, reference_distance_m=1.0, exponent=2.7)
    return modele.path_loss_db(d_lointaine) - modele.path_loss_db(d_proche)


def _scenario_avec(cle_propagation: str) -> str:
    return """schema_version: 1
name: inter-sf
seed: 3
gateway:
  x_m: 0
  y_m: 0
propagation:
  exponent: 2.7
""" + cle_propagation + """groups:
  - name: g
    count: 2
    placement:
      type: disk
      radius_m: 400
    spreading_factor: 9
    payload_bytes: 10
    period_s: 600
    messages: 2
"""


# --- Comportement historique -------------------------------------------------------------------

def test_deux_sf_differents_ne_collisionnent_pas_par_defaut():
    """Orthogonalité parfaite : c'est le comportement d'origine, il doit rester."""
    outcomes = _par_sf(_trames(200.0, 1600.0, 7, 12, "orthogonal"))
    assert outcomes == {7: RECU, 12: RECU}


def test_orthogonal_explicite_egale_absence_de_la_cle():
    """Écrire `inter_sf: orthogonal` ne change rien — ni chiffres ni empreinte.

    C'est la garantie qu'un scénario écrit avant l'introduction de l'option garde
    exactement son empreinte : la clé quitte le hachage quand elle vaut le défaut.
    """
    from lsim.scenario import load_scenario

    with tempfile.TemporaryDirectory() as d:
        sans = pathlib.Path(d) / "sans.yaml"
        avec = pathlib.Path(d) / "avec.yaml"
        sans.write_text(_scenario_avec(""), encoding="utf-8")
        avec.write_text(_scenario_avec("  inter_sf: orthogonal\n"), encoding="utf-8")
        s_sans = load_scenario(str(sans))
        s_avec = load_scenario(str(avec))
        assert s_sans.sha256 == s_avec.sha256
        assert s_sans.propagation().inter_sf == "orthogonal"


def test_activer_l_option_change_l_empreinte():
    """Deux modèles différents ne peuvent pas partager une empreinte."""
    from lsim.scenario import load_scenario

    with tempfile.TemporaryDirectory() as d:
        empreintes = {}
        for regle in ("orthogonal", "sx1276"):
            p = pathlib.Path(d) / f"{regle}.yaml"
            p.write_text(_scenario_avec(f"  inter_sf: {regle}\n"), encoding="utf-8")
            empreintes[regle] = load_scenario(str(p)).sha256
        assert empreintes["orthogonal"] != empreintes["sx1276"]


# --- Seuil : l'effet, pas la table -------------------------------------------------------------

def test_interferent_au_dela_du_seuil_fait_tomber_la_trame_lointaine():
    """SF7 proche, SF12 lointain : 24,4 dB d'écart, au-delà de ce que tolère le SF12."""
    ecart = _ecart_db(200.0, 1600.0)
    assert ecart > 20.0, f"écart attendu > 20 dB, mesuré {ecart:.1f}"
    outcomes = _par_sf(_trames(200.0, 1600.0, 7, 12, "sx1276"))
    assert outcomes[12] == COLLISION, "le SF12 lointain doit céder"
    assert outcomes[7] == RECU, "le SF7 proche n'est pas gêné par un signal plus faible"


def test_interferent_sous_le_seuil_laisse_passer_la_trame():
    """Même configuration, écart ramené sous le seuil : plus rien ne tombe.

    Sans ce test, on ne saurait pas si l'option est un seuil ou une interdiction pure et
    simple de tout SF différent.
    """
    ecart = _ecart_db(200.0, 1000.0)
    assert 0.0 < ecart < 20.0, f"écart attendu sous 20 dB, mesuré {ecart:.1f}"
    outcomes = _par_sf(_trames(200.0, 1000.0, 7, 12, "sx1276"))
    assert outcomes == {7: RECU, 12: RECU}


def test_le_seuil_depend_du_sf_voulu_et_pas_de_l_interferent():
    """Même géométrie, même puissances, seuls les SF permutés : le verdict change.

    L'interférent est reçu 12 dB au-dessus de la trame voulue. Le SF12 le tolère (il
    supporte 20 dB), le SF7 non (7,5 dB). C'est la propriété que le seuil dépend du SF
    **voulu** — vérifiée sur l'effet, sans jamais recopier la table.
    """
    ecart = _ecart_db(200.0, 556.0)
    assert 7.5 < ecart < 20.0, f"écart attendu entre 7,5 et 20 dB, mesuré {ecart:.1f}"

    # Voulu SF12 (lointain), interférent SF7 (proche) : toléré.
    douze = _par_sf(_trames(200.0, 556.0, 7, 12, "sx1276"))
    assert douze[12] == RECU, "un SF12 supporte un interférent 12 dB au-dessus"
    assert douze[7] == RECU

    # Voulu SF7 (lointain), interférent SF12 (proche) : refusé.
    sept = _par_sf(_trames(200.0, 556.0, 12, 7, "sx1276"))
    assert sept[7] == COLLISION, "un SF7 ne supporte pas 12 dB"
    assert sept[12] == RECU


def test_meme_sf_garde_le_seuil_de_capture():
    """Entre deux trames de même SF, c'est toujours le seuil de capture (6 dB) qui décide."""
    ecart = _ecart_db(200.0, 280.0)
    assert 0.0 < ecart < 6.0, f"écart attendu sous 6 dB, mesuré {ecart:.1f}"
    records = _trames(200.0, 280.0, 7, 7, "sx1276")
    assert len(records) == 2
    assert all(r.outcome == COLLISION for r in records), (
        "sous le seuil de capture, aucune des deux ne passe")


# --- Validation --------------------------------------------------------------------------------

def test_valeur_inconnue_est_refusee():
    """Un scénario est validé strictement : une faute de frappe est signalée, pas absorbée."""
    with pytest.raises(ValueError):
        _propagation("mesure")


def test_defaut_est_orthogonal():
    assert Propagation().inter_sf == "orthogonal"


def test_multi_passerelles_applique_le_meme_seuil():
    """Le chemin multi-passerelles a sa propre boucle de collision : il doit suivre.

    Deux boucles indépendantes dans le moteur décident des collisions (mono- et
    multi-passerelles). Un correctif appliqué à une seule laisserait un scénario
    changer de verdict selon le nombre de passerelles — divergence d'autant plus
    sournoise qu'aucun test ne la verrait.
    """
    from lsim.export import run_scenario
    from lsim.scenario import load_scenario

    modele = """schema_version: 1
name: multi inter-sf
seed: 5
gateways:
  - name: ouest
    x_m: -400
    y_m: 0
  - name: est
    x_m: 400
    y_m: 0
propagation:
  exponent: 2.7
  shadowing_sigma_db: 0.0
  inter_sf: {regle}
groups:
  - name: proche-sf7
    count: 1
    placement:
      type: disk
      radius_m: 150
      center_x_m: 150
      center_y_m: 0
    spreading_factor: 7
    payload_bytes: 10
    tx_power_dbm: 14.0
    period_s: 3600
    messages: 1
  - name: lointain-sf12
    count: 1
    placement:
      type: disk
      radius_m: 1500
      center_x_m: 1500
      center_y_m: 0
    spreading_factor: 12
    payload_bytes: 10
    tx_power_dbm: 14.0
    period_s: 3600
    messages: 1
"""
    with tempfile.TemporaryDirectory() as d:
        resultats = {}
        for regle in ("orthogonal", "sx1276"):
            p = pathlib.Path(d) / f"{regle}.yaml"
            p.write_text(modele.format(regle=regle), encoding="utf-8")
            r = run_scenario(load_scenario(str(p)))
            resultats[regle] = (r.totals.received, [g.received for g in r.gateway_loads])

    (recues_ortho, par_gw_ortho) = resultats["orthogonal"]
    (recues_sx, par_gw_sx) = resultats["sx1276"]

    assert recues_ortho == 2, "en orthogonalité parfaite, les deux trames passent"
    assert recues_sx == 1, "la trame lointaine SF12 cède devant le SF7 proche"
    # Les deux passerelles voient la même chose : le seuil est appliqué partout.
    assert len(par_gw_sx) == 2
    assert par_gw_sx == [1, 1], f"attendu [1, 1], obtenu {par_gw_sx}"
    assert par_gw_ortho == [2, 2]
