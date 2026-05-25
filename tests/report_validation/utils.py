"""
tests/report_validation/utils.py — Shared utilities for the Anveshak report
validation suite.

All section modules import from here.  Build this first.
"""

from __future__ import annotations

import base64
import gc
import io
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

# ── Matplotlib: force Agg BEFORE any pyplot import ──────────────────────────
import matplotlib
matplotlib.use("Agg")  # noqa: E402
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import Normalize


# ── Project paths ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent   # Z:/Anveshak
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "report_validation"
LOGS_DIR    = OUTPUT_ROOT / "logs"
IMAGES_DIR  = OUTPUT_ROOT / "images"


def ensure_dirs() -> None:
    """Create output directories (idempotent)."""
    for d in [LOGS_DIR, IMAGES_DIR]:
        d.mkdir(parents=True, exist_ok=True)


# ── Standard rover profiles ──────────────────────────────────────────────────
VIPER_PROFILE: dict = {
    "mission_type": "water_ice",
    "power_source": "solar",
    "max_slope_deg": 20.0,
    "min_flat_radius_m": 300.0,
    "wheel_radius_m": 0.25,
    "rover_mass_kg": 430.0,
    "wheel_width_m": 0.20,
    "n_wheels": 6,
    "speed_kmh": 0.6,
    "battery_wh": 450.0,
    "solar_panel_w": 50.0,
    "mission_day": 7.4,
    "slope_penalty_factor": 15.0,
    "psr_intent": "rim",
    "priority": 0.5,
}

RTG_PROFILE: dict = {
    **VIPER_PROFILE,
    "power_source": "rtg",
    "psr_intent": "enter",
    "battery_wh": 2000.0,
}

PRAGYAN_PROFILE: dict = {
    "mission_type": "water_ice",
    "power_source": "solar",
    "max_slope_deg": 12.0,
    "min_flat_radius_m": 200.0,
    "wheel_radius_m": 0.075,
    "rover_mass_kg": 26.0,
    "wheel_width_m": 0.05,
    "n_wheels": 6,
    "speed_kmh": 0.036,
    "battery_wh": 50.0,
    "solar_panel_w": 25.0,
    "slope_penalty_factor": 15.0,
    "psr_intent": "avoid",
    "priority": 0.3,
}

GEOLOGICAL_RTG_PROFILE: dict = {
    "mission_type": "geological",
    "power_source": "rtg",
    "max_slope_deg": 20.0,
    "min_flat_radius_m": 300.0,
    "wheel_radius_m": 0.25,
    "rover_mass_kg": 430.0,
    "wheel_width_m": 0.20,
    "n_wheels": 6,
    "speed_kmh": 0.5,
    "battery_wh": 2000.0,
    "slope_penalty_factor": 15.0,
    "psr_intent": "rim",
    "priority": 0.7,
}

# Preset definitions (mirrors test_combinations.py)
_PRESETS: dict[str, dict] = {
    "viper": {
        "max_slope_deg": 20.0, "min_flat_radius_m": 300.0,
        "wheel_radius_m": 0.25, "rover_mass_kg": 430.0,
        "wheel_width_m": 0.20, "n_wheels": 6,
        "speed_kmh": 0.6, "battery_wh": 450.0,
        "slope_penalty_factor": 15.0,
    },
    "pragyan": {
        "max_slope_deg": 12.0, "min_flat_radius_m": 200.0,
        "wheel_radius_m": 0.075, "rover_mass_kg": 26.0,
        "wheel_width_m": 0.05, "n_wheels": 6,
        "speed_kmh": 0.036, "battery_wh": 50.0,
        "slope_penalty_factor": 15.0,
    },
    "yutu2": {
        "max_slope_deg": 20.0, "min_flat_radius_m": 250.0,
        "wheel_radius_m": 0.15, "rover_mass_kg": 140.0,
        "wheel_width_m": 0.12, "n_wheels": 6,
        "speed_kmh": 0.2, "battery_wh": 52.0,
        "slope_penalty_factor": 15.0,
    },
    "custom": {
        "max_slope_deg": 15.0, "min_flat_radius_m": 400.0,
        "wheel_radius_m": 0.25, "rover_mass_kg": 200.0,
        "wheel_width_m": 0.20, "n_wheels": 6,
        "speed_kmh": 0.5, "battery_wh": 1000.0,
        "slope_penalty_factor": 15.0,
    },
}
_SOLAR_EXTRA: dict = {"solar_panel_w": 50.0, "mission_day": 7.4}


def make_rover_profile(
    mission_type: str,
    power_source: str,
    psr_intent: str,
    preset: str = "viper",
) -> dict:
    """Build a rover profile dict by merging a preset with mission parameters."""
    base = dict(_PRESETS.get(preset, _PRESETS["viper"]))
    base["mission_type"] = mission_type
    base["power_source"] = power_source
    base["psr_intent"] = psr_intent
    base["priority"] = 0.5
    if power_source == "solar":
        base.update(_SOLAR_EXTRA)
    else:
        base["battery_wh"] = 2000.0
    return base


# ── TeeOutput ────────────────────────────────────────────────────────────────

class TeeOutput:
    """Captures output to both terminal AND log file simultaneously."""

    def __init__(self, log_path: Path) -> None:
        self.terminal = sys.stdout
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = open(log_path, "w", encoding="utf-8")
        self.buffer: list[str] = []

    def write(self, message: str) -> None:
        # Write to terminal with encoding-safe fallback (Windows cp1252 can't
        # handle Unicode box-drawing chars — replace them rather than crash).
        try:
            self.terminal.write(message)
        except UnicodeEncodeError:
            enc = getattr(self.terminal, "encoding", "utf-8") or "utf-8"
            self.terminal.write(message.encode(enc, errors="replace").decode(enc))
        self.log.write(message)
        self.buffer.append(message)

    def flush(self) -> None:
        self.terminal.flush()
        self.log.flush()

    def close(self) -> None:
        self.log.close()

    def get_content(self) -> str:
        return "".join(self.buffer)

    # Context-manager support for safe stdout restoration
    def __enter__(self) -> "TeeOutput":
        sys.stdout = self
        return self

    def __exit__(self, *_: Any) -> None:
        sys.stdout = self.terminal
        self.close()


# ── Printing helpers ─────────────────────────────────────────────────────────

def print_section_header(title: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "═" * 60
    print()
    print(sep)
    print(f"  {title}")
    print(f"  Timestamp: {ts}")
    print(sep)
    print()


def print_result(
    name: str,
    passed: bool,
    value: Any = None,
    expected: Any = None,
    tolerance: Any = None,
) -> None:
    status = "✅ PASS" if passed else "❌ FAIL"
    line = f"  {status} | {name}"
    if value is not None:
        line += f": {value}"
    if expected is not None:
        line += f"  (expected: {expected}"
        if tolerance is not None:
            line += f" ±{tolerance}"
        line += ")"
    print(line)


# ── Terminal screenshot ───────────────────────────────────────────────────────

def save_terminal_screenshot(
    text_content: str,
    output_path: Path,
    title: str,
    figsize: tuple[float, float] = (14, 10),
) -> Path:
    """Render terminal output as a dark-themed PNG image."""
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("#1e1e1e")
    ax.set_facecolor("#1e1e1e")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Title bar
    title_bar = mpatches.FancyBboxPatch(
        (0, 0.95), 1, 0.05,
        boxstyle="square,pad=0",
        facecolor="#3c3c3c",
        edgecolor="none",
        transform=ax.transAxes,
    )
    ax.add_patch(title_bar)
    ax.text(
        0.5, 0.975, title,
        ha="center", va="center",
        color="#ffffff", fontsize=10,
        fontfamily="monospace", fontweight="bold",
        transform=ax.transAxes,
    )

    # Terminal content
    lines = text_content.strip().split("\n")
    max_lines = 45
    if len(lines) > max_lines:
        half = max_lines // 2
        lines = (
            lines[:half]
            + ["...", f"[{len(lines) - max_lines} lines omitted]", "..."]
            + lines[-half:]
        )

    line_height = 0.90 / max(len(lines), 1)

    for i, line in enumerate(lines):
        y = 0.93 - (i * line_height)
        if "PASS" in line or "✅" in line:
            color = "#4ec94e"
        elif "FAIL" in line or "❌" in line:
            color = "#f44747"
        elif "WARN" in line or "⚠" in line:
            color = "#ffcc02"
        elif line.startswith("=") or line.startswith("═") or line.startswith("─"):
            color = "#569cd6"
        elif "%" in line and any(c.isdigit() for c in line):
            color = "#ce9178"
        else:
            color = "#d4d4d4"

        ax.text(
            0.02, y, line[:120],
            ha="left", va="top",
            color=color,
            fontsize=7.5,
            fontfamily="monospace",
            transform=ax.transAxes,
        )

    plt.tight_layout(pad=0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="#1e1e1e")
    plt.close(fig)
    return output_path


# ── Terrain loading ───────────────────────────────────────────────────────────

def load_real_terrain_safe(
    shape: tuple[int, int] = (300, 300),
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict, bool]:
    """Try to load real NASA DEM; fall back to synthetic terrain on any failure.

    Returns
    -------
    elevation, slope, roughness, profile, is_real
    """
    # Attempt 1: load_terrain_by_region (explicit region key)
    try:
        from core.terrain import load_terrain_by_region
        elev, slope, rough, profile = load_terrain_by_region("south_pole_80_90")
        print("[utils] Real terrain loaded via load_terrain_by_region()")
        return elev, slope, rough, profile, True
    except Exception as exc:
        print(f"[utils] load_terrain_by_region failed: {exc}")

    # Attempt 2: load_terrain() with no args (validation_runner.py pattern)
    try:
        from core.terrain import load_terrain
        elev, slope, rough, profile = load_terrain()  # type: ignore[call-arg]
        print("[utils] Real terrain loaded via load_terrain()")
        return elev, slope, rough, profile, True
    except Exception as exc:
        print(f"[utils] load_terrain() failed: {exc}")

    # Fallback: synthetic terrain
    print(f"[utils] Using synthetic terrain ({shape[0]}×{shape[1]})")
    from core.landing_scorer import _synthetic_terrain
    elev, slope, rough, profile = _synthetic_terrain(shape=shape)
    return elev, slope, rough, profile, False


def build_lat_grid_safe(profile: dict) -> np.ndarray:
    """Return a (H, W) float32 latitude grid in decimal degrees.

    Uses the cached version if available, otherwise computes it.
    Falls back to a constant -85.0° grid on failure.
    """
    cached = profile.get("_lat_grid_cache")
    if cached is not None:
        return cached

    try:
        from core.landing_scorer import _build_lat_grid
        lg = _build_lat_grid(profile)
        profile["_lat_grid_cache"] = lg
        return lg
    except Exception as exc:
        print(f"[utils] _build_lat_grid failed: {exc}")

    H = int(profile.get("height", profile.get("width", 300)))
    W = int(profile.get("width", profile.get("height", 300)))
    return np.full((H, W), np.float32(-85.0))


# ── Map image helpers ─────────────────────────────────────────────────────────

def make_score_heatmap(
    score_array: np.ndarray,
    title: str,
    markers: list[dict] | None,
    output_path: Path,
    cmap: str = "RdYlGn",
    vmin: float = 0.0,
    vmax: float = 1.0,
) -> Path:
    """Save a 2-D score heatmap as PNG with optional point markers."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor("#0a0a1a")
    ax.set_facecolor("#0a0a1a")

    # Downsample very large arrays for PNG output
    arr = score_array
    if arr.shape[0] > 2000 or arr.shape[1] > 2000:
        step = max(arr.shape[0] // 1000, arr.shape[1] // 1000, 1)
        arr = arr[::step, ::step]

    im = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax, origin="upper")
    cbar = plt.colorbar(im, ax=ax, label="Score [0–1]")
    cbar.ax.yaxis.label.set_color("white")
    cbar.ax.tick_params(colors="white")

    ax.set_title(title, fontsize=11, color="white", pad=8)
    ax.set_xlabel("Column (pixel)", color="white")
    ax.set_ylabel("Row (pixel)", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444")

    for m in markers or []:
        r, c = m["pixel"]
        # Scale if downsampled
        if arr.shape != score_array.shape:
            step_r = score_array.shape[0] // arr.shape[0]
            step_c = score_array.shape[1] // arr.shape[1]
            r, c = r // step_r, c // step_c
        ax.scatter(
            c, r,
            marker=m.get("marker", "o"),
            color=m.get("color", "white"),
            s=m.get("size", 100),
            zorder=5,
            label=m.get("label", ""),
            edgecolors="black",
            linewidths=0.5,
        )

    if markers:
        legend = ax.legend(loc="upper right", fontsize=8, facecolor="#1a1a2e", labelcolor="white")

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="#0a0a1a")
    plt.close(fig)
    return output_path


def make_path_overlay(
    elevation: np.ndarray,
    path: list[tuple[int, int]] | None,
    start: tuple[int, int] | None,
    goal: tuple[int, int] | None,
    title: str,
    markers: list[dict] | None,
    output_path: Path,
) -> Path:
    """Save elevation heatmap with rover path overlaid."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor("#0a0a1a")
    ax.set_facecolor("#0a0a1a")

    arr = elevation
    if arr.shape[0] > 2000 or arr.shape[1] > 2000:
        step = max(arr.shape[0] // 1000, arr.shape[1] // 1000, 1)
        arr = arr[::step, ::step]

    im = ax.imshow(arr, cmap="terrain", origin="upper")
    cbar = plt.colorbar(im, ax=ax, label="Elevation (m)")
    cbar.ax.yaxis.label.set_color("white")
    cbar.ax.tick_params(colors="white")

    if path and len(path) > 1:
        # Downsample path if very long
        step = max(len(path) // 5000, 1)
        pth = path[::step]
        rows = [p[0] for p in pth]
        cols = [p[1] for p in pth]
        if arr.shape != elevation.shape:
            ds = max(elevation.shape[0] // arr.shape[0], 1)
            rows = [r // ds for r in rows]
            cols = [c // ds for c in cols]
        ax.plot(cols, rows, "w-", linewidth=1.5, alpha=0.85, label="Path")

    def _scale_px(r, c):
        if arr.shape == elevation.shape:
            return r, c
        ds = max(elevation.shape[0] // arr.shape[0], 1)
        return r // ds, c // ds

    if start:
        sr, sc = _scale_px(*start)
        ax.scatter(sc, sr, marker="^", color="#00ff00", s=200, zorder=5, label="Start", edgecolors="black")
    if goal:
        gr, gc_ = _scale_px(*goal)
        ax.scatter(gc_, gr, marker="*", color="gold", s=300, zorder=5, label="Goal", edgecolors="black")

    for m in markers or []:
        r, c = _scale_px(*m["pixel"])
        ax.scatter(
            c, r,
            marker=m.get("marker", "o"),
            color=m.get("color", "white"),
            s=m.get("size", 100),
            zorder=5,
            label=m.get("label", ""),
            edgecolors="black",
            linewidths=0.5,
        )

    ax.set_title(title, fontsize=11, color="white", pad=8)
    ax.set_xlabel("Column (pixel)", color="white")
    ax.set_ylabel("Row (pixel)", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444")

    ax.legend(loc="upper right", fontsize=8, facecolor="#1a1a2e", labelcolor="white")

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="#0a0a1a")
    plt.close(fig)
    return output_path


def make_comparison_table_png(
    headers: list[str],
    rows: list[list[str]],
    title: str,
    output_path: Path,
) -> Path:
    """Render a table as a matplotlib figure PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ncols = len(headers)
    nrows = len(rows)
    fig_w = max(ncols * 2.0, 10.0)
    fig_h = max(nrows * 0.55 + 2.0, 3.0)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor("#0a0a1a")
    ax.set_facecolor("#0a0a1a")
    ax.axis("off")

    if rows:
        table = ax.table(
            cellText=rows,
            colLabels=headers,
            loc="center",
            cellLoc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1, 1.6)

        for (r, c), cell in table.get_celld().items():
            text = str(cell.get_text().get_text())
            if r == 0:
                cell.set_facecolor("#1a237e")
                cell.set_text_props(color="white", fontweight="bold")
            elif "PASS" in text or "✅" in text:
                cell.set_facecolor("#1b5e20")
                cell.set_text_props(color="#a5d6a7")
            elif "FAIL" in text or "❌" in text:
                cell.set_facecolor("#b71c1c")
                cell.set_text_props(color="#ef9a9a")
            elif "WARN" in text or "⚠" in text or "PARTIAL" in text:
                cell.set_facecolor("#e65100")
                cell.set_text_props(color="#ffe0b2")
            elif "SKIP" in text or "N/A" in text:
                cell.set_facecolor("#37474f")
                cell.set_text_props(color="#b0bec5")
            else:
                bg = "#1a1a2e" if r % 2 == 0 else "#0d1b2e"
                cell.set_facecolor(bg)
                cell.set_text_props(color="#e0e0e0")
            cell.set_edgecolor("#333344")

    ax.set_title(title, fontsize=12, color="white", pad=15, fontweight="bold")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="#0a0a1a")
    plt.close(fig)
    return output_path


# ── Base64 helpers ────────────────────────────────────────────────────────────

def img_to_base64(path: Path) -> str:
    """Return base64-encoded PNG as a data: URI string."""
    if not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def fig_to_base64(fig: plt.Figure) -> str:
    """Save a matplotlib figure to a base64 data-URI string without a temp file."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("ascii")
    buf.close()
    return "data:image/png;base64," + encoded


# ── Section orchestration helpers ─────────────────────────────────────────────

def safe_run_section(
    mod: Any,
    elevation: np.ndarray,
    slope: np.ndarray,
    roughness: np.ndarray,
    profile: dict,
    out_dir: str,
) -> dict:
    """Run a section module's run() with full exception catching + timing."""
    t0 = time.perf_counter()
    try:
        result = mod.run(elevation, slope, roughness, profile, out_dir)
    except Exception:
        result = {
            "result": "FAIL",
            "test_name": getattr(mod, "__name__", str(mod)),
            "notes": traceback.format_exc(),
        }
    result.setdefault("result", "FAIL")
    result["_elapsed_s"] = round(time.perf_counter() - t0, 2)
    gc.collect()
    return result


def verdict_from_checks(checks: list[dict]) -> str:
    """Aggregate PASS/WARN/FAIL from a list of check dicts."""
    n = len(checks)
    if n == 0:
        return "WARN"
    n_pass = sum(1 for c in checks if c.get("result") == "PASS")
    if n_pass == n:
        return "PASS"
    if n_pass >= max(n // 2, 1):
        return "WARN"
    return "FAIL"


def make_check(name: str, ok: bool, value: Any = None, expected: Any = None) -> dict:
    """Create a standardised check record."""
    return {
        "check": name,
        "result": "PASS" if ok else "FAIL",
        "value": str(value) if value is not None else "",
        "expected": str(expected) if expected is not None else "",
    }
