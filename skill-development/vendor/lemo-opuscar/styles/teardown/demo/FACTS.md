# Fact sheet: 《二十一键》 21 Keys, Opened

Every number and factual claim in the film is in the tables below: claim → source (URL) → source wording. The project files are pinned at foostan/crkbd commit 63366fb (2025-05-10). Checked on 2026-10-16.

On-screen labels and subtitles are Chinese; they are quoted as they appear, with an English gloss.

Two kinds of number are kept apart:

- **Wording of the project files**: written directly in the build guide, the BOM and the KiCad files (A).
- **Measured from CAD**: measured by this film from the project's STEP / KiCad geometry (B); the method is given below and can be reproduced with `tools/`.

## A. Wording of the project files and component documentation

| # | Claim in the film (picture / narration) | Source | Wording |
|---|---|---|---|
| A1 | Narration "Twenty-one keys. Half a keyboard."; subtitle "二十一个键，半把键盘" (twenty-one keys, half a keyboard) | README https://github.com/foostan/crkbd/blob/63366fb7f51cf2a796462fdd90527e99dd126055/README.md | "The Corne keyboard is a split keyboard with 3x6 column staggered keys and 3 thumb keys" (3×6 + 3 = 21 per half) |
| A2 | Label "键帽 1u ×20 · 1.5u ×1" (keycaps) | v4 build guide https://github.com/foostan/crkbd/blob/63366fb7f51cf2a796462fdd90527e99dd126055/docs/corne-cherry/v4/buildguide_en.md | "\| Keycaps \| 42 - 46 \| 1u 40 pcs, 1.5u 2 pcs \|" (both halves together; 20 + 1 per half) |
| A3 | Label "机械轴体 十字轴 ×21" (mechanical switches, cross stem ×21); "热插拔 ×21" (hot-swap ×21); narration "Hot-swappable. No soldering." | Same as A2; README | "\| Key switches \| 42 - 46 \| Only Cherry MX compatible \|"; README "v4 Hotswappable". The left half in KiCad has 21 switch footprints `keyswitch_cherrymx_hotswap_1u` / `_1.5u` (hot-swap socket footprints) |
| A4 | Label "定位板 FR-4 · 1.6 mm" (switch plate) | Same as A2 | "\| Switch plate \| 1 set \| FR4 1.6mm thick \|" |
| A5 | Label "铜柱 M2 × 7.5 mm ×4" (brass standoffs) | Same as A2 | "\| Spacer M2 \| 8 \| 7.5 mm For Case assembly \|" (both halves together; 4 per half); screws "\| Screw M2 \| 16 \| 5 mm For Case assembly \|"; feet "\| Rubber cushion \| 8 \|" |
| A6 | Label "电路板 双层 · 1.6 mm" (circuit board, two layers) | KiCad board file https://github.com/foostan/crkbd/blob/63366fb7f51cf2a796462fdd90527e99dd126055/pcbs/corne-cherry/hotswap/corne-cherry.kicad_pcb | `(general (thickness 1.6))`; the stack-up has only two copper layers, `"F.Cu"` and `"B.Cu"`, `(rev "4.1.0")` |
| A7 | Label "主控 RP2040 · 7 × 7 mm" (controller); narration "One RP2040 chip runs it all." | BOM https://github.com/foostan/crkbd/blob/63366fb7f51cf2a796462fdd90527e99dd126055/pcbs/corne-cherry/hotswap/jlcpcb/production_files/BOM-corne-cherry.csv ; RP2040 datasheet https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf | BOM: "RP2040,\"U1,rU1\",QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm"; datasheet: "The RP2040 7×7 mm QFN-56 package …" |
| A8 | Label "闪存 16 MB" (flash) | BOM (as A7); Winbond W25Q128JV datasheet https://www.winbond.com/resource-files/w25q128jv%20revf%2003272018%20plus.pdf | BOM: "W25Q128JVSIQ,\"U4,rU4\",SOIC-8_5.23x5.23mm_P1.27mm"; datasheet: "W25Q128JV: 128M-bit / 16M-byte" |
| A9 | Label "灯珠 ×23 · 反贴" (LEDs ×23 · reverse-mounted); narration "Twenty-three lights, mounted upside down." | BOM (as A7); KiCad board file | The BOM lists YS-SK6812MINI-E: LED1–LED21, EXLED1–2 (23 on the left half; the right half has another 23 with an r prefix); in KiCad all these footprints are on `(layer "B.Cu")` (the back), and the -E suffix of the part number means reverse-mount |
| A10 | Position and footprint of the crystal, 0402 resistors and capacitors, USB-C, TRRS jack and reset button in the picture | KiCad board file, BOM | Footprint names and coordinates read as they are (e.g. "Crystal_SMD_3225-4Pin_3.2x2.5mm", "TYPE-C-31-M-13C", "PJ-398A-5A_PJ-399B-6A"); no text labels |
| A11 | Narration "Every one of them is drawn in open files." / "Every number is public." | Repository licences https://github.com/foostan/crkbd (LICENSE_CC, LICENSE_MIT) | The repository is published under CC BY 4.0 (LICENSE_CC) and MIT (LICENSE_MIT); every file this film uses is in that repository |

## B. Measured from CAD

| # | Claim in the film | Method | Result |
|---|---|---|---|
| B1 | Dimension line "键距 19.05 mm" (key pitch 19.05 mm); narration "Nineteen point oh five millimetres apart." | Centre distance between neighbouring switch positions in the KiCad board file: SW19 (−128.5875, −7.14375) and SW18 (−109.5375, −7.14375) | 19.050 mm (the column pitch is 19.05 across the whole board) |
| B2 | Dimension lines "138.4 mm", "97.6 mm", "11.1 mm" | Bounding box of the case STEP https://github.com/foostan/crkbd/blob/63366fb7f51cf2a796462fdd90527e99dd126055/cases/3x6/left.step after triangulation with occt-import-js (`tools/step2mesh.mjs`) | 138.35 × 97.62 × 11.10 mm, shown to one decimal place |
| B3 | Label "外壳 底厚 2.0 mm" (case, floor thickness 2.0 mm) | Same as B2: heights of the horizontal faces of the case mesh, underside −11.40, inner floor −9.40 | 2.00 mm |
| B4 | Exploded layers and assembled heights (relative positions of the parts in the picture) | Inner floor 2.0 + standoff 7.5 (A5) + plate 1.6 (A4) = 11.1 mm, exactly the height of the case rim (B2); the plate's 4 Ø2.2 holes line up with the case screw holes and the circuit board's Ø5 holes | The three files agree with one another; the circuit board sits 5.0 mm below the plate (the standard mounting height for cross-stem switches) |
| B5 | Narration "Take it apart: six layers." | This film's way of grouping the layers: keycaps, switches, plate, circuit board, standoffs, case (screws and feet go with the adjacent layer) | An editorial grouping, not a number from the project files |

## C. Parts of the picture that are not data

The keycap profile, the switch housings, all material colours, the metallic look of the case, the position of the feet and the heights of the components on the back are modelling choices based on common specifications; no numbers are labelled for them on screen.
