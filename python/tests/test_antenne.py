"""Antennes : diagramme de rayonnement et couverture directionnelle.

Le moteur ne connaissait qu'un gain scalaire ; toute antenne couvrait donc un
disque. Ces tests vérifient que le lobe se voit sur la zone, et qu'il ne fait
que retirer de la portée — jamais en ajouter.
"""

import math

import pytest

from lsim.environment import Environment, Obstacle
from lsim.simulator import (AntennaKind, AntennaPattern, Gateway, Propagation,
                            coverage_radii)

F = 868.1e6


def _prop() -> Propagation:
    return Propagation(frequency_hz=F, reference_distance_m=1.0, exponent=2.7)


def _flat_radii(mapl: float = 130.0, azimuths: int = 72):
    """Portée par azimut en terrain plat : le relief ne perturbe pas la comparaison."""
    return coverage_radii(Gateway(), _prop(), mapl, None, 50.0, azimuths)


def _at(radii: tuple[float, ...], azimuth_deg: float) -> float:
    """Portée dans une direction, pour un échantillonnage à 72 azimuts (pas de 5°)."""
    k = round(azimuth_deg / 5.0) % len(radii)
    return radii[k]


# ------------------------------------------------------------ diagramme

def test_omnidirectional_is_a_circle():
    a = AntennaPattern(AntennaKind.OMNIDIRECTIONAL, 3.0, 90.0, 0.0, 20.0)
    for az in range(0, 360, 11):
        assert a.gain_offset_db(az) == pytest.approx(0.0, abs=1e-9)
        assert a.gain_dbi(az) == pytest.approx(3.0, abs=1e-9)


def test_omnidirectional_ignores_beamwidth_and_back_lobe():
    """Une omni n'a pas à renseigner des réglages sans effet.

    La refuser sous prétexte qu'un champ inutile est hors bornes serait un piège
    pour l'appelant.
    """
    a = AntennaPattern(AntennaKind.OMNIDIRECTIONAL, 3.0, 1.0, 0.0, 999.0)
    assert a.gain_dbi(37.0) == pytest.approx(3.0, abs=1e-9)


def test_minus_3db_at_half_beamwidth():
    """La convention qui fixe la pente du modèle (12 × 0,25 = 3)."""
    for w in (30.0, 60.0, 90.0, 120.0):
        a = AntennaPattern(AntennaKind.UNIDIRECTIONAL, 0.0, w, 0.0, 60.0)
        assert a.gain_offset_db(0.5 * w) == pytest.approx(-3.0, abs=1e-9)
        assert a.gain_offset_db(-0.5 * w) == pytest.approx(-3.0, abs=1e-9)
        assert a.gain_offset_db(w) == pytest.approx(-12.0, abs=1e-9)


def test_rear_attenuation_is_a_floor():
    a = AntennaPattern(AntennaKind.UNIDIRECTIONAL, 0.0, 60.0, 0.0, 20.0)
    assert a.gain_offset_db(180.0) == pytest.approx(-20.0, abs=1e-9)
    # 90° vaudrait 27 dB sans le plancher : c'est bien lui qui écrête.
    assert a.gain_offset_db(90.0) == pytest.approx(-20.0, abs=1e-9)
    b = AntennaPattern(AntennaKind.UNIDIRECTIONAL, 0.0, 60.0, 0.0, 45.0)
    assert b.gain_offset_db(90.0) == pytest.approx(-27.0, abs=1e-9)


def test_bidirectional_has_two_opposite_lobes():
    a = AntennaPattern(AntennaKind.BIDIRECTIONAL, 0.0, 60.0, 0.0, 30.0)
    assert a.gain_offset_db(0.0) == pytest.approx(0.0, abs=1e-9)
    # Le dos est un axe, pas un plancher.
    assert a.gain_offset_db(180.0) == pytest.approx(0.0, abs=1e-9)
    # Le creux est à 90°, le point le plus éloigné des deux axes.
    assert a.gain_offset_db(90.0) == pytest.approx(-27.0, abs=1e-9)
    assert a.gain_offset_db(270.0) == pytest.approx(-27.0, abs=1e-9)
    for az in range(0, 180, 7):
        assert a.gain_offset_db(az) == pytest.approx(a.gain_offset_db(az + 180.0), abs=1e-9)


def test_sector_has_a_flat_top():
    """Tout le secteur annoncé est servi au gain maximal, contrairement à une directive."""
    s = AntennaPattern(AntennaKind.SECTOR, 0.0, 120.0, 0.0, 30.0)
    for az in range(-60, 61, 5):
        assert s.gain_offset_db(az) == pytest.approx(0.0, abs=1e-9)
    # Au-delà du bord, la courbe retombe à −3 dB un demi-secteur plus loin.
    assert s.gain_offset_db(120.0) == pytest.approx(-3.0, abs=1e-9)

    u = AntennaPattern(AntennaKind.UNIDIRECTIONAL, 0.0, 120.0, 0.0, 30.0)
    assert u.gain_offset_db(60.0) == pytest.approx(-3.0, abs=1e-9)
    assert s.gain_offset_db(60.0) > u.gain_offset_db(60.0) + 2.9


def test_the_three_usual_sector_widths():
    for w in (60.0, 90.0, 120.0):
        s = AntennaPattern(AntennaKind.SECTOR, 0.0, w, 0.0, 30.0)
        assert s.gain_offset_db(0.5 * w) == pytest.approx(0.0, abs=1e-9)   # bord : au sommet
        assert s.gain_offset_db(w) == pytest.approx(-3.0, abs=1e-9)
        # Le secteur sert une part du tour d'autant plus grande qu'il est large.
        assert math.pow(10.0, s.gain_offset_db(w / 4.0) / 10.0) == pytest.approx(1.0, abs=1e-9)


def test_azimuth_wraps_around():
    a = AntennaPattern(AntennaKind.UNIDIRECTIONAL, 0.0, 90.0, 30.0, 25.0)
    for az in range(0, 360, 13):
        assert a.gain_offset_db(az) == pytest.approx(a.gain_offset_db(az + 360.0), abs=1e-9)
        assert a.gain_offset_db(az) == pytest.approx(a.gain_offset_db(az - 720.0), abs=1e-9)
    # Pointage ramené lui aussi : 370° vaut 10°.
    p = AntennaPattern(AntennaKind.UNIDIRECTIONAL, 0.0, 90.0, 370.0, 25.0)
    q = AntennaPattern(AntennaKind.UNIDIRECTIONAL, 0.0, 90.0, 10.0, 25.0)
    for az in range(0, 360, 17):
        assert p.gain_offset_db(az) == pytest.approx(q.gain_offset_db(az), abs=1e-9)


def test_gain_never_exceeds_the_peak():
    for kind in AntennaKind:
        a = AntennaPattern(kind, 0.0, 45.0, 0.0, 20.0)
        for az in range(0, 360, 3):
            assert a.gain_offset_db(az) <= 1e-9


# ------------------------------------------------------------ validation

def test_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="kind"):
        AntennaPattern(kind=7)


def test_out_of_range_settings_are_refused():
    with pytest.raises(ValueError, match="beamwidth_deg"):
        AntennaPattern(AntennaKind.SECTOR, 0.0, 1.0)
    with pytest.raises(ValueError, match="beamwidth_deg"):
        AntennaPattern(AntennaKind.SECTOR, 0.0, 500.0)
    with pytest.raises(ValueError, match="peak_gain_dbi"):
        AntennaPattern(AntennaKind.SECTOR, 100.0)
    with pytest.raises(ValueError, match="front_to_back_db"):
        AntennaPattern(AntennaKind.SECTOR, 0.0, 90.0, 0.0, -1.0)


def test_non_finite_values_are_refused():
    with pytest.raises(ValueError, match="nombre fini"):
        AntennaPattern(AntennaKind.SECTOR, 0.0, float("nan"))
    with pytest.raises(ValueError, match="nombre fini"):
        AntennaPattern(AntennaKind.SECTOR, float("inf"))


# ------------------------------------------------------------ couverture

def test_a_lobe_only_ever_removes_range():
    """Le diagramme retire du budget, il n'en crée pas : aucune direction ne gagne."""
    omni = _flat_radii()
    for kind in (AntennaKind.UNIDIRECTIONAL, AntennaKind.BIDIRECTIONAL, AntennaKind.SECTOR):
        beam = coverage_radii(Gateway(), _prop(), 130.0, None, 50.0, 72,
                              AntennaPattern(kind, 2.0, 60.0, 0.0, 25.0))
        for got, ref in zip(beam, omni):
            assert got <= ref + 1e-6


def test_a_lobe_pointed_east_reaches_full_range_east():
    """Sur l'axe du lobe, la portée est celle d'une omnidirectionnelle."""
    omni = _flat_radii()
    beam = coverage_radii(Gateway(), _prop(), 130.0, None, 50.0, 72,
                          AntennaPattern(AntennaKind.UNIDIRECTIONAL, 2.0, 60.0, 0.0, 25.0))
    assert _at(beam, 0.0) == pytest.approx(_at(omni, 0.0), abs=1.0)
    # Et le dos s'effondre, sans devenir nul : le plancher n'est pas un mur.
    assert _at(beam, 180.0) < _at(omni, 180.0) * 0.2
    assert _at(beam, 180.0) > 0.0


def test_a_bidirectional_lobe_reaches_both_ends():
    omni = _flat_radii()
    beam = coverage_radii(Gateway(), _prop(), 130.0, None, 50.0, 72,
                          AntennaPattern(AntennaKind.BIDIRECTIONAL, 2.0, 60.0, 0.0, 25.0))
    assert _at(beam, 0.0) == pytest.approx(_at(omni, 0.0), abs=1.0)
    assert _at(beam, 180.0) == pytest.approx(_at(omni, 180.0), abs=1.0)
    # Les flancs, à 90° des deux axes, sont les plus courts.
    assert _at(beam, 90.0) < _at(omni, 90.0) * 0.2
    assert _at(beam, 90.0) == pytest.approx(_at(beam, 270.0), abs=1.0)


def test_a_sector_covers_its_whole_width():
    """Un secteur de 120° pointé à l'est arrose ±60°, et pas l'ouest."""
    omni = _flat_radii()
    beam = coverage_radii(Gateway(), _prop(), 130.0, None, 50.0, 72,
                          AntennaPattern(AntennaKind.SECTOR, 2.0, 120.0, 0.0, 30.0))
    east = _at(beam, 0.0)
    assert east == pytest.approx(_at(omni, 0.0), abs=1.0)
    # ±60° : tout le secteur est encore au sommet du lobe.
    assert _at(beam, 60.0) == pytest.approx(east, abs=1.0)
    assert _at(beam, 300.0) == pytest.approx(east, abs=1.0)
    assert _at(beam, 180.0) < east * 0.5


def test_pointing_moves_the_zone():
    """Même antenne, même ouverture : seul l'azimut de l'axe change."""
    est = coverage_radii(Gateway(), _prop(), 130.0, None, 50.0, 72,
                         AntennaPattern(AntennaKind.SECTOR, 2.0, 90.0, 0.0, 30.0))
    nord = coverage_radii(Gateway(), _prop(), 130.0, None, 50.0, 72,
                          AntennaPattern(AntennaKind.SECTOR, 2.0, 90.0, 90.0, 30.0))
    assert _at(nord, 90.0) == pytest.approx(_at(est, 0.0), abs=1.0)
    assert _at(nord, 0.0) == pytest.approx(_at(est, 90.0), abs=1.0)
    # Le secteur tourné ne couvre plus l'est aussi loin qu'avant.
    assert _at(nord, 0.0) < _at(est, 0.0)


def test_an_omnidirectional_pattern_reproduces_plain_coverage():
    """Garantie de non-régression : sans diagramme, le calcul est celui d'avant."""
    a = coverage_radii(Gateway(), _prop(), 135.0, None, 40.0, 36)
    b = coverage_radii(Gateway(), _prop(), 135.0, None, 40.0, 36,
                       AntennaPattern(AntennaKind.OMNIDIRECTIONAL, 2.0, 90.0, 45.0, 20.0))
    assert a == pytest.approx(b, abs=1e-9)


def test_a_lobe_narrows_the_zone_left_by_an_obstacle():
    """Les deux effets se composent, et c'est le plus contraignant qui gagne.

    Lobe pointé à l'ouest (azimut 180°). Au nord, rien ne bornait la portée : le lobe
    la raccourcit. À l'est, le mur bornait déjà à 310 m, très en deçà de ce que le
    lobe autorise encore (540 m) : la zone ne bouge pas. Un lobe ne creuse donc une
    zone déjà fermée que s'il est plus sévère que l'obstacle.
    """
    wall = Obstacle(300.0, -200.0, 320.0, 200.0, 40.0, 60.0)
    env = Environment(obstacles=(wall,))
    beam_antenna = AntennaPattern(AntennaKind.UNIDIRECTIONAL, 2.0, 60.0, 180.0, 25.0)
    walled = coverage_radii(Gateway(), _prop(), 130.0, env, 10.0, 8)
    beam = coverage_radii(Gateway(), _prop(), 130.0, env, 10.0, 8, beam_antenna)

    assert beam[2] < walled[2] * 0.2                            # nord : hors axe
    assert beam[4] == pytest.approx(walled[4], abs=10.0 + 1e-6)  # ouest : sur l'axe
    assert beam[0] == pytest.approx(walled[0], abs=10.0 + 1e-6)  # est : le mur borne déjà
    assert all(b <= w + 1e-6 for b, w in zip(beam, walled))


def test_coverage_arguments_are_still_validated_with_an_antenna():
    """Le diagramme ne court-circuite pas les contrôles existants."""
    with pytest.raises(ValueError, match="azimuths"):
        coverage_radii(Gateway(), _prop(), 130.0, None, 50.0, 0,
                       AntennaPattern(AntennaKind.SECTOR, 2.0, 120.0))
    with pytest.raises(ValueError, match="step_m"):
        coverage_radii(Gateway(), _prop(), 130.0, None, 0.5, 8,
                       AntennaPattern(AntennaKind.SECTOR, 2.0, 120.0))
