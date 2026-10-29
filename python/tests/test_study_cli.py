"""CLI d'équipement du panneau d'étude : grammaire, modes, erreurs, aide, complétion."""

import lsim.study_cli as cli
from lsim.study_cli import Command, Session, complete, execute, help_for, render_config


def run(sess, *lines):
    """Exécute les lignes dans l'ordre ; renvoie le résultat de la dernière."""
    results = [execute(sess, line) for line in lines]
    return results[-1]


def test_modes_and_prompts_follow_the_spec():
    s = Session("gw1")
    assert s.prompt() == "gw1>"
    assert run(s, "enable").prompt == "gw1#"
    assert run(s, "configure terminal").prompt == "gw1(config)#"
    assert run(s, "interface lora 0").prompt == "gw1(config-if)#"
    assert run(s, "exit").prompt == "gw1(config)#"
    assert run(s, "end").prompt == "gw1#"
    assert run(s, "disable").prompt == "gw1>"


def test_abbreviations_are_unique_prefixes_as_in_ios():
    s = Session("gw1")
    run(s, "en", "conf t", "int lora 0")
    assert s.mode == "config-if" and s.iface == "lora"
    run(s, "no shut")
    assert s.config.lora.shutdown is False
    run(s, "end")
    assert run(s, "sh ver").error is None


def test_exit_at_user_level_closes_the_session():
    s = Session("gw1")
    result = run(s, "exit")
    assert result.closed is True
    assert run(s, "show version").output == "% Session fermée."


def test_unknown_command_marks_the_first_character():
    s = Session("gw1")
    r = run(s, "frob")
    assert r.error is not None and r.error[0] == 0
    assert "marqueur" in r.error[1]


def test_bad_argument_is_marked_at_its_token_and_changes_nothing():
    s = Session("gw1")
    run(s, "enable", "conf t", "int mesh 0", "max-hops 3")
    before = s.config.mesh.max_hops
    r = run(s, "max-hops 9")
    assert r.error == (len("max-hops "), r.error[1])
    assert "hors bornes" in r.error[1]
    assert s.config.mesh.max_hops == before == 3


def test_incomplete_command_is_reported_at_end_of_line():
    s = Session("gw1")
    r = run(s, "sh")
    assert r.error is not None and "incomplète" in r.error[1]
    r = run(s, "enable", "show")
    assert r.error is not None and "incomplète" in r.error[1]


def test_extra_words_are_refused_at_the_first_extra_word():
    s = Session("gw1")
    r = run(s, "show version now")
    assert r.error is not None and r.error[0] == len("show version ")


def test_ambiguous_abbreviation_is_refused(monkeypatch):
    s = Session("gw1")
    run(s, "enable")
    extra = Command(frozenset({"privileged"}), ("show", "vers"), lambda sess, args: "")
    monkeypatch.setattr(cli, "COMMANDS", cli.COMMANDS + (extra,))
    r = run(s, "show ver")
    assert r.error is not None and "ambiguë" in r.error[1]


def test_region_and_sub_band_rules():
    s = Session("gw1")
    run(s, "en", "conf t", "int lora 0", "region eu868")
    assert s.config.lora.region == "EU868"
    r = run(s, "sub-band 2")
    assert r.error is not None and "US915 ou AU915" in r.error[1]
    run(s, "region us915", "sub-band 2")
    assert s.config.lora.sub_band == 2
    run(s, "region as923")  # changer de région retire la sous-bande
    assert s.config.lora.sub_band is None


def test_mesh_values_are_checked_against_the_model():
    s = Session("gw1")
    run(s, "en", "conf t", "int mesh 0")
    assert run(s, "spreading-factor 6").error is not None
    assert run(s, "bandwidth 500").error is not None
    run(s, "spreading-factor 9", "bandwidth 203", "mode border", "max-hops 8")
    assert (s.config.mesh.spreading_factor, s.config.mesh.bandwidth_khz) == (9, "203")
    assert s.config.mesh.mode == "border"


def test_lorawan_server_net_id_and_location_are_parsed():
    s = Session("gw1")
    run(s, "en", "conf t", "lorawan net-id 0a0b0c",
        "lorawan server 10.0.0.5 up-port 1700 down-port 1701", "lorawan transport basicstation",
        "lorawan location 4.05 9.7")
    lw = s.config.lorawan
    assert lw.net_id == "0A0B0C"
    assert lw.server == ("10.0.0.5", 1700, 1701)
    assert lw.transport == "basicstation"
    assert lw.location == (4.05, 9.7)
    assert run(s, "lorawan server 300.1.1.1 up-port 1 down-port 2").error is not None
    assert run(s, "lorawan net-id 12").error is not None


def test_hostname_is_validated_and_changes_the_prompt():
    s = Session("gw1")
    run(s, "en", "conf t")
    assert run(s, "hostname 1abc").error is not None
    run(s, "hostname frontiere")
    assert s.prompt() == "frontiere(config)#"


def test_running_config_shows_set_values_only():
    s = Session("gw1")
    run(s, "en", "conf t", "int lora 0", "region EU868", "tx-power 14", "exit", "end")
    text = run(s, "show running-config").output
    assert "hostname gw1" in text and "region EU868" in text and "tx-power 14" in text
    assert "sub-band" not in text
    assert "key" not in text.lower() and "******" not in text


def test_copy_reload_and_write_erase_follow_the_config_lifecycle():
    s = Session("gw1")
    run(s, "en", "conf t", "int lora 0", "region EU868", "exit", "end")
    run(s, "write erase")
    assert s.config.lora.region is None and s.startup.lora.region is None
    run(s, "conf t", "int lora 0", "region AS923", "exit", "end")
    run(s, "copy running-config startup-config")
    run(s, "conf t", "int lora 0", "region KR920", "exit", "end")
    assert s.config.lora.region == "KR920"
    run(s, "reload")
    assert s.config.lora.region == "AS923" and s.mode == "user"


def test_show_mesh_without_simulation_says_so_and_uses_results_when_present():
    s = Session("gw1")
    run(s, "en")
    assert "Aucune simulation" in run(s, "show mesh neighbors").output
    s.simulation = {"mesh_neighbors": "relais-1 (-97 dBm)"}
    assert run(s, "show mesh neighbors").output == "relais-1 (-97 dBm)"


def test_question_mark_lists_the_next_words_and_arguments():
    s = Session("gw1")
    assert "enable" in help_for(s, "")
    run(s, "en", "conf t", "int lora 0")
    assert help_for(s, "region ") == ["EU868|US915|AU915|AS923|KR920|IN865|RU864"]
    assert "<cr>" in help_for(s, "region EU868 ")
    assert "region" in help_for(s, "r")


def test_tab_completes_a_unique_keyword_and_lists_the_others():
    s = Session("gw1")
    assert complete(s, "conf") == ("conf", [])
    run(s, "en")
    line, options = complete(s, "conf")
    assert line == "configure " and options == []
    assert complete(s, "sh") == ("show ", [])  # seul mot commençant par « sh » en privilégié
    line, options = complete(s, "show ")
    assert line == "show " and set(options) == {"interfaces", "lorawan", "mesh",
                                                "running-config", "startup-config", "version"}
    assert complete(s, "show l") == ("show lorawan ", [])


def test_empty_and_comment_lines_do_nothing():
    s = Session("gw1")
    assert execute(s, "   ").error is None
    assert s.mode == "user"


def test_rendered_config_has_no_secret_fields():
    assert "key" not in " ".join(render_config(Session("gw1").config)).lower()
