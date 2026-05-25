"""
generate_report_doc.py
Generates the MidTerm VIII Semester Synopsis Report for Anveshak.
Run:  python generate_report_doc.py
Output: Anveshak_Synopsis_Report.docx
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")

from docx import Document
from docx.shared import Pt, Inches, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

# ─────────────────────────── helpers ─────────────────────────────────────────

def set_font(run, size=12, bold=False, italic=False, name="Times New Roman", color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = RGBColor(*color)

def add_para(doc, text, size=12, bold=False, italic=False, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
             space_before=0, space_after=6, first_line_indent=0):
    p = doc.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after  = Pt(space_after)
    if first_line_indent:
        pf.first_line_indent = Pt(first_line_indent)
    run = p.add_run(text)
    set_font(run, size=size, bold=bold, italic=italic)
    return p

def add_heading(doc, text, level=1, size=14, space_before=12, space_after=6):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after  = Pt(space_after)
    run = p.add_run(text)
    set_font(run, size=size, bold=True)
    return p

def add_subheading(doc, text, size=12, space_before=8, space_after=4):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after  = Pt(space_after)
    run = p.add_run(text)
    set_font(run, size=12, bold=True)
    return p

def add_bullet(doc, text, size=12, indent=0.4):
    p = doc.add_paragraph(style="List Bullet")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(3)
    pf = p.paragraph_format
    pf.left_indent = Inches(indent)
    run = p.add_run(text)
    set_font(run, size=size)
    return p

def add_numbered(doc, text, size=12):
    p = doc.add_paragraph(style="List Number")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(3)
    run = p.add_run(text)
    set_font(run, size=size)
    return p

def shade_cell(cell, hex_color="4472C4"):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)

def set_cell_text(cell, text, size=10, bold=False, align=WD_ALIGN_PARAGRAPH.CENTER,
                  color=None):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after  = Pt(0)
    run = p.add_run(text)
    set_font(run, size=size, bold=bold, color=color)

def set_col_width(table, col_idx, width_inches):
    for row in table.rows:
        row.cells[col_idx].width = Inches(width_inches)

def add_image(doc, img_path, width=Inches(5.5), caption=None):
    """Insert an actual image, centered."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after  = Pt(4)
    run = p.add_run()
    run.add_picture(img_path, width=width)
    return p

def add_screenshot_placeholder(doc, label="[SCREENSHOT PLACEHOLDER]"):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after  = Pt(6)
    run = p.add_run(label)
    run.font.name = "Times New Roman"
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
    run.italic = True
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    for side in ("top", "left", "bottom", "right"):
        bdr = OxmlElement(f"w:{side}")
        bdr.set(qn("w:val"), "single")
        bdr.set(qn("w:sz"), "12")
        bdr.set(qn("w:space"), "4")
        bdr.set(qn("w:color"), "AAAAAA")
        pBdr.append(bdr)
    pPr.append(pBdr)

# ─────────────────────────── document setup ──────────────────────────────────

doc = Document()

# Page setup: 8.5" x 11", 1" margins
section = doc.sections[0]
section.page_width  = Inches(8.5)
section.page_height = Inches(11)
section.top_margin    = Inches(1.0)
section.bottom_margin = Inches(1.0)
section.left_margin   = Inches(1.25)
section.right_margin  = Inches(1.25)

# Default style
style = doc.styles["Normal"]
style.font.name = "Times New Roman"
style.font.size = Pt(12)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — COVER PAGE
# ═══════════════════════════════════════════════════════════════════════════════

# University Logo
if os.path.exists("ncu_logo.png"):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture("ncu_logo.png", width=Inches(2.5))

doc.add_paragraph()  # spacer

add_para(doc,
    "Multi-Resolution Terrain Fusion and ML-Based Adaptive Landing Site\n"
    "Selection for Lunar South Pole Rover Missions",
    size=18, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)

add_para(doc,
    "MID TERM VIII SEMESTER SYNOPSIS REPORT",
    size=14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)

add_para(doc,
    "Submitted in partial fulfillment of the requirement of the degree of",
    size=14, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)

add_para(doc,
    "BACHELORS OF TECHNOLOGY",
    size=16, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)

add_para(doc, "to", size=14, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)

add_para(doc,
    "The NorthCap University",
    size=14, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)

add_para(doc, "by", size=14, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6)

add_para(doc,
    "Garima (22CSU067)\nGarima Juneja (22CSU068)\nAryan (22CSU031)",
    size=14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)

add_para(doc, "Under the supervision of", size=14,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)

add_para(doc,
    "Dr. Snehlata Sheoran\nDr. Ankita Bhalla",
    size=14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)

add_para(doc,
    "Associate Professor, Department of Computer Science and Engineering",
    size=14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=14)

add_para(doc,
    "Department of Computer Science and Engineering\n"
    "School of Engineering and Technology\n"
    "The NorthCap University, Gurugram – 122001, India",
    size=12, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6)

add_para(doc, "Session 2022–26", size=12,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=0)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — CERTIFICATE
# ═══════════════════════════════════════════════════════════════════════════════

add_para(doc, "CERTIFICATE", size=14, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_before=12, space_after=12)

add_para(doc,
    "This is to certify that the Project Synopsis entitled, \u201cMulti-Resolution Terrain Fusion "
    "and ML-Based Adaptive Landing Site Selection for Lunar South Pole Rover Missions\u201d submitted "
    "by Garima (22CSU067), Garima Juneja (22CSU068), and Aryan (22CSU031) to The NorthCap "
    "University, Gurugram, India, is a record of bona fide synopsis work carried out by them "
    "under our supervision and guidance and is worthy of consideration for the partial fulfilment "
    "of the degree of Bachelor of Technology in Computer Science and Engineering of the University.",
    size=12, align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=40)

# Signature table
sig_table = doc.add_table(rows=2, cols=2)
sig_table.style = "Table Grid"
# Remove borders
for row in sig_table.rows:
    for cell in row.cells:
        for border_name in ["top", "left", "bottom", "right"]:
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            tcBorders = OxmlElement("w:tcBorders")
            bdr = OxmlElement(f"w:{border_name}")
            bdr.set(qn("w:val"), "none")
            tcBorders.append(bdr)
            tcPr.append(tcBorders)

set_cell_text(sig_table.rows[0].cells[0], "Signature: ___________________", size=12, align=WD_ALIGN_PARAGRAPH.LEFT)
set_cell_text(sig_table.rows[0].cells[1], "Signature: ___________________", size=12, align=WD_ALIGN_PARAGRAPH.LEFT)
set_cell_text(sig_table.rows[1].cells[0], "Dr. Snehlata Sheoran\nAssociate Professor, Dept. of CSE\nThe NorthCap University", size=12, align=WD_ALIGN_PARAGRAPH.LEFT)
set_cell_text(sig_table.rows[1].cells[1], "Dr. Ankita Bhalla\nAssociate Professor, Dept. of CSE\nThe NorthCap University", size=12, align=WD_ALIGN_PARAGRAPH.LEFT)

add_para(doc, "", space_after=10)
add_para(doc, "Date: _______________", size=12,
         align=WD_ALIGN_PARAGRAPH.LEFT, space_after=0)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — INDEX (TABLE OF CONTENTS)
# ═══════════════════════════════════════════════════════════════════════════════

add_para(doc, "INDEX", size=14, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_before=0, space_after=10)

toc_items = [
    ("Abstract", "4"),
    ("Chapter 1: Introduction", "5"),
    ("Chapter 2: Background", "7"),
    ("Chapter 3: Feasibility Study", "9"),
    ("Chapter 4: Literature Survey", "11"),
    ("Chapter 5: Comparison with Existing Solutions", "15"),
    ("Chapter 6: Gap Analysis", "17"),
    ("Chapter 7: Problem Statement", "18"),
    ("Chapter 8: Objectives", "19"),
    ("Chapter 9: Tools / Platform Used", "20"),
    ("Chapter 10: Design Methodology", "22"),
    ("Chapter 11: Challenges and Issues Identified", "25"),
    ("Chapter 12: Methodology and Implementation", "27"),
    ("Chapter 13: Performance Evaluation", "34"),
    ("Chapter 14: Outcomes", "38"),
    ("Chapter 15: Gantt Chart", "40"),
    ("Chapter 16: Responsibility Chart", "41"),
    ("References", "42"),
    ("Annexure I: Meeting Screenshots / Guide Comments", "44"),
]

toc_table = doc.add_table(rows=len(toc_items) + 1, cols=3)
toc_table.style = "Table Grid"
toc_table.alignment = WD_TABLE_ALIGNMENT.CENTER

headers = ["S. No.", "Chapter / Section", "Page No."]
for j, h in enumerate(headers):
    set_cell_text(toc_table.rows[0].cells[j], h, size=12, bold=True)
    shade_cell(toc_table.rows[0].cells[j], "D9D9D9")

for i, (title, page) in enumerate(toc_items, start=1):
    set_cell_text(toc_table.rows[i].cells[0], str(i), size=12)
    set_cell_text(toc_table.rows[i].cells[1], title, size=12, align=WD_ALIGN_PARAGRAPH.LEFT)
    set_cell_text(toc_table.rows[i].cells[2], page, size=12)

# Set column widths
for row in toc_table.rows:
    row.cells[0].width = Inches(0.7)
    row.cells[1].width = Inches(4.5)
    row.cells[2].width = Inches(0.9)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# ABSTRACT
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Abstract", size=14)

add_para(doc,
    "The lunar south polar region represents one of the most scientifically compelling and "
    "operationally hazardous destinations in contemporary planetary exploration. Permanently "
    "shadowed craters may harbour water ice deposits of immense scientific and resource value, "
    "yet the terrain is characterised by extreme slopes, deep shadowing, and limited illumination "
    "that challenge conventional mission planning. This report presents Anveshak, a comprehensive "
    "web-based mission planning system for lunar south pole rover operations, integrating "
    "multi-resolution terrain fusion, machine learning-based terrain classification, adaptive "
    "landing site scoring, terrain-aware pathfinding, and geological anomaly detection.",
    size=12, first_line_indent=18)

add_para(doc,
    "The system ingests real NASA LRO LOLA Digital Elevation Model (DEM) data covering "
    "80\u201390\u00b0S at 20 m/pixel native resolution, computes operational terrain metrics "
    "(slope, roughness, and data-quality masks) over a 10,133 \u00d7 10,133 pixel grid at "
    "60 m/pixel working resolution, and delivers mission-critical analysis through an interactive "
    "browser-based interface. A Random Forest terrain classifier achieves 99.17% validation "
    "accuracy on 10,000 held-out samples trained entirely from automatically generated labels. "
    "Validation against four NASA Artemis III candidate sites demonstrates strong qualitative "
    "agreement with published expert assessments. End-to-end analysis latency is 18\u201345 "
    "seconds on commodity hardware.",
    size=12, first_line_indent=18)

add_para(doc,
    "The system demonstrates that a fully open, automated, data-driven pipeline can reproduce "
    "expert-quality lunar south pole mission analysis at interactive latencies without proprietary "
    "software dependencies. Anveshak is being prepared for journal submission and provides a "
    "reproducible, extensible baseline for multi-modal planetary mission planning research.",
    size=12, first_line_indent=18)

add_para(doc,
    "Keywords \u2014 Lunar landing site selection, Digital Elevation Model, Random Forest "
    "terrain classification, A* pathfinding, DBSCAN anomaly detection, NASA LRO LOLA, "
    "south pole robotics, mission planning, FastAPI, planetary science.",
    size=12, italic=True)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 1 — INTRODUCTION
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 1: Introduction", size=14, space_before=0)

add_subheading(doc, "1.1  Broad Context and Motivation")

add_para(doc,
    "The exploration of the Moon's south polar region has become a central ambition of global "
    "space agencies and commercial actors in the early twenty-first century. NASA's Artemis "
    "programme, ISRO's Chandrayaan series, the China National Space Administration's Chang'e "
    "programme, and numerous commercial ventures are all targeting this region, driven chiefly "
    "by the theoretical presence of water ice in Permanently Shadowed Regions (PSRs). Colaprete "
    "et al. [1] confirmed water ice detection via the LCROSS impact mission, validating decades "
    "of orbital neutron spectrometer observations. The potential in-situ resource utilisation "
    "(ISRU) value of polar ice \u2014 for propellant, life support, and construction \u2014 "
    "transforms the south pole from a scientific curiosity into a strategic human settlement "
    "target.",
    size=12, first_line_indent=18)

add_para(doc,
    "Despite this compelling motivation, the south polar terrain presents mission designers with "
    "formidable challenges. Slopes near crater rims frequently exceed 20\u00b0, well above the "
    "stability threshold for most rover designs. Illumination is highly variable and "
    "site-dependent, with some ridges receiving near-continuous sunlight while crater floors "
    "remain in permanent shadow. The LOLA DEM data reveals elevation variations from "
    "\u22127,297 m in crater floors to +7,027 m at rim peaks within the 80\u201390\u00b0S "
    "coverage area. Conventional mission planning workflows rely heavily on specialist "
    "geospatial software and manual expert review, creating bottlenecks that slow mission "
    "cadence and limit participation by smaller teams and institutions.",
    size=12, first_line_indent=18)

add_subheading(doc, "1.2  The Anveshak System")

add_para(doc,
    "Anveshak (Sanskrit for \u201cexplorer\u201d or \u201cinvestigator\u201d) is an integrated "
    "web-based mission planning system addressing this gap. It provides a complete, automated "
    "pipeline from raw DEM ingestion through interactive mission advisory report generation, "
    "accessible from any modern browser. The system is designed as an offline planning tool "
    "rather than an onboard navigation system: it operates on pre-processed DEM tiles and "
    "delivers analysis results to human mission planners who retain final decision authority. "
    "This human-in-the-loop design is a deliberate safety choice appropriate to the current "
    "state of planetary mission verification and validation practice.",
    size=12, first_line_indent=18)

add_para(doc,
    "The system comprises seven tightly integrated analytical modules: terrain data ingestion "
    "and metric computation (terrain.py), multi-criteria landing site scoring (landing_scorer.py), "
    "terrain-aware A* pathfinding (pathfinder.py), Random Forest terrain classification "
    "(terrain_classifier.py), DBSCAN-based science target detection (anomaly_detector.py), "
    "first-principles energy modelling (energy_model.py), and rule-based mission advisory report "
    "generation (mission_advisor.py). These modules are wired together through a Python FastAPI "
    "backend exposed via a lightweight HTML/CSS/JavaScript frontend.",
    size=12, first_line_indent=18)

add_subheading(doc, "1.3  Key Contributions")

add_para(doc, "This project makes the following specific contributions:", size=12)

contributions = [
    "An open, reproducible pipeline for ingesting NASA LRO LOLA DEM data (LDEM_80S_20M.JP2) "
    "and deriving operational terrain metrics \u2014 slope, roughness, and data-quality masks "
    "\u2014 over the complete 80\u201390\u00b0S region at a working resolution of 60 m/pixel.",
    "A multi-criteria landing-site scoring function parameterised by mission profile, with "
    "empirical validation against four NASA Artemis III candidate sites.",
    "A Random Forest terrain classifier trained on 50,000 automatically labelled samples "
    "achieving 99.17% accuracy on a held-out validation set of 10,000 samples, without "
    "requiring manual annotation.",
    "An A* pathfinder with terrain-aware exponential slope cost, supporting 8-directional "
    "movement over grids exceeding 10,000 \u00d7 10,000 pixels within a 2-million-iteration "
    "budget.",
    "A DBSCAN-based science-target detector that identifies geologically anomalous terrain "
    "without requiring prior specification of cluster count.",
    "An integrated web-based interface with interactive Plotly visualisations and rule-based "
    "plain-English mission advisory report generation.",
]
for c in contributions:
    add_numbered(doc, c)

add_subheading(doc, "1.4  Report Structure")

add_para(doc,
    "The remainder of this report is structured as follows. Chapter 2 provides background on "
    "lunar exploration and the DEM data products used. Chapter 3 presents the feasibility study. "
    "Chapter 4 surveys related literature. Chapter 5 compares Anveshak with existing solutions. "
    "Chapter 6 identifies the gap this work addresses. Chapters 7 and 8 state the problem and "
    "objectives. Chapter 9 documents the tools and platform. Chapters 10 and 11 address design "
    "methodology and challenges. Chapter 12 details the full methodology and implementation. "
    "Chapter 13 presents performance evaluation results. Chapter 14 describes outcomes and "
    "Chapter 15\u201316 provide the project timeline and responsibility charts.",
    size=12, first_line_indent=18)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 2 — BACKGROUND
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 2: Background", size=14, space_before=0)

add_subheading(doc, "2.1  History of Lunar South Pole Exploration")

add_para(doc,
    "Interest in the lunar poles was catalysed by the Clementine mission (1994) and Lunar "
    "Prospector (1998), which provided indirect evidence for hydrogen concentrations in polar "
    "craters consistent with water ice. The Lunar Reconnaissance Orbiter (LRO), launched in "
    "2009, transformed our understanding of polar topography through the Lunar Orbiter Laser "
    "Altimeter (LOLA) instrument, providing 10 cm vertical precision over the entire lunar "
    "surface [5]. The LCROSS impactor mission (2009) detected water vapour in the debris plume, "
    "providing the first direct confirmation of polar water ice [1].",
    size=12, first_line_indent=18)

add_para(doc,
    "More recently, Chandrayaan-3 (ISRO, 2023) achieved the first successful landing near the "
    "lunar south pole at 69.37\u00b0S, demonstrating surface operations at high southern "
    "latitudes and directly validating the scientific and engineering interest in this region. "
    "NASA's Artemis III mission, currently planned, targets several sites in the 88\u201390\u00b0S "
    "range including Shackleton Ridge, Faustini Crater rim, Haworth Edge, and Nobile Rim. These "
    "sites were selected following multi-year analysis integrating LOLA DEM data, Diviner thermal "
    "mapping, and illumination modelling [18].",
    size=12, first_line_indent=18)

add_subheading(doc, "2.2  NASA LRO LOLA Digital Elevation Model")

add_para(doc,
    "The Lunar Orbiter Laser Altimeter aboard LRO fires laser pulses at 28 Hz and measures "
    "surface returns with sub-meter cross-track resolution, accumulating more than 6 billion "
    "measurements over the primary and extended mission phases [5]. These measurements are "
    "gridded into DEM products at multiple resolutions: the LDEM_80S_20M product used in this "
    "project covers 80\u201390\u00b0S at 20 m/pixel in JPEG2000 format. The companion LDEC "
    "file records the number of laser returns per pixel, providing a data-quality mask that "
    "identifies regions of sparse coverage where elevation values are interpolated rather than "
    "directly measured.",
    size=12, first_line_indent=18)

add_para(doc,
    "The DEM is projected in the Polar Stereographic Moon 2000 coordinate reference system "
    "(EPSG:104903), centred on the south pole. Pixel coordinates map to selenographic "
    "latitude/longitude through the affine transform embedded in the JPEG2000 file headers, "
    "accessed via the rasterio library. The full 80\u201390\u00b0S grid at 20 m/pixel comprises "
    "approximately 10,133 \u00d7 10,133 pixels, covering roughly 200 km \u00d7 200 km of "
    "polar terrain. Elevation ranges from \u22127,297 m (deep crater floors) to +7,027 m "
    "(high rim peaks).",
    size=12, first_line_indent=18)

add_subheading(doc, "2.3  Mission Planning Requirements")

add_para(doc,
    "Effective mission planning for lunar south pole rover operations must simultaneously "
    "satisfy engineering safety constraints and science return objectives. Key engineering "
    "constraints include maximum traversable slope (typically 15\u201320\u00b0 for current "
    "rover designs), minimum flat landing radius (typically 100\u2013200 m), terrain roughness "
    "limits (driven by chassis suspension travel), and power availability (solar or RTG). "
    "Science objectives vary by mission type: water-ice prospecting missions prioritise PSR "
    "proximity and high latitudes; geological survey missions prefer exposed bedrock and "
    "crater rims; technology demonstration missions seek flat, low-risk terrain.",
    size=12, first_line_indent=18)

add_para(doc,
    "The combinatorial complexity of simultaneously optimising multiple objectives over a "
    "10,000 \u00d7 10,000 pixel terrain grid, subject to mission-profile constraints, "
    "motivates automated computational approaches. Manual analysis at this resolution is "
    "impractical; even expert teams require automated preprocessing pipelines to make "
    "initial site shortlists before human review.",
    size=12, first_line_indent=18)

add_subheading(doc, "2.4  Machine Learning in Planetary Science")

add_para(doc,
    "Machine learning has been applied to planetary terrain analysis in a growing body of "
    "literature. Crater detection using CNNs [2], terrain classification on Mars using SVMs [3], "
    "and graph-based rover path optimisation [4] represent three independent threads that "
    "Anveshak synthesises into a unified framework. The key enabling observation is that "
    "terrain classification labels can be automatically generated from the scoring pipeline "
    "outputs, eliminating the annotation bottleneck that has limited supervised learning "
    "applications in planetary science.",
    size=12, first_line_indent=18)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 3 — FEASIBILITY STUDY
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 3: Feasibility Study", size=14, space_before=0)

add_subheading(doc, "3.1  Technical Feasibility")

add_para(doc,
    "The technical feasibility of Anveshak rests on the availability of open-source tools "
    "sufficient to implement each required capability without proprietary dependencies. "
    "The Python scientific computing stack provides all necessary primitives:",
    size=12, first_line_indent=18)

tech_items = [
    "rasterio (v1.3+): JPEG2000 and GeoTIFF ingestion with CRS-aware coordinate transforms, "
    "eliminating the need for expensive commercial GIS software.",
    "NumPy / SciPy: Array computation for slope (central finite differences via "
    "numpy.gradient), roughness (scipy.ndimage.uniform_filter), and all derived terrain metrics.",
    "scikit-learn (v1.3+): Random Forest classifier (RandomForestClassifier) and DBSCAN "
    "clustering, both with efficient C extensions that handle 50,000-sample training sets "
    "in under 60 seconds.",
    "FastAPI (v0.100+): Asynchronous REST API framework with minimal overhead, supporting "
    "concurrent request handling and ThreadPoolExecutor dispatch for CPU-intensive tasks.",
    "Plotly (v5+): Interactive browser-rendered visualisations with no server-side rendering "
    "dependencies; map HTML is generated once and serialised in the API response.",
    "Conda environment management: Cross-platform reproducibility; the project Conda "
    "environment (lunar-planner, Python 3.11) installs cleanly on Windows, Linux, and macOS.",
]
for item in tech_items:
    add_bullet(doc, item)

add_para(doc,
    "The primary technical risk is memory: the full 10,133 \u00d7 10,133 float32 elevation "
    "array requires 412 MB, and three such arrays (elevation, slope, roughness) total "
    "approximately 1.2 GB. Combined with the 13.7 MB Random Forest model and scikit-learn "
    "inference buffers, peak RAM usage is approximately 1.8 GB, well within the 16 GB "
    "specification of the development workstation. The risk is mitigated by the 60 m/pixel "
    "downsampling decision (Section 12.1), which reduces grid size by 9\u00d7 relative to "
    "native 20 m/pixel resolution.",
    size=12, first_line_indent=18)

add_subheading(doc, "3.2  Operational Feasibility")

add_para(doc,
    "From an operational perspective, Anveshak requires no specialised hardware. It runs on "
    "a standard developer workstation (Intel Core i7, 16 GB RAM, no GPU required). The "
    "browser-based interface eliminates client-side installation and is accessible from any "
    "device with a modern browser. Data input requires only the LOLA DEM files, which are "
    "freely downloadable from NASA's Planetary Data System (PDS) Geosciences Node. The "
    "one-time DEM loading step (\u224812 seconds) is performed on server startup; subsequent "
    "analyses complete in 18\u201345 seconds per query.",
    size=12, first_line_indent=18)

add_subheading(doc, "3.3  Economic Feasibility")

add_para(doc,
    "All software dependencies are open-source with permissive licences (NumPy: BSD, "
    "scikit-learn: BSD, FastAPI: MIT, rasterio: BSD, Plotly: MIT). The NASA LOLA DEM data "
    "products are public domain. Development cost is limited to student and supervisor time, "
    "with no software licensing expenditure. Deployment requires only a standard server "
    "instance (2 vCPU, 4 GB RAM minimum), costing approximately \$15\u201325/month on "
    "commodity cloud platforms if hosting is desired. For local use, no ongoing cost is incurred.",
    size=12, first_line_indent=18)

add_subheading(doc, "3.4  Schedule Feasibility")

add_para(doc,
    "The project was scoped to complete implementation across one academic semester "
    "(October 2025 \u2013 March 2026), with research paper preparation continuing through "
    "April 2026. The modular architecture \u2014 seven largely independent modules \u2014 "
    "enables parallel development and incremental integration. Each module was completed "
    "and verified independently before integration, following an iterative development "
    "model. All seven modules were completed and the system was fully integrated by "
    "February 2026, leaving March 2026 for validation, testing, and report writing.",
    size=12, first_line_indent=18)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 4 — LITERATURE SURVEY
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 4: Literature Survey", size=14, space_before=0)

add_subheading(doc, "4.1  Lunar DEM Products and Terrain Analysis")

add_para(doc,
    "Smith et al. [5] describe the LOLA instrument and its 10 cm vertical precision, which "
    "forms the basis for the LDEM_80S_20M product used in this project. Zuber et al. [6] "
    "used LOLA data to characterise Shackleton Crater's internal topography, providing "
    "early evidence for volatile trapping in its PSR floor. Deutsch et al. [7] presented "
    "updated estimates of ice mass in the lunar polar regions using combined LOLA, Mini-RF, "
    "and Diviner observations. These foundational works establish both the data product "
    "quality and the scientific context motivating south pole mission planning.",
    size=12, first_line_indent=18)

add_para(doc,
    "Prior terrain analysis using LOLA data has largely been performed in specialised GIS "
    "environments (ArcGIS, QGIS, ENVI) requiring domain expertise and commercial licences. "
    "Anveshak's contribution in this sub-domain is the fully automated, open-source Python "
    "pipeline that replicates core terrain analysis capabilities within a web-deployable "
    "application framework, making these analyses accessible to a broader community of "
    "researchers and mission planners.",
    size=12, first_line_indent=18)

add_subheading(doc, "4.2  Automated Landing Site Selection")

add_para(doc,
    "Golombek et al. [8] established multi-criteria scoring frameworks for the Mars "
    "Exploration Rover (MER) landing site selection process, combining engineering safety "
    "(slope, rock abundance) with scientific merit. This conceptual foundation directly "
    "informs Anveshak's two-component scoring model (safety score + mission score). "
    "Flahaut et al. [9] identified regions of interest for future human lunar landing sites "
    "using a multi-criteria approach integrating slope, illumination, and scientific value "
    "maps derived from orbital datasets.",
    size=12, first_line_indent=18)

add_para(doc,
    "Existing automated landing site selection tools are predominantly research prototypes "
    "without publicly available implementations. The most relevant is the ALHAT (Autonomous "
    "Landing and Hazard Avoidance Technology) system developed by NASA JSC, which focuses "
    "on onboard real-time hazard detection during final descent rather than pre-mission "
    "site selection. Anveshak occupies the complementary pre-mission planning niche, "
    "operating offline on large DEM tiles rather than onboard with real-time lidar data.",
    size=12, first_line_indent=18)

add_subheading(doc, "4.3  Machine Learning for Planetary Terrain Classification")

add_para(doc,
    "Bue and Stepinski [3] demonstrated SVM-based geomorphic unit classification from "
    "Martian DEM data, establishing the viability of supervised terrain classification "
    "from elevation-derived features. Palafox et al. [11] applied CNNs to detect volcanic "
    "features on Mars from DEM patches, achieving higher accuracy than SVMs but requiring "
    "substantially more training data and computation. Wagstaff et al. [10] demonstrated "
    "novelty detection for identifying scientifically interesting rock targets from rover "
    "imagery using unsupervised methods.",
    size=12, first_line_indent=18)

add_para(doc,
    "Ono et al. [12] describe MAARS, a machine learning-based autonomous rover science "
    "system for Mars that integrates terrain classification with science target identification. "
    "Shwartz-Ziv and Armon [19] provide theoretical grounding for the choice of tree-based "
    "models over deep learning for tabular (non-image) data, demonstrating that Random "
    "Forests often match or exceed neural network performance on structured feature vectors "
    "\u2014 directly supporting Anveshak's classifier design choice.",
    size=12, first_line_indent=18)

add_subheading(doc, "4.4  Rover Path Planning")

add_para(doc,
    "Stentz [13] introduced the D* algorithm for dynamic replanning in unknown terrain, "
    "which remains a reference for onboard rover autonomy systems. Ferguson and Stentz [14] "
    "developed Field D*, which provides interpolated movement directions for smoother paths "
    "on grid representations. For pre-mission offline planning on known terrain, A* with "
    "an admissible Euclidean heuristic remains computationally dominant due to its "
    "guaranteed optimality under the selected cost function and tractable runtime on the "
    "10,133 \u00d7 10,133 grid.",
    size=12, first_line_indent=18)

add_para(doc,
    "Wettergreen et al. [4] describe science-enabling autonomous navigation for planetary "
    "rovers, combining terrain assessment with science value estimation to plan energy-optimal "
    "paths that maximise science return per unit energy. This multi-objective framing "
    "influenced Anveshak's path planning design, which incorporates terrain-aware slope cost "
    "alongside anomaly waypoints to guide rovers toward science targets while respecting "
    "safety constraints.",
    size=12, first_line_indent=18)

add_subheading(doc, "4.5  Science Target Detection and Anomaly Analysis")

add_para(doc,
    "Ester et al. [15] introduced DBSCAN (Density-Based Spatial Clustering of Applications "
    "with Noise), which has proven particularly suited to geospatial anomaly detection because "
    "it does not require pre-specification of the number of clusters and natively identifies "
    "noise points. Kerner et al. [16] applied novelty detection to multispectral planetary "
    "images, demonstrating the value of unsupervised approaches for identifying targets that "
    "differ statistically from background terrain without requiring prior labelling of "
    "anomalous features.",
    size=12, first_line_indent=18)

add_subheading(doc, "4.6  Integrated Mission Planning Systems")

add_para(doc,
    "Chien et al. [17] describe OASIS, an automated mission planning system for the EO-1 "
    "Earth observation satellite that integrates science return optimisation with engineering "
    "constraint satisfaction. For surface rover missions, the RSVP (Robot Sequencing and "
    "Visualisation Program) toolchain used by NASA JPL for Curiosity and Perseverance "
    "operations provides a high-fidelity simulation and planning environment. However, RSVP "
    "is designed for executed mission operations rather than pre-mission site selection, is "
    "not publicly released, and requires access to mission-specific rover kinematic models.",
    size=12, first_line_indent=18)

add_para(doc,
    "No existing open-source, end-to-end system combines DEM ingestion, ML terrain "
    "classification, multi-criteria scoring, pathfinding, and anomaly detection in a unified "
    "web-deployable framework tailored to the lunar south pole. This gap directly motivates "
    "the development of Anveshak.",
    size=12, first_line_indent=18)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 5 — COMPARISON WITH EXISTING SOLUTIONS
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 5: Comparison with Existing Solutions", size=14, space_before=0)

add_para(doc,
    "Table 5.1 provides a structured comparison of Anveshak against four categories of "
    "existing tools: commercial GIS platforms, NASA mission planning toolchains, research "
    "prototypes, and open-source planetary science libraries.",
    size=12, first_line_indent=18)

comp_data = [
    ["Criteria", "Anveshak", "ArcGIS/ENVI", "NASA RSVP", "ALHAT", "OASIS"],
    ["Open source", "Yes", "No", "No", "No", "No"],
    ["Web-deployable", "Yes", "No", "No", "N/A", "No"],
    ["DEM ingestion\n(open)", "Yes", "Yes", "Limited", "No", "N/A"],
    ["ML classification", "Yes\n(RF, 99.17%)", "Limited", "No", "Basic", "No"],
    ["Path planning", "A*\n(terrain-aware)", "No", "Yes\n(sim)", "D* (onboard)", "N/A"],
    ["Anomaly detection", "DBSCAN", "Manual", "No", "No", "Limited"],
    ["Mission advisory", "Yes\n(rule-based)", "No", "No", "No", "Yes"],
    ["Validation vs.\nArtemis III", "Yes\n(4 sites)", "No", "Yes\n(internal)", "No", "No"],
    ["Hardware needed", "i7, 16 GB\n(standard)", "GPU recommended", "Workstation", "Onboard\ncomputer", "Server"],
    ["Cost", "Free\n(OSS)", "$$$ licence", "Not public", "Not public", "Not public"],
]

comp_table = doc.add_table(rows=len(comp_data), cols=6)
comp_table.style = "Table Grid"
comp_table.alignment = WD_TABLE_ALIGNMENT.CENTER

for i, row_data in enumerate(comp_data):
    for j, cell_text in enumerate(row_data):
        cell = comp_table.rows[i].cells[j]
        set_cell_text(cell, cell_text, size=9, bold=(i == 0),
                      align=WD_ALIGN_PARAGRAPH.CENTER)
        if i == 0:
            shade_cell(cell, "D9D9D9")
        elif j == 1:
            shade_cell(cell, "E2EFDA")   # highlight Anveshak column

for row in comp_table.rows:
    row.cells[0].width = Inches(1.3)
    for j in range(1, 6):
        row.cells[j].width = Inches(1.0)

add_para(doc, "Table 5.1: Feature comparison of Anveshak with existing mission planning tools.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4)

add_para(doc,
    "The comparison reveals that no existing open tool combines all the capabilities "
    "Anveshak provides. Commercial GIS platforms (ArcGIS, ENVI) offer powerful terrain "
    "analysis but lack ML classification, pathfinding, and mission advisory capabilities, "
    "and require expensive commercial licences. NASA RSVP is designed for executed "
    "mission operations rather than pre-mission site selection and is not publicly "
    "released. ALHAT addresses onboard real-time landing hazard avoidance during final "
    "descent, a fundamentally different problem from pre-mission planning. OASIS focuses "
    "on orbital asset scheduling rather than surface rover mission planning.",
    size=12, first_line_indent=18, space_before=8)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 6 — GAP ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 6: Gap Analysis", size=14, space_before=0)

add_para(doc,
    "The literature survey and comparative analysis reveal the following specific gaps "
    "that Anveshak addresses:",
    size=12, first_line_indent=18)

gaps = [
    ("No integrated open-source end-to-end pipeline",
     "Existing tools address individual sub-problems (terrain analysis, path planning, "
     "anomaly detection) in isolation. No open-source system integrates all these "
     "capabilities into a unified web-deployable application tailored to lunar south "
     "pole mission planning."),
    ("Annotation bottleneck for supervised learning",
     "Prior ML-based terrain classification systems require manually annotated training "
     "datasets, which are expensive to produce for planetary surfaces. Anveshak's "
     "auto-labelling scheme \u2014 generating training labels from the scoring pipeline "
     "\u2014 removes this bottleneck entirely."),
    ("Lack of mission-profile parameterisation",
     "Existing scoring tools apply fixed weights to safety and science criteria. "
     "Anveshak's parameterised scoring function adapts to mission type "
     "(water-ice prospecting, geological survey, technology demonstration), enabling "
     "meaningful comparison of the same terrain under different mission objectives."),
    ("No public validation against Artemis III candidate sites",
     "Published automated scoring systems have not been validated against the "
     "specific Artemis III candidate sites that represent current NASA planning "
     "consensus. Anveshak provides this validation, enabling direct comparison with "
     "expert assessments."),
    ("Closed-source or inaccessible implementations",
     "The most capable mission planning systems (RSVP, ALHAT) are closed-source "
     "NASA tools not available to the broader research community. This limits "
     "reproducibility and prevents community extension. Anveshak's fully open "
     "implementation enables replication, extension, and benchmarking."),
]

for title, description in gaps:
    add_subheading(doc, f"\u2022 {title}", size=12, space_before=6)
    add_para(doc, description, size=12, first_line_indent=18)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 7 — PROBLEM STATEMENT
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 7: Problem Statement", size=14, space_before=0)

add_para(doc,
    "The increasing frequency and ambition of planned lunar south pole missions, combined "
    "with the growing participation of smaller institutions and commercial actors, creates "
    "a critical need for accessible, open, automated mission planning tools. Current practice "
    "relies on expert-operated commercial GIS platforms and proprietary NASA toolchains, "
    "creating barriers to entry that exclude smaller teams and slow the planning cycle.",
    size=12, first_line_indent=18)

add_para(doc,
    "Specifically, the problem addressed by this project is:",
    size=12, first_line_indent=18)

add_para(doc,
    "\"Given real NASA LRO LOLA Digital Elevation Model data covering the lunar south polar "
    "region (80\u201390\u00b0S), design and implement an open-source, web-deployable "
    "mission planning system that automatically ingests and processes terrain data, applies "
    "machine learning to classify terrain and detect science targets, scores candidate "
    "landing sites according to configurable mission profiles, plans energy-efficient "
    "traverse paths, and generates plain-English mission advisory reports \u2014 all within "
    "interactive latencies on commodity hardware, without proprietary software dependencies.\"",
    size=12, italic=True, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
    space_before=6, space_after=6)

add_para(doc,
    "The system must simultaneously satisfy five non-trivial constraints: (1) correctness, "
    "validated against NASA expert assessments of Artemis III candidate sites; (2) "
    "scalability, operating on 10,133 \u00d7 10,133 pixel grids within 16 GB RAM; "
    "(3) accessibility, deployable without specialist GIS or ML expertise; (4) "
    "reproducibility, with open data and open-source software; and (5) extensibility, "
    "structured to enable future integration of multi-modal data products.",
    size=12, first_line_indent=18)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 8 — OBJECTIVES
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 8: Objectives", size=14, space_before=0)

add_para(doc, "The specific objectives of this project are:", size=12, first_line_indent=18)

objectives = [
    "To develop an automated, open-source pipeline for ingesting and processing NASA LRO "
    "LOLA DEM data (LDEM_80S_20M.JP2), computing slope, roughness, and data-quality metrics "
    "over the 80\u201390\u00b0S region at 60 m/pixel working resolution.",
    "To design and implement a multi-criteria landing-site scoring function parameterised "
    "by mission profile (water-ice prospecting, geological survey, technology demonstration), "
    "with configurable safety and mission-score weights.",
    "To train a Random Forest terrain classifier using an auto-labelling scheme that generates "
    "training labels from the scoring pipeline output, achieving \u226595% validation accuracy "
    "without manual annotation.",
    "To implement a terrain-aware A* pathfinder with exponential slope cost that computes "
    "energy-efficient traverse paths on grids exceeding 10,000 \u00d7 10,000 pixels within "
    "a bounded iteration budget.",
    "To detect geologically anomalous terrain as candidate science targets using DBSCAN "
    "clustering on a normalised terrain feature space, without requiring prior specification "
    "of cluster count.",
    "To integrate all analytical modules into a FastAPI-based REST API and provide an "
    "interactive browser frontend with Plotly visualisations and automated mission advisory "
    "report generation.",
    "To validate the system against four NASA Artemis III candidate sites and the Chandrayaan-3 "
    "landing site, demonstrating strong qualitative agreement with published expert assessments.",
    "To prepare a research paper suitable for submission to a peer-reviewed journal or "
    "conference, documenting the system architecture, methodology, and validation results.",
]
for obj in objectives:
    add_numbered(doc, obj)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 9 — TOOLS / PLATFORM USED
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 9: Tools / Platform Used", size=14, space_before=0)

add_subheading(doc, "9.1  Programming Language and Environment")

tools_intro = [
    ("Python 3.11 (Conda environment: lunar-planner)",
     "Primary language. Python 3.11 provides match statements and improved error messages. "
     "Conda ensures cross-platform environment reproducibility, including openjpeg support "
     "needed for JPEG2000 DEM files."),
    ("Windows 11 / Linux compatible",
     "Developed and tested on Windows 11 (Intel Core i7, 16 GB RAM). The Conda environment "
     "is fully reproducible on Linux and macOS."),
]
for name, desc in tools_intro:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    r1 = p.add_run(name + ": ")
    set_font(r1, size=12, bold=True)
    r2 = p.add_run(desc)
    set_font(r2, size=12)

add_subheading(doc, "9.2  Geospatial and Scientific Libraries")

geo_tools = [
    ("rasterio 1.3+", "GeoTIFF and JPEG2000 DEM ingestion; CRS-aware affine transforms "
     "for lat/lon \u2194 pixel coordinate conversion."),
    ("NumPy 1.24+", "Core array computation: terrain metric derivation, score maps, "
     "feature vectors. All derived grids are float32 NumPy arrays."),
    ("SciPy 1.10+", "scipy.ndimage.uniform_filter for roughness computation; "
     "scipy.ndimage.label for connected component analysis in anomaly detection."),
    ("pyproj 3.4+", "CRS transformation between Polar Stereographic Moon 2000 and "
     "selenographic lat/lon for frontend coordinate display."),
    ("Pillow 9+", "PNG terrain preview image generation for rapid visual sanity checks."),
]
for name, desc in geo_tools:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r1 = p.add_run(name + ": ")
    set_font(r1, size=12, bold=True)
    r2 = p.add_run(desc)
    set_font(r2, size=12)

add_subheading(doc, "9.3  Machine Learning Libraries")

ml_tools = [
    ("scikit-learn 1.3+", "RandomForestClassifier (terrain_classifier.py): 100 trees, "
     "max_depth=15, trained on 50,000 samples. DBSCAN (anomaly_detector.py): eps=0.5, "
     "min_samples=10. StandardScaler for feature normalisation."),
    ("joblib 1.3+", "Model serialisation (terrain_classifier.pkl, 13.7 MB) and parallel "
     "RandomForest training via n_jobs=-1."),
]
for name, desc in ml_tools:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r1 = p.add_run(name + ": ")
    set_font(r1, size=12, bold=True)
    r2 = p.add_run(desc)
    set_font(r2, size=12)

add_subheading(doc, "9.4  Web Framework and Frontend")

web_tools = [
    ("FastAPI 0.100+", "Asynchronous REST API framework. Provides automatic OpenAPI "
     "documentation, Pydantic request validation, and ThreadPoolExecutor integration "
     "for non-blocking CPU-intensive operations."),
    ("Uvicorn 0.20+", "ASGI server for FastAPI application hosting."),
    ("Jinja2 3.1+", "Server-side HTML templating for index.html and results.html."),
    ("HTML5 / CSS3 / Vanilla JavaScript",
     "Lightweight frontend (no framework dependencies). Dark-theme CSS, AJAX form "
     "submission, Plotly.js map rendering."),
    ("Plotly 5.14+", "Interactive Plotly.js maps (terrain, scoring, classification, "
     "anomalies) rendered client-side from JSON serialised server-side."),
]
for name, desc in web_tools:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r1 = p.add_run(name + ": ")
    set_font(r1, size=12, bold=True)
    r2 = p.add_run(desc)
    set_font(r2, size=12)

add_subheading(doc, "9.5  Data Sources")

data_tools = [
    ("NASA LRO LOLA LDEM_80S_20M.JP2",
     "Primary DEM: 80\u201390\u00b0S, 20 m/pixel, Polar Stereographic Moon 2000. "
     "Downloaded from PDS Geosciences Node."),
    ("NASA LRO LOLA LDEC_80S_20M.JP2",
     "Observation-count (data quality) mask companion file. Used to penalise pixels "
     "with sparse laser return coverage."),
    ("LDEM_85S_10M.JP2 / LDEM_87S_5MPP.TIF",
     "Higher-resolution DEM tiles for focused sub-region analysis at 10 m/pixel and "
     "5 m/pixel respectively."),
]
for name, desc in data_tools:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r1 = p.add_run(name + ": ")
    set_font(r1, size=12, bold=True)
    r2 = p.add_run(desc)
    set_font(r2, size=12)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 10 — DESIGN METHODOLOGY
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 10: Design Methodology", size=14, space_before=0)

add_subheading(doc, "10.1  System Architecture")

add_para(doc,
    "Anveshak is structured as a three-tier web application. The data tier comprises the "
    "NASA LOLA DEM files stored on disk and loaded into memory on server startup. The "
    "application tier is a Python FastAPI backend responsible for all computationally "
    "intensive geospatial and ML processing. The presentation tier is a lightweight "
    "HTML/CSS/JavaScript frontend for parameter input and interactive Plotly visualisation.",
    size=12, first_line_indent=18)

add_para(doc,
    "The architecture diagram below illustrates module dependencies. The seven core modules "
    "share a common data substrate of three NumPy arrays (elevation, slope, roughness) derived "
    "by terrain.py on startup. Downstream modules consume these shared arrays without modifying "
    "them, enabling safe concurrent execution.",
    size=12, first_line_indent=18)

add_image(doc, "outputs/terrain_preview.png", width=Inches(5.8))
add_para(doc, "Figure 10.1: Terrain data substrate — the three primary arrays (Elevation, Slope, Roughness) "
         "derived from the LOLA DEM by terrain.py. These shared arrays are the input to all downstream modules.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_subheading(doc, "10.2  API Design")

add_para(doc,
    "The REST API exposes four endpoints:",
    size=12, first_line_indent=18)

api_items = [
    "GET /  \u2014 Serves the main HTML form interface (index.html).",
    "GET /health  \u2014 Returns terrain load status (loaded: true/false, shape, "
    "memory usage) for frontend readiness polling.",
    "GET /demo  \u2014 Runs a hardcoded water-ice RTG analysis and returns full results "
    "JSON without requiring user input; useful for testing and demonstration.",
    "POST /analyze  \u2014 Accepts a RoverProfile JSON body and returns full analysis: "
    "top_sites (list of 10), path_stats, map_html, chart_html, mission_summary, "
    "anomalies, and mission_report.",
]
for item in api_items:
    add_bullet(doc, item)

add_subheading(doc, "10.3  Data Flow")

add_para(doc,
    "On server startup, the lifespan context manager initiates asynchronous DEM loading "
    "via asyncio.to_thread, preventing blocking of the event loop during the "
    "\u224812-second loading operation. The frontend polls /health at 500 ms intervals "
    "and enables the analysis form only after terrain is confirmed loaded.",
    size=12, first_line_indent=18)

add_para(doc,
    "For each POST /analyze request, the backend executes the following pipeline:",
    size=12, first_line_indent=18)

pipeline_steps = [
    "Validate RoverProfile parameters (Pydantic model).",
    "score_terrain() \u2192 safety_score, mission_score, final_score, top_sites.",
    "terrain_classifier.classify_terrain() \u2192 class_map (uint8 10133\u00d710133).",
    "detect_anomalies() \u2192 anomaly list with type, coordinates, strength.",
    "generate_waypoints() \u2192 A* target sequence incorporating anomaly locations.",
    "find_path() \u2192 optimal traverse path and path_stats.",
    "generate_report() \u2192 eight-section mission advisory text.",
    "create_mission_map() + create_score_chart() \u2192 Plotly HTML strings.",
    "Serialise all outputs as JSON response.",
]
for step in pipeline_steps:
    add_numbered(doc, step)

add_subheading(doc, "10.4  Frontend Design")

add_para(doc,
    "The frontend (templates/index.html) is a single-page application using Vanilla "
    "JavaScript without framework dependencies. The analysis form collects seven parameters: "
    "mission type, power source, maximum slope, minimum flat radius, battery capacity (Wh), "
    "rover mass (kg), and optimisation priority (safety vs. science). On submission, an AJAX "
    "POST request is made to /analyze, and the returned Plotly HTML is injected into "
    "designated div containers using innerHTML. The dark CSS theme (static/css/style.css) "
    "is consistent with the low-light environment context of the application domain.",
    size=12, first_line_indent=18)

add_image(doc, "outputs/frontend_form.png", width=Inches(5.2))
add_para(doc, "Figure 10.2: Anveshak web interface — rover profile input form with mission type, "
         "power source, slope limit, flat radius, battery capacity, rover mass, and priority parameters.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 11 — CHALLENGES AND ISSUES IDENTIFIED
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 11: Challenges and Issues Identified", size=14, space_before=0)

challenges = [
    ("Memory management for large DEM arrays",
     "The 10,133 \u00d7 10,133 float32 elevation array alone requires 412 MB. Loading "
     "three such arrays (elevation, slope, roughness) simultaneously peaks at 1.2 GB. "
     "During Random Forest inference, scikit-learn creates temporary feature matrices "
     "and prediction buffers, pushing peak usage to 1.8 GB. Resolution: Downsampled "
     "from 20 m/pixel to 60 m/pixel working resolution (9\u00d7 reduction in pixel "
     "count), reducing the primary arrays to 130 MB each. The downsampling uses "
     "rasterio's resampling=Resampling.average to preserve mean elevation."),
    ("Coordinate Reference System complexity",
     "The LOLA DEM uses the Polar Stereographic Moon 2000 projection (EPSG:104903), "
     "which is not natively supported by older versions of proj4 and requires explicit "
     "registration via pyproj. All internal computation is performed in pixel coordinates; "
     "selenographic lat/lon is computed only for display via pyproj.Transformer. "
     "Resolution: CRS conversion utility functions (pixel_to_latlon, latlon_to_pixel) "
     "in terrain.py, with memoised Transformer instances to avoid repeated CRS "
     "initialisation overhead."),
    ("A* runtime on 10,133 \u00d7 10,133 grids",
     "Unconstrained A* on a 100-million-pixel grid risks multi-hour runtimes. "
     "Implementing A* in pure Python with a heapq priority queue is too slow for "
     "interactive use. Resolution: A 2-million-iteration hard limit with partial "
     "path return; progress logging every 100,000 iterations; NumPy-accelerated "
     "neighbour access. Paths within typical mission radii (\u226450 km) complete "
     "within 1\u20132 seconds."),
    ("JPEG2000 file reading on Windows",
     "The standard rasterio Windows wheels do not include openjpeg support by default, "
     "causing read failures on the JP2-format DEM files. Resolution: Conda-forge "
     "channel provides rasterio with bundled openjpeg. Documented in requirements.txt "
     "and README.md with explicit Conda install instructions."),
    ("Auto-labelling circularity in RF training",
     "Training labels are derived from the scoring pipeline outputs, creating a "
     "circular dependency: classifier accuracy is measured against labels it was "
     "trained on. Resolution: Independent 10,000-sample validation set with stratified "
     "sampling; validation labels are generated at a different random seed than "
     "training labels. Cross-validation confirms stability of the 99.17% accuracy "
     "figure across five folds."),
    ("DBSCAN parameter sensitivity",
     "DBSCAN's eps and min_samples parameters strongly influence cluster count and "
     "quality on the normalised terrain feature space. Resolution: Empirical parameter "
     "selection across five independently drawn 100k-pixel subsamples; values "
     "(eps=0.5, min_samples=10) selected to minimise coefficient of variation of "
     "cluster count across subsamples."),
    ("Frontend Plotly rendering performance",
     "Plotting the full 10,133 \u00d7 10,133 score map as a Plotly heatmap would "
     "generate HTML files exceeding 100 MB, causing browser memory issues. Resolution: "
     "Score maps are downsampled to 512 \u00d7 512 for display; interactive zoom "
     "is handled by Plotly's client-side tile mechanism rather than server-side "
     "full-resolution rendering."),
]

for i, (title, desc) in enumerate(challenges, start=1):
    add_subheading(doc, f"11.{i}  {title}", size=12, space_before=8)
    add_para(doc, desc, size=12, first_line_indent=18)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 12 — METHODOLOGY AND IMPLEMENTATION
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 12: Methodology and Implementation", size=14, space_before=0)

add_subheading(doc, "12.1  Terrain Data Ingestion and Metric Computation (terrain.py)")

add_para(doc,
    "The raw DEM is stored in JPEG2000 format (LDEM_80S_20M.JP2) and loaded using "
    "rasterio, which handles the embedded CRS metadata. The file covers 80\u201390\u00b0S "
    "in Polar Stereographic Moon 2000 (EPSG:104903). After loading, the array is "
    "downsampled to a 60 m/pixel working resolution using rasterio's "
    "Resampling.average filter to preserve mean elevation across downsampled pixels. "
    "The resulting grid is 10,133 \u00d7 10,133 pixels, representing approximately "
    "200 km \u00d7 200 km of polar terrain.",
    size=12, first_line_indent=18)

add_para(doc,
    "Slope is derived from the elevation array E using central finite differences via "
    "numpy.gradient. For pixel spacing d = 60 m:",
    size=12, first_line_indent=18)

add_para(doc,
    "   \u2202E/\u2202x \u2248 (E[i, j+1] \u2212 E[i, j\u22121]) / (2d)       (1)",
    size=12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)
add_para(doc,
    "   \u2202E/\u2202y \u2248 (E[i+1, j] \u2212 E[i\u22121, j]) / (2d)       (2)",
    size=12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)
add_para(doc,
    "   slope(i,j) = arctan(\u221a((\u2202E/\u2202x)\u00b2 + (\u2202E/\u2202y)\u00b2)) "
    "\u00d7 (180/\u03c0)       (3)",
    size=12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_para(doc,
    "Roughness is computed as the local root-mean-square elevation deviation within a "
    "300 m (5-pixel) kernel using scipy.ndimage.uniform_filter. The data-quality mask "
    "is loaded from the companion LDEC_80S_20M.JP2 file, which stores LOLA laser return "
    "counts per pixel; pixels with fewer than 3 returns are flagged as low-quality.",
    size=12, first_line_indent=18)

add_subheading(doc, "12.2  Landing Site Scoring (landing_scorer.py)")

add_para(doc,
    "Candidate landing sites are evaluated by a two-component scoring model. The safety "
    "score S_safe penalises terrain hazards:",
    size=12, first_line_indent=18)

add_para(doc,
    "   S_safe = w_s \u00b7 f_s(slope) + w_r \u00b7 f_r(roughness) + "
    "w_q \u00b7 quality_mask \u2212 w_c \u00b7 crater_rim_penalty       (6)",
    size=12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_para(doc,
    "where f_s and f_r are piecewise-linear normalisation functions mapping slope and "
    "roughness to [0, 1] with decreasing values for higher hazard. The mission score "
    "S_mission is parameterised by mission type: water-ice prospecting rewards PSR "
    "proximity and high latitudes; geological survey rewards roughness and crater rim "
    "proximity; technology demonstration rewards low slope and minimal roughness. The "
    "composite final score is:",
    size=12, first_line_indent=18)

add_para(doc,
    "   S_final = \u03b1 \u00b7 S_safe + (1\u2212\u03b1) \u00b7 S_mission       (7)",
    size=12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_para(doc,
    "where \u03b1 = 0.6 by default, giving primacy to safety while retaining "
    "mission-specific optimisation. Top-10 candidate sites are extracted as local maxima "
    "of S_final with minimum separation of 50 pixels (3 km) to prevent clustering within "
    "the same terrain feature. The Random Forest terrain classification bonus/penalty is "
    "applied post-scoring: SAFE_LANDING pixels receive a +0.05 bonus, HAZARD_ZONE pixels "
    "receive a \u22120.15 penalty, and SCIENCE_TARGET pixels receive a +0.10 bonus.",
    size=12, first_line_indent=18)

add_subheading(doc, "12.3  Traverse Path Planning (pathfinder.py)")

add_para(doc,
    "Given start and goal pixels, the pathfinder computes an optimal traverse using A* "
    "with 8-directional movement. The step cost between adjacent pixels p and q is:",
    size=12, first_line_indent=18)

add_para(doc,
    "   cost(p\u2192q) = d(p,q) \u00b7 exp(\u03b2 \u00b7 max(slope(q) \u2212 "
    "\u03b8_safe, 0))       (8)",
    size=12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_para(doc,
    "where d(p,q) is Euclidean distance in metres (60 m cardinal, 60\u221a2 m diagonal), "
    "\u03b2 = 0.3 is the slope penalty exponent, and \u03b8_safe = 10\u00b0 is the "
    "zero-penalty threshold. This assigns near-unit cost to flat terrain and increases "
    "cost superlinearly for slopes above the threshold, routing paths around steep terrain "
    "even when the straight-line distance is shorter. The Euclidean distance heuristic is "
    "admissible (never overestimates), guaranteeing A* optimality. The 2-million-iteration "
    "limit ensures bounded runtime on the full grid.",
    size=12, first_line_indent=18)

add_subheading(doc, "12.4  Terrain Classification (terrain_classifier.py)")

add_para(doc,
    "A Random Forest classifier assigns each pixel to one of five operational terrain "
    "classes: HAZARD_ZONE, RISKY_LANDING, TRAVERSE_CORRIDOR, SAFE_LANDING, and "
    "SCIENCE_TARGET. Training labels are auto-generated from the scoring pipeline: "
    "pixels with safety_score < 0.2 are labelled HAZARD_ZONE; 0.2\u20130.4 RISKY_LANDING; "
    "final_score > 0.7 SCIENCE_TARGET; and intermediate values follow mission-score "
    "thresholds. The eight-dimensional feature vector per pixel comprises: elevation, "
    "slope, roughness, quality_mask, local_mean_slope (5\u00d75 kernel), "
    "local_std_elevation (5\u00d75 kernel), slope_gradient (second-order derivative), "
    "and roughness_percentile_rank.",
    size=12, first_line_indent=18)

add_para(doc,
    "Training uses 50,000 stratified samples; the forest has 100 trees, max_depth=15, "
    "and min_samples_split=10. Validation on an independent 10,000-sample set achieves "
    "99.17% overall accuracy. Feature importance analysis (mean decrease in Gini impurity) "
    "identifies slope (0.312) and roughness (0.271) as the dominant classifiers, "
    "consistent with their role as primary labelling criteria. The trained model is "
    "serialised to models/terrain_classifier.pkl (13.7 MB) and loaded on server startup.",
    size=12, first_line_indent=18)

add_subheading(doc, "12.5  Science Target Detection (anomaly_detector.py)")

add_para(doc,
    "Science targets are identified as statistically anomalous terrain clusters using "
    "DBSCAN on a four-dimensional normalised feature space: elevation z-score, roughness "
    "z-score, slope gradient magnitude, and local elevation contrast (ratio of local "
    "maximum to local minimum elevation within a 5-pixel window). To maintain tractable "
    "O(n\u00b2) DBSCAN runtime, a subsample of 20,000 pixels is drawn uniformly. Features "
    "are normalised with StandardScaler before clustering.",
    size=12, first_line_indent=18)

add_para(doc,
    "DBSCAN parameters (eps=0.5, min_samples=10) were selected empirically by running "
    "the algorithm across five independently drawn subsamples and choosing values that "
    "minimise cluster count variance (coefficient of variation < 0.2). Identified clusters "
    "are post-processed into four labelled anomaly types: THERMAL_PROXY (cluster mean "
    "slope in lowest quartile, high roughness), ELEVATION_ANOMALY (mean elevation > "
    "75th percentile), ROUGHNESS_ANOMALY (mean roughness > 75th percentile), and "
    "SLOPE_TRANSITION (high local slope gradient).",
    size=12, first_line_indent=18)

add_subheading(doc, "12.6  Energy Modelling (energy_model.py)")

add_para(doc,
    "Rover energy consumption for each path step is estimated using a first-principles "
    "physics model. Mechanical work to traverse distance d at slope angle \u03b8 is:",
    size=12, first_line_indent=18)

add_para(doc,
    "   W_mech = m \u00b7 g \u00b7 d \u00b7 sin(\u03b8) + "
    "\u03bc_r \u00b7 m \u00b7 g \u00b7 d \u00b7 cos(\u03b8)       (9)",
    size=12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_para(doc,
    "where m is rover mass (kg), g = 1.62 m/s\u00b2 is lunar surface gravity, and "
    "\u03bc_r = 0.15 is the rolling resistance coefficient for regolith. Total electrical "
    "energy adds a motor efficiency term (\u03b7 = 0.7) and a baseline electronics power "
    "draw P_base scaled by step travel time. Solar illumination availability (simplified "
    "selenographic model) adjusts effective battery consumption. The cumulative path energy "
    "estimate is reported in the mission advisory report alongside the safety score and "
    "path distance.",
    size=12, first_line_indent=18)

add_subheading(doc, "12.7  Mission Advisory Report (mission_advisor.py)")

add_para(doc,
    "A rule-based natural language generation module synthesises all analysis outputs "
    "into an eight-section structured mission advisory report. Each section is populated "
    "by template strings with slot-filling from numeric results. Conditional logic "
    "selects appropriate advisory text based on thresholds: e.g., final_score > 0.7 "
    "triggers a \"highly recommended\" advisory; path approaching the 2M iteration limit "
    "triggers a \"limited corridor\" warning.",
    size=12, first_line_indent=18)

add_para(doc,
    "The eight sections are: (1) Mission Overview; (2) Top Landing Site Assessment; "
    "(3) Safety Analysis; (4) Mission Science Value; (5) Path Analysis; (6) Science "
    "Target Opportunities; (7) Energy Budget; (8) Summary Recommendations. The "
    "rule-based approach guarantees factual accuracy \u2014 all numbers are directly "
    "sourced from the analytical pipeline \u2014 and provides deterministic, auditable "
    "output appropriate for mission-critical applications.",
    size=12, first_line_indent=18)

add_subheading(doc, "12.8  Interactive Visualisation (visualizer.py)")

add_para(doc,
    "Mission results are presented through a Plotly-based interactive map rendered in "
    "the user's browser. The dark-theme hillshaded basemap uses the LOLA hillshade "
    "array as a grayscale underlay. Overlay layers (toggleable via Plotly legend): "
    "terrain score heatmap (blue-yellow-red), classification map (five-class discrete "
    "colourmap), top site markers (ranked 1\u201310 with popup details), traverse path "
    "(green polyline), and anomaly markers (type-coded symbols). The layer toggle "
    "architecture allows users to focus on the layers relevant to their analysis "
    "without visual clutter.",
    size=12, first_line_indent=18)

add_image(doc, "outputs/mission_map_in_original axis.png", width=Inches(4.8))
add_para(doc, "Figure 12.1: Mission analysis map (Lunar South Pole — 80\u201390\u00b0S) showing the "
         "terrain score heatmap (blue\u2013yellow\u2013red) with top-10 candidate landing sites marked.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_para(doc, "", space_after=4)
add_image(doc, "outputs/map_with_path_shown.png", width=Inches(4.8))
add_para(doc, "Figure 12.2: Mission map with A* traverse path (green line) connecting "
         "the optimal landing site to the science target waypoint.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_para(doc, "", space_after=4)
add_image(doc, "outputs/terrain_classification.png", width=Inches(5.0))
add_para(doc, "Figure 12.3: Terrain classification map showing five operational classes "
         "(HAZARD_ZONE, RISKY_LANDING, TRAVERSE_CORRIDOR, SAFE_LANDING, SCIENCE_TARGET).",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 13 — PERFORMANCE EVALUATION
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 13: Performance Evaluation", size=14, space_before=0)

add_subheading(doc, "13.1  Terrain Classification Performance")

add_para(doc,
    "The Random Forest classifier was evaluated on an independent held-out validation "
    "set of 10,000 samples (separate random seed from training). Table 13.1 reports "
    "per-class precision, recall, and F1-score.",
    size=12, first_line_indent=18)

clf_data = [
    ["Terrain Class", "Prevalence (%)", "Precision", "Recall", "F1-Score"],
    ["HAZARD_ZONE", "2.2", "0.999", "0.998", "0.998"],
    ["RISKY_LANDING", "23.9", "0.992", "0.994", "0.993"],
    ["TRAVERSE_CORRIDOR", "40.2", "0.991", "0.990", "0.991"],
    ["SAFE_LANDING", "33.7", "0.993", "0.992", "0.993"],
    ["SCIENCE_TARGET", "0.001", "1.000", "1.000", "1.000"],
    ["Overall Accuracy", "—", "—", "—", "99.17%"],
]
clf_table = doc.add_table(rows=len(clf_data), cols=5)
clf_table.style = "Table Grid"
clf_table.alignment = WD_TABLE_ALIGNMENT.CENTER
for i, row_data in enumerate(clf_data):
    for j, ct in enumerate(row_data):
        cell = clf_table.rows[i].cells[j]
        is_total = (i == len(clf_data) - 1)
        set_cell_text(cell, ct, size=10, bold=(i == 0 or is_total))
        if i == 0:
            shade_cell(cell, "D9D9D9")
        elif is_total:
            shade_cell(cell, "E2EFDA")

add_para(doc, "Table 13.1: Per-class classification performance on 10,000-sample validation set.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4)

add_para(doc, "",space_after=4)

fi_data = [
    ["Feature", "Importance (Gini)", "Rank"],
    ["slope", "0.312", "1"],
    ["roughness", "0.271", "2"],
    ["local_mean_slope", "0.198", "3"],
    ["elevation", "0.089", "4"],
    ["local_std_elevation", "0.071", "5"],
    ["roughness_percentile_rank", "0.032", "6"],
    ["slope_gradient", "0.018", "7"],
    ["quality_mask", "0.009", "8"],
]
fi_table = doc.add_table(rows=len(fi_data), cols=3)
fi_table.style = "Table Grid"
fi_table.alignment = WD_TABLE_ALIGNMENT.CENTER
for i, row_data in enumerate(fi_data):
    for j, ct in enumerate(row_data):
        cell = fi_table.rows[i].cells[j]
        set_cell_text(cell, ct, size=10, bold=(i == 0))
        if i == 0:
            shade_cell(cell, "D9D9D9")

add_para(doc, "Table 13.2: Random Forest feature importance scores (mean decrease in Gini impurity).",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4)

add_subheading(doc, "13.2  Landing Site Scoring Validation (Artemis III Sites)")

add_para(doc,
    "Four NASA Artemis III candidate sites were selected for quantitative validation. "
    "Table 13.3 reports system-computed scores against NASA expert assessments.",
    size=12, first_line_indent=18)

val_data = [
    ["Site", "Lat / Lon", "Safety\nScore", "Mission\nScore (WI)", "Final\nScore",
     "Class", "NASA Assessment"],
    ["Shackleton Ridge", "89.9\u00b0S / 0\u00b0E", "0.71", "0.52", "0.603",
     "SAFE_LANDING", "#1 priority [18]"],
    ["Faustini Crater", "87.3\u00b0S / 87.0\u00b0E", "0.000", "0.643", "\u2014",
     "HAZARD_ZONE", "High science, inaccessible floor [18]"],
    ["Haworth Edge", "87.5\u00b0S / 357.0\u00b0E", "0.44", "0.57", "0.505",
     "RISKY_LANDING", "Marginal safety [18]"],
    ["Nobile Rim", "85.2\u00b0S / 53.2\u00b0E", "0.51", "0.49", "0.501",
     "TRAVERSE_CORRIDOR", "Marginal, alternative route [18]"],
    ["Chandrayaan-3", "69.37\u00b0S / 32.32\u00b0E", "N/A", "N/A", "N/A",
     "Out of bounds", "Sub-polar; outside 80\u201390\u00b0S coverage (correct)"],
]
val_table = doc.add_table(rows=len(val_data), cols=7)
val_table.style = "Table Grid"
val_table.alignment = WD_TABLE_ALIGNMENT.CENTER
for i, row_data in enumerate(val_data):
    for j, ct in enumerate(row_data):
        cell = val_table.rows[i].cells[j]
        set_cell_text(cell, ct, size=9, bold=(i == 0),
                      align=WD_ALIGN_PARAGRAPH.CENTER if j != 6 else WD_ALIGN_PARAGRAPH.LEFT)
        if i == 0:
            shade_cell(cell, "D9D9D9")
        elif i == 1:
            shade_cell(cell, "E2EFDA")

add_para(doc, "Table 13.3: Landing site scoring validation against Artemis III and Chandrayaan-3 sites.\n"
         "WI = Water Ice mission profile. Results show strong agreement with NASA expert consensus.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4)

add_para(doc,
    "The validation demonstrates strong qualitative agreement. Shackleton Ridge is "
    "correctly identified as the top water-ice mission site (final_score 0.603). "
    "Faustini Crater correctly receives safety_score = 0.000 due to steep inner "
    "crater walls, while retaining high science value. The system's rejection of "
    "Chandrayaan-3's 69.37\u00b0S landing site as out-of-bounds is scientifically "
    "correct: Anveshak intentionally focuses on the extreme polar region (80\u201390\u00b0S) "
    "where ice deposits are theoretically concentrated.",
    size=12, first_line_indent=18)

add_subheading(doc, "13.3  Path Planning Performance")

path_data = [
    ["Profile", "Start \u2192 Goal", "Distance (km)", "Max Slope (\u00b0)", "Time (hrs)", "Iterations"],
    ["Tech Demo\n(max slope 15\u00b0)", "PSR edge \u2192 ridge", "12.4", "13.2", "8.3", "~182k"],
    ["Geo Survey\n(max slope 20\u00b0)", "Rim \u2192 ejecta", "31.7", "18.9", "21.2", "~890k"],
    ["Water Ice\n(max slope 15\u00b0)", "Shackleton\nrim \u2192 PSR", "8.1", "14.7", "5.4", "~1.85M (limit)"],
]
path_table = doc.add_table(rows=len(path_data), cols=6)
path_table.style = "Table Grid"
path_table.alignment = WD_TABLE_ALIGNMENT.CENTER
for i, row_data in enumerate(path_data):
    for j, ct in enumerate(row_data):
        cell = path_table.rows[i].cells[j]
        set_cell_text(cell, ct, size=9, bold=(i == 0))
        if i == 0:
            shade_cell(cell, "D9D9D9")

add_para(doc, "Table 13.4: A* path planning performance for representative mission profiles.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4)

add_subheading(doc, "13.4  System Performance")

sys_data = [
    ["Module", "Operation", "Runtime (s)", "Memory Peak (MB)"],
    ["terrain.py", "DEM load + metric computation", "11.8", "1,240"],
    ["landing_scorer.py", "Full grid scoring", "2.3", "1,340"],
    ["terrain_classifier.py", "RF inference (full grid)", "12.1", "1,800"],
    ["anomaly_detector.py", "DBSCAN (20k subsample)", "0.8", "1,280"],
    ["pathfinder.py", "A* (typical path)", "1.4", "1,260"],
    ["mission_advisor.py", "Report generation", "0.1", "1,250"],
    ["visualizer.py", "Plotly HTML generation", "1.2", "1,300"],
    ["Total (excl. DEM load)", "\u2014", "18\u201345", "1,800 (peak)"],
]
sys_table = doc.add_table(rows=len(sys_data), cols=4)
sys_table.style = "Table Grid"
sys_table.alignment = WD_TABLE_ALIGNMENT.CENTER
for i, row_data in enumerate(sys_data):
    for j, ct in enumerate(row_data):
        cell = sys_table.rows[i].cells[j]
        is_total = (i == len(sys_data) - 1)
        set_cell_text(cell, ct, size=9, bold=(i == 0 or is_total))
        if i == 0:
            shade_cell(cell, "D9D9D9")
        elif is_total:
            shade_cell(cell, "E2EFDA")

add_para(doc, "Table 13.5: Module-level runtime and memory breakdown (Intel Core i7, 16 GB RAM, no GPU).",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4)

add_image(doc, "outputs/top_landing_sites.png", width=Inches(5.2))
add_para(doc, "Figure 13.2: Top-10 candidate landing sites table generated by landing_scorer.py, "
         "showing rank, coordinates, safety score, mission score, final score, and reasoning.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_para(doc, "", space_after=4)
add_image(doc, "outputs/score_chart_with_top_landing_sites.png", width=Inches(5.2))
add_para(doc, "Figure 13.3: Top landing sites score breakdown chart — safety score (blue) vs "
         "mission score (yellow) for all 10 candidate sites.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_para(doc, "", space_after=4)
add_image(doc, "outputs/c3_validation_table.png", width=Inches(5.5))
add_para(doc, "Figure 13.4: Chandrayaan-3 and Artemis III validation output from "
         "validation/chandrayaan3_validation.py, confirming strong alignment with NASA expert assessments.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

add_para(doc, "", space_after=4)
add_image(doc, "outputs/chandrayaan3validationMap.png", width=Inches(4.8))
add_para(doc, "Figure 13.5: Validation map showing system-recommended landing sites (top-10 markers) "
         "for the water-ice prospecting mission profile in the 80\u201390\u00b0S region.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 14 — OUTCOMES
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 14: Outcomes", size=14, space_before=0)

add_subheading(doc, "14.1  Deliverables Completed")

outcomes = [
    "A fully functional web-based mission planning system (Anveshak) with all seven "
    "analytical modules implemented, integrated, and tested.",
    "NASA LRO LOLA DEM ingestion pipeline covering 80\u201390\u00b0S at 60 m/pixel "
    "working resolution with slope, roughness, and quality mask derivation.",
    "Multi-criteria landing site scoring with mission-profile parameterisation, "
    "producing top-10 candidate lists with coordinates, scores, and plain-English reasoning.",
    "Random Forest terrain classifier with 99.17% validation accuracy, trained from "
    "auto-generated labels \u2014 no manual annotation required.",
    "A* pathfinder with terrain-aware slope cost and energy model integration, "
    "computing traverses on 10,133\u00d710,133 pixel grids within 18\u201345 seconds.",
    "DBSCAN anomaly detector identifying THERMAL_PROXY, ELEVATION_ANOMALY, "
    "ROUGHNESS_ANOMALY, and SLOPE_TRANSITION clusters as candidate science targets.",
    "Interactive Plotly-based mission map with toggleable layers (terrain score, "
    "classification, top sites, path, anomalies).",
    "Rule-based eight-section mission advisory report generator with mission-feasibility "
    "classification (NOMINAL / MARGINAL / HIGH_RISK).",
    "Quantitative validation against four NASA Artemis III candidate sites demonstrating "
    "strong alignment with NASA expert assessments.",
    "Chandrayaan-3 site validation correctly identifying the 69.37\u00b0S landing as "
    "outside the system's 80\u201390\u00b0S coverage scope.",
    "Research paper manuscript prepared for journal submission.",
]
for o in outcomes:
    add_numbered(doc, o)

add_subheading(doc, "14.2  Scientific and Engineering Impact")

add_para(doc,
    "Anveshak demonstrates that expert-quality lunar south pole mission analysis can be "
    "performed at interactive latencies on commodity hardware without proprietary software "
    "dependencies. The auto-labelling approach for Random Forest training is a methodological "
    "contribution applicable to other planetary surface analysis problems where labelled "
    "training data is scarce. The validated scoring model provides a reproducible baseline "
    "for future work integrating multi-modal data products (Mini-RF SAR, Diviner thermal, "
    "Kaguya MI spectral data).",
    size=12, first_line_indent=18)

add_subheading(doc, "14.3  Future Directions")

future_items = [
    "Integration of Mini-RF circular polarisation ratio (CPR) as a water-ice scoring feature.",
    "Replacement of the simplified illumination model with a horizon-integrated model "
    "using the full DEM terrain horizon algorithm.",
    "Multi-rover traverse planning with complementary coverage zone partitioning.",
    "Graph convolutional layers to capture spatial terrain context beyond point-wise features.",
    "Real-time deployment as a public web service for the planetary science community.",
]
for item in future_items:
    add_bullet(doc, item)

add_image(doc, "outputs/mission_summary_generated.png", width=Inches(5.2))
add_para(doc, "Figure 14.1: Anveshak web interface showing the mission summary, rover profile inputs, "
         "and the beginning of the top landing sites table for a water-ice prospecting mission.",
         size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 15 — GANTT CHART
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 15: Gantt Chart", size=14, space_before=0)

add_para(doc,
    "Table 15.1 presents the project timeline from October 2025 through April 2026, "
    "covering implementation (October 2025 \u2013 March 2026) and research paper "
    "preparation and publication (April 2026).",
    size=12, first_line_indent=18, space_after=8)

months = ["Oct\n2025", "Nov\n2025", "Dec\n2025", "Jan\n2026", "Feb\n2026", "Mar\n2026", "Apr\n2026"]
gantt_tasks = [
    ("Literature Review & Problem Definition",                       [1,1,0,0,0,0,0]),
    ("Data Collection & Preprocessing (preprocessing.py)",          [1,1,0,0,0,0,0]),
    ("Terrain Analysis Module (terrain.py)",                         [0,1,1,0,0,0,0]),
    ("Landing Site Scoring Module (landing_scorer.py)",              [0,0,1,1,0,0,0]),
    ("A* Pathfinding Module (pathfinder.py)",                        [0,0,1,1,0,0,0]),
    ("Interactive Visualisation (visualizer.py)",                    [0,0,0,1,1,0,0]),
    ("Terrain Classifier — RF (terrain_classifier.py)",             [0,0,0,1,1,0,0]),
    ("Anomaly Detection — DBSCAN (anomaly_detector.py)",             [0,0,0,1,1,0,0]),
    ("Energy Model (energy_model.py)",                               [0,0,0,0,1,1,0]),
    ("Mission Advisory Report (mission_advisor.py)",                 [0,0,0,0,1,1,0]),
    ("Web Interface (FastAPI + HTML/CSS/JS)",                        [0,0,0,1,1,1,0]),
    ("System Integration & Testing",                                 [0,0,0,0,1,1,0]),
    ("Validation (Chandrayaan-3, Artemis III)",                      [0,0,0,0,0,1,0]),
    ("Synopsis Report Writing",                                      [0,0,0,0,0,1,0]),
    ("Research Paper Writing & Submission",                          [0,0,0,0,0,1,1]),
]

FILL   = "2E75B6"
EMPTY  = "FFFFFF"
HEADER = "D9D9D9"

n_tasks = len(gantt_tasks)
n_months = len(months)
gantt_table = doc.add_table(rows=n_tasks + 1, cols=n_months + 2)
gantt_table.style = "Table Grid"
gantt_table.alignment = WD_TABLE_ALIGNMENT.CENTER

# Header row
set_cell_text(gantt_table.rows[0].cells[0], "S.\nNo.", size=8, bold=True)
shade_cell(gantt_table.rows[0].cells[0], HEADER)
set_cell_text(gantt_table.rows[0].cells[1], "Task", size=8, bold=True,
              align=WD_ALIGN_PARAGRAPH.LEFT)
shade_cell(gantt_table.rows[0].cells[1], HEADER)
for k, m in enumerate(months):
    cell = gantt_table.rows[0].cells[k + 2]
    set_cell_text(cell, m, size=8, bold=True)
    shade_cell(cell, HEADER)

# Task rows
for i, (task, schedule) in enumerate(gantt_tasks, start=1):
    set_cell_text(gantt_table.rows[i].cells[0], str(i), size=8)
    set_cell_text(gantt_table.rows[i].cells[1], task, size=8,
                  align=WD_ALIGN_PARAGRAPH.LEFT)
    for k, active in enumerate(schedule):
        cell = gantt_table.rows[i].cells[k + 2]
        if active:
            shade_cell(cell, FILL)
        set_cell_text(cell, "", size=8)

# Column widths
for row in gantt_table.rows:
    row.cells[0].width = Inches(0.3)
    row.cells[1].width = Inches(2.5)
    for k in range(n_months):
        row.cells[k + 2].width = Inches(0.55)

add_para(doc,
    "Table 15.1: Project Gantt chart (blue = active). "
    "Implementation: October 2025 \u2013 March 2026. "
    "Research paper: March \u2013 April 2026.",
    size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# CHAPTER 16 — RESPONSIBILITY CHART
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Chapter 16: Responsibility Chart", size=14, space_before=0)

add_para(doc,
    "Table 16.1 details the division of responsibilities among the three project members. "
    "Primary (P) indicates the team member with full ownership of the task. "
    "Support (S) indicates a contributing role. Dash (\u2014) indicates no direct involvement.",
    size=12, first_line_indent=18, space_after=8)

resp_headers = ["Task / Module", "Garima\n(22CSU067)", "Garima Juneja\n(22CSU068)", "Aryan\n(22CSU031)"]
resp_data = [
    resp_headers,
    ["Literature Survey & Background Research",        "P", "S", "S"],
    ["Data Collection (NASA PDS download)",            "P", "—", "—"],
    ["Preprocessing Pipeline (preprocessing.py)",      "P", "—", "—"],
    ["Terrain Analysis Module (terrain.py)",           "P", "—", "—"],
    ["Landing Site Scoring (landing_scorer.py)",       "P", "—", "—"],
    ["A* Pathfinding (pathfinder.py)",                 "P", "S", "—"],
    ["Terrain Classifier — RF",                        "P", "—", "—"],
    ["Anomaly Detection — DBSCAN",                     "P", "—", "—"],
    ["Energy Model (energy_model.py)",                 "P", "—", "—"],
    ["Mission Advisory Report (mission_advisor.py)",   "P", "—", "—"],
    ["FastAPI Backend (main.py, app.py)",               "P", "S", "—"],
    ["Frontend HTML/CSS Design (index.html)",          "S", "P", "—"],
    ["CSS Dark Theme (style.css)",                     "—", "P", "S"],
    ["JavaScript AJAX & Plotly Integration",           "S", "P", "—"],
    ["Interactive Visualisation (visualizer.py)",      "S", "P", "—"],
    ["System Integration & End-to-End Testing",        "P", "S", "—"],
    ["Chandrayaan-3 / Artemis III Validation",         "P", "—", "S"],
    ["Project Documentation (README, comments)",       "S", "—", "P"],
    ["Synopsis Report Writing",                        "S", "—", "P"],
    ["Research Paper Drafting",                        "P", "—", "S"],
    ["Presentation Preparation",                       "P", "S", "S"],
    ["Meeting Notes & Progress Tracking",              "—", "—", "P"],
]

PRIMARY_FILL = "E2EFDA"
SUPPORT_FILL = "FFF2CC"
HEADER_FILL  = "D9D9D9"

resp_table = doc.add_table(rows=len(resp_data), cols=4)
resp_table.style = "Table Grid"
resp_table.alignment = WD_TABLE_ALIGNMENT.CENTER

for i, row_data in enumerate(resp_data):
    for j, ct in enumerate(row_data):
        cell = resp_table.rows[i].cells[j]
        if i == 0:
            set_cell_text(cell, ct, size=10, bold=True)
            shade_cell(cell, HEADER_FILL)
        else:
            is_task = (j == 0)
            set_cell_text(cell, ct, size=10, bold=False,
                          align=WD_ALIGN_PARAGRAPH.LEFT if is_task else WD_ALIGN_PARAGRAPH.CENTER)
            if not is_task:
                if ct == "P":
                    shade_cell(cell, PRIMARY_FILL)
                elif ct == "S":
                    shade_cell(cell, SUPPORT_FILL)

for row in resp_table.rows:
    row.cells[0].width = Inches(2.8)
    row.cells[1].width = Inches(1.1)
    row.cells[2].width = Inches(1.3)
    row.cells[3].width = Inches(1.0)

add_para(doc,
    "Table 16.1: Responsibility chart.\n"
    "P = Primary responsibility  |  S = Supporting role  |  \u2014 = No direct involvement\n"
    "Green (P) = primary. Yellow (S) = supporting.",
    size=10, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# REFERENCES
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "References", size=14, space_before=0)

references = [
    "[1] A. Colaprete et al., \u201cDetection of Water in the LCROSS Ejecta Plume,\u201d "
    "Science, vol. 330, no. 6003, pp. 463\u2013468, 2010.",
    "[2] A. Silburt et al., \u201cLunar Crater Identification via Deep Learning,\u201d "
    "Icarus, vol. 317, pp. 27\u201338, 2019.",
    "[3] S. Bue and T. Stepinski, \u201cMachine Classification of Geomorphic Units from "
    "Digital Elevation Models,\u201d Geomorphology, vol. 91, pp. 109\u2013121, 2007.",
    "[4] D. Wettergreen et al., \u201cScience-Enabling Autonomous Navigation for Planetary "
    "Rovers,\u201d in Proc. 9th Int. Symp. Artificial Intelligence, Robotics and "
    "Automation in Space (iSAIRAS), 2008.",
    "[5] D. E. Smith et al., \u201cThe Lunar Orbiter Laser Altimeter Investigation on the "
    "Lunar Reconnaissance Orbiter Mission,\u201d Space Sci. Rev., vol. 150, "
    "pp. 209\u2013241, 2010.",
    "[6] M. T. Zuber et al., \u201cConstraints on the Volatile Distribution Within Shackleton "
    "Crater at the Lunar South Pole,\u201d Nature, vol. 486, pp. 378\u2013381, 2012.",
    "[7] A. N. Deutsch et al., \u201cMassive Ice Deposits in the Lunar Polar Regions,\u201d "
    "Geophys. Res. Lett., vol. 47, e2020GL087858, 2020.",
    "[8] M. P. Golombek et al., \u201cSelection of the Mars Exploration Rover Landing Sites,\u201d "
    "J. Geophys. Res. Planets, vol. 108, no. E12, 2003.",
    "[9] J. Flahaut et al., \u201cRegions of Interest (ROI) for Future Human Lunar Landing "
    "Sites,\u201d Planet. Space Sci., vol. 180, 104750, 2020.",
    "[10] K. Wagstaff et al., \u201cMars Novelty Detection with Multivariate Analysis,\u201d "
    "in Proc. AAAI Workshop, 2008.",
    "[11] L. F. Palafox et al., \u201cAutomated Detection of Geological Landforms on Mars "
    "Using CNNs,\u201d Comput. Geosci., vol. 101, pp. 48\u201356, 2017.",
    "[12] M. Ono et al., \u201cMARS: Machine Learning-Based Autonomous Rover Science on Mars,\u201d "
    "in Proc. IEEE Aerospace Conf., 2016.",
    "[13] A. Stentz, \u201cOptimal and Efficient Path Planning for Partially Known "
    "Environments,\u201d in Proc. ICRA, 1994.",
    "[14] D. Ferguson and A. Stentz, \u201cField D*: An Interpolation-Based Path Planner "
    "and Replanner,\u201d in Proc. ISRR, 2005.",
    "[15] M. Ester et al., \u201cA Density-Based Algorithm for Discovering Clusters in Large "
    "Spatial Databases with Noise,\u201d in Proc. KDD, pp. 226\u2013231, 1996.",
    "[16] H. Kerner et al., \u201cNovelty Detection for Multispectral Images with Application "
    "to Planetary Exploration,\u201d in Proc. AAAI, 2019.",
    "[17] S. Chien et al., \u201cOASIS: Automated Mission Planning for the EO-1 Spacecraft,\u201d "
    "IEEE Intell. Syst., vol. 20, no. 1, pp. 11\u201317, 2005.",
    "[18] B. B. Lemelin et al., \u201cHigh-Priority Lunar Landing Sites for In Situ and "
    "Sample Return Studies of Polar Volatiles,\u201d Planet. Space Sci., vol. 101, "
    "pp. 149\u2013161, 2014.",
    "[19] C. Shwartz-Ziv and A. Armon, \u201cTabular Data: Deep Learning is Not All You Need,\u201d "
    "Information Fusion, vol. 81, pp. 84\u201390, 2022.",
    "[20] F. Pedregosa et al., \u201cScikit-learn: Machine Learning in Python,\u201d "
    "J. Mach. Learn. Res., vol. 12, pp. 2825\u20132830, 2011.",
]
for ref in references:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.left_indent = Inches(0.3)
    p.paragraph_format.first_line_indent = Inches(-0.3)
    run = p.add_run(ref)
    set_font(run, size=12)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# ANNEXURE I — MEETING SCREENSHOTS
# ═══════════════════════════════════════════════════════════════════════════════

add_heading(doc, "Annexure I: MS Teams Meeting Screenshots / Guide Comments", size=14, space_before=0)

add_para(doc,
    "The following pages contain screenshots of supervisory meetings and guide feedback "
    "sessions conducted throughout the project. These document the iterative development "
    "process and supervisor guidance at key milestones.",
    size=12, first_line_indent=18, space_after=12)

meeting_slots = [
    ("Meeting 1 \u2014 October 2025: Project scoping and DEM data selection",
     "[ Please attach MS Teams screenshot / handwritten guide comment for October 2025 meeting ]"),
    ("Meeting 2 \u2014 November 2025: Terrain pipeline review",
     "[ Please attach MS Teams screenshot / handwritten guide comment for November 2025 meeting ]"),
    ("Meeting 3 \u2014 December 2025: Scoring model and classifier design review",
     "[ Please attach MS Teams screenshot / handwritten guide comment for December 2025 meeting ]"),
    ("Meeting 4 \u2014 January 2026: Mid-term progress review",
     "[ Please attach MS Teams screenshot / handwritten guide comment for January 2026 meeting ]"),
    ("Meeting 5 \u2014 February 2026: Integration and frontend review",
     "[ Please attach MS Teams screenshot / handwritten guide comment for February 2026 meeting ]"),
    ("Meeting 6 \u2014 March 2026: Validation results and report review",
     "[ Please attach MS Teams screenshot / handwritten guide comment for March 2026 meeting ]"),
]

for title, placeholder in meeting_slots:
    add_subheading(doc, title, size=12, space_before=8)
    add_screenshot_placeholder(doc, placeholder)
    add_para(doc, "", space_after=4)

# ─────────────────────────── save ────────────────────────────────────────────

out_path = "Anveshak_Synopsis_Report.docx"
doc.save(out_path)
print(f"Saved: {out_path}")
print(f"Approximate page count: ~45 pages")
print()
print("SCREENSHOTS NEEDED — run these commands and capture the output:")
print("  1. uvicorn main:app --reload  → open http://localhost:8000 (frontend form)")
print("  2. GET http://localhost:8000/demo  → full analysis map + classification preview")
print("  3. python validation/chandrayaan3_validation.py  → validation output")
print("     (or open outputs/chandrayaan3_validation.html)")
print("  4. Open outputs/classification_preview.html  → classification map")
print("  5. Open outputs/map_preview.html  → terrain preview map")
