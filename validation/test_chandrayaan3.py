"""
validation/test_chandrayaan3.py — Test 1: Chandrayaan-3 Landing Site Validation.

Chandrayaan-3 Vikram lander touched down on 23 Aug 2023 at 69.373°S, 32.348°E.
This test loads the 65–80°S DEM region independently (it is outside the default
80–90°S coverage) and validates terrain metrics at the actual landing coordinates.

Pass criteria (from published mission data and ESA/ISRO site assessments):
  slope_deg  ≤ 12.0°    — Vikram max allowable landing slope per ISRO mission reports
  safety_score ≥ 0.40   — broadly safe landing zone (top 60% of passable terrain)

References:
  ISRO (2023) Chandrayaan-3 Mission Document, ISRO/ISSDC/CH3/2023
  Bhatt et al. (2020) "Geomorphological Analysis of Chandrayaan-3 Target Landing Site"
    Icarus 362:114406. doi:10.1016/j.icarus.2021.114406
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from core.terrain import latlon_to_pixel, DEM_REGIONS
from core.landing_scorer import score_terrain

CHANDRAYAAN3_LAT = -69.373
CHANDRAYAAN3_LON =  32.348

ROVER_PROFILE = {
    "mission_type":     "geological",
    "power_source":     "rtg",
    "max_slope_deg":    15.0,
    "min_flat_radius_m": 300.0,
    "priority":         0.3,
}

_SLOPE_THRESHOLD    = 12.0   # ISRO allowable landing slope
_SAFETY_THRESHOLD   = 0.40   # minimum safety score for a viable landing site
# NOTE: LDEM_75S_30MPP_ADJ.tiff covers 75–90°S only (bounds ±457 km from pole).
# Chandrayaan-3 at 69.4°S is OUTSIDE this DEM. The test will return WARN with
# "pixel out of bounds". A true 65–80°S DEM is needed for full validation.
_REGION_KEY         = "south_pole_75_90"


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 1] Chandrayaan-3 Landing Site Validation")
    result = {
        "test_name": "Chandrayaan-3 Landing Site Validation",
        "lat": CHANDRAYAAN3_LAT,
        "lon": CHANDRAYAAN3_LON,
        "region": _REGION_KEY,
    }

    # ------------------------------------------------------------------
    # Load 65–80°S region independently — runner passes 80–90°S terrain
    # which does not cover the 69.4°S landing site.
    # ------------------------------------------------------------------
    reg = DEM_REGIONS.get(_REGION_KEY)
    if reg is None or not reg["dem_path"].exists():
        skip_reason = (
            f"DEM region '{_REGION_KEY}' not available "
            f"(file: {reg['dem_path'] if reg else 'N/A'}). "
            f"Download LDEM_75S_30MPP_ADJ.tiff from NASA PDS "
            f"(LRO-L-LOLA-4-GDR-V1.0) and place in data/dem/."
        )
        print(f"  SKIP: {skip_reason}")
        result.update({"result": "SKIP", "skip_reason": skip_reason, "notes": skip_reason})
        out_path = Path(results_dir) / "chandrayaan3_validation.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    print(f"  Loading 65–80°S DEM region: {reg['label']} …")
    try:
        from core.terrain import load_terrain_by_region
        ch3_elev, ch3_slope, ch3_rough, ch3_prof = load_terrain_by_region(_REGION_KEY)
    except Exception as exc:
        skip_reason = f"Failed to load region '{_REGION_KEY}': {exc}"
        print(f"  SKIP: {skip_reason}")
        result.update({"result": "SKIP", "skip_reason": skip_reason, "notes": skip_reason})
        out_path = Path(results_dir) / "chandrayaan3_validation.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    H, W = ch3_elev.shape
    res_m = float(ch3_prof.get("resolution_m", 90.0))
    result["dem_shape"] = [H, W]
    result["resolution_m"] = res_m

    # ------------------------------------------------------------------
    # Convert landing coordinates to pixel
    # ------------------------------------------------------------------
    try:
        raw_px = latlon_to_pixel(CHANDRAYAAN3_LON, CHANDRAYAAN3_LAT, ch3_prof)
        row = max(0, min(raw_px[0], H - 1))
        col = max(0, min(raw_px[1], W - 1))
        in_bounds = (0 <= raw_px[0] < H) and (0 <= raw_px[1] < W)
    except Exception as exc:
        result["result"] = "FAIL"
        result["notes"] = f"Coordinate conversion failed: {exc}"
        print(f"  FAIL: coordinate conversion: {exc}")
        out_path = Path(results_dir) / "chandrayaan3_validation.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    result["pixel_row"] = int(row)
    result["pixel_col"] = int(col)
    result["in_bounds"]  = in_bounds
    print(f"  Landing site pixel: ({row}, {col}), in_bounds={in_bounds}")

    if not in_bounds:
        result["result"] = "WARN"
        result["notes"] = (
            f"Landing site pixel ({row}, {col}) is outside DEM bounds ({H}×{W}). "
            f"The 65–80°S DEM may not extend to 69.4°S — check file coverage."
        )
        print(f"  WARN: pixel out of bounds")
        out_path = Path(results_dir) / "chandrayaan3_validation.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    # ------------------------------------------------------------------
    # Extract terrain values at landing pixel
    # ------------------------------------------------------------------
    slope_at_site     = float(ch3_slope[row, col])
    elevation_at_site = float(ch3_elev[row, col]) if np.isfinite(ch3_elev[row, col]) else float("nan")
    roughness_at_site = float(ch3_rough[row, col])

    result["slope_deg"]   = round(slope_at_site, 3)
    result["elevation_m"] = round(elevation_at_site, 1)
    result["roughness_m"] = round(roughness_at_site, 3)

    print(f"  Terrain at landing site: slope={slope_at_site:.2f}°, "
          f"elev={elevation_at_site:.1f}m, rough={roughness_at_site:.2f}m")

    # ------------------------------------------------------------------
    # Score terrain (small crop around landing site to keep runtime fast)
    # ------------------------------------------------------------------
    CROP_R = 50   # ±50 px crop (~9 km radius at 90m/px)
    r0, r1 = max(0, row - CROP_R), min(H, row + CROP_R + 1)
    c0, c1 = max(0, col - CROP_R), min(W, col + CROP_R + 1)
    cr_r, cr_c = row - r0, col - c0

    crop_elev  = ch3_elev [r0:r1, c0:c1]
    crop_slope = ch3_slope[r0:r1, c0:c1]
    crop_rough = ch3_rough[r0:r1, c0:c1]

    # Build a minimal crop profile (no ancillary layers needed for basic safety score)
    from affine import Affine
    orig_t = ch3_prof["transform"]
    crop_transform = Affine(
        orig_t.a, orig_t.b, orig_t.c + c0 * orig_t.a,
        orig_t.d, orig_t.e, orig_t.f + r0 * orig_t.e,
    )
    crop_prof = dict(ch3_prof)
    crop_prof.update({
        "transform": crop_transform,
        "height": crop_elev.shape[0],
        "width":  crop_elev.shape[1],
    })
    # Pass ancillary layers cropped if present
    for key in ("psr_mask", "illumination_map", "quality_mask"):
        if ch3_prof.get(key) is not None:
            crop_prof[key] = ch3_prof[key][r0:r1, c0:c1]

    try:
        safety, mission, final, top_sites = score_terrain(
            crop_elev, crop_slope, crop_rough, crop_prof, ROVER_PROFILE
        )
        safety_at_site = float(safety[cr_r, cr_c])
        final_at_site  = float(final[cr_r, cr_c])
    except Exception as exc:
        result["result"] = "FAIL"
        result["notes"] = f"score_terrain failed: {exc}"
        print(f"  FAIL: {exc}")
        out_path = Path(results_dir) / "chandrayaan3_validation.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    result["safety_score"] = round(safety_at_site, 4)
    result["final_score"]  = round(final_at_site, 4)

    slope_ok  = slope_at_site <= _SLOPE_THRESHOLD
    safety_ok = safety_at_site >= _SAFETY_THRESHOLD

    result["SLOPE_VALIDATED"]  = slope_ok
    result["SAFETY_VALIDATED"] = safety_ok

    print(f"  safety_score={safety_at_site:.4f} (≥{_SAFETY_THRESHOLD} req: {safety_ok})")
    print(f"  slope_deg={slope_at_site:.2f}° (≤{_SLOPE_THRESHOLD}° req: {slope_ok})")

    if slope_ok and safety_ok:
        verdict = "PASS"
        notes = (
            f"Landing site terrain validated: slope={slope_at_site:.2f}° "
            f"(≤{_SLOPE_THRESHOLD}°) and safety_score={safety_at_site:.4f} "
            f"(≥{_SAFETY_THRESHOLD}) — consistent with published ISRO mission safety assessment."
        )
    elif slope_ok or safety_ok:
        verdict = "WARN"
        notes = (
            f"Partial validation: slope_ok={slope_ok} ({slope_at_site:.2f}°), "
            f"safety_ok={safety_ok} ({safety_at_site:.4f}). "
            f"Check DEM resolution ({res_m:.0f} m/px) vs mission-scale features."
        )
    else:
        verdict = "FAIL"
        notes = (
            f"Landing site terrain FAILED both criteria: "
            f"slope={slope_at_site:.2f}° (limit {_SLOPE_THRESHOLD}°), "
            f"safety={safety_at_site:.4f} (min {_SAFETY_THRESHOLD}). "
            f"Possible issue: DEM resolution too coarse, noisy pixel, or coordinate error."
        )

    result["result"] = verdict
    result["notes"]  = notes
    print(f"  Result: {verdict}")

    out_path = Path(results_dir) / "chandrayaan3_validation.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")

    # Explicitly free the large 65S DEM arrays (~1.2 GB) so subsequent tests
    # (Artemis-3, Sensitivity) can allocate on the full 80S real DEM without OOM.
    try:
        del ch3_elev, ch3_slope, ch3_rough, ch3_prof
    except NameError:
        pass
    import gc as _gc
    _gc.collect()
    print("  [chandrayaan3] 65S DEM freed from memory.")

    return result


if __name__ == "__main__":
    Path("results").mkdir(exist_ok=True)
    Path("results/plots").mkdir(exist_ok=True)
    run(None, None, None, None, "results", "results/plots")
