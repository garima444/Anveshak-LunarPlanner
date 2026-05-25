"""
validation/test_ancillary_layers.py — Test 12: Ancillary Layers Integrity.

Validates that the PSR mask, solar illumination, and Earth-visibility files
load correctly and produce physically sensible values. These files exist in
data/ but were not tested by any prior validation.

Sub-tests:
  12a: illumination_map in [0, 1]; non-zero coverage at high latitudes
  12b: psr_mask is near-binary (values ≈ 0 or 1); PSR pixels exist at pole
  12c: earth_visibility in [0, 1]
  12d: water-ice rover safety scores differ inside vs outside PSR pixels
  12e: solar rover scores lower in low-illumination zones vs RTG rover
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from core.landing_scorer import score_terrain


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 12] Ancillary Layers Integrity")
    result = {"test_name": "Ancillary Layers Integrity"}

    checks = {}
    warnings = []
    failures = []

    # ---- 12a: Illumination map -----------------------------------------------
    print("  [12a] illumination_map …")
    illum = profile.get("illumination_map")
    if illum is None:
        warnings.append("illumination_map not loaded (ancillary file missing — check data/SolarIllumination/)")
        checks["12a_illumination"] = "SKIP"
        print("    SKIP: not loaded")
    else:
        finite = illum[np.isfinite(illum)]
        lo, hi = float(finite.min()), float(finite.max())
        checks["12a_illum_range"] = [round(lo, 4), round(hi, 4)]
        checks["12a_illum_shape"] = list(illum.shape)
        try:
            assert lo >= -1e-4, f"illumination_map min {lo:.4f} < 0"
            assert hi <= 1.0 + 1e-4, f"illumination_map max {hi:.4f} > 1"
            coverage = float(np.mean(np.isfinite(illum)))
            checks["12a_coverage_frac"] = round(coverage, 4)
            assert coverage > 0.5, f"illumination_map has only {coverage*100:.1f}% finite pixels"
            checks["12a_illumination"] = "PASS"
            print(f"    PASS: range=[{lo:.4f}, {hi:.4f}], coverage={coverage*100:.1f}%")
        except AssertionError as e:
            checks["12a_illumination"] = "FAIL"
            failures.append(f"12a: {e}")
            print(f"    FAIL: {e}")

    # ---- 12b: PSR mask -------------------------------------------------------
    print("  [12b] psr_mask …")
    psr = profile.get("psr_mask")
    if psr is None:
        warnings.append("psr_mask not loaded (ancillary file missing — check data/PSR/)")
        checks["12b_psr_mask"] = "SKIP"
        print("    SKIP: not loaded")
    else:
        finite_psr = psr[np.isfinite(psr)]
        checks["12b_psr_shape"] = list(psr.shape)
        try:
            # PSR mask should be near-binary: most values should be ≈ 0 or ≈ 1
            intermediate = float(np.mean((finite_psr > 0.05) & (finite_psr < 0.95)))
            checks["12b_intermediate_frac"] = round(intermediate, 4)
            assert intermediate < 0.10, (
                f"PSR mask has {intermediate*100:.1f}% intermediate values — "
                f"expected near-binary (0=lit, 1=shadowed)"
            )
            psr_fraction = float(np.mean(finite_psr >= 0.5))
            checks["12b_psr_coverage_frac"] = round(psr_fraction, 4)
            assert psr_fraction > 0.01, (
                f"PSR fraction {psr_fraction*100:.2f}% — expected >1% (south pole has PSRs)"
            )
            checks["12b_psr_mask"] = "PASS"
            print(f"    PASS: PSR coverage={psr_fraction*100:.1f}%, intermediate={intermediate*100:.1f}%")
        except AssertionError as e:
            checks["12b_psr_mask"] = "FAIL"
            failures.append(f"12b: {e}")
            print(f"    FAIL: {e}")

    # ---- 12c: Earth visibility -----------------------------------------------
    print("  [12c] earth_visibility …")
    earth = profile.get("earth_visibility")
    if earth is None:
        warnings.append("earth_visibility not loaded (ancillary file missing — check data/EarthVisibility/)")
        checks["12c_earth_visibility"] = "SKIP"
        print("    SKIP: not loaded")
    else:
        finite_e = earth[np.isfinite(earth)]
        lo_e, hi_e = float(finite_e.min()), float(finite_e.max())
        checks["12c_earth_range"] = [round(lo_e, 4), round(hi_e, 4)]
        try:
            assert lo_e >= -1e-4 and hi_e <= 1.0 + 1e-4, f"earth_visibility out of [0,1]: [{lo_e:.4f},{hi_e:.4f}]"
            checks["12c_earth_visibility"] = "PASS"
            print(f"    PASS: range=[{lo_e:.4f}, {hi_e:.4f}]")
        except AssertionError as e:
            checks["12c_earth_visibility"] = "FAIL"
            failures.append(f"12c: {e}")
            print(f"    FAIL: {e}")

    # ---- 12d: PSR influences water-ice rover safety -------------------------
    # Use a 2000×2000 crop centred on the south pole to avoid OOM on full DEM.
    # This crop always contains PSR pixels (south polar crater interiors).
    print("  [12d] PSR influence on landing safety (2000x2000 crop) …")
    if psr is None or not np.any(psr >= 0.5):
        warnings.append("12d skipped: no PSR pixels available")
        checks["12d_psr_safety"] = "SKIP"
        print("    SKIP: no PSR data")
    else:
        try:
            H12, W12 = elevation.shape
            CROP = 2000
            r0 = max(0, H12 // 2 - CROP // 2)
            c0 = max(0, W12 // 2 - CROP // 2)
            r1, c1 = r0 + CROP, c0 + CROP
            crop_elev  = elevation[r0:r1, c0:c1]
            crop_slope = slope    [r0:r1, c0:c1]
            crop_rough = roughness[r0:r1, c0:c1]
            crop_psr   = psr      [r0:r1, c0:c1]
            import copy as _copy
            from affine import Affine as _Affine
            orig_t = profile["transform"]
            crop_prof = _copy.copy(profile)
            crop_prof.update({
                "height": CROP, "width": CROP,
                "transform": _Affine(orig_t.a, orig_t.b, orig_t.c + c0 * orig_t.a,
                                     orig_t.d, orig_t.e, orig_t.f + r0 * orig_t.e),
            })
            for ak in ("psr_mask","illumination_map","earth_visibility","sky_visibility",
                       "diviner_coltemp","quality_mask","sunlight_map"):
                if profile.get(ak) is not None:
                    crop_prof[ak] = profile[ak][r0:r1, c0:c1]
            rover_wice = {
                "mission_type": "water_ice", "power_source": "rtg",
                "max_slope_deg": 20.0, "min_flat_radius_m": 200.0, "priority": 0.5,
                "psr_intent": "enter",
            }
            safety_wice, _, _, _ = score_terrain(crop_elev, crop_slope, crop_rough, crop_prof, rover_wice)
            psr = crop_psr

            psr_pixels = psr >= 0.5
            nonpsr_pixels = (psr < 0.5) & (safety_wice > 0)

            if psr_pixels.any() and nonpsr_pixels.any():
                mean_safety_psr    = float(np.nanmean(safety_wice[psr_pixels]))
                mean_safety_nonpsr = float(np.nanmean(safety_wice[nonpsr_pixels]))
                checks["12d_mean_safety_inside_psr"]  = round(mean_safety_psr, 4)
                checks["12d_mean_safety_outside_psr"] = round(mean_safety_nonpsr, 4)
                # PSR interiors are rougher/steeper → safety should generally be lower inside
                # (We accept either direction since some PSRs are flat; check that they differ)
                diff = abs(mean_safety_psr - mean_safety_nonpsr)
                assert diff > 0.02, (
                    f"Safety scores inside vs outside PSR differ by only {diff:.4f} — "
                    f"PSR mask may not be influencing scores"
                )
                checks["12d_psr_safety"] = "PASS"
                print(f"    PASS: inside_PSR={mean_safety_psr:.4f}, outside_PSR={mean_safety_nonpsr:.4f}, diff={diff:.4f}")
            else:
                warnings.append("12d: insufficient passable pixels in/out of PSR for comparison")
                checks["12d_psr_safety"] = "WARN"
                print("    WARN: not enough passable pixels for comparison")
        except Exception as exc:
            checks["12d_psr_safety"] = "FAIL"
            failures.append(f"12d: {exc}")
            print(f"    FAIL: {exc}")

    # ---- 12e: Solar hard-constraint in PSR + PSR-adjacent mission score gap ----
    # Two sub-assertions:
    #   (A) Solar rover final score inside PSR must be identically 0.
    #       Physically: solar panels receive zero flux in permanent shadow — the rover
    #       cannot operate, charge, or land safely there.
    #       Source: NASA VIPER Mission Design Document (NASA/TM-2022-217504, §4.2).
    #   (B) RTG rover must score positively inside the same PSR pixels — nuclear power
    #       is unaffected by illumination, so no hard zero applies.
    #       Source: Chang'e-7 Lunar Ice Explorer concept (Xiao et al. 2021, Nat. Astron.).
    #   Together these two assertions confirm that the power_source field drives different
    #   landing-site recommendations in dark terrain (the primary discriminator).
    print("  [12e] Solar hard-constraint in PSR; RTG positive in PSR (2000x2000 crop) …")
    # Reuse crop from 12d; fall back if 12d was skipped.
    try:
        _e12e, _s12e, _r12e, _p12e = crop_elev, crop_slope, crop_rough, crop_prof
        _psr12e = psr  # psr was reassigned to crop_psr inside 12d
    except NameError:
        _e12e, _s12e, _r12e, _p12e = elevation, slope, roughness, profile
        _psr12e = profile.get("psr_mask")

    if _psr12e is None or not np.any(_psr12e >= 0.5):
        warnings.append("12e skipped: no PSR pixels available in crop")
        checks["12e_solar_rtg"] = "SKIP"
        print("    SKIP: no PSR data")
    else:
        try:
            rover_solar = {
                "mission_type": "water_ice", "power_source": "solar",
                "max_slope_deg": 15.0, "min_flat_radius_m": 300.0, "priority": 0.5,
            }
            rover_rtg = dict(rover_solar, power_source="rtg")

            _, _, final_solar, _ = score_terrain(_e12e, _s12e, _r12e, _p12e, rover_solar)
            _, _, final_rtg,   _ = score_terrain(_e12e, _s12e, _r12e, _p12e, rover_rtg)

            # Assertion A: solar scores in PSR must be 0
            psr_pixels = (_psr12e >= 0.5)
            solar_in_psr = final_solar[psr_pixels]
            mean_solar_psr = float(np.nanmean(solar_in_psr))
            max_solar_psr  = float(np.nanmax(solar_in_psr))
            checks["12e_mean_solar_inside_psr"] = round(mean_solar_psr, 6)
            checks["12e_max_solar_inside_psr"]  = round(max_solar_psr, 6)
            assert max_solar_psr < 1e-5, (
                f"Solar rover has non-zero final score ({max_solar_psr:.6f}) inside PSR — "
                f"hard-zero constraint not applied (power_source='solar' must zero PSR pixels)"
            )

            # Assertion B: RTG must score positively in some PSR pixels
            rtg_in_psr = final_rtg[psr_pixels]
            mean_rtg_psr  = float(np.nanmean(rtg_in_psr[rtg_in_psr > 0])) if np.any(rtg_in_psr > 0) else 0.0
            frac_rtg_pos  = float(np.mean(rtg_in_psr > 0))
            checks["12e_mean_rtg_inside_psr"]  = round(mean_rtg_psr, 4)
            checks["12e_frac_rtg_pos_in_psr"]  = round(frac_rtg_pos, 4)
            assert mean_rtg_psr > 0.01, (
                f"RTG rover scores unexpectedly near-zero inside PSR (mean={mean_rtg_psr:.4f}) — "
                f"nuclear-power constraint should NOT zero PSR pixels"
            )

            checks["12e_solar_rtg"] = "PASS"
            print(
                f"    PASS: solar_in_PSR_max={max_solar_psr:.6f} (must=0), "
                f"rtg_in_PSR_mean={mean_rtg_psr:.4f} (must>0), "
                f"rtg_passable_frac={frac_rtg_pos*100:.1f}%"
            )
        except AssertionError as exc:
            checks["12e_solar_rtg"] = "FAIL"
            failures.append(f"12e: {exc}")
            print(f"    FAIL: {exc}")
        except Exception as exc:
            checks["12e_solar_rtg"] = "FAIL"
            failures.append(f"12e: {exc}")
            print(f"    FAIL: {exc}")

    # ---- Overall verdict ----------------------------------------------------
    sub_results = [checks.get(k) for k in ["12a_illumination","12b_psr_mask","12c_earth_visibility","12d_psr_safety","12e_solar_rtg"]]
    if failures or "FAIL" in sub_results:
        verdict = "FAIL"
    elif warnings or "WARN" in sub_results:
        verdict = "WARN"
    elif all(v == "SKIP" for v in sub_results if v is not None):
        verdict = "WARN"
    else:
        verdict = "PASS"

    print(f"  Overall: {verdict}")

    result.update({
        "checks":   checks,
        "warnings": warnings,
        "failures": failures,
        "result":   verdict,
        "notes": (
            f"Sub-tests: " + ", ".join(f"{k}={v}" for k, v in checks.items() if k.endswith(("_illumination","_psr_mask","_earth_visibility","_psr_safety","_solar_rtg")))
            + (f". Warnings: {warnings}" if warnings else "")
            + (f". Failures: {failures}" if failures else "")
        ),
    })

    out_path = Path(results_dir) / "ancillary_layers.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")

    return result


if __name__ == "__main__":
    from core.landing_scorer import _synthetic_terrain
    try:
        from core.terrain import load_terrain
        elev, sl, rough, prof = load_terrain()
    except Exception:
        elev, sl, rough, prof = _synthetic_terrain(shape=(500, 500))
    Path("results").mkdir(exist_ok=True)
    Path("results/plots").mkdir(exist_ok=True)
    run(elev, sl, rough, prof, "results", "results/plots")
