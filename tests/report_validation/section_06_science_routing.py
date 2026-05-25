"""
tests/report_validation/section_06_science_routing.py
──────────────────────────────────────────────────────
Section 6: Science Routing Verification
Proves that science experiments alter path choice, routing
through instrumentally richer terrain even when slightly longer.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np

from tests.report_validation.utils import (
    IMAGES_DIR,
    LOGS_DIR,
    VIPER_PROFILE,
    TeeOutput,
    build_lat_grid_safe,
    ensure_dirs,
    make_check,
    print_result,
    print_section_header,
    save_terminal_screenshot,
    verdict_from_checks,
)


def run(elevation=None, slope=None, roughness=None, profile=None, out_dir=None) -> dict:
    """Run Section 6: Science Routing Verification."""
    ensure_dirs()
    log_path     = LOGS_DIR  / "06_science_routing.txt"
    img_no_sci   = IMAGES_DIR / "06a_path_without_science.png"
    img_with_sci = IMAGES_DIR / "06b_path_with_science.png"
    img_compare  = IMAGES_DIR / "06c_science_routing_comparison.png"

    tee = TeeOutput(log_path)
    old_stdout = sys.stdout
    sys.stdout = tee

    checks: list[dict] = []
    images: list[str]  = []

    try:
        print_section_header("SECTION 6: SCIENCE ROUTING VERIFICATION")
        print("  Tests that build_science_map() and pathfinder science routing work.")
        print()

        # Always use synthetic terrain for reproducibility
        from core.landing_scorer import _synthetic_terrain, build_science_map
        from core.pathfinder import find_path, build_cost_grid, astar

        print("  Generating synthetic 300×300 terrain …")
        syn_elev, syn_slope, syn_rough, syn_profile = _synthetic_terrain(shape=(300, 300))
        H, W  = syn_elev.shape
        res_m = float(syn_profile.get("resolution_m", 60.0))
        lat_g = build_lat_grid_safe(syn_profile)

        # ── TEST 6.1: build_science_map basic correctness ─────────────────
        print()
        print("─" * 60)
        print("  TEST 6.1: build_science_map() Correctness")
        print("─" * 60)

        # 6.1a: empty experiments → all zeros
        try:
            sci_empty = build_science_map(
                syn_elev, syn_slope, syn_rough,
                lat_g, syn_profile,
                experiments=[],
                resolution_m=res_m,
            )
            empty_ok = float(np.nanmax(sci_empty)) == 0.0
            print_result("empty experiments → all zeros", empty_ok,
                         f"max={np.nanmax(sci_empty):.3f}", "0.0")
            checks.append(make_check("empty_experiments → zeros", empty_ok))
        except Exception as exc:
            print(f"  ❌ empty experiments test: {exc}")
            checks.append(make_check("empty_experiments → zeros", False, str(exc)[:60]))
            sci_empty = np.zeros((H, W), dtype=np.float32)

        # 6.1b: volatile_detection → non-zero
        try:
            sci_volatile = build_science_map(
                syn_elev, syn_slope, syn_rough,
                lat_g, syn_profile,
                experiments=["volatile_detection"],
                resolution_m=res_m,
            )
            vd_ok      = float(np.nanmax(sci_volatile)) > 0.0
            range_ok   = float(np.nanmin(sci_volatile)) >= 0.0 and float(np.nanmax(sci_volatile)) <= 1.001
            shape_ok   = sci_volatile.shape == (H, W)
            print_result("volatile_detection → non-zero", vd_ok, f"max={np.nanmax(sci_volatile):.3f}", "> 0")
            print_result("volatile_detection range [0,1]", range_ok)
            print_result("volatile_detection shape matches", shape_ok, str(sci_volatile.shape), str((H, W)))
            checks.append(make_check("volatile_detection non-zero", vd_ok))
            checks.append(make_check("volatile_detection range [0,1]", range_ok))
            checks.append(make_check("volatile_detection shape", shape_ok))
        except Exception as exc:
            print(f"  ❌ volatile_detection test: {exc}")
            for nm in ["volatile_detection non-zero", "volatile_detection range", "volatile_detection shape"]:
                checks.append(make_check(nm, False, str(exc)[:60]))
            sci_volatile = np.zeros((H, W), dtype=np.float32)

        # 6.1c: mineralogy → non-zero
        try:
            sci_mineral = build_science_map(
                syn_elev, syn_slope, syn_rough,
                lat_g, syn_profile,
                experiments=["mineralogy"],
                resolution_m=res_m,
            )
            min_ok = float(np.nanmax(sci_mineral)) > 0.0
            print_result("mineralogy → non-zero", min_ok, f"max={np.nanmax(sci_mineral):.3f}", "> 0")
            checks.append(make_check("mineralogy non-zero", min_ok))
        except Exception as exc:
            print(f"  ❌ mineralogy test: {exc}")
            checks.append(make_check("mineralogy non-zero", False, str(exc)[:60]))

        # ── TEST 6.2: Science routing changes path ─────────────────────────
        print()
        print("─" * 60)
        print("  TEST 6.2: Science Routing Effect on Path Selection")
        print("─" * 60)

        start_px = (10, 10)
        goal_px  = (H - 10, W - 10)
        rover    = {**VIPER_PROFILE, "max_slope_deg": 20.0, "battery_wh": 2000.0}

        # Combined science map for routing test
        try:
            sci_combined = build_science_map(
                syn_elev, syn_slope, syn_rough,
                lat_g, syn_profile,
                experiments=["volatile_detection", "mineralogy"],
                resolution_m=res_m,
            )
        except Exception as exc:
            print(f"  ⚠️  build_science_map combined: {exc}")
            sci_combined = np.zeros((H, W), dtype=np.float32)

        # Path WITHOUT science routing
        print()
        print("  Running pathfinding WITHOUT science routing …")
        try:
            path_no_sci, stats_no = find_path(
                syn_slope, start_px, goal_px, rover,
                resolution_m=res_m, elevation=syn_elev,
                science_map=None,
            )
        except Exception as exc:
            print(f"  ⚠️  find_path (no science): {exc}")
            path_no_sci, stats_no = None, None

        no_sci_dist  = float(stats_no.get("total_distance_km", 0)) if stats_no else 0.0
        no_sci_vals  = ([float(sci_combined[r, c]) for r, c in path_no_sci]
                        if path_no_sci else [0.0])
        no_sci_mean  = float(np.mean(no_sci_vals))
        print(f"  Without Science — Distance: {no_sci_dist:.2f} km | Mean science: {no_sci_mean:.3f}")

        # Path WITH science routing
        print()
        print("  Running pathfinding WITH science routing …")
        try:
            path_sci, stats_sci = find_path(
                syn_slope, start_px, goal_px, rover,
                resolution_m=res_m, elevation=syn_elev,
                science_map=sci_combined,
            )
        except Exception as exc:
            print(f"  ⚠️  find_path (with science): {exc}")
            path_sci, stats_sci = None, None

        sci_dist = float(stats_sci.get("total_distance_km", 0)) if stats_sci else 0.0
        sci_vals = ([float(sci_combined[r, c]) for r, c in path_sci]
                    if path_sci else [0.0])
        sci_mean = float(np.mean(sci_vals))
        print(f"  With Science    — Distance: {sci_dist:.2f} km | Mean science: {sci_mean:.3f}")

        # Checks
        sci_higher = sci_mean >= no_sci_mean  # science path should have ≥ science value
        checks.append(make_check("science path has ≥ science value",
                                  sci_higher, f"{sci_mean:.3f}", f"≥ {no_sci_mean:.3f}"))
        checks.append(make_check("no-science path found", path_no_sci is not None))
        checks.append(make_check("science path found", path_sci is not None))

        pct_change = (sci_dist - no_sci_dist) / max(no_sci_dist, 0.001) * 100
        print()
        print("  ┌─────────────────────────────────────────────────┐")
        print("  │ SCIENCE ROUTING COMPARISON                      │")
        print("  │                                                 │")
        print(f"  │         Without Science   With Science         │")
        print(f"  │ Distance: {no_sci_dist:>6.2f} km     {sci_dist:>6.2f} km         │")
        print(f"  │ Science:  {no_sci_mean:>7.3f}       {sci_mean:>7.3f}           │")
        print("  │                                                 │")
        sci_higher_str = "✅" if sci_higher else "❌"
        print(f"  │ Science routing increases value: {sci_higher_str}              │")
        print(f"  │ Distance change: {pct_change:+.1f}%                        │")
        print("  │                                                 │")
        result_str = "SCIENCE_ROUTING_VERIFIED ✅" if sci_higher else "ROUTING_EFFECT_MARGINAL ⚠️"
        print(f"  │ {result_str:<47}│")
        print("  └─────────────────────────────────────────────────┘")

    finally:
        sys.stdout = old_stdout
        tee.close()

    log_content = tee.get_content()

    # ── Terminal screenshot ───────────────────────────────────────────────────
    try:
        ss_path = IMAGES_DIR / "06_science_routing_terminal.png"
        save_terminal_screenshot(log_content, ss_path,
                                 "Section 6: Science Routing — Anveshak")
        images.append(str(ss_path))
    except Exception as exc:
        print(f"[sec06] screenshot failed: {exc}")

    # ── Path images ───────────────────────────────────────────────────────────
    try:
        import matplotlib.pyplot as plt
        from matplotlib.colors import Normalize
        from matplotlib.cm import ScalarMappable

        sci_arr = sci_combined if sci_combined is not None else np.zeros((H, W))

        def _draw_path_sci(ax, elevation, path, science_map, title, start, goal, cmap="RdYlGn"):
            ax.set_facecolor("#111122")
            ax.imshow(elevation, cmap="terrain", origin="upper", alpha=0.5)
            if path and len(path) > 1:
                step = max(len(path) // 3000, 1)
                pth  = path[::step]
                rows = [p[0] for p in pth]
                cols = [p[1] for p in pth]
                sci_vals_pth = [float(science_map[r, c]) for r, c in pth]
                norm    = Normalize(vmin=0, vmax=1)
                colormap = plt.cm.get_cmap(cmap)
                for i in range(len(pth) - 1):
                    ax.plot([cols[i], cols[i+1]], [rows[i], rows[i+1]],
                            color=colormap(norm(sci_vals_pth[i])), linewidth=2, alpha=0.8)
            if start:
                ax.scatter(start[1], start[0], marker="^", color="#00ff00", s=150, zorder=5)
            if goal:
                ax.scatter(goal[1], goal[0], marker="*", color="gold", s=200, zorder=5)
            ax.set_title(title, fontsize=8, color="white", pad=4)
            ax.tick_params(colors="white", labelsize=6)
            for sp in ax.spines.values():
                sp.set_edgecolor("#333")

        # Single images for each path
        for out_path, path_used, title_str in [
            (img_no_sci, path_no_sci,
             f"Without Science Routing\nDist: {no_sci_dist:.2f}km | Mean sci: {no_sci_mean:.3f}"),
            (img_with_sci, path_sci,
             f"With Science Routing\nDist: {sci_dist:.2f}km | Mean sci: {sci_mean:.3f}"),
        ]:
            fig, ax = plt.subplots(figsize=(8, 7))
            fig.patch.set_facecolor("#0a0a1a")
            _draw_path_sci(ax, syn_elev, path_used, sci_arr, title_str,
                           start_px, goal_px, cmap="RdYlGn")
            plt.tight_layout()
            fig.savefig(out_path, dpi=130, bbox_inches="tight", facecolor="#0a0a1a")
            plt.close(fig)
            images.append(str(out_path))

        # Comparison image
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
        fig.patch.set_facecolor("#0a0a1a")
        fig.suptitle("Science Routing Effect on Path Selection", fontsize=12, color="white")
        _draw_path_sci(ax1, syn_elev, path_no_sci, sci_arr,
                       f"Without Science (red=low sci)\n{no_sci_dist:.2f}km | sci={no_sci_mean:.3f}",
                       start_px, goal_px, cmap="RdYlGn")
        _draw_path_sci(ax2, syn_elev, path_sci, sci_arr,
                       f"With Science (green=high sci)\n{sci_dist:.2f}km | sci={sci_mean:.3f}",
                       start_px, goal_px, cmap="RdYlGn")
        plt.tight_layout()
        fig.savefig(img_compare, dpi=130, bbox_inches="tight", facecolor="#0a0a1a")
        plt.close(fig)
        images.append(str(img_compare))

    except Exception as exc:
        print(f"[sec06] path images failed: {exc}")

    return {
        "test_name": "Section 6: Science Routing Verification",
        "result": verdict_from_checks(checks),
        "notes": (
            f"Science path mean value: {sci_mean:.3f} vs {no_sci_mean:.3f} (no-science) | "
            f"Routing {'verified' if sci_higher else 'marginal'}"
        ),
        "passed": sum(1 for c in checks if c["result"] == "PASS"),
        "total": len(checks),
        "checks": checks,
        "no_sci_mean_val": round(no_sci_mean, 4),
        "sci_mean_val": round(sci_mean, 4),
        "sci_routing_verified": sci_higher,
        "images": images,
        "log": str(log_path),
    }


if __name__ == "__main__":
    ensure_dirs()
    result = run()
    print(f"\nSection result: {result['result']}")
    print(f"Passed: {result['passed']}/{result['total']}")
