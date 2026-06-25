"""Shared schema helpers for tiny SP instances."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any


REQUIRED_SETS = ("I", "J", "H", "L", "L_Amb", "T", "S")
MINOR = "minor"


def load_instance(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def write_instance(instance: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(instance, f, indent=2, sort_keys=True)


def instance_fingerprint(instance: dict[str, Any]) -> str:
    payload = json.dumps(instance, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def periods(instance: dict[str, Any]) -> list[int]:
    return sorted(int(t) for t in instance["sets"]["T"])


def period_key(t: int | str) -> str:
    return str(int(t))


def prev_period(instance: dict[str, Any], t: int) -> int | None:
    ts = periods(instance)
    idx = ts.index(int(t))
    return None if idx == 0 else ts[idx - 1]


def has_period(instance: dict[str, Any], t: int) -> bool:
    return int(t) in set(periods(instance))


def p(instance: dict[str, Any], s: str) -> float:
    return float(instance["p_s"][s])


def fs(instance: dict[str, Any], name: str) -> Any:
    return instance["first_stage"][name]


def ss(instance: dict[str, Any], name: str) -> Any:
    return instance["second_stage"][name]


def rv(instance: dict[str, Any], name: str) -> Any:
    return instance["random_variables"][name]


def xi(instance: dict[str, Any], i: str, l: str, t: int, s: str) -> float:
    return float(rv(instance, "xi_ilts")[i][l][period_key(t)][s])


def u(instance: dict[str, Any], i: str, j: str, t: int, s: str) -> float:
    return float(rv(instance, "u_ijts")[i][j][period_key(t)][s])


def w(instance: dict[str, Any], j: str, h: str, t: int, s: str) -> float:
    return float(rv(instance, "w_jhts")[j][h][period_key(t)][s])


def hosp_cap(instance: dict[str, Any], h: str, t: int, s: str) -> float:
    return float(rv(instance, "h_hts")[h][period_key(t)][s])


def nested_get_2(table: dict[str, Any], a: str, b: str) -> float:
    return float(table[a][b])


def nested_get_3(table: dict[str, Any], a: str, b: str, c: str) -> float:
    return float(table[a][b][c])
