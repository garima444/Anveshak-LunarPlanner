"""
validation/test_combinations_fast.py — Test 15: Input Combination Coverage (Fast/Synthetic).

Verifies all 8 practically valid mission-input combinations and the 1 hard-invalid
combination on synthetic terrain.  No real DEM required — runs in ~15–25 s total.

Combinations tested
-------------------
C1  water_ice  / rtg   / enter   (Chang'e-7 ice-sampler)
C2  water_ice  / rtg   / rim     (NASA VIPER)
C3  water_ice  / solar / rim     (Solar PSR-rim rover)
C4  water_ice  / solar / avoid   (Chandrayaan-3 class)
C5  geological / rtg   / rim     (Artemis LTV)
C6  geological / solar / avoid   (Chang'e-4 / Yutu-2)
C7  atmospheric/ rtg   / avoid   (Luna-27)
C8  atmospheric/ solar / avoid   (Solar atmospheric science)
X   water_ice  / solar / enter   ← INVALID: solar cannot recharge in PSR

Universal checks (all 8 valid combos)
--------------------------------------
- score_terrain() does not raise
- safety / mission / final arrays: shape (H,W), dtype float32, range [0,1]
- len(top_sites) >= 1 and top_sites[0]["final_score"] > 0
- All required keys present in each top-site dict
- Impassable pixels (slope > max_slope_deg) have safety_score == 0
- final_score is zero wherever safety_score is zero (hard safety gate)

Per-combo physics checks (on synthetic terrain, no ancillary layers)
----------------------------------------------------------------------
C1  water_ice/rtg/enter  : top site mission_score > 0 (no PSR penalty for RTG+enter)
C2  water_ice/rtg/rim    : top site final_score > 0 (rim scoring active)
C3  water_ice/solar/rim  : top site final_score > 0; if PSR map present → no site in PSR
C4  water_ice/solar/avoid: top site final_score > 0 (avoid scoring active)
C5  geological/rtg/rim   : mean top-3 mission_score > 0.60 (geological diversity scorer)
C6  geological/solar/avoid: mean top-3 mission_score > 0.60 (same scorer, solar variant)
C7  atmospheric/rtg/avoid: mean top-3 elevation > DEM median (ridge-top preference)
C8  atmospheric/solar/avoid: mean top-3 elevation > DEM median

Invalid combo check
-------------------
X  water_ice/solar/enter : scorer must not crash (constraint enforced at app layer via
   PSR map; noted as WARN rather than PASS to flag the combination as intentionally excluded)

Standalone usage:
    python validation/test_combinations_fast.py

Output:
    validation/results/combinations_fast.json
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import io

import numpy as np

from core.landing_scorer import _synthetic_terrain, score_terrain
from core.pathfinder import find_path


def _ensure_utf8_stdout() -> None:
    """
    On Windows the default console encoding is cp1252 / charmap.
    score_terrain() prints Unicode arrows (→ U+2192) that raise UnicodeEncodeError
    on those encodings.  Re-wrap stdout/stderr once so all subsequent print() calls
    use UTF-8 with replacement characters instead of crashing.
    """
    if sys.platform == "win32":
        for stream_name in ("stdout", "stderr"):
            stream = getattr(sys, stream_name)
            if hasattr(stream, "buffer") and getattr(stream, "encoding", "utf-8").lower() not in ("utf-8", "utf8"):
                setattr(sys, stream_name,
                        io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace", line_buffering=True))

# ---------------------------------------------------------------------------
# Rover presets (identical to test_combinations.py)
# ---------------------------------------------------------------------------

_PRESETS: dict[str, dict] = {
    "viper": {
        "max_slope_deg": 20.0, "min_flat_radius_m": 300.0,
        "wheel_radius_m": 0.25,  "rover_mass_kg": 430.0,
        "wheel_width_m": 0.20,   "n_wheels": 6,
        "speed_kmh": 0.6,        "battery_wh": 450.0,
        "slope_penalty_factor": 15.0,
    },
    "pragyan": {
        "max_slope_deg": 12.0, "min_flat_radius_m": 200.0,
        "wheel_radius_m": 0.075, "rover_mass_kg": 26.0,
        "wheel_width_m": 0.05,   "n_wheels": 6,
        "speed_kmh": 0.036,      "battery_wh": 50.0,
        "slope_penalty_factor": 15.0,
    },
    "yutu2": {
        "max_slope_deg": 20.0, "min_flat_radius_m": 250.0,
        "wheel_radius_m": 0.15,  "rover_mass_kg": 140.0,
        "wheel_width_m": 0.12,   "n_wheels": 6,
        "speed_kmh": 0.2,        "battery_wh": 52.0,
        "slope_penalty_factor": 15.0,
    },
    "custom": {
        "max_slope_deg": 15.0, "min_flat_radius_m": 400.0,
        "wheel_radius_m": 0.25,  "rover_mass_kg": 200.0,
        "wheel_width_m": 0.20,   "n_wheels": 6,
        "speed_kmh": 0.5,        "battery_wh": 1000.0,
        "slope_penalty_factor": 15.0,
    },
}

_SOLAR_EXTRA: dict = {"solar_panel_w": 50.0, "mission_day": 7.4}

# ---------------------------------------------------------------------------
# Combination definitions (identical to test_combinations.py)
# ---------------------------------------------------------------------------

COMBINATIONS: list[dict] = [
    {
        "id": "c1_water_ice_rtg_enter",
        "label": "C1",
        "rover_name": "RTG-Driller",
        "mission_type": "water_ice",
        "power_source": "rtg",
        "psr_intent": "enter",
        "preset": "viper",
        "priority": 0.5,
        "analogue": "Chang'e-7 ice-sampler concept",
    },
    {
        "id": "c2_water_ice_rtg_rim",
        "label": "C2",
        "rover_name": "VIPER-Clone",
        "mission_type": "water_ice",
        "power_source": "rtg",
        "psr_intent": "rim",
        "preset": "viper",
        "priority": 0.5,
        "analogue": "NASA VIPER operational concept",
    },
    {
        "id": "c3_water_ice_solar_rim",
        "label": "C3",
        "rover_name": "Solar-Scout",
        "mission_type": "water_ice",
        "power_source": "solar",
        "psr_intent": "rim",
        "preset": "viper",
        "priority": 0.5,
        "analogue": "Solar PSR-rim rover",
    },
    {
        "id": "c4_water_ice_solar_avoid",
        "label": "C4",
        "rover_name": "Pragyan-II",
        "mission_type": "water_ice",
        "power_source": "solar",
        "psr_intent": "avoid",
        "preset": "pragyan",
        "priority": 0.3,
        "analogue": "Solar rover avoiding shadow (Chandrayaan-3 class)",
    },
    {
        "id": "c5_geological_rtg_rim",
        "label": "C5",
        "rover_name": "Geo-RTG",
        "mission_type": "geological",
        "power_source": "rtg",
        "psr_intent": "rim",
        "preset": "yutu2",
        "priority": 0.7,
        "analogue": "RTG geology rover near PSR boundary",
    },
    {
        "id": "c6_geological_solar_avoid",
        "label": "C6",
        "rover_name": "Yutu-2-Clone",
        "mission_type": "geological",
        "power_source": "solar",
        "psr_intent": "avoid",
        "preset": "yutu2",
        "priority": 0.7,
        "analogue": "Chang'e-4 type geology mission",
    },
    {
        "id": "c7_atmospheric_rtg_avoid",
        "label": "C7",
        "rover_name": "Atmos-RTG",
        "mission_type": "atmospheric",
        "power_source": "rtg",
        "psr_intent": "avoid",
        "preset": "custom",
        "priority": 0.6,
        "analogue": "RTG exosphere / atmospheric science rover",
    },
    {
        "id": "c8_atmospheric_solar_avoid",
        "label": "C8",
        "rover_name": "Atmos-Solar",
        "mission_type": "atmospheric",
        "power_source": "solar",
        "psr_intent": "avoid",
        "preset": "custom",
        "priority": 0.6,
        "analogue": "Solar atmospheric science rover",
    },
]

_INVALID_COMBO: dict = {
    "id": "x_water_ice_solar_enter",
    "label": "X",
    "rover_name": "Invalid-Solar-PSR",
    "mission_type": "water_ice",
    "power_source": "solar",
    "psr_intent": "enter",
    "preset": "viper",
    "priority": 0.5,
    "analogue": "INVALID — solar cannot recharge in PSR",
}

# Keys every top-site dict must contain
_TOP_SITE_KEYS = frozenset({
    "rank", "pixel_row", "pixel_col", "lon", "lat",
    "elevation_m", "slope_deg", "roughness_m",
    "safety_score", "mission_score", "final_score", "reasoning",
})


# ---------------------------------------------------------------------------
# Per-combo physics checks
# ---------------------------------------------------------------------------

def _physics_checks(
    combo: dict,
    top_sites: list[dict],
    elevation: np.ndarray,
    profile: dict,
    dem_median_elev: float,
) -> list[dict]:
    """
    Return a list of check-result dicts:
        {"check": str, "result": "PASS"|"WARN"|"FAIL", "value": str, "expected": str}
    """
    results = []
    mid = combo["id"]
    psr = profile.get("psr_mask")   # None on synthetic terrain
    illum = profile.get("illumination_map")  # None on synthetic terrain
    top3 = top_sites[:3]
    rows = [s["pixel_row"] for s in top3]
    cols = [s["pixel_col"] for s in top3]

    def _chk(name: str, ok: bool, value, expected: str, warn_not_fail: bool = False) -> dict:
        if ok:
            verdict = "PASS"
        elif warn_not_fail:
            verdict = "WARN"
        else:
            verdict = "FAIL"
        return {"check": name, "result": verdict,
                "value": str(value), "expected": expected}

    if mid == "c1_water_ice_rtg_enter":
        # RTG+enter: no penalty inside PSR → mission_score must be positive
        ms = top_sites[0]["mission_score"] if top_sites else 0.0
        results.append(_chk(
            "rtg_enter_mission_score_positive",
            ms > 0,
            f"mission_score={ms:.4f}",
            "> 0 (RTG+enter: no PSR penalty applied)",
        ))
        # top final_score must be positive
        fs = top_sites[0]["final_score"] if top_sites else 0.0
        results.append(_chk(
            "rtg_enter_final_score_positive",
            fs > 0,
            f"final_score={fs:.4f}",
            "> 0",
        ))
        # If real PSR map available: top site is allowed INSIDE PSR (non-zero)
        if psr is not None and top_sites:
            r0, c0 = rows[0], cols[0]
            in_psr = bool(psr[r0, c0] >= 0.5)
            if in_psr:
                results.append(_chk(
                    "rtg_enter_psr_site_nonzero",
                    fs > 0,
                    f"final={fs:.4f} (site is in PSR)",
                    "> 0 (enter: PSR pixels allowed)",
                ))

    elif mid == "c2_water_ice_rtg_rim":
        fs = top_sites[0]["final_score"] if top_sites else 0.0
        results.append(_chk(
            "rtg_rim_final_score_positive",
            fs > 0,
            f"final_score={fs:.4f}",
            "> 0 (rim scoring active)",
        ))
        # If real PSR map: at least 1 of top-3 within 5 km of PSR
        if psr is not None:
            from scipy.ndimage import distance_transform_edt
            dist = distance_transform_edt(psr < 0.5).astype(np.float32)
            res_m = float(profile.get("resolution_m", 60.0))
            min_dist_km = min(float(dist[r, c]) * res_m / 1000.0 for r, c in zip(rows, cols))
            results.append(_chk(
                "rtg_rim_psr_adjacent_5km",
                min_dist_km <= 5.0,
                f"min_dist={min_dist_km:.2f} km",
                "<= 5 km from PSR (rim landing strategy)",
            ))

    elif mid == "c3_water_ice_solar_rim":
        fs = top_sites[0]["final_score"] if top_sites else 0.0
        results.append(_chk(
            "solar_rim_final_score_positive",
            fs > 0,
            f"final_score={fs:.4f}",
            "> 0",
        ))
        # Hard constraint: NO top-10 site inside PSR for solar rover
        if psr is not None:
            in_psr_count = sum(1 for s in top_sites if psr[s["pixel_row"], s["pixel_col"]] >= 0.5)
            results.append(_chk(
                "solar_no_sites_in_psr",
                in_psr_count == 0,
                f"{in_psr_count} top-10 sites inside PSR",
                "0 (solar hard-zero: cannot land in PSR)",
            ))
        else:
            results.append({
                "check": "solar_no_sites_in_psr",
                "result": "PASS",
                "value": "N/A (no PSR map on synthetic terrain)",
                "expected": "0 sites in PSR when PSR map present",
            })

    elif mid == "c4_water_ice_solar_avoid":
        fs = top_sites[0]["final_score"] if top_sites else 0.0
        results.append(_chk(
            "solar_avoid_final_score_positive",
            fs > 0,
            f"final_score={fs:.4f}",
            "> 0 (avoid scoring active)",
        ))
        # If illumination map present: check top-3 are well-lit
        if illum is not None:
            mean_illum = float(np.mean([illum[r, c] for r, c in zip(rows, cols)]))
            results.append(_chk(
                "solar_avoid_top3_illuminated",
                mean_illum > 0.40,
                f"mean_illum={mean_illum:.4f}",
                "> 0.40 (avoid mode: well-lit sites required)",
            ))

    elif mid == "c5_geological_rtg_rim":
        # Geological scorer rewards roughness diversity — mission_score should be high
        mean_ms = float(np.mean([s["mission_score"] for s in top3])) if top3 else 0.0
        results.append(_chk(
            "geological_rtg_mission_score",
            mean_ms > 0.60,
            f"mean_top3_mission_score={mean_ms:.4f}",
            "> 0.60 (geological diversity scorer)",
        ))

    elif mid == "c6_geological_solar_avoid":
        mean_ms = float(np.mean([s["mission_score"] for s in top3])) if top3 else 0.0
        results.append(_chk(
            "geological_solar_mission_score",
            mean_ms > 0.60,
            f"mean_top3_mission_score={mean_ms:.4f}",
            "> 0.60 (geological diversity scorer, solar variant)",
        ))
        if illum is not None:
            mean_illum = float(np.mean([illum[r, c] for r, c in zip(rows, cols)]))
            results.append(_chk(
                "geological_solar_illumination",
                mean_illum > 0.35,
                f"mean_illum={mean_illum:.4f}",
                "> 0.35 (solar: continuous power for instruments)",
            ))

    elif mid == "c7_atmospheric_rtg_avoid":
        # Atmospheric scorer prefers ridges (high elevation)
        mean_elev = float(np.mean([elevation[r, c] for r, c in zip(rows, cols)])) if rows else 0.0
        results.append(_chk(
            "atmospheric_rtg_elevation_above_median",
            mean_elev > dem_median_elev,
            f"mean_top3_elev={mean_elev:.0f} m vs median={dem_median_elev:.0f} m",
            "> DEM median elevation (ridge tops for sky visibility)",
        ))

    elif mid == "c8_atmospheric_solar_avoid":
        mean_elev = float(np.mean([elevation[r, c] for r, c in zip(rows, cols)])) if rows else 0.0
        results.append(_chk(
            "atmospheric_solar_elevation_above_median",
            mean_elev > dem_median_elev,
            f"mean_top3_elev={mean_elev:.0f} m vs median={dem_median_elev:.0f} m",
            "> DEM median elevation",
        ))
        if illum is not None:
            mean_illum = float(np.mean([illum[r, c] for r, c in zip(rows, cols)]))
            results.append(_chk(
                "atmospheric_solar_illumination",
                mean_illum > 0.40,
                f"mean_illum={mean_illum:.4f}",
                "> 0.40 (solar atmos: lit ridges for persistent power)",
            ))

    return results


# ---------------------------------------------------------------------------
# Main test function
# ---------------------------------------------------------------------------

def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    """
    Test 15: Input Combination Coverage (Fast/Synthetic).

    Ignores the passed terrain; generates its own synthetic 400×400 terrain
    so this test is always self-contained and fast.
    """
    _ensure_utf8_stdout()
    print("\n[Test 15] Input Combination Coverage (Fast / Synthetic Terrain)")
    result: dict = {"test_name": "Input Combination Coverage (Fast)"}

    sub_results: dict[str, dict] = {}
    failures: list[str] = []
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # 1. Generate synthetic terrain (400×400, ~0.5 s)
    # ------------------------------------------------------------------
    print("  Generating synthetic terrain (400×400) …")
    t0 = time.perf_counter()
    elev, sl, rough, prof = _synthetic_terrain(shape=(400, 400))
    H, W = elev.shape
    res_m = float(prof.get("resolution_m", 60.0))
    print(f"  Terrain ready: {H}×{W} px, res={res_m:.0f} m/px  ({time.perf_counter()-t0:.2f}s)")

    dem_finite = elev[np.isfinite(elev)]
    dem_median_elev = float(np.nanmedian(dem_finite))
    print(f"  DEM stats: median_elev={dem_median_elev:.0f} m")

    # ------------------------------------------------------------------
    # 2. Run all 8 valid combinations
    # ------------------------------------------------------------------
    all_combo_pass = True

    for combo in COMBINATIONS:
        label = combo["label"]
        cid   = combo["id"]
        print(f"\n  [{label}] {combo['mission_type']} / {combo['power_source']} "
              f"/ {combo['psr_intent']}  ({combo['rover_name']})")

        # Build rover profile
        rover = dict(_PRESETS[combo["preset"]])
        rover["mission_type"] = combo["mission_type"]
        rover["power_source"] = combo["power_source"]
        rover["psr_intent"]   = combo["psr_intent"]
        rover["priority"]     = combo["priority"]
        if combo["power_source"] == "solar":
            rover.update(_SOLAR_EXTRA)

        combo_checks: list[dict] = []
        combo_ok = True

        # ---- 2a. score_terrain --------------------------------------------
        try:
            t_s = time.perf_counter()
            safety, mission, final, top_sites = score_terrain(
                elev, sl, rough, prof, rover
            )
            elapsed = time.perf_counter() - t_s
            n_sites = len(top_sites)
            top_score = top_sites[0]["final_score"] if top_sites else 0.0
            print(f"    score_terrain  OK  ({elapsed:.2f}s) "
                  f"→ {n_sites} sites, top={top_score:.4f}")
        except Exception as exc:
            msg = f"score_terrain raised: {exc}"
            combo_checks.append({
                "check": "score_terrain_no_exception",
                "result": "FAIL", "value": str(exc), "expected": "no exception",
            })
            failures.append(f"{label} score_terrain: {exc}")
            all_combo_pass = False
            sub_results[cid] = {
                "label": label, "result": "FAIL",
                "checks": combo_checks, "error": str(exc),
            }
            print(f"    FAIL: {msg}")
            continue

        # ---- 2b. Universal array checks -----------------------------------
        try:
            # shape
            assert safety.shape == (H, W), f"safety shape {safety.shape} != ({H},{W})"
            assert mission.shape == (H, W), f"mission shape {mission.shape} != ({H},{W})"
            assert final.shape   == (H, W), f"final shape {final.shape} != ({H},{W})"
            combo_checks.append({
                "check": "array_shapes_correct",
                "result": "PASS",
                "value": f"all ({H},{W})",
                "expected": f"({H},{W})",
            })

            # dtype
            assert safety.dtype == np.float32, f"safety dtype {safety.dtype}"
            assert mission.dtype == np.float32, f"mission dtype {mission.dtype}"
            assert final.dtype   == np.float32, f"final dtype {final.dtype}"
            combo_checks.append({
                "check": "array_dtype_float32",
                "result": "PASS",
                "value": "float32 ✓",
                "expected": "float32",
            })

            # range [0, 1]
            range_ok = True
            range_detail = []
            for arr_name, arr in [("safety", safety), ("mission", mission), ("final", final)]:
                finite = arr[np.isfinite(arr)]
                lo, hi = float(finite.min()), float(finite.max())
                range_detail.append(f"{arr_name}=[{lo:.4f},{hi:.4f}]")
                if lo < -1e-4 or hi > 1.0 + 1e-4:
                    range_ok = False
            combo_checks.append({
                "check": "array_range_0_1",
                "result": "PASS" if range_ok else "FAIL",
                "value": "  ".join(range_detail),
                "expected": "all in [0, 1]",
            })
            if not range_ok:
                failures.append(f"{label} array out-of-range: {range_detail}")
                combo_ok = False

            # top_sites non-empty with positive score
            has_sites = len(top_sites) >= 1 and top_sites[0]["final_score"] > 0
            combo_checks.append({
                "check": "top_sites_exist_positive",
                "result": "PASS" if has_sites else "FAIL",
                "value": (f"{len(top_sites)} sites, top={top_sites[0]['final_score']:.4f}"
                          if top_sites else "0 sites"),
                "expected": ">= 1 site with final_score > 0",
            })
            if not has_sites:
                failures.append(f"{label}: no top sites with positive score")
                combo_ok = False

            # required keys in top-site dicts
            key_ok = True
            for s in top_sites:
                missing = _TOP_SITE_KEYS - set(s.keys())
                if missing:
                    key_ok = False
                    failures.append(f"{label} top-site missing keys: {missing}")
            combo_checks.append({
                "check": "top_site_keys_complete",
                "result": "PASS" if key_ok else "FAIL",
                "value": "all keys present" if key_ok else "missing keys",
                "expected": str(_TOP_SITE_KEYS),
            })
            if not key_ok:
                combo_ok = False

            # impassable pixels have safety == 0
            impassable = sl > float(rover["max_slope_deg"])
            n_wrong = int((safety[impassable] > 1e-6).sum()) if impassable.any() else 0
            combo_checks.append({
                "check": "impassable_safety_zero",
                "result": "PASS" if n_wrong == 0 else "FAIL",
                "value": f"{n_wrong} impassable px with non-zero safety",
                "expected": "0",
            })
            if n_wrong > 0:
                failures.append(f"{label}: {n_wrong} impassable pixels have non-zero safety")
                combo_ok = False

            # final_score == 0 wherever safety == 0 (hard safety gate)
            safety_zero = safety == 0.0
            n_gate_broken = int((final[safety_zero] > 1e-6).sum()) if safety_zero.any() else 0
            combo_checks.append({
                "check": "safety_gate_enforced",
                "result": "PASS" if n_gate_broken == 0 else "FAIL",
                "value": f"{n_gate_broken} pixels: final>0 but safety==0",
                "expected": "0 (final must be 0 wherever safety is 0)",
            })
            if n_gate_broken > 0:
                failures.append(f"{label}: safety gate broken at {n_gate_broken} pixels")
                combo_ok = False

        except AssertionError as ae:
            combo_checks.append({
                "check": "universal_array_checks",
                "result": "FAIL", "value": str(ae), "expected": "all pass",
            })
            failures.append(f"{label} universal check: {ae}")
            combo_ok = False

        # ---- 2c. Per-combo physics checks ---------------------------------
        phys = _physics_checks(combo, top_sites, elev, prof, dem_median_elev)
        combo_checks.extend(phys)
        for p in phys:
            if p["result"] == "FAIL":
                combo_ok = False
                failures.append(f"{label} physics check '{p['check']}' FAIL: {p['value']}")
            elif p["result"] == "WARN":
                warnings.append(f"{label} physics check '{p['check']}' WARN: {p['value']}")

        n_pass_c = sum(1 for c in combo_checks if c["result"] == "PASS")
        n_total_c = len(combo_checks)
        verdict_c = "PASS" if combo_ok else "FAIL"
        if combo_ok and any(c["result"] == "WARN" for c in combo_checks):
            verdict_c = "WARN"

        print(f"    checks: {n_pass_c}/{n_total_c} PASS  → {verdict_c}")

        if not combo_ok:
            all_combo_pass = False

        sub_results[cid] = {
            "label": label,
            "rover_name": combo["rover_name"],
            "mission_type": combo["mission_type"],
            "power_source": combo["power_source"],
            "psr_intent": combo["psr_intent"],
            "preset": combo["preset"],
            "analogue": combo["analogue"],
            "result": verdict_c,
            "n_checks_pass": n_pass_c,
            "n_checks_total": n_total_c,
            "checks": combo_checks,
            "top_site_final": round(top_sites[0]["final_score"], 4) if top_sites else None,
            "top_site_mission": round(top_sites[0]["mission_score"], 4) if top_sites else None,
            "top_site_lat": round(top_sites[0]["lat"], 3) if top_sites else None,
        }

        # free score arrays between combos (may not exist if scorer raised)
        for _arr in ("safety", "mission", "final"):
            try:
                del locals()[_arr]
            except KeyError:
                pass

    # ------------------------------------------------------------------
    # 3. Invalid combination: water_ice + solar + enter
    # ------------------------------------------------------------------
    print(f"\n  [X] INVALID: water_ice / solar / enter  (solar cannot enter PSR)")
    inv_rover = dict(_PRESETS[_INVALID_COMBO["preset"]])
    inv_rover["mission_type"] = _INVALID_COMBO["mission_type"]
    inv_rover["power_source"] = _INVALID_COMBO["power_source"]
    inv_rover["psr_intent"]   = _INVALID_COMBO["psr_intent"]
    inv_rover["priority"]     = _INVALID_COMBO["priority"]
    inv_rover.update(_SOLAR_EXTRA)

    inv_checks: list[dict] = []
    invalid_verdict = "PASS"

    try:
        t_inv = time.perf_counter()
        _, _, inv_final, inv_sites = score_terrain(elev, sl, rough, prof, inv_rover)
        elapsed_inv = time.perf_counter() - t_inv

        # Scorer did not raise — this is acceptable (enforcement is at app layer).
        # On synthetic terrain with no PSR map, there is no hard zero.
        # WARN: combination is scientifically invalid even though scorer handles it.
        inv_checks.append({
            "check": "invalid_combo_no_crash",
            "result": "PASS",
            "value": f"no exception raised ({elapsed_inv:.2f}s)",
            "expected": "scorer must not crash on any input",
        })
        inv_checks.append({
            "check": "solar_enter_psr_enforcement_note",
            "result": "WARN",
            "value": "Scorer ran without error on synthetic terrain (no PSR map loaded)",
            "expected": (
                "On real DEM with PSR map: final[psr_mask>=0.5]=0 enforces the constraint. "
                "Application layer (main.py) rejects this combo before calling scorer."
            ),
        })
        invalid_verdict = "WARN"
        warnings.append("Invalid combo (solar+enter) ran without error on synthetic terrain — "
                        "expected, PSR enforcement requires real PSR map.")
        print(f"    scorer ran (WARN: solar+enter is invalid — enforcement needs PSR map)")

    except (ValueError, RuntimeError) as exc:
        # Ideal: scorer itself detected the invalid combination
        inv_checks.append({
            "check": "invalid_combo_rejected",
            "result": "PASS",
            "value": f"Exception raised: {type(exc).__name__}: {exc}",
            "expected": "ValueError or RuntimeError indicating invalid combination",
        })
        invalid_verdict = "PASS"
        print(f"    PASS: scorer rejected invalid combo → {type(exc).__name__}: {exc}")

    except Exception as exc:
        inv_checks.append({
            "check": "invalid_combo_no_unexpected_crash",
            "result": "FAIL",
            "value": f"Unexpected exception: {type(exc).__name__}: {exc}",
            "expected": "no unexpected crash (only ValueError/RuntimeError acceptable)",
        })
        invalid_verdict = "FAIL"
        failures.append(f"Invalid combo crashed unexpectedly: {exc}")
        print(f"    FAIL: unexpected exception → {exc}")

    sub_results["x_invalid"] = {
        "label": "X",
        "description": "INVALID: water_ice + solar + enter",
        "result": invalid_verdict,
        "checks": inv_checks,
    }

    # ------------------------------------------------------------------
    # 4. Pathfinding smoke test on C1 (water_ice / rtg / enter)
    # ------------------------------------------------------------------
    print(f"\n  [PATH] Pathfinding smoke test on C1 (water_ice/rtg/enter) …")
    path_checks: list[dict] = []
    path_verdict = "SKIP"

    try:
        # Re-run C1 to get top_sites (arrays were freed above)
        c1_rover = dict(_PRESETS["viper"])
        c1_rover.update({"mission_type": "water_ice", "power_source": "rtg",
                         "psr_intent": "enter", "priority": 0.5})
        _, _, _, c1_sites = score_terrain(elev, sl, rough, prof, c1_rover)

        if len(c1_sites) >= 2:
            start_px = (c1_sites[0]["pixel_row"], c1_sites[0]["pixel_col"])
            goal_px  = (c1_sites[1]["pixel_row"], c1_sites[1]["pixel_col"])
            t_path = time.perf_counter()
            path, stats = find_path(sl, start_px, goal_px, c1_rover, res_m, elev)
            elapsed_path = time.perf_counter() - t_path

            if path is not None:
                dist_km = stats.get("total_distance_km", 0.0)
                battery = stats.get("battery_pct_used", 0.0)
                path_checks.append({
                    "check": "path_found",
                    "result": "PASS",
                    "value": f"{len(path)} waypoints, {dist_km:.2f} km, battery={battery:.1f}%",
                    "expected": "path returned",
                })
                path_verdict = "PASS"
                print(f"    path found: {len(path)} pts, {dist_km:.2f} km, "
                      f"battery={battery:.1f}%, time={elapsed_path:.2f}s")
            else:
                path_checks.append({
                    "check": "path_found",
                    "result": "WARN",
                    "value": "None (terrain separation or all routes blocked)",
                    "expected": "path returned",
                })
                path_verdict = "WARN"
                warnings.append("Pathfinder returned None on C1 (terrain separation on synthetic terrain)")
                print(f"    WARN: no path found ({elapsed_path:.2f}s) — may be terrain separation")
        else:
            path_checks.append({
                "check": "path_found",
                "result": "WARN",
                "value": f"only {len(c1_sites)} top sites returned (need >= 2)",
                "expected": ">= 2 top sites to plan path",
            })
            path_verdict = "WARN"
            warnings.append("C1 returned fewer than 2 top sites — path test skipped")
            print(f"    WARN: only {len(c1_sites)} top sites")

    except Exception as exc:
        path_checks.append({
            "check": "pathfinding_no_exception",
            "result": "FAIL",
            "value": str(exc),
            "expected": "no exception",
        })
        path_verdict = "FAIL"
        failures.append(f"Pathfinding smoke test exception: {exc}")
        print(f"    FAIL: {exc}")

    sub_results["pathfinding_smoke"] = {
        "description": "A* smoke test on C1 (water_ice/rtg/enter)",
        "result": path_verdict,
        "checks": path_checks,
    }

    # ------------------------------------------------------------------
    # 5. Aggregate verdict
    # ------------------------------------------------------------------
    if failures:
        verdict = "FAIL"
    elif warnings:
        verdict = "WARN"
    else:
        verdict = "PASS"

    # Count passes across all 8 combos
    n_combos_pass = sum(
        1 for cid in [c["id"] for c in COMBINATIONS]
        if sub_results.get(cid, {}).get("result") == "PASS"
    )
    n_combos_warn = sum(
        1 for cid in [c["id"] for c in COMBINATIONS]
        if sub_results.get(cid, {}).get("result") == "WARN"
    )

    print(f"\n  Combination results: {n_combos_pass}/8 PASS, {n_combos_warn}/8 WARN")
    print(f"  Invalid combo check: {sub_results['x_invalid']['result']}")
    print(f"  Pathfinding smoke:   {path_verdict}")
    print(f"  Overall result:      {verdict}")

    notes_parts = [f"{n_combos_pass}/8 combos PASS"]
    if n_combos_warn:
        notes_parts.append(f"{n_combos_warn} WARN")
    notes_parts.append(f"invalid={sub_results['x_invalid']['result']}")
    notes_parts.append(f"path={path_verdict}")
    if warnings:
        notes_parts.append(f"[warnings: {'; '.join(warnings[:2])}]")
    if failures:
        notes_parts.append(f"[FAIL: {'; '.join(failures[:2])}]")

    result.update({
        "result": verdict,
        "n_combos_pass": n_combos_pass,
        "n_combos_warn": n_combos_warn,
        "invalid_combo_result": sub_results["x_invalid"]["result"],
        "pathfinding_result": path_verdict,
        "sub_results": sub_results,
        "failures": failures,
        "warnings": warnings,
        "notes": "  |  ".join(notes_parts),
    })

    # ------------------------------------------------------------------
    # 6. Write JSON output
    # ------------------------------------------------------------------
    out_path = Path(results_dir) / "combinations_fast.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")

    return result


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    _results_dir = Path(__file__).parent / "results"
    _plots_dir   = _results_dir / "plots"
    _results_dir.mkdir(exist_ok=True)
    _plots_dir.mkdir(exist_ok=True)

    _r = run(None, None, None, None, str(_results_dir), str(_plots_dir))
    print(f"\nFinal verdict: {_r['result']}")
    if _r.get("failures"):
        print("Failures:")
        for f in _r["failures"]:
            print(f"  - {f}")
    if _r.get("warnings"):
        print("Warnings:")
        for w in _r["warnings"]:
            print(f"  - {w}")
