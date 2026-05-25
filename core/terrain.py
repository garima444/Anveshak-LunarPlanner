"""
core/terrain.py — DEM loading and terrain analysis for any lunar terrain region.

Supported regions (see DEM_REGIONS):
  south_pole_75_90  — LOLA 30 m/px GeoTIFF, 75–90°S  (broader south-pole context; float32)
  south_pole_80_90  — LOLA 20 m/px JP2,     80–90°S  (default, south-pole planning)
  south_pole_85_90  — LOLA 10 m/px JP2,     85–90°S  (higher detail)
  south_pole_87_90  — LOLA  5 m/px GeoTIFF, 87–90°S  (max detail, slow)
  custom:<filename> — user-uploaded GeoTIFF via /upload_dem

JP2 files carry no embedded CRS or geotransform; affine is constructed from LBL
parameters (LINE_PROJECTION_OFFSET, MAP_SCALE). GeoTIFF files have embedded affine.

Raw DN → metres: elevation_m = raw_int16 × 0.5
Nodata raw values: 0 and -32768 → set to nan.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pyproj
import rasterio
import rasterio.crs
import rasterio.transform
from affine import Affine
from rasterio.warp import reproject, Resampling
from scipy.ndimage import uniform_filter

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

# Project root — used only by DEM_REGIONS for local-file path construction.
# All runtime upload/session paths go through Config (config.py).
BASE = Path(__file__).parent.parent

# LBL-derived defaults for LOLA JP2 DEMs (numeric constants from PDS3 LBL headers).
_MAP_SCALE_M    = 20.0      # native pixel size for the 80–90°S 20 m/px DEM
_PROJ_OFFSET_PX = 15199.5   # LBL: LINE_PROJECTION_OFFSET (px from pole to image edge)
_JP2_SCALE      = 0.5       # DN → metres (LBL SCALING_FACTOR, all LOLA products)

# Raw nodata markers in LOLA JP2s (LBL: MISSING_CONSTANT)
_NODATA_RAW_A = 0
_NODATA_RAW_B = -32768

# Decode parameters derived from LRO/LOLA product documentation
_AVGVISIB_MAX   = 22396     # maximum illumination count in AVGVISIB dataset (2016-08)
_PSR_SHADOW_VAL = 20000     # LPSR pixel value meaning permanently shadowed
_EARTH_VIS_MAX  = 25000     # maximum Earth-visibility count in AVGVISIB_EARTH dataset
_SKYV_MIN_RAW   = -31399    # minimum raw DN in SKYV product (fully obstructed horizon)
_SKYV_RANGE     = 33918     # full DN range of SKYV (max − min)

# ---------------------------------------------------------------------------
# Decode functions for new NASA science products
# ---------------------------------------------------------------------------

def _decode_minirf_cpr(r: np.ndarray) -> np.ndarray:
    """Mini-RF Circular Polarisation Ratio (CPR) decode.

    LBL: SCALING_FACTOR=1.0, OFFSET=0.0, NODATA=-1.7976931E+308 (~-inf in float32).
    Physical range: CPR >= 0 (negative = nodata / artefact). Normalize to [0,1]
    by 95th percentile of valid pixels in the south-polar destination crop.
    Source: Spudis et al. 2013, JGR Planets.
    """
    r = r.copy()
    r[r < 0] = np.nan   # masks -inf nodata and any artefact negatives
    valid = r[np.isfinite(r)]
    p95 = float(np.nanpercentile(valid, 95)) if valid.size > 0 else 1.0
    return np.clip(r / max(p95, 1e-6), 0.0, 1.0).astype(np.float32)


def _decode_mas(r: np.ndarray) -> np.ndarray:
    """LOLA Median Absolute Slope (MAS) decode.

    LBL has no SCALING_FACTOR entry — JP2-native float values in degrees.
    Mask negatives (physically invalid). Normalize to [0,1] by 95th percentile.
    Source: Kreslavsky & Head 2000, JGR Planets 105:26695.
    """
    r = r.copy()
    r[r < 0] = np.nan
    valid = r[np.isfinite(r)]
    p95 = float(np.nanpercentile(valid, 95)) if valid.size > 0 else 40.0
    return np.clip(r / max(p95, 1e-6), 0.0, 1.0).astype(np.float32)


def _decode_hurst(r: np.ndarray) -> np.ndarray:
    """LOLA Hurst Exponent decode.

    No companion LBL file. Hurst exponent is dimensionless, expected ~0.5–1.0
    for lunar terrain. Use 2nd–98th percentile stretch to [0,1] robustly.
    0 = rough/anti-persistent terrain; 1 = smooth/persistent terrain.
    Source: Kreslavsky & Head 2000, JGR Planets 105:26695.
    """
    valid = r[np.isfinite(r)]
    if valid.size == 0:
        return np.zeros_like(r, dtype=np.float32)
    lo = float(np.nanpercentile(valid, 2))
    hi = float(np.nanpercentile(valid, 98))
    if hi <= lo:
        return np.zeros_like(r, dtype=np.float32)
    return np.clip(
        (r - np.float32(lo)) / np.float32(hi - lo), 0.0, 1.0
    ).astype(np.float32)


def _decode_ldsm_err(r: np.ndarray) -> np.ndarray:
    """LOLA Slope Error (LDSM_ERR) decode.

    GeoTIFF with embedded nodata. Values are slope uncertainty in degrees.
    Mask negatives (invalid). Normalize to [0,1] by 95th percentile.
    Source: NASA PGDA Barker et al. 2023.
    """
    r = r.copy()
    r[r < 0] = np.nan
    valid = r[np.isfinite(r)]
    p95 = float(np.nanpercentile(valid, 95)) if valid.size > 0 else 5.0
    return np.clip(r / max(p95, 1e-6), 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# DEM Region Registry
# ---------------------------------------------------------------------------
# All parameters sourced from PDS3 LBL files in data/dem/.
# Primary citation: Smith, D.E. et al. (2010) "The Lunar Orbiter Laser Altimeter
#   Investigation on the Lunar Reconnaissance Orbiter Mission."
#   Space Sci. Rev. 150:209-241. doi:10.1007/s11214-009-9512-y
# Data set: NASA PDS LRO-L-LOLA-4-GDR-V1.0
#
# LBL key: LINE_PROJECTION_OFFSET = distance (pixels) from image top-left to
#           pole, used to reconstruct the polar-stereographic affine transform.
# LBL key: SCALING_FACTOR = 0.5 m/DN for all three LOLA products.
# LBL key: MAP_SCALE = native ground sampling distance in m/pixel.
#
# Working resolution = factor-3 downsample of native resolution (rasterio
#   out_shape arg uses JP2 wavelet levels / GDAL overviews — no full-res alloc).
# Peak RAM estimate assumes 3 × float32 arrays (elevation, slope, roughness).

DEM_REGIONS: dict[str, dict] = {
    "south_pole_75_90": {
        "label":          "South Pole 75–90°S · 90 m/px (float32 adj.)",
        "description":    (
            "NASA LOLA 30 m/px adj. GeoTIFF, polar-stereo, covers ~75–90°S. "
            "Bounds: +-457 km from pole = 75.3 deg S. Already in metres (float32). "
            "Chandrayaan-3 (69.4 S) is outside this DEM — use the 80S product instead."
        ),
        "coverage":       "75 deg-90 deg S",
        "dem_path":       BASE / "data" / "dem" / "LDEM_75S_30MPP_ADJ.tiff",
        "count_path":     None,           # no quality-count mask for this product
        "native_res_m":   30.0,
        "working_res_m":  90.0,           # factor-3 downsample from 30 m native
        "proj_offset_px": None,           # GeoTIFF — affine read from rasterio
        "dn_scale":       1.0,            # float32 file already in metres — no DN scaling
        "is_geotiff":     True,
        "ancillary_band": "75S",          # PSR/illumination 75S files cover 75-90 S
        "size_mb":        2673,
        "peak_ram_mb":    1400,
        "load_time_s":    "120–180",
        "warn":           (
            "NOTE: 2.7 GB source file; 90 m/px working resolution. "
            "Covers 75-90 deg S only. Chandrayaan-3 (69.4 S) is outside this DEM."
        ),
        "citation":       "NASA PDS LRO-L-LOLA-4-GDR-V1.0 / LDEM_75S product",
    },
    "south_pole_80_90": {
        "label":          "South Pole 80–90°S · 100 m/px",
        "description":    (
            "NASA LOLA 20 m/px JP2, covers 80–90°S full polar cap. "
            "Best baseline for south-pole mission planning (VIPER, Artemis 3, Chang'e-7). "
            "30400×30400 native pixels downsampled to 6080×6080 at 100 m/px "
            "(factor-5 downsample; 60 m requires >3 GB RAM — use a larger instance for that)."
        ),
        "coverage":       "80°–90°S",
        "dem_path":       BASE / "data" / "dem" / "DEM_20M" / "LDEM_80S_20M.JP2",
        "count_path":     BASE / "data" / "dem" / "DEM_20M" / "LDEC_80S_20M.JP2",
        "native_res_m":   20.0,
        "working_res_m":  100.0,          # factor-5: 6080×6080 = 148 MB/array (was 60 m = 410 MB)
        "proj_offset_px": 15199.5,        # LBL: LINE_PROJECTION_OFFSET
        "dn_scale":       0.5,            # LBL: SCALING_FACTOR
        "is_geotiff":     False,
        "ancillary_band": "75S",
        "size_mb":        256,
        "peak_ram_mb":    800,
        "load_time_s":    "20–40",
        "warn":           None,
        "citation":       "NASA PDS LRO-L-LOLA-4-GDR-V1.0 / LDEM_80S_20M_JP2.LBL",
    },
    "south_pole_85_90": {
        "label":          "South Pole 85–90°S · 30 m/px (higher detail)",
        "description":    (
            "NASA LOLA 10 m/px JP2, covers 85–90°S inner polar cap. "
            "Best for Shackleton, Nobile, Haworth, de Gerlache — "
            "core Artemis 3 and VIPER candidate zones. "
            "30336×30336 native pixels downsampled to 10112×10112 at 30 m/px."
        ),
        "coverage":       "85°–90°S",
        "dem_path":       BASE / "data" / "dem" / "DEM_10m" / "LDEM_85S_10M.JP2",
        "count_path":     BASE / "data" / "dem" / "DEM_10m" / "LDEC_85S_10M.JP2",
        "native_res_m":   10.0,
        "working_res_m":  30.0,
        "proj_offset_px": 15167.5,        # LBL: LINE_PROJECTION_OFFSET
        "dn_scale":       0.5,
        "is_geotiff":     False,
        "ancillary_band": "85S",
        "size_mb":        221,
        "peak_ram_mb":    500,
        "load_time_s":    "30–60",
        "warn":           None,
        "citation":       "NASA PDS LRO-L-LOLA-4-GDR-V1.0 / LDEM_85S_10M_JP2.LBL",
    },
    "south_pole_87_90": {
        "label":          "South Pole 87–90°S · 15 m/px — max detail (slow)",
        "description":    (
            "NASA LOLA 5 m/px GeoTIFF, covers 87–90°S. "
            "Maximum resolution for Chang'e-7 (Shackleton), Nobile Rim, and "
            "Artemis-3 Connecting Ridge. Affine transform read from embedded GeoTIFF header. "
            "WARNING: 3.3 GB source file — first load takes 3–5 min and needs ~1.5 GB RAM."
        ),
        "coverage":       "87°–90°S",
        "dem_path":       BASE / "data" / "dem" / "DEM_5M" / "ldem_87s_5mpp.tif",
        "count_path":     BASE / "data" / "dem" / "DEM_5M" / "ldec_87s_5mpp.tif",
        "native_res_m":   5.0,
        "working_res_m":  15.0,
        "proj_offset_px": None,           # GeoTIFF — affine read from rasterio
        "dn_scale":       0.5,            # same LOLA DN scaling (confirmed by elevation range)
        "is_geotiff":     True,
        "ancillary_band": "85S",
        "size_mb":        3300,
        "peak_ram_mb":    1500,
        "load_time_s":    "180–300",
        "warn":           (
            "3.3 GB source DEM. First load requires ~1.5 GB RAM and 3–5 minutes. "
            "Subsequent analyses reuse the cached terrain."
        ),
        "citation":       "NASA PDS LRO-L-LOLA-4-GDR-V1.0 / ldem_87s_5mpp",
    },
}

# Moon CRS strings
_CRS_STERE = (
    "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
    "+R=1737400 +units=m +no_defs"
)
_CRS_LONLAT = "+proj=longlat +R=1737400 +no_defs"

# Module-level singleton Transformer (polar-stere → lon/lat), thread-safe
_TRANSFORMER: pyproj.Transformer | None = None

# Module-level singleton rasterio CRS (polar-stereographic), thread-safe
_MOON_CRS: rasterio.crs.CRS | None = None


# ---------------------------------------------------------------------------
# Dynamic path helpers (replaces removed _ANCILLARY_BY_BAND + file constants)
# ---------------------------------------------------------------------------

def get_bundled_path(key: str) -> Path | None:
    """Return the path to a bundled ancillary file, or None if unavailable.

    Looks up *key* in Config.BUNDLED_FILES and returns the full path only when
    the file actually exists on disk (Config.BUNDLED_DATA_DIR / filename).
    Returns None (→ graceful fallback) when:
      - key is not in BUNDLED_FILES
      - Config cannot be imported (testing without config.py)
      - file is absent from BUNDLED_DATA_DIR
    """
    try:
        from config import Config  # noqa: PLC0415
        filename = Config.BUNDLED_FILES.get(key)
        if not filename:
            return None
        p = Config.BUNDLED_DATA_DIR / filename
        return p if p.exists() else None
    except ImportError:
        return None


def _to_rasterio_path(value: Path | str) -> str | Path:
    """Convert a file_map dem value to something rasterio.open() can handle.

    HTTP(S) URLs are prefixed with '/vsicurl/' to activate GDAL's virtual HTTP
    filesystem (COG streaming). Local Path objects are returned unchanged.
    """
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return f"/vsicurl/{value}"
    return value


def stream_from_url(
    url: str,
    factor: int,
    resampling: Resampling = Resampling.average,
) -> np.ndarray | None:
    """Stream a Cloud-Optimised GeoTIFF from a NASA PGDA URL via GDAL /vsicurl/.

    Reads the DEM at (H//factor, W//factor) resolution using HTTP range requests.
    Requires GDAL compiled with libcurl — standard in conda-forge GDAL builds.

    Parameters
    ----------
    url       : full HTTPS URL to a COG DEM on NASA PGDA servers.
    factor    : downsampling factor (native→working resolution ratio).
    resampling: rasterio resampling method (default: average).

    Returns
    -------
    int16 ndarray (H//factor, W//factor), or None on any network/GDAL error.
    load_terrain_by_region() falls back to a synthetic terrain when None.
    """
    try:
        vsicurl = f"/vsicurl/{url}"
        print(f"[terrain] Streaming DEM from NASA COG: {url}")
        with rasterio.open(vsicurl) as ds:
            out_h = ds.height // factor
            out_w = ds.width  // factor
            raw = ds.read(
                1,
                out_shape=(out_h, out_w),
                resampling=resampling,
            ).astype(np.int16)
        print(f"[terrain] Streamed {raw.nbytes / 1e6:.0f} MB from NASA COG.")
        return raw
    except Exception as exc:
        print(f"[terrain] WARNING: COG streaming failed ({url}): {exc}")
        return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _make_moon_transformer() -> pyproj.Transformer:
    """Return (and lazily create) the module-level pyproj Transformer."""
    global _TRANSFORMER
    if _TRANSFORMER is None:
        _TRANSFORMER = pyproj.Transformer.from_crs(
            _CRS_STERE,
            _CRS_LONLAT,
            always_xy=True,
        )
    return _TRANSFORMER


def _get_moon_crs() -> rasterio.crs.CRS:
    """Return (and lazily create) the module-level rasterio Moon CRS."""
    global _MOON_CRS
    if _MOON_CRS is None:
        _MOON_CRS = rasterio.crs.CRS.from_proj4(_CRS_STERE)
    return _MOON_CRS


def _jp2_affine(map_scale_m: float = 20.0, proj_offset_px: float = 15199.5) -> Affine:
    """Construct rasterio Affine transform from LBL map_scale and proj_offset.

    origin_x = -proj_offset_px × map_scale_m  (left edge, westernmost)
    origin_y = +proj_offset_px × map_scale_m  (top edge,  northernmost)
    """
    origin_x = -proj_offset_px * map_scale_m
    origin_y =  proj_offset_px * map_scale_m
    return Affine(map_scale_m, 0, origin_x,
                  0, -map_scale_m, origin_y)


def _get_native_affine(
    path: Path | str,
    map_scale_m: float,
    proj_offset_px: float | None,
) -> Affine:
    """Return the native affine transform for a DEM file.

    Strategy:
    1. GeoTIFF with embedded CRS → read directly from rasterio (most accurate).
    2. LOLA JP2 (no embedded GeoJP2) → construct from PDS3 LBL parameters.

    The LOLA JP2 files do not carry GeoJP2 headers in older PDS releases, so we
    fall back to the LBL-derived proj_offset_px. The GeoTIFF (ldem_87s_5mpp.tif)
    has a proper GeoTIFF header and does not need LBL parameters.
    """
    with rasterio.open(path) as src:
        tr = src.transform
        # A valid embedded affine: non-trivial pixel size AND a CRS attached
        if src.crs is not None and 0 < abs(tr.a) < 1e8:
            return tr
    # No embedded georeference — construct from LBL parameters
    if proj_offset_px is None:
        raise ValueError(
            f"Cannot determine affine for {path.name}: no embedded CRS and "
            f"proj_offset_px is None. Check the .LBL file for LINE_PROJECTION_OFFSET."
        )
    return _jp2_affine(map_scale_m, proj_offset_px)


def _load_jp2_raw(path: Path) -> np.ndarray:
    """Read band 1 of a JP2 as int16 at full resolution. Returns (H, W) array.

    NOTE: For the 30 400×30 400 DEM this allocates ~1.74 GB.
    Prefer _load_jp2_downsampled() when a coarser resolution is acceptable.
    """
    with rasterio.open(path) as src:
        raw = src.read(1).astype(np.int16)
    return raw


def _load_jp2_downsampled(
    path: Path,
    factor: int = 3,
    resampling: Resampling = Resampling.average,
    out_dtype: type = np.int16,
) -> np.ndarray:
    """Load a JP2 file already downsampled to (H//factor, W//factor).

    Uses rasterio's read(out_shape=...) which instructs GDAL to serve the
    data at the requested resolution, exploiting JPEG2000's built-in wavelet
    decomposition levels. This is faster and uses far less memory than
    loading at full resolution then resampling in Python.

    Returns array of shape (H//factor, W//factor) cast to *out_dtype*.
    """
    with rasterio.open(path) as src:
        out_h = src.height // factor
        out_w = src.width  // factor
        arr = src.read(1, out_shape=(out_h, out_w), resampling=resampling)
    return arr.astype(out_dtype)


def _scale_dem(raw_int16: np.ndarray, dn_scale: float = _JP2_SCALE) -> np.ndarray:
    """Convert raw int16 DN → float32 elevation_m; mark nodata as NaN.

    dn_scale: LBL SCALING_FACTOR. 0.5 for all LOLA DEMs (elevation = DN × 0.5 metres
    above the 1737.4 km reference sphere). The LOLA OFFSET=1737400 is the sphere
    radius and is NOT added here — it cancels out when we compute height differences.
    """
    arr = raw_int16.astype(np.float32) * np.float32(dn_scale)
    nodata_mask = (raw_int16 == _NODATA_RAW_A) | (raw_int16 == _NODATA_RAW_B)
    arr[nodata_mask] = np.nan
    return arr


def _downsample_array(
    arr: np.ndarray,
    factor: int = 3,
    resampling: Resampling = Resampling.average,
    src_affine: Affine | None = None,
    src_crs: rasterio.crs.CRS | None = None,
) -> tuple[np.ndarray, Affine]:
    """Downsample an already-loaded 2-D array by *factor* via reproject.

    Use _load_jp2_downsampled() instead when reading from a JP2 file —
    it is faster and uses less memory by leveraging JPEG2000 resolution levels.

    Parameters
    ----------
    arr : np.ndarray
        Input 2-D array (any numeric dtype).
    factor : int
        Downsampling factor (output size ≈ input // factor).
    resampling : Resampling
        rasterio resampling algorithm.
    src_affine : Affine, optional
        Source affine (defaults to native 20 m LOLA affine).
    src_crs : CRS, optional
        Source CRS (defaults to Moon 2000 polar stereographic).

    Returns
    -------
    (downsampled_array, new_affine) : tuple
    """
    h, w = arr.shape
    new_h = h // factor
    new_w = w // factor

    if src_affine is None:
        src_affine = _jp2_affine(_MAP_SCALE_M, _PROJ_OFFSET_PX)
    if src_crs is None:
        src_crs = _get_moon_crs()

    new_affine = src_affine * Affine.scale(factor)

    dst = np.zeros((new_h, new_w), dtype=arr.dtype)
    reproject(
        source=arr,
        destination=dst,
        src_transform=src_affine,
        src_crs=src_crs,
        dst_transform=new_affine,
        dst_crs=src_crs,
        resampling=resampling,
    )
    return dst, new_affine


def _compute_slope(elevation_m: np.ndarray, resolution_m: float) -> np.ndarray:
    """Compute terrain slope in degrees from an elevation array.

    Uses float32 central differences (not np.gradient which promotes to float64,
    requiring ~1.6 GB extra RAM for a 10k×10k array on an 8 GB machine).
    NaN pixels propagate naturally via float32 arithmetic.

    Parameters
    ----------
    elevation_m : np.ndarray
        2-D float32 elevation array (metres).
    resolution_m : float
        Ground sampling distance in metres per pixel.

    Returns
    -------
    slope : np.ndarray, float32
        Slope angle in degrees, same shape as *elevation_m*.
    """
    res = np.float32(resolution_m)

    # ---- row-direction gradient (dy) in float32 ----
    dy = np.empty_like(elevation_m)               # float32, avoids float64 alloc
    dy[1:-1, :] = (elevation_m[2:, :] - elevation_m[:-2, :]) / (np.float32(2) * res)
    dy[0,  :]   = (elevation_m[1, :]  - elevation_m[0, :])  / res
    dy[-1, :]   = (elevation_m[-1, :] - elevation_m[-2, :]) / res

    # ---- col-direction gradient (dx) in float32 ----
    dx = np.empty_like(elevation_m)
    dx[:, 1:-1] = (elevation_m[:, 2:] - elevation_m[:, :-2]) / (np.float32(2) * res)
    dx[:, 0]    = (elevation_m[:, 1]  - elevation_m[:, 0])  / res
    dx[:, -1]   = (elevation_m[:, -1] - elevation_m[:, -2]) / res

    # ---- slope magnitude (in-place to minimise peak memory) ----
    np.multiply(dy, dy, out=dy)                    # dy  = dy²
    np.multiply(dx, dx, out=dx)                    # dx  = dx²
    np.add(dx, dy, out=dx)                         # dx  = dx² + dy²
    del dy
    np.sqrt(dx, out=dx)                            # dx  = |∇z|
    np.arctan(dx, out=dx)                          # dx  = atan(|∇z|)  (radians)
    np.multiply(dx, np.float32(180.0 / np.pi), out=dx)  # → degrees
    return dx


def _compute_aspect(elevation_m: np.ndarray, resolution_m: float) -> np.ndarray:
    """Compute terrain slope aspect in degrees (clockwise from north).

    Convention: 0=North, 90=East, 180=South, 270=West.
    Flat pixels (zero gradient in both directions) → NaN.
    NaN elevation pixels propagate as NaN.

    Uses the same float32 central-difference stencil as _compute_slope() to
    avoid float64 promotion and keep peak memory at ~2 × array size.
    """
    res = np.float32(resolution_m)

    # Row gradient: d(elev)/d(row) — south direction (+row = +south)
    dy = np.empty_like(elevation_m)
    dy[1:-1, :] = (elevation_m[2:, :] - elevation_m[:-2, :]) / (np.float32(2) * res)
    dy[0,  :]   = (elevation_m[1, :]  - elevation_m[0, :])  / res
    dy[-1, :]   = (elevation_m[-1, :] - elevation_m[-2, :]) / res

    # Col gradient: d(elev)/d(col) — east direction (+col = +east)
    dx = np.empty_like(elevation_m)
    dx[:, 1:-1] = (elevation_m[:, 2:] - elevation_m[:, :-2]) / (np.float32(2) * res)
    dx[:, 0]    = (elevation_m[:, 1]  - elevation_m[:, 0])  / res
    dx[:, -1]   = (elevation_m[:, -1] - elevation_m[:, -2]) / res

    # Flat mask before modifying arrays
    flat = (dx == np.float32(0.0)) & (dy == np.float32(0.0))

    # north_grad = −dy (flip: +row is south, −row is north)
    np.negative(dy, out=dy)

    # aspect = atan2(east_grad, north_grad) → CW from north in radians
    aspect = np.empty_like(elevation_m)
    np.arctan2(dx, dy, out=aspect)
    del dx, dy

    # Radians → degrees, normalize to [0, 360)
    np.multiply(aspect, np.float32(180.0 / np.pi), out=aspect)
    aspect[aspect < np.float32(0.0)] += np.float32(360.0)

    # Undefined pixels
    aspect[flat] = np.nan
    aspect[~np.isfinite(elevation_m)] = np.nan

    return aspect


def _compute_roughness(elevation_m: np.ndarray) -> np.ndarray:
    """Compute terrain roughness as local std-dev of elevation (metres).

    Uses the fast variance trick with scipy.ndimage.uniform_filter:
        std ≈ sqrt(E[x²] - E[x]²)
    Applied in a 3×3 neighbourhood, in float32 (avoids ~1.6 GB float64 overhead).

    **NaN handling**: scipy's uniform_filter uses a cumulative-sum algorithm that
    propagates NaN to ALL subsequent elements in each row/column. With even 2%
    scattered NaN, this makes the output ~99% NaN. To prevent this, NaN pixels
    are filled with the global mean before filtering, then re-masked afterward.
    The 1-pixel border around each NaN region gets slightly wrong roughness
    (mean contamination), which is acceptable for quality-masking purposes.

    Parameters
    ----------
    elevation_m : np.ndarray
        2-D float32 elevation array (metres).

    Returns
    -------
    roughness : np.ndarray, float32
        Local std-dev in metres, same shape as *elevation_m*.
        NaN wherever elevation_m is NaN.
    """
    nodata = ~np.isfinite(elevation_m)

    # Fill NaN with global mean so uniform_filter's cumsum sees no NaN
    fill_val = np.float32(np.nanmean(elevation_m))
    filled = np.where(nodata, fill_val, elevation_m)  # float32

    # E[x] and E[x²] over filled array (no NaN → no cumsum cascade)
    mean    = uniform_filter(filled, size=3)            # float32
    elev_sq = filled * filled                           # float32, temporary
    sq_mean = uniform_filter(elev_sq, size=3)
    del elev_sq, filled

    # Variance = E[x²] − E[x]² ; clamp negatives (float32 rounding artefacts)
    np.multiply(mean, mean, out=mean)                   # mean = mean² in-place
    variance = np.maximum(sq_mean - mean, np.float32(0.0))
    del sq_mean, mean

    roughness = np.sqrt(variance)
    roughness[nodata] = np.nan                          # restore nodata mask
    return roughness


# ---------------------------------------------------------------------------
# Ancillary layer loader
# ---------------------------------------------------------------------------

def _load_ancillary(
    path: Path,
    target_profile: dict,
    decode_fn: Callable[[np.ndarray], np.ndarray],
    resample: Resampling = Resampling.bilinear,
) -> np.ndarray | None:
    """Load, decode, and reproject an ancillary raster to match the DEM grid.

    Handles any input projection (polar-stereo, geographic GCS_Moon, etc.) by
    reading the source CRS from the file header. Falls back to lunar polar-stereo
    if no CRS is embedded.

    Returns float32 array shape (H, W) matching target_profile, NaN=nodata.
    Returns None (with warning) if the file is missing or unreadable.
    """
    try:
        with rasterio.open(path) as ds:
            raw = ds.read(1)
            src_transform = ds.transform
            # Use the file's own CRS (e.g. GCS_Moon geographic or polar-stereo);
            # fall back to lunar polar-stereo only when the file has none.
            src_crs = ds.crs if ds.crs is not None else _get_moon_crs()
            nodata_val = ds.nodata if ds.nodata is not None else _NODATA_RAW_B

        h = target_profile["height"]
        w = target_profile["width"]

        raw = raw.astype(np.float32)
        raw[raw == nodata_val] = np.nan

        decoded = decode_fn(raw)
        del raw

        dst = np.full((h, w), np.nan, dtype=np.float32)
        reproject(
            source=decoded,
            destination=dst,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=target_profile["transform"],
            dst_crs=_get_moon_crs(),
            resampling=resample,
            src_nodata=np.nan,
            dst_nodata=np.nan,
        )
        return dst
    except Exception as _exc:
        print(f"[terrain] WARNING: ancillary file skipped ({path.name}): {_exc}")
        return None


def _load_ancillary_streaming(
    path: Path,
    target_profile: dict,
    decode_fn: Callable[[np.ndarray], np.ndarray],
    resample: Resampling = Resampling.bilinear,
    nodata_sentinel: float | None = None,
) -> np.ndarray | None:
    """Like _load_ancillary but uses rasterio.band() streaming for large global files.

    The standard _load_ancillary reads the full source band into memory before
    reprojecting — unsuitable for files > ~1 GB (e.g. Mini-RF 128ppd, ~4.2 GB).
    This variant passes rasterio.band() as the source so GDAL reads on demand,
    materialising only the south-polar destination crop (~10133×10133 float32).

    decode_fn is applied AFTER reprojection (on the south-pole crop only).
    src_nodata comes from the file header; override with nodata_sentinel if needed.
    Returns float32 array shape (H, W) matching target_profile, NaN=nodata.
    Returns None (with warning) if the file is missing or unreadable.
    """
    try:
        with rasterio.open(path) as ds:
            src_crs  = ds.crs if ds.crs is not None else _get_moon_crs()
            nodata_v = nodata_sentinel if nodata_sentinel is not None else ds.nodata
            h = target_profile["height"]
            w = target_profile["width"]
            dst = np.full((h, w), np.nan, dtype=np.float32)
            reproject(
                source        = rasterio.band(ds, 1),
                destination   = dst,
                src_transform = ds.transform,
                src_crs       = src_crs,
                dst_transform = target_profile["transform"],
                dst_crs       = _get_moon_crs(),
                resampling    = resample,
                src_nodata    = nodata_v,
                dst_nodata    = np.nan,
            )
        return decode_fn(dst)
    except Exception as _exc:
        print(f"[terrain] WARNING: ancillary file skipped ({path.name}): {_exc}")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_terrain(
    file_map: dict,
    target_res_m: int = 60,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Load a LOLA DEM and compute slope, roughness, and ancillary layers.

    Parameters
    ----------
    file_map : dict
        Mapping of layer keys to file paths or URLs.  Required key:
            "dem"            : Path | str — local path or HTTPS URL (COG streaming).
        Optional keys (Path | None — None → graceful fallback / zeros):
            "count"          : data-count quality mask JP2
            "illumination"   : solar illumination fraction (AVGVISIB)
            "psr"            : permanently shadowed region mask (LPSR)
            "earth_visibility": Earth-visibility fraction (AVGVISIB_EARTH)
            "sky_visibility" : sky-visibility fraction (SKYV)
            "minirf_cpr"     : Mini-RF circular polarisation ratio
            "mas_57m"        : Median Absolute Slope 57 m baseline
            "mas_225m"       : Median Absolute Slope 225 m baseline
            "mas_560m"       : Median Absolute Slope 560 m baseline
            "hurst_exponent" : LOLA Hurst exponent
            "ldsm_err"       : LOLA slope error
        Metadata keys (used when loading JP2 files without embedded affine):
            "_map_scale_m"   : native pixel size m/px (default 20 m)
            "_proj_offset_px": LBL LINE_PROJECTION_OFFSET (default 15199.5)
            "_dn_scale"      : DN → metres scale factor (default 0.5)
    target_res_m : int
        Output resolution in metres. Must be integer multiple of native.

    Returns
    -------
    elevation : float32 (H, W) metres above 1737.4 km sphere; NaN = nodata.
    slope     : float32 (H, W) degrees.
    roughness : float32 (H, W) local std-dev in metres (3×3 window).
    profile   : dict  — crs, transform, height, width, dtype, nodata, resolution_m,
                quality_mask (optional), ancillary arrays, sunlight_map (float32).

    Memory budget (80-90°S DEM at 60 m/px)
    ----------------------------------------
    Downsampled int16 (factor 3) : ~193 MB  (JP2 wavelet decode, no full-res alloc)
    Scaled float32 elevation     : ~410 MB
    Slope + roughness float32    : ~820 MB
    Peak during roughness        : ~1.23 GB total
    """
    dem_value = file_map.get("dem")
    if dem_value is None:
        raise ValueError("file_map must contain 'dem' key with a valid path or URL.")

    count_value = file_map.get("count")

    map_scale   = file_map.get("_map_scale_m") or _MAP_SCALE_M
    dn_scale    = file_map.get("_dn_scale")    or _JP2_SCALE
    proj_offset = file_map.get("_proj_offset_px")   # None → read from GeoTIFF header

    is_url        = isinstance(dem_value, str) and dem_value.startswith(("http://", "https://"))
    dem_rasterio  = _to_rasterio_path(dem_value)     # adds /vsicurl/ prefix if URL

    moon_crs      = _get_moon_crs()
    affine_native = _get_native_affine(dem_rasterio, map_scale, proj_offset)
    factor        = round(target_res_m / map_scale)
    new_affine    = affine_native * Affine.scale(factor)

    # ------------------------------------------------------------------
    # 1. Load DEM at target resolution.
    # Local JP2/GeoTIFF: rasterio read(out_shape=...) exploits JPEG2000 wavelet
    #   levels — never allocates the full-resolution array.
    # URL (COG streaming): GDAL /vsicurl/ fetches only needed HTTP ranges.
    # Peak memory: ~193 MB (int16) → ~410 MB (float32 elevation).
    # ------------------------------------------------------------------
    print(
        f"Loading DEM at {target_res_m:.0f} m/px "
        f"(factor-{factor} downsample) …"
    )
    if is_url:
        raw_ds = stream_from_url(str(dem_value), factor=factor, resampling=Resampling.average)
        if raw_ds is None:
            # COG streaming is an optional enhancement — guide the user to upload manually.
            download_url = file_map.get("_dem_download_url", str(dem_value))
            raise RuntimeError(
                "Cannot stream from NASA directly. "
                "Please download and upload the file manually. "
                f"Download: {download_url}"
            )
    else:
        raw_ds = _load_jp2_downsampled(
            dem_rasterio, factor=factor, resampling=Resampling.average, out_dtype=np.int16,
        )

    # ------------------------------------------------------------------
    # 2. Scale DN → metres; mask nodata as NaN.
    # All LOLA DEMs use SCALING_FACTOR=0.5; file_map["_dn_scale"] overrides.
    # ------------------------------------------------------------------
    elevation = _scale_dem(raw_ds, dn_scale=dn_scale)
    del raw_ds                                                # free ~193 MB

    h, w = elevation.shape

    # ------------------------------------------------------------------
    # 3. Slope and roughness
    # ------------------------------------------------------------------
    print("Computing slope …")
    slope = _compute_slope(elevation, target_res_m)

    print("Computing roughness …")
    roughness = _compute_roughness(elevation)

    print("Computing aspect …")
    aspect = _compute_aspect(elevation, target_res_m)

    # ------------------------------------------------------------------
    # 4. Load data-count quality mask (optional)
    # ------------------------------------------------------------------
    quality_mask: np.ndarray | None = None
    if count_value is not None:
        _count_path = Path(count_value) if isinstance(count_value, (str, Path)) else None
        if _count_path is not None and _count_path.exists():
            print(f"Loading count mask: {_count_path} …")
            raw_count = _load_jp2_downsampled(
                _count_path, factor=factor, resampling=Resampling.average, out_dtype=np.int16,
            )
            quality_mask = raw_count.astype(np.float32)
            del raw_count

    # ------------------------------------------------------------------
    # 6. Build profile
    # ------------------------------------------------------------------
    profile: dict = {
        "crs":          moon_crs,
        "transform":    new_affine,
        "height":       h,
        "width":        w,
        "dtype":        "float32",
        "nodata":       np.nan,
        "resolution_m": target_res_m,
    }
    if quality_mask is not None:
        profile["quality_mask"] = quality_mask
    profile["aspect"] = aspect

    # Ancillary NASA layers — loaded in parallel (rasterio + reproject are thread-safe).
    # Paths come from file_map (session uploads, bundled files, or absent → graceful fallback).
    print("Loading ancillary layers …")
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    def _resolve_ancillary(key: str) -> Path | None:
        """Get a resolved Path for an ancillary key, or None if unavailable."""
        v = file_map.get(key)
        if v is not None:
            p = Path(v)
            return p if p.exists() else None
        # Fall back to bundled file
        return get_bundled_path(key)

    _ancillary_specs: list[tuple] = []

    # Core ancillaries — skip when path resolves to None (no fallback needed in scorer)
    _illum = _resolve_ancillary("illumination")
    if _illum:
        _ancillary_specs.append((
            "illumination_map", _illum,
            lambda r: np.clip(r / np.float32(_AVGVISIB_MAX), 0.0, 1.0), Resampling.bilinear,
        ))
    _psr = _resolve_ancillary("psr")
    if _psr:
        _ancillary_specs.append((
            "psr_mask", _psr,
            lambda r: (r == np.float32(_PSR_SHADOW_VAL)).astype(np.float32), Resampling.nearest,
        ))
    _ev = _resolve_ancillary("earth_visibility")
    if _ev:
        _ancillary_specs.append((
            "earth_visibility", _ev,
            lambda r: np.clip(r / np.float32(_EARTH_VIS_MAX), 0.0, 1.0), Resampling.bilinear,
        ))
    _sv = _resolve_ancillary("sky_visibility")
    if _sv:
        _ancillary_specs.append((
            "sky_visibility", _sv,
            lambda r: np.clip(
                (r - np.float32(_SKYV_MIN_RAW)) / np.float32(_SKYV_RANGE), 0.0, 1.0
            ),
            Resampling.bilinear,
        ))

    # Legacy optional science layers — look in bundled dir; skip when absent.
    # Diviner: uint8 RGB display image (0=cold, 255=hot); band-1 as relative cold proxy.
    _div = get_bundled_path("diviner_coltemp")
    if _div:
        _ancillary_specs.append((
            "diviner_coltemp", _div,
            lambda r: np.clip(r.astype(np.float32) / np.float32(255.0), 0.0, 1.0),
            Resampling.bilinear,
        ))
    # M3 OH-band: near-zero south-pole coverage; proxy preferred (see landing_scorer).
    _m3 = get_bundled_path("m3_oh_band")
    if _m3:
        _ancillary_specs.append((
            "m3_oh_band", _m3,
            lambda r: (np.clip(r / float(np.nanmax(r)), 0.0, 1.0)
                       if np.nanmax(r) > 0 else np.zeros_like(r, dtype=np.float32)),
            Resampling.bilinear,
        ))
    # LROC crater density: uint8 0–255 → [0,1]
    _cd = get_bundled_path("crater_density")
    if _cd:
        _ancillary_specs.append((
            "crater_density", _cd,
            lambda r: np.clip(r.astype(np.float32) / np.float32(255.0), 0.0, 1.0),
            Resampling.nearest,
        ))

    # New NASA science products (May 2026). MAS + HE use _load_ancillary (≤50 MB JP2).
    for _key, _decode_fn in [
        ("mas_57m",        _decode_mas),
        ("mas_225m",       _decode_mas),
        ("mas_560m",       _decode_mas),
        ("hurst_exponent", _decode_hurst),
        ("ldsm_err",       _decode_ldsm_err),
    ]:
        _p = _resolve_ancillary(_key)
        if _p:
            _ancillary_specs.append((_key, _p, _decode_fn, Resampling.bilinear))

    # Mini-RF CPR: ~4.2 GB global file — uses streaming loader.
    _streaming_specs: list[tuple] = []
    _minirf = _resolve_ancillary("minirf_cpr")
    if _minirf:
        _streaming_specs.append(("minirf_cpr", _minirf, _decode_minirf_cpr, Resampling.bilinear))

    with ThreadPoolExecutor(max_workers=13) as _pool:
        _futures = {
            key: _pool.submit(_load_ancillary, path, profile, fn, rs)
            for key, path, fn, rs in _ancillary_specs
        }
        _stream_futures = {
            key: _pool.submit(_load_ancillary_streaming, path, profile, fn, rs)
            for key, path, fn, rs in _streaming_specs
        }
    for key, future in _futures.items():
        profile[key] = future.result()
    for key, future in _stream_futures.items():
        profile[key] = future.result()

    # Zeros fallback for new science layers: downstream code expects arrays, not None.
    _H, _W = profile["height"], profile["width"]
    for _key in ("minirf_cpr", "mas_57m", "mas_225m", "mas_560m",
                 "hurst_exponent", "ldsm_err"):
        if profile.get(_key) is None:
            profile[_key] = np.zeros((_H, _W), dtype=np.float32)

    # Derived products from MAS ratio (Kreslavsky & Head 2000 JGR Planets 105:26695).
    # freshness_index = MAS_57m / MAS_225m  — high = fine-scale roughness dominates
    #   (fresh crater ejecta or recently disrupted terrain).
    _m57  = profile["mas_57m"]
    _m225 = profile["mas_225m"]
    _denom = np.where(
        np.isfinite(_m225) & (_m225 > 0), _m225, np.float32(1e-6)
    )
    profile["freshness_index"] = np.clip(
        _m57 / _denom, np.float32(0.0), np.float32(1.0)
    ).astype(np.float32)
    # roughness_spectral_slope = (MAS_225 - MAS_57) / ln(225/57)
    #   — positive = roughness increases with scale (normal); near-zero = scale-invariant.
    profile["roughness_spectral_slope"] = np.clip(
        (_m225 - _m57 + np.float32(1e-6)) / np.float32(np.log(225.0 / 57.0)),
        np.float32(0.0), np.float32(1.0),
    ).astype(np.float32)
    del _m57, _m225, _denom

    # sunlight_map: alias illumination_map directly when available (no copy — saves ~400 MB).
    # Fallback to estimate_sunlight() synthetic model when ancillaries are absent.
    _illum = profile.get("illumination_map")
    if _illum is not None:
        profile["sunlight_map"] = _illum
    else:
        from core.energy_model import estimate_sunlight  # noqa: PLC0415
        profile["sunlight_map"] = estimate_sunlight(elevation, profile)

    print(
        f"Done. Elevation shape: {elevation.shape}, "
        f"resolution: {target_res_m:.0f} m/px"
    )
    return elevation, slope, roughness, profile


def load_terrain_by_region(
    region_key: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Load terrain for a named region from the DEM_REGIONS registry.

    Builds a file_map from:
      1. DEM local path (from DEM_REGIONS)  → falls back to NASA COG URL if absent.
      2. Bundled ancillary files (from Config.BUNDLED_FILES).
      3. Session-uploaded files (not handled here — injected via file_map by caller).

    Parameters
    ----------
    region_key : str
        One of the keys in DEM_REGIONS (e.g. 'south_pole_80_90').
        'custom:<filename>' → routed to load_terrain_uploaded().

    Raises
    ------
    KeyError          : unknown region key.
    FileNotFoundError : DEM missing and no NASA URL configured.
    RuntimeError      : COG streaming failed.
    """
    if region_key.startswith("custom:"):
        filename = region_key[len("custom:"):]
        try:
            from config import Config  # noqa: PLC0415
            upload_dir = Config.UPLOAD_DIR
        except ImportError:
            upload_dir = Path(__file__).parent.parent / "data" / "uploaded"
        return load_terrain_uploaded(upload_dir / filename)

    if region_key not in DEM_REGIONS:
        raise KeyError(
            f"Unknown DEM region {region_key!r}. "
            f"Valid keys: {list(DEM_REGIONS)}. "
            f"For uploaded files use 'custom:<filename>'."
        )

    reg = DEM_REGIONS[region_key]

    if reg.get("warn"):
        print(f"[terrain] WARNING: {reg['warn']}")

    # Build file_map — metadata keys first, then DEM path / URL, then ancillaries.
    file_map: dict = {
        "_map_scale_m":    reg["native_res_m"],
        "_proj_offset_px": reg["proj_offset_px"],   # None for GeoTIFFs → reads from header
        "_dn_scale":       reg["dn_scale"],
    }

    # DEM: prefer local / uploaded file.
    # COG streaming from NASA is an *optional* enhancement — attempted only when
    # the file is absent and GDAL libcurl is available.  If streaming fails the
    # caller receives a user-friendly error with the manual download URL.
    dem_p = reg["dem_path"]
    if dem_p.exists():
        file_map["dem"] = dem_p
    else:
        try:
            from config import Config  # noqa: PLC0415
            url_info = Config.NASA_DEM_URLS.get(region_key)
        except ImportError:
            url_info = None

        if url_info:
            download_url = url_info["url"]
            print(
                f"[terrain] DEM not on disk ({dem_p.name}); "
                f"attempting optional COG stream from NASA: {download_url}"
            )
            file_map["dem"] = download_url
            # Saved so load_terrain() can embed it in the user-facing error message
            # if /vsicurl/ streaming fails (no libcurl, firewall, etc.).
            file_map["_dem_download_url"] = download_url
        else:
            # No local file and no known NASA URL — tell user exactly where to get it.
            citation = reg.get("citation", "LRO-L-LOLA-4-GDR-V1.0")
            raise FileNotFoundError(
                f"DEM file not found: {dem_p.name}. "
                f"Please download it from NASA PDS (dataset {citation}) "
                f"and upload it via /setup → 'Upload DEM'."
            )

    # Count mask (optional — None for regions that don't have one)
    cnt_p = reg.get("count_path")
    if cnt_p is not None and cnt_p.exists():
        file_map["count"] = cnt_p

    # Bundled ancillaries — get_bundled_path() returns None when file absent → graceful skip
    for _key in ("illumination", "psr", "earth_visibility", "sky_visibility",
                 "mas_57m", "mas_225m", "mas_560m", "hurst_exponent"):
        _p = get_bundled_path(_key)
        if _p:
            file_map[_key] = _p

    print(f"[terrain] Loading region '{region_key}': {reg['label']}")
    return load_terrain(file_map, target_res_m=round(reg["working_res_m"]))


def load_terrain_uploaded(
    file_path: Path | str,
    target_res_m: float = 60.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Load a user-uploaded GeoTIFF/ENVI/HGT DEM and derive slope + roughness.

    Accepted formats: GeoTIFF (.tif/.tiff), JPEG2000 (.jp2), ENVI .img, SRTM .hgt.
    The file must be georeferenced (CRS + affine transform embedded).

    Known problems with large uploads
    ----------------------------------
    1. Memory: rasterio reads GeoTIFF without wavelet levels, so the full file may be
       loaded before downsampling. A 1° × 1° area at 5 m/px ≈ 40000×40000 = 6.4 GB.
       Hard cap: reject if estimated working set > 3 GB.
    2. CRS mismatch: non-Moon DEMs (Earth SRTM etc.) will produce wrong lat/lon labels.
       A warning is printed but loading proceeds; the user is responsible.
    3. DN scaling: integer-stored DEMs are assumed to use 0.5 m/DN (LOLA convention).
       Float-stored DEMs are assumed to already be in metres. Both are handled.
    4. Upload timeout: FastAPI streams files in chunks; a 500 MB upload on a slow link
       takes ~50 s. The /upload_dem endpoint applies a 500 MB hard limit.
    5. Nodata: uses rasterio src.nodata if set; also masks raw values 0 and -32768
       (universal LOLA nodata convention).

    Parameters
    ----------
    file_path    : path to the uploaded DEM file.
    target_res_m : desired working resolution in metres. The file is downsampled
                   to this resolution. Must be >= native resolution.
    """
    import uuid as _uuid  # local import — only needed for custom uploads

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Uploaded DEM not found: {file_path}")

    print(f"[terrain] Loading custom DEM: {file_path.name}")

    with rasterio.open(file_path) as src:
        if src.count < 1:
            raise ValueError("DEM must have at least one band.")

        native_crs = src.crs
        if native_crs is None:
            raise ValueError(
                "Uploaded DEM has no embedded CRS. "
                "Georeference the file first (QGIS → Raster → Assign Projection)."
            )

        affine_native = src.transform
        native_res_m  = abs(affine_native.a)
        if native_res_m <= 0 or native_res_m > 1e7:
            raise ValueError(
                f"Pixel size {native_res_m} m is implausible. "
                f"Verify the file is in metres (polar-stereographic or geographic)."
            )

        # Warn if likely not a Moon DEM
        crs_str = str(native_crs).lower()
        if "1737" not in crs_str and "moon" not in crs_str and "luna" not in crs_str:
            print(
                f"[terrain] WARNING: CRS does not mention Moon/1737.4 km radius: "
                f"{native_crs}. Lat/lon labels will be wrong for Earth DEMs."
            )

        factor  = max(1, round(target_res_m / native_res_m))
        out_h   = src.height // factor
        out_w   = src.width  // factor
        est_ram = out_h * out_w * 4 * 3 / (1024 ** 2)   # 3 float32 arrays in MB

        if est_ram > 3000:
            raise ValueError(
                f"Working set after downsampling would be {est_ram:.0f} MB "
                f"({out_h}×{out_w} pixels × 3 float32 arrays). "
                f"Crop the DEM to a smaller region or use a coarser resolution. "
                f"Recommended max area at {target_res_m:.0f} m/px: "
                f"~{int((3000/(target_res_m**2/1e6))**0.5):.0f} km²."
            )

        print(
            f"[terrain] Custom DEM: {src.height}×{src.width} px @ {native_res_m:.1f} m/px"
            f" → {out_h}×{out_w} @ {target_res_m:.0f} m/px (factor={factor}). "
            f"Peak RAM ~{est_ram:.0f} MB."
        )

        arr      = src.read(1, out_shape=(out_h, out_w), resampling=Resampling.average)
        nodata_v = src.nodata
        raw_dtype = arr.dtype

    # Scale to metres
    if np.issubdtype(raw_dtype, np.floating):
        elevation = arr.astype(np.float32)
        if nodata_v is not None:
            elevation[np.abs(arr - nodata_v) < 1e-3] = np.nan
    else:
        # Integer DN — apply LOLA 0.5 scale (safest assumption for lunar DEMs)
        elevation   = arr.astype(np.float32) * np.float32(0.5)
        nodata_mask = (arr == _NODATA_RAW_A) | (arr == _NODATA_RAW_B)
        if nodata_v is not None:
            nodata_mask |= (arr == int(nodata_v))
        elevation[nodata_mask] = np.nan

    del arr

    new_affine = affine_native * Affine.scale(factor)
    h, w       = elevation.shape

    print("[terrain] Computing slope …")
    slope     = _compute_slope(elevation, target_res_m)
    print("[terrain] Computing roughness …")
    roughness = _compute_roughness(elevation)
    print("[terrain] Computing aspect …")
    aspect    = _compute_aspect(elevation, target_res_m)

    profile: dict = {
        "crs":          native_crs,
        "transform":    new_affine,
        "height":       h,
        "width":        w,
        "dtype":        "float32",
        "nodata":       np.nan,
        "resolution_m": target_res_m,
        "dem_source":   file_path.name,
        "aspect":       aspect,
    }

    from core.energy_model import estimate_sunlight  # noqa: PLC0415
    profile["sunlight_map"] = estimate_sunlight(elevation, profile)

    print(f"[terrain] Custom DEM loaded: {h}×{w} px at {target_res_m:.0f} m/px")
    return elevation, slope, roughness, profile


def get_dem_region_info(region_key: str | None = None) -> dict:
    """Return metadata dict for one or all DEM regions (for the /dem_regions endpoint)."""
    if region_key is not None:
        reg = DEM_REGIONS.get(region_key)
        if reg is None:
            return {}
        return {
            "key":           region_key,
            "label":         reg["label"],
            "description":   reg["description"],
            "coverage":      reg["coverage"],
            "working_res_m": reg["working_res_m"],
            "peak_ram_mb":   reg["peak_ram_mb"],
            "load_time_s":   reg["load_time_s"],
            "warn":          reg["warn"],
            "citation":      reg["citation"],
            "available":     reg["dem_path"].exists(),
        }
    return {
        k: get_dem_region_info(k) for k in DEM_REGIONS
    }


def pixel_to_latlon(
    row: int | float,
    col: int | float,
    profile: dict,
) -> tuple[float, float]:
    """Convert pixel coordinates to geographic (longitude, latitude) in degrees.

    Parameters
    ----------
    row, col : float
        Pixel coordinates (0-indexed; row = y axis, col = x axis).
    profile : dict
        Terrain profile from load_terrain().

    Returns
    -------
    (lon_deg, lat_deg) : tuple[float, float]
    """
    t = _make_moon_transformer()
    x, y = rasterio.transform.xy(profile["transform"], row, col)
    lon, lat = t.transform(x, y)
    return lon, lat


def latlon_to_pixel(
    lon_deg: float,
    lat_deg: float,
    profile: dict,
) -> tuple[int, int]:
    """Convert geographic coordinates to nearest pixel (row, col).

    Parameters
    ----------
    lon_deg, lat_deg : float
        Geographic coordinates in decimal degrees.
    profile : dict
        Terrain profile from load_terrain().

    Returns
    -------
    (row, col) : tuple[int, int]
    """
    t = _make_moon_transformer()
    x, y = t.transform(lon_deg, lat_deg, direction="INVERSE")
    col_f, row_f = ~profile["transform"] * (x, y)
    return int(round(row_f)), int(round(col_f))


def _latlon_to_pixel_float(
    lon_deg: float,
    lat_deg: float,
    profile: dict,
) -> tuple[float, float]:
    """Like latlon_to_pixel but returns unrounded (row_f, col_f) floats."""
    t = _make_moon_transformer()
    x, y = t.transform(lon_deg, lat_deg, direction="INVERSE")
    col_f, row_f = ~profile["transform"] * (x, y)
    return row_f, col_f


def get_elevation_at(
    elevation: np.ndarray,
    profile: dict,
    lon_deg: float,
    lat_deg: float,
) -> float:
    """Return bilinearly interpolated elevation at a geographic coordinate.

    Parameters
    ----------
    elevation : np.ndarray
        2-D float32 elevation array from load_terrain().
    profile : dict
        Terrain profile from load_terrain().
    lon_deg, lat_deg : float
        Geographic coordinates in decimal degrees.

    Returns
    -------
    float
        Interpolated elevation in metres, or nan if out-of-bounds or nodata.
    """
    row_f, col_f = _latlon_to_pixel_float(lon_deg, lat_deg, profile)
    h, w = elevation.shape

    r0 = int(math.floor(row_f))
    c0 = int(math.floor(col_f))
    r1 = r0 + 1
    c1 = c0 + 1

    if r0 < 0 or c0 < 0 or r1 >= h or c1 >= w:
        return float("nan")

    dr = row_f - r0
    dc = col_f - c0

    v00 = float(elevation[r0, c0])
    v01 = float(elevation[r0, c1])
    v10 = float(elevation[r1, c0])
    v11 = float(elevation[r1, c1])

    if any(math.isnan(v) for v in (v00, v01, v10, v11)):
        return float("nan")

    return (
        v00 * (1 - dr) * (1 - dc)
        + v01 * (1 - dr) * dc
        + v10 * dr       * (1 - dc)
        + v11 * dr       * dc
    )


def crop_region(
    elevation: np.ndarray,
    slope: np.ndarray,
    roughness: np.ndarray,
    profile: dict,
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Crop terrain arrays to a geographic bounding box.

    Parameters
    ----------
    elevation, slope, roughness : np.ndarray
        Full terrain arrays from load_terrain().
    profile : dict
        Terrain profile from load_terrain().
    lon_min, lon_max : float
        Longitude bounds in decimal degrees.
    lat_min, lat_max : float
        Latitude bounds in decimal degrees.

    Returns
    -------
    (elev_crop, slope_crop, roughness_crop, profile_crop) : tuple
        Cropped arrays and updated profile with adjusted transform and dims.
    """
    h, w = elevation.shape

    # Convert all four bbox corners to pixel coordinates
    corners = [
        _latlon_to_pixel_float(lon_min, lat_min, profile),
        _latlon_to_pixel_float(lon_min, lat_max, profile),
        _latlon_to_pixel_float(lon_max, lat_min, profile),
        _latlon_to_pixel_float(lon_max, lat_max, profile),
    ]
    rows = [c[0] for c in corners]
    cols = [c[1] for c in corners]

    row_start = max(0, int(math.floor(min(rows))))
    row_end   = min(h, int(math.ceil(max(rows))) + 1)
    col_start = max(0, int(math.floor(min(cols))))
    col_end   = min(w, int(math.ceil(max(cols))) + 1)

    elev_crop  = elevation[row_start:row_end, col_start:col_end]
    slope_crop = slope    [row_start:row_end, col_start:col_end]
    rough_crop = roughness[row_start:row_end, col_start:col_end]

    # Shift the affine origin to the top-left pixel of the crop
    crop_tf = profile["transform"] * Affine.translation(col_start, row_start)
    crop_h, crop_w = elev_crop.shape

    profile_crop: dict = {
        **profile,
        "transform": crop_tf,
        "height":    crop_h,
        "width":     crop_w,
    }

    # Slice every same-dimension numpy array in the profile (e.g. psr_mask,
    # earth_vis_map, sky_vis_map when resampled to DEM resolution).
    # Ancillary maps at different resolutions are left full-extent and continue
    # to work via lat/lon→pixel coordinate conversion using their own transforms.
    for key, val in profile.items():
        if isinstance(val, np.ndarray) and val.shape == (h, w):
            profile_crop[key] = val[row_start:row_end, col_start:col_end]

    # Drop stale lat-grid cache — caller must recompute for the new extent.
    profile_crop.pop("_lat_grid_cache", None)

    return elev_crop, slope_crop, rough_crop, profile_crop


# ---------------------------------------------------------------------------
# Verification (run as script)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    import matplotlib
    matplotlib.use("Agg")                   # headless — no display required
    import matplotlib.pyplot as plt

    print("=" * 60)
    print("terrain.py — DEM loading & terrain analysis (verification)")
    print("=" * 60)
    print()

    elevation, slope, roughness, profile = load_terrain()

    # ------------------------------------------------------------------
    # Print array stats
    # ------------------------------------------------------------------
    arrays = [
        ("elevation (m)",  elevation),
        ("slope (deg)",    slope),
        ("roughness (m)",  roughness),
        ("aspect (deg)",   profile.get("aspect")),
    ]
    print()
    for name, arr in arrays:
        if arr is None:
            print(f"  {name:20s}  NOT AVAILABLE")
            continue
        valid     = arr[~np.isnan(arr)]
        nan_count = int(np.isnan(arr).sum())
        nan_pct   = 100.0 * nan_count / arr.size
        vmin      = float(valid.min()) if valid.size > 0 else float("nan")
        vmax      = float(valid.max()) if valid.size > 0 else float("nan")
        print(
            f"  {name:20s}  shape={arr.shape}  dtype={arr.dtype}"
            f"  NaN={nan_count:>8,} ({nan_pct:5.1f}%)"
            f"  range=[{vmin:.2f}, {vmax:.2f}]"
        )

    assert elevation.shape == slope.shape == roughness.shape, (
        f"Shape mismatch: {elevation.shape} / {slope.shape} / {roughness.shape}"
    )
    print("\nShape check: PASS")

    # ------------------------------------------------------------------
    # Ancillary layer stats
    # ------------------------------------------------------------------
    ancillary_layers = [
        ("illumination_map",  profile.get("illumination_map")),
        ("psr_mask",          profile.get("psr_mask")),
        ("earth_visibility",  profile.get("earth_visibility")),
        ("sky_visibility",    profile.get("sky_visibility")),
    ]
    print("\nAncillary layers:")
    for lname, arr in ancillary_layers:
        if arr is None:
            print(f"  {lname:22s}  NOT LOADED (file missing)")
            continue
        valid   = arr[~np.isnan(arr)]
        nan_pct = 100.0 * np.isnan(arr).sum() / arr.size
        print(
            f"  {lname:22s}  shape={arr.shape}"
            f"  min={valid.min():.4f}  max={valid.max():.4f}"
            f"  mean={valid.mean():.4f}  NaN={nan_pct:.1f}%"
        )

    # ------------------------------------------------------------------
    # Ground truth checks
    # ------------------------------------------------------------------
    def _sample(arr, lon, lat):
        if arr is None:
            return None
        r, c = latlon_to_pixel(lon, lat, profile)
        if 0 <= r < profile["height"] and 0 <= c < profile["width"]:
            return float(arr[r, c])
        return None

    checks = [
        ("Shackleton peak illum",  "illumination_map",  0.0,  -89.5, 0.85, 1.0),
        ("Shackleton peak PSR",    "psr_mask",          0.0,  -89.5, 0.0,  0.1),
        ("Haworth floor PSR",      "psr_mask",         -5.0,  -87.0, 0.9,  1.0),
        ("Haworth floor illum",    "illumination_map", -5.0,  -87.0, 0.0,  0.1),
    ]
    print("\nGround truth checks:")
    all_pass = True
    for desc, key, lon, lat, lo, hi in checks:
        val = _sample(profile.get(key), lon, lat)
        if val is None or np.isnan(val):
            status = "SKIP (no data)"
        elif lo <= val <= hi:
            status = f"PASS ({val:.3f})"
        else:
            status = f"FAIL ({val:.3f}, expected [{lo},{hi}])"
            all_pass = False
        print(f"  {desc:30s}  {status}")
    print(f"\nGround truth: {'ALL PASS' if all_pass else 'SOME FAILED'}")

    # ------------------------------------------------------------------
    # Create outputs directory and save preview PNG
    # ------------------------------------------------------------------
    out_dir = BASE / "outputs"
    out_dir.mkdir(exist_ok=True)

    # Downsample to ~1500×1500 for plotting: matplotlib converts to RGBA float64
    # (shape × 4 × 8 bytes), so a 10133² array would need 3 GB — OOM on 8 GB systems.
    PLOT_STEP = max(1, elevation.shape[0] // 1500)

    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    axes = axes.flatten()
    panels = [
        (elevation,              "Elevation (m)",              "cividis"),
        (slope,                  "Slope (degrees)",            "hot"),
        (roughness,              "Roughness (m)",              "plasma"),
        (profile.get("aspect"),  "Aspect (deg, CW from N)",   "hsv"),
    ]

    for ax, (arr, title, cmap) in zip(axes, panels):
        if arr is None:
            ax.set_title(f"{title}\nNOT AVAILABLE")
            ax.axis("off")
            continue
        valid   = arr[~np.isnan(arr)]
        vmin    = float(valid.min()) if valid.size > 0 else 0.0
        vmax    = float(valid.max()) if valid.size > 0 else 1.0
        nan_pct = 100.0 * int(np.isnan(arr).sum()) / arr.size

        plot_arr = arr[::PLOT_STEP, ::PLOT_STEP]   # decimated for display only
        im = ax.imshow(plot_arr, cmap=cmap, vmin=vmin, vmax=vmax, origin="upper")
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        ax.set_title(
            f"{title}\n"
            f"min={vmin:.2f}  max={vmax:.2f}  NaN={nan_pct:.1f}%"
        )
        ax.axis("off")

    plt.tight_layout()
    out_path = out_dir / "terrain_preview.png"
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"\nSaved: {out_path}")

    # ------------------------------------------------------------------
    # Plotly 2×2 ancillary preview (HTML, dark theme)
    # ------------------------------------------------------------------
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        STEP = max(1, profile["height"] // 500)
        layers_plot = [
            ("illumination_map",  "Solar Illumination", "plasma"),
            ("psr_mask",          "PSR Mask",            "Blues"),
            ("earth_visibility",  "Earth Visibility",    "viridis"),
            ("sky_visibility",    "Sky Visibility",      "cividis"),
        ]
        fig_ancillary = make_subplots(rows=2, cols=2, subplot_titles=[l[1] for l in layers_plot])
        for (key, title, cscale), (row, col) in zip(layers_plot, [(1,1),(1,2),(2,1),(2,2)]):
            arr = profile.get(key)
            if arr is None:
                continue
            thumb = arr[::STEP, ::STEP]
            fig_ancillary.add_trace(
                go.Heatmap(z=thumb, colorscale=cscale, showscale=True,
                           colorbar=dict(len=0.45)),
                row=row, col=col,
            )
        fig_ancillary.update_layout(
            title="Ancillary Layers — Lunar South Pole",
            template="plotly_dark",
            height=900, width=1100,
        )
        html_out = out_dir / "ancillary_preview.html"
        fig_ancillary.write_html(str(html_out))
        print(f"Saved Plotly preview: {html_out}")
    except ImportError:
        print("[plotly not installed — skipping HTML preview]")
