"""
core/visualizer.py — Plotly-based terrain and mission plan visualisation.

Public API:
    create_mission_map(elevation, slope, final_score, top_sites, path,
                       path_stats, profile) -> str (HTML fragment)
    create_score_chart(top_sites) -> str (HTML fragment)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyproj
import rasterio.transform
import plotly.graph_objects as go
import plotly.io as pio

# ---------------------------------------------------------------------------
# CRS strings (same as landing_scorer.py — keeps this module self-contained)
# ---------------------------------------------------------------------------

_CRS_STERE = (
    "+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
    "+R=1737400 +units=m +no_defs"
)
_CRS_LONLAT = "+proj=longlat +R=1737400 +no_defs"

_TRANSFORMER: pyproj.Transformer | None = None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_transformer() -> pyproj.Transformer:
    global _TRANSFORMER
    if _TRANSFORMER is None:
        _TRANSFORMER = pyproj.Transformer.from_crs(
            _CRS_STERE, _CRS_LONLAT, always_xy=True
        )
    return _TRANSFORMER


def _pixel_to_latlon(row: int | float, col: int | float, profile: dict) -> tuple[float, float]:
    """Convert pixel (row, col) → (lon_deg, lat_deg)."""
    x, y = rasterio.transform.xy(profile["transform"], row, col)
    lon, lat = _get_transformer().transform(x, y)
    return float(lon), float(lat)


def _downsample(arr: np.ndarray, target: int = 500) -> tuple[np.ndarray, int]:
    """Downsample 2D array to ~target rows/cols. Returns (arr_ds, stride)."""
    stride = max(1, arr.shape[0] // target)
    return arr[::stride, ::stride], stride


def _build_axis_ticks(
    n_px_ds: int, stride: int, profile: dict, axis: str
) -> tuple[list[int], list[str]]:
    """Return (tickvals, ticktext) for ~6 evenly spaced positions.

    axis='row' → latitudes; axis='col' → longitudes.
    Tickvals are indices in downsampled space.
    """
    n_ticks = 6
    ds_indices = [round(i * (n_px_ds - 1) / (n_ticks - 1)) for i in range(n_ticks)]
    tickvals = ds_indices
    ticktext = []
    for ds_idx in ds_indices:
        px = ds_idx * stride
        if axis == "row":
            lon, lat = _pixel_to_latlon(px, 0, profile)
            ticktext.append(f"{lat:.2f}°")
        else:
            lon, lat = _pixel_to_latlon(0, px, profile)
            ticktext.append(f"{lon:.2f}°")
    return tickvals, ticktext


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_mission_map(
    elevation: np.ndarray,
    slope: np.ndarray,
    final_score: np.ndarray,
    top_sites: list[dict],
    path: list[tuple[int, int]] | None,
    path_stats: dict | None,
    profile: dict,
) -> str:
    """Build a Plotly mission map and return an embeddable HTML string.

    Layers:
      1. Elevation heatmap (visible by default)
      2. Slope overlay (toggleable)
      3. Landing score overlay (toggleable)
      4. Landing site markers (up to 3 tier traces)
      5. Rover path + start/goal markers (if path is not None)
      6. Path stats annotation (if path_stats is not None)

    Returns
    -------
    str
        HTML fragment (no <html>/<body> wrapper, Plotly loaded via CDN).
    """
    elev_ds, stride = _downsample(elevation)
    slope_ds, _     = _downsample(slope)
    score_ds, _     = _downsample(final_score)

    n_rows_ds = elev_ds.shape[0]
    n_cols_ds = elev_ds.shape[1]

    y_tickvals, y_ticktext = _build_axis_ticks(n_rows_ds, stride, profile, "row")
    x_tickvals, x_ticktext = _build_axis_ticks(n_cols_ds, stride, profile, "col")

    traces: list[go.BaseTraceType] = []

    # ---- 1. Elevation heatmap -----------------------------------------------
    traces.append(go.Heatmap(
        z=elev_ds,
        colorscale="thermal",
        name="Elevation (m)",
        colorbar=dict(title="Elev (m)", x=1.0),
        showscale=True,
    ))

    # ---- 2. Slope overlay ---------------------------------------------------
    traces.append(go.Heatmap(
        z=slope_ds,
        colorscale="hot",
        opacity=0.3,
        visible="legendonly",
        name="Slope (deg)",
        colorbar=dict(title="Slope (°)", x=1.08),
        showscale=True,
    ))

    # ---- 3. Score overlay ---------------------------------------------------
    traces.append(go.Heatmap(
        z=score_ds,
        colorscale="viridis",
        opacity=0.4,
        visible="legendonly",
        name="Landing Score",
        colorbar=dict(title="Score", x=1.16),
        showscale=True,
    ))

    # ---- 4. Landing site markers (3 tiers) ----------------------------------
    tier_defs = [
        # (filter_fn, label, symbol, color, size)
        (lambda s: s["rank"] == 1,           "Site #1 (Gold)",     "star",   "gold",        15),
        (lambda s: 2 <= s["rank"] <= 5,      "Sites #2-5",         "circle", "limegreen",   10),
        (lambda s: 6 <= s["rank"] <= 10,     "Sites #6-10",        "circle", "yellow",       8),
    ]

    for filter_fn, label, symbol, color, size in tier_defs:
        tier_sites = [s for s in top_sites if filter_fn(s)]
        if not tier_sites:
            continue

        xs = [s["pixel_col"] / stride for s in tier_sites]
        ys = [s["pixel_row"] / stride for s in tier_sites]
        hover = [
            (
                f"Rank: {s['rank']}<br>"
                f"Lat: {s['lat']:.3f}°<br>"
                f"Lon: {s['lon']:.3f}°<br>"
                f"Elevation: {s['elevation_m']:.0f} m<br>"
                f"Slope: {s['slope_deg']:.1f}°<br>"
                f"Score: {s['final_score']:.3f}<br>"
                f"{s['reasoning']}"
            )
            for s in tier_sites
        ]
        traces.append(go.Scatter(
            x=xs,
            y=ys,
            mode="markers",
            marker=dict(symbol=symbol, color=color, size=size,
                        line=dict(color="black", width=1)),
            name=label,
            text=hover,
            hovertemplate="%{text}<extra></extra>",
        ))

    # ---- 5. Rover path ------------------------------------------------------
    if path:
        path_x = [c / stride for r, c in path]
        path_y = [r / stride for r, c in path]

        traces.append(go.Scatter(
            x=path_x,
            y=path_y,
            mode="lines",
            line=dict(color="cyan", width=2),
            name="Rover Path",
            hoverinfo="skip",
        ))

        # Start marker
        traces.append(go.Scatter(
            x=[path_x[0]],
            y=[path_y[0]],
            mode="markers",
            marker=dict(symbol="triangle-up", color="lime", size=12,
                        line=dict(color="black", width=1)),
            name="Start",
            hovertemplate="Start<extra></extra>",
        ))

        # Goal marker
        traces.append(go.Scatter(
            x=[path_x[-1]],
            y=[path_y[-1]],
            mode="markers",
            marker=dict(symbol="star", color="red", size=12,
                        line=dict(color="black", width=1)),
            name="Goal",
            hovertemplate="Goal<extra></extra>",
        ))

    fig = go.Figure(data=traces)

    # ---- Layout -------------------------------------------------------------
    fig.update_layout(
        template="plotly_dark",
        width=900,
        height=900,
        title="Lunar South Pole — Mission Plan",
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

    # ---- 6. Path stats annotation -------------------------------------------
    if path_stats:
        km   = path_stats.get("total_distance_km", 0.0)
        hrs  = path_stats.get("estimated_time_hrs", 0.0)
        smax = path_stats.get("max_slope_deg", 0.0)
        smean = path_stats.get("mean_slope_deg", 0.0)
        fig.add_annotation(
            text=(
                f"Dist: {km:.1f} km | Time: {hrs:.1f} h | "
                f"Slope max/mean: {smax:.1f}°/{smean:.1f}°"
            ),
            xref="paper", yref="paper",
            x=0.99, y=0.01,
            xanchor="right", yanchor="bottom",
            showarrow=False,
            font=dict(size=11, color="white"),
            bgcolor="rgba(0,0,0,0.5)",
        )

    return pio.to_html(fig, full_html=False, include_plotlyjs="cdn")


def create_score_chart(top_sites: list[dict]) -> str:
    """Build a horizontal bar chart of safety vs mission scores.

    Returns
    -------
    str
        HTML fragment (no <html>/<body> wrapper, Plotly loaded via CDN).
    """
    # Sort ascending so rank 1 ends up at top of horizontal bar chart
    sites = sorted(top_sites, key=lambda s: s["rank"], reverse=True)

    y_labels = [f"#{s['rank']} ({s['lat']:.1f}°, {s['lon']:.1f}°)" for s in sites]
    safety_vals  = [s["safety_score"]  for s in sites]
    mission_vals = [s["mission_score"] for s in sites]

    fig = go.Figure(data=[
        go.Bar(
            y=y_labels,
            x=safety_vals,
            orientation="h",
            name="Safety Score",
            marker_color="#00B4D8",
        ),
        go.Bar(
            y=y_labels,
            x=mission_vals,
            orientation="h",
            name="Mission Score",
            marker_color="#FFD60A",
        ),
    ])

    fig.update_layout(
        template="plotly_dark",
        barmode="group",
        title="Top Landing Sites — Score Breakdown",
        width=700,
        height=450,
        xaxis_title="Score",
        yaxis_title="Site",
    )

    return pio.to_html(fig, full_html=False, include_plotlyjs="cdn")


# ---------------------------------------------------------------------------
# Demo / verification block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import webbrowser

    _project_root = str(Path(__file__).parent.parent)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

    # Try real terrain; fall back to synthetic
    try:
        from core.terrain import load_terrain
        elevation, slope, roughness, profile = load_terrain()
        demo_mode = False
    except Exception:
        from core.landing_scorer import _synthetic_terrain
        elevation, slope, roughness, profile = _synthetic_terrain()
        demo_mode = True

    from core.landing_scorer import score_terrain

    rover = dict(
        mission_type="water_ice",
        power_source="rtg",
        max_slope_deg=15.0,
        min_flat_radius_m=50.0,
        priority=0.3,
    )
    _, _, final_score, top_sites = score_terrain(
        elevation, slope, roughness, profile, rover
    )

    path, path_stats = None, None
    if len(top_sites) >= 5:
        from core.pathfinder import build_cost_grid, astar, compute_path_stats
        cost  = build_cost_grid(elevation, slope, profile["resolution_m"], rover["max_slope_deg"])
        start = (top_sites[0]["pixel_row"], top_sites[0]["pixel_col"])
        goal  = (top_sites[4]["pixel_row"], top_sites[4]["pixel_col"])
        path  = astar(cost, start, goal)
        if path:
            path_stats = compute_path_stats(path, slope, profile["resolution_m"], speed_kmh=0.5)

    map_html   = create_mission_map(elevation, slope, final_score, top_sites, path, path_stats, profile)
    chart_html = create_score_chart(top_sites)

    out_dir = Path(__file__).parent.parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "map_preview.html"
    out_path.write_text(
        f"<html><body style='background:#111'>{map_html}<br>{chart_html}</body></html>",
        encoding="utf-8",
    )
    print(f"Saved: {out_path}")
    webbrowser.open(out_path.as_uri())
