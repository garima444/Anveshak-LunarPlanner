"""
validation/test_classifier_cv.py — Test 5: Random Forest Classifier 5-Fold Cross-Validation.

Uses synthetic terrain (always available, faster). Tests whether the classifier
generalises rather than memorising training data.
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
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedKFold

from core.landing_scorer import _synthetic_terrain, score_terrain
from core.terrain_classifier import CLASS_NAMES, _build_feature_planes, _build_labels

FEATURE_NAMES = [
    "elevation_norm",
    "slope_norm",
    "roughness_norm",
    "quality_mask",
    "local_mean_slope",
    "local_std_elevation",
    "slope_gradient",
    "lat_normalized",
]

ROVER_PROFILE = {
    "mission_type": "geological",
    "power_source": "rtg",
    "max_slope_deg": 15.0,
    "min_flat_radius_m": 300.0,
    "priority": 0.3,
}


def run(elevation, slope, roughness, profile, results_dir, plots_dir) -> dict:
    print("\n[Test 5] Random Forest Classifier 5-Fold Cross-Validation")
    result = {"test_name": "Random Forest Classifier 5-Fold Cross-Validation"}

    try:
        # Always use synthetic terrain for this test (faster, deterministic)
        print("  Generating synthetic terrain (300x300) for classifier test ...")
        syn_elev, syn_slope, syn_rough, syn_profile = _synthetic_terrain(shape=(300, 300))

        print("  Scoring synthetic terrain ...")
        safety, mission, final, _ = score_terrain(
            syn_elev, syn_slope, syn_rough, syn_profile, ROVER_PROFILE
        )

        print("  Building feature planes (8 features) ...")
        planes = _build_feature_planes(syn_elev, syn_slope, syn_rough, syn_profile)

        print("  Building labels ...")
        labels = _build_labels(syn_slope, syn_rough, safety, mission, final)

        H, W = syn_elev.shape
        n_total = H * W

        # Stack features: (n_total, 8)
        X_all = np.stack([p.ravel() for p in planes], axis=-1).astype(np.float32)
        X_all = np.where(np.isfinite(X_all), X_all, np.float32(0.0))
        y_all = labels.ravel()

        # Sample up to 50k pixels
        n_sample = min(50_000, n_total)
        rng = np.random.default_rng(42)

        # Stratified sampling
        try:
            from sklearn.model_selection import train_test_split
            if n_total > n_sample:
                _, idx_sample = train_test_split(
                    np.arange(n_total), test_size=n_sample / n_total,
                    stratify=y_all, random_state=42
                )
            else:
                idx_sample = np.arange(n_total)
        except Exception:
            idx_sample = rng.choice(n_total, size=n_sample, replace=False)

        X = X_all[idx_sample]
        y = y_all[idx_sample]
        print(f"  Using {len(X)} samples for CV. Class distribution: {dict(zip(*np.unique(y, return_counts=True)))}")

        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

        fold_accuracies = []
        fold_f1_scores = []
        fold_confusion_matrices = []

        for fold_idx, (train_idx, val_idx) in enumerate(skf.split(X, y)):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            clf_fold = RandomForestClassifier(
                n_estimators=100, max_depth=15, n_jobs=-1,
                class_weight="balanced", random_state=42
            )
            clf_fold.fit(X_train, y_train)
            y_pred = clf_fold.predict(X_val)

            acc = float(accuracy_score(y_val, y_pred))
            f1_per_class = f1_score(y_val, y_pred, average=None, labels=list(range(5)), zero_division=0)
            cm = confusion_matrix(y_val, y_pred, labels=list(range(5)))

            fold_accuracies.append(acc)
            fold_f1_scores.append(f1_per_class.tolist())
            fold_confusion_matrices.append(cm.tolist())

            print(f"    Fold {fold_idx+1}: accuracy={acc:.4f}")

        mean_accuracy = float(np.mean(fold_accuracies))
        std_accuracy = float(np.std(fold_accuracies))

        # Per-class F1 mean/std across folds
        fold_f1_arr = np.array(fold_f1_scores)  # (5, 5)
        per_class_f1 = {
            CLASS_NAMES[i]: {
                "mean": float(fold_f1_arr[:, i].mean()),
                "std": float(fold_f1_arr[:, i].std()),
            }
            for i in range(5)
        }

        print(f"  Mean accuracy: {mean_accuracy:.4f} ± {std_accuracy:.4f}")

        # Feature importances from final model trained on all samples
        clf_final = RandomForestClassifier(
            n_estimators=100, max_depth=15, n_jobs=-1,
            class_weight="balanced", random_state=42
        )
        clf_final.fit(X, y)
        importances = clf_final.feature_importances_.tolist()
        top3 = sorted(range(8), key=lambda i: importances[i], reverse=True)[:3]

        # Per-class F1 check: require >= 0.70 for all classes with >= 100 samples
        # CLASS_NAMES is a dict {int: str}, so iterate over items() not enumerate().
        class_sample_counts = dict(zip(*np.unique(y, return_counts=True)))
        per_class_f1_pass = True
        low_f1_classes = []
        for i in range(5):
            cname = CLASS_NAMES[i]   # e.g. "HAZARD_ZONE"
            n_samples_cls = int(class_sample_counts.get(i, 0))
            mean_f1 = per_class_f1[cname]["mean"]
            if n_samples_cls >= 100 and mean_f1 < 0.70:
                per_class_f1_pass = False
                low_f1_classes.append(f"{cname}(F1={mean_f1:.3f}, n={n_samples_cls})")
        if low_f1_classes:
            print(f"  WARNING: Low per-class F1: {low_f1_classes}")

        # PASS/WARN/FAIL
        if mean_accuracy >= 0.80 and std_accuracy <= 0.03 and per_class_f1_pass:
            verdict = "PASS"
        elif mean_accuracy >= 0.65 and std_accuracy <= 0.06:
            verdict = "WARN"
        else:
            verdict = "FAIL"

        print(f"  Result: {verdict}")

        # CV accuracy bar chart
        fig, ax = plt.subplots(figsize=(8, 5))
        folds = list(range(1, 6))
        ax.bar(folds, fold_accuracies, color="steelblue", edgecolor="black")
        ax.axhline(y=mean_accuracy, color="red", linestyle="--", linewidth=1.5,
                   label=f"Mean = {mean_accuracy:.3f}")
        ax.set_xticks(folds)
        ax.set_xticklabels([f"Fold {i}" for i in folds])
        ax.set_ylabel("Accuracy")
        ax.set_ylim(0, 1)
        ax.set_title("5-Fold CV Accuracy — Terrain Classifier")
        ax.legend()
        plt.tight_layout()
        cv_plot = Path(plots_dir) / "cv_accuracy.png"
        plt.savefig(cv_plot, dpi=150)
        plt.close()

        # Feature importance chart
        sorted_idx = sorted(range(8), key=lambda i: importances[i], reverse=True)
        sorted_names = [FEATURE_NAMES[i] for i in sorted_idx]
        sorted_vals = [importances[i] for i in sorted_idx]

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.barh(sorted_names, sorted_vals, color="mediumseagreen", edgecolor="black")
        ax.set_xlabel("Feature Importance")
        ax.set_title("Random Forest Feature Importances — Terrain Classifier")
        ax.invert_yaxis()
        plt.tight_layout()
        fi_plot = Path(plots_dir) / "feature_importance.png"
        plt.savefig(fi_plot, dpi=150)
        plt.close()

        print(f"  Plots saved: {cv_plot}, {fi_plot}")

        result.update({
            "n_samples": len(X),
            "class_sample_counts": {CLASS_NAMES[i]: int(class_sample_counts.get(i, 0)) for i in range(5)},
            "fold_accuracies": [round(a, 6) for a in fold_accuracies],
            "mean_accuracy": round(mean_accuracy, 6),
            "std_accuracy": round(std_accuracy, 6),
            "fold_f1_scores": fold_f1_scores,
            "per_class_f1": per_class_f1,
            "per_class_f1_pass": per_class_f1_pass,
            "low_f1_classes": low_f1_classes,
            "fold_confusion_matrices": fold_confusion_matrices,
            "feature_importances": {FEATURE_NAMES[i]: round(importances[i], 6) for i in range(8)},
            "top3_features": [FEATURE_NAMES[i] for i in top3],
            "result": verdict,
            "notes": (
                f"Mean accuracy={mean_accuracy:.4f} ± {std_accuracy:.4f}. "
                f"Per-class F1 pass={per_class_f1_pass}. "
                f"Top features: {[FEATURE_NAMES[i] for i in top3]}"
            ),
        })

    except Exception as exc:
        import traceback
        result["result"] = "FAIL"
        result["notes"] = f"Exception: {exc}\n{traceback.format_exc()}"
        print(f"  FAIL: {exc}")

    out_path = Path(results_dir) / "classifier_cv.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  Saved: {out_path}")

    return result


if __name__ == "__main__":
    Path("results").mkdir(exist_ok=True)
    Path("results/plots").mkdir(exist_ok=True)
    run(None, None, None, None, "results", "results/plots")
