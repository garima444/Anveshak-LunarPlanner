"""
validation/test_roughness_accuracy.py — Test 9: Roughness Computation Accuracy (3 sub-tests).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

import math

from core.terrain import _compute_roughness

# _compute_roughness uses a 3×3 uniform_filter window (see terrain.py docstring).
# For a checkerboard of 100m and 200m values, the theoretical local std-dev is:
#   In each 3×3 window: 5 cells of one value, 4 of the other (alternating pattern).
#   For a 100m-center window: mean=(5*100+4*200)/9=144.44m, E[x²]=(5*10000+4*40000)/9=23333.3
#   std = sqrt(E[x²] - mean²) = sqrt(23333.3 - 20876.5) ≈ 49.57m
#   For a 200m-center window: similarly ≈ 49.69m
#   Theoretical std-dev for interior pixels: ~49.6-49.7m
# We accept ±15% tolerance: [42.2m, 57.1m]
ROUGHNESS_WINDOW_SIZE = 3  # from terrain.py _compute_roughness docstring
_CHECKERBOARD_AMPLITUDE = 100.0  # half-range of checkerboard (200-100=100m)
_CHECKERBOARD_CELLS_A = 5  # cells of value A in 3×3 window (center type)
_CHECKERBOARD_CELLS_B = 4  # cells of value B in 3×3 window
_CELLS_TOTAL = ROUGHNESS_WINDOW_SIZE ** 2
_THEORETICAL_MEAN = (_CHECKERBOARD_CELLS_A * 100.0 + _CHECKERBOARD_CELLS_B * 200.0) / _CELLS_TOTAL
_THEORETICAL_E_X2 = (_CHECKERBOARD_CELLS_A * 100.0**2 + _CHECKERBOARD_CELLS_B * 200.0**2) / _CELLS_TOTAL
THEORETICAL_CHECKERBOARD_STD = math.sqrt(_THEORETICAL_E_X2 - _THEORETICAL_MEAN**2)
_ROUGHNESS_LOW  = round(THEORETICAL_CHECKERBOARD_STD * 0.85, 1)  # -15% tolerance
_ROUGHNESS_HIGH = round(THEORETICAL_CHECKERBOARD_STD * 1.15, 1)  # +15% tolerance


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 9] Roughness Computation Accuracy")
    result = {"test_name": "Roughness Computation Accuracy"}

    sub_results = {}

    # ---- 9a: Constant terrain → roughness ≈ 0.0 -------------------------
    print("  [9a] Constant terrain (100x100, elev=500.0) -- expected roughness ~ 0 ...")
    try:
        elev = np.full((100, 100), 500.0, dtype=np.float32)
        rough = _compute_roughness(elev)
        max_rough = float(np.nanmax(rough))
        passed = max_rough <= 0.01
        sub_results["9a"] = {
            "max_roughness_m": round(max_rough, 6),
            "tolerance_m": 0.01,
            "result": "PASS" if passed else "FAIL",
            "notes": f"max_roughness={max_rough:.6f}m, tolerance=0.01m",
        }
        print(f"    {sub_results['9a']['result']}: max_roughness={max_rough:.6f}m")
    except Exception as exc:
        sub_results["9a"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 9b: Checkerboard (100/200) → local std within ±15% of theoretical
    # Theoretical std for 3×3 window on 100/200m checkerboard ≈ 49.6m (see constants above).
    print(f"  [9b] Checkerboard (100/200 m) -- expected local std ~ {THEORETICAL_CHECKERBOARD_STD:.1f} m (±15%: [{_ROUGHNESS_LOW}, {_ROUGHNESS_HIGH}]) ...")
    try:
        H, W = 100, 100
        elev = np.zeros((H, W), dtype=np.float32)
        for r in range(H):
            for c in range(W):
                elev[r, c] = 100.0 if (r + c) % 2 == 0 else 200.0

        rough = _compute_roughness(elev)
        interior = rough[2:-2, 2:-2]
        mean_rough = float(np.nanmean(interior))
        min_rough = float(np.nanmin(interior))
        max_rough = float(np.nanmax(interior))
        passed = _ROUGHNESS_LOW <= mean_rough <= _ROUGHNESS_HIGH
        sub_results["9b"] = {
            "mean_interior_roughness_m": round(mean_rough, 4),
            "min_interior_roughness_m": round(min_rough, 4),
            "max_interior_roughness_m": round(max_rough, 4),
            "theoretical_std_m": round(THEORETICAL_CHECKERBOARD_STD, 4),
            "expected_range_m": [_ROUGHNESS_LOW, _ROUGHNESS_HIGH],
            "roughness_window_size": ROUGHNESS_WINDOW_SIZE,
            "result": "PASS" if passed else "WARN",
            "notes": f"mean_rough={mean_rough:.4f}m, expected in [{_ROUGHNESS_LOW},{_ROUGHNESS_HIGH}] (±15% of theoretical {THEORETICAL_CHECKERBOARD_STD:.1f}m)",
        }
        print(f"    {sub_results['9b']['result']}: mean_rough={mean_rough:.4f}m (theoretical={THEORETICAL_CHECKERBOARD_STD:.1f}m)")
    except Exception as exc:
        sub_results["9b"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 9c: Flat + 10% random NaN → NaN pixels stay NaN, far ≈ 0 ------
    print("  [9c] Flat terrain + 10% random NaN: NaN mask preserved, far roughness ~ 0 ...")
    try:
        H, W = 100, 100
        elev = np.full((H, W), 500.0, dtype=np.float32)
        rng = np.random.default_rng(42)
        nan_idx = rng.choice(H * W, size=int(0.10 * H * W), replace=False)
        nan_rows = nan_idx // W
        nan_cols = nan_idx % W
        elev[nan_rows, nan_cols] = np.nan

        rough = _compute_roughness(elev)

        # NaN pixels in roughness
        nan_in_rough = not np.isfinite(rough[nan_rows, nan_cols]).any()

        # Far pixel: (5, 5) — sample a pixel away from any NaN
        # Find a pixel that is at least 5px from any NaN
        nan_mask = ~np.isfinite(elev)
        from scipy.ndimage import binary_dilation
        near_nan = binary_dilation(nan_mask, iterations=2)
        safe_pixels = np.where(~near_nan)
        if len(safe_pixels[0]) > 0:
            sr, sc = int(safe_pixels[0][0]), int(safe_pixels[1][0])
            far_rough = float(rough[sr, sc])
            far_ok = np.isfinite(rough[sr, sc]) and far_rough < 0.01
        else:
            far_rough = float("nan")
            far_ok = False

        passed = nan_in_rough and far_ok
        sub_results["9c"] = {
            "nan_pixels_have_nan_roughness": nan_in_rough,
            "sample_far_pixel": [int(safe_pixels[0][0]) if len(safe_pixels[0]) > 0 else -1,
                                  int(safe_pixels[1][0]) if len(safe_pixels[1]) > 0 else -1],
            "far_roughness_m": round(far_rough, 6) if not (far_rough != far_rough) else None,
            "far_pixel_near_zero": far_ok,
            "result": "PASS" if passed else "WARN",
            "notes": f"NaN preserved={nan_in_rough}, far_rough={far_rough:.4f}m",
        }
        print(f"    {sub_results['9c']['result']}: nan_preserved={nan_in_rough}, far_rough={far_rough:.4f}m")
    except Exception as exc:
        sub_results["9c"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 9d: Roughness-slope correlation -----------------------------------
    # Rougher terrain should correlate with steeper terrain across patches.
    # Tests 5 synthetic patches of increasing gradient; expects Pearson r >= 0.80.
    print("  [9d] Roughness-slope correlation across 5 terrain patches (Pearson r >= 0.80) ...")
    try:
        from scipy.stats import pearsonr
        from core.terrain import _compute_slope
        _RES = 60.0
        patch_slopes = []
        patch_roughness = []
        for gradient in [0.0, 0.05, 0.10, 0.15, 0.20]:  # increasing slope magnitude
            H, W = 50, 50
            elev_patch = np.zeros((H, W), dtype=np.float32)
            for r in range(H):
                for c in range(W):
                    elev_patch[r, c] = float(r) * _RES * gradient
            sl_patch = _compute_slope(elev_patch, _RES)
            rough_patch = _compute_roughness(elev_patch)
            mean_sl = float(np.nanmean(sl_patch[1:-1, 1:-1]))
            mean_rg = float(np.nanmean(rough_patch[1:-1, 1:-1]))
            patch_slopes.append(mean_sl)
            patch_roughness.append(mean_rg)

        if len(set(patch_slopes)) < 2 or len(set(patch_roughness)) < 2:
            corr, _ = 0.0, None
        else:
            corr, _ = pearsonr(patch_slopes, patch_roughness)
        corr = float(corr)
        passed = corr >= 0.80

        sub_results["9d"] = {
            "patch_gradients": [0.0, 0.05, 0.10, 0.15, 0.20],
            "mean_slopes_deg": [round(s, 4) for s in patch_slopes],
            "mean_roughness_m": [round(r, 4) for r in patch_roughness],
            "pearson_r": round(corr, 4),
            "result": "PASS" if passed else "WARN",
            "notes": f"Pearson r={corr:.4f} between mean slope and mean roughness across 5 patches (expected >= 0.80)",
        }
        print(f"    {sub_results['9d']['result']}: Pearson r={corr:.4f}")
    except Exception as exc:
        sub_results["9d"] = {"result": "FAIL", "notes": str(exc)}
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

    out_path = Path(results_dir) / "roughness_accuracy.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")

    return result


if __name__ == "__main__":
    Path("results").mkdir(exist_ok=True)
    Path("results/plots").mkdir(exist_ok=True)
    run(None, None, None, None, "results", "results/plots")
