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
from scipy.ndimage import distance_transform_edt, maximum_filter, uniform_filter

# ---------------------------------------------------------------------------
# CRS strings  (mirror terrain.py — keeps this module self-contained)
# ---------------------------------------------------------------------------

_CRS_STERE = (
    "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
    "+R=1737400 +units=m +no_defs"
)
_CRS_LONLAT = "+proj=longlat +R=1737400 +no_defs"

# RAM: ~500 MB peak on 4 GB machines (_LAT_GRID_STRIP batching + gc.collect() after scoring)

# Crater-rim detection parameters
# _EXTREME_SLOPE_DEG=35°: anything steeper is a crater wall (ISRO landing safety threshold).
# _RIM_RADIUS_PX=8: ~480 m dilation at 60 m/px — covers typical crater-rim hazard zone.
_EXTREME_SLOPE_DEG = 35.0
_RIM_RADIUS_PX     = 8

# Latitude-grid strip size (rows processed per pyproj batch)
# 50 rows × 10133 cols × 8 bytes = ~4 MB per strip — safe on 4 GB machines.
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
    elevation        : np.ndarray,
    slope            : np.ndarray,
    roughness        : np.ndarray,
    quality_mask     : np.ndarray | None,
    max_slope_deg    : float,
    flat_radius_px   : int,
    wheel_radius_m   : float = 0.25,
    mobility_risk_map: np.ndarray | None = None,
) -> np.ndarray:
    """Return float32 (H, W) safety score in [0, 1].

    Sub-scores (all in [0, 1], higher = better):
      slope_sub    — lower slope is safer
      rough_sub    — lower roughness is safer
      qual_sub     — higher data-count mask quality is safer
      flat_sub     — larger flat neighbourhood is safer
      mob_sub      — lower Bekker-Wong sinkage risk is safer
    Penalties applied multiplicatively:
      crater-rim zone — ×0.4
    Hard zeros:
      slope > max_slope_deg  or  nan elevation → 0
    """
    ms = np.float32(max_slope_deg)
    passable = (slope <= ms) & np.isfinite(elevation)

    # ---- 1. Slope sub-score (sigmoid penalty) ---------------------------------
    # Old: linear 1 - slope/max_slope — crushed moderate slopes (10-12°) too
    # hard. Sigmoid is gentle at low slopes, sharp only near the hard limit.
    # Inflection at 75% of max_slope (15° for a 20° VIPER limit), steepness=8.
    # Rovers sustain full mobility up to ~75% of their design-limit slope;
    # significant penalty should only kick in in the final 25% of capacity.
    # Source: Creager et al. (2020) ASCE Earth and Space — lunar rover traction
    # tests show tractive efficiency > 90% up to 75% of tip-over angle.
    slope_ratio = slope.astype(np.float32) / ms
    slope_sub = np.float32(1.0) / (
        np.float32(1.0) + np.exp(np.float32(8.0) * (slope_ratio - np.float32(0.75)))
    )
    slope_sub = np.clip(slope_sub, np.float32(0.0), np.float32(1.0))
    slope_sub = np.where(np.isfinite(slope_sub), slope_sub, np.float32(0.0))

    # ---- 2. Roughness sub-score  exp(-r / r_thresh) -------------------------
    # Threshold is rover-capability-based, not DEM-relative (old: 95th pct).
    # Hazard when pixel-roughness ≥ 2× wheel radius (rock can belly the rover).
    # At 60 m pixel scale, pixel-roughness ≈ 10× wheel-scale roughness → ×20.
    # Sources: ISRO CY3 Mission Doc 2023 (Pragyan 150 mm wheel, radius 0.075 m);
    #          NASA NF-2022-08-032-JSC (VIPER 500 mm wheel, radius 0.25 m).
    # DESIGN CHOICE: the 10× pixel-to-wheel scale factor is empirical — no
    # published study directly maps 60 m DEM roughness to wheel-scale obstacle
    # height. Validated indirectly: VIPER 0.25 m wheels → r_thresh = 5 m →
    # appropriate for Nobile terrain (matches VIPER terrain criterion comment).
    r_thresh = max(wheel_radius_m * 20.0, 0.1)
    rough_sub = np.exp((-roughness.astype(np.float32)) / np.float32(r_thresh))
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

    # ---- 4. Crater-rim proximity penalty (direction-aware) -----------------
    # Rim tops (elevated above local neighbourhood) get light penalty (×0.85);
    # wall-adjacent lower sites get full penalty (×0.40).
    extreme  = (slope >= np.float32(_EXTREME_SLOPE_DEG)).astype(np.float32)
    rim_zone = maximum_filter(extreme, size=_RIM_RADIUS_PX * 2 + 1)
    del extreme
    elev_safe = np.where(np.isfinite(elevation),
                         elevation.astype(np.float32), np.float32(-1e9))
    local_elev_max = maximum_filter(elev_safe, size=_RIM_RADIUS_PX * 2 + 1)
    del elev_safe
    is_rim_top = np.isfinite(elevation) & (
        elevation.astype(np.float32) >= local_elev_max - np.float32(50.0)
    )
    del local_elev_max
    rim_penalty = np.where(
        rim_zone > 0,
        np.where(is_rim_top, np.float32(0.85), np.float32(0.40)),
        np.float32(1.0),
    )
    del rim_zone, is_rim_top

    # ---- 5a. Flat-area sub-score -------------------------------------------
    if flat_radius_px > 0:
        kernel = flat_radius_px * 2 + 1
        flat_frac = uniform_filter(passable.astype(np.float32), size=kernel)
        flat_sub  = np.clip(
            flat_frac / np.float32(0.5), np.float32(0.0), np.float32(1.0)
        )
        del flat_frac
    else:
        flat_sub = np.ones(elevation.shape, dtype=np.float32)

    # ---- 5b. Elevation prominence sub-score --------------------------------
    # Rewards sites that rise above their local neighbourhood (rim tops,
    # massifs) — a proxy for solar illumination and comm line-of-sight.
    # Memory-efficient: compute in-place, del intermediates immediately.
    kernel_p = max(flat_radius_px * 2 + 1, 3)
    elev_dev = np.where(np.isfinite(elevation), elevation.astype(np.float32),
                        np.float32(0.0))               # (H, W) work array
    local_mean_e = uniform_filter(elev_dev, size=kernel_p)
    np.subtract(elev_dev, local_mean_e, out=elev_dev)  # elev_dev = deviation
    del local_mean_e
    # Normalise: +200 m above local mean → score of 1.0
    prom_sub = np.clip(elev_dev / np.float32(200.0), np.float32(0.0), np.float32(1.0))
    del elev_dev
    prom_sub = np.where(np.isfinite(elevation), prom_sub, np.float32(0.0))

    # ---- 6. Combine --------------------------------------------------------
    # When mobility_risk_map is provided: 6-component weighted sum (sum=1.0).
    # When absent: 5-component sum with the original weights (backward-compatible,
    # avoids an unnecessary 400 MB array allocation on large DEMs).
    # Weight sources:
    #   slope  — Creager et al. (2020) ASCE Earth and Space (primary constraint).
    #   rough  — NASA VIPER terrain criterion roughness < 20 cm RMS / 1 m.
    #   qual   — LOLA data-count mask (elevation error correlation).
    #   flat   — neighbourhood flatness (post-landing area).
    #   prom   — elevation prominence (solar exposure / comms proxy).
    #   mob    — Bekker-Wong trafficability; Mitchell et al. (1974) NASA SP-330;
    #             Carrier et al. (1991) Lunar Sourcebook Table 9.28;
    #             Arvidson et al. (2004) Science 305 (MER surface texture method);
    #             Arvidson et al. (2011) JGR Planets 116 (Spirit stuck-rover event).
    if mobility_risk_map is not None:
        # ---- 5c. Mobility sub-score (Bekker-Wong trafficability) -----------
        mob_sub = np.float32(1.0) - mobility_risk_map.astype(np.float32)
        mob_sub = np.clip(mob_sub, np.float32(0.0), np.float32(1.0))
        mob_sub = np.where(np.isfinite(mob_sub), mob_sub, np.float32(1.0))
        score = (
            np.float32(0.33) * slope_sub    # was 0.35 without mob
            + np.float32(0.23) * rough_sub  # was 0.25
            + np.float32(0.18) * qual_sub   # was 0.20
            + np.float32(0.05) * flat_sub
            + np.float32(0.11) * prom_sub   # was 0.15
            + np.float32(0.10) * mob_sub    # new: sinkage trafficability
        )
        del mob_sub
    else:
        score = (
            np.float32(0.35) * slope_sub
            + np.float32(0.25) * rough_sub
            + np.float32(0.20) * qual_sub
            + np.float32(0.05) * flat_sub
            + np.float32(0.15) * prom_sub
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
    elevation    : np.ndarray,
    slope        : np.ndarray,
    roughness    : np.ndarray,
    lat_grid     : np.ndarray,
    mission_type : str,
    power_source : str,
    resolution_m : float,
    sunlight_map : np.ndarray | None = None,
    psr_intent   : str = "rim",
    psr_map      : np.ndarray | None = None,       # LPSR_75S_120M_201608.TIF
    earth_vis_map: np.ndarray | None = None,       # AVGVISIB_75S_120M_201608_EARTH.TIF
    sky_vis_map  : np.ndarray | None = None,       # SKYV_65S_240M.TIF
) -> np.ndarray:
    """Return float32 (H, W) mission-specific score in [0, 1].

    water_ice   — rewards near-polar lat and PSR-adjacent terrain.
    geological  — rewards terrain diversity, elevation transitions, accessibility.
    atmospheric — rewards high ridges and maximum sunlight exposure.

    sunlight_map : optional float32 (H, W) in [0,1] from estimate_sunlight().
                   When provided, replaces the elevation-proxy PSI.

    psr_intent : controls how PSR (Permanently Shadowed Region) pixels are scored.
        "rim"    — Land on the PSR rim: RTG gets 0.3× inside PSR, solar gets 0.1×.
                   Matches VIPER/Artemis approach (sunlit rim + short PSR sorties).
                   Source: NASA VIPER Mission Overview, NASA/TM-2022-217504.
        "enter"  — Rover enters PSR (RTG-powered ice drilling / ice sample collection).
                   No inside-PSR penalty. Matches Chang'e-7 ice-sampler concept.
                   Source: Xiao et al. (2021) Nat. Astron. doi:10.1038/s41550-020-01250-3.
        "avoid"  — Atmospheric/geology mission needing persistent sunlight.
                   Zero score inside PSR, 0.3× score within 2 km of PSR boundary.
                   Source: Lunar Illumination studies (Mazarico et al. 2011,
                   Icarus 211:1066-1081. doi:10.1016/j.icarus.2010.10.030).
    """
    nodata = ~np.isfinite(elevation)
    elev_f = _nanfill(elevation)

    # ------------------------------------------------------------------ water_ice
    if mission_type == "water_ice":
        # Reward latitudes south of -82°S, plateau at -88°S.
        # Old formula started at -88°S, giving zero credit to 84-88°S —
        # the band where LCROSS, VIPER, and all Artemis candidates actually sit.
        lat_score = np.clip(
            (np.float32(-82.0) - lat_grid) / np.float32(6.0),
            np.float32(0.0), np.float32(1.0),
        )

        # PSR proximity score: reward sites NEAR a potential PSR but elevated
        # above it. The original formula rewarded crater FLOORS (low elevation),
        # which is wrong — rovers can't operate inside permanently-shadowed
        # regions. Missions like VIPER land on rim tops to ACCESS PSRs.
        #
        # Step 1: identify PSR pixels.
        # Source: LPSR_75S_120M_201608.TIF — NASA LOLA, 1 full lunar year of
        # ray-casting simulation (Mazarico et al. 2011, J. Geophys. Res.).
        # Fallback to elevation ≤ 15th percentile proxy when real data unavailable.
        if psr_map is not None:
            psr_mask = psr_map >= np.float32(0.5)
        else:
            e15 = float(np.nanpercentile(elevation, 15))
            psr_mask = (elev_f <= np.float32(e15))

        # Step 2: distance (in pixels) to the nearest PSR edge
        dist_px = distance_transform_edt(~psr_mask).astype(np.float32)
        dist_m  = dist_px * np.float32(resolution_m)

        # Step 3: proximity score — max within 5 km of a PSR edge
        psr_proximity = np.clip(
            np.float32(1.0) - dist_m / np.float32(5000.0),
            np.float32(0.0), np.float32(1.0),
        )

        # Step 4: PSR inside-penalty according to psr_intent.
        if psr_intent == "enter":
            # RTG rover deliberately enters PSR (ice drilling, volatile sampling).
            # No penalty — mission explicitly targets PSR interior.
            # Matches Chang'e-7 Lunar Ice Explorer concept (Xiao et al. 2021).
            inside_penalty = np.ones_like(psr_proximity, dtype=np.float32)

        elif psr_intent == "avoid":
            # Atmospheric/geology rover needs persistent sunlight.
            # Zero score inside PSR; strongly penalise within 2 km of PSR edge
            # (thermal cycling and partial shadow risk near rim).
            inside_penalty = np.where(psr_mask, np.float32(0.0), np.float32(1.0))
            near_psr = (dist_m < np.float32(2000.0)) & ~psr_mask
            inside_penalty = np.where(near_psr,
                                      inside_penalty * np.float32(0.3),
                                      inside_penalty)

        else:  # "rim" — default: land on rim, short sorties inside
            # RTG: 0.3× inside (nuclear power works in shadow, but cold)
            # Solar: 0.1× inside (no recharge — rovers can only make brief sorties)
            # Based on VIPER/Artemis operational concept (NASA/TM-2022-217504).
            if power_source == "solar":
                inside_penalty = np.where(psr_mask, np.float32(0.1), np.float32(1.0))
            else:
                inside_penalty = np.where(psr_mask, np.float32(0.3), np.float32(1.0))

        psr_score = psr_proximity * inside_penalty

        # ---- PSI: solar illumination score -----------------------------------
        # Preferred: use the pre-computed sunlight_map from estimate_sunlight()
        # (latitude bands + ridge/basin bonuses from terrain.py → energy_model.py).
        # Fallback: elevation-prominence proxy when no sunlight_map is available.
        if sunlight_map is not None:
            psi_proxy = sunlight_map.astype(np.float32)
            psi_proxy = np.where(nodata, np.float32(0.0), psi_proxy)
        else:
            # Elevation proxy: sites elevated above crater-scale neighbourhood (~3 km)
            # are more likely to receive persistent sunlight. ±500 m → [0, 1].
            psi_radius_px = max(3, int(3000.0 / resolution_m))
            kern_psi = psi_radius_px * 2 + 1
            local_mean_psi = uniform_filter(elev_f, size=kern_psi)
            psi_proxy = np.clip(
                (elev_f - local_mean_psi) / np.float32(500.0) + np.float32(0.5),
                np.float32(0.0), np.float32(1.0),
            )
            psi_proxy = np.where(nodata, np.float32(0.0), psi_proxy)
            del local_mean_psi

        # Water-ice mission weights (sum = 1.0):
        #   lat        0.30 — polar latitude bonus; LCROSS and all confirmed water-ice
        #                     sites are at ≥84°S (Colaprete et al. 2010, Science).
        #   psr        0.40 — PSR proximity is the primary water-ice discriminator;
        #                     highest weight because ice only survives in permanent shadow.
        #   psi        0.30 — solar illumination for rover power; complements psr because
        #                     optimal landing is near-but-not-inside the PSR.
        score = (np.float32(0.30) * lat_score
                 + np.float32(0.40) * psr_score
                 + np.float32(0.30) * psi_proxy)

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

        # Accessibility: bell-curve centred at the DEM median latitude (σ=1.5°).
        # For the LOLA 80–90°S DEM this is ~-85°S, peaking in the Artemis 3 candidate
        # band (-85 to -88°S). Near-zero at -90°S (too rough) and -82°S (far from PSRs).
        # Using lat_grid median makes this self-adjusting if a different DEM is loaded.
        center_lat = float(np.nanmedian(lat_grid))
        access_score = np.exp(
            -(lat_grid - np.float32(center_lat)) ** 2 / np.float32(2.0 * 1.5 ** 2)
        )

        # Geological mission weights (sum = 1.0):
        #   roughness_var 0.40 — local roughness variance rewards terrain diversity
        #                        (Potts et al. 2015 show variance correlates with
        #                         exposure of sub-surface stratigraphy).
        #   elevation_grad 0.35 — gradient magnitude marks geological unit boundaries
        #                         (crater rims, lava flow edges, massif flanks).
        #   accessibility  0.25 — bell-curve around DEM center latitude; ensures sites
        #                         are reachable without extreme traverse energy.
        score = (
            np.float32(0.40) * var_norm
            + np.float32(0.35) * grad_norm
            + np.float32(0.25) * access_score
        )

    # ------------------------------------------------------------------ atmospheric
    else:
        if sky_vis_map is not None:
            # Source: SKYV_65S_240M.TIF — LRO/LOLA sky visibility (horizon obstruction
            # model). 0=fully obstructed, 1=open sky. Weight 0.6 per PROGRESS.md.
            sky_score = np.where(nodata, np.float32(0.0), sky_vis_map.astype(np.float32))
            if sunlight_map is not None:
                # Source: AVGVISIB_75S_120M_201608.TIF — solar illumination fraction.
                # Weight 0.4 per PROGRESS.md (power availability component).
                illum_score = np.where(nodata, np.float32(0.0), sunlight_map.astype(np.float32))
            else:
                e_5  = float(np.nanpercentile(elevation, 5))
                e_95 = float(np.nanpercentile(elevation, 95))
                span2 = max(e_95 - e_5, 1.0)
                illum_score = np.clip(
                    (elev_f - np.float32(e_5)) / np.float32(span2),
                    np.float32(0.0), np.float32(1.0),
                )
            score = np.float32(0.6) * sky_score + np.float32(0.4) * illum_score
        else:
            # Fallback: original elevation-based formulas (SKYV not available)
            e_med  = float(np.nanmedian(elevation))
            e_95   = float(np.nanpercentile(elevation, 95))
            e_5    = float(np.nanpercentile(elevation, 5))
            span1  = max(e_95 - e_med, 1.0)
            span2  = max(e_95 - e_5,  1.0)
            ridge_score = np.clip(
                (elev_f - np.float32(e_med)) / np.float32(span1),
                np.float32(0.0), np.float32(1.0),
            )
            sun_score = np.clip(
                (elev_f - np.float32(e_5)) / np.float32(span2),
                np.float32(0.0), np.float32(1.0),
            )
            score = np.float32(0.5) * ridge_score + np.float32(0.5) * sun_score

    # Earth visibility minor factor — all mission types.
    # Source: AVGVISIB_75S_120M_201608_EARTH.TIF (NASA LOLA 2016).
    # Weight 0.1 — distribution analysis at top-20 sites showed earth_visibility
    # ranges [0.00, 0.47] mean ~0.12, confirming secondary (non-uniform) discriminator.
    # Additive term preserves all existing mission weights unchanged.
    if earth_vis_map is not None:
        ev = np.where(nodata, np.float32(0.0), earth_vis_map.astype(np.float32))
        score = np.clip(score + np.float32(0.1) * ev, np.float32(0.0), np.float32(1.0))

    score = np.where(np.isfinite(score), score, np.float32(0.0))
    score[nodata] = np.float32(0.0)
    return score.astype(np.float32)


# ---------------------------------------------------------------------------
# Science value map builder
# ---------------------------------------------------------------------------

def build_science_map(
    elevation: np.ndarray,
    slope: np.ndarray,
    roughness: np.ndarray,
    lat_grid: np.ndarray,
    profile: dict,
    experiments: list[str],
    resolution_m: float,
    psr_map: np.ndarray | None = None,
) -> np.ndarray:
    """Build a per-pixel science value raster for the chosen experiment set.

    Returns a float32 array in [0, 1] (higher = more scientifically valuable).
    Uses real ancillary data when present in *profile*; falls back to DEM-derived
    proxies automatically when optional files are absent.

    The per-pixel **maximum** across all experiment components is taken so that the
    A* planner routes through cells excellent for *any* selected experiment rather
    than only cells mediocre for all of them.

    Experiment IDs and their primary sources
    -----------------------------------------
    volatile_detection  : Paige et al. 2010 Science 330:479–482 (Diviner 110 K threshold)
    mineralogy          : Pieters et al. 2009 Science 326:568–572 (M3 2.8 µm OH band)
    thermal_environment : Vasavada et al. 2012 JGR Planets 117:E00H18 (PSR edge gradient)
    geomorphology       : Kreslavsky & Head 2000 JGR Planets 105:26695 (roughness variance)
    regolith_mechanics  : Bandfield et al. 2011 JGR Planets 116:E00H02 (LROC crater density)
    space_weathering    : Lucey et al. 2000 JGR Planets 105:20377 (optical maturity proxy)
    """
    if not experiments:
        return np.zeros(elevation.shape, dtype=np.float32)

    elev_f  = _nanfill(elevation)
    slope_f = _nanfill(slope)
    rough_f = _nanfill(roughness)

    # Latitude grid: use cached value or a synthetic placeholder (demo / test mode)
    if lat_grid is None:
        lat_grid = np.full(elevation.shape, np.float32(-85.0), dtype=np.float32)

    # --- Shared sub-computations reused by multiple experiments ---

    # Roughness variance (used by geomorphology + space_weathering)
    def _roughness_variance() -> np.ndarray:
        r_mean    = uniform_filter(rough_f, size=20)
        r_sq_mean = uniform_filter(rough_f * rough_f, size=20)
        r_var     = np.sqrt(np.maximum(r_sq_mean - r_mean * r_mean, np.float32(0.0)))
        rv95 = float(np.nanpercentile(r_var, 95))
        rv95 = rv95 if rv95 > 1e-6 else 1.0
        return np.clip(r_var / np.float32(rv95), np.float32(0.0), np.float32(1.0))

    # PSR proximity (used by volatile_detection + thermal_environment proxy)
    # 5 km radius — VIPER sorties planned within 5 km of PSR rims (JPL D-102240, 2022)
    def _psr_proximity() -> np.ndarray:
        if psr_map is not None:
            psr_bool = (psr_map >= np.float32(0.5))
        else:
            # Elevation proxy: lowest 15th percentile treated as PSR floor
            elev_thresh = float(np.nanpercentile(elev_f, 15))
            psr_bool = (elev_f <= np.float32(elev_thresh))
        dist_px = distance_transform_edt(~psr_bool)
        dist_m  = dist_px * np.float32(resolution_m)
        # Latitude bonus poleward of -82°S (Hayne et al. 2015 Icarus 255:58–69)
        lat_bonus = np.clip(
            (np.float32(-82.0) - lat_grid) / np.float32(6.0),
            np.float32(0.0), np.float32(1.0),
        )
        prox = np.clip(np.float32(1.0) - dist_m / np.float32(5000.0),
                       np.float32(0.0), np.float32(1.0))
        return np.float32(0.6) * prox + np.float32(0.4) * lat_bonus

    # Cache lazily
    _var_norm_cache: list[np.ndarray] = []
    _psr_prox_cache: list[np.ndarray] = []

    def _get_var_norm() -> np.ndarray:
        if not _var_norm_cache:
            _var_norm_cache.append(_roughness_variance())
        return _var_norm_cache[0]

    def _get_psr_prox() -> np.ndarray:
        if not _psr_prox_cache:
            _psr_prox_cache.append(_psr_proximity())
        return _psr_prox_cache[0]

    # --- Per-experiment component computation ---
    science_map = np.zeros(elevation.shape, dtype=np.float32)

    for exp in experiments:
        component: np.ndarray | None = None

        if exp == "volatile_detection":
            # Cold terrain = high science value; Diviner 110 K ice stability threshold
            # (Paige et al. 2010 Science 330:479–482, Eq. 1)
            coltemp = profile.get("diviner_coltemp")
            if coltemp is not None:
                cold = np.where(np.isfinite(coltemp), coltemp.astype(np.float32), np.float32(1.0))
                component = np.float32(0.6) * (np.float32(1.0) - cold) + np.float32(0.4) * _get_psr_prox()
            else:
                component = _get_psr_prox()

        elif exp == "mineralogy":
            # M3 2.8 µm OH absorption band (Pieters et al. 2009 Science 326:568–572)
            m3 = profile.get("m3_oh_band")
            if m3 is not None:
                component = np.where(np.isfinite(m3), m3.astype(np.float32), np.float32(0.0))
            else:
                # Proxy: elevation gradient magnitude marks geological unit boundaries
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
                component = np.clip(grad_mag / np.float32(g95), np.float32(0.0), np.float32(1.0))
                del grad_mag

        elif exp == "thermal_environment":
            # Thermal inertia science is maximised at PSR edge where day/night ΔT≈200 K
            # (Vasavada et al. 2012 JGR Planets 117:E00H18)
            coltemp = profile.get("diviner_coltemp")
            if coltemp is not None:
                ct_f = np.where(np.isfinite(coltemp), coltemp.astype(np.float32), np.float32(0.5))
                # Thermal gradient over a 5-pixel (≈600 m) kernel captures PSR rim transition zone
                local_mean = uniform_filter(ct_f, size=5)
                component  = np.clip(
                    np.abs(ct_f - local_mean) / np.float32(0.3),
                    np.float32(0.0), np.float32(1.0),
                )
            else:
                # Proxy: bell curve peaking at PSR proximity=0.5 (edge zone)
                prox = _get_psr_prox()
                component = np.clip(prox * (np.float32(1.0) - prox) * np.float32(4.0),
                                    np.float32(0.0), np.float32(1.0))

        elif exp == "geomorphology":
            # Crater morphology & mass wasting — roughness variance at 20-pixel (1.2 km) kernel
            # (Kreslavsky & Head 2000 JGR Planets 105:26695, adapted for lunar LOLA 60 m data)
            component = _get_var_norm()

        elif exp == "regolith_mechanics":
            # Rock abundance proxy: high crater density → high ejecta blocks
            # (Bandfield et al. 2011 JGR Planets 116:E00H02)
            cd = profile.get("crater_density")
            if cd is not None:
                component = np.where(np.isfinite(cd), cd.astype(np.float32), np.float32(0.0))
            else:
                r95 = float(np.nanpercentile(rough_f, 95))
                r95 = r95 if r95 > 1e-6 else 1.0
                component = np.clip(rough_f / np.float32(r95), np.float32(0.0), np.float32(1.0))

        elif exp == "space_weathering":
            # Fresh crater proxy: high roughness variance + steep walls (angle of repose 35°)
            # (Lucey et al. 2000 JGR 105:20377; Mitchell et al. 1972 Proc. 3rd Lunar Sci. Conf.)
            slope_norm = np.clip(slope_f / np.float32(35.0), np.float32(0.0), np.float32(1.0))
            component = np.float32(0.5) * _get_var_norm() + np.float32(0.5) * slope_norm

        if component is not None:
            component = np.where(np.isfinite(component), component, np.float32(0.0))
            np.maximum(science_map, component.astype(np.float32), out=science_map)
            del component

    return science_map


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

    Blend weights rationale:
      Safety-first (default priority=0.3): 0.7/0.3 follows ISRO/NASA Go/No-Go criteria
        where terrain safety is mandatory — a scientifically interesting site that exceeds
        slope limits is simply unavailable to the rover.
      Science-first (priority≥0.5): 0.4/0.6 preserves a non-trivial safety floor so the
        planner never suggests a crater wall even in maximum-science mode.
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
    elevation        : np.ndarray,
    slope            : np.ndarray,
    roughness        : np.ndarray,
    profile          : dict,
    rover_profile    : dict,
    mobility_risk_map: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict]]:
    """Score the full terrain and select the top landing sites.

    Parameters
    ----------
    elevation, slope, roughness : np.ndarray
        Float32 arrays of shape (H, W) from terrain.load_terrain().
    profile : dict
        Terrain profile from terrain.load_terrain().
    rover_profile : dict
        mission_type    : 'water_ice' | 'geological' | 'atmospheric'
        power_source    : 'solar' | 'rtg'
        max_slope_deg   : float — rover trafficability limit
        min_flat_radius_m : float — minimum safe flat area radius
        wheel_radius_m  : float — wheel radius (m); sets roughness hazard threshold
                          (Pragyan 0.075 m, VIPER 0.25 m); default 0.25 m
        priority        : float  0=max safety, 1=max science
    mobility_risk_map : np.ndarray | None
        Float32 Bekker-Wong sinkage risk raster [0, 1] from
        core.mobility.compute_trafficability_map(); None disables mobility
        sub-score and soft terrain routing.

    Returns
    -------
    safety_score : np.ndarray  float32 (H, W)  0–1
    mission_score: np.ndarray  float32 (H, W)  0–1
    final_score  : np.ndarray  float32 (H, W)  0–1
    top_sites    : list[dict]  up to 10 best sites with full metadata
    """
    mission_type   = rover_profile["mission_type"]
    power_source   = rover_profile["power_source"]
    max_slope_deg  = float(rover_profile["max_slope_deg"])
    min_flat_r_m   = float(rover_profile["min_flat_radius_m"])
    priority       = float(rover_profile["priority"])
    psr_intent     = str(rover_profile.get("psr_intent", "rim"))
    wheel_radius_m = float(rover_profile.get("wheel_radius_m", 0.25))
    res_m          = float(profile.get("resolution_m", 60.0))

    flat_radius_px = max(1, round(min_flat_r_m / res_m))
    quality_mask   = profile.get("quality_mask")
    sunlight_map   = profile.get("sunlight_map")   # float32 (H,W) — real AVGVISIB data via estimate_sunlight()
    psr_map        = profile.get("psr_mask")        # LPSR_75S_120M_201608.TIF
    earth_vis_map  = profile.get("earth_visibility") # AVGVISIB_75S_120M_201608_EARTH.TIF
    sky_vis_map    = profile.get("sky_visibility")   # SKYV_65S_240M.TIF

    print(
        f"[scorer] mission={mission_type}  power={power_source}  "
        f"max_slope={max_slope_deg}°  priority={priority}"
    )

    # Use pre-computed lat grid if available in profile (cached by main.py at startup).
    # Falls back to computing it here for standalone use or tests.
    if "_lat_grid_cache" in profile:
        print("[scorer] Using pre-cached latitude grid.")
        lat_grid = profile["_lat_grid_cache"]
    else:
        print("[scorer] Building latitude grid …")
        lat_grid = _build_lat_grid(profile)

    print("[scorer] Computing safety score …")
    safety = _compute_safety_score(
        elevation, slope, roughness, quality_mask,
        max_slope_deg, flat_radius_px,
        wheel_radius_m=wheel_radius_m,
        mobility_risk_map=mobility_risk_map,
    )

    print("[scorer] Computing mission score …")
    mission = _compute_mission_score(
        elevation, slope, roughness, lat_grid,
        mission_type, power_source, res_m,
        sunlight_map=sunlight_map,
        psr_intent=psr_intent,
        psr_map=psr_map,
        earth_vis_map=earth_vis_map,
        sky_vis_map=sky_vis_map,
    )

    print("[scorer] Blending scores …")
    final = _blend_scores(safety, mission, priority)

    # CONSTRAINT: Solar-powered rovers cannot operate in permanently shadowed regions
    # (zero solar flux). Source: NASA VIPER Mission Design Document (2021),
    # NASA/TM-2022-217504. Binary hard constraint — not a gradient penalty.
    if power_source == "solar" and psr_map is not None:
        final[psr_map >= np.float32(0.5)] = np.float32(0.0)

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

    # Step 0 diagnostic: layer distribution at top sites
    _layer_diag = [
        ("illumination_map", sunlight_map),
        ("psr_mask",         psr_map),
        ("earth_visibility", earth_vis_map),
        ("sky_visibility",   sky_vis_map),
    ]
    if top_sites:
        print("[scorer] Ancillary layer values at top sites:")
        for _lname, _larr in _layer_diag:
            if _larr is None:
                print(f"  {_lname:22s}  NOT AVAILABLE")
                continue
            _vals = [float(_larr[s["pixel_row"], s["pixel_col"]]) for s in top_sites]
            print(f"  {_lname:22s}  n={len(_vals)}"
                  f"  min={min(_vals):.3f}  max={max(_vals):.3f}"
                  f"  mean={sum(_vals)/len(_vals):.3f}")

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
        # 240 m/px → 2534×2534 array (~24 MB each); safe for verification on any machine.
        # Production runs use the default 60 m/px via main.py.
        print("Loading real terrain data at 240 m/px (verification resolution) …")
        from core.terrain import load_terrain
        elevation, slope, roughness, profile = load_terrain(target_res_m=240.0)
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
            print(f"       -> {s['reasoning']}")

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
        print(f"\nPreview saved -> {_out_path}")

    except ImportError:
        print("\nmatplotlib not available — skipping preview image.")
