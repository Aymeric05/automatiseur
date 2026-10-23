# Optimization journal

Daily log of the optimization loop run by Claude (scheduled task "automatiseur-optimisation",
from 2026-10-23, with no end date, until the owner pauses it). Each run reads this file first, adds
one dated entry, and keeps "Changes under evaluation" up to date. Newest entries at the top.

## Rules

The owner said (2026-10-23) that the strategy rules below are their guesses at what works best
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

## Knowledge (accumulated, per channel)

What the loop has learned and how strongly. Each line: the pattern, the evidence (number of
Shorts and channels), the date seen first and last. Strengthen, weaken or remove lines as new
evidence comes; turn a strong line into an A/B test, then into the app's default.

### LiveActions! (gaming)
- Their hits (top third, 10 channels, 96 Shorts) vs flops: titles ~40 chars, 25% with emoji;
  ours 45 chars, 76-88% with emoji. Lengths: theirs median ~74 s (long Shorts up to 3 min), ours 31 s.
  (2026-10-23)
- Weekly guide: start at the heart of the action, one strong event, cut right after the climax,
  understandable without the game's lore. (2026-10-23)
- Gemini watch (5 hits vs 5 flops, UChCE_tZPaGv80-dH4kMY_Qg/CaseOh/NoPixel channels): hits = banner
  hook top of screen, strong emotion in the first seconds (rage/laugh/punchline), one tight fast-cut
  moment; flops = slow scripted RP, passive gameplay, no real stake. Test started: shorter titles,
  less emoji (gaming_title_style_v1). (2026-10-23)

### PeakMoments (irl)
- Their hits (6 channels, 58 Shorts) vs flops: hits ~28 s vs flops ~23 s; titles ~32 chars,
  60% emoji; ours 45 chars, 93% emoji, 31 s. (2026-10-23)
- Weekly guide: open on the key line or question, very expressive moments, cut right after the
  punchline, avoid moments needing long political or narrative context; ideal 15-25 s. (2026-10-23)
- Top Shorts of Kai Cenat Live / Hasanabi Clips use word-by-word subtitles in the middle (see
  proposal). (2026-10-23)
- Gemini watch (5 hits vs 5 flops, Kai Cenat/theGrefg/SNL UK-adjacent channels): hits = punchy
  visual/sound hook in the first second, context in under 3 s (split-screen, captions), climax at
  15-35 s; flops = no hook, long monologue explanations (>40 s), static shot. Test started: shorter
  titles, less emoji (irl_title_style_v1). (2026-10-23)

## Waiting for the owner

Risky or doubtful actions are never done directly: the loop writes them here (what, why with
numbers, risks, how to undo) and in its daily summary. The owner answers by writing OK or NON
at the start of the line (or tells Claude); the next run applies the OK ones, drops the NON
ones, and moves them to the entries.

- (proposal) Word-by-word subtitles in the middle of the screen, as on the IRL clip channels
  that do best. Why: seen on the top Shorts of Kai Cenat Live and Hasanabi Clips. Risk: changes
  how every new Short looks; could do worse. Undo: one setting. Waiting for data first.

## Changes under evaluation

| Since | Change | Expected effect | Metric to watch | Verdict |
|---|---|---|---|---|
| 2026-10-23 | Gemini picks each Short's start and end (trimming.py); 30 s length test dropped | Shorts understandable alone, complete endings | share watched (retention_pct), views_3d | pending |
| 2026-10-23 | Cold open 3 s, starting 1 s before the reaction | fewer swipe-aways in the first seconds | retention_pct of cold_open=yes vs no | pending (early data: -0.3 pts for cold_open=yes) |
| 2026-10-23 | Ranking learned from real results (performance.py) | better Shorts published first | correlation of predicted_points with results (reliability) | pending (needs 30 measured Shorts) |
| 2026-10-23 | Gemini score reweighted by how well it predicts results | | gemini_weight | 0.89 on gaming (2026-10-23) |
| 2026-10-23 | Competitor format guide (competitors.py, weekly) used in selection, bounds, hooks, titles | Shorts made like the ones that work elsewhere | retention_pct and views of Shorts made after it vs before | pending |
| 2026-10-22 | Sharper encoding (CRF 18, Lanczos, sharpening), Twitch source quality | better-looking Shorts | retention_pct | pending |
| 2026-10-23 | A/B gaming_title_style_v1: shorter, less emoji titles | retention/views closer to competitor hits | retention_pct, views_3d of B vs A | pending (0 measured) |
| 2026-10-23 | A/B irl_title_style_v1: shorter, less emoji titles | retention/views closer to competitor hits | retention_pct, views_3d of B vs A | pending (0 measured) |

## Entries

### 2026-10-23 - titres + bug de fin coupee

- Gaming : Gemini a regarde 5 hits/5 flops concurrents + nos 2 extremes + 3 Shorts recents. Hits =
  banniere d'accroche, emotion forte des les 1res secondes, montage nerveux ; nos 3 Shorts recents
  coupent tous la fin en plein mot. Test lance : titres plus courts, moins d'emoji
  (gaming_title_style_v1).
- IRL : memes conclusions (hook visuel/sonore immediat, contexte <3s, climax 15-35s) ; 1 Short sur 3
  aussi coupe en plein milieu de phrase. Test lance : titres plus courts, moins d'emoji
  (irl_title_style_v1).
- Bug corrige (trimming.py) : quand Gemini ne renvoie pas de bornes utilisables pour un moment, le
  Short gardait son ancienne fin heuristique sans jamais la recaler sur une vraie fin de phrase ->
  coupe en plein mot. Elle est maintenant toujours recalee. Commit + redemarrage app.

### 2026-10-23 - analyse complete (corrigee)

- Gaming : 66 mesures, IRL : 0. Reliability gaming 1.00, gemini_weight 0.87.
- La boucle avait desactive le cold open sur gaming (-0.3 vs +0.1). Annule par Claude dans la
  conversation principale : seulement 13 Shorts avec cold open, tous du 19 au 21/10, contre 53
  sans, surtout plus anciens. Echantillon trop petit et periode differente (confondu).
- Regle ajoutee : >= 20 Shorts par groupe ET comparer des Shorts de la meme periode.

### 2026-10-23 - pas assez de nouvelles donnees

- Gaming toujours a 66 mesures, IRL a 0 : 0 nouveau mesure depuis la derniere entree, rien a trancher.

### 2026-10-23 - baseline

- Gaming: 66 measured Shorts. Learned: <25 s +0.3, >40 s -0.3, chat moments +0.2,
  cold open -0.3 (early). PeakMoments: no measured Shorts yet.
- Competitors: 10 gaming channels (290 Shorts), 6 IRL channels (176 Shorts). Ideal length
  from the format guide: gaming 15-45 s, IRL 15-25 s.
- Open idea, waiting for the owner: word-by-word subtitles in the middle of the screen
  (seen on the IRL channels that do best); it changes how the Shorts look.
