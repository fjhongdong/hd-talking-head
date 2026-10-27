# Fact sheet: 《差两秒》 Two Seconds Short

Every date, number, call number and factual claim in the film is in the table below, in the form: claim → official source (URL) → source wording (in the original English). Checked on 2026-10-16.

On-screen labels and index lines are Chinese (some bilingual); they are quoted as they appear, with an English gloss.

**How it was checked**: the loc.gov item pages are blocked by a Cloudflare human-verification check and can't be opened with curl or WebFetch. So the catalogue records were taken instead from the Library of Congress's own SRU catalogue service (`http://lx2.loc.gov:210/lcdb`, MARCXML); the raw records are saved in `sources/sru_*.xml` and can be re-queried with `tools/sru.py`. Image files were taken directly from the Library's `tile.loc.gov` master storage; only the colour scan of the telegram was obtained via Wikimedia Commons, whose page gives LoC `mcc.061` as the source. The text of the telegram was read from the image itself (the original is a primary historical document).

| # | Claim in the film (picture / narration / subtitle) | Source | Wording |
|---|---|---|---|
| F1 | Narration "December seventeenth, nineteen oh three.", telegram line "Kitty Hawk N C Dec 17" | LoC catalogue, P&P copy of the telegram `cph.3b12982` (LC-USZ62-65459), `sources/sru_cph.3b12982.xml`; image of the original telegram | 245: "[Telegram from Orville Wright in Kitty Hawk, N.C., to his father announcing four successful flights, 1903 Dec. 17]" |
| F2 | Narration "Orville wired home: success, four flights."; index line "01 电报 · 1903.12.17 · LC-USZ62-65459" (01 telegram) | Same as F1; telegram text (image) | Telegram text: "Success four flights thursday morning all against twenty one mile wind …"; addressee "Bishop M Wright / 7 Hawthorne St" |
| F3 | Narration "The longest, fifty-seven seconds."; readout "电报 · 最长一次 57 秒" (telegram · longest 57 seconds) | Telegram text (image, `assets/raw/telegram_mcc061.jpg`, LoC `mcc.061`) | "… through air thirty one miles longest 57 seconds inform Press home … Christmas" |
| F4 | Narration "Next day, the paper printed the same number."; label "1903.12.18 / 代顿先驱报" (Dayton Herald); index line "02 代顿先驱报 · LC-USZ62-70686" (02 Dayton Herald) | LoC catalogue `cph.3b18080` (LC-USZ62-70686), `sources/sru_cph.3b18080.xml`; clipping text (image) | 245: "[Newspaper notice of Wright Bros. 1st flight: Dayton Herald, Dec. 18, 1903]"; clipping text: "Our longest time in air was 57 seconds. ORVILLE WRIGHT." |
| F5 | Narration "The first flight lasted twelve seconds. One hundred and twenty feet."; label "第一次飞行 / 12 秒 · 120 英尺 · 上午 10:35" (first flight / 12 seconds · 120 feet · 10:35 a.m.); index line "03" | LoC catalogue `ppprs.00626` (LC-DIG-ppprs-00626), `sources/sru_ppprs.00626.xml` | 245: "[First flight, 120 feet in 12 seconds, 10:35 a.m.; Kitty Hawk, North Carolina]"; 260: "[1903 Dec. 17]" |
| F6 | Picture "玻璃底片" (glass negative) (the first negative) | Same as F5 | 300: "1 photograph : glass negative, dry plate ; plate 18 x 12.5 cm (5 x 7 format)." |
| F7 | Label "快门：John T. Daniels" (shutter: John T. Daniels) | Same as F5 | 520: "(Orville Wright preset the camera and had John T. Daniels squeeze the rubber bulb, tripping the shutter.)" |
| F8 | Label "威尔伯·莱特 / Wilbur Wright" (the person on the right of the photo) | Same as F5 | 520: "Wilbur Wright running alongside to balance the machine, has just released his hold on the forward upright of the right wing." |
| F9 | Narration "The fourth flight: eight hundred and fifty-two feet, in fifty-nine seconds."; readout "852 英尺 / 59 秒" (852 feet / 59 seconds); comparison card quotation "852 feet covered in 59 seconds."; index line "04 · LC-DIG-ppprs-00629" | LoC catalogue `ppprs.00629` (LC-DIG-ppprs-00629), `sources/sru_ppprs.00629.xml` | 245: "[Distant view of the Wright airplane just after landing, taken from the starting point, with wing-rest in center of picture and launching rail at right. This flight, the fourth and final of December 17, 1903, was the longest: 852 feet covered in 59 seconds.]" |
| F10 | Measuring line from "起点" (starting point) to "落地点" (landing point) | Same as F9 | "… taken from the starting point …" (the camera position is the starting point) |
| F11 | Narration "The telegram was two seconds short."; verdict "差 2 秒" (2 seconds short) | Comparison of F3 and F9: the telegram says 57, the Library's record says 59 | The difference between the two numbers; the film does not speculate about why it is wrong |
| F12 | Index line "05 试飞受损 · 1903.12.14 · LC-DIG-ppprs-00610" (05 damaged in a trial) (a prop on the light table) | LoC catalogue `ppprs.00610`, `sources/sru_ppprs.00610.xml` | 245: "[Wilbur in prone position in damaged machine on ground after unsuccessful trial of December 14, 1903; Kitty Hawk, North Carolina]" |

## Illustrative, not measured

- The scale for the fourth flight is laid out in the perspective of "flat ground + pinhole camera": the distance of a given row from the camera is D = K / (row − horizon row), where K comes from the recorded 852 feet and the row of the bottom edge of the landed machine (horizon at row 1385, bottom edge of the machine at about row 1410, K = 852 × 25). The picture labels it "透视刻度（示意）" (perspective scale (illustrative)). It only lays the recorded 852 feet onto the photograph; it is not a distance measured from the photograph.
- The 0 → 59 second readout rolls in step with the scale; it is only animation and does not represent moments during the flight.

## Notes on image processing

- The "negative image" of the glass negative on the light table is made by inverting the Library's positive scan in the shader and adding a film-base colour. The "positive image" in the loupe is the Library's scan itself.
- Once the first negative enters photo space, the flying machine and Wilbur are cut out as separate layers (`tools/prep.py`: difference keying in the sky, only strong edges cut on the sand), and the holes behind them are filled with pyramid interpolation plus grain. The machine is moved about 125 pixels (scan pixels) across the picture: this is animation, not the historical flight path.
