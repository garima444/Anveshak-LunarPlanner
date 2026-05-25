"""
validation/test_dbscan_params.py — Test 4: DBSCAN Parameter Validation via k-Distance Elbow.

Validates that the hand-tuned eps=0.5 is consistent with the k-distance elbow method.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from core.anomaly_detector import (
    _compute_feature_planes,
    DBSCAN_EPS,
    DBSCAN_MIN_SAMPLES,
    N_SUBSAMPLE,
)


def _find_elbow(sorted_distances: np.ndarray) -> int:
    """Find elbow index using a normalised Kneedle-style method.

    The raw second-derivative approach fails when a handful of extreme outliers
    (e.g. crater-bottom pixels) sit at the head of the descending k-distance
    curve: those 5-10 points create a huge drop whose second derivative
    dominates, placing the elbow in the outlier region at index ~7.

    Fix: skip the top 1% (extreme outliers), normalise the remaining curve to
    [0,1]×[0,1], then find the point with maximum perpendicular distance from
    the straight line connecting the two endpoints (classic Kneedle criterion).
    """
    n = len(sorted_distances)
    if n < 3:
        return 0

    # Drop top-1% outliers (they cause the raw-second-derivative to misfire)
    skip = max(1, n // 100)
    working = sorted_distances[skip:]

    if len(working) < 3:
        return skip

    y = working.astype(np.float64)
    y_max, y_min = float(y[0]), float(y[-1])
    if y_max - y_min < 1e-10:
        return skip

    # Normalise y to [0, 1] (1 = highest distance, 0 = lowest)
    y_norm = (y - y_min) / (y_max - y_min)
    # Normalise x (position) to [0, 1]
    x_norm = np.linspace(0.0, 1.0, len(working))

    # Kneedle: perpendicular distance from the diagonal line y = 1 - x
    # (connects top-left corner (0,1) to bottom-right corner (1,0))
    dist_from_diag = np.abs(y_norm - (1.0 - x_norm))
    elbow_local = int(np.argmax(dist_from_diag))

    return skip + elbow_local


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 4] DBSCAN Parameter Validation — k-Distance Elbow Method")
    result = {"test_name": "DBSCAN Parameter Validation — k-Distance Elbow Method"}

    try:
        H, W = elevation.shape
        print(f"  Computing feature planes for {H}x{W} terrain ...")

        # Downsample if needed (mirror anomaly_detector logic)
        _MAX_SIDE = 2500
        ds_stride = max(1, max(H, W) // _MAX_SIDE)
        if ds_stride > 1:
            elev_in = elevation[::ds_stride, ::ds_stride]
            slope_in = slope[::ds_stride, ::ds_stride]
            rough_in = roughness[::ds_stride, ::ds_stride]
        else:
            elev_in, slope_in, rough_in = elevation, slope, roughness

        planes = _compute_feature_planes(elev_in, slope_in, rough_in)

        # Subsample exactly as detect_anomalies does
        rng = np.random.default_rng(42)
        H_ds, W_ds = planes[0].shape
        n_total = H_ds * W_ds
        n_samp = min(N_SUBSAMPLE, n_total)
        idx = rng.choice(n_total, size=n_samp, replace=False)

        X_raw = np.stack([p.reshape(-1)[idx] for p in planes], axis=-1).astype(np.float32)
        del planes
        X_raw = np.where(np.isfinite(X_raw), X_raw, np.float32(0.0))

        print(f"  Scaling {n_samp} samples ...")
        X_scaled = StandardScaler().fit_transform(X_raw).astype(np.float32)

        # k-distance computation
        print(f"  Computing k-distance (k={DBSCAN_MIN_SAMPLES}) ...")
        nbrs = NearestNeighbors(n_neighbors=DBSCAN_MIN_SAMPLES, algorithm="ball_tree")
        nbrs.fit(X_scaled)
        distances, _ = nbrs.kneighbors(X_scaled)
        k_distances = distances[:, -1]  # distance to k-th nearest neighbour

        sorted_distances = np.sort(k_distances)[::-1]  # descending

        # Find elbow
        elbow_idx = _find_elbow(sorted_distances)
        suggested_eps = float(sorted_distances[elbow_idx])

        print(f"  Current eps={DBSCAN_EPS}, suggested eps={suggested_eps:.4f} (elbow at index {elbow_idx})")

        # Run DBSCAN with current eps
        print(f"  Running DBSCAN with eps={DBSCAN_EPS} ...")
        labels_current = DBSCAN(
            eps=DBSCAN_EPS,
            min_samples=DBSCAN_MIN_SAMPLES,
            algorithm="ball_tree",
            n_jobs=1,
        ).fit_predict(X_scaled)
        clusters_current = len(set(labels_current) - {-1})

        # Run DBSCAN with suggested eps
        print(f"  Running DBSCAN with eps={suggested_eps:.4f} ...")
        labels_suggested = DBSCAN(
            eps=suggested_eps,
            min_samples=DBSCAN_MIN_SAMPLES,
            algorithm="ball_tree",
            n_jobs=1,
        ).fit_predict(X_scaled)
        clusters_suggested = len(set(labels_suggested) - {-1})

        eps_diff = abs(suggested_eps - DBSCAN_EPS)

        # Cluster size distributions (not just count)
        cluster_sizes_current = {}
        for label in set(labels_current) - {-1}:
            cluster_sizes_current[int(label)] = int((labels_current == label).sum())
        cluster_sizes_suggested = {}
        for label in set(labels_suggested) - {-1}:
            cluster_sizes_suggested[int(label)] = int((labels_suggested == label).sum())
        print(f"  Cluster sizes at current eps={DBSCAN_EPS}: {cluster_sizes_current}")
        print(f"  Cluster sizes at suggested eps={suggested_eps:.4f}: {cluster_sizes_suggested}")

        # Silhouette scores (sampled for speed; skip if only 1 cluster)
        sil_current = None
        sil_suggested = None
        try:
            from sklearn.metrics import silhouette_score
            if clusters_current >= 2:
                mask_c = labels_current != -1
                if mask_c.sum() >= 10:
                    n_sil = min(5000, mask_c.sum())
                    rng_sil = np.random.default_rng(0)
                    sil_idx = rng_sil.choice(np.where(mask_c)[0], size=n_sil, replace=False)
                    sil_current = float(silhouette_score(X_scaled[sil_idx], labels_current[sil_idx]))
            if clusters_suggested >= 2:
                mask_s = labels_suggested != -1
                if mask_s.sum() >= 10:
                    n_sil = min(5000, mask_s.sum())
                    rng_sil = np.random.default_rng(0)
                    sil_idx = rng_sil.choice(np.where(mask_s)[0], size=n_sil, replace=False)
                    sil_suggested = float(silhouette_score(X_scaled[sil_idx], labels_suggested[sil_idx]))
        except Exception as sil_err:
            print(f"  Silhouette score unavailable: {sil_err}")
        print(f"  Silhouette score — current eps: {sil_current}, suggested eps: {sil_suggested}")

        # PASS/WARN/FAIL
        # Tightened tolerance to 0.20 (was 0.35) in standardised feature space.
        # The original eps=0.18 was chosen by running the k-distance elbow on the
        # 80-90°S DEM feature space and selecting the knee point empirically.
        # Tolerance 0.20 allows small data-driven drift while flagging large deviations.
        if eps_diff <= 0.20:
            verdict = "PASS"
        elif eps_diff <= 0.40:
            verdict = "WARN"
        else:
            verdict = "FAIL"

        print(f"  |suggested - current| = {eps_diff:.4f} (pass threshold: <= 0.20)")
        print(f"  Clusters at current eps: {clusters_current}, at suggested: {clusters_suggested}")
        print(f"  Result: {verdict}")

        # k-distance elbow plot
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(sorted_distances, linewidth=1.2, color="steelblue", label="k-distance curve")
        ax.axvline(x=elbow_idx, color="red", linestyle="--", linewidth=1.5,
                   label=f"Elbow index = {elbow_idx}")
        ax.axhline(y=suggested_eps, color="red", linestyle="--", linewidth=1.5,
                   label=f"Suggested eps = {suggested_eps:.3f}")
        ax.axhline(y=DBSCAN_EPS, color="blue", linestyle="--", linewidth=1.5,
                   label=f"Current eps = {DBSCAN_EPS}")
        ax.set_xlabel("Points (sorted by distance, descending)")
        ax.set_ylabel("Distance to 10th nearest neighbour")
        ax.set_title(f"k-Distance Graph — DBSCAN eps Validation (k={DBSCAN_MIN_SAMPLES})")
        ax.legend()
        ax.annotate(f"Suggested eps = {suggested_eps:.3f}",
                    xy=(elbow_idx, suggested_eps),
                    xytext=(elbow_idx + len(sorted_distances) * 0.05, suggested_eps + 0.1),
                    arrowprops=dict(arrowstyle="->", color="red"),
                    color="red", fontsize=9)
        ax.annotate(f"Current eps = {DBSCAN_EPS}",
                    xy=(0, DBSCAN_EPS),
                    xytext=(len(sorted_distances) * 0.3, DBSCAN_EPS + 0.15),
                    color="blue", fontsize=9)
        plt.tight_layout()
        plot_path = Path(plots_dir) / "kdistance_elbow.png"
        plt.savefig(plot_path, dpi=150)
        plt.close()
        print(f"  Plot saved: {plot_path}")

        result.update({
            "n_samples": n_samp,
            "current_eps": DBSCAN_EPS,
            "suggested_eps": round(suggested_eps, 6),
            "eps_difference": round(eps_diff, 6),
            "elbow_index": elbow_idx,
            "clusters_at_current_eps": clusters_current,
            "clusters_at_suggested_eps": clusters_suggested,
            "cluster_sizes_current_eps": cluster_sizes_current,
            "cluster_sizes_suggested_eps": cluster_sizes_suggested,
            "silhouette_current_eps": round(sil_current, 4) if sil_current is not None else None,
            "silhouette_suggested_eps": round(sil_suggested, 4) if sil_suggested is not None else None,
            "result": verdict,
            "notes": (
                f"|suggested_eps - current_eps| = {eps_diff:.4f} (pass <= 0.20). "
                f"Clusters: current={clusters_current}, suggested={clusters_suggested}. "
                f"Silhouette: current={sil_current}, suggested={sil_suggested}."
            ),
        })

    except Exception as exc:
        import traceback
        result["result"] = "FAIL"
        result["notes"] = f"Exception: {exc}\n{traceback.format_exc()}"
        print(f"  FAIL: {exc}")

    out_path = Path(results_dir) / "dbscan_validation.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")

    return result


if __name__ == "__main__":
    from core.landing_scorer import _synthetic_terrain
    try:
        from core.terrain import load_terrain
        elev, sl, rough, prof = load_terrain()
    except Exception:
        elev, sl, rough, prof = _synthetic_terrain()
    Path("results").mkdir(exist_ok=True)
    Path("results/plots").mkdir(exist_ok=True)
    run(elev, sl, rough, prof, "results", "results/plots")
