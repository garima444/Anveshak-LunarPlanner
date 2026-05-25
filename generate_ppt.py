"""
generate_ppt.py
Generates Anveshak MidTerm VIII Semester PPT, matching ProjectPPT(MidTerm).pptx format.
Run:  python generate_ppt.py
Output: Anveshak_MidTerm_PPT.pptx
"""
import sys, os, copy
sys.stdout.reconfigure(encoding="utf-8")

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml import parse_xml
from lxml import etree

# ── Load template ─────────────────────────────────────────────────────────────
TEMPLATE = "ProjectPPT(MidTerm).pptx"
prs = Presentation(TEMPLATE)

SW = prs.slide_width
SH = prs.slide_height

LAYOUT_TITLE   = prs.slide_layouts[0]   # "Title Slide"
LAYOUT_CONTENT = prs.slide_layouts[1]   # "Title and Content"

# ── Constants ─────────────────────────────────────────────────────────────────
W = Inches
P = Pt

# ── Helper: clone a slide XML (preserves background/theme) ───────────────────
def clone_content_slide(prs):
    """Clone the first content-layout slide (index 2) and append to prs."""
    src = prs.slides[2]
    slide = prs.slides.add_slide(LAYOUT_CONTENT)
    # Remove auto-added shapes from layout
    sp_tree = slide.shapes._spTree
    for el in list(sp_tree):
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag in ("sp", "pic", "graphicFrame", "grpSp", "cxnSp"):
            sp_tree.remove(el)
    # Deep-copy shapes from source (preserves placeholders with correct styling)
    for shape in src.shapes:
        sp_tree.append(copy.deepcopy(shape._element))
    return slide

# ── Helper: set title text ────────────────────────────────────────────────────
def set_title(slide, text):
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == 0:
            tf = ph.text_frame
            tf.clear()
            para = tf.paragraphs[0]
            run = para.add_run()
            run.text = text
            return
    # fallback: first shape named Title
    for shape in slide.shapes:
        if "Title" in shape.name and shape.has_text_frame:
            shape.text_frame.paragraphs[0].runs[0].text = text
            return

# ── Helper: set content placeholder with (level, text, bold) tuples ──────────
def set_content(slide, items):
    """
    items: list of (level, text)  or  (level, text, bold)
    level 0 = first bullet, level 1 = sub-bullet
    """
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == 1:
            tf = ph.text_frame
            tf.clear()
            for i, item in enumerate(items):
                level = item[0]
                text  = item[1]
                bold  = item[2] if len(item) > 2 else False
                if i == 0:
                    para = tf.paragraphs[0]
                else:
                    para = tf.add_paragraph()
                para.level = level
                run = para.add_run()
                run.text = text
                if bold:
                    run.font.bold = True
            return

# ── Helper: add image to slide ────────────────────────────────────────────────
def add_img(slide, path, left, top, width=None, height=None):
    if width and height:
        return slide.shapes.add_picture(path, W(left), W(top), W(width), W(height))
    elif width:
        return slide.shapes.add_picture(path, W(left), W(top), width=W(width))
    elif height:
        return slide.shapes.add_picture(path, W(left), W(top), height=W(height))
    return slide.shapes.add_picture(path, W(left), W(top))

# ── Helper: add a text box ────────────────────────────────────────────────────
def add_textbox(slide, text, left, top, width, height,
                size=18, bold=False, color=None,
                align=PP_ALIGN.LEFT, wrap=True, italic=False):
    txb = slide.shapes.add_textbox(W(left), W(top), W(width), W(height))
    tf = txb.text_frame
    tf.word_wrap = wrap
    para = tf.paragraphs[0]
    para.alignment = align
    run = para.add_run()
    run.text = text
    run.font.size = P(size)
    run.font.bold = bold
    run.font.italic = italic
    if color:
        run.font.color.rgb = RGBColor(*color)
    return txb

# ── Helper: add table ─────────────────────────────────────────────────────────
def add_table(slide, data, left, top, width, height,
              header_fill=(68,114,196), row_fill=(None,), font_size=12):
    rows = len(data)
    cols = len(data[0])
    tbl = slide.shapes.add_table(rows, cols, W(left), W(top), W(width), W(height))
    tbl_obj = tbl.table
    for r, row_data in enumerate(data):
        for c, cell_text in enumerate(row_data):
            cell = tbl_obj.cell(r, c)
            tf = cell.text_frame
            tf.word_wrap = True
            para = tf.paragraphs[0]
            para.alignment = PP_ALIGN.CENTER
            run = para.add_run()
            run.text = str(cell_text)
            run.font.size = P(font_size)
            run.font.bold = (r == 0)
            if r == 0:
                run.font.color.rgb = RGBColor(255, 255, 255)
                _set_cell_fill(cell, *header_fill)
            elif r % 2 == 1:
                _set_cell_fill(cell, 235, 241, 250)
    return tbl

def _set_cell_fill(cell, r, g, b):
    from pptx.oxml import parse_xml
    from pptx.oxml.ns import nsmap
    fill_xml = (
        '<a:solidFill xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f'<a:srgbClr val="{r:02X}{g:02X}{b:02X}"/>'
        '</a:solidFill>'
    )
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for child in list(tcPr):
        if child.tag.endswith('}solidFill') or child.tag.endswith('}gradFill') or child.tag.endswith('}noFill'):
            tcPr.remove(child)
    tcPr.append(parse_xml(fill_xml))

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 1 — COVER
# ══════════════════════════════════════════════════════════════════════════════
s1 = prs.slides[0]
for ph in s1.placeholders:
    if ph.placeholder_format.idx == 0:
        tf = ph.text_frame
        tf.clear()
        para = tf.paragraphs[0]
        run = para.add_run()
        run.text = "MID TERM VIII SEMESTER SYNOPSIS\nSession 2025–26"
        run.font.size = P(32)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 2 — PROJECT TITLE
# ══════════════════════════════════════════════════════════════════════════════
s2 = prs.slides[1]
for shape in s2.shapes:
    if not shape.has_text_frame:
        continue
    t = shape.text_frame.paragraphs[0].text
    tf = shape.text_frame
    if "NAME OF THE PROJECT" in t:
        tf.clear()
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = ("Multi-Resolution Terrain Fusion and ML-Based\n"
                  "Adaptive Landing Site Selection for\nLunar South Pole Rover Missions")
        r.font.size = P(24)
        r.font.bold = True
    elif "Team Member" in t or "Roll No" in t:
        tf.clear()
        lines = [
            ("Team Members:", True, 20),
            ("Garima (22CSU067)", False, 18),
            ("Garima Juneja (22CSU068)", False, 18),
            ("Aryan (22CSU031)", False, 18),
        ]
        for i, (txt, bold, sz) in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            run = para.add_run()
            run.text = txt
            run.font.bold = bold
            run.font.size = P(sz)
    elif "Supervisor" in t:
        tf.clear()
        lines = [
            ("Supervisors:", True, 20),
            ("Dr. Snehlata Sheoran", False, 18),
            ("Dr. Ankita Bhalla", False, 18),
        ]
        for i, (txt, bold, sz) in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            run = para.add_run()
            run.text = txt
            run.font.bold = bold
            run.font.size = P(sz)
    elif "DEPARTMENT" in t:
        tf.clear()
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = "Department of Computer Science and Engineering\nSchool of Engineering and Technology | The NorthCap University"
        r.font.size = P(18)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 3 — AGENDA
# ══════════════════════════════════════════════════════════════════════════════
s3 = prs.slides[2]
set_title(s3, "Agenda")
set_content(s3, [
    (0, "1.  Description of the Topic / Introduction",       True),
    (0, "2.  Feasibility Study",                             False),
    (0, "3.  Literature Review & Gap Analysis",               False),
    (0, "4.  Problem Statement & Objectives",                 False),
    (0, "5.  Tools / Platform Used",                          False),
    (0, "6.  Design Methodology",                             False),
    (0, "7.  Challenges and Issues Identified",               False),
    (0, "8.  Methodology & Implementation",                   False),
    (0, "9.  Testing and Performance Evaluation",             False),
    (0, "10. Outcomes",                                       False),
    (0, "11. Gantt Chart & Responsibility Chart",             False),
    (0, "12. Broader Impact / Research Paper Status",         False),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 4 — DESCRIPTION OF TOPIC
# ══════════════════════════════════════════════════════════════════════════════
s4 = prs.slides[3]
set_title(s4, "Description of the Topic")
set_content(s4, [
    (0, "What is Anveshak?",                                              True),
    (1, "Open-source, web-based ML mission planning system for lunar south pole rover operations"),
    (1, "Named after Sanskrit word for 'explorer' / 'investigator'"),
    (0, "Why the Lunar South Pole?",                                      True),
    (1, "Permanently Shadowed Regions (PSRs) may contain water ice — ISRU fuel, life support, construction"),
    (1, "Primary target: NASA Artemis, ISRO Chandrayaan-3, commercial landers"),
    (1, "Terrain challenges: slopes >20°, deep shadows, −173°C to +127°C temperature range"),
    (0, "The Problem with Current Tools",                                 True),
    (1, "Existing planning relies on proprietary GIS software & manual expert review"),
    (1, "No integrated, open, end-to-end system combining ML + scoring + pathfinding"),
    (0, "Anveshak's Approach",                                            True),
    (1, "Ingests NASA LRO LOLA DEM (80–90°S, 60 m/px) → scores sites → classifies terrain → plans paths → detects anomalies → generates advisory report"),
    (1, "All within 18–45 seconds on commodity hardware"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 5 — FEASIBILITY STUDY
# ══════════════════════════════════════════════════════════════════════════════
s5 = prs.slides[4]
set_title(s5, "Feasibility Study")
set_content(s5, [
    (0, "Technical Feasibility",                                          True),
    (1, "Full Python open-source stack: rasterio, NumPy, SciPy, scikit-learn, FastAPI, Plotly"),
    (1, "Peak RAM: 1.8 GB — within 16 GB workstation spec"),
    (1, "RF classifier: 50k samples trains in <60 sec; full inference in ~12 sec"),
    (1, "60 m/px downsampling: 9× memory reduction from native 20 m/px"),
    (0, "Operational Feasibility",                                        True),
    (1, "Browser-based — no client installation; accessible from any modern browser"),
    (1, "NASA LOLA DEM freely available from PDS Geosciences Node"),
    (1, "Server startup: ~12 sec DEM load; subsequent queries: 18–45 sec"),
    (0, "Economic Feasibility",                                           True),
    (1, "100% open-source licences (BSD, MIT) — zero software licensing cost"),
    (1, "Data: public domain (NASA PDS); Deployment: ~$15–25/month on cloud if needed"),
    (0, "Schedule Feasibility",                                           True),
    (1, "7 modules completed: Oct 2025 – Mar 2026 (one semester)"),
    (1, "Modular architecture enabled parallel development and incremental integration"),
    (1, "Research paper preparation: Mar – Apr 2026"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 6 — LITERATURE REVIEW
# ══════════════════════════════════════════════════════════════════════════════
s6 = prs.slides[5]
set_title(s6, "Existing Solutions / Literature Review")
set_content(s6, [
    (0, "A. Lunar DEM & Terrain Analysis",                                True),
    (1, "Smith et al. [5]: LOLA instrument, 10 cm vertical precision — basis for LDEM_80S_20M product"),
    (1, "Zuber et al. [6]: Shackleton Crater topography, volatile trapping evidence"),
    (1, "Deutsch et al. [7]: Ice mass estimates using LOLA + Mini-RF + Diviner"),
    (0, "B. Landing Site Selection",                                      True),
    (1, "Golombek et al. [8]: Multi-criteria scoring for MER (safety + science merit) — direct conceptual basis"),
    (1, "Flahaut et al. [9]: Human lunar landing site ROIs — slope + illumination + science maps"),
    (0, "C. ML for Terrain Classification",                               True),
    (1, "Bue & Stepinski [3]: SVM-based geomorphic unit classification from Martian DEM"),
    (1, "Palafox et al. [11]: CNNs for volcanic feature detection on Mars"),
    (1, "Shwartz-Ziv & Armon [19]: Random Forests match/exceed deep learning on tabular data"),
    (0, "D. Path Planning",                                               True),
    (1, "Stentz [13]: D* algorithm for dynamic replanning (onboard use)"),
    (1, "Ferguson & Stentz [14]: Field D* — interpolated movement on grid representations"),
    (1, "A* with Euclidean heuristic — optimal for known terrain (Anveshak)"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 7 — GAPS IN EXISTING SOLUTIONS
# ══════════════════════════════════════════════════════════════════════════════
s7 = prs.slides[6]
set_title(s7, "Gaps in Existing Solutions")
set_content(s7, [
    (0, "Gap 1: No Integrated Open-Source End-to-End Pipeline",           True),
    (1, "Existing tools address sub-problems in isolation (GIS tools, path planners, ML classifiers)"),
    (1, "None combine DEM ingestion + ML + scoring + pathfinding + anomaly detection + advisory"),
    (0, "Gap 2: Annotation Bottleneck for Supervised Learning",           True),
    (1, "Prior ML terrain classifiers require expensive manual annotation"),
    (1, "Anveshak's auto-labelling from scoring pipeline eliminates this entirely"),
    (0, "Gap 3: No Mission-Profile Parameterisation",                     True),
    (1, "Existing scoring tools use fixed weights; same site = same score regardless of mission objective"),
    (1, "Anveshak adapts to: water-ice prospecting / geological survey / tech demonstration"),
    (0, "Gap 4: No Public Validation Against Artemis III Sites",          True),
    (1, "Published tools not validated against NASA's current planning consensus sites"),
    (0, "Gap 5: Closed-Source, Inaccessible Implementations",             True),
    (1, "NASA RSVP and ALHAT — closed-source, not reproducible by broader research community"),
    (1, "Anveshak: fully open-source, reproducible, extensible baseline"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 8 — PROBLEM STATEMENT
# ══════════════════════════════════════════════════════════════════════════════
s8 = prs.slides[7]
set_title(s8, "Problem Statement")
set_content(s8, [
    (0, "Core Problem",                                                   True),
    (1, "Given NASA LRO LOLA DEM data (80–90°S), design and implement an open-source, web-deployable mission planning system that:"),
    (0, "Functional Requirements",                                        True),
    (1, "→  Automatically ingest and process terrain data (slope, roughness, quality mask)"),
    (1, "→  Apply ML to classify terrain and detect science targets"),
    (1, "→  Score candidate landing sites per configurable mission profile"),
    (1, "→  Plan energy-efficient traverse paths on 10,133×10,133 pixel grids"),
    (1, "→  Generate plain-English mission advisory reports"),
    (0, "Non-Functional Constraints",                                     True),
    (1, "✓  Correctness: validated against NASA Artemis III expert assessments"),
    (1, "✓  Performance: 18–45 sec end-to-end on 16 GB commodity hardware"),
    (1, "✓  Accessibility: no specialist GIS/ML expertise required"),
    (1, "✓  Reproducibility: open data + open-source software only"),
    (1, "✓  Extensibility: ready for multi-modal data integration"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 9 — OBJECTIVES
# ══════════════════════════════════════════════════════════════════════════════
s9 = prs.slides[8]
set_title(s9, "Objectives")
set_content(s9, [
    (0, "1.  DEM Pipeline", True),
    (1, "Automated ingestion of LDEM_80S_20M.JP2; slope, roughness, quality mask at 60 m/px"),
    (0, "2.  Multi-Criteria Scoring", True),
    (1, "Parameterised by mission profile (water-ice / geological / tech-demo); safety–science tradeoff"),
    (0, "3.  ML Terrain Classifier", True),
    (1, "Random Forest, 99.17% accuracy, auto-labelled — no manual annotation"),
    (0, "4.  A* Pathfinder", True),
    (1, "Terrain-aware exponential slope cost; 10,133×10,133 grid; 2M iteration budget"),
    (0, "5.  Science Target Detection", True),
    (1, "DBSCAN anomaly detector — no pre-specified cluster count"),
    (0, "6.  Integrated Web Application", True),
    (1, "FastAPI backend + interactive Plotly frontend + 8-section mission advisory report"),
    (0, "7.  Validation", True),
    (1, "4 NASA Artemis III candidate sites + Chandrayaan-3 landing site — strong alignment confirmed"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 10 — TOOLS / PLATFORM USED
# ══════════════════════════════════════════════════════════════════════════════
s10 = prs.slides[9]
set_title(s10, "Tools / Platform Used")
set_content(s10, [
    (0, "Backend & Scientific Computing",                                 True),
    (1, "Python 3.11 (Conda: lunar-planner)  |  FastAPI 0.100+  |  Uvicorn"),
    (1, "rasterio 1.3+ (DEM I/O)  |  NumPy 1.24+  |  SciPy 1.10+  |  pyproj 3.4+"),
    (1, "scikit-learn 1.3+ (Random Forest, DBSCAN, StandardScaler)  |  joblib"),
    (0, "Frontend",                                                       True),
    (1, "HTML5 / CSS3 / Vanilla JavaScript  |  Plotly 5.14+ (interactive maps)"),
    (1, "Jinja2 3.1+ (server-side templating)"),
    (0, "Data Sources",                                                   True),
    (1, "LDEM_80S_20M.JP2  — NASA LRO LOLA DEM, 80–90°S, 20 m/px (primary)"),
    (1, "LDEC_80S_20M.JP2  — observation-count quality mask"),
    (1, "LDEM_85S_10M.JP2, ldem_87s_5mpp.tif  — higher-res sub-regions"),
    (0, "Development Platform",                                           True),
    (1, "Windows 11  |  Intel Core i7  |  16 GB RAM  |  No GPU required"),
    (0, "Licence",                                                        True),
    (1, "All dependencies: BSD / MIT open-source  |  Data: NASA public domain"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 11 — DESIGN METHODOLOGY  (split: text left, terrain_preview right)
# ══════════════════════════════════════════════════════════════════════════════
s11 = prs.slides[10]
set_title(s11, "Design Methodology")
set_content(s11, [
    (0, "Three-Tier Web Application",                                     True),
    (1, "Data tier: NASA LOLA JP2 files loaded in-memory on startup"),
    (1, "Application tier: Python FastAPI — 7 analytical modules"),
    (1, "Presentation tier: HTML/CSS/JS + Plotly interactive maps"),
    (0, "REST API Endpoints",                                             True),
    (1, "GET /       → main form interface"),
    (1, "GET /health → terrain load status (polled at 500 ms)"),
    (1, "GET /demo   → hardcoded water-ice RTG full analysis"),
    (1, "POST /analyze → RoverProfile JSON → full analysis JSON"),
    (0, "Per-Request Pipeline",                                           True),
    (1, "score_terrain → classify_terrain → detect_anomalies → generate_waypoints → find_path → generate_report → create_mission_map"),
    (0, "Long-running ops dispatched to ThreadPoolExecutor (non-blocking event loop)", False),
])
# resize content placeholder to left half, add terrain image right
for ph in s11.placeholders:
    if ph.placeholder_format.idx == 1:
        ph.left   = W(0.3)
        ph.top    = W(1.7)
        ph.width  = W(6.4)
        ph.height = W(5.5)
add_img(s11, "outputs/terrain_preview.png", left=6.8, top=1.8, width=6.2)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 12 — CHALLENGES
# ══════════════════════════════════════════════════════════════════════════════
s12 = prs.slides[11]
set_title(s12, "Challenges and Issues Identified")
set_content(s12, [
    (0, "1. Memory Management",                                           True),
    (1, "3× float32 arrays at 10,133×10,133 = 1.2 GB base; RF inference peaks at 1.8 GB"),
    (1, "Solution: 60 m/px downsampling (9× reduction) using rasterio Resampling.average"),
    (0, "2. CRS Complexity",                                              True),
    (1, "EPSG:104903 (Polar Stereographic Moon 2000) not in default proj4 builds"),
    (1, "Solution: pyproj.Transformer with memoised instances for coordinate conversion"),
    (0, "3. A* Runtime on 100M-Pixel Grid",                               True),
    (1, "Pure Python heapq too slow; solution: 2M iteration limit + NumPy neighbour access"),
    (0, "4. JPEG2000 on Windows",                                         True),
    (1, "Default rasterio wheels lack openjpeg; solution: Conda-forge channel"),
    (0, "5. Auto-Labelling Circularity",                                  True),
    (1, "RF labels derived from scorer → independent 10k validation set + 5-fold CV"),
    (0, "6. DBSCAN Sensitivity",                                          True),
    (1, "eps/min_samples tuned across 5 subsamples; CV of cluster count < 0.2"),
    (0, "7. Frontend Plotly Rendering",                                   True),
    (1, "Full-resolution heatmap >100 MB; solution: downsampled to 512×512 for display"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 13 — METHODOLOGY PART 1  (core modules)
# ══════════════════════════════════════════════════════════════════════════════
s13 = prs.slides[12]
set_title(s13, "Methodology & Implementation — Core Modules")
set_content(s13, [
    (0, "A. Terrain Analysis  (terrain.py)",                              True),
    (1, "Load LDEM_80S_20M.JP2 via rasterio → downsample to 60 m/px (10,133×10,133)"),
    (1, "Slope: numpy.gradient central differences →  arctan(√(∂E/∂x² + ∂E/∂y²))"),
    (1, "Roughness: scipy.ndimage.uniform_filter, 300 m (5 px) kernel"),
    (1, "Quality mask from LDEC (observation count < 3 → flagged low quality)"),
    (0, "B. Landing Site Scoring  (landing_scorer.py)",                   True),
    (1, "S_safe = f(slope, roughness, quality_mask, crater_rim_penalty)"),
    (1, "S_mission = f(mission_type: water-ice | geological | tech-demo)"),
    (1, "S_final = 0.6·S_safe + 0.4·S_mission  →  top-10 local maxima (50 px separation)"),
    (1, "RF class bonus: SAFE_LANDING +0.05, HAZARD_ZONE −0.15, SCIENCE_TARGET +0.10"),
    (0, "C. Pathfinding  (pathfinder.py)",                                True),
    (1, "A* search, 8-directional, cost = d · exp(0.3 · max(slope − 10°, 0))"),
    (1, "2M iteration limit; partial path + advisory warning if reached"),
    (1, "generate_waypoints() incorporates anomaly cluster centroids into target sequence"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 14 — METHODOLOGY PART 2  (ML modules)
# ══════════════════════════════════════════════════════════════════════════════
s14 = prs.slides[13]
set_title(s14, "Methodology & Implementation — ML Modules")
set_content(s14, [
    (0, "D. Terrain Classifier  (terrain_classifier.py)",                 True),
    (1, "100-tree Random Forest, 8 features, 50k auto-labelled training samples"),
    (1, "Classes: HAZARD_ZONE (2.2%) | RISKY_LANDING (23.9%) | TRAVERSE_CORRIDOR (40.2%) | SAFE_LANDING (33.7%) | SCIENCE_TARGET (0.001%)"),
    (1, "Validation accuracy: 99.17% on independent 10k held-out set | Model: 13.7 MB"),
    (0, "E. Anomaly Detection  (anomaly_detector.py)",                    True),
    (1, "DBSCAN (ε=0.5, min_samples=10) on 4-feature normalised space (20k subsample)"),
    (1, "4 types: THERMAL_PROXY | ELEVATION_ANOMALY | ROUGHNESS_ANOMALY | SLOPE_TRANSITION"),
    (0, "F. Energy Model  (energy_model.py)",                             True),
    (1, "W_mech = m·g·d·sin(θ) + μr·m·g·d·cos(θ),   g = 1.62 m/s²,   μr = 0.15"),
    (1, "Motor efficiency η = 0.7; baseline electronics power; solar illumination model"),
    (0, "G. Mission Advisory  (mission_advisor.py)",                      True),
    (1, "Rule-based 8-section NLG report: Overview → Site Assessment → Safety → Science → Path → Anomalies → Energy → Recommendations"),
    (1, "Feasibility: NOMINAL / MARGINAL / HIGH_RISK (threshold-based)"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 15 — INTERFACE SCREENSHOTS
# ══════════════════════════════════════════════════════════════════════════════
s15 = prs.slides[14]
set_title(s15, "Interface & Output Screenshots")
# Remove content placeholder; place 4 images in 2×2 grid
for ph in s15.placeholders:
    if ph.placeholder_format.idx == 1:
        sp = ph._element
        sp.getparent().remove(sp)

add_img(s15, "outputs/frontend_form.png",              left=0.3,  top=1.55, width=4.05)
add_img(s15, "outputs/mission_map_in_original axis.png", left=4.55, top=1.55, width=4.35)
add_img(s15, "outputs/map_with_path_shown.png",        left=9.0,  top=1.55, width=4.1)
add_img(s15, "outputs/mission_summary_generated.png",  left=0.3,  top=4.35, width=4.05)
add_img(s15, "outputs/score_chart_with_top_landing_sites.png", left=4.55, top=4.35, width=8.6)

# Caption labels
for (txt, lf, tp) in [
    ("(a) Web Interface",          0.3,  4.15),
    ("(b) Mission Score Map",      4.55, 4.15),
    ("(c) Map with Path",          9.0,  4.15),
    ("(d) Mission Summary",        0.3,  7.0),
    ("(e) Score Chart – Top Sites",4.55, 7.0),
]:
    add_textbox(s15, txt, lf, tp, 4.0, 0.25, size=11, italic=True,
                align=PP_ALIGN.CENTER, color=(80,80,80))

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 16 — PERFORMANCE EVALUATION
# ══════════════════════════════════════════════════════════════════════════════
s16 = prs.slides[15]
set_title(s16, "Testing and Performance Evaluation")
# Remove content ph; add classification table + runtime table
for ph in s16.placeholders:
    if ph.placeholder_format.idx == 1:
        sp = ph._element
        sp.getparent().remove(sp)

add_textbox(s16, "Terrain Classification Results (10,000-sample validation set)",
            0.35, 1.55, 6.2, 0.35, size=14, bold=True, color=(31,73,125))
clf_data = [
    ["Class",            "Prevalence", "Precision", "Recall", "F1"],
    ["HAZARD_ZONE",      "2.2%",       "0.999",     "0.998",  "0.998"],
    ["RISKY_LANDING",    "23.9%",      "0.992",     "0.994",  "0.993"],
    ["TRAVERSE_CORRIDOR","40.2%",      "0.991",     "0.990",  "0.991"],
    ["SAFE_LANDING",     "33.7%",      "0.993",     "0.992",  "0.993"],
    ["SCIENCE_TARGET",   "0.001%",     "1.000",     "1.000",  "1.000"],
    ["Overall Accuracy", "—",          "—",         "—",      "99.17%"],
]
add_table(s16, clf_data, left=0.35, top=1.95, width=6.2, height=3.6, font_size=11)

add_textbox(s16, "System Runtime (Intel Core i7, 16 GB RAM)",
            6.8, 1.55, 6.2, 0.35, size=14, bold=True, color=(31,73,125))
rt_data = [
    ["Module",                 "Runtime (s)", "Memory Peak"],
    ["DEM Load + Metrics",     "11.8",        "1,240 MB"],
    ["Landing Scorer",         "2.3",         "1,340 MB"],
    ["RF Inference (full grid)","12.1",        "1,800 MB"],
    ["DBSCAN Anomaly Det.",    "0.8",         "1,280 MB"],
    ["A* Pathfinder",          "1.4",         "1,260 MB"],
    ["Mission Advisor",        "0.1",         "1,250 MB"],
    ["Plotly HTML Gen.",       "1.2",         "1,300 MB"],
    ["Total (excl. DEM load)", "18–45",       "1,800 MB peak"],
]
add_table(s16, rt_data, left=6.8, top=1.95, width=6.2, height=4.2, font_size=11)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 17 — ARTEMIS III VALIDATION
# ══════════════════════════════════════════════════════════════════════════════
s17 = prs.slides[16]
set_title(s17, "Validation — Artemis III & Chandrayaan-3")
for ph in s17.placeholders:
    if ph.placeholder_format.idx == 1:
        sp = ph._element
        sp.getparent().remove(sp)

add_textbox(s17, "Scoring Validation Against NASA Expert Assessments",
            0.35, 1.55, 12.6, 0.35, size=14, bold=True, color=(31,73,125))
val_data = [
    ["Site",             "Lat/Lon",               "Safety", "Mission\n(WI)", "Final",  "Class",             "NASA Assessment"],
    ["Shackleton Ridge", "89.9°S / 0°E",          "0.71",  "0.52",          "0.603",  "SAFE_LANDING",      "✓ #1 Artemis III priority"],
    ["Faustini Crater",  "87.3°S / 87.0°E",       "0.000", "0.643",         "—",      "HAZARD_ZONE",       "✓ High science, inaccessible floor"],
    ["Haworth Edge",     "87.5°S / 357.0°E",      "0.44",  "0.57",          "0.505",  "RISKY_LANDING",     "✓ Marginal safety"],
    ["Nobile Rim",       "85.2°S / 53.2°E",       "0.51",  "0.49",          "0.501",  "TRAVERSE_CORRIDOR", "✓ Marginal, alternative route"],
    ["Chandrayaan-3",    "69.37°S / 32.32°E",     "N/A",   "N/A",           "N/A",    "Out of bounds",     "✓ Outside 80–90°S — scientifically correct"],
]
add_table(s17, val_data, left=0.35, top=1.95, width=12.6, height=2.9, font_size=10)

add_img(s17, "outputs/c3_validation_table.png",    left=0.35, top=4.95, width=7.0)
add_img(s17, "outputs/chandrayaan3validationMap.png", left=7.5, top=4.95, width=5.6)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 18 — OUTCOMES  (use existing slot)
# ══════════════════════════════════════════════════════════════════════════════
s18 = prs.slides[17]
set_title(s18, "Outcomes")
set_content(s18, [
    (0, "Delivered",                                                      True),
    (1, "✓  Fully functional web-based mission planning system — 7 integrated modules"),
    (1, "✓  RF terrain classifier: 99.17% accuracy, zero manual annotations required"),
    (1, "✓  A* pathfinder: interactive paths on 10,133×10,133 grids in ~1.4 sec"),
    (1, "✓  DBSCAN science target detector: 12 clusters/run (median, range 8–19)"),
    (1, "✓  Validated against 4 NASA Artemis III sites + Chandrayaan-3 — strong alignment"),
    (1, "✓  Research paper manuscript prepared for submission (April 2026)"),
    (0, "Scientific / Engineering Impact",                                True),
    (1, "→  Expert-quality lunar mission analysis at interactive latencies on commodity hardware"),
    (1, "→  Auto-labelling methodology applicable to any data-rich planetary surface problem"),
    (1, "→  Open-source reproducible baseline for multi-modal planetary mission planning"),
    (0, "Future Directions",                                              True),
    (1, "Mini-RF CPR integration  |  Horizon-integrated illumination model  |  Multi-rover planning"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 19 — GANTT CHART  (new slide)
# ══════════════════════════════════════════════════════════════════════════════
s19 = clone_content_slide(prs)
set_title(s19, "Gantt Chart")
for ph in s19.placeholders:
    if ph.placeholder_format.idx == 1:
        sp = ph._element
        sp.getparent().remove(sp)

months = ["Oct\n2025","Nov\n2025","Dec\n2025","Jan\n2026","Feb\n2026","Mar\n2026","Apr\n2026"]
tasks = [
    ("Literature Review & Problem Definition",          [1,1,0,0,0,0,0]),
    ("Data Collection & Preprocessing",                 [1,1,0,0,0,0,0]),
    ("Terrain Analysis (terrain.py)",                   [0,1,1,0,0,0,0]),
    ("Landing Site Scoring (landing_scorer.py)",        [0,0,1,1,0,0,0]),
    ("A* Pathfinding (pathfinder.py)",                  [0,0,1,1,0,0,0]),
    ("Visualisation (visualizer.py)",                   [0,0,0,1,1,0,0]),
    ("Terrain Classifier — RF",                         [0,0,0,1,1,0,0]),
    ("Anomaly Detection — DBSCAN",                      [0,0,0,1,1,0,0]),
    ("Energy Model & Mission Advisor",                  [0,0,0,0,1,1,0]),
    ("Web Interface (FastAPI + HTML/CSS/JS)",            [0,0,0,1,1,1,0]),
    ("System Integration & Testing",                    [0,0,0,0,1,1,0]),
    ("Validation (Artemis III, Chandrayaan-3)",         [0,0,0,0,0,1,0]),
    ("Synopsis Report Writing",                         [0,0,0,0,0,1,0]),
    ("Research Paper Writing & Submission",             [0,0,0,0,0,1,1]),
]

n_tasks  = len(tasks)
n_months = len(months)
header = ["S.No.", "Task"] + months
all_rows = [header]
for i, (name, sched) in enumerate(tasks, 1):
    row = [str(i), name] + ["" for _ in sched]
    all_rows.append(row)

tbl_shape = s19.shapes.add_table(
    n_tasks + 1, n_months + 2,
    W(0.2), W(1.55), W(12.9), W(5.6)
)
tbl = tbl_shape.table

# header row
HEADER_COL = (31, 73, 125)
FILL_COL   = (68, 114, 196)
for c, h in enumerate(header):
    cell = tbl.cell(0, c)
    tf = cell.text_frame
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    run = tf.paragraphs[0].add_run()
    run.text = h
    run.font.size = P(9)
    run.font.bold = True
    run.font.color.rgb = RGBColor(255, 255, 255)
    _set_cell_fill(cell, *HEADER_COL)

for i, (name, sched) in enumerate(tasks, 1):
    # S.No.
    c0 = tbl.cell(i, 0)
    c0.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    r0 = c0.text_frame.paragraphs[0].add_run()
    r0.text = str(i)
    r0.font.size = P(9)
    if i % 2 == 0:
        _set_cell_fill(c0, 235, 241, 250)
    # Task name
    c1 = tbl.cell(i, 1)
    c1.text_frame.word_wrap = True
    c1.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
    r1 = c1.text_frame.paragraphs[0].add_run()
    r1.text = name
    r1.font.size = P(9)
    if i % 2 == 0:
        _set_cell_fill(c1, 235, 241, 250)
    # Month cells
    for j, active in enumerate(sched):
        cell = tbl.cell(i, j + 2)
        cell.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        if active:
            _set_cell_fill(cell, *FILL_COL)
        elif i % 2 == 0:
            _set_cell_fill(cell, 235, 241, 250)

# set column widths
for row in tbl.rows:
    row.cells[0].width = W(0.35)
    row.cells[1].width = W(3.0)
    for k in range(n_months):
        row.cells[k + 2].width = W(1.36)

add_textbox(s19, "Blue = active period.  Implementation: Oct 2025 – Mar 2026.  Research paper: Mar – Apr 2026.",
            0.2, 7.15, 12.9, 0.25, size=10, italic=True,
            color=(80,80,80), align=PP_ALIGN.CENTER)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 20 — RESPONSIBILITY CHART  (new slide)
# ══════════════════════════════════════════════════════════════════════════════
s20 = clone_content_slide(prs)
set_title(s20, "Responsibility Chart")
for ph in s20.placeholders:
    if ph.placeholder_format.idx == 1:
        sp = ph._element
        sp.getparent().remove(sp)

resp = [
    ["Task / Module",                         "Garima\n(22CSU067)", "Garima Juneja\n(22CSU068)", "Aryan\n(22CSU031)"],
    ["Literature Survey & Background Research","P",                  "S",                          "S"],
    ["Data Collection (NASA PDS)",            "P",                  "—",                          "—"],
    ["Preprocessing + Terrain Analysis",       "P",                  "—",                          "—"],
    ["Landing Scorer + A* Pathfinder",        "P",                  "S",                          "—"],
    ["RF Terrain Classifier",                 "P",                  "—",                          "—"],
    ["Anomaly Detection + Energy Model",       "P",                  "—",                          "—"],
    ["Mission Advisor + Integration",          "P",                  "S",                          "—"],
    ["FastAPI Backend (main.py)",              "P",                  "S",                          "—"],
    ["Frontend HTML/CSS Design",              "S",                  "P",                          "—"],
    ["JS AJAX + Plotly Integration",          "S",                  "P",                          "—"],
    ["Validation (Artemis III / C3)",         "P",                  "—",                          "S"],
    ["Documentation & README",                "S",                  "—",                          "P"],
    ["Synopsis Report Writing",               "S",                  "—",                          "P"],
    ["Research Paper Drafting",               "P",                  "—",                          "S"],
    ["Presentation Preparation",              "P",                  "S",                          "S"],
    ["Meeting Notes & Progress Tracking",     "—",                  "—",                          "P"],
]

tbl_r = s20.shapes.add_table(len(resp), 4, W(0.2), W(1.55), W(12.9), W(5.6))
tbl_r = tbl_r.table

P_GREEN  = (84,  130, 53)
S_YELLOW = (191, 143, 0)

for r, row_data in enumerate(resp):
    for c, txt in enumerate(row_data):
        cell = tbl_r.cell(r, c)
        tf = cell.text_frame
        tf.word_wrap = True
        al = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER
        tf.paragraphs[0].alignment = al
        run = tf.paragraphs[0].add_run()
        run.text = txt
        run.font.size = P(10 if c == 0 else 11)
        run.font.bold = (r == 0)
        if r == 0:
            run.font.color.rgb = RGBColor(255, 255, 255)
            _set_cell_fill(cell, 31, 73, 125)
        elif c > 0:
            if txt == "P":
                run.font.color.rgb = RGBColor(255, 255, 255)
                _set_cell_fill(cell, *P_GREEN)
            elif txt == "S":
                run.font.color.rgb = RGBColor(0, 0, 0)
                _set_cell_fill(cell, 255, 242, 204)
            elif r % 2 == 0:
                _set_cell_fill(cell, 242, 242, 242)
        elif r % 2 == 0:
            _set_cell_fill(cell, 242, 242, 242)

for row in tbl_r.rows:
    row.cells[0].width = W(4.5)
    row.cells[1].width = W(2.8)
    row.cells[2].width = W(3.2)
    row.cells[3].width = W(2.4)

add_textbox(s20, "P = Primary (green)   |   S = Supporting (yellow)   |   — = No direct involvement",
            0.2, 7.15, 12.9, 0.25, size=10, italic=True,
            color=(80,80,80), align=PP_ALIGN.CENTER)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 21 — BROADER IMPACT / RESEARCH PAPER  (new slide)
# ══════════════════════════════════════════════════════════════════════════════
s21 = clone_content_slide(prs)
set_title(s21, "Broader Impact & Research Paper Status")
set_content(s21, [
    (0, "Broader Impact",                                                 True),
    (1, "Democratises lunar mission planning — accessible without proprietary GIS tools"),
    (1, "Reproducible open-source pipeline for the planetary science community"),
    (1, "Auto-labelling methodology eliminates annotation bottleneck for planetary ML"),
    (1, "Extensible baseline: ready for Mini-RF SAR, Diviner thermal, spectral data integration"),
    (1, "ISRU potential: identifies water-ice prospecting targets for future human missions"),
    (1, "Supports India's Chandrayaan / Artemis mission planning community"),
    (0, "Research Paper Status",                                          True),
    (1, "Title: \"Multi-Resolution Terrain Fusion and ML-Based Adaptive Landing Site"),
    (1, "         Selection for Lunar South Pole Rover Missions\""),
    (1, "Authors: Garima, Garima Juneja, Aryan (under supervision of Dr. Snehlata Sheoran, Dr. Ankita Bhalla)"),
    (1, "Status: Manuscript prepared → targeting submission April 2026"),
    (1, "Target venue: IEEE / Elsevier — Planetary & Space Science or AI+Robotics journal"),
])

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 22 — MS MEETING SCREENSHOTS  (new slide)
# ══════════════════════════════════════════════════════════════════════════════
s22 = clone_content_slide(prs)
set_title(s22, "Screenshot of MS-Meetings (Online) / Guide Comments (Offline)")
# Remove content placeholder; add placeholder boxes for 6 meetings
for ph in s22.placeholders:
    if ph.placeholder_format.idx == 1:
        sp = ph._element
        sp.getparent().remove(sp)

meeting_labels = [
    ("Oct 2025\nProject Scoping",  0.3,  1.55),
    ("Nov 2025\nTerrain Review",   4.55, 1.55),
    ("Dec 2025\nScoring & RF",     8.8,  1.55),
    ("Jan 2026\nMid-Term Review",  0.3,  4.55),
    ("Feb 2026\nIntegration",      4.55, 4.55),
    ("Mar 2026\nValidation",       8.8,  4.55),
]

for (lbl, lf, tp) in meeting_labels:
    # Gray placeholder box
    box = s22.shapes.add_textbox(W(lf), W(tp), W(4.1), W(2.7))
    tf = box.text_frame
    tf.word_wrap = True
    para = tf.paragraphs[0]
    para.alignment = PP_ALIGN.CENTER
    run = para.add_run()
    run.text = f"[ Please attach\nMS Teams screenshot\nor guide comment ]\n\n{lbl}"
    run.font.size = P(12)
    run.font.color.rgb = RGBColor(120, 120, 120)
    run.font.italic = True
    # Add border via XML
    from pptx.oxml.ns import qn as _qn
    spPr = box._element.find(_qn("p:spPr"))
    if spPr is None:
        spPr = etree.SubElement(box._element, _qn("p:spPr"))
    ln = etree.SubElement(spPr, _qn("a:ln"))
    ln.set("w", "12700")
    solidFill = etree.SubElement(ln, _qn("a:solidFill"))
    srgb = etree.SubElement(solidFill, _qn("a:srgbClr"))
    srgb.set("val", "AAAAAA")

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 23 — THANK YOU  (new slide)
# ══════════════════════════════════════════════════════════════════════════════
s23 = clone_content_slide(prs)
set_title(s23, "Thank You")
set_content(s23, [
    (0, "Key References",                                                 True),
    (1, "[1] Colaprete et al., 'Detection of Water in LCROSS Ejecta Plume,' Science, 2010"),
    (1, "[5] Smith et al., 'LOLA Investigation on LRO Mission,' Space Sci. Rev., 2010"),
    (1, "[8] Golombek et al., 'Selection of MER Landing Sites,' JGR Planets, 2003"),
    (1, "[13] Stentz, 'Optimal Path Planning for Partially Known Environments,' ICRA, 1994"),
    (1, "[15] Ester et al., 'DBSCAN,' KDD, 1996"),
    (1, "[18] Lemelin et al., 'High-Priority Lunar Landing Sites,' Planet. Space Sci., 2014"),
    (1, "[20] Pedregosa et al., 'Scikit-learn: ML in Python,' JMLR, 2011"),
    (0, "",                                                               False),
    (0, "Queries / Contact",                                              True),
    (1, "Garima (22CSU067)  |  Garima Juneja (22CSU068)  |  Aryan (22CSU031)"),
    (1, "Supervisors: Dr. Snehlata Sheoran  |  Dr. Ankita Bhalla"),
    (1, "Dept. of CSE, The NorthCap University, Gurugram – 122001"),
])

# ── Save ─────────────────────────────────────────────────────────────────────
out = "Anveshak_MidTerm_PPT.pptx"
prs.save(out)
print(f"Saved: {out}")
print(f"Total slides: {len(prs.slides)}")
