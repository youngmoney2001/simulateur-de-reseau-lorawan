"""Contrat du panneau d'étude (brouillon) : schémas reproductibles et règles de sécurité des types."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from lsim import study_contract as sc

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "api" / "study-draft"


def test_committed_study_schemas_match_the_code(tmp_path):
    written = sc.write_schemas(tmp_path)
    assert len(written) == len(sc._MODELS)
    for path in written:
        committed = SCHEMA_DIR / path.name
        assert committed.exists(), f"schéma absent du dépôt : {path.name}"
        assert committed.read_text(encoding="utf-8") == path.read_text(encoding="utf-8"), path.name


def test_submit_request_cannot_carry_a_result():
    """Le navigateur n'envoie jamais de résultat à valider : champ inconnu refusé."""
    sc.SubmitRequest(session_id="abcdefgh12")
    for extra in ({"score": 100}, {"criteria": []}, {"result": "ok"}):
        with pytest.raises(ValidationError):
            sc.SubmitRequest(session_id="abcdefgh12", **extra)


def test_exercise_catalogue_exposes_no_criteria_or_solution():
    # Vérifié sur les propriétés (pas sur le texte : la docstring peut citer ces mots).
    assert set(sc.ExerciseSummary.model_fields) == {
        "id", "title", "statement", "max_points", "hints_available"}
    assert set(sc.ExerciseSummary.model_json_schema()["properties"]) == set(
        sc.ExerciseSummary.model_fields)


def test_a_node_key_can_only_be_the_mask():
    base = dict(node_id="gw1", hostname="gw1", configured=True)
    assert sc.NodeState(**base, keys=sc.MASKED).keys == sc.MASKED
    for value in ("0123456789ABCDEF", "", "******x"):
        with pytest.raises(ValidationError):
            sc.NodeState(**base, keys=value)


def test_cli_command_length_and_topology_size_are_bounded():
    sc.CliRequest(node_id="gw1", command="x" * 256)
    with pytest.raises(ValidationError):
        sc.CliRequest(node_id="gw1", command="x" * 257)
    node = dict(id="n1", kind="sensor", name="n1", x_m=0.0, y_m=0.0)
    nodes = [dict(node, id=f"n{i}") for i in range(sc.MAX_NODES)]
    sc.SessionTopology(session_id="abcdefgh12", nodes=nodes, states=[])
    with pytest.raises(ValidationError):
        sc.SessionTopology(session_id="abcdefgh12",
                           nodes=nodes + [dict(node, id="extra")], states=[])


def test_scores_and_hints_are_bounded():
    crit = dict(id="c1", label="joint", passed=True, points=5, max_points=5)
    ok = dict(exercise_id="joint-eu868", score=5, max_score=10, hints_used=0, criteria=[crit])
    sc.SubmitResult(**ok)
    with pytest.raises(ValidationError):
        sc.SubmitResult(**dict(ok, hints_used=11))
    with pytest.raises(ValidationError):
        sc.ExerciseSummary(id="joint-eu868", title="t", statement="s", max_points=10,
                           hints_available=11)
