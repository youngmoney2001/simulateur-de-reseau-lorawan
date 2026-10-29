"""La carte de couverture suit le même seuil que la simulation (décalage du profil de passerelle)."""

from pathlib import Path

from lsim.geo import _mapl_db
from lsim.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[2]


def test_composite_gateway_gains_the_offset_in_the_coverage_budget():
    sc = load_scenario(ROOT / "examples" / "mesh_relais_quartier.yaml")
    composite = sc.model.gateways[0]
    assert composite.profile == "rak5146-rak5148"
    no_profile = composite.model_copy(update={"profile": None})
    # Seuil plus bas de 3 dB (décalage -3 dB) : budget de liaison plus grand de 3 dB.
    assert abs((_mapl_db(sc, 12, 14.0, composite) - _mapl_db(sc, 12, 14.0, no_profile)) - 3.0) < 1e-9
