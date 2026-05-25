"""
validation/test_sensitivity.py — Test 3: Scoring Weight Sensitivity Analysis.

Tests how stable the top-10 landing sites are when the safety-score blend
weights (slope, roughness, quality, flatness) shift by ±0.10.
Real engineering uncertainty in weight tuning is ±0.10 or more; ±0.05 is too
conservative for a meaningful robustness check.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import maximum_filter, uniform_filter
from scipy.stats import spearmanr

from core.landing_scorer import _select_top_sites, _synthetic_terrain

# Weight configurations: (w_slope, w_rough, w_qual, w_flat, w_prom)
# BASELINE matches the actual scorer (landing_scorer.py _compute_safety_score).
# Variants perturb each weight by ±0.10 while keeping the sum = 1.0.
# Using ±0.10 instead of ±0.05 to represent realistic engineering uncertainty.
# NOTE: If avg_spearman is suspiciously close to 1.0 (e.g. 0.999), this may
# indicate the scoring is dominated by the slope term (w=0.35) and other weights
# are effectively irrelevant. This should be investigated — high stability is not
# always a sign of a well-calibrated model.
WEIGHT_CONFIGS = {
    "BASELINE":  (0.35, 0.25, 0.20, 0.05, 0.15),
    "VARIANT_1": (0.45, 0.25, 0.20, 0.05, 0.05),  # more slope (+0.10), less prom (-0.10)
    "VARIANT_2": (0.25, 0.35, 0.20, 0.05, 0.15),  # less slope (-0.10), more rough (+0.10)
    "VARIANT_3": (0.35, 0.25, 0.30, 0.05, 0.05),  # more qual (+0.10), less prom (-0.10)
    "VARIANT_4": (0.35, 0.15, 0.20, 0.15, 0.15),  # less rough (-0.10), more flat (+0.10)
    "VARIANT_5": (0.45, 0.25, 0.10, 0.05, 0.15),  # more slope (+0.10), less qual (-0.10)
    "VARIANT_6": (0.35, 0.35, 0.10, 0.05, 0.15),  # more rough (+0.10), less qual (-0.10)
    "VARIANT_7": (0.25, 0.25, 0.20, 0.05, 0.25),  # less slope (-0.10), more prom (+0.10)
}

_EXTREME_SLOPE_DEG = 35.0
_RIM_RADIUS_PX = 8


def _compute_sub_scores(elevation, slope, roughness, quality_mask, max_slope_deg, flat_radius_px):
    """Compute the five sub-scores used in the actual _compute_safety_score.

    Mirrors landing_scorer.py exactly so that sensitivity variants are tested
    against the real formula, not a stale reimplementation.
    """
    ms = np.float32(max_slope_deg)
    passable = (slope <= ms) & np.isfinite(elevation)

    # Slope sub-score — sigmoid (same as scorer, NOT old linear formula)
    slope_ratio = slope.astype(np.float32) / ms
    slope_sub = np.float32(1.0) / (
        np.float32(1.0) + np.exp(np.float32(8.0) * (slope_ratio - np.float32(0.6)))
    )
    slope_sub = np.clip(slope_sub, np.float32(0.0), np.float32(1.0))
    slope_sub = np.where(np.isfinite(slope_sub), slope_sub, np.float32(0.0))

    # Roughness sub-score
    r95 = float(np.nanpercentile(roughness, 95))
    r95 = r95 if r95 > 1e-6 else 1.0
    rough_sub = np.exp((-roughness.astype(np.float32)) / np.float32(r95))
    rough_sub = np.where(np.isfinite(rough_sub), rough_sub, np.float32(0.0))

    # Quality sub-score
    if quality_mask is not None:
        q_max = float(np.nanmax(quality_mask))
        q_max = q_max if q_max > 1e-6 else 1.0
        qual_sub = np.clip(
            quality_mask.astype(np.float32) / np.float32(q_max),
            np.float32(0.0), np.float32(1.0),
        )
        qual_sub = np.where(np.isfinite(qual_sub), qual_sub, np.float32(0.0))
    else:
        qual_sub = np.ones(elevation.shape, dtype=np.float32)

    # Crater-rim proximity penalty
    extreme = (slope >= np.float32(_EXTREME_SLOPE_DEG)).astype(np.float32)
    rim_zone = maximum_filter(extreme, size=_RIM_RADIUS_PX * 2 + 1)
    elev_safe = np.where(np.isfinite(elevation), elevation.astype(np.float32), np.float32(-1e9))
    local_elev_max = maximum_filter(elev_safe, size=_RIM_RADIUS_PX * 2 + 1)
    is_rim_top = np.isfinite(elevation) & (
        elevation.astype(np.float32) >= local_elev_max - np.float32(50.0)
    )
    rim_penalty = np.where(
        rim_zone > 0,
        np.where(is_rim_top, np.float32(0.85), np.float32(0.40)),
        np.float32(1.0),
    )

    # Flat-area sub-score
    if flat_radius_px > 0:
        kernel = flat_radius_px * 2 + 1
        flat_frac = uniform_filter(passable.astype(np.float32), size=kernel)
        flat_sub = np.clip(
            flat_frac / np.float32(0.5), np.float32(0.0), np.float32(1.0)
        )
    else:
        flat_sub = np.ones(elevation.shape, dtype=np.float32)

    # Prominence sub-score — elevation above local neighbourhood
    kernel_p = max(flat_radius_px * 2 + 1, 3)
    elev_dev = np.where(np.isfinite(elevation), elevation.astype(np.float32), np.float32(0.0))
    local_mean_e = uniform_filter(elev_dev, size=kernel_p)
    np.subtract(elev_dev, local_mean_e, out=elev_dev)
    prom_sub = np.clip(elev_dev / np.float32(200.0), np.float32(0.0), np.float32(1.0))
    prom_sub = np.where(np.isfinite(elevation), prom_sub, np.float32(0.0))

    return slope_sub, rough_sub, qual_sub, flat_sub, prom_sub, rim_penalty, passable


def _blend_safety(slope_sub, rough_sub, qual_sub, flat_sub, prom_sub, rim_penalty, passable, weights):
    w_s, w_r, w_q, w_f, w_p = [np.float32(w) for w in weights]
    score = w_s * slope_sub + w_r * rough_sub + w_q * qual_sub + w_f * flat_sub + w_p * prom_sub
    score = score * rim_penalty
    score[~passable] = np.float32(0.0)
    return score.astype(np.float32)


def _get_top10_pixels(safety_score, mission_score, elevation, slope, roughness, profile, rover_profile):
    """Get top-10 sites as list of (row,col) tuples."""
    from core.landing_scorer import _blend_scores
    final = _blend_scores(safety_score, mission_score, float(rover_profile["priority"]))
    sites = _select_top_sites(
        final, elevation, slope, roughness, safety_score, mission_score, profile, rover_profile, n=10
    )
    return [(s["pixel_row"], s["pixel_col"]) for s in sites], final


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 3] Scoring Weight Sensitivity Analysis")
    result = {"test_name": "Scoring Weight Sensitivity Analysis"}

    try:
        # Crop to 3000×3000 centred on south pole if DEM is larger than 4M pixels.
        # The sensitivity test measures RELATIVE rank stability across weight variants —
        # this is invariant to DEM extent. A 3000×3000 crop at 60 m/px = 180 km radius
        # captures the full inner south-polar region (craters, PSRs, rims, plains).
        _SENS_CROP = 3000
        H0, W0 = elevation.shape
        if H0 * W0 > _SENS_CROP * _SENS_CROP:
            r0s = max(0, H0 // 2 - _SENS_CROP // 2)
            c0s = max(0, W0 // 2 - _SENS_CROP // 2)
            r1s, c1s = r0s + _SENS_CROP, c0s + _SENS_CROP
            elevation = elevation[r0s:r1s, c0s:c1s]
            slope     = slope    [r0s:r1s, c0s:c1s]
            roughness = roughness[r0s:r1s, c0s:c1s]
            import copy as _copy
            from affine import Affine as _Aff
            orig_t = profile["transform"]
            profile = _copy.copy(profile)
            profile["height"] = _SENS_CROP
            profile["width"]  = _SENS_CROP
            profile["transform"] = _Aff(
                orig_t.a, orig_t.b, orig_t.c + c0s * orig_t.a,
                orig_t.d, orig_t.e, orig_t.f + r0s * orig_t.e,
            )
            for _ak in ("psr_mask", "illumination_map", "earth_visibility",
                        "sky_visibility", "diviner_coltemp", "quality_mask", "sunlight_map"):
                if profile.get(_ak) is not None:
                    profile[_ak] = profile[_ak][r0s:r1s, c0s:c1s]
            import gc as _gc; _gc.collect()
            print(f"  [sensitivity] Cropped to {_SENS_CROP}x{_SENS_CROP} centre (south pole) to avoid OOM.")
        result["crop_size"] = list(elevation.shape)

        max_slope_deg = 15.0
        min_flat_r_m = 300.0
        res_m = float(profile.get("resolution_m", 60.0))
        flat_radius_px = max(1, round(min_flat_r_m / res_m))
        quality_mask = profile.get("quality_mask")

        rover_profile = {
            "mission_type": "geological",
            "power_source": "rtg",
            "max_slope_deg": max_slope_deg,
            "min_flat_radius_m": min_flat_r_m,
            "priority": 0.3,
        }

        print("  Computing sub-scores ...")
        slope_sub, rough_sub, qual_sub, flat_sub, prom_sub, rim_penalty, passable = _compute_sub_scores(
            elevation, slope, roughness, quality_mask, max_slope_deg, flat_radius_px
        )

        # Passable pixel mask for Spearman correlation
        passable_flat = passable.ravel()

        # Compute mission score (needed for top-site selection)
        from core.landing_scorer import _build_lat_grid, _compute_mission_score
        print("  Building latitude grid and mission score ...")
        lat_grid = _build_lat_grid(profile)
        sunlight_map = profile.get("sunlight_map")
        mission_score = _compute_mission_score(
            elevation, slope, roughness, lat_grid,
            rover_profile["mission_type"], rover_profile["power_source"], res_m,
            sunlight_map=sunlight_map,
        )

        # Compute safety + top-10 for each weight configuration
        variant_results = {}
        config_scores = {}

        for name, weights in WEIGHT_CONFIGS.items():
            print(f"  Computing variant {name} {weights} ...")
            safety = _blend_safety(slope_sub, rough_sub, qual_sub, flat_sub, prom_sub, rim_penalty, passable, weights)
            top10_pixels, final_score = _get_top10_pixels(
                safety, mission_score, elevation, slope, roughness, profile, rover_profile
            )
            config_scores[name] = (safety.ravel()[passable_flat], final_score)
            variant_results[name] = {
                "weights":      list(weights),
                "top10_pixels": top10_pixels,
                # Do NOT store the full safety_array — 10133×10133 × 4 B = 392 MB per variant;
                # 8 variants × 392 MB = 3.1 GB would exhaust RAM. Pixel coords are sufficient.
            }
            del safety   # release immediately to prevent 3.1 GB accumulation
            import gc as _gc; _gc.collect()

        # Baseline
        baseline_top10 = variant_results["BASELINE"]["top10_pixels"]
        baseline_scores_flat = config_scores["BASELINE"][0]

        overlap_counts = []
        spearman_corrs = []
        per_variant = {}

        for name, weights in WEIGHT_CONFIGS.items():
            if name == "BASELINE":
                continue

            variant_top10 = variant_results[name]["top10_pixels"]
            variant_scores_flat = config_scores[name][0]

            # Overlap: how many baseline top-10 pixels appear (within 50px) in variant top-10
            overlap = 0
            for b_row, b_col in baseline_top10:
                for v_row, v_col in variant_top10:
                    if math.sqrt((b_row - v_row) ** 2 + (b_col - v_col) ** 2) < 50:
                        overlap += 1
                        break

            # Spearman correlation on passable pixels (subsample for speed if large)
            b_pass = config_scores["BASELINE"][0]  # safety scores, length = n_passable
            v_pass = variant_scores_flat            # same length
            n_passable = len(b_pass)
            if n_passable > 100_000:
                rng_spear = np.random.default_rng(42)
                idx_sub = rng_spear.choice(n_passable, size=100_000, replace=False)
                b_samp = b_pass[idx_sub]
                v_samp = v_pass[idx_sub]
            else:
                b_samp = b_pass
                v_samp = v_pass

            if len(b_samp) > 1:
                corr, _ = spearmanr(b_samp, v_samp)
                corr = float(corr) if np.isfinite(corr) else 0.0
            else:
                corr = 0.0

            overlap_counts.append(overlap)
            spearman_corrs.append(corr)
            per_variant[name] = {
                "weights": list(weights),
                "top10_overlap_with_baseline": overlap,
                "spearman_correlation": round(corr, 6),
                "top10_pixels": [(int(r), int(c)) for r, c in variant_top10],
            }
            print(f"    {name}: overlap={overlap}/10, spearman={corr:.4f}")

        avg_overlap = float(np.mean(overlap_counts)) if overlap_counts else 0.0
        avg_spearman = float(np.mean(spearman_corrs)) if spearman_corrs else 0.0

        # PASS/WARN/FAIL
        # Requires >=8/10 site overlap (80% stability) at ±0.10 weight perturbation —
        # appropriate for a safety-critical system.
        # Spearman >= 0.92 is required; values near 1.0 should be investigated for
        # slope-term dominance (log individual weight contributions for diagnosis).
        if avg_overlap >= 8.0 and avg_spearman >= 0.92:
            verdict = "PASS"
        elif avg_overlap >= 6.0 and avg_spearman >= 0.80:
            verdict = "WARN"
        else:
            verdict = "FAIL"

        print(f"  avg_overlap={avg_overlap:.2f}/10, avg_spearman={avg_spearman:.4f}")

        # Distinguish between terrain-driven stability (correct) and slope dominance (problem).
        spearman_diagnosis = ""
        if avg_spearman >= 0.999:
            top_slopes = [
                float(slope[r, c])
                for r, c in baseline_top10
                if 0 <= r < slope.shape[0] and 0 <= c < slope.shape[1]
                and np.isfinite(slope[r, c])
            ]
            top_slope_range = max(top_slopes) - min(top_slopes) if len(top_slopes) >= 2 else 0.0
            if top_slope_range < 3.0:
                spearman_diagnosis = (
                    f"Spearman={avg_spearman:.4f}: terrain-driven stability — "
                    f"top-10 sites span only {top_slope_range:.1f}° slope (all essentially flat); "
                    f"slope-weight saturation is expected correct behaviour near the south pole."
                )
                print(f"  NOTE: {spearman_diagnosis}")
                # verdict stays PASS — this is correct model behaviour
            else:
                spearman_diagnosis = (
                    f"WARN: Spearman={avg_spearman:.4f} despite top-10 slope range "
                    f"{top_slope_range:.1f}° — slope weight may dominate; "
                    f"roughness/PSR/flatness are effectively irrelevant. "
                    f"Consider normalising feature ranges or capping slope weight."
                )
                print(f"  {spearman_diagnosis}")
                if verdict == "PASS":
                    verdict = "WARN"

        print(f"  Result: {verdict}")

        # Heatmap: 7 variants × 10 baseline sites
        variant_names = list(per_variant.keys())
        overlap_matrix = np.zeros((len(variant_names), 10), dtype=np.float32)
        for i, vname in enumerate(variant_names):
            v_top10 = per_variant[vname]["top10_pixels"]
            for j, (b_row, b_col) in enumerate(baseline_top10):
                for v_row, v_col in v_top10:
                    if math.sqrt((b_row - v_row) ** 2 + (b_col - v_col) ** 2) < 50:
                        overlap_matrix[i, j] = 1.0
                        break

        fig, ax = plt.subplots(figsize=(12, 5))
        im = ax.imshow(overlap_matrix, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
        ax.set_yticks(range(len(variant_names)))
        ax.set_yticklabels(variant_names)
        ax.set_xticks(range(10))
        ax.set_xticklabels([f"Site {i+1}" for i in range(10)])
        ax.set_title("Top-10 Site Stability Across Weight Variants")
        plt.colorbar(im, ax=ax, label="Present (1) / Absent (0)")
        plt.tight_layout()
        plot_path = Path(plots_dir) / "sensitivity_heatmap.png"
        plt.savefig(plot_path, dpi=150)
        plt.close()
        print(f"  Plot saved: {plot_path}")

        result.update({
            "baseline_top10_pixels": [(int(r), int(c)) for r, c in baseline_top10],
            "per_variant": per_variant,
            "average_overlap": round(avg_overlap, 4),
            "average_spearman_correlation": round(avg_spearman, 6),
            "spearman_diagnosis": spearman_diagnosis,
            "result": verdict,
            "notes": (
                f"avg overlap={avg_overlap:.2f}/10, avg Spearman={avg_spearman:.4f}"
                + (f". {spearman_diagnosis}" if spearman_diagnosis else "")
            ),
        })

    except Exception as exc:
        import traceback
        result["result"] = "FAIL"
        result["notes"] = f"Exception: {exc}\n{traceback.format_exc()}"
        print(f"  FAIL: {exc}")

    out_path = Path(results_dir) / "sensitivity_analysis.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")

    return result


if __name__ == "__main__":
    try:
        from core.terrain import load_terrain
        elev, sl, rough, prof = load_terrain()
    except Exception:
        elev, sl, rough, prof = _synthetic_terrain()
    Path("results").mkdir(exist_ok=True)
    Path("results/plots").mkdir(exist_ok=True)
    run(elev, sl, rough, prof, "results", "results/plots")
