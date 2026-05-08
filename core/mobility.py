"""
core/mobility.py — Bekker-Wong wheel-soil interaction and soft terrain trafficability.

Implements a physics-based terramechanics model to estimate wheel sinkage and
rolling resistance on lunar regolith, and produces a pixel-wise soft terrain risk
map that the path planner and landing scorer use to avoid potentially immobilising
terrain.

Physical model
--------------
The Bekker (1960, 1969) pressure-sinkage relationship describes how a wheel sinks
into soil under its weight:

    p = (kc/b + kφ) · z^n                              (Bekker 1969, Eq. 7.8)

where p is contact pressure [Pa], b is wheel width [m], z is sinkage depth [m],
kc and kφ are cohesive and frictional moduli of sinkage, and n is the sinkage
exponent.  For a rolling wheel, the contact length is approximated as
l_c ≈ 2√(2rz) (valid for z << r; Wong 2008 §2.3), so the wheel equilibrium gives:

    W = b · p · l_c = b · (kc/b + kφ) · z^n · 2√(2rz)

For n = 1 (lunar regolith; Carrier et al. 1991 Table 9.28):

    z = [W / (2b√(2r) · (kc/b + kφ))]^(2/3)

Rolling resistance coefficient (Wong 2008, Eq. 2.101, simplified rigid wheel):

    μr = (2/3) · √(z / (2r))

Lunar regolith parameters
-------------------------
All parameters for "average Apollo regolith" are taken from:
    Carrier, W.D., Olhoeft, G.R., Mendell, W. (1991). Physical properties of the
    lunar surface. In: Heiken, G., Vaniman, D., French, B. (eds.) Lunar Sourcebook.
    Cambridge University Press, pp. 475-594. Table 9.28.

    kc  = 1 400 Pa   (cohesive modulus of sinkage; n=1 so SI unit is Pa)
    kφ  = 820 000 Pa/m  (frictional modulus of sinkage; n=1 → Pa/m)
    n   = 1.0        (sinkage exponent, dimensionless)

Lower-bound values from loose/disturbed regolith samples are documented in:
    Mitchell, J.K. et al. (1974). Soil mechanics. In: Apollo 17 Preliminary Science
    Report, NASA SP-330, pp. 8-1 to 8-22.

Spatial soft terrain proxy
--------------------------
At 60 m DEM resolution, direct soil-strength measurement is impossible.  A composite
soft terrain index is derived from three DEM-based proxies, following the surface-
texture methodology of Arvidson et al. (2004, Science 305, 821-824):

    depression   — depth below local mean elevation; fine-grained material accumulates
                   in topographic lows via mass-wasting (Carrier et al. 1991, Ch. 9).
    smoothness   — inverse of normalised roughness; smooth surfaces at 60 m scale
                   indicate absence of boulders, correlating with deeper fine regolith
                   (Bandfield et al. 2011, JGR Planets 116, E00H02).
    crater_density — higher density = more impact-gardened, disaggregated regolith
                   with lower packing and bearing capacity (Heiken et al. 1991, Ch. 7).

References
----------
Bekker, M.G. (1960). Off-the-Road Locomotion. University of Michigan Press.
Bekker, M.G. (1969). Introduction to Terrain-Vehicle Systems. Univ. Michigan Press.
Wong, J.Y. (2008). Theory of Ground Vehicles, 4th ed. Wiley. §2.3, §2.5, Eq. 2.101.
Mitchell, J.K. et al. (1974). Apollo 17 Prelim. Science Report, NASA SP-330, pp. 8-1–8-22.
Carrier, W.D. et al. (1991). Lunar Sourcebook. Cambridge Univ. Press. Table 9.28.
Arvidson, R.E. et al. (2004). Science 305(5685), 821-824. doi:10.1126/science.1099922.
Arvidson, R.E. et al. (2011). JGR Planets 116, E00F02. doi:10.1029/2010JE003682.
Bandfield, J.L. et al. (2011). JGR Planets 116, E00H02. doi:10.1029/2011JE003866.
Heiken, G., Vaniman, D., French, B. (eds., 1991). Lunar Sourcebook. Cambridge Univ. Press. Ch. 7.
Iagnemma, K. & Dubowsky, S. (2004). Mobile Robots in Rough Terrain. Springer STAR Vol. 12.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import uniform_filter


# ---------------------------------------------------------------------------
# Lunar regolith Bekker parameters — Carrier et al. (1991) Table 9.28
# ---------------------------------------------------------------------------

# Cohesive modulus of sinkage [Pa]; for n=1 the unit collapses to Pa.
LUNAR_KC_PA: float = 1_400.0

# Frictional modulus of sinkage [Pa/m]; for n=1.
LUNAR_KPHI_PA_M: float = 820_000.0

# Sinkage exponent (dimensionless) — 1.0 for average Apollo soil.
LUNAR_N: float = 1.0

# Mean lunar surface gravitational acceleration [m/s²].
# Source: Williams, J.G. et al. (2014) JGR Planets 119, 1546-1578.
LUNAR_G: float = 1.62

# Baseline rolling resistance coefficient for compacted nominal lunar regolith.
# Source: Carrier et al. (1991), compacted simulant rolling tests; confirmed in
#         Wong (2008) Table 2.3 for compact lunar simulant.
ROLLING_RESISTANCE_BASELINE: float = 0.015

# Sinkage fraction of wheel radius beyond which the rover risks becoming stuck.
# Source: Wong (2008) §2.5 — practical mobility limit for rocker-bogie rovers;
#         consistent with Spirit "Troy" experience (Arvidson et al. 2011).
STUCK_SINKAGE_FRACTION: float = 0.50

# Soft-index degradation fractions applied to Bekker moduli.
# At soft_index = 1.0 the effective moduli equal the lowest Apollo-measured values
# (c ≈ 0.05 kPa, lower-bound kφ per Mitchell et al. 1974).
_KC_SOFT_FRACTION: float = 0.50    # kc_eff = kc × (1 - 0.50 × soft_index)
_KPHI_SOFT_FRACTION: float = 0.60  # kφ_eff = kφ × (1 - 0.60 × soft_index)


# ---------------------------------------------------------------------------
# Per-rover sinkage (scalar)
# ---------------------------------------------------------------------------

def compute_sinkage_m(
    rover_mass_kg: float,
    wheel_width_m: float,
    wheel_radius_m: float,
    n_wheels: int = 6,
    soft_index: float = 0.0,
) -> float:
    """Return predicted wheel sinkage [m] using the Bekker-Wong model.

    Parameters
    ----------
    rover_mass_kg : float
        Total rover mass [kg].
    wheel_width_m : float
        Wheel tread width [m] (Bekker contact-patch parameter b).
    wheel_radius_m : float
        Wheel radius [m].
    n_wheels : int
        Number of weight-bearing wheels.
    soft_index : float
        Soft terrain index in [0, 1]; 0 = nominal compacted regolith,
        1 = loosest disturbed regolith (Mitchell et al. 1974 lower bound).

    Returns
    -------
    float
        Predicted sinkage z [m].
    """
    soft_index = float(np.clip(soft_index, 0.0, 1.0))
    wheel_load_n = (rover_mass_kg * LUNAR_G) / max(n_wheels, 1)

    # Effective Bekker parameters — degraded by soft terrain index.
    kc_eff   = LUNAR_KC_PA    * (1.0 - _KC_SOFT_FRACTION   * soft_index)
    kphi_eff = LUNAR_KPHI_PA_M * (1.0 - _KPHI_SOFT_FRACTION * soft_index)

    b = max(wheel_width_m, 1e-6)
    r = max(wheel_radius_m, 1e-6)

    # Bekker (1969) n=1 with rigid-wheel contact arc l_c = 2√(2rz):
    #   W = b · (kc/b + kφ) · z · 2√(2rz)
    #   W = 2b√(2r) · (kc/b + kφ) · z^(3/2)
    #   z = (W / (2b√(2r) · (kc/b + kφ)))^(2/3)
    modulus_combined = kc_eff / b + kphi_eff          # [Pa/m] for n=1
    denominator      = 2.0 * b * math.sqrt(2.0 * r) * modulus_combined
    if denominator <= 0.0:
        return 0.0
    return (wheel_load_n / denominator) ** (2.0 / 3.0)


# ---------------------------------------------------------------------------
# Rolling resistance coefficient (scalar)
# ---------------------------------------------------------------------------

def compute_rolling_resistance_coeff(
    sinkage_m: float,
    wheel_radius_m: float,
) -> float:
    """Rolling resistance coefficient from sinkage (Wong 2008, Eq. 2.101, rigid wheel).

    μr = (2/3) · √(z / (2r))

    Parameters
    ----------
    sinkage_m : float
        Wheel sinkage [m].
    wheel_radius_m : float
        Wheel radius [m].

    Returns
    -------
    float
        Dimensionless rolling resistance coefficient μr.
    """
    r = max(wheel_radius_m, 1e-6)
    z = max(sinkage_m, 0.0)
    return (2.0 / 3.0) * math.sqrt(z / (2.0 * r))


# ---------------------------------------------------------------------------
# Pixel-wise trafficability map
# ---------------------------------------------------------------------------

def compute_trafficability_map(
    elevation: np.ndarray,
    roughness: np.ndarray,
    profile: dict,
    rover_profile: dict,
    resolution_m: float = 60.0,
) -> np.ndarray:
    """Compute a pixel-wise mobility risk map (float32, [0, 1]).

    A value of 0 means no soft-terrain risk; 1 means the predicted wheel sinkage
    equals or exceeds the stuck threshold (STUCK_SINKAGE_FRACTION × wheel_radius).

    The map is derived from three DEM-level proxies (Arvidson et al. 2004 method):
      1. Topographic depression below local mean  (weight 0.50 / 0.60 without crater_density)
      2. Surface smoothness (1 − normalised roughness)  (weight 0.30 / 0.40)
      3. Crater density (impact-gardened, weaker regolith)  (weight 0.20 / 0.00)

    Parameters
    ----------
    elevation : np.ndarray
        2-D float32 elevation array [m].
    roughness : np.ndarray
        2-D float32 roughness array [m].
    profile : dict
        Terrain profile dictionary (may contain "crater_density" [0,1] float32).
    rover_profile : dict
        Must contain "rover_mass_kg", "wheel_width_m", "wheel_radius_m", "n_wheels".
    resolution_m : float
        DEM resolution [m/pixel].

    Returns
    -------
    np.ndarray
        Float32 array same shape as elevation; values in [0, 1].
    """
    rover_mass_kg  = float(rover_profile.get("rover_mass_kg",  150.0))
    wheel_width_m  = float(rover_profile.get("wheel_width_m",  0.20))
    wheel_radius_m = float(rover_profile.get("wheel_radius_m", 0.25))
    n_wheels       = int(rover_profile.get("n_wheels", 6))

    shape = elevation.shape

    # ------------------------------------------------------------------
    # Step A — Soft terrain index (composite DEM proxy)
    # ------------------------------------------------------------------

    # A1: Topographic depression below 5-pixel local mean.
    # Kernel size ≈ 5 pixels × 60 m/px = 300 m, capturing crater-floor / basin scale.
    elev_f = np.where(np.isfinite(elevation),
                      elevation.astype(np.float32), np.float32(0.0))
    local_mean_elev = uniform_filter(elev_f, size=5)
    depression      = np.maximum(np.float32(0.0), local_mean_elev - elev_f)
    del elev_f, local_mean_elev
    # Normalise: 200 m depression → index = 1.0 (polar basin depth scale).
    depression_n = np.clip(depression / np.float32(200.0),
                           np.float32(0.0), np.float32(1.0))
    del depression

    # A2: Smoothness — inverse of normalised roughness.
    # High roughness = rocky = harder/stiffer; smooth = fine-grained = softer.
    rough_f  = roughness.astype(np.float32)
    p95_r    = float(np.nanpercentile(rough_f, 95))
    p95_r    = p95_r if p95_r > 1e-6 else 1.0
    smooth_n = np.float32(1.0) - np.clip(rough_f / np.float32(p95_r),
                                         np.float32(0.0), np.float32(1.0))
    smooth_n = np.where(np.isfinite(smooth_n), smooth_n, np.float32(0.0))
    del rough_f

    # A3: Crater density proxy (Bandfield et al. 2011; Heiken et al. 1991 Ch. 7).
    crater_density = profile.get("crater_density")
    has_crater = crater_density is not None and np.any(np.isfinite(crater_density))

    if has_crater:
        crater_n = np.clip(crater_density.astype(np.float32),
                           np.float32(0.0), np.float32(1.0))
        crater_n = np.where(np.isfinite(crater_n), crater_n, np.float32(0.0))
        soft_index = (
            np.float32(0.50) * depression_n
            + np.float32(0.30) * smooth_n
            + np.float32(0.20) * crater_n
        )
        del crater_n
    else:
        soft_index = (
            np.float32(0.60) * depression_n
            + np.float32(0.40) * smooth_n
        )

    soft_index = np.clip(soft_index, np.float32(0.0), np.float32(1.0))
    del depression_n, smooth_n

    # ------------------------------------------------------------------
    # Step B — Per-rover sinkage for each soft_index pixel.
    # Vectorised version of compute_sinkage_m over the soft_index array.
    # ------------------------------------------------------------------

    b  = max(wheel_width_m,  1e-6)
    r  = max(wheel_radius_m, 1e-6)
    wheel_load_n = (rover_mass_kg * LUNAR_G) / max(n_wheels, 1)

    # kc_eff and kφ_eff as 2-D arrays.
    kc_arr   = np.float32(LUNAR_KC_PA)    * (np.float32(1.0) - np.float32(_KC_SOFT_FRACTION)   * soft_index)
    kphi_arr = np.float32(LUNAR_KPHI_PA_M) * (np.float32(1.0) - np.float32(_KPHI_SOFT_FRACTION) * soft_index)
    del soft_index

    modulus  = kc_arr / np.float32(b) + kphi_arr   # [Pa/m]
    del kc_arr, kphi_arr

    denom = np.float32(2.0 * b * math.sqrt(2.0 * r)) * modulus
    del modulus

    # z = (W / denom)^(2/3)
    safe_denom = np.where(denom > np.float32(1e-12), denom, np.float32(1e-12))
    del denom
    sinkage    = (np.float32(wheel_load_n) / safe_denom) ** np.float32(2.0 / 3.0)
    del safe_denom

    # ------------------------------------------------------------------
    # Step C — Mobility risk: sinkage relative to stuck threshold.
    # ------------------------------------------------------------------

    z_critical   = STUCK_SINKAGE_FRACTION * wheel_radius_m
    z_critical   = max(z_critical, 1e-6)
    mob_risk_map = np.clip(sinkage / np.float32(z_critical),
                           np.float32(0.0), np.float32(1.0))
    del sinkage

    # NaN elevation → unknown risk → set to 0 (conservative: let safety scorer handle NaN)
    mob_risk_map = np.where(np.isfinite(elevation), mob_risk_map, np.float32(0.0))
    return mob_risk_map.astype(np.float32)
