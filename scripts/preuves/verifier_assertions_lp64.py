#!/usr/bin/env python3
"""Tableau des assertions ABI en littéraux de `test_rf_frontend.cpp` et verdict par ABI.

    python3 scripts/preuves/verifier_assertions_lp64.py

Lit les deux tables de `core/tests/abi_layout.cpp` (x86-64 et i386) et confronte chacune aux
14 assertions `sizeof`/`offsetof` de `core/tests/test_rf_frontend.cpp`.
Au commit 68176d6 : 0 échec en x86-64, 11 échecs en i386, 3 assertions indépendantes de l'ABI.
Code retour 1 si une valeur manque ou si x86-64 diverge (le fichier ne serait plus cohérent).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAYOUT = ROOT / "core" / "tests" / "abi_layout.cpp"
TESTS = ROOT / "core" / "tests" / "test_rf_frontend.cpp"

ENTRY = re.compile(r"inline constexpr size_t (size|off)_(\w+?)(?:__(\w+))? = (\d+);")
CHECK = re.compile(r"CHECK_EQ\(static_cast<int>\((sizeof|offsetof)\((lsim_\w+)(?:, (\w+))?\)\), (\d+)\);")


def table(lines: list[str], start: int, stop: int) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in lines[start:stop]:
        match = ENTRY.search(line)
        if match:
            kind, struct, member, value = match.groups()
            key = f"size_{struct}" if kind == "size" else f"off_{struct}__{member}"
            values[key] = int(value)
    return values


def main() -> int:
    lines = LAYOUT.read_text(encoding="utf-8").splitlines()
    first = next(i for i, l in enumerate(lines) if "namespace expected {" in l)
    split = next(i for i, l in enumerate(lines[first:], first) if l.strip().startswith("#elif"))
    end = next(i for i, l in enumerate(lines[first:], first) if "}  // namespace expected" in l)
    i386 = table(lines, first + 1, split)
    x86 = table(lines, split + 1, end)

    rows = []
    for number, line in enumerate(TESTS.read_text(encoding="utf-8").splitlines(), 1):
        match = CHECK.search(line)
        if match:
            kind, struct, member, literal = match.groups()
            key = f"size_{struct}" if kind == "sizeof" else f"off_{struct}__{member}"
            rows.append((number, kind, struct, member, int(literal), key))

    print(f"{'ligne':>5} | {'grandeur':<52} | x86-64 | i386 | i386")
    failures_i386 = failures_x86 = missing = 0
    for number, kind, struct, member, literal, key in rows:
        size_x, size_i = x86.get(key), i386.get(key)
        missing += (size_x is None) + (size_i is None)
        ok_x = size_x == literal
        ok_i = size_i == literal
        failures_x86 += not ok_x
        failures_i386 += not ok_i
        label = f"{kind}({struct}{', ' + member if member else ''})"
        print(f"{number:>5} | {label:<52} | {literal:>6} | {size_i!s:>4} | "
              f"{'OK' if ok_i else 'ÉCHEC'}")
    print(f"\nassertions : {len(rows)} | échecs x86-64 : {failures_x86} | "
          f"échecs i386 : {failures_i386} | valeurs manquantes : {missing}")
    if missing:
        return 1
    return 0 if failures_x86 == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
