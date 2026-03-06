"""
core/terrain.py — DEM loading and terrain analysis for lunar south-pole DEMs.

Data source: LOLA 20 m/px JP2 DEMs, 80–90°S
  DEM:   data/dem/DEM_20M/LDEM_80S_20M.JP2  (int16, elevation DN)
  Count: data/dem/DEM_20M/LDEC_80S_20M.JP2  (uint8, data-count quality mask)

JP2 files carry no embedded CRS or geotransform; both are constructed from LBL
parameters following the same pattern as core/multi_res_fusion.py.

Raw DN → metres: elevation_m = raw_int16 × 0.5
Nodata raw values: 0 and -32768 → set to nan.
"""

from __future__ import annotations

import math
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

BASE = Path(__file__).parent.parent

DEM_PATH   = BASE / "data" / "dem" / "DEM_20M" / "LDEM_80S_20M.JP2"
COUNT_PATH = BASE / "data" / "dem" / "DEM_20M" / "LDEC_80S_20M.JP2"

# LBL-derived parameters for the 20 m native resolution
_MAP_SCALE_M    = 20.0
_PROJ_OFFSET_PX = 15199.5

# DN → metres (LBL SCALING_FACTOR)
_JP2_SCALE = 0.5

# Raw values that represent nodata in LOLA JP2s
_NODATA_RAW_A = 0
_NODATA_RAW_B = -32768

# Moon CRS strings
_CRS_STERE = (
    "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
    "+R=1737400 +units=m +no_defs"
)
_CRS_LONLAT = "+proj=longlat +R=1737400 +no_defs"

# Module-level singleton Transformer (polar-stere → lon/lat), thread-safe
_TRANSFORMER: pyproj.Transformer | None = None


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


def _jp2_affine(map_scale_m: float = 20.0, proj_offset_px: float = 15199.5) -> Affine:
    """Construct rasterio Affine transform from LBL map_scale and proj_offset.

    origin_x = -proj_offset_px × map_scale_m  (left edge, westernmost)
    origin_y = +proj_offset_px × map_scale_m  (top edge,  northernmost)
    """
    origin_x = -proj_offset_px * map_scale_m
    origin_y =  proj_offset_px * map_scale_m
    return Affine(map_scale_m, 0, origin_x,
                  0, -map_scale_m, origin_y)


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


def _scale_dem(raw_int16: np.ndarray) -> np.ndarray:
    """Convert raw int16 DN → float32 elevation_m; mark nodata as NaN.

    Boolean OR of equality tests avoids the int64 promotion that np.isin()
    would trigger, keeping peak memory at 1 byte/px for the mask.
    """
    arr = raw_int16.astype(np.float32) * _JP2_SCALE
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
        src_crs = rasterio.crs.CRS.from_proj4(_CRS_STERE)

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
# Public API
# ---------------------------------------------------------------------------

def load_terrain(
    dem_path: Path | str | None = None,
    count_path: Path | str | None = None,
    target_res_m: float = 60.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Load the lunar south-pole DEM and compute slope and roughness.

    Parameters
    ----------
    dem_path : path-like, optional
        Path to the DEM JP2 file (default: DEM_PATH module constant).
    count_path : path-like, optional
        Path to the data-count JP2 file (default: COUNT_PATH module constant).
    target_res_m : float
        Target output resolution in metres (must be a multiple of 20 m).
        Default 60 m → factor-3 downsample.

    Returns
    -------
    elevation : np.ndarray, float32, shape (H, W)
        Elevation in metres; NaN where nodata.
    slope : np.ndarray, float32, shape (H, W)
        Slope in degrees.
    roughness : np.ndarray, float32, shape (H, W)
        Local elevation std-dev in metres (3×3 window).
    profile : dict
        Rasterio-compatible profile with keys:
          crs, transform, height, width, dtype, nodata, resolution_m.
        Also includes optional key "quality_mask" (float32 data-count array).

    Memory budget
    -------------
    Downsampled int16 (factor 3) : ~193 MB  (read directly via JP2 wavelet levels)
    Scaled float32 DEM           : ~410 MB
    Slope float32                : ~410 MB
    Roughness float32            : ~410 MB
    Peak (during roughness)      : ~1.23 GB  (3 × float32 arrays)
    Full-res array never allocated — JP2 wavelet decode serves 1/3 res directly.
    """
    dem_path   = Path(dem_path)   if dem_path   is not None else DEM_PATH
    count_path = Path(count_path) if count_path is not None else COUNT_PATH

    moon_crs      = rasterio.crs.CRS.from_proj4(_CRS_STERE)
    affine_native = _jp2_affine(_MAP_SCALE_M, _PROJ_OFFSET_PX)
    factor        = round(target_res_m / _MAP_SCALE_M)   # 3 for 60 m target
    new_affine    = affine_native * Affine.scale(factor)

    # ------------------------------------------------------------------
    # 1. Load DEM at target resolution in one step.
    # rasterio read(out_shape=...) instructs GDAL to use JPEG2000's built-in
    # wavelet resolution levels, so we never allocate the full 1.74 GB array.
    # Peak memory: ~193 MB (downsampled int16) → ~410 MB (scaled float32).
    # ------------------------------------------------------------------
    print(
        f"Loading DEM at {target_res_m:.0f} m/px "
        f"(factor-{factor} downsample during JP2 decode) …"
    )
    raw_ds = _load_jp2_downsampled(
        dem_path, factor=factor, resampling=Resampling.average, out_dtype=np.int16,
    )

    # ------------------------------------------------------------------
    # 2. Scale DN → metres; mask nodata as NaN
    # ------------------------------------------------------------------
    elevation = _scale_dem(raw_ds)
    del raw_ds                                                # free ~193 MB

    h, w = elevation.shape

    # ------------------------------------------------------------------
    # 3. Slope and roughness
    # ------------------------------------------------------------------
    print("Computing slope …")
    slope = _compute_slope(elevation, target_res_m)

    print("Computing roughness …")
    roughness = _compute_roughness(elevation)

    # ------------------------------------------------------------------
    # 4. Load data-count quality mask (optional)
    # ------------------------------------------------------------------
    quality_mask: np.ndarray | None = None
    if count_path.exists():
        print(f"Loading count mask: {count_path} …")
        raw_count = _load_jp2_downsampled(
            count_path, factor=factor, resampling=Resampling.average, out_dtype=np.int16,
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

    # Solar illumination map (deferred import avoids circular dependency)
    from core.energy_model import estimate_sunlight  # noqa: PLC0415
    profile["sunlight_map"] = estimate_sunlight(elevation, profile)

    print(
        f"Done. Elevation shape: {elevation.shape}, "
        f"resolution: {target_res_m:.0f} m/px"
    )
    return elevation, slope, roughness, profile


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

    profile_crop = {
        **profile,
        "transform": crop_tf,
        "height":    crop_h,
        "width":     crop_w,
    }
    # quality_mask and sunlight_map are not sliced here — full-array references only

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
    ]
    print()
    for name, arr in arrays:
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
    # Create outputs directory and save preview PNG
    # ------------------------------------------------------------------
    out_dir = BASE / "outputs"
    out_dir.mkdir(exist_ok=True)

    # Downsample to ~1500×1500 for plotting: matplotlib converts to RGBA float64
    # (shape × 4 × 8 bytes), so a 10133² array would need 3 GB — OOM on 8 GB systems.
    PLOT_STEP = max(1, elevation.shape[0] // 1500)

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    panels = [
        (elevation, "Elevation (m)",   "cividis"),
        (slope,     "Slope (degrees)", "hot"),
        (roughness, "Roughness (m)",   "plasma"),
    ]

    for ax, (arr, title, cmap) in zip(axes, panels):
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
