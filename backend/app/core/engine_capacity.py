"""Deployment-time capacity controls, calibrated against measured workloads.

Importing this module never loads app secrets or changes running infrastructure.
Defaults retain current provisioned capacity. Operators can independently tune
warm/burst pools and placement for render, combined and model workers.
"""
from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping


def capacity_options(kind: str, environment: Mapping[str, str] | None = None) -> dict:
    defaults = {"LATEX": (1, 120), "ORCHESTRATOR": (1, 180), "LLM": (0, 60)}
    if kind not in defaults:
        raise ValueError("Unknown engine capacity class")
    values = os.environ if environment is None else environment
    prefix = f"MODAL_{kind}_"

    def integer(name: str, default: int, minimum: int, maximum: int) -> int:
        raw = values.get(prefix + name, str(default))
        try:
            parsed = int(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid {prefix}{name}") from exc
        if not minimum <= parsed <= maximum:
            raise ValueError(f"Invalid {prefix}{name}")
        return parsed

    minimum, idle = defaults[kind]
    options = {
        "min_containers": integer("MIN_CONTAINERS", minimum, 0, 20),
        "buffer_containers": integer("BUFFER_CONTAINERS", 0, 0, 20),
        "scaledown_window": integer("SCALEDOWN_SECONDS", idle, 2, 1200),
    }
    if prefix + "MAX_CONTAINERS" in values:
        maximum = integer("MAX_CONTAINERS", 20, 1, 100)
        if maximum < options["min_containers"]:
            raise ValueError("Engine max capacity is below its warm minimum")
        options["max_containers"] = maximum
    if prefix + "CPU" in values:
        try:
            cpu = float(values[prefix + "CPU"])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid {prefix}CPU") from exc
        if not math.isfinite(cpu) or not .25 <= cpu <= 16:
            raise ValueError(f"Invalid {prefix}CPU")
        options["cpu"] = cpu
    region = values.get("MODAL_ENGINE_REGION", "").strip()
    if region:
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+){0,2}", region) or len(region) > 32:
            raise ValueError("Invalid MODAL_ENGINE_REGION")
        options["region"] = region
    return options
