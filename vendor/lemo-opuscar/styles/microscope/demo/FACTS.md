# Fact sheet: 《量出来的蓝》 Measured Blue

Every number and factual claim in the film is in the tables below: claim, source (URL), source wording. Quotations are kept in the original English. Checked on 2026-10-16.

On-screen labels are Chinese; they are quoted as they appear, with an English gloss.

The numbers fall into two kinds:

- **File and sources**: taken directly from the slide file's metadata or from public descriptions (table A).
- **Measured by this film**: measured on this scan by the film itself (table B). On screen each comes with its measuring method (a pixel count under “胶原（蓝）占组织面积” (collagen (blue) share of tissue area), “核膜外缘拟合” (fit to the outer edge of the nuclear membrane) under the nucleus diameter); the methods are given here and can be reproduced with `tools/plates.py` and `tools/nucleus.py`.

The film only describes measurement results; it makes no diagnosis and assigns no stage.

## A. File and sources

| # | Claim in the film (picture / narration) | Source | Wording |
|---|---|---|---|
| A1 | “一片人肝组织” (a slice of human liver tissue), “人肝组织 · 三色染色” (human liver tissue · trichrome stain); narration “One slice of human liver.” | OpenSlide test data index https://openslide.cs.cmu.edu/download/openslide-testdata/Ventana/index.yaml | `Ventana-1.bif: credit: PathAI · description: Human liver, trichrome stain, brightfield, joint direction LEFT, scanned on Ventana DP 200 · license: CC0-1.0` |
| A2 | Source credit “全切片扫描 Ventana DP 200 · PathAI · CC0” (whole-slide scan) | Same as A1; file XMP | `ScannerModel="VENTANA DP 200"` |
| A3 | Narration “The stain turns collagen blue.”; readout label “胶原（蓝）” (collagen (blue)) | Wikipedia “Trichrome staining” https://en.wikipedia.org/wiki/Trichrome_staining | “A trichrome stain can colour the muscle tissue red, and the collagen fibres green or blue. Liver biopsies may have fine collagen fibres between the liver cells, and the amount of collagen may be estimated based on the staining method.” |
| A4 | Scale bar, field-of-view readout | File XMP (level 0), and the TIFF XResolution of level 0 | `Magnification="40" ScanRes="0.25"`; XResolution 40000 px/cm (i.e. 0.25 µm/px) |
| A5 | Gauge “等效 1.25× / 2.5× / 5× / 10× / 20× / 40×” (equivalent magnification) | TIFF ImageDescription of each pyramid level | `level=0 mag=40`, `level=1 mag=20` … `level=5 mag=1.25` |
| A6 | The opening photo of the whole slide and its scale | Page 0 of the file, `Label_Image`, XResolution = 4294967295/9091032 px/cm; the scan-area coordinates are in AOI0 in the XMP | `<AOI0 Left="297" Top="2323" Right="574" Bottom="2069"/>`. Computed at 21.167 µm/px, with Top counted from the bottom edge |

## B. Measured by this film

| # | Number in the film | Method | Result |
|---|---|---|---|
| B0 | (registration check, not on screen) | The slide photo and the scan are registered via AOI0 and the pixel sizes of both; then a darkness mask on each gives the tissue centroid and area, cross-checked | Centroids differ by 19 µm (less than 1 pixel of the photo); area ratio 0.999 |
| B1 | “4.80 mm”; narration “Four point eight millimeters across.” | On level 3 (2 µm/px), take a tissue mask (not glass and not low saturation), close it and fill holes, keep the largest connected component, run principal component analysis and take its projected extent along the main axis | 4.80 mm (width 2.80 mm) |
| B2 | Circle A “胶原（蓝）占组织面积 13.5%” (collagen (blue) share of tissue area 13.5%), “97,058 / 716,763 px”; narration “blue covers thirteen point five percent” | Pixel-by-pixel classification on level 2 (1 µm/px): tissue = (luminance < 200) or (RGB range > 40); blue collagen = tissue and B > R + 12 and B ≥ G. Circle centre at level-0 coordinates (8393, 13083), diameter 1 mm (1000 px); share = blue pixels in the circle / tissue pixels in the circle | 97,058 / 716,763 = 13.5% |
| B3 | Circle B “32.6%”, “232,688 / 713,354 px”; narration “thirty two point six” | Same as B2, centre (13425, 10578) | 232,688 / 713,354 = 32.6% |
| B4 | “相隔 1.41 mm” (1.41 mm apart); narration “One point four millimeters away” | Distance between the two circle centres × 0.25 µm/px | 1.41 mm |
| B5 | “B 的蓝色占比是 A 的 2.4 倍” (B's blue share is 2.4 times A's); narration “Two point four times the blue.” | B3 / B2 | 32.6 / 13.5 = 2.41 |
| B6 | “肝细胞核 8.5 µm” (hepatocyte nucleus 8.5 µm); narration “eight point five microns across” | On level 0 (0.25 µm/px), cast 72 rays from the nucleus centre; on each ray take the darkest point within 2–5 µm (the nuclear membrane), then search outwards for the point where brightness has recovered halfway, as the outer edge; fit a least-squares circle to the edge points, remove outliers and iterate 6 times | Radius 17.04 px, residual 0.72 px, diameter 8.52 µm; centre at (13295.0, 9266.8) |

The thresholds are empirical values for this trichrome-stained slide; the result of the blue mask was checked region by region with overlays (the counted pixels are visible on the measurement frames in `stills/`). The readouts mean “inside this circle, at these thresholds”; they are not a fibrosis grade in the clinical sense.

`tools/export.mjs` checks every number in the narration and subtitles in `timeline.js`; they must match the measured values in `assets/plates/plates.json` and `nucleus.json`, or the build fails.
