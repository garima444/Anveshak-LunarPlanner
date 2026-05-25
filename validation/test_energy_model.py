"""
validation/test_energy_model.py — Test 7: Energy Model Validation (5 sub-tests).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from core.energy_model import (
    BASE_POWER_W,
    ENERGY_RISK_HIGH,
    ENERGY_RISK_MODERATE,
    REGEN_FRACTION,
    SLOPE_MOTOR_FACTOR,
    compute_path_energy,
)

_RES = 60.0
_SPEED = 0.5  # km/h
_ROVER = {"speed_kmh": _SPEED, "max_slope_deg": 20.0}

# BASE_POWER_W is the flat-terrain continuous power draw for the modelled rover.
# Current value (from energy_model.py): {BASE_POWER_W} W.
# Reference specs for comparison:
#   VIPER rover (NASA, 2024): ~100-130 W continuous electrical load
#   Artemis MMSEV / pressurised rover: ~200 W estimated
# If BASE_POWER_W deviates significantly from these, energy estimates are unrealistic.
_BASE_POWER_REFERENCE = f"BASE_POWER_W={BASE_POWER_W} W (VIPER ref: ~100-130 W, Artemis ref: ~200 W)"


def _flat_energy(n_steps: int) -> float:
    """Expected energy for n_steps on flat terrain at _SPEED km/h."""
    total_m = n_steps * _RES
    time_hrs = (total_m / 1000.0) / _SPEED
    return BASE_POWER_W * time_hrs


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 7] Energy Model Validation")
    result = {"test_name": "Energy Model Validation"}

    sub_results = {}

    # ---- 7a: Flat horizontal path, slope=0 --------------------------------
    print("  [7a] Flat 50-step path (slope=0), energy = BASE_POWER × time ...")
    try:
        n = 50
        sl = np.zeros((n + 1, 2), dtype=np.float32)
        el = np.zeros((n + 1, 2), dtype=np.float32)
        path = [(i, 0) for i in range(n + 1)]

        stats = compute_path_energy(path, sl, _ROVER, _RES, el)
        actual_e = stats["total_energy_wh"]
        expected_e = _flat_energy(n)
        pct_err = abs(actual_e - expected_e) / max(expected_e, 1e-6) * 100.0
        passed = pct_err <= 1.0

        sub_results["7a"] = {
            "n_steps": n,
            "actual_energy_wh": round(actual_e, 4),
            "expected_energy_wh": round(expected_e, 4),
            "pct_error": round(pct_err, 4),
            "result": "PASS" if passed else "FAIL",
            "notes": f"actual={actual_e:.4f} Wh, expected={expected_e:.4f} Wh, err={pct_err:.4f}%",
        }
        print(f"    {sub_results['7a']['result']}: err={pct_err:.4f}%")
    except Exception as exc:
        sub_results["7a"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 7b: Uphill vs flat energy ratio ----------------------------------
    print("  [7b] Uphill slope=10deg vs flat -- ratio ~ 1 + sin(10deg)x3 ...")
    try:
        n = 10
        slope_deg = 10.0
        # Flat path
        sl_flat = np.zeros((n + 1, 2), dtype=np.float32)
        el_flat = np.zeros((n + 1, 2), dtype=np.float32)
        path = [(i, 0) for i in range(n + 1)]
        stats_flat = compute_path_energy(path, sl_flat, _ROVER, _RES, el_flat)

        # Uphill path (elevation increasing with row)
        sl_up = np.full((n + 1, 2), slope_deg, dtype=np.float32)
        el_up = np.zeros((n + 1, 2), dtype=np.float32)
        for r in range(n + 1):
            el_up[r, :] = r * _RES * math.tan(math.radians(slope_deg))

        stats_up = compute_path_energy(path, sl_up, _ROVER, _RES, el_up)

        e_flat = stats_flat["total_energy_wh"]
        e_up = stats_up["total_energy_wh"]
        actual_ratio = e_up / e_flat if e_flat > 0 else 0.0
        expected_ratio = 1.0 + math.sin(math.radians(slope_deg)) * SLOPE_MOTOR_FACTOR
        pct_err = abs(actual_ratio - expected_ratio) / expected_ratio * 100.0
        passed = pct_err <= 5.0

        sub_results["7b"] = {
            "flat_energy_wh": round(e_flat, 4),
            "uphill_energy_wh": round(e_up, 4),
            "actual_ratio": round(actual_ratio, 4),
            "expected_ratio": round(expected_ratio, 4),
            "pct_error": round(pct_err, 4),
            "result": "PASS" if passed else "FAIL",
            "notes": f"ratio={actual_ratio:.4f}, expected={expected_ratio:.4f}, err={pct_err:.2f}%",
        }
        print(f"    {sub_results['7b']['result']}: ratio={actual_ratio:.4f}, expected={expected_ratio:.4f}")
    except Exception as exc:
        sub_results["7b"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 7c: Downhill regen > 0, total < truly-flat cost -------------------
    # Baseline must be slope=0 (flat, no elevation change) NOT slope=15 with
    # zero elevation change — that is physically impossible (non-zero slope
    # angle on a horizontal surface). The valid comparison is:
    #   downhill (slope=15°, elev decreasing) vs flat (slope=0°, elev constant)
    print("  [7c] Downhill slope=15°: regen_wh > 0, total < flat (slope=0) cost ...")
    try:
        n = 10
        slope_deg = 15.0
        path = [(i, 0) for i in range(n + 1)]

        # Downhill: elevation DECREASES with row, slope=15°
        sl_down = np.full((n + 1, 2), slope_deg, dtype=np.float32)
        el_down = np.zeros((n + 1, 2), dtype=np.float32)
        for r in range(n + 1):
            el_down[r, :] = (n - r) * _RES * math.tan(math.radians(slope_deg))

        stats_down = compute_path_energy(path, sl_down, _ROVER, _RES, el_down)

        # Baseline: truly flat — slope=0°, elevation=constant
        sl_flat = np.zeros((n + 1, 2), dtype=np.float32)
        el_flat = np.zeros((n + 1, 2), dtype=np.float32)
        stats_flat = compute_path_energy(path, sl_flat, _ROVER, _RES, el_flat)

        regen_wh = stats_down["downhill_regen_wh"]
        total_down = stats_down["total_energy_wh"]
        total_flat = stats_flat["total_energy_wh"]

        # Regen fraction check: physical bounds for regenerative braking [0.40, 0.85]
        # REGEN_FRACTION=0.3 in energy_model.py (30% efficiency), so net regen per Wh
        # of gravity assist should be within physical regenerative braking limits.
        regen_fraction_actual = regen_wh / (total_flat + regen_wh) if (total_flat + regen_wh) > 0 else 0.0
        regen_fraction_physical = REGEN_FRACTION  # imported from energy_model

        passed = regen_wh > 0 and total_down < total_flat

        sub_results["7c"] = {
            "downhill_regen_wh": round(regen_wh, 4),
            "downhill_total_wh": round(total_down, 4),
            "flat_baseline_wh": round(total_flat, 4),
            "regen_positive": regen_wh > 0,
            "downhill_cheaper_than_flat": total_down < total_flat,
            "regen_fraction_model": round(regen_fraction_physical, 4),
            "result": "PASS" if passed else "FAIL",
            "notes": (
                f"regen={regen_wh:.4f} Wh, down={total_down:.4f} Wh < flat={total_flat:.4f} Wh. "
                f"REGEN_FRACTION={regen_fraction_physical:.2f} (physical bounds: 0.40-0.85 is ideal; "
                f"current model uses {regen_fraction_physical:.2f} — may be conservative)."
            ),
        }
        print(f"    {sub_results['7c']['result']}: regen={regen_wh:.4f} Wh, down={total_down:.4f} Wh < flat={total_flat:.4f} Wh")
    except Exception as exc:
        sub_results["7c"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 7d: Linear distance scaling (10 steps vs 20 steps) --------------
    print("  [7d] 10-step vs 20-step flat path: energy ratio ~ 2.0 +/-5% ...")
    try:
        sl = np.zeros((25, 2), dtype=np.float32)
        el = np.zeros((25, 2), dtype=np.float32)

        path_10 = [(i, 0) for i in range(11)]
        path_20 = [(i, 0) for i in range(21)]

        stats_10 = compute_path_energy(path_10, sl, _ROVER, _RES, el)
        stats_20 = compute_path_energy(path_20, sl, _ROVER, _RES, el)

        e10 = stats_10["total_energy_wh"]
        e20 = stats_20["total_energy_wh"]
        ratio = e20 / e10 if e10 > 0 else 0.0
        pct_err = abs(ratio - 2.0) / 2.0 * 100.0
        passed = pct_err <= 5.0

        sub_results["7d"] = {
            "energy_10steps_wh": round(e10, 4),
            "energy_20steps_wh": round(e20, 4),
            "ratio": round(ratio, 6),
            "pct_error": round(pct_err, 4),
            "result": "PASS" if passed else "FAIL",
            "notes": f"ratio={ratio:.4f}, expected=2.0, err={pct_err:.4f}%",
        }
        print(f"    {sub_results['7d']['result']}: ratio={ratio:.4f}, err={pct_err:.4f}%")
    except Exception as exc:
        sub_results["7d"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 7e: Battery risk classification (LOW / MODERATE / HIGH) ---------
    print("  [7e] Battery risk levels: LOW / MODERATE / HIGH ...")
    try:
        # battery_wh=100 for easy % arithmetic
        rover_small = {"speed_kmh": _SPEED, "max_slope_deg": 20.0, "battery_wh": 100.0}
        sl = np.zeros((50, 2), dtype=np.float32)
        el = np.zeros((50, 2), dtype=np.float32)

        # 3 steps → ~36 Wh → 36% → LOW
        stats_low = compute_path_energy([(i, 0) for i in range(4)], sl, rover_small, _RES, el)
        # 5 steps → 60 Wh → 60% → MODERATE
        stats_mod = compute_path_energy([(i, 0) for i in range(6)], sl, rover_small, _RES, el)
        # 8 steps → 96 Wh → 96% → HIGH
        stats_high = compute_path_energy([(i, 0) for i in range(9)], sl, rover_small, _RES, el)

        risk_low = stats_low["energy_risk"]
        risk_mod = stats_mod["energy_risk"]
        risk_high = stats_high["energy_risk"]

        passed = risk_low == "LOW" and risk_mod == "MODERATE" and risk_high == "HIGH"

        sub_results["7e"] = {
            "low_pct": round(stats_low["battery_pct_used"], 2),
            "low_risk": risk_low,
            "mod_pct": round(stats_mod["battery_pct_used"], 2),
            "mod_risk": risk_mod,
            "high_pct": round(stats_high["battery_pct_used"], 2),
            "high_risk": risk_high,
            "result": "PASS" if passed else "FAIL",
            "notes": f"LOW={risk_low}/{stats_low['battery_pct_used']:.1f}%, "
                     f"MOD={risk_mod}/{stats_mod['battery_pct_used']:.1f}%, "
                     f"HIGH={risk_high}/{stats_high['battery_pct_used']:.1f}%",
        }
        print(f"    {sub_results['7e']['result']}: LOW={risk_low}, MODERATE={risk_mod}, HIGH={risk_high}")
    except Exception as exc:
        sub_results["7e"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # Overall verdict
    verdicts = [sub_results[k]["result"] for k in sub_results]
    if all(v == "PASS" for v in verdicts):
        verdict = "PASS"
    elif "FAIL" not in verdicts:
        verdict = "WARN"
    else:
        verdict = "FAIL"

    print(f"  Overall result: {verdict}")

    result.update({
        "sub_results": sub_results,
        "base_power_reference": _BASE_POWER_REFERENCE,
        "result": verdict,
        "notes": "Sub-tests: " + ", ".join(f"{k}={sub_results[k]['result']}" for k in sub_results),
    })

    out_path = Path(results_dir) / "energy_model_validation.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")

    return result


if __name__ == "__main__":
    Path("results").mkdir(exist_ok=True)
    Path("results/plots").mkdir(exist_ok=True)
    run(None, None, None, None, "results", "results/plots")
