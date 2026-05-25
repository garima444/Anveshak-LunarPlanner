"""
generate_qa_doc.py  —  Generates Anveshak_QA.docx
Comprehensive module-by-module Q&A for viva/review preparation.
Run: python generate_qa_doc.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

doc = Document()

# ── Page setup ────────────────────────────────────────────────────────────────
sec = doc.sections[0]
sec.page_width   = Inches(8.5)
sec.page_height  = Inches(11)
sec.top_margin   = sec.bottom_margin = Inches(1.0)
sec.left_margin  = sec.right_margin  = Inches(1.25)

# Default font
doc.styles["Normal"].font.name = "Times New Roman"
doc.styles["Normal"].font.size = Pt(12)

# ── Colour palette ────────────────────────────────────────────────────────────
BLUE    = RGBColor(0x1F, 0x49, 0x7D)   # module heading
DKGREEN = RGBColor(0x14, 0x54, 0x22)   # Q label
DKRED   = RGBColor(0x7B, 0x0C, 0x0C)   # A label
GREY    = RGBColor(0x40, 0x40, 0x40)

def add_page_break(): doc.add_page_break()

def section_heading(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after  = Pt(6)
    run = p.add_run(text)
    run.font.name  = "Times New Roman"
    run.font.size  = Pt(16)
    run.font.bold  = True
    run.font.color.rgb = BLUE
    # Bottom border
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single"); b.set(qn("w:sz"), "6")
    b.set(qn("w:space"), "4");    b.set(qn("w:color"), "1F497D")
    pBdr.append(b); pPr.append(pBdr)
    return p

def sub_heading(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after  = Pt(4)
    run = p.add_run(text)
    run.font.name  = "Times New Roman"
    run.font.size  = Pt(13)
    run.font.bold  = True
    run.font.color.rgb = BLUE
    return p

def qa(num, question, answer):
    """Add a Q-A pair."""
    # Q
    pq = doc.add_paragraph()
    pq.paragraph_format.space_before = Pt(8)
    pq.paragraph_format.space_after  = Pt(2)
    pq.paragraph_format.left_indent  = Inches(0.0)
    rq1 = pq.add_run(f"Q{num}. ")
    rq1.font.name  = "Times New Roman"
    rq1.font.size  = Pt(12)
    rq1.font.bold  = True
    rq1.font.color.rgb = DKGREEN
    rq2 = pq.add_run(question)
    rq2.font.name  = "Times New Roman"
    rq2.font.size  = Pt(12)
    rq2.font.bold  = True
    rq2.font.color.rgb = GREY

    # A
    pa = doc.add_paragraph()
    pa.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pa.paragraph_format.space_before = Pt(2)
    pa.paragraph_format.space_after  = Pt(6)
    pa.paragraph_format.left_indent  = Inches(0.2)
    ra1 = pa.add_run("Ans: ")
    ra1.font.name  = "Times New Roman"
    ra1.font.size  = Pt(12)
    ra1.font.bold  = True
    ra1.font.color.rgb = DKRED
    ra2 = pa.add_run(answer)
    ra2.font.name  = "Times New Roman"
    ra2.font.size  = Pt(12)
    ra2.font.color.rgb = RGBColor(0x10, 0x10, 0x10)
    return pq, pa

# ══════════════════════════════════════════════════════════════════════════════
# COVER
# ══════════════════════════════════════════════════════════════════════════════
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(24)
r = p.add_run("ANVESHAK — Lunar Mission Planner\nModule-wise Q&A for Viva / Review Preparation")
r.font.name = "Times New Roman"; r.font.size = Pt(18); r.font.bold = True
r.font.color.rgb = BLUE

p2 = doc.add_paragraph()
p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
r2 = p2.add_run(
    "Garima (22CSU067)  |  Garima Juneja (22CSU068)  |  Aryan (22CSU031)\n"
    "Supervised by: Dr. Snehlata Sheoran & Dr. Ankita Bhalla\n"
    "Department of CSE, The NorthCap University"
)
r2.font.name = "Times New Roman"; r2.font.size = Pt(12)

add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 1 — terrain.py
# ══════════════════════════════════════════════════════════════════════════════
section_heading("Module 1: terrain.py — DEM Loading & Terrain Analysis")

qa(1,
"What is the purpose of terrain.py? What does it output?",
"terrain.py is the foundational data-ingestion module. It loads the NASA LRO LOLA "
"Digital Elevation Model (DEM) from a JPEG2000 file (LDEM_80S_20M.JP2), converts raw "
"integer DN values to elevation in metres, and computes three derived terrain metrics: "
"slope (in degrees), roughness (local elevation standard deviation in metres), and a "
"data-quality mask from the companion LDEC file. It returns four outputs: elevation, "
"slope, roughness (all float32 NumPy arrays of shape 10,133×10,133), and a profile "
"dictionary containing CRS, affine transform, resolution, and optional quality_mask "
"and sunlight_map arrays. Every other module in Anveshak consumes these outputs."
)

qa(2,
"Why is the LOLA DEM stored in JPEG2000 format? What special advantage does this give?",
"JPEG2000 is a wavelet-based image compression standard that natively supports "
"multi-resolution decoding — its internal wavelet decomposition stores the image "
"at multiple resolution levels simultaneously. When rasterio calls read(out_shape=...) "
"on a JP2 file, it instructs the underlying GDAL/openjpeg decoder to serve the data "
"at a coarser resolution level directly, without ever decompressing the full image. "
"For Anveshak's factor-3 downsample (from native 20 m to 60 m/pixel), this means the "
"full 30,400×30,400 array (which would require ~1.74 GB as int16) is never allocated "
"in memory. The decoder serves the 10,133×10,133 version directly, costing only "
"~193 MB. This is the single most important memory optimisation in the entire system."
)

qa(3,
"What is the `_JP2_SCALE = 0.5` constant? Why is raw DN multiplied by 0.5?",
"The LOLA JP2 files store elevation as int16 Digital Numbers (DNs) rather than "
"direct metre values, to maximise dynamic range within a 16-bit integer. The LBL "
"metadata file specifies SCALING_FACTOR = 0.5, meaning the true elevation in metres "
"equals raw_DN × 0.5. For example, a raw value of −14,594 represents −7,297 m "
"(a deep crater floor). This halved resolution gives a maximum representable elevation "
"range of ±16,383.5 m, which is far greater than the Moon's actual topographic "
"range of about ±10,783 m, providing comfortable headroom. Without applying this "
"scale, all elevation-dependent calculations (slope, roughness, scoring) would be "
"off by a factor of 2."
)

qa(4,
"Why are there two nodata values (`_NODATA_RAW_A = 0` and `_NODATA_RAW_B = -32768`)? "
"How are they handled?",
"The LOLA DEM uses two different sentinel values to indicate missing data. "
"−32768 is the standard int16 minimum value used as a generic 'nodata' flag "
"(common in GIS formats). Zero is used in LOLA-specific products to indicate "
"pixels with no laser returns at all — effectively a gap in coverage. "
"Both are checked with a bitwise OR of equality tests: "
"`(raw == 0) | (raw == -32768)`. Using bitwise OR instead of np.isin() is deliberate: "
"np.isin() internally promotes int16 arrays to int64 for comparison, which would "
"allocate an extra ~400 MB for the full-resolution array. The boolean mask itself "
"uses only 1 byte per pixel, keeping peak memory minimal. Matched pixels are set "
"to float32 NaN so they propagate naturally through all subsequent calculations."
)

qa(5,
"How is slope computed in `_compute_slope()`? Why is float32 used explicitly?",
"Slope is computed using central finite differences — the same mathematical "
"approach as the standard GIS slope formula. For each interior pixel (i, j): "
"∂E/∂x = (E[i,j+1] − E[i,j−1]) / (2d) and ∂E/∂y = (E[i+1,j] − E[i−1,j]) / (2d), "
"where d = 60 m is the pixel spacing. The gradient magnitude |∇E| = sqrt((∂E/∂x)² + (∂E/∂y)²) "
"is then converted to degrees via arctan. Critically, the code avoids np.gradient() "
"which promotes float32 inputs to float64 — for a 10,133×10,133 array that would "
"allocate an additional ~1.6 GB. Instead, all operations use np.float32 literals "
"and in-place operations (np.multiply with out= parameter) to reuse memory. "
"The same array is overwritten stepwise: dy² → dx² → dx²+dy² → sqrt → arctan → degrees, "
"meaning only two float32 arrays plus temporary scalars are live at any point."
)

qa(6,
"What is the 'variance trick' used in `_compute_roughness()`? Why does NaN handling require "
"filling with the global mean first?",
"The variance trick computes local standard deviation without storing the full "
"neighbourhood for every pixel. It exploits the identity: Var(X) = E[X²] − E[X]², "
"where E[·] denotes local mean computed with scipy.ndimage.uniform_filter. "
"This requires only two passes of uniform_filter (one for mean, one for squared-mean), "
"each O(n) in the number of pixels. For a 10,133×10,133 grid with a 3×3 kernel, "
"this is much faster than a sliding window approach.\n\n"
"The NaN problem: scipy's uniform_filter uses a cumulative-sum (integral image) "
"algorithm internally. A single NaN in any row causes all subsequent elements in "
"that row's cumsum to also become NaN, cascading through the entire array. With "
"even 2% scattered NaN, the output becomes ~99% NaN. The solution is to fill NaN "
"pixels with the global mean (nanmean) before filtering — this prevents cumsum "
"contamination. The NaN mask is saved before filling and re-applied to the roughness "
"output afterward, so the semantics are preserved. The only artefact is a 1-pixel "
"border around each NaN region where roughness values are slightly wrong "
"(contaminated by mean fill), which is acceptable for quality-masking purposes."
)

qa(7,
"What does the CRS string `+proj=stere +lat_0=-90 +R=1737400` mean? Why is the radius "
"1,737,400 and not 6,371,000 (Earth)?",
"This is the Polar Stereographic Moon 2000 projection. `+proj=stere` means Stereographic "
"projection, centred at the south pole (`+lat_0=-90`). The radius `+R=1737400` is the "
"mean radius of the Moon in metres (1,737.4 km), replacing Earth's radius (~6,371 km). "
"The Moon is smaller by a factor of ~3.67. Using the correct radius is critical: if "
"the Earth radius were used, all distance calculations would be wrong by a factor "
"of ~3.67, making 60 m/pixel ground sampling appear as ~220 m/pixel. The terrain "
"coverage area (200 km × 200 km) would be interpreted as 730 km × 730 km, "
"completely invalidating path distances, energy calculations, and coordinate conversions. "
"pyproj handles this non-standard body radius via the `+R=` parameter in the proj4 string."
)

qa(8,
"What is the singleton `_TRANSFORMER` pattern? Why is it important for performance?",
"A pyproj.Transformer object is expensive to create — it parses the CRS strings, "
"validates them against the proj4 database, and initialises the transformation pipeline. "
"In Anveshak, coordinate conversions happen millions of times (once per pixel in the "
"latitude grid, once per top site, once per path waypoint). Creating a new Transformer "
"each time would add significant overhead. The `_make_moon_transformer()` function "
"checks a module-level global `_TRANSFORMER` — if None, it creates one; otherwise "
"it returns the cached instance. This is the Singleton pattern: one instance per "
"Python process. Because Python's GIL protects simple attribute reads in CPython, "
"this is also effectively thread-safe for the read path. The same pattern is "
"duplicated in landing_scorer.py and terrain_classifier.py to keep each module "
"self-contained without circular imports."
)

qa(9,
"What does `get_elevation_at()` do? Why does it use bilinear interpolation "
"instead of nearest-neighbour?",
"get_elevation_at() takes a geographic coordinate (lon, lat) and returns the "
"elevation at that exact point. Because terrain data is sampled on a discrete "
"60 m grid, a geographic coordinate will in general fall between four pixel centres. "
"Nearest-neighbour lookup would introduce quantisation errors of up to ±30 m "
"(half a pixel). Bilinear interpolation computes a weighted average of the four "
"surrounding pixel values using fractional pixel offsets (dr, dc), giving a "
"continuous estimate. The formula is: "
"v = v00·(1−dr)(1−dc) + v01·(1−dr)·dc + v10·dr·(1−dc) + v11·dr·dc. "
"This is important for validation (e.g., checking the exact elevation at "
"Shackleton Ridge's GPS coordinates) and for the energy model (elevation "
"difference per path step). If any of the four neighbouring pixels is NaN, "
"the function returns NaN to avoid corrupting the result with imputed values."
)

qa(10,
"Why is the working resolution set to 60 m/pixel specifically? What are the trade-offs?",
"60 m/pixel is a factor-3 downsample from the 20 m/pixel native LOLA DEM resolution. "
"The choice balances memory, speed, and scientific relevance. At 20 m/pixel, "
"the full 30,400×30,400 grid requires ~7 GB of RAM for three float32 arrays — "
"impractical for commodity hardware. At 60 m/pixel (10,133×10,133), three arrays "
"total ~1.2 GB, comfortably within 16 GB. At 60 m resolution, features larger than "
"120 m (two pixels) are resolved, which captures: crater rims (typically hundreds "
"of metres wide), large slope transitions, and the broad flat areas required by "
"rovers for safe landing (typically 200–500 m radius). What is lost: fine-scale "
"rock fields, individual boulders (<60 m), and sub-crater-rim microterrain. "
"For mission-planning purposes (site selection over a 200×200 km area) this "
"is an acceptable trade-off. A sub-region analysis at 5–10 m/pixel could be "
"performed using the higher-resolution LDEM_87S_5MPP files for a shortlisted site."
)

add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 2 — landing_scorer.py
# ══════════════════════════════════════════════════════════════════════════════
section_heading("Module 2: landing_scorer.py — Multi-Criteria Landing Site Scoring")

qa(11,
"What is the purpose of landing_scorer.py? What are its inputs and outputs?",
"landing_scorer.py evaluates every pixel in the 10,133×10,133 terrain grid as a "
"potential landing site, producing a score between 0 and 1 for each pixel. "
"Inputs are the three terrain arrays (elevation, slope, roughness), the terrain "
"profile dict, and a rover_profile dict specifying: mission_type, power_source, "
"max_slope_deg, min_flat_radius_m, and priority (0=safety-first, 1=science-first). "
"Outputs are three full-grid score arrays (safety_score, mission_score, final_score) "
"and a list of up to 10 top candidate sites, each with coordinates, terrain metrics, "
"scores, and a plain-English reasoning string. All scoring is fully vectorised — "
"there are no Python loops over pixels — making it fast enough to run interactively."
)

qa(12,
"Explain the safety score formula. What are its four sub-scores and their weights?",
"The safety score combines four independent sub-scores, each normalised to [0, 1]:\n\n"
"1. Slope sub-score (weight 0.50): 1 − clip(slope / max_slope_deg, 0, 1). "
"A flat pixel (0°) scores 1.0; a pixel at the rover's maximum traversable slope "
"scores 0.0. This is the dominant safety criterion.\n\n"
"2. Roughness sub-score (weight 0.25): exp(−roughness / r95), where r95 is the "
"95th-percentile roughness value over the entire grid. Using exponential decay "
"rather than linear normalisation ensures very rough pixels (e.g., crater interiors) "
"are strongly penalised, while moderately rough pixels are treated less harshly.\n\n"
"3. Quality sub-score (weight 0.15): LDEC observation count normalised by its "
"global maximum. Low-count pixels have interpolated rather than measured elevation, "
"making them unreliable for safety assessment.\n\n"
"4. Flat-area sub-score (weight 0.10): fraction of passable pixels within a "
"neighbourhood of radius min_flat_radius_m / 60 m pixels, normalised by 0.5. "
"This rewards sites surrounded by flat terrain (important for rover mobility post-landing).\n\n"
"After combining, a crater-rim proximity penalty of ×0.4 is applied multiplicatively "
"to all pixels within ~480 m of any pixel with slope > 35°. "
"Finally, any pixel with slope > max_slope_deg is hard-zeroed regardless."
)

qa(13,
"Why is the roughness sub-score computed as `exp(−r/r95)` instead of `1 − r/r_max`?",
"Linear normalisation (1 − r/r_max) spreads the entire roughness range evenly between "
"0 and 1. But lunar terrain has a very skewed roughness distribution — the vast "
"majority of pixels are relatively smooth (crater floors, plains), while a small "
"fraction (crater rims, steep scarps) are extremely rough. Linear scaling would "
"make even moderately rough pixels score quite low, producing an uninformative map. "
"The exponential decay `exp(−r/r95)` assigns high scores to smooth terrain "
"(r << r95) and drops steeply for rough terrain (r ≈ r95). Using r95 as the "
"scale parameter rather than r_max prevents a few extreme outlier pixels from "
"compressing the entire distribution. The result is a score that realistically "
"distinguishes 'good landing terrain' from 'marginal terrain' rather than just "
"penalising relative to the most extreme value seen."
)

qa(14,
"What is the crater-rim proximity penalty? How is it implemented efficiently?",
"Crater rims are among the most dangerous landing zones — steep on both sides, "
"with highly variable terrain. Even if a pixel slightly inside the rim has an "
"acceptable slope, the immediate surroundings are impassable. The penalty "
"identifies all pixels with slope > 35° (empirically the threshold above which "
"terrain is structurally a crater rim), then uses scipy.ndimage.maximum_filter "
"with a (17×17) kernel (radius = 8 px = 480 m) to dilate this mask. Any pixel "
"within 480 m of a rim pixel receives a ×0.4 multiplier on its safety score. "
"This is computationally efficient because maximum_filter runs in O(n) time "
"regardless of kernel size (it uses a sliding maximum algorithm). The alternative "
"— looping over detected rim pixels and masking their neighbourhoods — would be "
"O(n × k²) and far too slow on a 10M-pixel grid."
)

qa(15,
"How does the mission score differ between water_ice, geological, and atmospheric missions?",
"Each mission type rewards different terrain characteristics:\n\n"
"water_ice: Rewards (a) latitudes south of −88°S — these are near the pole where "
"Permanently Shadowed Regions (PSRs) are most prevalent, and (b) deep crater floors "
"(low elevation relative to the 95th-percentile) which are most likely PSRs. "
"Solar-powered rovers receive a 0.3× penalty on the depth score because they cannot "
"operate in dark craters.\n\n"
"geological: Rewards (a) high local roughness variance — diverse terrain indicates "
"multiple geological units exposed, (b) high elevation gradient magnitude — "
"sharp elevation transitions mark geological boundaries between rock types, and "
"(c) accessibility — a bell-curve centred at −86.5°S, representing a balanced "
"location that is scientifically interesting but not too extreme.\n\n"
"atmospheric: Rewards high-elevation ridges and peaks, since these provide maximum "
"sunlight exposure and are ideal for atmospheric/thermal measurements, solar "
"power generation, and communication relay stations."
)

qa(16,
"What is the `priority` parameter and how does it affect final score blending?",
"priority is a float between 0 and 1 provided by the user. It controls how "
"the safety_score and mission_score are blended into final_score:\n\n"
"priority < 0.5 (safety-first): final = 0.7 × safety + 0.3 × mission. "
"Appropriate for technology demonstration missions or first landings where safe "
"touchdown is paramount.\n\n"
"priority ≥ 0.5 (science-first): final = 0.4 × safety + 0.6 × mission. "
"Appropriate for geological survey or water-ice prospecting missions where "
"maximising science return justifies accepting higher terrain risk.\n\n"
"Crucially, pixels with safety_score = 0 (impassable) are forced to final_score = 0 "
"regardless of priority, ensuring the system never recommends a landing on "
"steep, unsafe terrain no matter how scientifically attractive it is."
)

qa(17,
"How are the top-10 landing sites selected? What prevents clustering within one crater?",
"Top site selection uses local maximum extraction: scipy.ndimage.maximum_filter "
"with a 50-pixel kernel identifies pixels whose score equals the maximum in their "
"neighbourhood (local maxima). All local maxima with score > 0 are collected and "
"sorted by descending final_score. A greedy spatial deduplication then selects "
"sites: a candidate is accepted only if it is more than 50 pixels (3 km) from "
"all already-accepted sites, checked using math.hypot distance. This 50-pixel "
"minimum separation prevents the top-10 list from being dominated by closely "
"spaced pixels within a single large flat area. The result is a geographically "
"diverse shortlist of sites spread across the 200×200 km coverage region."
)

qa(18,
"What is the ML refinement step at the end of `score_terrain()`? Is it circular?",
"After the top-10 sites are selected by the scoring model, score_terrain() "
"optionally loads the Random Forest terrain classifier (if trained) and applies "
"post-hoc class-based adjustments: SCIENCE_TARGET pixels receive a +0.10 bonus "
"and HAZARD_ZONE pixels are zeroed out. This is a refinement, not a re-scoring — "
"the initial ranking is based purely on the physics-derived score; the ML step "
"adds a learned sanity check.\n\n"
"It is somewhat circular: the RF classifier was trained on labels derived from "
"the same scoring model. This circularity is acknowledged as a limitation. However, "
"the adjustment only modifies the top-10 list (not the full grid), and the RF "
"classifier uses spatial context features (local_mean_slope, local_std_elevation) "
"that the point-wise scorer does not, so it can legitimately reclassify a site "
"whose immediate neighbourhood is dangerous even if its own pixel is technically "
"passable. The 10k independent validation set confirms the classifier generalises "
"beyond its training labels."
)

add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 3 — pathfinder.py
# ══════════════════════════════════════════════════════════════════════════════
section_heading("Module 3: pathfinder.py — Terrain-Aware A* Path Planning")

qa(19,
"What is A* and why is it used instead of simpler algorithms like BFS or Dijkstra's?",
"A* (A-star) is a best-first graph search algorithm that finds the minimum-cost "
"path between two nodes. It is an extension of Dijkstra's algorithm with a "
"heuristic function h(n) that estimates the remaining cost from any node n to "
"the goal. The total priority of a node in A* is f(n) = g(n) + h(n), where "
"g(n) is the actual cost from start to n and h(n) is the heuristic estimate.\n\n"
"Compared to Dijkstra's (h=0 everywhere), A* expands fewer nodes by biasing "
"exploration toward the goal direction, dramatically reducing runtime on large grids. "
"BFS is unsuitable because it ignores edge costs (treats all steps as equal), "
"which would produce straight-line paths ignoring steep terrain. "
"On the 10,133×10,133 Anveshak grid, A* typically finds paths within 500k–2M "
"iterations; pure Dijkstra's would need to explore a much larger frontier. "
"The Euclidean heuristic h(n) = distance_to_goal × min_cost is admissible "
"(never overestimates true cost), guaranteeing A* returns the optimal path."
)

qa(20,
"What is the cost function in `build_cost_grid()`? Why use `exp(slope / factor)` "
"instead of slope directly?",
"The per-pixel traversal cost is: cost = resolution_m × exp(slope_deg / slope_penalty_factor). "
"For default slope_penalty_factor = 10, a 0° slope pixel costs 60 m (flat ground). "
"A 10° slope pixel costs 60 × exp(1) ≈ 163 m (effective distance penalty). "
"A 20° slope pixel costs 60 × exp(2) ≈ 443 m. A 30° pixel costs ~1,200 m.\n\n"
"Linear slope cost (cost = resolution_m + k × slope) would add a fixed penalty per "
"degree of slope, which underpenalises very steep terrain. The exponential function "
"grows superlinearly, making very steep segments disproportionately expensive "
"and routing paths around them even when the straight-line distance is shorter. "
"This mimics real rover behaviour: a rover will travel significantly farther "
"on flat ground rather than attempt even a modest detour onto steep terrain, "
"because the energy cost and mechanical risk increase non-linearly with slope."
)

qa(21,
"What is `snap_to_passable()` and why is it necessary?",
"snap_to_passable() takes a (row, col) point and the cost grid, and finds the "
"nearest pixel with finite (non-inf) cost. It uses an expanding square-ring "
"search: first checks radius 1 (8 neighbours), then radius 2 (16 perimeter pixels), "
"and so on up to max_radius = 50 pixels.\n\n"
"It is necessary because user-specified start/goal coordinates or top-site pixel "
"coordinates may fall on impassable pixels (slope > max_slope, NaN elevation). "
"For example, the highest-scoring landing site might be on the rim of a crater "
"where the slope just exceeds the threshold. Without snapping, A* would immediately "
"reject the query. Snapping finds the nearest passable pixel within 3 km, "
"which is a reasonable approximation for mission planning purposes. The system "
"logs when snapping occurs so the planner is aware of the adjustment."
)

qa(22,
"Why does the 8-directional movement model multiply diagonal move costs by √2?",
"In an 8-directional grid, cardinal moves (up/down/left/right) travel one pixel "
"width = 60 m. Diagonal moves travel to a corner-adjacent pixel, which has a "
"true Euclidean distance of √(60² + 60²) = 60√2 ≈ 84.85 m. Without the √2 "
"multiplier, the planner would prefer diagonal paths over equivalent cardinal "
"paths (since they reach the goal faster in terms of pixel count but at the same "
"cost), producing unrealistically zig-zagged paths. The √2 multiplier ensures "
"that any equivalent path — whether it uses diagonal or cardinal steps — has the "
"same total cost, and that the planner finds the truly shortest terrain-weighted "
"path. The module precomputes `_SQRT2 = sqrt(2.0)` as a constant to avoid "
"computing it in the inner loop of A*."
)

qa(23,
"What happens when the 2-million iteration limit is reached in A*?",
"The 2M iteration limit is a hard safety cap to guarantee bounded runtime. "
"If reached, astar() prints a warning and returns None (no path found). "
"The find_path() caller propagates this as (None, None) to the API response, "
"which includes a 'path_not_found' indicator and advisory text in the mission "
"report. In practice, this occurs mainly for paths approaching very challenging "
"terrain like Faustini Crater rim, where the only low-slope corridors are "
"narrow and far from the straight-line route. The 2M limit was chosen empirically: "
"it allows paths within ~50 km mission radius to complete within 1–2 seconds "
"while bounding worst-case runtime at ~3–5 seconds for pathological cases. "
"A potential improvement would be to return the best partial path (the node in "
"the closed set closest to the goal) rather than None, but this would require "
"tracking the closest node separately."
)

qa(24,
"How does `generate_waypoints()` decide which sites to visit? How does it use anomaly data?",
"generate_waypoints() selects up to n=3 rover waypoints for sequential path planning. "
"If anomaly data is available, it first filters anomalies by mission relevance "
"(each anomaly has a `recommended_for` list of mission types), then sorts by "
"anomaly_strength (descending). If enough relevant anomalies exist, they are "
"used as waypoints — directing the rover to geologically or scientifically "
"interesting terrain. If fewer anomalies than n are available, it pads with "
"top landing sites sorted by mission-specific criteria:\n\n"
"water_ice → sorted by latitude (most polar first)\n"
"geological → sorted by roughness_m (most diverse terrain first)\n"
"atmospheric → sorted by elevation_m (highest ridges first)\n\n"
"This two-level priority system ensures the rover path is science-driven when "
"anomalies are detected, but falls back to the best scored sites otherwise."
)

add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 4 — terrain_classifier.py
# ══════════════════════════════════════════════════════════════════════════════
section_heading("Module 4: terrain_classifier.py — Random Forest Terrain Classification")

qa(25,
"What are the five terrain classes? How is each defined scientifically?",
"0. HAZARD_ZONE: slope > 25° OR roughness > 200 m. Terrain too steep or "
"broken for any rover operation. Crater interiors, steep scarps.\n\n"
"1. RISKY_LANDING: safety_score < 0.3. Terrain marginally outside safe limits — "
"possible in an emergency but not recommended. Sub-threshold sloped plains.\n\n"
"2. TRAVERSE_CORRIDOR: 0.3 ≤ safety_score ≤ 0.6. Acceptable for rover driving "
"but not ideal for landing. Used as path segments between better sites.\n\n"
"3. SAFE_LANDING: safety_score > 0.6 AND final_score > 0.5. Meets all safety "
"criteria and scores well overall. Ideal landing targets.\n\n"
"4. SCIENCE_TARGET: mission_score > 0.7 AND safety_score > 0.3. High scientific "
"interest with acceptable safety. Extreme polar terrain, crater-rim edges, "
"geologically diverse zones. Only 0.001% of all pixels — very rare.\n\n"
"The class definitions directly mirror mission planning categories used by NASA's "
"ALHAT and MER site selection teams, making the classification operationally meaningful."
)

qa(26,
"What is auto-labelling? Why is it used instead of manual annotation?",
"Auto-labelling is the process of generating training labels from the output of "
"another algorithm (the scoring pipeline) rather than having human experts label "
"each sample. Instead of asking planetary geologists to manually classify thousands "
"of DEM pixels — which would require months of expert time, access to ground truth "
"that doesn't exist for the south pole, and would still introduce subjective "
"inconsistency — the scoring pipeline's priority rules are used to assign class "
"labels (see _build_labels()). The rules are deterministic, consistent, and grounded "
"in the same physical/scientific criteria that a domain expert would use.\n\n"
"The trade-off is circularity: the classifier learns to replicate the scorer's "
"decisions. This is acknowledged as a limitation. However, the classifier adds "
"value because: (1) it captures spatial context through local_mean_slope and "
"local_std_elevation features that the point-wise scorer ignores, (2) once trained, "
"it is ~100× faster than re-running the full scoring pipeline for new queries, "
"and (3) the independent 10k validation set confirms it generalises beyond its "
"training labels."
)

qa(27,
"What are the 8 features used in the classifier? Why was each chosen?",
"0. Elevation (normalised): Provides global context — crater floors vs ridges "
"have characteristically different elevations.\n\n"
"1. Slope (normalised): Primary safety discriminator. The most important single "
"feature (Gini importance 0.312).\n\n"
"2. Roughness (normalised): Second most important (0.271). Distinguishes stable "
"plains from boulder fields and geologically active terrain.\n\n"
"3. Quality mask: LOLA observation count. Low-quality pixels should be classified "
"with less confidence — this feature lets the RF learn to flag uncertain regions.\n\n"
"4. Local mean slope (3×3 kernel, normalised): Captures neighbourhood-averaged "
"slope context (importance 0.198). A pixel with gentle local slope but steep "
"surroundings is very different from one with gentle slope throughout.\n\n"
"5. Local std elevation (3×3 kernel): Captures micro-roughness and local "
"terrain variability — complementary to the larger-scale roughness feature.\n\n"
"6. Slope gradient magnitude: Second-order terrain derivative. High values "
"indicate abrupt slope transitions — terrain boundaries between geological units.\n\n"
"7. Latitude (normalised): Encodes polar proximity, critical for distinguishing "
"SCIENCE_TARGET zones near −90°S from equivalent terrain farther from the pole."
)

qa(28,
"Why is Random Forest chosen instead of SVM, CNN, or a deep neural network?",
"Three reasons justify Random Forest over alternatives:\n\n"
"1. Training time: Random Forest on 50,000 samples trains in under 60 seconds. "
"A comparable deep neural network would require hours of training and GPU hardware "
"not assumed to be available on the deployment machine.\n\n"
"2. Interpretability: Random Forest provides feature importance scores "
"(mean decrease in Gini impurity) out of the box. This lets us verify that "
"slope and roughness are the dominant factors (as physically expected), which "
"builds confidence in the model's scientific validity. A black-box neural "
"network provides no such transparency.\n\n"
"3. Tabular data advantage: The classifier uses 8 hand-engineered scalar features "
"per pixel (not raw image patches). Shwartz-Ziv & Armon (2022) show that tree-based "
"models match or exceed deep learning on tabular data. CNNs would require "
"image patches as input, quadratically increasing memory during training.\n\n"
"The 99.17% accuracy demonstrates that the problem is well-served by Random Forest."
)

qa(29,
"What is `class_weight='balanced'` in RandomForestClassifier? Why is it important here?",
"class_weight='balanced' instructs scikit-learn to inversely weight each sample "
"by its class frequency: weight_class = n_samples / (n_classes × n_samples_in_class). "
"This counteracts class imbalance — SCIENCE_TARGET has only 0.001% prevalence "
"while TRAVERSE_CORRIDOR has 40.2%. Without balancing, the RF would maximise "
"accuracy by simply learning to always predict TRAVERSE_CORRIDOR and ignoring "
"rare classes entirely. With balanced weights, the model is penalised 40,000× "
"more severely for misclassifying a SCIENCE_TARGET pixel than a TRAVERSE_CORRIDOR "
"pixel, forcing it to learn meaningful boundaries for rare classes. The result "
"is perfect F1 (1.000) on SCIENCE_TARGET in the validation set — evidence that "
"the balance is working effectively."
)

qa(30,
"How does `classify_terrain()` process the full 10,133×10,133 grid efficiently?",
"Classifying 10,133×10,133 = ~102.7M pixels at once would require a (102.7M × 8) "
"float32 feature matrix of ~3.3 GB — beyond available memory. Instead, classify_terrain() "
"processes the grid in horizontal strips of 500 rows at a time. For each strip:\n\n"
"1. Extract 500 rows from each of the 8 pre-computed feature planes: (500, W, 8)\n"
"2. Reshape to (500×W, 8) = a flat matrix of ~5M samples\n"
"3. Call classifier.predict() on this batch (~600 MB peak per strip)\n"
"4. Reshape predictions back to (500, W) and store in class_map\n\n"
"This strip-based approach keeps peak memory at ~1.8 GB (3 terrain arrays + one strip "
"+ classifier buffers) rather than ~5 GB. Total inference time is ~12 seconds, "
"dominated by the Random Forest's vectorised BLAS operations."
)

add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 5 — anomaly_detector.py
# ══════════════════════════════════════════════════════════════════════════════
section_heading("Module 5: anomaly_detector.py — DBSCAN Science Target Detection")

qa(31,
"What is DBSCAN and how does it work fundamentally?",
"DBSCAN (Density-Based Spatial Clustering of Applications with Noise) groups points "
"based on local density rather than distance to a centroid. A point P is a 'core point' "
"if it has at least min_samples neighbours within radius ε (epsilon) in the feature space. "
"Core points and all their density-reachable neighbours form one cluster. Points that "
"are not core points and not reachable from any core point are labelled 'noise' (−1).\n\n"
"Compared to K-means: DBSCAN does not require pre-specifying the number of clusters k, "
"can find clusters of arbitrary shape (not just spherical), and explicitly identifies "
"noise/outlier points. This makes it ideal for geological anomaly detection where we "
"don't know in advance how many scientifically interesting terrain features exist, "
"and where 'not a cluster' (noise) is meaningful information."
)

qa(32,
"What are the four anomaly types? How is each one identified?",
"After DBSCAN identifies clusters, post-processing assigns each cluster a semantic label "
"based on the cluster's mean statistics:\n\n"
"1. THERMAL_PROXY: Cluster mean slope is in the lowest quartile (very gentle terrain) "
"AND mean roughness is above the 75th percentile. Interpretation: a flat but rough area "
"may indicate volcanic outgassing, regolith anomalies, or near-surface thermal activity — "
"proxy for potential ice-modified terrain.\n\n"
"2. ELEVATION_ANOMALY: Cluster mean elevation is above the 75th percentile globally. "
"High-standing terrain that is statistically unusual — candidate for exposed bedrock "
"or ancient impact melt sheets.\n\n"
"3. ROUGHNESS_ANOMALY: Cluster mean roughness is above the 75th percentile. "
"Anomalously rough terrain — candidate for recently disturbed regolith, lava flows, "
"or ejecta deposits.\n\n"
"4. SLOPE_TRANSITION: Cluster exhibits high slope gradient magnitude — sharp transitions "
"between slope regimes. Candidate for geological contacts, fault scarps, or crater rim "
"fractures of scientific interest."
)

qa(33,
"Why is only a 20,000-pixel subsample used for DBSCAN instead of all 102M pixels?",
"DBSCAN's time complexity is O(n²) in the naive implementation (computing pairwise "
"distances) and O(n log n) with a kd-tree. For n = 102M pixels, even O(n log n) would "
"be computationally intractable. More critically, scikit-learn's DBSCAN must hold "
"the distance matrix or neighbours list in memory: for 102M points, even a sparse "
"representation would require tens of GB. The 20,000-sample subsample reduces this "
"to a tractable size (~0.8 MB feature matrix), completing in under 1 second. "
"A uniform random subsample preserves the statistical properties of the terrain "
"distribution. The cluster centroids found on the subsample are used as anomaly "
"location references for path planning and reporting. The limitation is that "
"small isolated anomalies (occupying fewer pixels than the expected sample density "
"of ~102M/20k ≈ 5,100 pixels per sample) may be missed — this is a known limitation "
"noted in the research paper."
)

qa(34,
"What is StandardScaler and why is it critical for DBSCAN specifically?",
"StandardScaler transforms each feature to zero mean and unit variance: "
"x_scaled = (x − mean) / std_dev. Without scaling, features measured in "
"different units or with vastly different ranges dominate the ε-neighbourhood "
"calculation. In Anveshak's feature space: elevation z-scores are dimensionless "
"(range ≈ −3 to +3), but unscaled elevation would range from −7,297 to +7,027 m, "
"and unscaled roughness from 0 to 746 m. The Euclidean distance in feature space "
"would be dominated entirely by elevation differences, and DBSCAN would only "
"cluster by elevation, ignoring roughness and slope information entirely. "
"StandardScaler is essential to give all four features equal weight in the "
"distance metric. This is a fundamental requirement for any distance-based "
"algorithm (DBSCAN, KNN, SVM with RBF kernel)."
)

qa(35,
"How were ε=0.5 and min_samples=10 chosen?",
"These parameters were selected empirically by running DBSCAN over five independently "
"drawn 20,000-pixel subsamples and observing how cluster count varies:\n\n"
"Too small ε (e.g., 0.2): Over-clusters the data, producing hundreds of tiny clusters. "
"Many are spurious noise patches rather than true geological anomalies.\n\n"
"Too large ε (e.g., 1.5): Under-clusters, merging geologically distinct features "
"(e.g., a ridge and a distant crater) into single clusters.\n\n"
"ε=0.5 produced 8–19 clusters across all five subsamples, with coefficient of "
"variation < 0.2 (stable). min_samples=10 ensures clusters represent at least "
"10 sample pixels (roughly 5,000–10,000 actual terrain pixels given the 20k/102M "
"sampling ratio), filtering out spurious single-pixel noise points."
)

add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 6 — energy_model.py
# ══════════════════════════════════════════════════════════════════════════════
section_heading("Module 6: energy_model.py — Physics-Based Energy & Illumination Model")

qa(36,
"What physics model is used in `compute_path_energy()`? Walk through the uphill cost formula.",
"The energy model uses first-principles Newtonian mechanics for the Moon.\n\n"
"For each path step from pixel (r0,c0) to (r1,c1):\n"
"• step_m = 60 m (cardinal) or 60√2 m (diagonal)\n"
"• time_hrs = step_m / speed_m_s / 3600\n\n"
"Baseline electronics power: flat_cost_wh = BASE_POWER_W × time_hrs = 100 W × time.\n\n"
"Uphill motor cost (if elevation increases):\n"
"slope_cost_wh = flat_cost_wh × (1 + sin(slope_rad) × SLOPE_MOTOR_FACTOR)\n"
"where SLOPE_MOTOR_FACTOR = 3.0. This means: on flat terrain the motor adds "
"nothing extra; at 10° slope: sin(10°) ≈ 0.174, multiplier = 1.52×; at 20°: "
"sin(20°) ≈ 0.342, multiplier = 2.03×. The sin(θ) term is the component of "
"gravity opposing forward motion — the fundamental mechanical work against gravity.\n\n"
"Downhill regenerative braking: regen_wh = flat_cost_wh × 0.3 × sin(slope_rad). "
"The 0.3 factor represents 30% regenerative efficiency (realistic for lunar rover "
"motor-as-generator configurations). Net cost on downhill = max(0, flat_cost − regen)."
)

qa(37,
"Why is lunar gravity g = 1.62 m/s² significant for energy calculations?",
"Lunar gravity is 1/6th of Earth's (~9.81 m/s²). This has two counteracting effects:\n\n"
"1. Lower gravitational potential energy: Going uphill on the Moon requires only 1/6th "
"the energy compared to the same slope on Earth. A rover climbing a 10° slope at "
"60 m resolution on the Moon expends far less gravitational energy than on Earth.\n\n"
"2. Lower traction force: With lower normal force (weight), the rover has less friction "
"with the regolith surface, making wheel slippage more likely on loose granular terrain. "
"This is not modelled in the current energy model (acknowledged limitation) but affects "
"real rover design.\n\n"
"The energy_model.py uses lunar gravity implicitly through the sin(slope) × rolling_resistance "
"formulation. The rolling resistance coefficient μr = 0.15 is a regolith-specific value "
"(higher than roads: 0.01–0.02) accounting for the soft, granular lunar surface "
"where wheels sink slightly and create resistance even on flat ground."
)

qa(38,
"What is `estimate_sunlight()` and how accurate is its illumination model?",
"estimate_sunlight() builds a float32 map of solar illumination fraction (0–1) for "
"every pixel in the DEM. It uses a simplified selenographic approximation:\n\n"
"• Latitudes < −89°: floor value of 0.05 (near-permanent shadow near pole)\n"
"• Latitudes > −85°: high illumination value of 0.70\n"
"• Ridge bonus (+0.20): pixels > 500 m above local mean elevation\n"
"• Basin penalty (−0.30): pixels < 1,000 m below local mean elevation\n\n"
"The model is deliberately simple — it does not compute the actual solar elevation "
"angle or terrain horizon shadowing. This is a known limitation (explicitly noted in "
"Section VI.C of the research paper). A horizon-integrated illumination model using "
"the full DEM terrain horizon algorithm would be physically accurate but requires "
"O(n × 360) ray-casting operations (~35 billion ray-pixel tests for the full grid). "
"The simplified model is used as an initialisation heuristic and for solar vs RTG "
"power source differentiation. The research paper identifies this as a priority "
"improvement for future work."
)

add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 7 — mission_advisor.py
# ══════════════════════════════════════════════════════════════════════════════
section_heading("Module 7: mission_advisor.py — Rule-Based Mission Advisory Report")

qa(39,
"What are the 8 sections of the mission advisory report? What does each contain?",
"1. Mission Overview: Summarises input rover profile — mission type, power source, "
"slope limit, flat radius, battery capacity. Sets context for the rest of the report.\n\n"
"2. Top Landing Site Assessment: Coordinates, elevation, slope, roughness, safety "
"and mission scores of the #1 ranked site, with terrain class from RF classifier.\n\n"
"3. Safety Analysis: Distribution of slope and roughness values across the top-10 "
"sites; flags any site with slope > 10° or roughness > 20 m as 'attention required'.\n\n"
"4. Mission Science Value: Top sites ranked by mission score with site-specific "
"scientific reasoning (PSR proximity for water_ice, terrain diversity for geological).\n\n"
"5. Path Analysis: Traverse distance, max/mean slope, estimated time, energy budget "
"and risk level from the path planner and energy model.\n\n"
"6. Science Target Opportunities: Count, types, and coordinates of DBSCAN-detected "
"anomalies, sorted by anomaly_strength. Links anomaly locations to the planned path.\n\n"
"7. Energy Budget: Battery percentage consumed, uphill vs downhill energy breakdown, "
"energy per km, and overall energy_risk (LOW/MODERATE/HIGH).\n\n"
"8. Summary Recommendations: 3–5 concrete action items based on all findings, "
"including mission feasibility classification (NOMINAL / MARGINAL / HIGH_RISK)."
)

qa(40,
"Why is the report generated by rule-based template filling rather than an LLM?",
"Three reasons justify the rule-based approach:\n\n"
"1. Factual accuracy: Mission-critical reports must contain only numbers that come "
"directly from the analytical pipeline. An LLM might hallucinate plausible-sounding "
"but incorrect values (e.g., 'The path length is approximately 15 km' when it is "
"actually 8.1 km). Template slot-filling guarantees every number in the report "
"is directly sourced from the pipeline's dict outputs.\n\n"
"2. Determinism and auditability: Given the same inputs, the rule-based system "
"produces identical output every time. This is required for reproducible science "
"and mission review processes. An LLM's output varies with temperature settings "
"and can change with model updates.\n\n"
"3. Offline operation: Anveshak is designed to run without internet connectivity "
"(no API dependency). An LLM API call would require network access, introduce "
"latency, and create a subscription cost. The rule-based system runs entirely "
"offline at near-zero latency (~0.1 seconds)."
)

qa(41,
"How is mission feasibility (NOMINAL / MARGINAL / HIGH_RISK) determined?",
"Feasibility classification uses a priority-ordered rule system applied to the "
"combined analysis results:\n\n"
"HIGH_RISK is declared if ANY of: top site final_score < 0.3 (unsafe terrain), "
"max path slope > rover's max_slope_deg (route exceeds rover limits), "
"battery_pct_used > 75% (energy risk HIGH), or path was not found at all.\n\n"
"MARGINAL is declared if ANY of: top site final_score 0.3–0.5 (borderline terrain), "
"max path slope 0.8 × max_slope_deg to max_slope_deg (approaching rover limits), "
"battery_pct_used 40–75% (MODERATE energy risk), or fewer than 3 top sites found.\n\n"
"NOMINAL is declared if none of the above conditions apply — safe terrain, "
"path within limits, and comfortable energy margin.\n\n"
"The classification uses AND/OR logic on numerical thresholds, which is "
"auditable and explainable — a mission planner can directly check which "
"criterion triggered the classification."
)

add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# MODULE 8 — System Architecture / main.py
# ══════════════════════════════════════════════════════════════════════════════
section_heading("Module 8: System Architecture & main.py")

qa(42,
"What is the lifespan context manager in main.py? Why is terrain loading handled there?",
"FastAPI's lifespan context manager (decorated with @asynccontextmanager) runs code "
"at server startup and shutdown. In main.py it uses asyncio.to_thread to run "
"load_terrain() in a background thread without blocking the FastAPI event loop. "
"If terrain loading succeeds, the global state (elevation, slope, roughness, profile) "
"is populated and _terrain_loaded = True. If it fails (e.g., DEM files not found), "
"it falls back to _synthetic_terrain().\n\n"
"Terrain loading takes ~12 seconds and is CPU/IO bound. Running it inside the event "
"loop directly would block ALL requests for 12 seconds — FastAPI is single-threaded "
"in its event loop, so a synchronous call there would make the server completely "
"unresponsive. asyncio.to_thread() moves the blocking work to a ThreadPoolExecutor "
"thread, keeping the event loop free to handle /health polling requests from the "
"frontend during the loading period."
)

qa(43,
"Why does Anveshak store terrain arrays in global module-level variables rather than "
"a database or per-request loading?",
"Two key reasons:\n\n"
"1. Performance: The terrain arrays are ~1.2 GB in total. Loading them from disk "
"for every request would add ~12 seconds of latency per analysis — completely "
"unacceptable for interactive use. Storing them in global memory (RAM) means "
"all subsequent requests access them at memory bandwidth speeds (~50 GB/s), "
"taking microseconds rather than seconds.\n\n"
"2. Reproducibility: The LOLA DEM is static — the lunar terrain doesn't change. "
"There is no need for session-specific state, transactions, or concurrent writes. "
"A relational database would add architectural complexity with zero benefit. "
"The trade-off is that the server is stateful: restarting the server clears the "
"terrain state and requires a fresh ~12-second load. For a planning tool that "
"runs on a local workstation or a single-node server, this is entirely acceptable.\n\n"
"The design explicitly prioritises simplicity and interactivity over distributed "
"scalability — a deliberate choice noted in the paper."
)

qa(44,
"What is a Pydantic BaseModel? How does it validate the /analyze POST request?",
"Pydantic is a Python data validation library that FastAPI uses for request body "
"parsing. The RoverProfile class inherits from pydantic.BaseModel and declares "
"typed fields with optional default values:\n\n"
"mission_type: str = 'water_ice'\n"
"power_source: str = 'rtg'\n"
"max_slope_deg: float = 15.0\n"
"min_flat_radius_m: float = 300.0\n"
"battery_wh: float = 1000.0\n"
"rover_mass_kg: float = 150.0\n"
"priority: float = 0.3\n\n"
"When a POST /analyze request arrives, FastAPI automatically deserialises the JSON "
"body into a RoverProfile instance, validating types (str, float) and reporting "
"clear error messages if required fields are missing or malformed. This prevents "
"invalid inputs from reaching the analytical pipeline (e.g., negative slope limits, "
"non-numeric battery capacity). The Pydantic model acts as the API contract — "
"it is also automatically documented in FastAPI's /docs OpenAPI interface."
)

qa(45,
"What is the significance of validating Anveshak against Chandrayaan-3 and Artemis III sites?",
"Validation against real missions provides external ground truth to assess whether "
"the automated system agrees with expert human judgement:\n\n"
"Chandrayaan-3 (69.37°S, 32.32°E): The system correctly identifies this location "
"as outside its 80–90°S coverage boundary and reports COVERAGE_BOUNDARY_WEAK. "
"This is scientifically correct — C3 targeted a sub-polar technology demonstration "
"site deliberately outside the extreme polar zone. The system's explanation "
"('prioritises 80–90°S where ice deposits are theoretically concentrated') "
"aligns with the scientific rationale for polar vs sub-polar mission planning.\n\n"
"Artemis III sites: Shackleton Ridge gets the highest final_score (0.603, SAFE_LANDING) "
"matching its #1 priority ranking in NASA's published site selection documents [18]. "
"Faustini Crater gets safety=0.000 (correct — inaccessible steep walls) with high "
"mission_score (correct — high science value). All four sites receive terrain "
"classifications consistent with NASA expert consensus. This cross-validation "
"establishes that the automated pipeline can reliably reproduce expert-quality "
"site assessments without requiring domain expertise from the user."
)

qa(46,
"What are the main limitations of Anveshak and how could they be addressed?",
"1. Single data source: Only topographic data (DEM). No thermal (Diviner), radar "
"(Mini-RF SAR for ice detection), or spectral (Kaguya MI) data integration. "
"Improvement: Add Mini-RF Circular Polarisation Ratio as a water-ice scoring feature.\n\n"
"2. Simplified illumination model: estimate_sunlight() uses a selenographic "
"approximation, not true horizon-integrated shadowing. Improvement: Implement the "
"horizon algorithm — for each pixel, compute terrain horizon in 360 directions "
"using DEM ray-casting.\n\n"
"3. Auto-labelling circularity: RF classifier trained on scorer labels limits "
"theoretical independence. Improvement: Use human-annotated validation from "
"published NASA site assessments as an alternative ground truth.\n\n"
"4. Static offline planning: A* computes paths from full DEM before mission. "
"No dynamic replanning if terrain differs from DEM (e.g., after dust storms). "
"Improvement: Integrate with onboard LIDAR for dynamic D* replanning.\n\n"
"5. Single-rover planning: Only one traverse path. Improvement: Multi-rover "
"coverage partitioning with communication relay optimisation.\n\n"
"6. No rock abundance: DEM can't resolve individual boulders (<60 m). "
"Improvement: Use LROC NAC imagery at 0.5 m/pixel for final site confirmation."
)

add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# BONUS — Concept & Terminology Questions
# ══════════════════════════════════════════════════════════════════════════════
section_heading("Bonus: Key Concepts & Terminology")

qa(47,
"What is a Permanently Shadowed Region (PSR) and why is it significant?",
"A Permanently Shadowed Region is a crater floor, polar depression, or terrain "
"feature that never receives direct sunlight due to the Moon's small axial tilt "
"(~1.54°) and the high obliqueness of sunlight at polar latitudes. At the south "
"pole, some crater floors have been in permanent shadow for billions of years. "
"Temperatures in PSRs can drop below −200°C, cold enough to trap and preserve "
"volatile compounds — particularly water ice — that would sublimate on illuminated "
"terrain. The LCROSS impact confirmed water ice in Cabeus Crater's PSR in 2009. "
"PSRs are the primary scientific targets for water-ice prospecting missions, making "
"them central to Anveshak's water_ice mission scoring model (which rewards "
"proximity to PSRs and low-elevation potential PSR sites)."
)

qa(48,
"What is an Affine Transform and how is it used in Anveshak?",
"An affine transform is a mathematical mapping between pixel coordinates (row, col) "
"and geographic/projected coordinates (x, y in metres). In rasterio/GDAL it is "
"represented as a 6-parameter matrix:\n\n"
"x = c + col × a  (a = pixel width in metres, c = x at top-left)\n"
"y = f + row × e  (e = pixel height in metres (negative), f = y at top-left)\n\n"
"For Anveshak's 60 m/pixel grid: a = 60 m, e = −60 m, c = −609,570 m, f = +609,570 m "
"(polar-stereographic metres from the south pole). The inverse transform (~affine) "
"converts projected XY back to pixel indices. This is used in pixel_to_latlon() "
"(for displaying site coordinates) and latlon_to_pixel() (for user-specified start/goal "
"coordinates). When the grid is downsampled by factor 3, the affine is scaled: "
"new_affine = native_affine × Affine.scale(3), doubling the pixel width to 60 m."
)

qa(49,
"What is the difference between slope and roughness? Are they not measuring the same thing?",
"Slope and roughness both characterise terrain complexity but at different spatial scales:\n\n"
"Slope is the first derivative of elevation — the rate of elevation change per unit "
"horizontal distance, measured in degrees at the single-pixel level (60 m scale). "
"A crater rim has high slope; a flat plain has near-zero slope.\n\n"
"Roughness is the local standard deviation of elevation within a neighbourhood "
"(3×3 pixels = 180 m × 180 m). It measures how much elevation varies relative "
"to the local mean, independent of the overall slope direction. A uniformly sloped "
"ramp has zero roughness (all elevations predictably increasing) but nonzero slope. "
"A boulder field on a flat plain has high roughness but potentially low slope.\n\n"
"For rover mission planning both matter independently: slope determines whether "
"the rover can traverse without tipping; roughness determines whether the chassis "
"suspension can accommodate ground undulations. A smooth steep slope is "
"unlandable but traversable. A flat rough surface is landable but may damage "
"the rover's wheels and chassis."
)

qa(50,
"Why does the A* heuristic use `min_cost × euclidean_distance` rather than just "
"`euclidean_distance`?",
"A heuristic h(n) is admissible if it never overestimates the true cost to reach "
"the goal. The true cost along any path is at minimum min_cost × euclidean_distance "
"(every step costs at least min_cost = the cheapest passable pixel cost = 60 × exp(0) = 60 m, "
"multiplied by the Euclidean distance in pixels). Using just euclidean_distance (i.e., "
"implicitly assuming each step costs 1 pixel) would underestimate even more than "
"min_cost × distance when min_cost > 1, but would be less informative. Using "
"min_cost × distance provides a tighter lower bound, making the heuristic more "
"informed — it guides the search more aggressively toward the goal and reduces the "
"number of nodes expanded. Since min_cost ≤ actual_cost at every pixel (exponential "
"cost is always ≥ base), h(n) ≤ actual remaining cost, preserving admissibility "
"and guaranteeing A*'s optimality guarantee."
)

# ── Save ──────────────────────────────────────────────────────────────────────
doc.save("Anveshak_QA.docx")
print("Saved: Anveshak_QA.docx")
print(f"Total Q&A pairs: 50")
