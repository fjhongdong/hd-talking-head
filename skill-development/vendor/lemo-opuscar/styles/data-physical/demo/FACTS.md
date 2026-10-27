# Fact sheet: 《两条螺旋》Two Spirals

Every number and factual claim in the film is in the tables below: claim → source (URL) → source wording. The data are IRENA's "Renewable Energy Statistics" (2026 edition), as processed and published by Our World in Data (CC BY 4.0). The original CSVs and metadata were downloaded on 2026-10-16 and are stored unchanged in `data/`:

- `data/world_solar_capacity_irena2026.csv`, `data/owid_solar_capacity.metadata.json` — https://ourworldindata.org/grapher/installed-solar-pv-capacity
- `data/world_wind_capacity_irena2026.csv`, `data/owid_wind_capacity.metadata.json` — https://ourworldindata.org/grapher/cumulative-installed-wind-energy-capacity-gigawatts

Definitions of the two datasets (metadata wording):

- Solar: "Total solar (on- and off-grid) electricity installed capacity, measured in gigawatts. This includes solar photovoltaic and concentrated solar power." Chart subtitle: "Cumulative installed solar capacity, measured in gigawatts (GW)."
- Wind: "Total wind (on- and off-grid) electricity installed capacity, measured in gigawatts. This includes onshore and offshore wind." Chart subtitle: "Cumulative installed wind energy capacity including both onshore and offshore wind sources, measured in gigawatts (GW)."
- Citation format (metadata wording): "IRENA (2026) – processed by Our World in Data. “Total solar capacity” [dataset]. IRENA, “Renewable Energy Statistics” [original data]." (wind the same, "Total wind capacity")

So in the film "solar" = photovoltaic + concentrated solar power and "wind" = onshore + offshore, both cumulative installed capacity at year end (GW), world total (OWID entity "World").

On-screen text and subtitles are Chinese; they are quoted as they appear, with an English gloss.

## A. Numbers in the picture and narration

| # | Claim in the film (picture / narration) | Source | Wording (CSV row) |
|---|---|---|---|
| A1 | Readout "2014 风电 349.5 GW" (2014 wind 349.5 GW) | Wind CSV | `World,OWID_WRL,2014,349.49323` |
| A2 | Readout "2014 太阳能 178.8 GW" (2014 solar 178.8 GW) | Solar CSV | `World,OWID_WRL,2014,178.84773` |
| A3 | Verdict "风电 = 太阳能 × 1.95" (wind = solar × 1.95); narration "In 2014, the world had almost twice as much wind power as solar." / subtitle "将近太阳能的两倍" (nearly twice solar) | A1 ÷ A2 | 349.49323 ÷ 178.84773 = 1.954 → 1.95, "nearly twice" |
| A4 | Readouts "2020 风电 733.3 GW" (2020 wind), "2020 太阳能 721.2 GW" (2020 solar) | Both CSVs | `World,OWID_WRL,2020,733.2712`; `World,OWID_WRL,2020,721.2222` |
| A5 | Readouts "2021 风电 824.2 GW" (2021 wind), "2021 太阳能 865.9 GW" (2021 solar) | Both CSVs | `World,OWID_WRL,2021,824.1905`; `World,OWID_WRL,2021,865.921` |
| A6 | Verdict "2021 · 太阳能超过风电" (2021 · solar passes wind); narration "In 2021, solar passed wind." | A4, A5: at the end of 2020 solar was still 12.0 GW behind, at the end of 2021 it was 41.7 GW ahead. Wind was ahead in every year 2014–2020 (see CSVs) | Measured as cumulative installed capacity; the first year it passed is 2021 |
| A7 | 2025 counter rolls from "1,883.2" to "2,396.7 GW", "2025 · 太阳能累计装机" (2025 · cumulative solar capacity) | Solar CSV | `World,OWID_WRL,2024,1883.1776`; `World,OWID_WRL,2025,2396.7092` |
| A8 | "当年新增 +513.5 GW" (added that year +513.5 GW); narration "In 2025 alone, solar added more than five hundred gigawatts." / subtitle "新增了 500 多 GW" (added more than 500 GW) | Difference in A7 | 2396.7092 − 1883.1776 = 513.53 GW (difference between two cumulative values, including PV and CSP; not IRENA's separately published "additions" table, and IRENA revises earlier cumulative values every year) |
| A9 | Disc engraving "×1.86 · 太阳能 ÷ 风电 · 2025" (×1.86 · solar ÷ wind · 2025); "2025 · 太阳能装机是风电的 1.86 倍" (2025 · solar capacity is 1.86 times wind); narration "Now it is the other way round." | Both CSVs | 2396.7092 ÷ 1291.015 = 1.856 → 1.86; wind 2025: `World,OWID_WRL,2025,1291.015` |
| A10 | Narration "Wind kept growing. Solar grew faster." | Both CSVs | 2014→2025 wind 349.5 → 1,291.0 (×3.7), solar 178.8 → 2,396.7 (×13.4); wind grew every year |
| A11 | Narration "Step back, and twelve years become one dial." | 2014–2025 is 12 years | Rhetorical line |

## B. Scale of the physical objects (a conversion set by this film)

- **1 disc = 10 GW** (the same unit for both materials): number of discs = round(capacity ÷ 10). E.g.: 2025 solar 239.67 → 240 discs, wind 129.10 → 129 discs; 2014 solar 17.88 → 18 discs, wind 34.95 → 35 discs. Height error < half a disc (5 GW).
- **Every 10th disc is brass**: brass discs mark each full 100 GW.
- In 2020 the two values differ by 12.0 GW (73 discs vs 72); after rounding wind is still one disc higher, so rounding never flips the order.
- Numbers on screen always use the original values (one decimal place); the physical height is only to scale.
- Discs dropped for the 2025 additions = 240 − 188 = 52 discs (= 2025 disc count − 2024 disc count); the counter interpolates linearly over the discs that have landed, and shows the original value 2,396.7 when the last disc lands.

## C. Check

- Before the last render, the narration and `LABELS` in `timeline.js` were compared item by item with this table (2026-10-16).
- On-screen numbers are formatted directly from `data.js` (`fmt`, one decimal place); 1.95, 1.86 and +513.5 are values computed in this table and written into `LABELS` in `timeline.js`; the disc engraving in `set.js` is computed from the data as `(SOLAR[11] / WIND[11]).toFixed(2)`.
