"""
core/pathfinder.py — Traverse cost grid construction and A* path planning.

Dependency: numpy, heapq (stdlib)
"""

from __future__ import annotations

import heapq
import math
from math import exp, sqrt

import numpy as np


# ---------------------------------------------------------------------------
# Cost grid
# ---------------------------------------------------------------------------

def build_cost_grid(
    elevation: np.ndarray,
    slope: np.ndarray,
    resolution_m: float,
    max_slope_deg: float,
    slope_penalty_factor: float = 15.0,
    science_map: np.ndarray | None = None,
    science_weight: float = 0.0,
    mobility_risk_map: np.ndarray | None = None,
    mobility_penalty_factor: float = 3.0,
    mobility_impassable_thresh: float = 0.85,
) -> np.ndarray:
    """Build a per-pixel traversal cost grid for the A* planner.

    Impassable pixels (slope > *max_slope_deg* or NaN) are set to inf.
    Passable pixels receive a cost of ``resolution_m * exp(slope / slope_penalty_factor)``.

    slope_penalty_factor=15.0: derived from the energy model — at a typical 10° slope,
    exp(10/15)=1.95× vs exp(10/10)=2.72×. The energy model shows ~52% uphill cost increase
    at moderate slopes (sin(10°)×SLOPE_MOTOR_FACTOR=3.0); factor=15 matches this gradient
    more faithfully than the previous value of 10 which over-penalised gentle slopes.

    Parameters
    ----------
    elevation : np.ndarray
        2-D elevation array in metres.
    slope : np.ndarray
        2-D slope array in degrees.
    resolution_m : float
        Ground sampling distance in metres per pixel.
    max_slope_deg : float
        Slope threshold above which a pixel is considered impassable.
    slope_penalty_factor : float
        Denominator in the exponent; larger = gentler penalty curve.
    science_map : np.ndarray | None
        Float32 science value raster in [0, 1] from build_science_map().
        When provided with science_weight > 0, reduces traversal cost at
        scientifically valuable pixels so A* naturally routes through them.
    science_weight : float
        Derived from rover priority slider: priority × 0.5.  Maximum 50%
        cost reduction preserves energy safety margin (design choice).
    mobility_risk_map : np.ndarray | None
        Float32 Bekker-Wong sinkage risk raster in [0, 1] from
        core.mobility.compute_trafficability_map().  0 = safe nominal
        regolith; 1 = sinkage reaches stuck threshold.
        Source: Bekker (1969); Carrier et al. (1991); Wong (2008) §2.5.
    mobility_penalty_factor : float
        Exponent multiplier for soft terrain: cost ×= exp(risk × factor).
        3.0 aligns with SLOPE_MOTOR_FACTOR so soft-soil and steep-slope
        penalties are comparable in magnitude.
    mobility_impassable_thresh : float
        Mobility risk above which a pixel is marked impassable (cost=inf).
        0.85 means z ≥ 85 % of the stuck-threshold sinkage — consistent with
        the safety margin recommended in Wong (2008) §2.5.

    Returns
    -------
    cost_grid : np.ndarray
        2-D float32 array; inf where impassable, positive elsewhere.
    """
    cost = np.full(slope.shape, np.inf, dtype=np.float32)

    passable = (
        np.isfinite(slope) &
        np.isfinite(elevation) &
        (slope <= max_slope_deg)
    )

    cost[passable] = np.float32(resolution_m) * np.exp(
        slope[passable].astype(np.float32) / np.float32(slope_penalty_factor)
    )

    # Science discount: reduce traversal cost at high-value pixels.
    # Multiplicative factor (1 − w·s) where s∈[0,1], w∈[0,0.5].
    # Floor at 0.1 keeps cost bounded so A* heuristic stays admissible.
    if science_map is not None and science_weight > 0.0:
        discount = np.float32(1.0) - (
            np.float32(science_weight) * science_map[passable].astype(np.float32)
        )
        discount = np.clip(discount, np.float32(0.1), np.float32(1.0))
        cost[passable] *= discount

    # Soft terrain (Bekker-Wong) mobility penalty.
    # Pixels whose sinkage risk ≥ mobility_impassable_thresh are blocked (cost=inf);
    # remaining high-risk pixels receive an exponential cost surcharge so A*
    # naturally routes around soft areas when an alternative exists.
    # Source: Bekker (1969); Wong (2008) §2.5; Arvidson et al. (2011).
    if mobility_risk_map is not None:
        thresh = np.float32(mobility_impassable_thresh)
        too_soft = passable & (mobility_risk_map >= thresh)
        cost[too_soft] = np.inf

        safe_soft = passable & (mobility_risk_map < thresh)
        risk_vals  = mobility_risk_map[safe_soft].astype(np.float32)
        cost[safe_soft] *= np.exp(risk_vals * np.float32(mobility_penalty_factor))

    return cost


# ---------------------------------------------------------------------------
# Snap to passable pixel
# ---------------------------------------------------------------------------

def snap_to_passable(
    point: tuple[int, int],
    cost_grid: np.ndarray,
    max_radius: int = 50,
) -> tuple[int, int] | None:
    """Find the nearest passable pixel to *point* within *max_radius*.

    Uses an expanding square-ring search. Returns the closest passable
    (row, col) or ``None`` if nothing found within the search radius.
    """
    r, c = point
    rows, cols = cost_grid.shape

    if 0 <= r < rows and 0 <= c < cols and np.isfinite(cost_grid[r, c]):
        return (r, c)

    for radius in range(1, max_radius + 1):
        best = None
        best_dist = float("inf")
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if abs(dr) != radius and abs(dc) != radius:
                    continue  # only the ring perimeter
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and np.isfinite(cost_grid[nr, nc]):
                    dist = dr * dr + dc * dc
                    if dist < best_dist:
                        best = (nr, nc)
                        best_dist = dist
        if best is not None:
            return best

    return None


# ---------------------------------------------------------------------------
# Path reconstruction
# ---------------------------------------------------------------------------

def reconstruct_path(
    came_from: dict[tuple, tuple],
    start: tuple[int, int],
    goal: tuple[int, int],
) -> list[tuple[int, int]]:
    """Walk the *came_from* dict backwards to build the ordered path.

    Parameters
    ----------
    came_from : dict
        Mapping from each visited pixel to its predecessor.
    start : tuple[int, int]
        (row, col) of the path start (termination condition).
    goal : tuple[int, int]
        (row, col) of the path end (reconstruction starts here).

    Returns
    -------
    list[tuple[int, int]]
        Ordered pixel list from *start* to *goal* inclusive.
    """
    path = []
    current = goal
    while current != start:
        path.append(current)
        current = came_from[current]
    path.append(start)
    path.reverse()
    return path


# ---------------------------------------------------------------------------
# A* planner
# ---------------------------------------------------------------------------

_NEIGHBOURS = [
    (-1, -1), (-1, 0), (-1, 1),
    ( 0, -1),           ( 0, 1),
    ( 1, -1), ( 1, 0), ( 1, 1),
]
_SQRT2 = sqrt(2.0)


def astar(
    cost_grid: np.ndarray,
    start: tuple[int, int],
    goal: tuple[int, int],
    max_iterations: int = 2_000_000,
) -> list[tuple[int, int]] | None:
    """Find the minimum-cost path from *start* to *goal* using A*.

    Uses an 8-directional neighbourhood. The heuristic is the Euclidean
    distance to the goal weighted by the minimum finite cell cost.

    Parameters
    ----------
    cost_grid : np.ndarray
        2-D cost array produced by :func:`build_cost_grid`.
    start : tuple[int, int]
        (row, col) of the starting pixel.
    goal : tuple[int, int]
        (row, col) of the destination pixel.
    max_iterations : int
        Safety cap; returns None if exceeded.

    Returns
    -------
    list[tuple[int, int]] | None
        Ordered list of (row, col) pixels from *start* to *goal* inclusive,
        or ``None`` if no path exists.
    """
    rows, cols = cost_grid.shape
    sr, sc = start
    gr, gc = goal

    # Guard: start or goal impassable
    if not np.isfinite(cost_grid[sr, sc]):
        print("[astar] Start pixel is impassable.")
        return None
    if not np.isfinite(cost_grid[gr, gc]):
        print("[astar] Goal pixel is impassable.")
        return None

    # Precompute minimum finite cost for the admissible heuristic
    finite_mask = np.isfinite(cost_grid)
    if not finite_mask.any():
        return None
    min_cost = float(cost_grid[finite_mask].min())

    def heuristic(nr: int, nc: int) -> float:
        return sqrt((gr - nr) ** 2 + (gc - nc) ** 2) * min_cost

    # g_score[node] = cheapest cost from start so far
    g_score: dict[tuple[int, int], float] = {start: 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}

    # heap: (f, g, row, col)
    open_heap: list[tuple[float, float, int, int]] = []
    heapq.heappush(open_heap, (heuristic(sr, sc), 0.0, sr, sc))

    closed: set[tuple[int, int]] = set()
    iterations = 0

    while open_heap:
        if iterations % 100_000 == 0 and iterations > 0:
            print(f"[astar] Progress: {iterations:,} iterations, "
                  f"open={len(open_heap):,}, closed={len(closed):,}")

        if iterations >= max_iterations:
            print(f"[astar] Reached max_iterations ({max_iterations:,}) — no path found.")
            return None

        f, g, r, c = heapq.heappop(open_heap)
        iterations += 1

        if (r, c) in closed:
            continue

        if (r, c) == goal:
            print(f"[astar] Path found in {iterations:,} iterations.")
            return reconstruct_path(came_from, start, goal)

        closed.add((r, c))

        for dr, dc in _NEIGHBOURS:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            if (nr, nc) in closed:
                continue

            cell_cost = cost_grid[nr, nc]
            if not math.isfinite(cell_cost):
                continue

            # Diagonal moves cost sqrt(2) × cell cost
            move_cost = cell_cost * (_SQRT2 if abs(dr) + abs(dc) == 2 else 1.0)
            tentative_g = g + move_cost

            if tentative_g < g_score.get((nr, nc), math.inf):
                g_score[(nr, nc)] = tentative_g
                came_from[(nr, nc)] = (r, c)
                f_new = tentative_g + heuristic(nr, nc)
                heapq.heappush(open_heap, (f_new, tentative_g, nr, nc))

    print("[astar] Open set exhausted — no path exists.")
    return None


# ---------------------------------------------------------------------------
# Path statistics
# ---------------------------------------------------------------------------

def compute_path_stats(
    path: list[tuple[int, int]],
    slope: np.ndarray,
    resolution_m: float,
    speed_kmh: float,
) -> dict:
    """Compute distance, slope, and time statistics for a planned path.

    Parameters
    ----------
    path : list[tuple[int, int]]
        Ordered (row, col) pixel list from :func:`astar`.
    slope : np.ndarray
        2-D slope array in degrees (same grid as cost grid).
    resolution_m : float
        Ground sampling distance in metres per pixel.
    speed_kmh : float
        Assumed rover travel speed in km/h.

    Returns
    -------
    dict with keys:
        total_distance_m, total_distance_km, max_slope_deg,
        mean_slope_deg, estimated_time_hrs, waypoint_count
    """
    if not path:
        return {
            "total_distance_m": 0.0,
            "total_distance_km": 0.0,
            "max_slope_deg": 0.0,
            "mean_slope_deg": 0.0,
            "estimated_time_hrs": 0.0,
            "waypoint_count": 0,
        }

    total_m = 0.0
    slope_values = []

    for i in range(len(path) - 1):
        r0, c0 = path[i]
        r1, c1 = path[i + 1]
        dr = abs(r1 - r0)
        dc = abs(c1 - c0)
        step_m = resolution_m * (_SQRT2 if dr + dc == 2 else 1.0)
        total_m += step_m
        slope_values.append(float(slope[r1, c1]))

    # Include slope at start pixel too
    sr, sc = path[0]
    slope_values.insert(0, float(slope[sr, sc]))

    valid_slopes = [s for s in slope_values if math.isfinite(s)]
    max_slope = max(valid_slopes) if valid_slopes else 0.0
    mean_slope = sum(valid_slopes) / len(valid_slopes) if valid_slopes else 0.0

    total_km = total_m / 1000.0
    time_hrs = total_km / speed_kmh if speed_kmh > 0 else 0.0

    return {
        "total_distance_m": total_m,
        "total_distance_km": total_km,
        "max_slope_deg": max_slope,
        "mean_slope_deg": mean_slope,
        "estimated_time_hrs": time_hrs,
        "waypoint_count": len(path),
    }


# ---------------------------------------------------------------------------
# Waypoint generation
# ---------------------------------------------------------------------------

def generate_waypoints(
    top_sites: list[dict],
    mission_type: str,
    n: int = 3,
    anomalies: list[dict] | None = None,
    science_map: np.ndarray | None = None,
    science_experiments: list[str] | None = None,
) -> list[tuple[int, int]]:
    """Select up to *n* waypoints from *top_sites* filtered by mission priority.

    If *anomalies* are provided, mission-relevant anomaly clusters are preferred
    over simple top_sites sorting. Falls back to top_sites for any remaining
    slots when there are fewer relevant anomalies than *n*.

    Sorting rules (top_sites fallback)
    -----------------------------------
    water_ice   → sort by ``lat`` ascending (most negative = nearest 90°S)
    geological  → sort by ``roughness_m`` descending
    atmospheric → sort by ``elevation_m`` descending

    Parameters
    ----------
    top_sites : list[dict]
        Site dicts from :func:`~core.landing_scorer.score_terrain`.
    mission_type : str
        One of ``'water_ice'``, ``'geological'``, ``'atmospheric'``.
    n : int
        Maximum number of waypoints to return.
    anomalies : list[dict] | None
        Optional anomaly dicts from :func:`~core.anomaly_detector.detect_anomalies`.

    Returns
    -------
    list[tuple[int, int]]
        Up to *n* ``(pixel_row, pixel_col)`` tuples.
    """
    if not top_sites:
        return []

    # When science experiments are selected, re-score top_sites by blending
    # final_score (60%) with science value at the site pixel (40%).
    # This ensures waypoints favour scientifically rich terrain while still
    # respecting the overall mission priority score.
    if science_map is not None and science_experiments:
        h, w = science_map.shape
        top_sites = sorted(
            top_sites,
            key=lambda s: (
                np.float32(0.6) * s["final_score"]
                + np.float32(0.4) * float(
                    science_map[
                        max(0, min(s["pixel_row"], h - 1)),
                        max(0, min(s["pixel_col"], w - 1)),
                    ]
                )
            ),
            reverse=True,
        )

    # ---- Anomaly-based waypoints (preferred when available) ----
    if anomalies:
        relevant = sorted(
            [a for a in anomalies if mission_type in a.get("recommended_for", [])],
            key=lambda a: a["anomaly_strength"],
            reverse=True,
        )
        if len(relevant) >= n:
            return [(a["centroid_row"], a["centroid_col"]) for a in relevant[:n]]

        # Partial fill: use all relevant anomaly waypoints, pad with top_sites
        wpts: list[tuple[int, int]] = [
            (a["centroid_row"], a["centroid_col"]) for a in relevant
        ]
        seen: set[tuple[int, int]] = set(wpts)

        # Build sorted top_sites fallback (already re-scored above if science active)
        if mission_type == "water_ice":
            sorted_sites = sorted(top_sites, key=lambda s: s["lat"])
        elif mission_type == "geological":
            sorted_sites = sorted(top_sites, key=lambda s: s["roughness_m"], reverse=True)
        elif mission_type == "atmospheric":
            sorted_sites = sorted(top_sites, key=lambda s: s["elevation_m"], reverse=True)
        else:
            sorted_sites = top_sites[:]

        for s in sorted_sites:
            if len(wpts) >= n:
                break
            pt = (s["pixel_row"], s["pixel_col"])
            if pt not in seen:
                wpts.append(pt)
                seen.add(pt)
        return wpts

    # ---- Default: sort top_sites by mission priority ----
    if mission_type == "water_ice":
        sorted_sites = sorted(top_sites, key=lambda s: s["lat"])
    elif mission_type == "geological":
        sorted_sites = sorted(top_sites, key=lambda s: s["roughness_m"], reverse=True)
    elif mission_type == "atmospheric":
        sorted_sites = sorted(top_sites, key=lambda s: s["elevation_m"], reverse=True)
    else:
        sorted_sites = top_sites[:]

    return [(s["pixel_row"], s["pixel_col"]) for s in sorted_sites[:n]]


# ---------------------------------------------------------------------------
# Public API entry point
# ---------------------------------------------------------------------------

def find_path(
    slope: np.ndarray,
    start: tuple[int, int],
    goal: tuple[int, int],
    rover_profile: dict,
    resolution_m: float = 60.0,
    elevation: np.ndarray | None = None,
    science_map: np.ndarray | None = None,
    mobility_risk_map: np.ndarray | None = None,
) -> tuple[list[tuple[int, int]] | None, dict | None]:
    """Plan a rover path from *start* to *goal* on the given terrain.

    Parameters
    ----------
    slope : np.ndarray
        2-D slope array in degrees.
    start : tuple[int, int]
        (row, col) origin pixel.
    goal : tuple[int, int]
        (row, col) destination pixel.
    rover_profile : dict
        Must contain ``max_slope_deg``, ``speed_kmh`` (optional, default 0.5),
        and optionally ``slope_penalty_factor`` (default 10.0).
    resolution_m : float
        Ground sampling distance in metres per pixel.
    elevation : np.ndarray | None
        2-D elevation array; synthesised as zeros if not provided.
    mobility_risk_map : np.ndarray | None
        Float32 Bekker-Wong sinkage risk raster [0, 1] from
        core.mobility.compute_trafficability_map(); None disables soft terrain
        routing.  Passed straight through to build_cost_grid().

    Returns
    -------
    (path, stats) : tuple
        ``path`` is the ordered pixel list or ``None`` if unreachable.
        ``stats`` is the dict from :func:`compute_path_stats` or ``None``.
    """
    if elevation is None:
        elevation = np.zeros_like(slope)

    max_slope_deg  = float(rover_profile.get("max_slope_deg", 20.0))
    penalty_factor = float(rover_profile.get("slope_penalty_factor", 15.0))
    speed_kmh      = float(rover_profile.get("speed_kmh", 0.5))
    # science_weight = priority × 0.5 so max discount is 50% at priority=1.0
    science_weight = float(rover_profile.get("priority", 0.0)) * 0.5

    cost_grid = build_cost_grid(
        elevation, slope, resolution_m, max_slope_deg, penalty_factor,
        science_map=science_map, science_weight=science_weight,
        mobility_risk_map=mobility_risk_map,
    )

    # Snap start and goal to nearest passable pixels
    snapped_start = snap_to_passable(start, cost_grid)
    snapped_goal = snap_to_passable(goal, cost_grid)

    if snapped_start is None or snapped_goal is None:
        print(f"[find_path] Cannot snap start={start} or goal={goal} to passable pixel.")
        return None, None

    if snapped_start != start:
        print(f"[find_path] Snapped start {start} -> {snapped_start}")
    if snapped_goal != goal:
        print(f"[find_path] Snapped goal {goal} -> {snapped_goal}")

    path = astar(cost_grid, snapped_start, snapped_goal)

    if path is None:
        return None, None

    stats = compute_path_stats(path, slope, resolution_m, speed_kmh)

    from core.energy_model import compute_path_energy  # noqa: PLC0415
    energy_stats = compute_path_energy(
        path, slope, rover_profile, resolution_m, elevation,
        mobility_risk_map=mobility_risk_map,
    )
    stats.update(energy_stats)   # no key collisions — all new keys

    # battery_feasible: False when the path demands more energy than the rover's battery.
    # A value >100% means the rover runs out of power mid-traverse — caller should warn.
    stats["battery_feasible"] = stats.get("battery_pct_used", 0.0) <= 100.0

    return path, stats


# ---------------------------------------------------------------------------
# __main__ verification
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from pathlib import Path

    _SQRT2_DIAG = sqrt(2.0)

    # -----------------------------------------------------------------------
    # Step 1: Synthetic 20×20 test
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("Step 1: Synthetic 20×20 grid test")
    print("=" * 60)

    ROWS, COLS = 20, 20
    resolution_m = 60.0
    max_slope = 15.0

    # Flat terrain
    syn_slope = np.zeros((ROWS, COLS), dtype=np.float32)
    syn_elev  = np.zeros((ROWS, COLS), dtype=np.float32)

    # Wall: column 10, rows 0–15 → impassable (slope = 999)
    syn_slope[0:16, 10] = 999.0

    cost = build_cost_grid(syn_elev, syn_slope, resolution_m, max_slope)

    start = (0, 0)
    goal  = (0, 19)

    print(f"Start: {start}  Goal: {goal}")
    print(f"Wall: column 10, rows 0–15  (path must go around bottom)")

    path = astar(cost, start, goal)

    if path is None:
        print("ERROR: No path found in synthetic test!")
    else:
        print(f"Path length: {len(path)} pixels")
        # Print full path
        print("Path coords:", path)

        rover_profile = {"max_slope_deg": max_slope, "speed_kmh": 0.5}
        stats = compute_path_stats(path, syn_slope, resolution_m, speed_kmh=0.5)
        print()
        print("Stats:")
        for k, v in stats.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.3f}")
            else:
                print(f"  {k}: {v}")

    # -----------------------------------------------------------------------
    # Step 2: Real terrain (if DEM exists)
    # -----------------------------------------------------------------------
    _DEM_CANDIDATES = [
        Path("data/raw/ldem_87s_5mpp.tif"),
        Path("data/raw/ldem_5mpp.tif"),
        Path("data/ldem_87s_5mpp.tif"),
    ]
    dem_exists = any(p.exists() for p in _DEM_CANDIDATES)

    print()
    print("=" * 60)
    print("Step 2: Real terrain test")
    print("=" * 60)

    if not dem_exists:
        print("DEM file not found — skipping real terrain test.")
    else:
        try:
            from core.terrain import load_terrain
            from core.landing_scorer import score_terrain

            print("Loading terrain …")
            elevation, slope, roughness, profile = load_terrain()
            res_m = float(profile.get("resolution_m", 60.0))

            water_ice_profile = dict(
                mission_type="water_ice",
                power_source="rtg",
                max_slope_deg=15,
                min_flat_radius_m=300,
                priority=0.3,
                speed_kmh=0.5,
            )

            print("Scoring terrain …")
            _, _, _, top_sites = score_terrain(
                elevation, slope, roughness, profile, water_ice_profile
            )

            if len(top_sites) < 2:
                print("Fewer than 2 sites scored — cannot plan a path.")
            else:
                waypoints = generate_waypoints(top_sites, "water_ice", n=3)
                print(f"Top site:      pixel {top_sites[0]['pixel_row']}, {top_sites[0]['pixel_col']}")
                print(f"First waypoint: pixel {waypoints[0]}")

                wp_start = (top_sites[0]["pixel_row"], top_sites[0]["pixel_col"])
                wp_goal  = waypoints[0]

                if wp_start == wp_goal:
                    wp_goal = waypoints[1] if len(waypoints) > 1 else (
                        top_sites[1]["pixel_row"], top_sites[1]["pixel_col"]
                    )

                print(f"Planning path: {wp_start} → {wp_goal}")
                path, stats = find_path(
                    slope, wp_start, wp_goal, water_ice_profile,
                    resolution_m=res_m, elevation=elevation
                )

                if path is None:
                    print("No path found (may have hit max_iterations or terrain is fully blocked).")
                else:
                    print()
                    print("Path Stats:")
                    print(f"  {'Waypoints':<22}: {stats['waypoint_count']}")
                    print(f"  {'Distance (m)':<22}: {stats['total_distance_m']:.1f}")
                    print(f"  {'Distance (km)':<22}: {stats['total_distance_km']:.3f}")
                    print(f"  {'Max slope (deg)':<22}: {stats['max_slope_deg']:.2f}")
                    print(f"  {'Mean slope (deg)':<22}: {stats['mean_slope_deg']:.2f}")
                    print(f"  {'Est. time (hrs)':<22}: {stats['estimated_time_hrs']:.2f}")

        except Exception as exc:
            print(f"Real terrain test failed: {exc}")
            raise
