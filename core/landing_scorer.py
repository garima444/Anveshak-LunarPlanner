"""
core/landing_scorer.py — Landing site scoring for lunar south-pole rover missions.

Inputs:  elevation, slope, roughness, profile  from terrain.load_terrain()
         rover_profile dict (mission_type, power_source, max_slope_deg,
                             min_flat_radius_m, priority)

Outputs: safety_score, mission_score, final_score   float32 arrays, same shape
         top_sites                                   list of 10 dicts

All scoring is fully vectorised — no Python loops over pixels.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pyproj
import rasterio.crs
import rasterio.transform
from affine import Affine
from scipy.ndimage import maximum_filter, uniform_filter

# ---------------------------------------------------------------------------
# CRS strings  (mirror terrain.py — keeps this module self-contained)
# ---------------------------------------------------------------------------

_CRS_STERE = (
    "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
    "+R=1737400 +units=m +no_defs"
)
_CRS_LONLAT = "+proj=longlat +R=1737400 +no_defs"

# Crater-rim detection parameters
_EXTREME_SLOPE_DEG = 35.0   # slope threshold that marks a crater rim
_RIM_RADIUS_PX     = 8      # dilation radius for rim penalty (~480 m at 60 m/px)

# Latitude-grid strip size  (rows processed per pyproj batch)
_LAT_GRID_STRIP = 50

# Module-level cached transformer
_TRANSFORMER: pyproj.Transformer | None = None


def _get_transformer() -> pyproj.Transformer:
    global _TRANSFORMER
    if _TRANSFORMER is None:
        _TRANSFORMER = pyproj.Transformer.from_crs(
            _CRS_STERE, _CRS_LONLAT, always_xy=True
        )
    return _TRANSFORMER


def _pixel_to_latlon(row: int | float, col: int | float, profile: dict) -> tuple[float, float]:
    """Convert pixel (row, col) → (lon_deg, lat_deg) using the profile affine."""
    x, y = rasterio.transform.xy(profile["transform"], row, col)
    lon, lat = _get_transformer().transform(x, y)
    return float(lon), float(lat)


# ---------------------------------------------------------------------------
# Latitude grid
# ---------------------------------------------------------------------------

def _build_lat_grid(profile: dict) -> np.ndarray:
    """Return float32 (H, W) array of latitude in decimal degrees.

    Processes in strips of _LAT_GRID_STRIP rows to keep peak memory low
    (~4 MB per strip for a 10 133-column array).
    """
    T   = profile["transform"]
    H   = profile["height"]
    W   = profile["width"]
    res = float(T.a)    # pixel width (positive metres)
    x0  = float(T.c)    # top-left x  (polar-stere metres)
    y0  = float(T.f)    # top-left y  (polar-stere metres)

    x_1d = x0 + np.arange(W, dtype=np.float64) * res
    y_1d = y0 - np.arange(H, dtype=np.float64) * res   # y decreases downward

    tr       = _get_transformer()
    lat_grid = np.empty((H, W), dtype=np.float32)

    for r0 in range(0, H, _LAT_GRID_STRIP):
        r1     = min(r0 + _LAT_GRID_STRIP, H)
        n_rows = r1 - r0
        xs     = np.tile(x_1d, n_rows)                 # (n_rows*W,)
        ys     = np.repeat(y_1d[r0:r1], W)             # (n_rows*W,)
        _, lats = tr.transform(xs, ys)
        lat_grid[r0:r1] = lats.reshape(n_rows, W).astype(np.float32)

    return lat_grid


# ---------------------------------------------------------------------------
# Safety scorer
# ---------------------------------------------------------------------------

def _compute_safety_score(
    elevation    : np.ndarray,
    slope        : np.ndarray,
    roughness    : np.ndarray,
    quality_mask : np.ndarray | None,
    max_slope_deg: float,
    flat_radius_px: int,
) -> np.ndarray:
    """Return float32 (H, W) safety score in [0, 1].

    Sub-scores (all in [0, 1], higher = better):
      slope_sub    — lower slope is safer
      rough_sub    — lower roughness is safer
      qual_sub     — higher data-count mask quality is safer
      flat_sub     — larger flat neighbourhood is safer
    Penalties applied multiplicatively:
      crater-rim zone — ×0.4
    Hard zeros:
      slope > max_slope_deg  or  nan elevation → 0
    """
    ms = np.float32(max_slope_deg)
    passable = (slope <= ms) & np.isfinite(elevation)

    # ---- 1. Slope sub-score ------------------------------------------------
    slope_sub = np.float32(1.0) - np.clip(
        slope.astype(np.float32) / ms,
        np.float32(0.0), np.float32(1.0),
    )
    slope_sub = np.where(np.isfinite(slope_sub), slope_sub, np.float32(0.0))

    # ---- 2. Roughness sub-score  exp(-r / r95) -----------------------------
    r95 = float(np.nanpercentile(roughness, 95))
    r95 = r95 if r95 > 1e-6 else 1.0
    rough_sub = np.exp((-roughness.astype(np.float32)) / np.float32(r95))
    rough_sub = np.where(np.isfinite(rough_sub), rough_sub, np.float32(0.0))

    # ---- 3. Quality sub-score ----------------------------------------------
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

    # ---- 4. Crater-rim proximity penalty -----------------------------------
    extreme = (slope >= np.float32(_EXTREME_SLOPE_DEG)).astype(np.float32)
    rim_zone = maximum_filter(extreme, size=_RIM_RADIUS_PX * 2 + 1)
    rim_penalty = np.where(rim_zone > 0, np.float32(0.4), np.float32(1.0))

    # ---- 5. Flat-area sub-score --------------------------------------------
    if flat_radius_px > 0:
        kernel = flat_radius_px * 2 + 1
        flat_frac = uniform_filter(passable.astype(np.float32), size=kernel)
        flat_sub  = np.clip(
            flat_frac / np.float32(0.5), np.float32(0.0), np.float32(1.0)
        )
    else:
        flat_sub = np.ones(elevation.shape, dtype=np.float32)

    # ---- 6. Combine --------------------------------------------------------
    score = (
        np.float32(0.50) * slope_sub
        + np.float32(0.25) * rough_sub
        + np.float32(0.15) * qual_sub
        + np.float32(0.10) * flat_sub
    )
    score *= rim_penalty

    # ---- 7. Hard-zero impassable & nodata ----------------------------------
    score[~passable] = np.float32(0.0)
    return score.astype(np.float32)


# ---------------------------------------------------------------------------
# Mission scorer
# ---------------------------------------------------------------------------

def _nanfill(arr: np.ndarray) -> np.ndarray:
    """Return float32 copy of *arr* with NaN replaced by the global nanmean."""
    out  = arr.astype(np.float32)
    mask = ~np.isfinite(out)
    if mask.any():
        out[mask] = np.float32(float(np.nanmean(out)))
    return out


def _compute_mission_score(
    elevation   : np.ndarray,
    slope       : np.ndarray,
    roughness   : np.ndarray,
    lat_grid    : np.ndarray,
    mission_type: str,
    power_source: str,
    resolution_m: float,
) -> np.ndarray:
    """Return float32 (H, W) mission-specific score in [0, 1].

    water_ice  — rewards near-polar lat and low-elevation (PSR) craters.
    geological — rewards terrain diversity, elevation transitions, accessibility.
    atmospheric — rewards high ridges and maximum sunlight exposure.
    """
    nodata = ~np.isfinite(elevation)
    elev_f = _nanfill(elevation)

    # ------------------------------------------------------------------ water_ice
    if mission_type == "water_ice":
        # Reward latitudes south of -88°S
        lat_score = np.clip(
            (np.float32(-88.0) - lat_grid) / np.float32(2.0),
            np.float32(0.0), np.float32(1.0),
        )

        # Reward deep crater floors (potential PSR)
        e5  = float(np.nanpercentile(elevation, 5))
        e95 = float(np.nanpercentile(elevation, 95))
        span = max(e95 - e5, 1.0)
        psr_score = np.clip(
            (np.float32(e95) - elev_f) / np.float32(span),
            np.float32(0.0), np.float32(1.0),
        )

        # Solar rovers penalised in dark (deep) areas
        if power_source == "solar":
            psr_score = psr_score * np.float32(0.3)

        score = np.float32(0.5) * lat_score + np.float32(0.5) * psr_score

    # ------------------------------------------------------------------ geological
    elif mission_type == "geological":
        rough_f = _nanfill(roughness)

        # Local roughness variance — rewards terrain diversity
        r_mean    = uniform_filter(rough_f, size=20)
        r_sq_mean = uniform_filter(rough_f * rough_f, size=20)
        r_var     = np.sqrt(np.maximum(r_sq_mean - r_mean * r_mean, np.float32(0.0)))
        rv95 = float(np.nanpercentile(r_var, 95))
        rv95 = rv95 if rv95 > 1e-6 else 1.0
        var_norm  = np.clip(r_var / np.float32(rv95), np.float32(0.0), np.float32(1.0))

        # Elevation gradient magnitude — rewards geological boundaries
        # (float32 finite-difference to avoid float64 promotion and ~800 MB overhead)
        gx = np.empty_like(elev_f)
        gx[:, 1:-1] = (elev_f[:, 2:] - elev_f[:, :-2]) * np.float32(0.5)
        gx[:, 0]    = elev_f[:, 1] - elev_f[:, 0]
        gx[:, -1]   = elev_f[:, -1] - elev_f[:, -2]
        gy = np.empty_like(elev_f)
        gy[1:-1]    = (elev_f[2:] - elev_f[:-2]) * np.float32(0.5)
        gy[0]       = elev_f[1] - elev_f[0]
        gy[-1]      = elev_f[-1] - elev_f[-2]
        grad_mag    = np.sqrt(gx * gx + gy * gy)
        del gx, gy
        g95 = float(np.nanpercentile(grad_mag, 95))
        g95 = g95 if g95 > 1e-6 else 1.0
        grad_norm = np.clip(grad_mag / np.float32(g95), np.float32(0.0), np.float32(1.0))
        del grad_mag

        # Accessibility — bell-curve centred at -86.5°S (between -85 and -88)
        access_score = np.exp(
            -(lat_grid - np.float32(-86.5)) ** 2 / np.float32(2.0 * 1.5 ** 2)
        )

        score = (
            np.float32(0.40) * var_norm
            + np.float32(0.35) * grad_norm
            + np.float32(0.25) * access_score
        )

    # ------------------------------------------------------------------ atmospheric
    else:
        e_med  = float(np.nanmedian(elevation))
        e_95   = float(np.nanpercentile(elevation, 95))
        e_5    = float(np.nanpercentile(elevation, 5))
        span1  = max(e_95 - e_med, 1.0)
        span2  = max(e_95 - e_5,  1.0)

        # High-ridge score — rewards elevated terrain
        ridge_score = np.clip(
            (elev_f - np.float32(e_med)) / np.float32(span1),
            np.float32(0.0), np.float32(1.0),
        )

        # Sunlight score — rewards high elevation (inverse of PSR proxy)
        sun_score = np.clip(
            (elev_f - np.float32(e_5)) / np.float32(span2),
            np.float32(0.0), np.float32(1.0),
        )

        score = np.float32(0.5) * ridge_score + np.float32(0.5) * sun_score

    score = np.where(np.isfinite(score), score, np.float32(0.0))
    score[nodata] = np.float32(0.0)
    return score.astype(np.float32)


# ---------------------------------------------------------------------------
# Score blending
# ---------------------------------------------------------------------------

def _blend_scores(
    safety  : np.ndarray,
    mission : np.ndarray,
    priority: float,
) -> np.ndarray:
    """Combine safety and mission scores weighted by *priority* (0–1).

    priority < 0.5  → safety-first   (0.7 × safety + 0.3 × mission)
    priority ≥ 0.5  → science-first  (0.4 × safety + 0.6 × mission)
    Impassable pixels (safety == 0) are forced to 0 in the final score.
    """
    if priority < 0.5:
        w_s, w_m = np.float32(0.7), np.float32(0.3)
    else:
        w_s, w_m = np.float32(0.4), np.float32(0.6)

    final = w_s * safety + w_m * mission
    final[safety == np.float32(0.0)] = np.float32(0.0)
    return final.astype(np.float32)


# ---------------------------------------------------------------------------
# Top-site selection
# ---------------------------------------------------------------------------

def _make_reasoning(site: dict, rover_profile: dict) -> str:
    """Return a one-sentence explanation for why this site was selected."""
    mission_type = rover_profile.get("mission_type", "")
    lat  = site["lat"]
    lon  = site["lon"]
    sf   = site["safety_score"]
    ms_  = site["mission_score"]

    if sf > 0.85:
        return (
            f"Exceptionally flat, low-roughness terrain (safety={sf:.2f}) "
            f"ideal for safe touchdown at {lat:.2f}°S, {lon:.2f}°E."
        )
    if mission_type == "water_ice" and lat < -88.5:
        return (
            f"Near-polar location ({lat:.2f}°S) maximises access to "
            f"permanently shadowed regions for ice prospecting (mission={ms_:.2f})."
        )
    if mission_type == "geological":
        return (
            f"Diverse terrain with elevation transitions at {lat:.2f}°S "
            f"offers high geological sampling value (mission={ms_:.2f})."
        )
    if mission_type == "atmospheric" and site["elevation_m"] > 0:
        return (
            f"Elevated ridge at {site['elevation_m']:.0f} m provides "
            f"extended sunlight exposure for power generation (mission={ms_:.2f})."
        )
    return (
        f"Balanced safety ({sf:.2f}) and science ({ms_:.2f}) score "
        f"at {lat:.2f}°S, {lon:.2f}°E."
    )


def _select_top_sites(
    final_score  : np.ndarray,
    elevation    : np.ndarray,
    slope        : np.ndarray,
    roughness    : np.ndarray,
    safety_score : np.ndarray,
    mission_score: np.ndarray,
    profile      : dict,
    rover_profile: dict,
    n            : int = 10,
    min_sep_px   : int = 50,
) -> list[dict]:
    """Pick *n* spatially separated local-maxima sites, sorted by final_score.

    A pixel is a local maximum if it equals the maximum in its *min_sep_px*
    neighbourhood.  Sites are then selected greedily: once a site is accepted,
    any candidate within *min_sep_px* Euclidean pixels is skipped.
    """
    # Local maxima (pixel equals neighbourhood max and has non-zero score)
    nbr           = maximum_filter(final_score, size=min_sep_px)
    is_local_max  = (final_score == nbr) & (final_score > 0)

    rows_arr, cols_arr = np.where(is_local_max)
    if rows_arr.size == 0:
        return []

    scores_arr = final_score[rows_arr, cols_arr]
    order      = np.argsort(scores_arr)[::-1]
    rows_arr   = rows_arr[order]
    cols_arr   = cols_arr[order]

    # Greedy spatial deduplication
    kept_rows: list[int] = []
    kept_cols: list[int] = []

    for r, c in zip(rows_arr.tolist(), cols_arr.tolist()):
        if len(kept_rows) >= n:
            break
        if not any(
            math.hypot(r - kr, c - kc) < min_sep_px
            for kr, kc in zip(kept_rows, kept_cols)
        ):
            kept_rows.append(r)
            kept_cols.append(c)

    # Build result dicts
    sites: list[dict] = []
    for rank, (r, c) in enumerate(zip(kept_rows, kept_cols), start=1):
        lon, lat = _pixel_to_latlon(r, c, profile)
        site: dict = {
            "rank"         : rank,
            "pixel_row"    : int(r),
            "pixel_col"    : int(c),
            "lon"          : float(lon),
            "lat"          : float(lat),
            "elevation_m"  : float(elevation[r, c]),
            "slope_deg"    : float(slope[r, c]),
            "roughness_m"  : float(roughness[r, c]),
            "safety_score" : float(safety_score[r, c]),
            "mission_score": float(mission_score[r, c]),
            "final_score"  : float(final_score[r, c]),
        }
        site["reasoning"] = _make_reasoning(site, rover_profile)
        sites.append(site)

    return sites


# ---------------------------------------------------------------------------
# Synthetic terrain (demo / testing without NASA files)
# ---------------------------------------------------------------------------

def _synthetic_terrain(
    shape: tuple[int, int] = (500, 500),
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Generate simple synthetic lunar terrain for offline testing.

    Creates a flat base with five Gaussian craters and computes slope and
    roughness using the same algorithms as terrain.py.
    """
    H, W = shape
    yy, xx = np.mgrid[:H, :W]

    elevation = np.full((H, W), -1000.0, dtype=np.float32)

    rng = np.random.default_rng(42)
    for _ in range(5):
        cr    = rng.integers(50, H - 50)
        cc    = rng.integers(50, W - 50)
        depth = rng.uniform(500.0, 3000.0)
        sigma = rng.uniform(20.0, 60.0)
        r2    = ((yy - cr) ** 2 + (xx - cc) ** 2).astype(np.float32)
        elevation -= (depth * np.exp(-r2 / np.float32(2.0 * sigma ** 2)))

    # Slope via float32 finite differences
    res = np.float32(60.0)
    dy  = np.empty_like(elevation)
    dy[1:-1] = (elevation[2:] - elevation[:-2]) / (np.float32(2.0) * res)
    dy[0]    = (elevation[1] - elevation[0])  / res
    dy[-1]   = (elevation[-1] - elevation[-2]) / res
    dx  = np.empty_like(elevation)
    dx[:, 1:-1] = (elevation[:, 2:] - elevation[:, :-2]) / (np.float32(2.0) * res)
    dx[:, 0]    = (elevation[:, 1] - elevation[:, 0])  / res
    dx[:, -1]   = (elevation[:, -1] - elevation[:, -2]) / res
    slope = np.degrees(np.arctan(np.sqrt(dx * dx + dy * dy))).astype(np.float32)

    # Roughness via local variance trick
    mean_e  = uniform_filter(elevation.astype(np.float64), size=3).astype(np.float32)
    sq_mean = uniform_filter((elevation.astype(np.float64)) ** 2, size=3).astype(np.float32)
    roughness = np.sqrt(np.maximum(sq_mean - mean_e * mean_e, np.float32(0.0)))

    # Minimal profile
    transform = Affine(60.0, 0.0, -300_000.0, 0.0, -60.0, 300_000.0)
    profile: dict = {
        "crs"         : rasterio.crs.CRS.from_proj4(_CRS_STERE),
        "transform"   : transform,
        "height"      : H,
        "width"       : W,
        "dtype"       : "float32",
        "nodata"      : np.nan,
        "resolution_m": 60.0,
    }
    return elevation, slope, roughness, profile


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_terrain(
    elevation    : np.ndarray,
    slope        : np.ndarray,
    roughness    : np.ndarray,
    profile      : dict,
    rover_profile: dict,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict]]:
    """Score the full terrain and select the top landing sites.

    Parameters
    ----------
    elevation, slope, roughness : np.ndarray
        Float32 arrays of shape (H, W) from terrain.load_terrain().
    profile : dict
        Terrain profile from terrain.load_terrain().
    rover_profile : dict
        mission_type   : 'water_ice' | 'geological' | 'atmospheric'
        power_source   : 'solar' | 'rtg'
        max_slope_deg  : float — rover trafficability limit
        min_flat_radius_m : float — minimum safe flat area radius
        priority       : float  0=max safety, 1=max science

    Returns
    -------
    safety_score : np.ndarray  float32 (H, W)  0–1
    mission_score: np.ndarray  float32 (H, W)  0–1
    final_score  : np.ndarray  float32 (H, W)  0–1
    top_sites    : list[dict]  up to 10 best sites with full metadata
    """
    mission_type  = rover_profile["mission_type"]
    power_source  = rover_profile["power_source"]
    max_slope_deg = float(rover_profile["max_slope_deg"])
    min_flat_r_m  = float(rover_profile["min_flat_radius_m"])
    priority      = float(rover_profile["priority"])
    res_m         = float(profile.get("resolution_m", 60.0))

    flat_radius_px = max(1, round(min_flat_r_m / res_m))
    quality_mask   = profile.get("quality_mask")

    print(
        f"[scorer] mission={mission_type}  power={power_source}  "
        f"max_slope={max_slope_deg}°  priority={priority}"
    )

    print("[scorer] Building latitude grid …")
    lat_grid = _build_lat_grid(profile)

    print("[scorer] Computing safety score …")
    safety = _compute_safety_score(
        elevation, slope, roughness, quality_mask,
        max_slope_deg, flat_radius_px,
    )

    print("[scorer] Computing mission score …")
    mission = _compute_mission_score(
        elevation, slope, roughness, lat_grid,
        mission_type, power_source, res_m,
    )

    print("[scorer] Blending scores …")
    final = _blend_scores(safety, mission, priority)

    print("[scorer] Selecting top sites …")
    top_sites = _select_top_sites(
        final, elevation, slope, roughness,
        safety, mission, profile, rover_profile,
    )

    # ML refinement (if a trained model is available)
    try:
        from core.terrain_classifier import load_classifier, classify_terrain as _classify
        clf = load_classifier()
        if clf is not None:
            print("[scorer] Applying ML terrain classification refinement …")
            class_map = _classify(clf, elevation, slope, roughness, profile)
            for site in top_sites:
                r, c = site["pixel_row"], site["pixel_col"]
                cls = int(class_map[r, c])
                if cls == 4:   # SCIENCE_TARGET — boost
                    site["final_score"] = min(1.0, site["final_score"] + 0.1)
                elif cls == 0:  # HAZARD_ZONE — zero out
                    site["final_score"] = 0.0
            top_sites.sort(key=lambda s: s["final_score"], reverse=True)
            for i, s in enumerate(top_sites, start=1):
                s["rank"] = i
    except ImportError:
        pass

    print(f"[scorer] Done — {len(top_sites)} site(s) selected.")
    return safety, mission, final, top_sites


# ---------------------------------------------------------------------------
# Verification block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Ensure project root is on sys.path when run directly (python core/landing_scorer.py)
    _project_root = str(Path(__file__).parent.parent)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

    _DEM_PATH = Path(_project_root) / "data" / "dem" / "DEM_20M" / "LDEM_80S_20M.JP2"

    if _DEM_PATH.exists():
        print("Loading real terrain data …")
        from core.terrain import load_terrain
        elevation, slope, roughness, profile = load_terrain()
    else:
        print("DEM not found — using synthetic terrain (demo mode, 500×500).")
        elevation, slope, roughness, profile = _synthetic_terrain(shape=(500, 500))

    _rover_profiles = [
        dict(
            mission_type="water_ice",  power_source="rtg",
            max_slope_deg=15, min_flat_radius_m=300, priority=0.3,
        ),
        dict(
            mission_type="geological", power_source="solar",
            max_slope_deg=20, min_flat_radius_m=500, priority=0.7,
        ),
    ]

    _last_safety = _last_mission = _last_final = None
    _last_sites: list[dict] = []
    _last_rp: dict = {}

    for rp in _rover_profiles:
        sep = "=" * 72
        print(f"\n{sep}")
        print(
            f"Profile : {rp['mission_type'].upper()}  |  {rp['power_source'].upper()}"
            f"  |  max_slope={rp['max_slope_deg']}°  |  priority={rp['priority']}"
        )
        print(sep)

        safety, mission, final, sites = score_terrain(
            elevation, slope, roughness, profile, rp
        )

        # Print top-3 as a table
        hdr = (
            f"{'Rank':>4}  {'Lat':>8}  {'Lon':>9}  {'Elev(m)':>8}  "
            f"{'Slope°':>6}  {'Safe':>6}  {'Misn':>6}  {'Final':>6}"
        )
        print(f"\nTop 3 sites:\n{hdr}")
        print("-" * len(hdr))
        for s in sites[:3]:
            print(
                f"{s['rank']:>4}  {s['lat']:>8.3f}  {s['lon']:>9.3f}  "
                f"{s['elevation_m']:>8.0f}  {s['slope_deg']:>6.1f}  "
                f"{s['safety_score']:>6.3f}  {s['mission_score']:>6.3f}  "
                f"{s['final_score']:>6.3f}"
            )
            print(f"       → {s['reasoning']}")

        _last_safety, _last_mission, _last_final = safety, mission, final
        _last_sites, _last_rp = sites, rp

    # Save preview PNG using last profile's scores
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 2, figsize=(14, 12))
        panels = [
            (_last_safety,  "Safety Score"),
            (_last_mission, "Mission Score"),
            (_last_final,   "Final Score"),
            (_last_final,   "Final Score + Top 10 Sites"),
        ]
        for ax, (arr, title) in zip(axes.flat, panels):
            im = ax.imshow(
                arr, cmap="RdYlGn", vmin=0, vmax=1,
                origin="upper", interpolation="nearest",
            )
            ax.set_title(title, fontsize=11)
            plt.colorbar(im, ax=ax, fraction=0.046)

        ax4 = axes.flat[3]
        for s in _last_sites:
            ax4.plot(
                s["pixel_col"], s["pixel_row"],
                "ro", markersize=6, markeredgewidth=0.5, markeredgecolor="black",
            )
            ax4.text(
                s["pixel_col"] + 3, s["pixel_row"], str(s["rank"]),
                color="white", fontsize=7, va="center",
            )

        fig.suptitle(
            f"Landing Site Scorer Preview\n"
            f"mission={_last_rp.get('mission_type')}  |  "
            f"power={_last_rp.get('power_source')}",
            fontsize=13,
        )
        plt.tight_layout()

        _out_dir = Path(_project_root) / "outputs"
        _out_dir.mkdir(exist_ok=True)
        _out_path = _out_dir / "scorer_preview.png"
        plt.savefig(_out_path, dpi=150)
        plt.close()
        print(f"\nPreview saved → {_out_path}")

    except ImportError:
        print("\nmatplotlib not available — skipping preview image.")
