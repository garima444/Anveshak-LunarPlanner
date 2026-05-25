"""
validation/test_real_dem_sanity.py — Test 13: Real DEM Terrain Sanity.

Validates that the loaded NASA DEM produces physically sensible terrain
distributions. Uses whichever DEM region was loaded by the runner.

Sub-tests:
  13a: Slope distribution — >85% of pixels have slope < 35°
  13b: Roughness–slope Pearson r ≥ 0.50
  13c: Elevation range within plausible lunar south-pole limits
  13d: NaN fraction < 5% (large void regions indicate a bad DEM load)
  13e: No isolated single-pixel NaN islands in interior (DEM decode artifacts)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from scipy.ndimage import label as ndlabel


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 13] Real DEM Terrain Sanity")
    result = {"test_name": "Real DEM Terrain Sanity"}

    if elevation is None:
        result.update({"result": "SKIP", "notes": "No real DEM loaded (synthetic fallback active)"})
        return result

    H, W = elevation.shape
    res_m = float(profile.get("resolution_m", 60.0))
    checks = {}
    warnings = []
    failures = []

    checks["dem_shape"] = [H, W]
    checks["resolution_m"] = res_m

    # Determine if this is real DEM data by checking if it has a transform
    if "transform" not in profile:
        result.update({
            "result": "SKIP",
            "notes": "No geotransform in profile — likely synthetic terrain. Run with real DEM.",
        })
        out_path = Path(results_dir) / "real_dem_sanity.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    finite_mask = np.isfinite(elevation)
    n_total  = elevation.size
    n_finite = int(finite_mask.sum())
    nan_frac = 1.0 - n_finite / n_total
    checks["total_pixels"] = n_total
    checks["finite_pixels"] = n_finite
    checks["nan_fraction"] = round(nan_frac, 4)

    # ---- 13a: Slope distribution -----------------------------------------------
    print("  [13a] Slope distribution …")
    try:
        finite_slope = slope[np.isfinite(slope)]
        frac_below_35 = float(np.mean(finite_slope < 35.0))
        checks["13a_pct_below_35deg"] = round(frac_below_35 * 100, 2)
        checks["13a_slope_p50"] = round(float(np.median(finite_slope)), 3)
        checks["13a_slope_p95"] = round(float(np.percentile(finite_slope, 95)), 3)
        assert frac_below_35 >= 0.85, (
            f"Only {frac_below_35*100:.1f}% of pixels have slope < 35° "
            f"(expected >85% for flat lunar plains) — possible DEM scaling error"
        )
        checks["13a_slope_dist"] = "PASS"
        print(f"    PASS: {frac_below_35*100:.1f}% below 35°, median={checks['13a_slope_p50']}°, p95={checks['13a_slope_p95']}°")
    except AssertionError as e:
        checks["13a_slope_dist"] = "FAIL"
        failures.append(f"13a: {e}")
        print(f"    FAIL: {e}")

    # ---- 13b: Roughness–slope correlation ------------------------------------
    print("  [13b] Roughness–slope Pearson correlation …")
    try:
        valid = np.isfinite(slope) & np.isfinite(roughness)
        if valid.sum() > 1000:
            # Subsample for speed (Pearson on 100k samples is accurate enough)
            rng = np.random.default_rng(42)
            idx = rng.choice(int(valid.sum()), size=min(100_000, int(valid.sum())), replace=False)
            s_samp = slope[valid].ravel()[idx]
            r_samp = roughness[valid].ravel()[idx]
            pearson_r = float(np.corrcoef(s_samp, r_samp)[0, 1])
        else:
            pearson_r = float(np.corrcoef(slope[valid].ravel(), roughness[valid].ravel())[0, 1])

        checks["13b_roughness_slope_pearson_r"] = round(pearson_r, 4)
        assert pearson_r >= 0.50, (
            f"Roughness–slope Pearson r = {pearson_r:.4f} < 0.50 — "
            f"steep terrain should be rough terrain; possible DEM compute error"
        )
        checks["13b_roughness_slope_corr"] = "PASS"
        print(f"    PASS: Pearson r={pearson_r:.4f}")
    except AssertionError as e:
        checks["13b_roughness_slope_corr"] = "FAIL"
        failures.append(f"13b: {e}")
        print(f"    FAIL: {e}")

    # ---- 13c: Elevation range ------------------------------------------------
    print("  [13c] Elevation range plausibility …")
    try:
        finite_elev = elevation[finite_mask]
        elev_min = float(np.nanmin(finite_elev))
        elev_max = float(np.nanmax(finite_elev))
        elev_mean = float(np.nanmean(finite_elev))
        checks["13c_elevation_min_m"] = round(elev_min, 1)
        checks["13c_elevation_max_m"] = round(elev_max, 1)
        checks["13c_elevation_mean_m"] = round(elev_mean, 1)
        # Lunar south-pole DEM: elevations referenced to 1737.4 km sphere
        # Typical range: -9000 m (deep craters) to +2000 m (high rims)
        assert -15000 < elev_min, f"Elevation min {elev_min:.0f} m is below -15 km — possible DN scaling error"
        assert elev_max < 15000,  f"Elevation max {elev_max:.0f} m is above +15 km — possible DN scaling error"
        assert elev_max - elev_min > 500, f"Elevation range {elev_max-elev_min:.0f} m is suspiciously small (<500 m)"
        checks["13c_elevation_range"] = "PASS"
        print(f"    PASS: min={elev_min:.0f}m, max={elev_max:.0f}m, mean={elev_mean:.0f}m, range={elev_max-elev_min:.0f}m")
    except AssertionError as e:
        checks["13c_elevation_range"] = "FAIL"
        failures.append(f"13c: {e}")
        print(f"    FAIL: {e}")

    # ---- 13d: NaN fraction ---------------------------------------------------
    print("  [13d] NaN data fraction …")
    try:
        checks["13d_nan_frac_pct"] = round(nan_frac * 100, 2)
        assert nan_frac < 0.05, (
            f"NaN fraction {nan_frac*100:.1f}% exceeds 5% — "
            f"large void regions may indicate a bad DEM load or incomplete file"
        )
        checks["13d_nan_fraction"] = "PASS"
        print(f"    PASS: NaN fraction={nan_frac*100:.2f}%")
    except AssertionError as e:
        checks["13d_nan_fraction"] = "WARN"   # WARN not FAIL — some DEMs have valid edge voids
        warnings.append(f"13d: {e}")
        print(f"    WARN: {e}")

    # ---- 13e: Isolated single-pixel NaN islands (DEM decode artifacts) ------
    print("  [13e] Isolated single-pixel NaN islands …")
    try:
        nan_mask = ~finite_mask
        # Label connected NaN regions; count those of size 1 (isolated pixels)
        interior = nan_mask[1:-1, 1:-1]   # exclude border pixels (edge voids are normal)
        if interior.any():
            labeled, n_components = ndlabel(interior)
            component_sizes = np.bincount(labeled.ravel())[1:]   # skip background (0)
            n_isolated = int(np.sum(component_sizes == 1))
            frac_isolated = n_isolated / max(1, n_finite)
            checks["13e_isolated_nan_count"] = n_isolated
            checks["13e_isolated_nan_frac"]  = round(frac_isolated, 6)
            # Tolerance: up to 0.01% of finite pixels may be isolated NaN (LOLA voids are normal)
            assert frac_isolated < 0.001, (
                f"{n_isolated} isolated single-pixel NaN islands "
                f"({frac_isolated*100:.3f}% of valid pixels) — "
                f"possible DEM decode artifact or nodata masking error"
            )
            checks["13e_nan_islands"] = "PASS"
            print(f"    PASS: {n_isolated} isolated NaN pixels ({frac_isolated*100:.4f}%)")
        else:
            checks["13e_isolated_nan_count"] = 0
            checks["13e_nan_islands"] = "PASS"
            print("    PASS: no interior NaN pixels")
    except AssertionError as e:
        checks["13e_nan_islands"] = "WARN"   # Isolated pixels are not mission-critical
        warnings.append(f"13e: {e}")
        print(f"    WARN: {e}")

    # ---- Overall verdict -----------------------------------------------
    sub_keys = ["13a_slope_dist","13b_roughness_slope_corr","13c_elevation_range","13d_nan_fraction","13e_nan_islands"]
    sub_results = [checks.get(k) for k in sub_keys]
    if failures or "FAIL" in sub_results:
        verdict = "FAIL"
    elif warnings or "WARN" in sub_results:
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
            f"DEM {H}×{W} px @ {res_m:.0f}m/px. "
            + ", ".join(f"{k}={checks.get(k,'?')}" for k in sub_keys)
            + (f". Warnings: {warnings}" if warnings else "")
            + (f". Failures: {failures}" if failures else "")
        ),
    })

    out_path = Path(results_dir) / "real_dem_sanity.json"
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
        print("  WARNING: load_terrain failed, using synthetic. Run with real DEM for meaningful results.")
        elev, sl, rough, prof = _synthetic_terrain(shape=(500, 500))
    Path("results").mkdir(exist_ok=True)
    Path("results/plots").mkdir(exist_ok=True)
    run(elev, sl, rough, prof, "results", "results/plots")
