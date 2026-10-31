"""Tests du contrat Python ABI v3 (étape 6.2.7) : parité avec c_api.h, schémas synchronisés,
validations, conditionnels de trace, chemins Python inchangés, documentation complète."""

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from pydantic import ValidationError  # noqa: E402

from lsim import abi_v3_contract as c  # noqa: E402

HEADER = (ROOT / "core/include/lsim/c_api.h").read_text(encoding="utf-8")
ENGINE_HEADER = (ROOT / "core/include/lsim/engine.hpp").read_text(encoding="utf-8")
DOC = ROOT / "docs/CLOSED_LOOP_ABI_V3.md"
SCHEMA_DIR = ROOT / "schemas/abi/v3"


def header_values(prefix):
    """Valeurs `#define <prefix>_<NOM> <n>u` : {nom en minuscules: n}."""
    pattern = re.compile(rf"#define {prefix}_(\w+) (\d+)u\b")
    return {m.group(1).lower(): int(m.group(2)) for m in pattern.finditer(HEADER)}


def ok_element(**overrides):
    base = {
        "device_index": 0,
        "present": True,
        "defined": [{"index": 0, "dr_mask": 0x3F}, {"index": 5, "dr_mask": 0x3F}],
        "enabled": [0, 5],
        "server_defined": [0, 5],
    }
    base.update(overrides)
    return base


def trace(**overrides):
    base = {
        "t_ns": 1_000, "device": 0, "uplink": 0, "kind": "uplink", "origin": "radio",
        "dr": 0, "power_index": 0, "channel_mask": 0, "value": 0,
    }
    base.update(overrides)
    return base


class ConstantParityTests(unittest.TestCase):
    def test_channel_status_codes_match_header(self):
        header = {
            m.group(1): 1000 + int(m.group(2))
            for m in re.finditer(r"#define LSIM_STATUS_CHANNEL_(\w+) \(LSIM_STATUS_CHANNEL_BASE \+ (\d+)\)", HEADER)
        }
        self.assertEqual(len(header), 21)
        self.assertEqual(c.CHANNEL_STATUS_CODES, header)

    def test_channel_status_base_is_1000(self):
        self.assertIn("#define LSIM_STATUS_CHANNEL_BASE 1000", HEADER)

    def test_trace_enumerations_match_header(self):
        self.assertEqual(c.TRACE_KIND_VALUES, header_values("LSIM_TRACE_KIND"))
        self.assertEqual(c.TRACE_ORIGIN_VALUES, header_values("LSIM_TRACE_ORIGIN"))
        self.assertEqual(c.TRACE_ACTION_VALUES, header_values("LSIM_TRACE_ACTION"))
        self.assertEqual(c.TRACE_TARGET_VALUES, header_values("LSIM_TRACE_TARGET"))
        self.assertEqual(c.TRACE_LOSS_VALUES, header_values("LSIM_TRACE_LOSS"))
        self.assertEqual(c.TRACE_CHANNEL_REASON_VALUES, header_values("LSIM_TRACE_CHANNEL_REASON"))
        self.assertEqual(c.TRACE_DR_REASON_VALUES, header_values("LSIM_TRACE_DR_REASON"))
        self.assertEqual(c.TRACE_POWER_REASON_VALUES, header_values("LSIM_TRACE_POWER_REASON"))

    def test_sentinels_and_limits_match_header(self):
        self.assertIn("#define LSIM_TRACE_NO_INDEX 0xFFFFFFFFu", HEADER)
        self.assertIn("#define LSIM_TRACE_STATUS_NONE 0xFFu", HEADER)
        self.assertIn("#define LSIM_TRACE_FIELD_IGNORE 15u", HEADER)
        self.assertEqual(c.DOWNLINK_NO_INDEX, 0xFFFFFFFF)
        self.assertEqual(c.STATUS_NONE, 0xFF)
        self.assertEqual(c.FIELD_IGNORE, 15)
        self.assertIn("#define LSIM_CHANNEL_ENGINE_MAX 80u", HEADER)
        self.assertIn("#define LSIM_CHANNEL_SUPPORTED_MAX 16u", HEADER)
        self.assertEqual(c.CHANNEL_ABI_SLOTS, 80)
        self.assertEqual(c.CHANNEL_SUPPORTED_MAX, 16)
        self.assertIn("kMaxEndDevices = 10'000;", ENGINE_HEADER)
        self.assertEqual(c.MAX_END_DEVICES, 10_000)
        self.assertEqual(c.ABI_VERSION, 3)
        self.assertIn("#define LSIM_CHANNEL_PRESENT_NO 0u", HEADER)
        self.assertIn("#define LSIM_CHANNEL_PRESENT_YES 1u", HEADER)


class SchemaPublicationTests(unittest.TestCase):
    def test_published_schemas_are_synchronised(self):
        for name, schema in c.schemas().items():
            path = SCHEMA_DIR / f"{name}.schema.json"
            self.assertTrue(path.exists(), path)
            with tempfile.TemporaryDirectory() as tmp:
                written = c.write_schemas(Path(tmp))
                fresh = next(p for p in written if p.name == path.name).read_text(encoding="utf-8")
            self.assertEqual(path.read_text(encoding="utf-8"), fresh, f"{path} désynchronisé")

    def test_exact_set_of_v3_schema_files(self):
        self.assertEqual(
            sorted(p.name for p in SCHEMA_DIR.glob("*.json")),
            sorted(f"{n}.schema.json" for n in c.PUBLISHED_MODELS),
        )

    def test_api_v1_schemas_do_not_contain_v3(self):
        for p in (ROOT / "schemas/api/v1").glob("*.json"):
            self.assertNotIn("closed_loop_v3", p.read_text(encoding="utf-8"), p.name)

    def test_v1_scenario_schema_still_exposes_device_channels(self):
        text = (ROOT / "schemas/api/v1/scenario_input.schema.json").read_text(encoding="utf-8")
        self.assertIn("device_channels", text)


class ChannelSetTests(unittest.TestCase):
    def test_historical_mode_without_elements(self):
        self.assertTrue(c.ChannelSetV3().is_historical)
        self.assertTrue(c.ChannelSetV3(channel_plan="none", elements=[]).is_historical)
        c.ChannelSetV3().validate_for_devices(3)

    def test_explicit_eu868_mode(self):
        cs = c.ChannelSetV3(channel_plan="eu868_rp002_1_0_5", elements=[ok_element()])
        self.assertFalse(cs.is_historical)
        cs.validate_for_devices(1)

    def test_plan_without_elements_refused(self):
        with self.assertRaisesRegex(ValidationError, "CHANNEL_MODE"):
            c.ChannelSetV3(channel_plan="eu868_rp002_1_0_5")

    def test_elements_without_plan_refused(self):
        with self.assertRaisesRegex(ValidationError, "CHANNEL_MODE"):
            c.ChannelSetV3(channel_plan="none", elements=[ok_element()])

    def test_element_count_must_equal_device_count(self):
        cs = c.ChannelSetV3(channel_plan="eu868_rp002_1_0_5", elements=[ok_element()])
        with self.assertRaisesRegex(ValueError, "CHANNEL_MODE"):
            cs.validate_for_devices(2)

    def test_device_index_must_be_unique_and_in_range(self):
        cs = c.ChannelSetV3(channel_plan="eu868_rp002_1_0_5",
                            elements=[ok_element(), ok_element()])
        with self.assertRaisesRegex(ValueError, "DEVICE_INDEX"):
            cs.validate_for_devices(2)
        cs = c.ChannelSetV3(channel_plan="eu868_rp002_1_0_5",
                            elements=[ok_element(device_index=1)])
        with self.assertRaisesRegex(ValueError, "DEVICE_INDEX"):
            cs.validate_for_devices(1)

    def test_present_false_requires_empty_fields(self):
        with self.assertRaisesRegex(ValidationError, "FIELDS_WITHOUT_PRESENT"):
            c.ChannelElementV3(device_index=0, present=False, enabled=[0])
        c.ChannelElementV3(device_index=0, present=False)

    def test_enabled_must_be_defined(self):
        with self.assertRaisesRegex(ValidationError, "ENABLED_UNDEFINED"):
            c.ChannelElementV3(**ok_element(enabled=[0, 7]))

    def test_enabled_empty_refused(self):
        with self.assertRaisesRegex(ValidationError, "ENABLED_EMPTY"):
            c.ChannelElementV3(**ok_element(enabled=[]))

    def test_server_view_empty_refused(self):
        with self.assertRaisesRegex(ValidationError, "SERVER_VIEW_EMPTY"):
            c.ChannelElementV3(**ok_element(server_defined=[]))

    def test_channel_index_16_to_79_refused(self):
        with self.assertRaisesRegex(ValidationError, "INDEX_UNSUPPORTED"):
            c.ChannelElementV3(**ok_element(server_defined=[0, 16]))
        with self.assertRaisesRegex(ValidationError, "INDEX_UNSUPPORTED"):
            c.ChannelElementV3(**ok_element(defined=[{"index": 0, "dr_mask": 1}, {"index": 79, "dr_mask": 1}],
                                            enabled=[0], server_defined=[0]))

    def test_channel_index_80_and_above_outside_abi(self):
        with self.assertRaises(ValidationError):
            c.ChannelElementV3(**ok_element(enabled=[80]))

    def test_duplicate_index_refused(self):
        with self.assertRaises(ValidationError):
            c.ChannelElementV3(**ok_element(enabled=[0, 0]))
        with self.assertRaises(ValidationError):
            c.ChannelElementV3(**ok_element(defined=[{"index": 0, "dr_mask": 1}, {"index": 0, "dr_mask": 2}]))

    def test_dr_mask_zero_refused(self):
        with self.assertRaises(ValidationError):
            c.ChannelDefinitionV3(index=0, dr_mask=0)

    def test_unknown_field_refused(self):
        with self.assertRaises(ValidationError):
            c.ChannelElementV3(**ok_element(ch_mask_cntl=0))

    def test_error_code_names_are_in_messages(self):
        with self.assertRaises(ValidationError) as ctx:
            c.ChannelElementV3(**ok_element(enabled=[0, 7]))
        self.assertIn("LSIM_STATUS_CHANNEL_ENABLED_UNDEFINED (1012)", str(ctx.exception))


class TraceEventTests(unittest.TestCase):
    def test_uplink_sentinels(self):
        ev = c.TraceEventV3(**trace())
        self.assertIsNone(ev.downlink)
        self.assertIsNone(ev.status)
        self.assertEqual(c.trace_raw_downlink(ev), 0xFFFFFFFF)
        self.assertEqual(c.trace_raw_status(ev), 0xFF)

    def test_link_adr_ans_requires_status(self):
        with self.assertRaisesRegex(ValidationError, "status"):
            c.TraceEventV3(**trace(kind="link_adr_ans", origin="normative", flag=True))
        ev = c.TraceEventV3(**trace(kind="link_adr_ans", origin="normative", status=7, flag=True))
        self.assertEqual(c.trace_raw_status(ev), 7)

    def test_status_refused_on_uplink(self):
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(status=1))

    def test_downlink_index_required_for_request_and_downlink(self):
        for kind in ("link_adr_req", "downlink", "apply"):
            with self.subTest(kind=kind):
                extra = {"status": 5} if kind == "apply" else {}
                with self.assertRaisesRegex(ValidationError, "downlink"):
                    c.TraceEventV3(**trace(kind=kind, origin="normative", flag=(kind != "link_adr_req"), **extra))

    def test_downlink_index_refused_on_uplink_and_exclusion(self):
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(downlink=3))
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(kind="exclusion", origin="normative", downlink=3))

    def test_downlink_loss_only_for_downlink(self):
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(loss="no_gateway_slot"))
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(kind="apply", origin="normative", downlink=1, status=1,
                                   loss="below_sensitivity"))

    def test_lost_downlink_has_loss_and_no_flag(self):
        ev = c.TraceEventV3(**trace(kind="downlink", origin="radio", downlink=2, value=3,
                                    loss="no_gateway_slot", flag=False))
        self.assertEqual(ev.loss, "no_gateway_slot")
        self.assertEqual(c.trace_raw_downlink(ev), 2)
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(kind="downlink", origin="radio", downlink=2, value=3,
                                   loss="no_gateway_slot", flag=True))

    def test_received_downlink_requires_no_loss(self):
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(kind="downlink", origin="radio", downlink=2, value=3, flag=False))
        ev = c.TraceEventV3(**trace(kind="downlink", origin="radio", downlink=2, value=3, flag=True))
        self.assertEqual(ev.loss, "none")

    def test_reasons_only_on_apply(self):
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(reason_channel=2))
        ev = c.TraceEventV3(**trace(kind="apply", origin="normative", downlink=0, status=5,
                                    reason_channel=2, reason_dr=0, reason_power=0))
        self.assertEqual(ev.reason_channel, 2)

    def test_time_and_range_limits(self):
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(t_ns=-1))
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(channel_mask=65536))
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(kind="link_adr_req", origin="normative", downlink=0xFFFFFFFE + 1))

    def test_unknown_kind_refused(self):
        with self.assertRaises(ValidationError):
            c.TraceEventV3(**trace(kind="channel_mask_ack"))


class FlagAndValueContractTests(unittest.TestCase):
    """Décisions contractuelles : flag de link_adr_ans/link_adr_req, value par type, bornes par cible."""

    def test_link_adr_ans_flag_equals_full_acceptance(self):
        ok = c.TraceEventV3(**trace(kind="link_adr_ans", origin="normative", status=7, flag=True))
        self.assertTrue(ok.flag)
        ok = c.TraceEventV3(**trace(kind="link_adr_ans", origin="normative", status=5, flag=False))
        self.assertFalse(ok.flag)
        with self.assertRaisesRegex(ValidationError, "status == 0x07"):
            c.TraceEventV3(**trace(kind="link_adr_ans", origin="normative", status=5, flag=True))
        with self.assertRaisesRegex(ValidationError, "status == 0x07"):
            c.TraceEventV3(**trace(kind="link_adr_ans", origin="normative", status=7, flag=False))

    def test_link_adr_req_flag_must_be_false(self):
        ev = c.TraceEventV3(**trace(kind="link_adr_req", origin="simulator_policy", downlink=0, flag=False))
        self.assertFalse(ev.flag)
        with self.assertRaisesRegex(ValidationError, "sans objet"):
            c.TraceEventV3(**trace(kind="link_adr_req", origin="simulator_policy", downlink=0, flag=True))

    def test_value_zero_outside_exclusion_and_downlink(self):
        cases = [
            trace(value=1),  # uplink
            trace(kind="link_adr_ans", origin="normative", status=7, flag=True, value=2),
            trace(kind="adr_decision", origin="simulator_policy", value=1),
            trace(kind="link_adr_req", origin="simulator_policy", downlink=0, value=4),
            trace(kind="apply", origin="normative", downlink=0, status=7, flag=True, value=1),
        ]
        for case in cases:
            with self.subTest(kind=case["kind"]):
                with self.assertRaisesRegex(ValidationError, "0 requis"):
                    c.TraceEventV3(**case)
        ev = c.TraceEventV3(**trace(kind="apply", origin="normative", downlink=0, status=7, flag=True))
        self.assertEqual(ev.value, 0)

    def test_downlink_value_limited_to_five_known_bits(self):
        self.assertEqual(c.TRACE_DOWNLINK_COMMAND_MASK, 0x1F)
        self.assertEqual(sorted(c.TRACE_DOWNLINK_COMMAND_BITS.values()), [0x01, 0x02, 0x04, 0x08, 0x10])
        for value in (0, 0x01, 0x03, 0x1F):
            ev = c.TraceEventV3(**trace(kind="downlink", origin="radio", downlink=0, value=value, flag=True))
            self.assertEqual(ev.value, value)
        for value in (0x20, 0x40, 0x80, 0x3F):
            with self.subTest(value=hex(value)):
                with self.assertRaisesRegex(ValidationError, "cinq bits"):
                    c.TraceEventV3(**trace(kind="downlink", origin="radio", downlink=0, value=value, flag=True))

    def test_exclusion_value_bounds_per_target(self):
        bounds = {"data_rate": 15, "power": 14, "channel": 15, "mask": 65535}
        self.assertEqual(c.TRACE_EXCLUSION_VALUE_MAX, bounds)
        for target, bound in bounds.items():
            base = dict(kind="exclusion", origin="simulator_policy", target=target, action="created")
            c.TraceEventV3(**trace(value=bound, **base))
            c.TraceEventV3(**trace(value=0, **base))
            with self.subTest(target=target):
                with self.assertRaises(ValidationError):
                    c.TraceEventV3(**trace(value=bound + 1, **base))

    def test_power_reserved_indices_8_to_14_are_representable(self):
        for index in range(8, 15):
            ev = c.TraceEventV3(**trace(kind="exclusion", origin="simulator_policy", target="power",
                                        action="created", value=index))
            self.assertEqual(ev.value, index)
        with self.assertRaisesRegex(ValidationError, "au plus 14"):
            c.TraceEventV3(**trace(kind="exclusion", origin="simulator_policy", target="power",
                                   action="created", value=15))

    def test_mask_exclusion_carries_full_sixteen_bit_mask(self):
        ev = c.TraceEventV3(**trace(kind="exclusion", origin="simulator_policy", target="mask",
                                    action="created", value=0xFF03))
        self.assertEqual(ev.value, 0xFF03)

    def test_schema_mirrors_value_and_flag_rules(self):
        schema = c.schemas()["closed_loop_v3_trace_event"]
        rules = schema["allOf"]

        def find(kind=None, **props):
            for rule in rules:
                cond = rule.get("if", {}).get("properties", {})
                if kind is not None and cond.get("kind") != {"const": kind}:
                    continue
                if all(cond.get(k) == v for k, v in props.items()):
                    return rule
            return None

        power = find(kind="exclusion", target={"const": "power"})
        self.assertIsNotNone(power)
        self.assertEqual(power["then"]["properties"]["value"]["maximum"], 14)
        mask = find(kind="exclusion", target={"const": "mask"})
        self.assertEqual(mask["then"]["properties"]["value"]["maximum"], 65535)
        downlink = next(r for r in rules if r.get("if", {}).get("properties", {}).get("kind", {}).get("enum") == ["downlink"])
        self.assertEqual(downlink["then"]["properties"]["value"]["maximum"], 0x1F)
        req = next(r for r in rules if r.get("if", {}).get("properties", {}).get("kind", {}).get("enum") == ["link_adr_req"])
        self.assertEqual(req["then"]["properties"]["flag"], {"const": False})

    def test_schema_documents_value_zero_for_other_kinds(self):
        rules = c.schemas()["closed_loop_v3_trace_event"]["allOf"]
        zero_rules = [r for r in rules if r.get("then", {}).get("properties", {}).get("value") == {"const": 0}]
        self.assertEqual(len(zero_rules), 1)
        excluded = set(zero_rules[0]["if"]["properties"]["kind"]["enum"])
        self.assertEqual(excluded, set(c.TRACE_KIND_VALUES) - {"exclusion", "downlink"})


class TerminalStateTests(unittest.TestCase):
    def test_terminal_state_bounds(self):
        ts = c.TerminalStateV3(device_index=0, dr=5, power_index=1,
                               defined=[{"index": 0, "dr_mask": 1}], enabled=[0])
        self.assertEqual(ts.enabled, [0])
        with self.assertRaises(ValidationError):
            c.TerminalStateV3(device_index=0, dr=256, power_index=0)


class PathIsolationTests(unittest.TestCase):
    def test_v3_python_binding_is_the_single_native_module(self):
        # Seul le module de liaison v3 référence le symbole natif ; v1, v2 et gw2 n'importent rien de v3.
        bindings = []
        importers = []
        for path in sorted((ROOT / "python/lsim").rglob("*.py")):
            if path.name == "abi_v3_contract.py":
                continue
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(ROOT).as_posix()
            if "lsim_simulate_closed_loop_v3" in text:
                bindings.append(rel)
            if "closed_loop_v3" in text and rel != "python/lsim/closed_loop_v3.py":
                importers.append(rel)
        self.assertEqual(bindings, ["python/lsim/closed_loop_v3.py"])
        self.assertEqual(importers, [])
        source = (ROOT / "python/lsim/closed_loop_v3.py").read_text(encoding="utf-8")
        self.assertIn("from lsim._native import", source)
        self.assertIn("LIB.lsim_simulate_closed_loop_v3(ctypes.pointer(args))", source)
        self.assertIn("ABI_VERSION_V3 = 3", source)

    def test_scenario_still_refuses_device_channels_with_step_three(self):
        from lsim import scenario

        source = (ROOT / "python/lsim/scenario.py").read_text(encoding="utf-8")
        self.assertIn("étape 3", source)
        self.assertNotIn("abi_v3_contract", source)
        self.assertTrue(hasattr(scenario, "MacModel"))

    def test_contract_module_does_not_import_scenario(self):
        source = (ROOT / "python/lsim/abi_v3_contract.py").read_text(encoding="utf-8")
        self.assertNotIn("from lsim.scenario", source)
        self.assertNotIn("import scenario", source)


class DocumentationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DOC.exists(), "docs/CLOSED_LOOP_ABI_V3.md manquant")
        self.text = DOC.read_text(encoding="utf-8")

    def test_documents_every_channel_status_code(self):
        for name in c.CHANNEL_STATUS_CODES:
            self.assertIn(f"LSIM_STATUS_CHANNEL_{name}", self.text, name)

    def test_documents_every_trace_kind_and_sentinel(self):
        for name in c.TRACE_KIND_VALUES:
            self.assertIn(name, self.text, name)
        self.assertIn("0xFFFFFFFF", self.text)
        self.assertIn("0xFF", self.text)

    def test_states_function_is_defined_and_exported(self):
        self.assertIn("lsim_simulate_closed_loop_v3", self.text)
        self.assertNotIn("non exportée", self.text)
        self.assertNotIn("non encore définie", self.text)
        self.assertIn("exportée", self.text)

    def test_states_historical_and_explicit_modes(self):
        self.assertIn("historique", self.text)
        self.assertIn("EU868", self.text)

    def test_documents_value_and_flag_decisions(self):
        for needle in ("0 à 15", "0 à 14", "0 à 65535", "8 à 14", "0x1F", "status == 0x07", "sans objet"):
            self.assertIn(needle, self.text, needle)

    def test_documents_v1_v2_unchanged(self):
        self.assertIn("v1", self.text)
        self.assertIn("v2", self.text)
        self.assertIn("inchang", self.text)


if __name__ == "__main__":
    unittest.main()
