"""
core/terrain_classifier.py — Random Forest terrain classification.

Trains a multi-class classifier on landing-scorer outputs and classifies
the full DEM into 5 terrain categories:

  0  HAZARD_ZONE
  1  RISKY_LANDING
  2  TRAVERSE_CORRIDOR
  3  SAFE_LANDING
  4  SCIENCE_TARGET

Public API:
    train_classifier(elevation, slope, roughness, profile,
                     safety_score, mission_score, final_score=None)
        -> (classifier, metrics_dict)

    classify_terrain(classifier, elevation, slope, roughness, profile)
        -> class_map  np.ndarray uint8 (H, W)

    load_classifier(path=MODEL_PATH) -> classifier | None

    create_classification_map(class_map, profile) -> str (HTML fragment)
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pyproj
import rasterio.crs
import rasterio.transform
from affine import Affine
from scipy.ndimage import uniform_filter
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score, f1_score
import plotly.graph_objects as go
import plotly.io as pio

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLASS_NAMES = {
    0: "HAZARD_ZONE",
    1: "RISKY_LANDING",
    2: "TRAVERSE_CORRIDOR",
    3: "SAFE_LANDING",
    4: "SCIENCE_TARGET",
}
CLASS_COLORS = ["red", "orange", "yellow", "green", "purple"]
MODEL_PATH = Path(__file__).parent.parent / "models" / "terrain_classifier.pkl"

# ---------------------------------------------------------------------------
# CRS / projection helpers (same as landing_scorer.py — self-contained)
# ---------------------------------------------------------------------------

_CRS_STERE = (
    "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
    "+R=1737400 +units=m +no_defs"
)
_CRS_LONLAT = "+proj=longlat +R=1737400 +no_defs"
_LAT_GRID_STRIP = 50

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


def _build_lat_grid(profile: dict) -> np.ndarray:
    """Return float32 (H, W) array of latitude in decimal degrees.

    Processes in strips of _LAT_GRID_STRIP rows to keep peak memory low.
    Copied from landing_scorer.py — keeps this module self-contained.
    """
    T   = profile["transform"]
    H   = profile["height"]
    W   = profile["width"]
    res = float(T.a)
    x0  = float(T.c)
    y0  = float(T.f)

    x_1d = x0 + np.arange(W, dtype=np.float64) * res
    y_1d = y0 - np.arange(H, dtype=np.float64) * res

    tr       = _get_transformer()
    lat_grid = np.empty((H, W), dtype=np.float32)

    for r0 in range(0, H, _LAT_GRID_STRIP):
        r1     = min(r0 + _LAT_GRID_STRIP, H)
        n_rows = r1 - r0
        xs     = np.tile(x_1d, n_rows)
        ys     = np.repeat(y_1d[r0:r1], W)
        _, lats = tr.transform(xs, ys)
        lat_grid[r0:r1] = lats.reshape(n_rows, W).astype(np.float32)

    return lat_grid


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------

def _build_feature_planes(
    elevation: np.ndarray,
    slope:     np.ndarray,
    roughness: np.ndarray,
    profile:   dict,
) -> list[np.ndarray]:
    """Compute 8 feature planes, returned as a list of float32 (H, W) arrays.

    Feature index mapping:
      0  elevation_m normalized        (elev - nanmin) / (nanmax - nanmin)
      1  slope_deg normalized          slope / 90.0
      2  roughness_m normalized        roughness / nanmax
      3  quality_mask                  from profile["quality_mask"], else ones
      4  local_mean_slope              uniform_filter(slope, 3) / 90
      5  local_std_elevation           sqrt(E[e²] - E[e]²) normalized
      6  slope_gradient                finite-diff magnitude / 95th-pct
      7  lat_normalized                -(lat + 90) / 10
    """
    H, W = elevation.shape

    # 0: elevation normalized
    e_min  = float(np.nanmin(elevation))
    e_max  = float(np.nanmax(elevation))
    e_span = max(e_max - e_min, 1e-6)
    p0 = np.where(
        np.isfinite(elevation),
        (elevation.astype(np.float32) - np.float32(e_min)) / np.float32(e_span),
        np.float32(0.0),
    ).astype(np.float32)

    # 1: slope normalized
    p1 = (slope.astype(np.float32) / np.float32(90.0))
    p1 = np.where(np.isfinite(p1), p1, np.float32(0.0))

    # 2: roughness normalized
    r_max = float(np.nanmax(roughness))
    r_max = r_max if r_max > 1e-6 else 1.0
    p2 = np.where(
        np.isfinite(roughness),
        roughness.astype(np.float32) / np.float32(r_max),
        np.float32(0.0),
    ).astype(np.float32)

    # 3: quality_mask
    qm = profile.get("quality_mask")
    if qm is not None:
        p3 = qm.astype(np.float32)
        p3 = np.where(np.isfinite(p3), p3, np.float32(0.0))
    else:
        p3 = np.ones((H, W), dtype=np.float32)

    # 4: local_mean_slope via uniform_filter
    p4 = uniform_filter(slope.astype(np.float32), size=3) / np.float32(90.0)
    p4 = np.where(np.isfinite(p4), p4, np.float32(0.0))

    # 5: local_std_elevation  sqrt(max(E[e²] - E[e]², 0)), normalized
    elev_f64 = np.where(
        np.isfinite(elevation.astype(np.float64)),
        elevation.astype(np.float64),
        0.0,
    )
    mean_e  = uniform_filter(elev_f64, size=3).astype(np.float32)
    sq_mean = uniform_filter(elev_f64 ** 2, size=3).astype(np.float32)
    del elev_f64
    p5 = np.sqrt(np.maximum(sq_mean - mean_e * mean_e, np.float32(0.0)))
    del mean_e, sq_mean
    e_abs_max = float(np.nanmax(np.abs(elevation))) if np.any(np.isfinite(elevation)) else 1.0
    e_abs_max = e_abs_max if e_abs_max > 1e-6 else 1.0
    p5 /= np.float32(e_abs_max)
    p5 = np.where(np.isfinite(p5), p5, np.float32(0.0))

    # 6: slope_gradient  (finite-diff magnitude of slope array / 95th pct)
    sl = slope.astype(np.float32)
    gx          = np.empty_like(sl)
    gx[:, 1:-1] = (sl[:, 2:] - sl[:, :-2]) * np.float32(0.5)
    gx[:, 0]    = sl[:, 1] - sl[:, 0]
    gx[:, -1]   = sl[:, -1] - sl[:, -2]
    gy          = np.empty_like(sl)
    gy[1:-1]    = (sl[2:] - sl[:-2]) * np.float32(0.5)
    gy[0]       = sl[1] - sl[0]
    gy[-1]      = sl[-1] - sl[-2]
    grad_mag    = np.sqrt(gx * gx + gy * gy)
    del gx, gy
    g95  = float(np.nanpercentile(grad_mag, 95))
    g95  = g95 if g95 > 1e-6 else 1.0
    p6   = np.clip(grad_mag / np.float32(g95), np.float32(0.0), np.float32(1.0))
    del grad_mag
    p6   = np.where(np.isfinite(p6), p6, np.float32(0.0))

    # 7: lat_normalized  -(lat + 90) / 10  → range: -1 at -80°, 0 at -90°
    lat_grid = _build_lat_grid(profile)
    p7 = -(lat_grid + np.float32(90.0)) / np.float32(10.0)
    p7 = np.where(np.isfinite(p7), p7, np.float32(0.0))

    return [p0, p1, p2, p3, p4, p5, p6, p7]


def _build_features(
    elevation: np.ndarray,
    slope:     np.ndarray,
    roughness: np.ndarray,
    profile:   dict,
) -> np.ndarray:
    """Compute 8 feature planes → float32 (H, W, 8).

    NOTE: allocates (H×W×8) float32 — only safe for small arrays (≤500×500).
    For large DEMs use _build_feature_planes() and classify/sample strip-by-strip.
    """
    planes = _build_feature_planes(elevation, slope, roughness, profile)
    return np.stack(planes, axis=-1).astype(np.float32)


# ---------------------------------------------------------------------------
# Label generation
# ---------------------------------------------------------------------------

def _build_labels(
    slope:        np.ndarray,
    roughness:    np.ndarray,
    safety_score: np.ndarray,
    mission_score: np.ndarray,
    final_score:  np.ndarray,
) -> np.ndarray:
    """Assign class labels via priority rules → uint8 (H, W).

    Priority order (first matching rule wins):
      Rule 1  slope > 25  OR  roughness > 200          → 0  HAZARD_ZONE
      Rule 2  mission > 0.7  AND  safety > 0.3         → 4  SCIENCE_TARGET
      Rule 3  safety > 0.6  AND  final_score > 0.5     → 3  SAFE_LANDING
      Rule 4  0.3 ≤ safety ≤ 0.6                       → 2  TRAVERSE_CORRIDOR
      else                                              → 1  RISKY_LANDING
    """
    labels = np.ones(slope.shape, dtype=np.uint8)  # default: RISKY_LANDING (1)

    # Rule 4 (lowest priority among overrides)
    mask4 = (safety_score >= 0.3) & (safety_score <= 0.6)
    labels[mask4] = np.uint8(2)

    # Rule 3 (overrides rule 4)
    mask3 = (safety_score > 0.6) & (final_score > 0.5)
    labels[mask3] = np.uint8(3)

    # Rule 2 (overrides rules 3 and 4)
    mask2 = (mission_score > 0.7) & (safety_score > 0.3)
    labels[mask2] = np.uint8(4)

    # Rule 1 (overrides all)
    mask1 = (slope > 25.0) | (roughness > 200.0)
    labels[mask1] = np.uint8(0)

    return labels.astype(np.uint8)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_classifier(
    elevation:    np.ndarray,
    slope:        np.ndarray,
    roughness:    np.ndarray,
    profile:      dict,
    safety_score: np.ndarray,
    mission_score: np.ndarray,
    final_score:  np.ndarray | None = None,
) -> tuple:
    """Train a RandomForest terrain classifier and save to disk.

    Parameters
    ----------
    elevation, slope, roughness : float32 arrays (H, W)
    profile : terrain profile dict
    safety_score, mission_score : float32 arrays (H, W)  from score_terrain()
    final_score : optional float32 array (H, W); if None, approximated as
                  0.7×safety + 0.3×mission

    Returns
    -------
    (classifier, metrics_dict)
    metrics_dict keys: accuracy, per_class_f1, feature_importances
    """
    print("[classifier] Building features …")
    # Build 8 planes separately to avoid a (H×W×8) stacked array in memory
    planes = _build_feature_planes(elevation, slope, roughness, profile)

    if final_score is None:
        final_score = (
            np.float32(0.7) * safety_score.astype(np.float32)
            + np.float32(0.3) * mission_score.astype(np.float32)
        )

    labels = _build_labels(slope, roughness, safety_score, mission_score, final_score)

    H, W    = elevation.shape
    n_total = H * W
    n_train = min(50_000, n_total)
    n_val   = min(10_000, max(0, n_total - n_train))

    y_flat = labels.reshape(-1)

    # Sample pixel indices (stratified where possible)
    try:
        from sklearn.model_selection import train_test_split

        all_idx = np.arange(n_total)
        if n_total > n_train + n_val:
            sample_frac = (n_train + n_val) / n_total
            _, idx_sub = train_test_split(
                all_idx,
                test_size=sample_frac,
                stratify=y_flat,
                random_state=42,
            )
        else:
            idx_sub = all_idx

        y_sub = y_flat[idx_sub]
        if len(idx_sub) > n_train and n_val > 0:
            val_frac = n_val / len(idx_sub)
            train_idx, val_idx = train_test_split(
                idx_sub,
                test_size=val_frac,
                stratify=y_sub,
                random_state=42,
            )
        else:
            train_idx = val_idx = idx_sub

    except Exception:
        rng = np.random.default_rng(42)
        perm = rng.permutation(n_total)
        train_idx = perm[:n_train]
        val_idx   = perm[n_train:n_train + n_val]

    # Stack features only for selected pixel indices → (n_samples, 8)
    def _gather(idx: np.ndarray) -> np.ndarray:
        cols_arr = [p.reshape(-1)[idx] for p in planes]
        X = np.stack(cols_arr, axis=-1).astype(np.float32)
        return np.where(np.isfinite(X), X, np.float32(0.0))

    X_train = _gather(train_idx)
    y_train = y_flat[train_idx]
    X_val   = _gather(val_idx)
    y_val   = y_flat[val_idx]

    print(
        f"[classifier] Training on {len(X_train):,} samples, "
        f"validating on {len(X_val):,} samples …"
    )

    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=15,
        n_jobs=-1,
        class_weight="balanced",
        random_state=42,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_val)
    report_str = classification_report(
        y_val,
        y_pred,
        target_names=[CLASS_NAMES.get(i, str(i)) for i in range(5)],
        labels=list(range(5)),
        zero_division=0,
    )
    print(report_str)

    acc = float(accuracy_score(y_val, y_pred))
    per_class_f1 = {
        CLASS_NAMES[i]: float(f)
        for i, f in enumerate(
            f1_score(y_val, y_pred, average=None, labels=list(range(5)), zero_division=0)
        )
    }
    metrics = {
        "accuracy": acc,
        "per_class_f1": per_class_f1,
        "feature_importances": clf.feature_importances_.tolist(),
    }

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, MODEL_PATH)
    print(f"[classifier] Model saved → {MODEL_PATH}")

    return clf, metrics


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def classify_terrain(
    classifier,
    elevation: np.ndarray,
    slope:     np.ndarray,
    roughness: np.ndarray,
    profile:   dict,
) -> np.ndarray:
    """Classify the full DEM into 5 terrain classes → uint8 (H, W).

    Builds all 8 feature planes on the full array (needed for global
    normalization constants), then classifies in row strips of 500 to
    avoid a single (H×W, 8) float32 feature matrix in memory at once.
    """
    H, W = elevation.shape
    STRIP = 500

    print("[classifier] Building feature planes …")
    planes = _build_feature_planes(elevation, slope, roughness, profile)

    print("[classifier] Classifying in strips …")
    class_map = np.zeros((H, W), dtype=np.uint8)

    for r0 in range(0, H, STRIP):
        r1          = min(r0 + STRIP, H)
        strip_data  = np.stack([p[r0:r1] for p in planes], axis=-1)   # (rows, W, 8)
        n_rows_strip = r1 - r0
        X_strip     = strip_data.reshape(n_rows_strip * W, 8)
        X_strip     = np.where(np.isfinite(X_strip), X_strip, np.float32(0.0))
        preds       = classifier.predict(X_strip).astype(np.uint8)
        class_map[r0:r1] = preds.reshape(n_rows_strip, W)

    return class_map


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_classifier(path: Path = MODEL_PATH):
    """Load a serialised classifier from disk.  Returns None if unavailable."""
    try:
        return joblib.load(path)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def create_classification_map(class_map: np.ndarray, profile: dict) -> str:
    """Build a Plotly discrete heatmap of terrain classification.

    Returns an embeddable HTML string (no <html>/<body> wrapper,
    Plotly loaded via CDN).
    """
    stride    = max(1, class_map.shape[0] // 500)
    ds        = class_map[::stride, ::stride].astype(np.float32)
    n_rows_ds = ds.shape[0]
    n_cols_ds = ds.shape[1]

    # Axis ticks
    n_ticks  = 6
    y_ds_idx = [round(i * (n_rows_ds - 1) / (n_ticks - 1)) for i in range(n_ticks)]
    x_ds_idx = [round(i * (n_cols_ds - 1) / (n_ticks - 1)) for i in range(n_ticks)]

    y_ticktext: list[str] = []
    x_ticktext: list[str] = []
    for di in y_ds_idx:
        _, lat = _pixel_to_latlon(di * stride, 0, profile)
        y_ticktext.append(f"{lat:.2f}°")
    for di in x_ds_idx:
        lon, _ = _pixel_to_latlon(0, di * stride, profile)
        x_ticktext.append(f"{lon:.2f}°")

    # Stepped discrete colorscale: values 0–4 mapped to 5 colors
    n = len(CLASS_COLORS)
    colorscale: list = []
    for i, color in enumerate(CLASS_COLORS):
        colorscale.append([i / n, color])
        colorscale.append([(i + 1) / n, color])

    fig = go.Figure(data=go.Heatmap(
        z=ds,
        zmin=0,
        zmax=4,
        colorscale=colorscale,
        colorbar=dict(
            title="Class",
            tickvals=[0.4, 1.2, 2.0, 2.8, 3.6],
            ticktext=[CLASS_NAMES[i] for i in range(5)],
        ),
    ))

    fig.update_layout(
        template="plotly_dark",
        width=900,
        height=700,
        title="Terrain Classification Map",
        xaxis=dict(
            title="Longitude",
            tickvals=x_ds_idx,
            ticktext=x_ticktext,
        ),
        yaxis=dict(
            title="Latitude",
            tickvals=y_ds_idx,
            ticktext=y_ticktext,
            autorange="reversed",
        ),
    )

    return pio.to_html(fig, full_html=False, include_plotlyjs="cdn")


# ---------------------------------------------------------------------------
# Verification block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

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
        from core.landing_scorer import _synthetic_terrain
        elevation, slope, roughness, profile = _synthetic_terrain(shape=(500, 500))

    from core.landing_scorer import score_terrain

    rover = dict(
        mission_type="water_ice",
        power_source="rtg",
        max_slope_deg=15.0,
        min_flat_radius_m=300.0,
        priority=0.3,
    )
    safety, mission, final, top_sites = score_terrain(
        elevation, slope, roughness, profile, rover
    )

    clf, metrics = train_classifier(
        elevation, slope, roughness, profile,
        safety, mission, final_score=final,
    )

    print(f"\nAccuracy: {metrics['accuracy']:.4f}")
    print("Per-class F1:")
    for name, f1_val in metrics["per_class_f1"].items():
        print(f"  {name}: {f1_val:.4f}")

    class_map = classify_terrain(clf, elevation, slope, roughness, profile)

    print("\nClass distribution:")
    total = class_map.size
    for cls_id, cls_name in CLASS_NAMES.items():
        count = int(np.sum(class_map == cls_id))
        pct   = 100.0 * count / total
        print(f"  {cls_id}  {cls_name}: {count:,} px  ({pct:.1f}%)")

    _out_dir = Path(_project_root) / "outputs"
    _out_dir.mkdir(exist_ok=True)
    html      = create_classification_map(class_map, profile)
    _out_path = _out_dir / "classification_preview.html"
    _out_path.write_text(
        f"<html><body style='background:#111'>{html}</body></html>",
        encoding="utf-8",
    )
    print(f"\nPreview saved → {_out_path}")
    print(f"Model saved   → {MODEL_PATH}")
