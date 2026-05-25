"""
tests/report_validation/section_02_classifier_accuracy.py
──────────────────────────────────────────────────────────
Section 2: ML Terrain Classifier Accuracy
Proves the RandomForest classifier achieves ≥75 % accuracy
on synthetic terrain using 5-fold cross-validation.

Always runs on synthetic 300×300 terrain for speed and determinism.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np

from tests.report_validation.utils import (
    IMAGES_DIR,
    LOGS_DIR,
    GEOLOGICAL_RTG_PROFILE,
    TeeOutput,
    ensure_dirs,
    make_check,
    make_comparison_table_png,
    print_result,
    print_section_header,
    save_terminal_screenshot,
    verdict_from_checks,
)


# ═════════════════════════════════════════════════════════════════════════════
def run(elevation=None, slope=None, roughness=None, profile=None, out_dir=None) -> dict:
    """Run Section 2: ML Classifier Accuracy."""
    ensure_dirs()
    log_path = LOGS_DIR / "02_classifier_accuracy.txt"
    img_cm   = IMAGES_DIR / "02a_classifier_confusion_matrix.png"
    img_bar  = IMAGES_DIR / "02b_classifier_accuracy_bar.png"

    tee = TeeOutput(log_path)
    old_stdout = sys.stdout
    sys.stdout = tee

    checks: list[dict] = []
    images: list[str]  = []
    cv_data: dict = {}

    try:
        print_section_header("SECTION 2: ML TERRAIN CLASSIFIER ACCURACY")

        # Always use synthetic terrain — keeps runtime < 2 min
        from core.landing_scorer import _synthetic_terrain, score_terrain
        from core.terrain_classifier import (
            CLASS_NAMES,
            _build_feature_planes,
            _build_labels,
        )
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import (
            accuracy_score,
            confusion_matrix,
            f1_score,
        )
        from sklearn.model_selection import StratifiedKFold

        print("  Generating synthetic 300×300 terrain …")
        syn_elev, syn_slope, syn_rough, syn_profile = _synthetic_terrain(shape=(300, 300))
        safety, mission, final, _ = score_terrain(
            syn_elev, syn_slope, syn_rough, syn_profile, GEOLOGICAL_RTG_PROFILE
        )
        checks.append(make_check("score_terrain on synthetic", True))

        # ── Build feature matrix + labels ──────────────────────────────────
        print("  Building feature planes …")
        planes = _build_feature_planes(syn_elev, syn_slope, syn_rough, syn_profile)
        labels = _build_labels(syn_slope, syn_rough, safety, mission, final)

        X = np.stack([p.ravel().astype(np.float32) for p in planes], axis=-1)
        y = labels.ravel().astype(int)

        # Replace non-finite values
        X = np.where(np.isfinite(X), X, 0.0)

        # Class distribution
        classes, counts = np.unique(y, return_counts=True)
        print()
        print(f"  {'Class':<25} {'Count':>8}  {'%':>6}")
        print("  " + "─" * 44)
        for cls, cnt in zip(classes, counts):
            name = CLASS_NAMES.get(int(cls), f"Class{cls}")
            pct  = 100.0 * cnt / len(y)
            print(f"  {name:<25} {cnt:>8}  {pct:>5.1f}%")
        print()

        total_samples = len(y)
        checks.append(make_check("samples built", total_samples > 100, total_samples, "> 100"))

        # ── 5-fold cross-validation ────────────────────────────────────────
        print("─" * 60)
        print("  TEST 2.1: 5-Fold Cross-Validation")
        print("─" * 60)

        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        fold_accuracies: list[float] = []
        fold_f1_scores:  list[list[float]] = []
        fold_cms:        list[np.ndarray] = []
        all_y_true:      list[int] = []
        all_y_pred:      list[int] = []

        for fold_idx, (train_idx, val_idx) in enumerate(skf.split(X, y)):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            clf = RandomForestClassifier(
                n_estimators=100,
                max_depth=15,
                n_jobs=-1,
                random_state=42,
            )
            clf.fit(X_train, y_train)
            y_pred = clf.predict(X_val)

            acc = accuracy_score(y_val, y_pred)
            f1s = f1_score(y_val, y_pred, average=None, zero_division=0)
            cm  = confusion_matrix(y_val, y_pred, labels=list(range(5)))

            fold_accuracies.append(float(acc))
            fold_f1_scores.append(f1s.tolist())
            fold_cms.append(cm)
            all_y_true.extend(y_val.tolist())
            all_y_pred.extend(y_pred.tolist())

            print(f"    Fold {fold_idx + 1}: {acc * 100:.2f}%")

        mean_acc = float(np.mean(fold_accuracies))
        std_acc  = float(np.std(fold_accuracies))
        print(f"    ─────────────────────────────")
        print(f"    Mean CV: {mean_acc * 100:.2f}% ± {std_acc * 100:.2f}%")

        acc_ok = mean_acc >= 0.75
        print_result("5-fold CV accuracy ≥ 75%", acc_ok, f"{mean_acc*100:.2f}%", "≥ 75%")
        checks.append(make_check("CV accuracy ≥ 75%", acc_ok, f"{mean_acc*100:.2f}%", "≥ 75%"))

        cv_data = {
            "fold_accuracies": fold_accuracies,
            "mean_accuracy": mean_acc,
            "std_accuracy": std_acc,
        }

        # ── Feature importance ─────────────────────────────────────────────
        print()
        print("─" * 60)
        print("  TEST 2.2: Feature Importance (last fold classifier)")
        print("─" * 60)
        feature_names = [
            "elevation_norm", "slope_norm", "roughness_norm", "quality_mask",
            "local_mean_slope", "local_std_elev", "slope_gradient", "lat_norm",
        ]
        importances = clf.feature_importances_
        sorted_idx  = np.argsort(importances)[::-1]
        print()
        for rank, i in enumerate(sorted_idx[:5], 1):
            bar = "█" * int(importances[i] * 40)
            print(f"    {rank}. {feature_names[i]:<22}: {importances[i]*100:.1f}%  {bar}")

        # ── Per-class F1 summary ───────────────────────────────────────────
        print()
        print("─" * 60)
        print("  TEST 2.3: Per-Class F1 Score (mean across folds)")
        print("─" * 60)
        print()
        mean_f1_per_class: dict[str, float] = {}
        for cls_idx in range(5):
            name = CLASS_NAMES.get(cls_idx, f"Class{cls_idx}")
            vals = [fold_f1_scores[f][cls_idx] if cls_idx < len(fold_f1_scores[f]) else 0.0
                    for f in range(5)]
            mf1  = float(np.mean(vals))
            mean_f1_per_class[name] = mf1
            bar  = "█" * int(mf1 * 20)
            flag = "✅" if mf1 >= 0.50 else "⚠️"
            print(f"    {name:<22}: {mf1:.3f}  {bar}  {flag}")

        print()
        print("═" * 60)
        print(f"  CLASSIFIER ACCURACY RESULT")
        print(f"  Overall Accuracy (mean CV): {mean_acc*100:.2f}%")
        status_str = "✅ PASS" if acc_ok else "❌ FAIL"
        print(f"  Status: {status_str}")
        print("═" * 60)

    finally:
        sys.stdout = old_stdout
        tee.close()

    log_content = tee.get_content()

    # ── Generate terminal screenshot ──────────────────────────────────────────
    try:
        ss_path = IMAGES_DIR / "02_classifier_terminal.png"
        save_terminal_screenshot(log_content, ss_path, "Section 2: Classifier Accuracy — Anveshak")
        images.append(str(ss_path))
    except Exception as exc:
        print(f"[sec02] screenshot failed: {exc}")

    # ── Confusion matrix PNG ──────────────────────────────────────────────────
    try:
        import matplotlib.pyplot as plt
        from sklearn.metrics import ConfusionMatrixDisplay

        cm_total = confusion_matrix(all_y_true, all_y_pred, labels=list(range(5)))
        class_labels = [CLASS_NAMES[i] for i in range(5)]

        fig, ax = plt.subplots(figsize=(10, 8))
        fig.patch.set_facecolor("#0a0a1a")
        ax.set_facecolor("#0a0a1a")

        disp = ConfusionMatrixDisplay(confusion_matrix=cm_total, display_labels=class_labels)
        disp.plot(ax=ax, cmap="Blues", colorbar=True, xticks_rotation=30)
        ax.set_title(
            f"Terrain Classifier — Confusion Matrix\n"
            f"5-Fold Cross-Validation | Mean Accuracy: {mean_acc*100:.2f}%",
            fontsize=11, color="white",
        )
        ax.set_facecolor("#0a0a1a")
        ax.tick_params(colors="white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")
        fig.patch.set_facecolor("#0a0a1a")

        plt.tight_layout()
        fig.savefig(img_cm, dpi=150, bbox_inches="tight", facecolor="#0a0a1a")
        plt.close(fig)
        images.append(str(img_cm))
    except Exception as exc:
        print(f"[sec02] confusion matrix failed: {exc}")

    # ── Accuracy bar chart PNG ────────────────────────────────────────────────
    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor("#0a0a1a")
        ax.set_facecolor("#0a0a1a")

        if mean_f1_per_class:
            names  = list(mean_f1_per_class.keys())
            values = list(mean_f1_per_class.values())
            colors = ["#4caf50" if v >= 0.75 else "#ff9800" if v >= 0.50 else "#f44336"
                      for v in values]
            bars = ax.bar(names, values, color=colors, edgecolor="#555", linewidth=0.5)
            ax.axhline(0.75, color="#4fc3f7", linestyle="--", linewidth=1, label="0.75 target")
            ax.set_ylim(0, 1.05)
            ax.set_ylabel("Mean F1 Score", color="white")
            ax.set_title("Per-Class F1 Score (5-Fold CV)", color="white", fontsize=12)
            ax.tick_params(colors="white")
            plt.xticks(rotation=25, ha="right", color="white")
            for spine in ax.spines.values():
                spine.set_edgecolor("#444")
            ax.legend(facecolor="#1a1a2e", labelcolor="white")

        plt.tight_layout()
        fig.savefig(img_bar, dpi=150, bbox_inches="tight", facecolor="#0a0a1a")
        plt.close(fig)
        images.append(str(img_bar))
    except Exception as exc:
        print(f"[sec02] bar chart failed: {exc}")

    return {
        "test_name": "Section 2: ML Classifier Accuracy",
        "result": verdict_from_checks(checks),
        "notes": (
            f"Mean CV accuracy: {cv_data.get('mean_accuracy', 0)*100:.2f}% | "
            f"{sum(1 for c in checks if c['result']=='PASS')}/{len(checks)} checks"
        ),
        "passed": sum(1 for c in checks if c["result"] == "PASS"),
        "total": len(checks),
        "checks": checks,
        "cv_data": cv_data,
        "images": images,
        "log": str(log_path),
    }


if __name__ == "__main__":
    ensure_dirs()
    result = run()
    print(f"\nSection result: {result['result']}")
    print(f"Passed: {result['passed']}/{result['total']}")
