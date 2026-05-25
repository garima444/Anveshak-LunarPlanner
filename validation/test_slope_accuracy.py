"""
validation/test_slope_accuracy.py — Test 8: Slope Computation Accuracy (5 sub-tests).
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

from core.terrain import _compute_slope

# Pixel resolution in metres — matches the processed_dem.tif mosaic downsampled
# from LDEM_80S_20M.JP2 (native 20m, resampled to ~60m for memory efficiency).
# If this changes, all expected slope values in the sub-tests below must be re-derived.
PIXEL_RESOLUTION_M = 60.0
_RES = PIXEL_RESOLUTION_M


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 8] Slope Computation Accuracy")
    result = {"test_name": "Slope Computation Accuracy"}

    sub_results = {}

    # ---- 8a: Flat terrain → slope ≈ 0.0° --------------------------------
    print("  [8a] Flat terrain (100x100, elev=1000.0) -- expected slope ~ 0deg ...")
    try:
        elev = np.full((100, 100), 1000.0, dtype=np.float32)
        sl = _compute_slope(elev, _RES)
        interior = sl[1:-1, 1:-1]
        max_slope = float(np.nanmax(np.abs(interior)))
        passed = max_slope <= 0.001
        sub_results["8a"] = {
            "max_interior_slope_deg": round(max_slope, 6),
            "tolerance_deg": 0.001,
            "result": "PASS" if passed else "FAIL",
            "notes": f"max_slope={max_slope:.6f}°, tolerance=0.001°",
        }
        print(f"    {sub_results['8a']['result']}: max_slope={max_slope:.6f}°")
    except Exception as exc:
        sub_results["8a"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 8b: Row ramp elevation[r,c]=r*60 → slope ≈ 45° ----------------
    print("  [8b] Row ramp elev[r,c]=r*60m -- expected slope ~ 45deg ...")
    try:
        H, W = 100, 100
        elev = np.zeros((H, W), dtype=np.float32)
        for r in range(H):
            elev[r, :] = r * _RES  # elevation increases at exactly 1:1 with resolution
        sl = _compute_slope(elev, _RES)
        interior = sl[1:-1, 1:-1]
        mean_slope = float(np.nanmean(interior))
        pct_err = abs(mean_slope - 45.0) / 45.0 * 100.0
        passed = abs(mean_slope - 45.0) <= 1.0
        sub_results["8b"] = {
            "mean_interior_slope_deg": round(mean_slope, 4),
            "expected_deg": 45.0,
            "pct_error": round(pct_err, 4),
            "result": "PASS" if passed else "FAIL",
            "notes": f"mean_slope={mean_slope:.4f}°, expected=45.0°, err={pct_err:.4f}%",
        }
        print(f"    {sub_results['8b']['result']}: mean_slope={mean_slope:.4f}°")
    except Exception as exc:
        sub_results["8b"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 8c: 30° slope: elev[r,c] = r*60*tan(30°) ----------------------
    print("  [8c] Row ramp elev[r,c]=r*60*tan(30deg) -- expected slope ~ 30deg ...")
    try:
        H, W = 100, 100
        t30 = math.tan(math.radians(30.0))
        elev = np.zeros((H, W), dtype=np.float32)
        for r in range(H):
            elev[r, :] = r * _RES * t30
        sl = _compute_slope(elev, _RES)
        interior = sl[1:-1, 1:-1]
        mean_slope = float(np.nanmean(interior))
        passed = abs(mean_slope - 30.0) <= 1.0
        sub_results["8c"] = {
            "mean_interior_slope_deg": round(mean_slope, 4),
            "expected_deg": 30.0,
            "abs_error_deg": round(abs(mean_slope - 30.0), 4),
            "result": "PASS" if passed else "FAIL",
            "notes": f"mean_slope={mean_slope:.4f}°, expected=30.0°",
        }
        print(f"    {sub_results['8c']['result']}: mean_slope={mean_slope:.4f}°")
    except Exception as exc:
        sub_results["8c"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 8d: Diagonal 20°: elev[r,c]=(r+c)*60*tan(20°)/√2 -------------
    print("  [8d] Diagonal ramp -- expected slope ~ 20deg +/-2deg ...")
    try:
        H, W = 100, 100
        t20 = math.tan(math.radians(20.0))
        elev = np.zeros((H, W), dtype=np.float32)
        for r in range(H):
            for c in range(W):
                elev[r, c] = (r + c) * _RES * t20 / math.sqrt(2.0)
        elev = elev.astype(np.float32)
        sl = _compute_slope(elev, _RES)
        interior = sl[1:-1, 1:-1]
        mean_slope = float(np.nanmean(interior))
        passed = abs(mean_slope - 20.0) <= 2.0
        sub_results["8d"] = {
            "mean_interior_slope_deg": round(mean_slope, 4),
            "expected_deg": 20.0,
            "abs_error_deg": round(abs(mean_slope - 20.0), 4),
            "result": "PASS" if passed else "FAIL",
            "notes": f"mean_slope={mean_slope:.4f}°, expected=20.0°",
        }
        print(f"    {sub_results['8d']['result']}: mean_slope={mean_slope:.4f}°")
    except Exception as exc:
        sub_results["8d"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 8e: NaN propagation near (50,50) --------------------------------
    # Central differences at (50,50) use rows 49 and 51 (both finite), so
    # slope[50,50] is itself finite. NaN propagates to ADJACENT pixels:
    # slope[49,50] uses elevation[50,50]=NaN → NaN. This is correct behavior.
    print("  [8e] Flat + NaN at (50,50): adjacent slope is NaN, far pixel ~ 0deg ...")
    try:
        H, W = 100, 100
        elev = np.full((H, W), 500.0, dtype=np.float32)
        elev[50, 50] = np.nan
        sl = _compute_slope(elev, _RES)

        # Adjacent pixels that use elevation[50,50] in their central diff:
        slope_adj = sl[49, 50]  # dy[49,50] = (elev[50,50] - elev[48,50])/(2r) = NaN
        slope_far_pixel = sl[48, 48]

        adj_is_nan = not np.isfinite(slope_adj)
        far_is_ok = np.isfinite(slope_far_pixel) and abs(float(slope_far_pixel)) <= 0.1

        passed = adj_is_nan and far_is_ok
        sub_results["8e"] = {
            "slope_at_adjacent_49_50": None if not np.isfinite(slope_adj) else float(slope_adj),
            "adjacent_pixel_is_nan": adj_is_nan,
            "slope_at_far_pixel_48_48_deg": round(float(slope_far_pixel), 6) if np.isfinite(slope_far_pixel) else None,
            "far_pixel_near_zero": far_is_ok,
            "result": "PASS" if passed else "WARN",
            "notes": f"slope[49,50]={'NaN' if adj_is_nan else f'{float(slope_adj):.4f}'}deg (adj to NaN), slope[48,48]={slope_far_pixel:.4f}deg",
        }
        print(f"    {sub_results['8e']['result']}: adj_NaN={adj_is_nan}, far_slope={slope_far_pixel:.4f}deg")
    except Exception as exc:
        sub_results["8e"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 8f: Edge pixel with NaN corner neighbor ---------------------------
    # Real DEMs have NaN at data-void boundaries. Edge pixels with NaN neighbors
    # must propagate NaN correctly (not silently produce zero).
    print("  [8f] Edge + NaN at (0,0): adjacent slope is NaN, interior pixels ~0deg ...")
    try:
        H, W = 100, 100
        elev = np.full((H, W), 300.0, dtype=np.float32)
        elev[0, 0] = np.nan  # NaN at top-left corner
        sl = _compute_slope(elev, _RES)

        # Pixel (0,1) uses elev[0,0] in its central diff → should be NaN
        slope_adj = sl[0, 1]
        # Pixel (5, 5) is far from the NaN — should be ~0°
        slope_interior = sl[5, 5]

        adj_is_nan = not np.isfinite(slope_adj)
        interior_ok = np.isfinite(slope_interior) and abs(float(slope_interior)) <= 0.1

        passed = adj_is_nan and interior_ok
        sub_results["8f"] = {
            "slope_at_adjacent_0_1": None if not np.isfinite(slope_adj) else float(slope_adj),
            "adjacent_pixel_is_nan": adj_is_nan,
            "slope_at_interior_5_5_deg": round(float(slope_interior), 6) if np.isfinite(slope_interior) else None,
            "interior_near_zero": interior_ok,
            "result": "PASS" if passed else "WARN",
            "notes": f"slope[0,1]={'NaN' if adj_is_nan else f'{float(slope_adj):.4f}'}deg, interior[5,5]={slope_interior:.4f}deg",
        }
        print(f"    {sub_results['8f']['result']}: adj_NaN={adj_is_nan}, interior_slope={slope_interior:.4f}deg")
    except Exception as exc:
        sub_results["8f"] = {"result": "FAIL", "notes": str(exc)}
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
        "result": verdict,
        "notes": "Sub-tests: " + ", ".join(f"{k}={sub_results[k]['result']}" for k in sub_results),
    })

    out_path = Path(results_dir) / "slope_accuracy.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")

    return result


if __name__ == "__main__":
    Path("results").mkdir(exist_ok=True)
    Path("results/plots").mkdir(exist_ok=True)
    run(None, None, None, None, "results", "results/plots")
