# Score edit sheet · The Lampbearer 守灯人

> Generated automatically by `edit.py` (re-running overwrites it). Times in seconds. "Film" = the 74.5 s film timeline; "P" = time in the source track (decoded by ffmpeg at 48 kHz, same as a DAW import).

## Source

| Title | Composer | Page / direct link | Licence |
|---|---|---|---|
| Precipice | Scott Buckley | https://www.scottbuckley.com.au/library/precipice/ · https://www.scottbuckley.com.au/library/wp-content/uploads/2021/01/sb_precipice.mp3 | CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/) |

Composer's description: "A short, sweeping fantasy orchestral track evoking the anticipation of approaching the unknown, the confusion and terror as you cross the threshold, and the pride and relief as you learn and grow from your discoveries." (third place in the Orchestral Tools "Discovery" competition).
Only this one track is used: the source itself runs "anticipation → terror at crossing the threshold → pride and relief", the same arc as the film's "setting out with the lamp → storm → the lighthouse lit", so key, orchestration and mix space are naturally consistent, and every edit point is inside the same piece. The original mp3 is in `src/`.

Structure of the source (librosa analysis): P0–12 D pedal pad (about -43 dB) → P12–36 first section in D/G/B♭ major, flowing and gradually opening out → P36–49 crescendo to the first high point (G) → P50–76 turns to D minor / A dominant pedal, the tense section → **P79.7 sudden shift from D to G♭, low brass / bass voices enter, the climax of the piece begins** → G♭–B♭m–E♭–Fm–D♭–B♭m → **P104.9 lands on the final E♭ chord**, P105–117 natural decay.

## Edit table (film ← source)

| Segment | Film | Source P | Notes |
|---|---|---|---|
| S1 | 0.30–11.60 | 4.70–16.00 | 2 s cosine fade-in from 0.3 s; the D pedal pad plays under the chapter card; at film ≈7.6 s the source swells for the first time, landing on the harbour-town wide shot |
| Pause | 11.60–12.40 | — | **The lamp goes out, a "drop into nothing"**: cosine fade-out over 11.48–11.60, then a synthetic room reverb tail (RT60 1.5 s, -7 dB) lets the music "breathe out"; 0.8 s with essentially no music |
| S2 | 12.40–42.00 | 18.486–48.086 | Resumes on the bass entry of the G chord (automatically aligned to the onset, measured in the film at 12.386); continuous all the way: pier → night forest → the source's own crescendo at film 34–35.5 → storm |
| Drop-out | 42.00 | hard cut at P48.09 | 50 ms cosine cut + synthetic reverb tail (RT60 1.6 s, -9 dB), "the wind blows the flame out"; after 0.5 s only a held tone at about -44 dBFS remains |
| S3 | 42.05–44.90 | 6.20–9.05 | The opening D pedal pad returns at -4 dB as the only, very soft held tone; equal-power crossfade with S4 over 44.3–44.9 |
| S4 | 44.30–66.95 | 70.546–93.195 | The source's own build before the climax (A dominant pedal → D); **the G♭ downbeat at P79.746 = film 53.500** |
| S5 | 66.95–76.50 | 104.849–114.40 | Jumps to the arrival of the final E♭ chord (bass onset), natural decay; cosine fade to 0 over 75.2–76.5 |

### Jump points

| Film position | From P | To P | Crossfade | Alignment |
|---|---|---|---|---|
| 11.60 → 12.40 | 16.00 (B♭ chord decaying) | 18.486 (G-chord bass onset) | None (0.8 s pause + reverb tail in between) | The source itself has a phrase breath at P17.3; here it is stretched into a pause |
| 42.00 | 48.086 | — | 50 ms fade-out + reverb tail | Cut just before the bass accent at P48.2, so that it is "swallowed" |
| 44.30 | opening pad P6.20 | 70.546 | 0.6 s equal power | D pad → A/D dominant pedal, the same harmony |
| 66.949 | 93.195 (onset inside the Fm bar) | 104.849 (bass onset of the E♭ arrival) | 60 ms equal power, crossfade ends at the onset | Pitch content in the 0.5 s before each side is C / F / D♭ on both; the E♭ onset is kept whole |

## The 53.5 hit point

- The climax is not made by an edit: it is the source's own D → G♭ modulation downbeat (bass voices enter, source energy below 250 Hz rises +8.2 dB within 40 ms). The whole of S4 is placed at the fixed offset `P_hit − 53.5`, so the accuracy of the hit depends only on locating the onset.
- `edit.py` searches the <250 Hz energy envelope of the source over P79.66–79.82 (43 ms frames, 2.5 ms hop, 20 ms smoothing) for the steepest 40 ms rise and takes its midpoint as the onset, giving P_hit = 79.7463; S4 placement offset = P_hit − 53.5 = 26.2463; after rounding to 48 kHz samples the theoretical error is < 0.02 ms.
- Measured in the finished score.wav with the same detector (±150 ms search): onset at **53.4963 s, error -3.7 ms** (requirement < 60 ms).
- So that it reads as "the full orchestra coming in" rather than just the top of a crescendo: a 10 dB "intake of breath" dip over 53.12–53.42, recovering to 0 dB within 5 ms over 53.495–53.500, and the downbeat comes in untouched. RMS of the 300 ms before -28.6 dB → 300 ms after -13.9 dB (+14.6 dB).
- The build over 44.3–53.2 uses "level-following" automation: the source's 0.5 s short-term RMS is pulled towards a rising target line from -42 dB to -22 dB (-18/+10 dB clamp, 300 ms smoothing); the small peak at P71–72 is held down and the dip at P73–76 is lifted level, so in the film 44.5→52.75 is a steady crescendo (about -43 → -22 dBFS).

## Measured RMS (score.wav, dBFS)

| Film | Section | Section RMS | 0.4 s window max | 0.4 s window min |
|---|---|---|---|---|
| 0.0–5.5 | Chapter card | -39.4 | -36.3 | -94.3 |
| 5.5–11.6 | Harbour town at night (narration N1) | -31.1 | -25.1 | -44.5 |
| 11.6–12.4 | Lamp-out pause | -43.4 | -40.8 | -54.6 |
| 12.4–25.5 | Harbour town / pier | -31.1 | -25.2 | -51.1 |
| 25.5–35.5 | Night forest | -26.5 | -20.4 | -40.3 |
| 35.5–42.0 | Storm, stone steps | -19.9 | -18.1 | -23.8 |
| 42.0–44.3 | Flame almost out (drop-out) | -37.8 | -31.1 | -45.9 |
| 44.3–53.5 | Relit → climbing the tower | -29.6 | -22.5 | -43.5 |
| 53.5–67.0 | Climax: beam sweeps the sea | -14.7 | -12.2 | -20.4 |
| 67.0–74.5 | Title wrap-up | -17.3 | -12.4 | -28.4 |
| 74.5–76.5 | Reverb tail | -33.7 | -30.4 | -57.9 |

Overall RMS -20.3 dBFS, sample peak -1.12 dBFS (4× oversampled true peak ≤ -1.1 dBFS). No loudness normalisation.

Loudness curve, 1 s windows (dBFS, labelled by window start):
`0s:-57 1s:-42 2s:-38 3s:-38 4s:-37 5s:-41 6s:-40 7s:-40 8s:-36 9s:-31 10s:-26 11s:-29 12s:-33 13s:-30 14s:-31 15s:-31 16s:-36 17s:-45 18s:-38 19s:-37 20s:-32 21s:-26 22s:-31 23s:-31 24s:-29 25s:-28 26s:-26 27s:-29 28s:-28 29s:-33 30s:-38 31s:-34 32s:-29 33s:-25 34s:-22 35s:-20 36s:-20 37s:-20 38s:-22 39s:-20 40s:-19 41s:-19 42s:-35 43s:-45 44s:-43 45s:-38 46s:-38 47s:-37 48s:-35 49s:-32 50s:-30 51s:-27 52s:-24 53s:-16 54s:-15 55s:-18 56s:-14 57s:-14 58s:-13 59s:-14 60s:-18 61s:-17 62s:-15 63s:-14 64s:-13 65s:-16 66s:-14 67s:-13 68s:-14 69s:-20 70s:-18 71s:-19 72s:-24 73s:-27 74s:-29 75s:-34`

## Gain automation (CONFIG in edit.py)

- Static gain points `GAIN_POINTS`: 0s +3dB, 5.3s +3dB, 5.8s +0dB, 11.6s +0dB, 12.4s -3dB, 25s -4dB, 31s -6dB, 35.2s -6dB, 35.8s -3dB, 41.9s -1dB, 42s +0dB, 76.5s +0dB (linear interpolation in dB)
- Ducking under the narration `NARR_DIP_DB`: 6.8–11 -3.5dB, 12.6–13.7 -2dB, 17.8–23.2 -3.5dB, 27–30.1 -2dB, 59.5–63 -1.5dB (350 ms cosine transitions)
- 42.0–44.9 pedal pad -4 dB
- 44.3–53.5: level-following crescendo; 53.12–53.50 intake of breath; 0 dB after 53.5
- 75.2–76.5: cosine fade-out to 0

## How to change it

Edit CONFIG at the top of `edit.py`: `T_HIT` moves the climax time (S4 shifts as a whole; the length of the build follows `T_SILENCE[1]`); `T_CAESURA` changes the lamp-out pause; `GAIN_POINTS` / `NARR_DIP_DB` change the loudness curve. Then run `../../../../.venv/bin/python edit.py` in this folder; score.wav, measure.json and CUES.md are updated together.
