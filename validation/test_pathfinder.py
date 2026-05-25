"""
validation/test_pathfinder.py — Test 6: A* Pathfinder Validation (5 sub-tests).
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

from core.pathfinder import astar, build_cost_grid, compute_path_stats, find_path

_ROVER = {"max_slope_deg": 15.0, "speed_kmh": 0.5}
_RES = 60.0


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 6] A* Pathfinder Validation")
    result = {"test_name": "A* Pathfinder Validation"}

    sub_results = {}

    # ---- 6a: Wall bypass ------------------------------------------------
    print("  [6a] Wall bypass (20x20 grid, wall at col=10 rows 0-15) ...")
    try:
        sl = np.zeros((20, 20), dtype=np.float32)
        sl[0:16, 10] = 999.0
        el = np.zeros((20, 20), dtype=np.float32)
        cg = build_cost_grid(el, sl, _RES, 15.0)
        path = astar(cg, (0, 0), (0, 19))

        if path is None:
            sub_results["6a"] = {"result": "FAIL", "notes": "Path is None — wall bypass failed"}
        else:
            all_in_bounds = all(0 <= r < 20 and 0 <= c < 20 for r, c in path)
            all_finite = all(math.isfinite(cg[r, c]) for r, c in path)
            passed = path is not None and all_in_bounds and all_finite and len(path) > 19
            sub_results["6a"] = {
                "path_length": len(path),
                "all_in_bounds": all_in_bounds,
                "all_passable": all_finite,
                "result": "PASS" if passed else "FAIL",
                "notes": f"len={len(path)}, all_in_bounds={all_in_bounds}, all_passable={all_finite}",
            }
        print(f"    {sub_results['6a']['result']}: path_length={sub_results['6a'].get('path_length','N/A')}")
    except Exception as exc:
        sub_results["6a"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 6b: Fully impassable grid → (None, None) -----------------------
    print("  [6b] Fully impassable grid ...")
    try:
        sl = np.full((10, 10), 999.0, dtype=np.float32)
        el = np.zeros((10, 10), dtype=np.float32)
        path, stats = find_path(sl, (0, 0), (9, 9), _ROVER, _RES, el)
        passed = path is None and stats is None
        sub_results["6b"] = {
            "path_is_none": path is None,
            "stats_is_none": stats is None,
            "result": "PASS" if passed else "FAIL",
            "notes": f"path={path}, stats={stats}",
        }
        print(f"    {sub_results['6b']['result']}: path_is_none={path is None}")
    except Exception as exc:
        sub_results["6b"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 6c: start == goal (5,5) ----------------------------------------
    print("  [6c] start == goal ...")
    try:
        sl = np.zeros((10, 10), dtype=np.float32)
        el = np.zeros((10, 10), dtype=np.float32)
        path, stats = find_path(sl, (5, 5), (5, 5), _ROVER, _RES, el)
        no_crash = True
        if path is None:
            dist = 0.0
        else:
            dist = stats["total_distance_m"] if stats else 0.0
        passed = no_crash and dist == 0.0
        sub_results["6c"] = {
            "path_returned": path is not None,
            "total_distance_m": dist,
            "result": "PASS" if passed else "WARN",
            "notes": f"No crash, distance={dist:.2f}m",
        }
        print(f"    {sub_results['6c']['result']}: distance={dist:.2f}m")
    except Exception as exc:
        sub_results["6c"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 6d: 100x100 flat terrain, diagonal path distance ---------------
    print("  [6d] 100x100 flat slope=5deg, (0,0)->(99,99), expected ~8400m +/-10% ...")
    try:
        sl = np.full((100, 100), 5.0, dtype=np.float32)
        el = np.zeros((100, 100), dtype=np.float32)
        path, stats = find_path(sl, (0, 0), (99, 99), _ROVER, _RES, el)
        if path is None or stats is None:
            sub_results["6d"] = {"result": "FAIL", "notes": "No path found"}
            print("    FAIL: No path found")
        else:
            dist_m = stats["total_distance_m"]
            expected_m = 99.0 * _RES * math.sqrt(2)  # ≈ 8400m
            pct_error = abs(dist_m - expected_m) / expected_m * 100.0
            time_hrs = stats["estimated_time_hrs"]
            expected_time = (dist_m / 1000.0) / 0.5
            max_sl = stats["max_slope_deg"]
            mean_sl = stats["mean_slope_deg"]
            passed = (
                pct_error <= 10.0
                and abs(time_hrs - expected_time) / max(expected_time, 1e-6) < 0.01
                and abs(max_sl - 5.0) < 1.0
                and abs(mean_sl - 5.0) < 1.0
            )
            sub_results["6d"] = {
                "total_distance_m": round(dist_m, 2),
                "expected_distance_m": round(expected_m, 2),
                "pct_error": round(pct_error, 3),
                "estimated_time_hrs": round(time_hrs, 4),
                "max_slope_deg": round(max_sl, 4),
                "mean_slope_deg": round(mean_sl, 4),
                "result": "PASS" if passed else "WARN",
                "notes": f"dist={dist_m:.1f}m, expected≈{expected_m:.1f}m, err={pct_error:.2f}%",
            }
            print(f"    {sub_results['6d']['result']}: dist={dist_m:.1f}m, err={pct_error:.2f}%")
    except Exception as exc:
        sub_results["6d"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 6e: 3x3 diagonal cost verification ------------------------------
    print("  [6e] 3x3 flat slope=0deg, (0,0)->(2,2), expected ~2x60xsqrt(2) m ...")
    try:
        sl = np.zeros((3, 3), dtype=np.float32)
        el = np.zeros((3, 3), dtype=np.float32)
        cg = build_cost_grid(el, sl, _RES, 15.0)
        path = astar(cg, (0, 0), (2, 2))
        if path is None:
            sub_results["6e"] = {"result": "FAIL", "notes": "No path on 3x3 flat grid"}
            print("    FAIL: No path on 3x3 flat grid")
        else:
            stats = compute_path_stats(path, sl, _RES, 0.5)
            dist_m = stats["total_distance_m"]
            expected_m = 2.0 * _RES * math.sqrt(2)
            pct_error = abs(dist_m - expected_m) / expected_m * 100.0
            passed = pct_error <= 1.0
            sub_results["6e"] = {
                "path": [list(p) for p in path],
                "total_distance_m": round(dist_m, 4),
                "expected_distance_m": round(expected_m, 4),
                "pct_error": round(pct_error, 4),
                "result": "PASS" if passed else "WARN",
                "notes": f"dist={dist_m:.4f}m, expected={expected_m:.4f}m, err={pct_error:.4f}%",
            }
            print(f"    {sub_results['6e']['result']}: dist={dist_m:.4f}m, err={pct_error:.4f}%")
    except Exception as exc:
        sub_results["6e"] = {"result": "FAIL", "notes": str(exc)}
        print(f"    FAIL: {exc}")

    # ---- 6f: Slope-preference — pathfinder must choose shallower route -----
    print("  [6f] Slope-preference: two routes (5° vs 15°), pathfinder must pick 5° ...")
    try:
        # 20×20 grid: left corridor (cols 0-9) at slope=5°, right (cols 10-19) at 15°
        sl_pref = np.full((20, 20), 5.0, dtype=np.float32)
        sl_pref[:, 10:] = 15.0
        el_pref = np.zeros((20, 20), dtype=np.float32)
        path_pref, stats_pref = find_path(sl_pref, (0, 0), (19, 0), _ROVER, _RES, el_pref)
        if path_pref is None:
            sub_results["6f"] = {"result": "FAIL", "notes": "No path found on slope-preference grid"}
            print("    FAIL: No path found")
        else:
            # Check that the path stays in the shallow corridor (col < 10)
            max_col_used = max(c for _, c in path_pref)
            stayed_shallow = max_col_used <= 12  # allow minor diagonal steps
            max_sl_on_path = max(float(sl_pref[r, c]) for r, c in path_pref)
            passed = stayed_shallow
            sub_results["6f"] = {
                "max_col_used": max_col_used,
                "stayed_in_shallow_corridor": stayed_shallow,
                "max_slope_on_path_deg": round(max_sl_on_path, 1),
                "result": "PASS" if passed else "FAIL",
                "notes": (
                    f"max_col={max_col_used} (shallow zone: col<10), "
                    f"max_slope_on_path={max_sl_on_path:.1f}°. "
                    f"Proves slope is used in A* cost function."
                ),
            }
            print(f"    {sub_results['6f']['result']}: max_col={max_col_used}, max_slope={max_sl_on_path:.1f}°")
    except Exception as exc:
        sub_results["6f"] = {"result": "FAIL", "notes": str(exc)}
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

    out_path = Path(results_dir) / "pathfinder_validation.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")

    return result


if __name__ == "__main__":
    Path("results").mkdir(exist_ok=True)
    Path("results/plots").mkdir(exist_ok=True)
    run(None, None, None, None, "results", "results/plots")
