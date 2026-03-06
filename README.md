# Anveshak — Lunar South Pole Mission Planner

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-ML-F7931E?style=flat&logo=scikit-learn&logoColor=white)
![Plotly](https://img.shields.io/badge/Plotly-Interactive_Maps-3F4F75?style=flat&logo=plotly&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)

**Multi-Resolution Terrain Fusion and ML-Based Adaptive Landing Site Selection for Lunar South Pole Rover Missions**

Anveshak is a web-based mission planning system that ingests NASA LOLA Digital Elevation Models of the lunar south pole (80–90°S), fuses multi-resolution terrain data, and uses machine learning to rank safe landing sites and plan energy-optimal rover traversal paths. Validated against NASA's Artemis III candidate sites and the Chandrayaan-3 landing zone.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Installation](#installation)
- [NASA Data Files](#nasa-data-files)
- [Running the Project](#running-the-project)
- [Demo Mode](#demo-mode)
- [API Reference](#api-reference)
- [Results](#results)
- [Screenshots](#screenshots)
- [Citation](#citation)

---

## System Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │              ANVESHAK SYSTEM                 │
                        └─────────────────────────────────────────────┘

  ┌──────────────────┐     ┌─────────────────────────────────────────────────┐
  │  NASA LOLA DEMs  │     │                  core/ modules                  │
  │  ─────────────── │     │                                                 │
  │  5m  ldem_87s    │────▶│  terrain.py         multi_res_fusion.py         │
  │  10m LDEM_85S    │     │  ┌─────────────┐    ┌──────────────────────┐   │
  │  20m LDEM_80S    │     │  │ load_terrain│    │ fuse 5m+10m+20m DEMs │   │
  └──────────────────┘     │  │ elevation   │    │ quality-weighted avg │   │
                           │  │ slope       │    └──────────────────────┘   │
                           │  │ roughness   │                                │
                           │  └──────┬──────┘                               │
                           │         │                                       │
                           │         ▼                                       │
                           │  ┌─────────────────┐   ┌────────────────────┐  │
                           │  │ terrain_         │   │ anomaly_detector   │  │
                           │  │ classifier.py    │   │ ────────────────── │  │
                           │  │ Random Forest    │   │ DBSCAN clustering  │  │
                           │  │ 5 terrain classes│   │ StandardScaler     │  │
                           │  │ 99.17% accuracy  │   │ 4 anomaly types    │  │
                           │  └────────┬─────────┘   └────────┬───────────┘  │
                           │           │                       │              │
                           │           ▼                       ▼              │
                           │  ┌──────────────────────────────────────────┐   │
                           │  │           landing_scorer.py              │   │
                           │  │  safety_score × (1-priority)             │   │
                           │  │  + mission_score × priority              │   │
                           │  │  → top 10 candidate sites                │   │
                           │  └────────────────┬─────────────────────────┘   │
                           │                   │                              │
                           │                   ▼                              │
                           │  ┌──────────────────────────────────────────┐   │
                           │  │           pathfinder.py                  │   │
                           │  │  A* on slope cost grid                   │   │
                           │  │  energy_model.py (Wh budget)             │   │
                           │  │  → path + path_stats                     │   │
                           │  └────────────────┬─────────────────────────┘   │
                           │                   │                              │
                           │                   ▼                              │
                           │  ┌───────────────────────┐  ┌───────────────┐   │
                           │  │   mission_advisor.py  │  │ visualizer.py │   │
                           │  │   8-section report    │  │ Plotly maps   │   │
                           │  │   feasibility rating  │  │ dark theme    │   │
                           │  └───────────────────────┘  └───────────────┘   │
                           └─────────────────────────────────────────────────┘
                                                  │
                                    ┌─────────────▼──────────────┐
                                    │       main.py (FastAPI)     │
                                    │  GET  /           → UI      │
                                    │  GET  /health     → status  │
                                    │  GET  /demo       → demo    │
                                    │  POST /analyze    → JSON    │
                                    └─────────────────────────────┘
                                                  │
                                    ┌─────────────▼──────────────┐
                                    │   Browser (HTML/JS/CSS)     │
                                    │   Interactive Plotly map    │
                                    │   Landing site rankings     │
                                    │   Mission report            │
                                    └─────────────────────────────┘
```

---

## Features

- **Multi-resolution DEM fusion** — combines 5 m, 10 m, and 20 m LOLA DEMs into a single quality-weighted terrain model
- **Random Forest terrain classifier** — 5 terrain classes at 99.17% accuracy (SAFE_LANDING, TRAVERSE_CORRIDOR, RISKY_LANDING, HAZARD_ZONE, SCIENCE_TARGET)
- **Weighted landing site scorer** — configurable safety/science trade-off with rover-specific constraints
- **A\* path planner** — slope-aware pathfinding with energy budget modelling (Wh)
- **Anomaly detector** — DBSCAN clustering on 100k terrain samples identifies PSR proxies and elevation anomalies
- **Mission advisor** — generates 8-section mission report with feasibility rating (NOMINAL / MARGINAL / HIGH_RISK)
- **Interactive web UI** — Plotly dark-theme maps, toggleable layers, form-driven rover profiles
- **Demo mode** — fully functional with synthetic craters, no NASA files required

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web framework | FastAPI 0.115 + Uvicorn |
| ML | scikit-learn (Random Forest, DBSCAN) |
| Geospatial | rasterio + GDAL (via conda-forge) |
| Numerics | NumPy, SciPy |
| Visualisation | Plotly 6.0 |
| Templating | Jinja2 |
| Runtime | Python 3.11, Conda |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/anveshak.git
cd anveshak
```

### 2. Create the conda environment

> **Windows note:** rasterio requires a pre-built GDAL. Use conda-forge — do **not** pip-install rasterio on Windows.

```bash
conda create -n anveshak python=3.11 rasterio numpy scipy -c conda-forge
conda activate anveshak
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. (Optional) Add NASA data files

See [NASA Data Files](#nasa-data-files) below. Skip this step to run in [Demo Mode](#demo-mode).

---

## NASA Data Files

Place all files under `data/dem/` as shown:

```
data/
└── dem/
    ├── DEM_5m/
    │   ├── ldem_87s_5mpp.tif          (3.3 GB — elevation, 5 m/px, 87–90°S)
    │   ├── ldem_87s_5mpp_hillshade.tif
    │   └── dem_5m_slope.tif
    ├── DEM_10m/
    │   ├── LDEM_85S_10M.JP2           (220 MB — elevation, 10 m/px, 85–90°S)
    │   ├── LDEC_85S_10M.JP2           (slope, 10 m/px)
    │   ├── LDEM_85S_10M_JP2.LBL
    │   └── LDEC_85S_10M_JP2.LBL
    └── DEM_20M/
        ├── LDEM_80S_20M.JP2           (255 MB — elevation, 20 m/px, 80–90°S)
        ├── LDEC_80S_20M.JP2           (slope, 20 m/px)
        ├── LDEM_80S_20M_JP2.LBL
        └── LDEC_80S_20M_JP2.LBL
```

All files are **free public data** from the NASA Lunar Reconnaissance Orbiter (LRO) LOLA instrument, archived at the PDS Geosciences Node.

### Download URLs

**PDS Geosciences Node (LOLA GDR products):**
```
https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/
```

| File | Direct URL |
|------|-----------|
| `ldem_87s_5mpp.tif` | `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldem_87s_5mpp.tif` |
| `ldem_87s_5mpp_hillshade.tif` | `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldem_87s_5mpp_hillshade.tif` |
| `LDEM_85S_10M.JP2` | `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/jp2/LDEM_85S_10M.JP2` |
| `LDEC_85S_10M.JP2` | `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/jp2/LDEC_85S_10M.JP2` |
| `LDEM_80S_20M.JP2` | `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/jp2/LDEM_80S_20M.JP2` |
| `LDEC_80S_20M.JP2` | `https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/jp2/LDEC_80S_20M.JP2` |

> If a URL returns 404, browse the PDS node directly at:
> **https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/**
> or search the PDS at **https://pds.nasa.gov/datasearch/subscription-service/SS-Release.shtml**

### Preprocessing

After downloading, run the preprocessing pipeline once to generate derived products:

```bash
python preprocessing.py
```

This reprojects the JP2 files to Polar Stereographic (Moon 2000), computes the slope raster for the 5 m DEM, and writes `data/processed_dem.tif`.

---

## Running the Project

```bash
conda activate anveshak
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** in your browser.

On startup, terrain is loaded asynchronously in the background. Check load status at:
```
GET http://localhost:8000/health
```

---

## Demo Mode

No NASA files needed. The system automatically falls back to a synthetic terrain (500 × 500 Gaussian crater field) if no DEM files are found.

```bash
# Start server as normal
uvicorn main:app --reload

# Trigger a demo analysis via the browser or curl:
curl http://localhost:8000/demo
```

The demo runs a full analysis pipeline — terrain scoring, path planning, anomaly detection, mission report — on synthetic data so you can explore the UI without downloading gigabytes of DEM files.

---

## API Reference

### `GET /`
Browser UI with rover profile form.

### `GET /health`
```json
{ "status": "ok", "terrain_loaded": true }
```

### `GET /demo`
Runs a full analysis with default parameters (water_ice / RTG / slope ≤ 15°).

### `POST /analyze`
```json
{
  "rover_name": "Anveshak-1",
  "mission_type": "water_ice",
  "power_source": "rtg",
  "max_slope_deg": 15.0,
  "min_flat_radius_m": 300.0,
  "speed_kmh": 0.5,
  "priority": 0.3,
  "battery_wh": 1000.0
}
```

**mission_type:** `water_ice` | `geological` | `atmospheric`
**power_source:** `solar` | `rtg`
**priority:** 0.0 = maximum safety, 1.0 = maximum science value

Response fields: `top_sites`, `path_stats`, `anomalies`, `map_html`, `chart_html`, `mission_summary`, `report`

---

## Results

### Terrain Classification (80–90°S, 10 133 × 10 133 grid)

| Class | Coverage |
|-------|---------|
| TRAVERSE_CORRIDOR | 40.2% |
| SAFE_LANDING | 33.7% |
| RISKY_LANDING | 23.9% |
| HAZARD_ZONE | 2.2% |
| SCIENCE_TARGET | 0.001% |

Random Forest accuracy: **99.17%** | Model size: 13.7 MB

### Artemis III Candidate Site Validation

Scores at NASA's 13 Artemis III candidate regions (4 shown below). Profile A = geological / slope ≤ 20° / priority 0.6. Profile B = water_ice / slope ≤ 15° / priority 0.4.

| Site | Safety A | Mission A | Final A | Safety B | Mission B | Final B | Class |
|------|----------|-----------|---------|----------|-----------|---------|-------|
| Shackleton Ridge | 0.655 | 0.210 | 0.388 | 0.605 | 0.599 | **0.603** | SAFE_LANDING |
| Faustini Crater | 0.000 | 0.643 | 0.000 | 0.000 | 0.372 | 0.000 | RISKY_LANDING |
| Haworth Edge | 0.402 | 0.574 | 0.505 | 0.287 | 0.278 | 0.284 | RISKY_LANDING |
| Nobile Rim | 0.423 | 0.553 | 0.501 | 0.314 | 0.124 | 0.257 | TRAVERSE_CORRIDOR |

Key findings:
- **Shackleton Ridge** ranked highest in water-ice profile (final = 0.603) — consistent with NASA's designation as the primary Artemis III target.
- **Faustini Crater** correctly scores zero safety (interior is permanently shadowed, high slope walls) while retaining high science value.
- System alignment with NASA mission planning consensus is strong for the 80–90°S coverage zone.

### Chandrayaan-3 Validation

Chandrayaan-3 (–69.37°S) is outside the system's 80–90°S coverage zone by design. The system targets the extreme polar region where water-ice probability and PSR coverage are highest. The nearest system-recommended site is 526 km from the C3 landing point — a scientifically meaningful separation between technological demonstration objectives (~70°S) and optimal ice-prospecting targets (>85°S).

---

## Screenshots

> Screenshots will be added after the first public deployment.

| View | Description |
|------|-------------|
| `outputs/map_preview.html` | Interactive terrain + landing site map |
| `outputs/classification_preview.html` | ML terrain classification overlay |
| `outputs/chandrayaan3_validation.html` | Artemis III and C3 validation report |

To regenerate all HTML outputs locally:
```bash
uvicorn main:app --reload
curl http://localhost:8000/demo
```

---

## Citation

If you use Anveshak in your research, please cite:

```bibtex
@article{anveshak2026,
  title   = {Multi-Resolution Terrain Fusion and ML-Based Adaptive Landing Site
             Selection for Lunar South Pole Rover Missions},
  author  = {<Author(s)>},
  journal = {<Journal / Conference>},
  year    = {2026},
  note    = {Preprint / Under review}
}
```

---

## License

MIT — see `LICENSE` for details.

---

*Built with NASA LOLA data. All DEM products courtesy of the NASA LRO LOLA Science Team and the PDS Geosciences Node.*
