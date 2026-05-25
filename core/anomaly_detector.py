"""
core/anomaly_detector.py — DBSCAN-based geological anomaly detection.

Identifies geologically anomalous terrain clusters as candidate science targets
by computing four feature planes (elevation deviation, roughness z-score,
slope gradient magnitude, local elevation contrast) and clustering with DBSCAN.

Public API:
    detect_anomalies(elevation, slope, roughness, profile) -> list[dict]
    _create_anomaly_preview(elevation, anomalies, profile) -> str (HTML)

Example::

    anomalies = detect_anomalies(elevation, slope, roughness, profile)
    # anomalies[0]["anomaly_type"]  -> "ELEVATION_ANOMALY"
    # anomalies[0]["anomaly_strength"] -> 3.14
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter, maximum_filter, minimum_filter
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler
import plotly.graph_objects as go
import plotly.io as pio
import rasterio.transform
import pyproj

# ---------------------------------------------------------------------------
# Constants
# RAM: ~300 MB peak on 4 GB machines (downsampled to _MAX_SIDE=2500 before feature planes)
# ---------------------------------------------------------------------------

WINDOW_LOCAL    = 25      # pixels, uniform_filter for local elevation stats
WINDOW_CONTRAST = 5       # pixels, max/min filter for local_contrast
N_SUBSAMPLE     = 20_000  # random pixel samples for DBSCAN (keep low — DBSCAN memory ∝ n²)
MIN_CLUSTER_PX  = 5       # minimum cluster size (sampled pixels)
# eps=0.18: k-distance elbow on 20k samples from the LOLA 80–90°S DEM (test_dbscan_params.py).
# The elbow method found the natural density boundary at 0.1841, yielding ~7 distinct
# geological clusters. The previous value (0.5) merged all terrain into 1 cluster.
DBSCAN_EPS      = 0.18
DBSCAN_MIN_SAMPLES = 10

_RECOMMENDED_FOR: dict[str, list[str]] = {
    "THERMAL_PROXY":     ["water_ice", "geological"],
    "ELEVATION_ANOMALY": ["geological", "atmospheric"],
    "ROUGHNESS_ANOMALY": ["geological"],
    "SLOPE_TRANSITION":  ["geological", "atmospheric"],
}

_ANOMALY_STYLE: dict[str, tuple[str, str]] = {
    "THERMAL_PROXY":     ("diamond",        "#FF6B6B"),
    "ELEVATION_ANOMALY": ("circle",         "#FFD700"),
    "ROUGHNESS_ANOMALY": ("square",         "#FF8C00"),
    "SLOPE_TRANSITION":  ("triangle-up",    "#00CED1"),
}


# ---------------------------------------------------------------------------
# CRS helpers (self-contained — same pattern as terrain_classifier.py)
# ---------------------------------------------------------------------------

_CRS_STERE = (
    "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
    "+R=1737400 +units=m +no_defs"
)
_CRS_LONLAT = "+proj=longlat +R=1737400 +no_defs"

_TRANSFORMER: pyproj.Transformer | None = None


def _get_transformer() -> pyproj.Transformer:
    global _TRANSFORMER
    if _TRANSFORMER is None:
        _TRANSFORMER = pyproj.Transformer.from_crs(
            _CRS_STERE, _CRS_LONLAT, always_xy=True
        )
    return _TRANSFORMER


def _pixel_to_latlon(
    row: int | float, col: int | float, profile: dict
) -> tuple[float, float]:
    x, y = rasterio.transform.xy(profile["transform"], row, col)
    lon, lat = _get_transformer().transform(x, y)
    return float(lon), float(lat)


# ---------------------------------------------------------------------------
# Downsampling helper (same as visualizer.py)
# ---------------------------------------------------------------------------

def _downsample(arr: np.ndarray, target: int = 500) -> tuple[np.ndarray, int]:
    stride = max(1, arr.shape[0] // target)
    return arr[::stride, ::stride], stride


# ---------------------------------------------------------------------------
# Feature plane computation
# ---------------------------------------------------------------------------

def _compute_feature_planes(
    elevation: np.ndarray,
    slope: np.ndarray,
    roughness: np.ndarray,
) -> list[np.ndarray]:
    """Compute 4 anomaly feature planes. Returns list of float32 arrays."""

    def _clean(arr: np.ndarray) -> np.ndarray:
        return np.where(np.isfinite(arr), arr, np.float32(0.0)).astype(np.float32)

    # ---- plane 0: elevation_deviation ----
    e = elevation.astype(np.float32)
    local_mean = uniform_filter(e, size=WINDOW_LOCAL).astype(np.float32)
    local_sq   = uniform_filter(e * e, size=WINDOW_LOCAL).astype(np.float32)
    local_var  = np.maximum(local_sq - local_mean * local_mean, np.float32(0.0))
    local_std  = np.sqrt(local_var)
    p0 = np.abs(e - local_mean) / (local_std + np.float32(1e-6))
    p0 = _clean(p0)

    # ---- plane 1: roughness_zscore ----
    r = roughness.astype(np.float32)
    r_mean = float(np.nanmean(r))
    r_std  = float(np.nanstd(r))
    p1 = (r - r_mean) / (r_std + 1e-6)
    p1 = np.clip(p1, 0.0, None)   # positive anomalies only
    p1 = _clean(p1)

    # ---- plane 2: slope_gradient_magnitude (verbatim from terrain_classifier feature 6) ----
    sl = slope.astype(np.float32)
    gx          = np.empty_like(sl)
    gx[:, 1:-1] = (sl[:, 2:] - sl[:, :-2]) * np.float32(0.5)
    gx[:, 0]    = sl[:, 1] - sl[:, 0]
    gx[:, -1]   = sl[:, -1] - sl[:, -2]
    gy          = np.empty_like(sl)
    gy[1:-1, :] = (sl[2:, :] - sl[:-2, :]) * np.float32(0.5)
    gy[0, :]    = sl[1, :] - sl[0, :]
    gy[-1, :]   = sl[-1, :] - sl[-2, :]
    grad_mag    = np.sqrt(gx * gx + gy * gy)
    del gx, gy
    g95 = float(np.nanpercentile(grad_mag, 95))
    g95 = g95 if g95 > 1e-6 else 1.0
    p2  = np.clip(grad_mag / np.float32(g95), np.float32(0.0), np.float32(1.0))
    del grad_mag
    p2  = _clean(p2)

    # ---- plane 3: local_contrast ----
    p3_raw = (
        maximum_filter(e, size=WINDOW_CONTRAST).astype(np.float32)
        - minimum_filter(e, size=WINDOW_CONTRAST).astype(np.float32)
    )
    p3_95  = float(np.nanpercentile(p3_raw, 95))
    p3_95  = p3_95 if p3_95 > 1e-6 else 1.0
    p3     = np.clip(p3_raw / p3_95, 0.0, None)
    p3     = _clean(p3)

    return [p0, p1, p2, p3]


# ---------------------------------------------------------------------------
# Cluster type classification
# ---------------------------------------------------------------------------

def _classify_cluster_type(feat_means: np.ndarray, centroid_elevation: float) -> str:
    """Map feature means + centroid elevation to an anomaly type string."""
    dominant = int(np.argmax(feat_means))

    # THERMAL_PROXY: elevation_deviation dominant AND deep basin
    if dominant == 0 and centroid_elevation < -3000.0:
        return "THERMAL_PROXY"

    if dominant in (0, 3):
        return "ELEVATION_ANOMALY"
    if dominant == 1:
        return "ROUGHNESS_ANOMALY"
    # dominant == 2
    return "SLOPE_TRANSITION"


# ---------------------------------------------------------------------------
# Anomaly preview visualisation
# ---------------------------------------------------------------------------

def _build_axis_ticks(
    n_px_ds: int, stride: int, profile: dict, axis: str
) -> tuple[list[int], list[str]]:
    n_ticks  = 6
    ds_indices = [round(i * (n_px_ds - 1) / (n_ticks - 1)) for i in range(n_ticks)]
    ticktext = []
    for ds_idx in ds_indices:
        px = ds_idx * stride
        if axis == "row":
            lon, lat = _pixel_to_latlon(px, 0, profile)
            ticktext.append(f"{lat:.2f}°")
        else:
            lon, lat = _pixel_to_latlon(0, px, profile)
            ticktext.append(f"{lon:.2f}°")
    return ds_indices, ticktext


def _create_anomaly_preview(
    elevation: np.ndarray,
    anomalies: list[dict],
    profile: dict,
) -> str:
    """Build a Plotly anomaly preview. Returns a full HTML string."""
    elev_ds, stride = _downsample(elevation)
    n_rows_ds = elev_ds.shape[0]
    n_cols_ds = elev_ds.shape[1]

    y_tickvals, y_ticktext = _build_axis_ticks(n_rows_ds, stride, profile, "row")
    x_tickvals, x_ticktext = _build_axis_ticks(n_cols_ds, stride, profile, "col")

    traces: list[go.BaseTraceType] = []

    # ---- 1. Elevation heatmap ----
    traces.append(go.Heatmap(
        z=elev_ds,
        colorscale="thermal",
        name="Elevation (m)",
        colorbar=dict(title="Elev (m)", x=1.0),
        showscale=True,
    ))

    # ---- 2. Anomaly scatter traces per type ----
    # Group anomalies by type
    by_type: dict[str, list[dict]] = {}
    for a in anomalies:
        by_type.setdefault(a["anomaly_type"], []).append(a)

    for atype, group in by_type.items():
        symbol, color = _ANOMALY_STYLE.get(atype, ("circle", "white"))
        xs     = [a["centroid_col"] / stride for a in group]
        ys     = [a["centroid_row"] / stride for a in group]
        hover  = [
            (
                f"Type: {a['anomaly_type']}<br>"
                f"Strength: {a['anomaly_strength']:.3f}<br>"
                f"Pixels: {a['pixel_count']}<br>"
                f"Lat: {a['lat']:.3f}°<br>"
                f"Lon: {a['lon']:.3f}°<br>"
                f"Recommended for: {', '.join(a['recommended_for'])}"
            )
            for a in group
        ]
        traces.append(go.Scatter(
            x=xs, y=ys,
            mode="markers",
            marker=dict(symbol=symbol, color=color, size=12,
                        line=dict(color="white", width=1)),
            name=atype,
            text=hover,
            hovertemplate="%{text}<extra></extra>",
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        template="plotly_dark",
        width=900,
        height=900,
        title="Lunar South Pole — Geological Anomaly Clusters",
        showlegend=True,
        xaxis=dict(
            title="Longitude",
            tickvals=x_tickvals,
            ticktext=x_ticktext,
        ),
        yaxis=dict(
            title="Latitude",
            tickvals=y_tickvals,
            ticktext=y_ticktext,
            autorange="reversed",
        ),
    )

    fragment = pio.to_html(fig, full_html=False, include_plotlyjs="cdn")
    return f"<html><body>{fragment}</body></html>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_anomalies(
    elevation: np.ndarray,
    slope: np.ndarray,
    roughness: np.ndarray,
    profile: dict,
) -> list[dict]:
    """Detect geologically anomalous terrain clusters via DBSCAN.

    Parameters
    ----------
    elevation : np.ndarray float32 (H, W)
    slope     : np.ndarray float32 (H, W)
    roughness : np.ndarray float32 (H, W)
    profile   : dict  — rasterio-style profile with ``transform``, ``height``, ``width``

    Returns
    -------
    list[dict] sorted by anomaly_strength descending. Each dict has keys:
        centroid_row, centroid_col, lat, lon, anomaly_type,
        anomaly_strength, pixel_count, recommended_for
    """
    H, W = elevation.shape
    print(f"[anomaly] Computing feature planes for {H}×{W} terrain …")

    # ---- 0. Downsample large terrains to stay within memory limits ----
    # Each float32 array at full resolution = H*W*4 bytes.
    # _compute_feature_planes creates ~12 intermediate arrays, so we cap the
    # working resolution to keep peak memory well under 4 GB.
    _MAX_SIDE = 2500  # target max dimension for anomaly computation
    ds_stride = max(1, max(H, W) // _MAX_SIDE)
    if ds_stride > 1:
        elev_in = elevation[::ds_stride, ::ds_stride]
        slope_in = slope[::ds_stride, ::ds_stride]
        rough_in = roughness[::ds_stride, ::ds_stride]
        print(f"[anomaly] Downsampled {H}×{W} → {elev_in.shape[0]}×{elev_in.shape[1]} "
              f"(stride={ds_stride}) to reduce memory usage.")
    else:
        elev_in, slope_in, rough_in = elevation, slope, roughness
        ds_stride = 1

    # ---- 1. Feature planes (on possibly-downsampled arrays) ----
    planes = _compute_feature_planes(elev_in, slope_in, rough_in)

    # ---- 2. Subsample random pixels (from the downsampled grid) ----
    rng     = np.random.default_rng(42)
    H_ds, W_ds = planes[0].shape
    n_total = H_ds * W_ds
    n_samp  = min(N_SUBSAMPLE, n_total)
    idx     = rng.choice(n_total, size=n_samp, replace=False)

    # row / col coords for each sampled index (in downsampled pixel space)
    rows = (idx // W_ds).astype(np.int32)
    cols = (idx  % W_ds).astype(np.int32)

    # ---- 3. Gather feature values (then free planes immediately) ----
    X_raw = np.stack([p.reshape(-1)[idx] for p in planes], axis=-1).astype(np.float32)
    del planes
    if ds_stride > 1:
        del elev_in, slope_in, rough_in

    # ---- 4. Replace NaN/inf ----
    X_raw = np.where(np.isfinite(X_raw), X_raw, np.float32(0.0))

    # ---- 5. Scale ----
    X_scaled = StandardScaler().fit_transform(X_raw).astype(np.float32)

    # ---- 6. DBSCAN ----
    print(f"[anomaly] Running DBSCAN on {n_samp:,} samples …")
    labels = DBSCAN(
        eps=DBSCAN_EPS,
        min_samples=DBSCAN_MIN_SAMPLES,
        algorithm="ball_tree",
        n_jobs=1,
    ).fit_predict(X_scaled)

    unique_labels = set(labels)
    unique_labels.discard(-1)   # noise
    print(f"[anomaly] DBSCAN found {len(unique_labels)} clusters (excl. noise).")

    # ---- 7. Build anomaly dicts ----
    results: list[dict] = []
    for label in unique_labels:
        mask        = labels == label
        pixel_count = int(mask.sum())

        if pixel_count < MIN_CLUSTER_PX:
            continue

        cluster_rows = rows[mask]
        cluster_cols = cols[mask]

        # Centroid in downsampled space → scale back to full-resolution pixels
        centroid_row = int(round(float(cluster_rows.mean()))) * ds_stride
        centroid_col = int(round(float(cluster_cols.mean()))) * ds_stride

        # Clamp to valid range
        centroid_row = max(0, min(centroid_row, H - 1))
        centroid_col = max(0, min(centroid_col, W - 1))

        lon, lat = _pixel_to_latlon(centroid_row, centroid_col, profile)

        # Feature means at cluster indices using UN-scaled features
        feat_means = X_raw[mask].mean(axis=0)

        centroid_elev = float(elevation[centroid_row, centroid_col])
        anomaly_type  = _classify_cluster_type(feat_means, centroid_elev)

        dominant_feat     = int(np.argmax(feat_means))
        anomaly_strength  = float(feat_means[dominant_feat])
        recommended_for   = _RECOMMENDED_FOR[anomaly_type]

        results.append({
            "centroid_row"    : centroid_row,
            "centroid_col"    : centroid_col,
            "lat"             : lat,
            "lon"             : lon,
            "anomaly_type"    : anomaly_type,
            "anomaly_strength": anomaly_strength,
            "pixel_count"     : pixel_count,
            "recommended_for" : recommended_for,
        })

    # ---- 8. Sort by strength ----
    results.sort(key=lambda a: a["anomaly_strength"], reverse=True)

    # ---- 9. Summary ----
    type_counts: dict[str, int] = {}
    for a in results:
        type_counts[a["anomaly_type"]] = type_counts.get(a["anomaly_type"], 0) + 1
    print(
        f"[anomaly] Detected {len(results)} anomaly clusters: "
        + ", ".join(f"{v}×{k}" for k, v in type_counts.items())
    )

    return results


# ---------------------------------------------------------------------------
# Verification block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import sys

    # 1. Load terrain
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from core.terrain import load_terrain
        elevation, slope, roughness, profile = load_terrain()
        print("[anomaly __main__] Real terrain loaded.")
    except Exception as e:
        print(f"[anomaly __main__] load_terrain failed ({e}), using synthetic terrain.")
        from core.landing_scorer import _synthetic_terrain
        elevation, slope, roughness, profile = _synthetic_terrain(shape=(500, 500))
        print("[anomaly __main__] Synthetic terrain (500×500) loaded.")

    # 2. Detect anomalies
    anomalies = detect_anomalies(elevation, slope, roughness, profile)

    # 3. Print summary table
    print(f"\n{'TYPE':<20} {'STRENGTH':>9} {'PIXELS':>8} {'LAT':>9} {'LON':>9}")
    print("-" * 60)
    for a in anomalies:
        print(
            f"{a['anomaly_type']:<20} "
            f"{a['anomaly_strength']:>9.3f} "
            f"{a['pixel_count']:>8} "
            f"{a['lat']:>9.3f} "
            f"{a['lon']:>9.3f}"
        )

    # 4. Create preview HTML
    html = _create_anomaly_preview(elevation, anomalies, profile)

    # 5. Save to outputs/
    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "anomaly_preview.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[anomaly __main__] Preview saved to: {out_path}")
