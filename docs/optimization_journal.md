# Optimization journal

Daily log of the optimization loop run by Claude (scheduled task "automatiseur-optimisation",
2026-10-23 to 2026-11-23, unless the owner pauses it). Each run reads this file first, adds
one dated entry, and keeps "Changes under evaluation" up to date. Newest entries at the top.

## Rules

The owner said (2026-10-23) that the strategy rules below are his guesses at what works best
to grow, and that the loop is free to reshape them when the evidence (our results, the big
clip channels) shows something better. Change them one at a time, with numbers, and say so in
the daily summary.

Strategy (hypotheses, may be reshaped with evidence):
- Two channels: LiveActions! = video games, PeakMoments = everything else (IRL, Just
  Chatting...). Each streamer in one whitelist, the one of their main content.
- Whitelist streamers keep priority; a standout whitelist streamer takes the day's Shorts.
- The streamer's learned score weighs much less than what the Short itself is; other
  channels never give points to a streamer.
- Learning from real results over many Shorts, never from a handful of lucky ones.
- Below a channel's top 30, nothing is kept or rendered. 10 uploads per 24 h per channel.
- Framing (what the 9:16 crop shows), hook style (white Bangers, black outline, no emoji),
  subtitles: owner preferences; change only with strong evidence, and tell the owner.

Hard limits (never change): never declare "made for kids"; never delete the owner's files,
never empty the recycle bin, never touch other projects, never reveal .env contents or tokens;
never run two instances of the app; ask the owner before anything irreversible or doubtful.

## Changes under evaluation

| Since | Change | Expected effect | Metric to watch | Verdict |
|---|---|---|---|---|
| 2026-10-23 | Gemini picks each Short's start and end (trimming.py); 30 s length test dropped | Shorts understandable alone, complete endings | share watched (retention_pct), views_3d | pending |
| 2026-10-23 | Cold open 3 s, starting 1 s before the reaction | fewer swipe-aways in the first seconds | retention_pct of cold_open=yes vs no | pending (early data: -0.3 pts for cold_open=yes) |
| 2026-10-23 | Ranking learned from real results (performance.py) | better Shorts published first | correlation of predicted_points with results (reliability) | pending (needs 30 measured Shorts) |
| 2026-10-23 | Gemini score reweighted by how well it predicts results | | gemini_weight | 0.89 on gaming (2026-10-23) |
| 2026-10-23 | Competitor format guide (competitors.py, weekly) used in selection, bounds, hooks, titles | Shorts made like the ones that work elsewhere | retention_pct and views of Shorts made after it vs before | pending |
| 2026-10-22 | Sharper encoding (CRF 18, Lanczos, sharpening), Twitch source quality | better-looking Shorts | retention_pct | pending |

## Entries

### 2026-10-23 - baseline

- Gaming: 66 measured Shorts. Learned: <25 s +0.3, >40 s -0.3, chat moments +0.2,
  cold open -0.3 (early). PeakMoments: no measured Shorts yet.
- Competitors: 10 gaming channels (290 Shorts), 6 IRL channels (176 Shorts). Ideal length
  from the format guide: gaming 15-45 s, IRL 15-25 s.
- Open idea, waiting for the owner: word-by-word subtitles in the middle of the screen
  (seen on the IRL channels that do best); it changes how the Shorts look.
