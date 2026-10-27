# Fact sheet: 《地图上还写着海》 (On the Map It's Still a Sea)

Every number, year and factual claim in the film is in the tables below: claim → official source (URL) → source wording. Quotations are in the original English. NASA Earth Observatory's old domain earthobservatory.nasa.gov now 301-redirects to science.nasa.gov; the addresses below are the redirect targets. Checked on 2026-10-15.

On-screen text and subtitles are Chinese; they are quoted as they appear, with an English gloss.

Two kinds of number must be kept apart:

- **Official figures**: taken directly from the wording of NASA, USGS and the World Bank (table A below).
- **Image measurements**: measured by this film itself on USGS Landsat imagery (the year-ring shorelines, the percentage "still under water", the distance from Moynaq to the sea; table B below). On screen they are all labelled "Landsat 测算 / 影像实测" (Landsat estimate / measured from imagery); the method and the scenes used are given here and compared one by one against the official figures.

## A. Official figures and claims

| # | Claim in the film (picture / narration) | Source | Wording |
|---|---|---|---|
| A1 | Map label "咸海" (Aral Sea), "地图 · 约 68,000 km²" (map · about 68,000 km²) | USGS EROS Earthshots, "Aral Sea, Kazakhstan and Uzbekistan" https://eros.usgs.gov/earthshots/aral-sea-kazakhstan-and-uzbekistan | "The Aral Sea once covered about 68,000 square kilometers…" |
| A1′ | Map layers: blue sea surface, shoreline, shoreline hachures drawn like depth contours, rivers (Amu Darya, Syr Darya) | Natural Earth `ne_10m_lakes_historic` (public domain), feature "Aral Sea", featurecla = "Historic Lake"; rivers from `ne_10m_rivers_lake_centerlines` (public domain). The hachures inside the shoreline are a cartographic printing convention and do not represent depth data | Polygon area computed by this film: 67,501 km², consistent with the UNEP GEAS 2014 bulletin "approximately 66,000 km2 – 67, 500 km2 (depending on source)" |
| A2 | Narration "On the map, this is still a sea." | Natural Earth's current lakes layer `ne_10m_lakes` still names these two bodies of water "North Aral Sea" / "South Aral Sea"; the place name itself says "sea" | Rhetorical line, no figure |
| A3 | Narration "Then its rivers went to the cotton fields." | NASA Earth Observatory, World of Change: Shrinking Aral Sea https://science.nasa.gov/earth/earth-observatory/world-of-change/aral-sea | "In the 1960s, the Soviet Union undertook a major water diversion project…" / "…were used to transform the desert into farms for cotton and other crops." |
| A4 | Narration "By 2014, the eastern basin had dried.", subtitle "到 2014 年，东边的湖盆干涸了" (by 2014 the eastern basin had dried) | NASA Earth Observatory, *The Aral Sea Loses Its Eastern Lobe* (2014-09-26 Image of the Day) https://science.nasa.gov/earth/earth-observatory/the-aral-sea-loses-its-eastern-lobe-84437 | "For the first time in modern history, the eastern basin of the South Aral Sea has completely dried." |
| A5 | Narration "This was a fishing port.", label "莫伊纳克 · 旧渔港" (Moynaq · former fishing port) | NASA MODIS Image Gallery, 2014-05-04 https://modis.gsfc.nasa.gov/gallery/individual.php?db_date=2014-05-04 | "…a vibrant center of the Aral Sea's fishing industry" / "…rusting ship hulks sitting on dry land, far from any water." |
| A6 | Label "科卡拉尔大坝 · 2005 年建成 · 长 13 km" (Kok-Aral Dam · completed 2005 · 13 km long) | World Bank 2008 Feature Story https://documents1.worldbank.org/curated/en/888771468089960580/pdf/462360BRI0Box31e0no0FS231Kazakhstan.pdf | "the 13 km Kok-Aral Dike … Completion was in August 2005." |
| A7 | Readout "北咸海水面 +37% · 2001→2009 · 世界银行" (North Aral Sea surface +37% · 2001→2009 · World Bank); the ring years 2001 and 2009 are aligned with it | World Bank Implementation Completion Report ICR0000874 (2011-06-21), SYR DARYA CONTROL AND NORTHERN ARAL SEA PHASE-1 PROJECT (P046045) https://documents1.worldbank.org/curated/en/189171468038051254/pdf/ICR8740P0460450Official0Use0Only090.pdf | "increased by 37% from 2,400 km2 in 2001 to 3,300 km2 in 2009" |
| A8 | Narration "And the water came back." | Same as A7 | "NAS water levels above Baltic Sea Level (BSL) increased from a pre-project low of 38 m to the desired design level of 42 m." |
| A9 | Narration "The sea did not come back on its own. Someone kept it." | Same as A7 (the project is the "someone": the SYNAS project of the government of Kazakhstan and the World Bank) | Rhetorical line, no figure |
| A10 | Targeting-box readout "北纬 45° 东经 60°" (45°N 60°E) | The centre of the Natural Earth historic lake polygon is at about 45.1°N, 59.8°E, rounded | Position label |
| A11 | Image credit "影像 Landsat · USGS/NASA  Blue Marble · NASA" (imagery Landsat · USGS/NASA, Blue Marble · NASA) | USGS data citation page https://www.usgs.gov/centers/eros/data-citation ; NASA image use guidelines https://science.nasa.gov/earth/faq/ | "federally created data and therefore reside in the public domain"; "freely available for re-publication or re-use, including commercial purposes… We ask that NASA be given credit" |

## B. Image measurements (made by this film)

### B1. Year rings and "the part still under water"

Method: for each year, cloud-free Landsat scenes from July–October of that year are mosaicked into one latitude/longitude raster (0.0024° longitude × 0.0017° latitude per pixel, about 190 m). Water: for TM/ETM+/OLI a joint threshold on MNDWI (green − shortwave infrared) and NDWI; for MSS green − near infrared (0.8–1.1 µm) plus a dark near-infrared value. Only water bodies that fall inside the Natural Earth historic sea surface and are ≥ 25 km² are kept, and islands < 3 km² are filled in. Pixel areas are corrected for latitude and summed. Shoreline = the 0.5 contour of the water mask (marching squares), simplified to about 115 m. Percentage = measured water area ÷ 68,000 km² (A1). Code: `tools/fetch_landsat.py`, `tools/plates.py`, `tools/vectors.py`; results in `assets/vectors.json` and `assets/plates/plates.json` (including which scene each pixel comes from).

| Year (on screen) | Imagery used | Measured water area | On-screen readout |
|---|---|---|---|
| 1977 | Landsat 2 MSS, 34 scenes, 1977-07-25 to 09-22 (including 6 same-year scenes to fill holes, 1 of them L1GS); scan-line dropouts repaired (see B4) | 54,403 km² | 80% |
| 1989 | Landsat 4/5 TM, 27 scenes, 1989-06-14 to 10-13 (path 161 of 1989-08-16 excluded: a dust plume over the lake; 09-17 used instead) | 39,860 km² | 59% |
| 2000 | Landsat 7 ETM+, 28 scenes, 2000-07-17 to 09-29 | 26,879 km² | 40% |
| 2009 | Landsat 5 TM, 27 scenes, 2009-07-14 to 09-16 | 14,366 km² | 21% |
| 2014 | Landsat 8 OLI, 28 scenes, 2014-07-03 to 09-16 | 7,061 km² | 10% |
| 2025 | Landsat 8/9 OLI, 28 scenes, 2025-08-18 to 08-31 | 5,079 km² | 7% |

Comparison with the official figures:

- NASA EO 2001 (*The Shrinking Aral Sea*, https://science.nasa.gov/earth/earth-observatory/the-shrinking-aral-sea-1396/ ): "In the last 30 years, more than 60 percent of the lake has disappeared." This film measures 39.5% remaining in 2000, i.e. about 60% gone. Consistent.
- World Bank 2008 press release: "Between 1960 and 2004, the sea's surface area shrank almost 70 percent." 2004 falls between this film's 2000 (39.5%) and 2009 (21.1%), about 30%. Consistent.
- USGS Earthshots: "It is now only about 10% of the size it was in 1960." NASA EO 2024 (https://science.nasa.gov/earth/earth-observatory/dunes-and-desert-replace-the-aral-sea-152887 ): "…has decreased to approximately 10 percent of its original area." This film: 10.4% in 2014, 7.5% in August 2025 (that late summer was on the dry side; the official figure is approximate). The picture ends on the measured 7% and does not write "约 10%" (about 10%), so that the two numbers don't contradict each other.
- The "100%" before the 1977 readout is the sea on the map (A1) and does not correspond to any image.

### B2. From Moynaq's old port to today's shore: 95 km

- Start: the ship graveyard on the Moynaq waterfront (the old port shoreline), 59.030°E, 43.785°N.
- End: the water pixel nearest the start in the western basin of the South Aral Sea (the part of the sea that still exists) on the August 2025 Landsat mosaic, 58.323°E, 44.467°N.
- Method: the nearest point is searched only within the connected water body containing the western basin, using great-circle distance (R = 6371.0088 km): 94.5 km; the picture and narration use 95 km.
- Comparison: the ESA 2003 image caption (https://www.esa.int/ESA_Multimedia/Images/2003/07/Fishing_town_Muynak_is_now_150_km_from_water ) "Now the town is 150 km away from water." That is from 2003 and measured to a different body of water at the time, a different reference point, so this film does not use 150 km, only its own measurement made with a published method.

### B3. Position of the Kok-Aral Dam

The white line traces the dam body visible on 2025 Landsat imagery: north-west arm 60.750°E 46.120°N → corner 60.788°E 46.087°N → east arm 60.865°E 46.088°N. The dam body visible to the eye is about 10 km; the on-screen "长 13 km" (13 km long) uses the World Bank figure (A6), not the length of this white line.

### B4. Image repairs (they do not change the measurement)

- Scan-line dropouts in the 1977 Landsat 2 MSS imagery (whole rows near zero) are treated as invalid pixels and filled from neighbouring scenes; the remaining thin streaks (long straight lines at about 12°, 1-pixel seams between request tiles) are replaced with a cross-line median on land only; the lake surface and shoreline are left untouched (the shoreline is what is being measured).
- In 1989 one scene with a dust plume was replaced by the same path on 09-17 of the same year.
- Areas were measured again on the repaired imagery (table above): 1977 is 0.3% lower than before the repair, 1989 is 1.0% lower because of the scene swap; the on-screen readouts for both years (80%, 59%) did not change.

## C. Check before the final render

Before the final render, the 10 narration lines and the Chinese and English subtitles in `timeline.js`, all on-screen text in `film.js`, and `cues.json` and `satellite-briefing.srt` were checked line by line: every number and year can be traced to a source in the tables above; there is no number outside the tables.
