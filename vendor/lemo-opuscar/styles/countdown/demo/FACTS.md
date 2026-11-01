# Facts and sources · 《自己倒数》Counting Itself Down

Every piece of on-screen text and every claim in the narration, listed with its source and the source's wording. Times always follow NASA's official figures. Checked on 2026-10-20; before the last render the lines were checked one by one against this table (`audio/lines.json`, and in `index.html` the `CUES` / `CHECK` / `FLIGHT` / data cell / end card).

The source audio (launch commentary, loop calls) is not our claim; it is NASA's live broadcast soundtrack itself. The basis of the transcription is in §T.

On-screen text is bilingual; it is quoted as it appears (Chinese / English). Chinese-only labels get an English gloss.

## On screen / narration

| On screen or narration | Claim | Source |
|---|---|---|
| 阿尔忒弥斯二号 · 2026 年 4 月 1 日 · 39B 发射台 / ARTEMIS II · APRIL 1, 2026 · LC-39B, KENNEDY SPACE CENTER | Launch date, launch pad | F1 |
| Crew name tags: 怀斯曼 (Wiseman) CDR, 格洛弗 (Glover) PILOT, 科赫 (Koch) MS, 汉森 (Hansen) MS · CSA | Crew and roles | F1 |
| Checklist T−33 移交自动程序 GO FOR ALS | Planned milestone | F2 |
| Checklist T−30 芯级计算机接管 CORE STAGE → ALS | Planned milestone | F2 |
| Checklist T−12 氢气燃烧点火器 H2 BURN-OFF IGNITERS | Planned milestone | F2 |
| Checklist T−10 发动机启动指令 ENGINE START CMD | Planned milestone | F2 |
| Checklist T−6.36 RS-25 启动 (RS-25 start); event flag "RS-25 ×4 启动 ENGINE START · T−6.36" | Planned milestone; the core stage's 4 RS-25s | F2, F4 |
| Checklist T−0 助推器点火 · 升空 (booster ignition · liftoff) | Planned milestone | F2 |
| "听到 −32.1 / −6.0 / +0.2" (heard at −32.1 / −6.0 / +0.2) (red tags) | The times actually called out in the source audio (measured for the film, see §T) | Measurement |
| Data cell: SLS BLOCK 1 · 880 万磅 8.8 M LBF; 土星五号 (Saturn V); +15% SLS 多 15% | Liftoff thrust and the comparison | F4 |
| Document cell: 10 天试飞 10-DAY TEST FLIGHT; 先绕地球 2 圈 2 EARTH ORBITS FIRST | Mission figures | F5 |
| Narration N1 "About ten days: around the Moon, and back." | Planned round trip around the Moon of about 10 days | F5 |
| Narration N2 "Next on the clock: booster separation, at two minutes nine."; milestone cell "预计 T+2:09 EXPECTED" | Expected time of booster separation | F3 |
| Milestone cells 升空 (liftoff) / 滚转、俯仰 (roll, pitch) / 休斯敦接管 (Houston takes over) (tick times) | The times called out in the source audio (measured for the film) | Measurement, F3 |
| Control bar 地面 GLS → 火箭 ALS → 休斯敦 HOUSTON (ground GLS → rocket ALS → Houston) | GLS hands over to the automated launch sequencer; Houston takes over after liftoff | F2, F3, source audio |
| End card: 素材 NASA · 公有领域 · 非官方作品 (footage NASA · public domain · unofficial work) | Footage licence | CREDITS |

## F1 Launch date, time, pad, crew
- NASA image caption "Artemis II Launch": https://www.nasa.gov/image-detail/artemis-ii-launch-5/
  > "Wednesday, April 1, 2026"
  > "The quartet launched at 6:35 p.m. EDT"
  > "from Launch Complex 39B at NASA's Kennedy Space Center in Florida"
  > "Reid Wiseman, commander; Victor Glover, pilot; Christina Koch, mission specialist;"
  > "and CSA (Canadian Space Agency) astronaut Jeremy Hansen, mission specialist"
- Corroboration: the UTC time burned into the tracking-telescope footage, 22:35:27 (film 51.5 s, i.e. T+19) = 18:35 US Eastern, consistent with F1.

## F2 Countdown milestones (planned times)
- NASA "NASA Releases Artemis II Moon Mission Launch Countdown": https://www.nasa.gov/general/nasa-releases-artemis-ii-moon-mission-launch-countdown/
  > "T-33S – GLS sends "go for automated launch sequencer" command"
  > "T-30S – Core stage flight computer to automated launching sequencer"
  > "T-12S – Hydrogen burn off igniters initiated"
  > "T-10S – GLS sends the command for core stage engine start"
  > "T-6.36S– RS-25 engines startup"
  > "T-0: Booster ignition, umbilical separation, and liftoff"

## F3 Source audio after liftoff (NASA's official transcript)
- NASA Scientific Visualization Studio "Artemis II launch live": https://svs.gsfc.nasa.gov/31385/ , subtitle file `Artemis 2 launch long.srt` (https://svs.gsfc.nasa.gov/vis/a030000/a031300/a031385/Artemis%202%20launch%20long.srt)
  > "Sound suppression. / Water is flowing." "And here we go." "RS 25 Engines lit." "Booster. / Ignition and lift off."
  > "The crew of Artemis two, now bound for the moon." "Humanity's next great voyage begins."
  > "Good role. / Pitch." "Roger Role, Pitch" (i.e. roll / pitch)
  > "Houston. / Now controlling the flight of integrity on the Artemis two mission around the Moon."
  > "Standing by for main engine throttle down to 85% ahead of solid rocket booster separation expected at the two minute nine second mark."
  > "Confirm separation."
- Integrity is the name of this mission's Orion spacecraft; the source is the official transcript line above.
- Commentary from the same broadcast at T−47 s (not used in the film; it supports the "control bar"): "The rocket will count itself down, but honor any holds that could come from the ground." "Now, shortly after liftoff, Houston will take control of the rocket." (broadcast excerpt in this film 0.0–9.7 s, Whisper transcription)

## F4 Thrust and engines
- NASA RS-25 engine fact sheet: https://www.nasa.gov/sites/default/files/atoms/files/sls_rs25_engine_fs_508.pdf
  > "During liftoff, the Block 1 configuration of SLS will produce 8.8 million pounds of thrust — 15 percent more than the Saturn V rockets that launched astronauts on journeys to the Moon."
  > "It will use four RS-25 engines for the core stage, along with two solid rocket boosters."
- The film's data bars are drawn at 1.15 : 1; no separate figure for the Saturn V is written.
- "the most powerful rocket NASA has ever launched" is the live commentary's own wording, not our claim.

## F5 Mission figures (the plan before launch)
- NASA Artemis II one-page overview AIIFS-08.27.25 (archived on Wikimedia Commons, PD-USGov-NASA): https://commons.wikimedia.org/wiki/File:Artemis_II_One_pager_082725_508_(1974822455374).pdf
  > "10 DAY TEST FLIGHT" "2 EARTH ORBITS"
  > "Many of these will be completed as Orion flies two elliptical orbits around Earth before venturing around the Moon."
  > "Orion will fire its thrusters and send the crew on a trip of about 10 days around the far side of the Moon and back to Earth."
- Note: this was the plan at the time of launch. NASA's mission page (https://www.nasa.gov/mission/artemis-ii/) later gives the actual mission duration as "9 Days, 1 Hour, 32 Minutes". The film takes the real-time point of view of the moment of launch, so the narration says "about ten days" (the plan), not the actual duration.

## §T Transcription and timing measurements
- T0 (film 32.5 s): the jump of the broadcast picture's countdown bug from T−0:00:32 to 31 + the word-level time of the commentary's "booster" (film 32.70); the two agree.
- "GLS, go for ALS." (film 0.40): Whisper base.en / small hear it as "go for your left", and medium drops the line; it is judged to be "go for ALS" from the F2 T−33 milestone (GLS sends "go for automated launch sequencer") and the commentary that follows immediately, "Great call-out. The rocket is on its own." The time actually called out in the source audio is T−32.1 (the milestone table gives the planned T−33); the checklist marks the two separately.
- "RS-25 engines lit": Whisper sometimes hears "lift"; NASA's official transcript (F3) has "lit".
- "Good roll, pitch." / "Roger, roll, pitch." at film 46.40 / 49.78 (T+13.9 / +17.3); "Houston, now controlling…" at film 53.78 (T+21.3).
- Timing of the vehicle camera (CAM 3): the burned-in timer jumps from "001-04:17:27.3" to "002-00:00:01.0"; the "002" segment reaches zero at source 34.8 s, taken as T0. The broadcast soundtrack that comes with the same file is about 1 s off the picture, so its sound is not used for timing.
- The control room (CAM 2) has no clock to sync to; it is labelled "同一时段 SAME WINDOW · 未逐帧同步" (not frame-synced).
