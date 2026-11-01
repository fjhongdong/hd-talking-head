# Facts and sources ·《蜜蜂账本 The Bee Ledger》

Every number on screen and every fact in the voice-over comes from one official report:

**USDA NASS, "Honey Bee Colonies"**, ISSN 2470-993X, released 3 August 2026 (US federal government work, public domain).
- PDF: https://release.nass.usda.gov/reports/hcny0726.pdf
- Release page: https://esmis.nal.usda.gov/publication/honey-bee-colonies
- Scope: operations with five or more colonies, United States total. The report is a **quarterly** survey.

Checked on 2026-10-20. Before the last render, the table below was compared item by item against `audio/lines.json` and `timeline.json`.

## On screen / voice-over

The on-screen text is Chinese and is quoted as it appears, with an English gloss.

| # | On screen (Chinese) | Voice-over (English) | Figure | Source |
|---|---|---|---|---|
| 1 | 一年没了 130 万箱蜜蜂 (1.3 million colonies gone in one year) | "In one year, American beekeepers lost one point three million honey bee colonies." | Losses of the four quarters of 2025 added up: 1,305,540 colonies | F1 (derived, arithmetic below) |
| 2 | ≈49% · 接近年初总数的一半 (nearly half of the total at the start of the year) | "Nearly half of what they started with." | 1,305,540 ÷ 2,639,300 = 49.5 % | F1, F2 (derived) |
| 3 | 那美国的蜜蜂快没了？ (So are America's bees running out?) | "So, are America's bees running out?" | (question, no figure) | — |
| 4 | Highlighted source line "January 1 Honey Bee colonies Up 6 Percent"; +6%; 1 月 1 日的总数涨了 6% (the January 1 total rose 6%) | "No. By January, colonies were up six percent." | 2.81 million colonies on 2026-01-01, +6 % on 2025-01-01 | F3 |
| 5 | Colony line chart: 264 / 288 / 312 / 295 / 281 / 284 (万箱, tens of thousands of colonies); +6%; 总数不降反升 (the total rose instead of falling) | (no voice-over) | Colonies on the first day of each quarter | F2, F3 |
| 6 | 死掉 1,305,540 箱 (1,305,540 died) / 补上 1,453,600 箱 (1,453,600 added) / 多补 148,060 箱 (148,060 more added than lost); 2025 · 四个季度相加 (2025 · four quarters added up); 因为养蜂人一直在补：145 万箱 (because beekeepers kept rebuilding: 1.45 million colonies) | "Because beekeepers kept rebuilding: almost one and a half million new colonies." | Additions added up: 1,453,600; difference 148,060 | F1 (derived) |
| 7 | 新建 / 整箱买 / 换蜂王 (raise new / buy whole / requeen); 补法有三种 (three ways to rebuild) | "They raise new ones, buy them whole, or give old ones a new queen." | The report's definitions of "added" and "requeened" | F6 |
| 8 | Highlighted source lines "Varroa Mites Top Colony Stressor…" and "Varroa mites were the number one stressor … during all quarters surveyed in 2025."; 2025 年每个季度的头号威胁：瓦螨 (top threat in every quarter of 2025: varroa mites) | "The top stressor, every quarter of 2025: varroa mites." | Varroa share in the four quarters of 2025: 28.3 / 26.3 / 22.2 / 25.4 %, the highest in each quarter | F4 |
| 9 | 谁在伤害蜂群 (what is harming the colonies): 瓦螨 (varroa mites) 21.8%, 农药 (pesticides) 6.4%, 其他虫害 (other pests) 5.6%, 疾病 (diseases) 4.8%, 原因不明 (unknown) 4.6%, 其他 (other) 3.5%; 2026 年初，超过五分之一的蜂群受害 (early 2026: more than one in five colonies affected) | "In early 2026, they affected more than one in five colonies." | National stressor shares, January–March 2026 | F5 |
| 10 | Loss rate by quarter 12 / 11 / 11 / 12 / 16 / 11 %; 16% · 六个季度最高 (16% · highest of six quarters); 这一季最糟：三个月没了 16% (the worst quarter: 16% gone in three months) | "That quarter was the worst in six: sixteen percent gone in three months." | Losses January–March 2026: 454,890 colonies, 16 % | F1, F3 |
| 11 | Map of loss rate by state (2026 Q1); 加州 −220,000 · 损失率 18% (California −220,000 · loss rate 18%); 光加州就没了 22 万箱 (California alone lost 220,000 colonies) | "California alone lost two hundred and twenty thousand." | California, January–March 2026: 220,000 colonies lost, 18 % | F7 |
| 12 | 到 6 月，又补了 108 万箱 (by June, another 1.08 million colonies added) | "And still, by June, they had added over a million more." | 2026 January–March 464,320 + April–June 619,850 = 1,084,170 | F1 (derived) |
| 13 | 蜜蜂没有消失 / 是养蜂人在硬撑 (the bees aren't vanishing / beekeepers are holding the line) | "The bees aren't vanishing. Beekeepers are holding the line." | Conclusion (follows from 4, 6, 12) | — |
| End card | 2025 年损失和新增为四个季度相加 (2025 losses and additions are the four quarters added up) | — | Note on scope | — |

## F1 Losses and additions by quarter (national row, tables on pages 3–8)

| Quarter | Colonies at start of quarter | Lost | Loss rate | Added | Renovated | Page |
|---|---|---|---|---|---|---|
| 2025 Jan–Mar | 2,639,300 | 328,500 | 12 | 539,200 | 158,710 | 3 |
| 2025 Apr–Jun | 2,876,810 | 302,100 | 11 | 561,090 | 514,790 | 4 |
| 2025 Jul–Sep | 3,121,610 | 327,840 | 11 | 182,750 | 356,810 | 5 |
| 2025 Oct–Dec | 2,954,950 | 347,100 | 12 | 170,560 | 121,970 | 6 |
| 2026 Jan–Mar | 2,805,370 | 454,890 | 16 | 464,320 | 215,440 | 7 |
| 2026 Apr–Jun | 2,841,280 | 321,910 | 11 | 619,850 | 507,890 | 8 |

Source wording (national row of the table on page 3):
> "United States ........... 2,639,300 (X) 328,500 12 539,200 158,710 6"

Derived figures (added up by us; labelled "四个季度相加" (four quarters added up) in the film):
- 2025 losses: 328,500 + 302,100 + 327,840 + 347,100 = **1,305,540** (≈1.3 million)
- 2025 additions: 539,200 + 561,090 + 182,750 + 170,560 = **1,453,600** (≈1.45 million; voice-over "almost one and a half million")
- Difference: 1,453,600 − 1,305,540 = **148,060**
- 2026 first-half additions: 464,320 + 619,850 = **1,084,170** (≈1.08 million; voice-over "over a million")
- Caution on scope: the report surveys each quarter separately, so the four quarterly losses added together are **not a "net annual loss"** (colonies are added between quarters all the time). The film therefore says only "一年没了" (gone in one year) and "四个季度相加" (four quarters added up), never "net loss".

## F2 Colonies at the start of the year, and "nearly half"

Page 1 wording:
> "During 2025, honey bee colonies on January 1, April 1, July 1, and October 1 were 2.64 million, 2.88 million, 3.12 million, and 2.95 million colonies, respectively."

1,305,540 ÷ 2,639,300 = 0.4947 → the film's "≈49%" and "接近年初总数的一半" (nearly half of the total at the start of the year).

## F3 +6 %, the latest two quarters

Page 1 wording:
> "Honey bee colonies for operations with five or more colonies in the United States on January 1, 2026 totaled 2.81 million colonies, up 6 percent from January 1, 2025. The number of colonies in the United States on April 1, 2026, was 2.84 million colonies."
> "Honey bee colonies lost for operations with five or more colonies from January through March 2026, was 454,890 colonies, or 16 percent. The number of colonies lost during the quarter of April through June 2026, was 321,910 colonies, or 11 percent."

Check: 2,805,370 ÷ 2,639,300 = 1.063. "六个季度最高" (highest of six quarters): the loss rates of the six quarters are 12, 11, 11, 12, 16, 11; 16 is the highest.

## F4 Varroa mites, the top stressor in every quarter of 2025

Page 1 wording (these are the two lines the highlighter sweeps in the film):
> "Varroa Mites Top Colony Stressor for Operations with Five or More colonies"
> "Varroa mites were the number one stressor for operations with five or more colonies during all quarters surveyed in 2025."

National rows on pages 9–12 (varroa mites / other pests / diseases / pesticides / other / unknown, %): Jan–Mar 28.3 / 7.1 / 4.4 / 6.2 / 5.1 / 5.9; Apr–Jun 26.3 / 9.2 / 4.3 / 6.5 / 5.0 / 2.0; Jul–Sep 22.2 / 6.6 / 3.5 / 4.3 / 2.7 / 2.9; Oct–Dec 25.4 / 5.6 / 5.2 / 4.5 / 4.6 / 5.7. Varroa is the highest in every quarter.

"Stressor" is the report's word and means "the share of colonies affected by it during the quarter"; it is not a cause of death. The voice-over says "top stressor" and the Chinese text says "头号威胁" (top threat), never "头号杀手" (top killer).

## F5 Stressors, January–March 2026 (national row, page 13)

> "United States .................. 21.8 5.6 4.8 6.4 3.5 4.6"

Column order: Varroa mites / Other pests and parasites / Diseases / Pesticides / Other / Unknown. The film's ranking runs from largest to smallest: varroa mites 21.8, pesticides 6.4, other pests 5.6, diseases 4.8, unknown 4.6, other 3.5. 21.8 % > 1/5 → "超过五分之一" and "more than one in five".
Table header note:
> "[Percent of colonies affected by stressors anytime during the quarter. A colony may be affected by multiple stressors during the quarter]"

Inconsistency inside the report (not used in the film): the page 1 text says varroa affected "26.3 percent" in April–June 2026, while the national row of the table on page 14 gives 22.2. The film uses only January–March (21.8, where text and table agree).

## F6 Definitions of added and renovated colonies (page 16)

> "Added colonies: A new or replacement, surviving colony that was either created or purchased whole by an operation."
> "Renovated colony: An existing colony that was requeened or received a nuc or package."
> "Package: A shipping container with several pounds of honey bees that may or may not include a queen; used for expansion of the apiary operation or renovating an existing colony."

In the film, "新建" (raise new ones) = created; "整箱买" (buy them whole) = purchased whole (a photo of a bee package stands for bought bees); "换蜂王" (give old ones a new queen) = requeened. Note: the report counts requeening as renovated, not as "added"; the film's triptych is about "ways to rebuild", and the voice-over does not say all three count towards the 1.45 million.

## F7 States, January–March 2026 (page 7)

State loss rate = the state's losses ÷ the state's "maximum colonies" (colonies at the start of the quarter + colonies moved in during the quarter); national loss rate = national losses ÷ colonies at the start of the quarter (table note 2). The map colours only the 20 states listed individually in the table; the remaining states (combined as "Other States") are grey, "未单列" (not listed separately).

| State | Loss rate % | State | Loss rate % |
|---|---|---|---|
| California | 18 | New York | 17 |
| Florida | 15 | North Carolina | 18 |
| Georgia | 17 | North Dakota | 2 |
| Idaho | 15 | Ohio | 7 |
| Iowa | 4 | Oregon | 7 |
| Louisiana | 8 | Pennsylvania | 23 |
| Michigan | 5 | South Dakota | 1 |
| Minnesota | 2 | Texas | 11 |
| Mississippi | 7 | Washington | 2 |
| Montana | (Z) <0.5 | Wisconsin | 8 |

California row, source wording:
> "California ................. 885,000 1,250,000 220,000 18 179,000 73,000 6"

## Notes on the pictures (not statements of fact, but they must be honest)

- The almond orchard photo was taken in February 2014 (USDA, McFarland, California); its corner label reads "加州杏仁园 2014" (California almond orchard 2014). It stands for the apiary setting in California, not the scene of the 2026 losses.
- The rooftop apiary video was shot in 2013 (on the roof of USDA headquarters in Washington); the lower third gives the place and year.
- The rows-of-hives video was shot in the Netherlands (Altena TV); in the film it serves only as a picture of "one hive = one colony", carries no place label and is not presented as a US scene.
- The channel "简闻" (Jianwen) is fictional. The film is an unofficial work and has nothing to do with USDA.
