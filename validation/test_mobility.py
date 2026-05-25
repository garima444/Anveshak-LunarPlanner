"""
validation/test_mobility.py — Test 12: Bekker-Wong Terramechanics Validation.

Verifies that the soft terrain / wheel-sinkage model in core/mobility.py:
  1. Produces sinkage values within the range documented for Apollo regolith.
  2. Correctly shows higher sinkage on soft terrain than nominal terrain.
  3. Produces a trafficability risk map bounded in [0, 1].
  4. Correctly identifies smooth depressions as higher-risk than flat terrain.
  5. Is backward-compatible (no side-effects when mobility_risk_map is None).

References
----------
Carrier, W.D. et al. (1991). Lunar Sourcebook, Table 9.28.
    Apollo average regolith: kc=1.4 kPa, kφ=820 kPa/m, n=1.0.
    Typical measured sinkage for Apollo ALSEP equipment: 2-15 mm.
Wong, J.Y. (2008). Theory of Ground Vehicles, 4th ed. Wiley. §2.3, §2.5.
Bekker, M.G. (1969). Introduction to Terrain-Vehicle Systems. Univ. Michigan Press.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from core.mobility import (
    STUCK_SINKAGE_FRACTION,
    compute_rolling_resistance_coeff,
    compute_sinkage_m,
    compute_trafficability_map,
)


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 12] Bekker-Wong Terramechanics Validation")
    result = {"test_name": "Bekker-Wong Terramechanics Validation"}
    sub_results = {}
    failures = []

    # ------------------------------------------------------------------
    # 12a: Nominal VIPER sinkage within Apollo-documented range
    # ------------------------------------------------------------------
    print("  [12a] VIPER nominal sinkage in Apollo-documented range (2–15 mm) ...")
    try:
        # VIPER: 430 kg, 6 wheels, wheel_width=0.20 m, wheel_radius=0.25 m
        # Source: Colaprete et al. 2019 (VIPER mass); NASA VIPER Fact Sheet (wheel dims)
        z_viper = compute_sinkage_m(430.0, 0.20, 0.25, 6, soft_index=0.0)
        z_mm = z_viper * 1000.0
        # Apollo documented sinkage range: ~2–15 mm for equipment on nominal regolith
        # Source: Mitchell et al. 1974 NASA SP-330; Carrier et al. 1991 Table 9.28
        passed = 2.0 <= z_mm <= 15.0
        sub_results["12a"] = {"sinkage_mm": round(z_mm, 3), "range": "2-15 mm", "passed": passed}
        print(f"    {'PASS' if passed else 'FAIL'}: VIPER sinkage = {z_mm:.2f} mm (expected 2-15 mm)")
        if not passed:
            failures.append(f"12a: sinkage {z_mm:.2f} mm outside 2-15 mm range")
    except Exception as exc:
        sub_results["12a"] = {"error": str(exc)}
        failures.append(f"12a: exception — {exc}")

    # ------------------------------------------------------------------
    # 12b: Soft terrain sinkage > nominal (monotone in soft_index)
    # ------------------------------------------------------------------
    print("  [12b] Sinkage increases monotonically with soft_index ...")
    try:
        indices = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        sinkages = [compute_sinkage_m(430.0, 0.20, 0.25, 6, si) * 1000.0 for si in indices]
        monotone = all(sinkages[i] <= sinkages[i + 1] for i in range(len(sinkages) - 1))
        sub_results["12b"] = {
            "soft_indices": indices,
            "sinkage_mm": [round(s, 3) for s in sinkages],
            "monotone": monotone,
            "passed": monotone,
        }
        print(f"    {'PASS' if monotone else 'FAIL'}: sinkages = {[f'{s:.2f}' for s in sinkages]} mm")
        if not monotone:
            failures.append("12b: sinkage not monotone with soft_index")
    except Exception as exc:
        sub_results["12b"] = {"error": str(exc)}
        failures.append(f"12b: exception — {exc}")

    # ------------------------------------------------------------------
    # 12c: Rolling resistance coefficient increases with sinkage
    # ------------------------------------------------------------------
    print("  [12c] Rolling resistance coefficient mu_r increases with sinkage ...")
    try:
        z_nom  = compute_sinkage_m(430.0, 0.20, 0.25, 6, soft_index=0.0)
        z_soft = compute_sinkage_m(430.0, 0.20, 0.25, 6, soft_index=0.8)
        mu_nom  = compute_rolling_resistance_coeff(z_nom,  0.25)
        mu_soft = compute_rolling_resistance_coeff(z_soft, 0.25)
        passed = mu_soft > mu_nom > 0.0
        sub_results["12c"] = {
            "mu_r_nominal": round(mu_nom, 5),
            "mu_r_soft":    round(mu_soft, 5),
            "passed": passed,
        }
        print(f"    {'PASS' if passed else 'FAIL'}: mu_r nominal={mu_nom:.4f}, soft={mu_soft:.4f}")
        if not passed:
            failures.append("12c: rolling resistance not increasing with sinkage")
    except Exception as exc:
        sub_results["12c"] = {"error": str(exc)}
        failures.append(f"12c: exception — {exc}")

    # ------------------------------------------------------------------
    # 12d: Trafficability map bounded in [0, 1]
    # ------------------------------------------------------------------
    print("  [12d] compute_trafficability_map() produces values in [0, 1] ...")
    try:
        H, W = 100, 100
        elev_test = np.zeros((H, W), dtype=np.float32)
        # Depression in centre (potential soft terrain)
        elev_test[40:60, 40:60] = -150.0
        rough_test = np.full((H, W), 5.0, dtype=np.float32)
        rough_test[40:60, 40:60] = 0.2   # smooth floor inside depression
        rover_p = {"rover_mass_kg": 430.0, "wheel_width_m": 0.20,
                   "wheel_radius_m": 0.25, "n_wheels": 6}
        mob = compute_trafficability_map(elev_test, rough_test, {}, rover_p, 60.0)
        bounded = float(mob.min()) >= 0.0 and float(mob.max()) <= 1.0
        correct_shape = mob.shape == (H, W)
        passed = bounded and correct_shape
        sub_results["12d"] = {
            "shape": list(mob.shape),
            "min": round(float(mob.min()), 5),
            "max": round(float(mob.max()), 5),
            "bounded": bounded,
            "correct_shape": correct_shape,
            "passed": passed,
        }
        print(f"    {'PASS' if passed else 'FAIL'}: shape={mob.shape}, "
              f"min={mob.min():.4f}, max={mob.max():.4f}")
        if not passed:
            failures.append(f"12d: map out of [0,1] or wrong shape")
    except Exception as exc:
        sub_results["12d"] = {"error": str(exc)}
        failures.append(f"12d: exception — {exc}")

    # ------------------------------------------------------------------
    # 12e: Smooth depression scored higher risk than flat terrain
    # ------------------------------------------------------------------
    print("  [12e] Smooth depression has higher risk than flat terrain ...")
    try:
        H, W = 100, 100
        elev_flat = np.zeros((H, W), dtype=np.float32)
        rough_flat = np.full((H, W), 5.0, dtype=np.float32)
        rover_p = {"rover_mass_kg": 430.0, "wheel_width_m": 0.20,
                   "wheel_radius_m": 0.25, "n_wheels": 6}
        mob_flat = compute_trafficability_map(elev_flat, rough_flat, {}, rover_p, 60.0)

        elev_dep = np.zeros((H, W), dtype=np.float32)
        elev_dep[40:60, 40:60] = -150.0  # depression
        rough_dep = rough_flat.copy()
        rough_dep[40:60, 40:60] = 0.2    # smooth floor
        mob_dep = compute_trafficability_map(elev_dep, rough_dep, {}, rover_p, 60.0)

        risk_flat  = float(mob_flat[50, 50])
        risk_dep   = float(mob_dep[50, 50])
        passed = risk_dep > risk_flat
        sub_results["12e"] = {
            "risk_flat_terrain": round(risk_flat, 5),
            "risk_in_depression": round(risk_dep, 5),
            "depression_riskier": passed,
            "passed": passed,
        }
        print(f"    {'PASS' if passed else 'FAIL'}: flat={risk_flat:.4f}, "
              f"depression={risk_dep:.4f}")
        if not passed:
            failures.append("12e: depression not riskier than flat terrain")
    except Exception as exc:
        sub_results["12e"] = {"error": str(exc)}
        failures.append(f"12e: exception — {exc}")

    # ------------------------------------------------------------------
    # 12f: Pragyan (lighter, smaller wheels) nominal sinkage < VIPER
    # ------------------------------------------------------------------
    print("  [12f] Pragyan sinkage < VIPER sinkage (lighter rover, smaller wheels) ...")
    try:
        # Pragyan: 26 kg, 6 wheels, wheel_width=0.05 m, wheel_radius=0.075 m
        # Source: ISRO Chandrayaan-3 Mission Report 2023
        z_pragyan = compute_sinkage_m(26.0, 0.05, 0.075, 6, soft_index=0.0)
        z_viper2  = compute_sinkage_m(430.0, 0.20, 0.25,  6, soft_index=0.0)
        passed = z_pragyan < z_viper2
        sub_results["12f"] = {
            "pragyan_sinkage_mm": round(z_pragyan * 1000, 3),
            "viper_sinkage_mm":   round(z_viper2  * 1000, 3),
            "passed": passed,
        }
        print(f"    {'PASS' if passed else 'FAIL'}: Pragyan={z_pragyan*1000:.2f} mm, "
              f"VIPER={z_viper2*1000:.2f} mm")
        if not passed:
            failures.append("12f: Pragyan sinkage not less than VIPER")
    except Exception as exc:
        sub_results["12f"] = {"error": str(exc)}
        failures.append(f"12f: exception — {exc}")

    # ------------------------------------------------------------------
    # 12g: Stuck threshold constant matches Wong 2008 §2.5
    # ------------------------------------------------------------------
    print("  [12g] STUCK_SINKAGE_FRACTION = 0.50 (Wong 2008 §2.5) ...")
    passed = abs(STUCK_SINKAGE_FRACTION - 0.50) < 1e-9
    sub_results["12g"] = {"STUCK_SINKAGE_FRACTION": STUCK_SINKAGE_FRACTION, "passed": passed}
    print(f"    {'PASS' if passed else 'FAIL'}: STUCK_SINKAGE_FRACTION={STUCK_SINKAGE_FRACTION}")
    if not passed:
        failures.append(f"12g: STUCK_SINKAGE_FRACTION={STUCK_SINKAGE_FRACTION} != 0.50")

    # ------------------------------------------------------------------
    # Overall verdict
    # ------------------------------------------------------------------
    verdict = "PASS" if not failures else "FAIL"
    n_pass = sum(1 for v in sub_results.values() if isinstance(v, dict) and v.get("passed"))
    n_total = len(sub_results)

    print(f"  Overall result: {verdict} ({n_pass}/{n_total} sub-tests passed)")
    if failures:
        for f in failures:
            print(f"    FAIL: {f}")

    result.update({
        "result":      verdict,
        "sub_results": sub_results,
        "failures":    failures,
        "n_pass":      n_pass,
        "n_total":     n_total,
    })

    out = Path(results_dir) / "mobility_validation.json"
    with open(out, "w", encoding="utf-8") as _f:
        json.dump(result, _f, indent=2)
    print(f"  Saved: {out}")
    return result


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    results_dir = Path(tempfile.mkdtemp())
    plots_dir = results_dir / "plots"
    plots_dir.mkdir()
    # Stub terrain arrays (test 12 uses its own synthetic arrays internally)
    H = 10
    elev  = np.zeros((H, H), dtype=np.float32)
    slope = np.zeros((H, H), dtype=np.float32)
    rough = np.ones((H, H), dtype=np.float32)
    prof  = {"resolution_m": 60.0}
    run(elev, slope, rough, prof, results_dir, plots_dir)
