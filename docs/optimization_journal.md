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
- Production (2026-10-29, Gemini bloque, donnees seules) : Shorts 25-40s quasi tout perdus (1
  publie / 69 produits, 9 en reserve, 59 abandonnes), meme sens que le test gaming_length_v1 en
  cours. GTA V toujours faible (3 publies / 34 rendus, coherent avec le -0.6 appris) - a surveiller
  encore, slots de test pleins.
- Their hits (top third, 10 channels, 96 Shorts) vs flops: titles ~40 chars, 25% with emoji;
  ours 45 chars, 76-88% with emoji. Lengths: theirs median ~74 s (long Shorts up to 3 min), ours 31 s.
  (2026-10-23)
- Weekly guide: start at the heart of the action, one strong event, cut right after the climax,
  understandable without the game's lore. (2026-10-23)
- Gemini watch (5 hits vs 5 flops, UChCE_tZPaGv80-dH4kMY_Qg/CaseOh/NoPixel channels): hits = banner
  hook top of screen, strong emotion in the first seconds (rage/laugh/punchline), one tight fast-cut
  moment; flops = slow scripted RP, passive gameplay, no real stake. Test started: shorter titles,
  less emoji (gaming_title_style_v1). (2026-10-23)
- Gemini watch (2026-10-24, our 3 latest Shorts + our 2 extremes vs 5 hits/5 flops): confirms
  immediate hook + fast-cut rhythm; no ending/start/framing defect found (the 2026-10-23 fix holds).
  Test started: longer Shorts (gaming_length_v1), per the length gap below.
- Gemini watch (2026-10-25, 5 hits/5 flops vs our best/worst + 3 quality-check Shorts): confirms
  immediate hook + fast context + dynamic cuts = hits, flat slow intros = flops. 2 of 3
  quality-check Shorts had a defect again (cut mid-sentence, no context at start). Bug found and
  fixed (trimming.py): the hard 58 s cap rejected Gemini's longer bounds for the gaming_length_v1
  test (ideal 45-90 s), falling back to un-recut heuristic bounds. Cap now follows the test's
  ideal_seconds.
- Production: World of Warcraft moments fully wasted this week (13 rendered, 0 kept in reserve,
  0 published) - one stream's worth so far, watching for a repeat before touching selection.
- Production: Dota 2 wasted two weeks running (2026-10-26: 14/17 dropped; 2026-10-27: 22/29
  dropped) but the 7-day windows overlap heavily - not independent proof yet, still watching.
  (2026-10-28)
- Gemini watch (2026-10-26, 5 hits/5 flops vs our best/worst + 3 quality-check Shorts): confirms
  immediate hook + fast cuts = hits. The 3 quality-check Shorts ALL had the same defect again
  (cut mid-word/mid-sentence) despite the 2026-10-25 fix. Real cause found (vod_pipeline.py,
  trimming.py): when Gemini's trim call fails outright (quota, network), the VOD's moments kept
  their raw, un-snapped heuristic end entirely - and separately, when Gemini only snapped a
  moment's end (no usable start), the next step crashed the whole VOD on a missing "start" key
  (log: "KeyError('start')", 3x on VOD 2907583164). Both fixed: a failed trim call now still
  snaps every end to a sentence boundary; the crash can no longer happen.

### PeakMoments (irl)
- Production (2026-10-29, Gemini bloque, donnees seules) : Just Chatting tire toujours l'essentiel
  des Shorts publies (9/30) ; les Shorts <25s n'ont aucun abandon (6 publies/6 reserve/0 abandonne,
  12 produits) - meilleur taux de reussite de toutes les longueurs, a surveiller face au test
  irl_length_v1 (qui pousse vers plus long).
- ohnepixel (owner's reference, Shorts at 2-14M views vs his weak ones at 60-80k, watched by
  Gemini 2026-10-27): webcam on top ~35-40%, screen under it (now the app's split layout), text
  at the seam, 1-3 big words per subtitle line, speech from the first frame, no pauses (jump
  cuts); hits = guest/voice-chat dialogue, lore stories, trolling with a payoff; weak = solo
  walkthroughs, silent moments, chaos without a story. Candidate tests: favor dialogue with
  guests; cut the silences. (2026-10-27)
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
- Gemini watch (2026-10-24, our 3 latest Shorts + our 2 extremes vs 5 hits/5 flops): confirms
  immediate hook + fast rhythm; no ending/start/framing defect found. No new test: no line strong
  enough yet beyond the running one.
- Gemini watch (2026-10-25, 5 hits/5 flops vs our best/worst + 3 quality-check Shorts): confirms
  short duration, hook + context in the first seconds, clean endings on hits; flops run long with
  a weak start. No defect on any of our 3 quality-check Shorts. No new test: title test still at
  0 measures, no new line strong enough.
- Production: Just Chatting drives almost all published IRL Shorts (14/34 rendered this week);
  Fortnite mostly discarded (1 published of 8) but sample too small to act on yet.
- Gemini watch (2026-10-26, 5 hits/5 flops vs our best/worst + 3 quality-check Shorts): confirms
  hook + context in the first seconds, clean endings on hits; one of our 3 quality-check Shorts
  had desynced subtitles (single occurrence, not a pattern yet). Competitors refreshed today: top
  third of 6 channels now 45 s vs bottom third 33 s vs ours 30.6 s - same direction as the
  2026-10-23 reading (28 s vs 23 s), on the 2nd free test slot. Test started: longer Shorts,
  30-50 s (irl_length_v1).

## Waiting for the owner

Risky or doubtful actions are never done directly: the loop writes them here (what, why with
numbers, risks, how to undo) and in its daily summary. The owner answers by writing OK or NON
at the start of the line (or tells Claude); the next run applies the OK ones, drops the NON
ones, and moves them to the entries.

- Passer l'API Gemini en tier payant (console Google AI) : 4e jour de suite ou les 6 modeles
  (120 requetes/jour au total) sont satures avant la fin de journee - 68 VOD renvoyees en attente
  de Gemini aujourd'hui, 7 VOD rendues/24h contre un objectif de 20+, 53 jobs abandonnes pour file
  pleine. Deja verifie que ce n'est pas le telechargement (DOWNLOAD_SHARE) ni une erreur de code
  (modeles pas sous leur limite, vraiment satures). Utilite : plus de VOD traitees = plus de
  candidats = top 30 plus fort, sur les deux chaines. Risque : cout selon l'usage (a verifier sur
  la console Google, pas consulte par la boucle). Annulation : repasser la cle API en tier gratuit
  a tout moment, aucun changement de code necessaire.

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
| 2026-10-24 | A/B gaming_length_v1: longer Shorts (45-90s vs guide's 15-45s) | retention/views closer to competitor hits (median 74s) | retention_pct, views_3d of B vs A | pending (0 measured) |
| 2026-10-26 | A/B irl_length_v1: longer Shorts (30-50s vs guide's 15-25s) | retention/views closer to competitor hits (top third 45s) | retention_pct, views_3d of B vs A | pending (0 measured) |
| 2026-10-26 | Fix: a failed Gemini trim call (quota/network) still snaps every moment's end to a sentence boundary, instead of keeping the raw un-snapped end | fewer mid-word/mid-sentence cuts | Gemini quality-check defects on our Shorts | pending |
| 2026-10-26 | Fix: a partial trim (end only, no start) no longer crashes the whole VOD (missing "start" key) | fewer VOD retries/losses | "erreur inattendue" / KeyError in the log | pending |

## Entries

### 2026-10-29 - quota Gemini sature un 4e jour, rien a trancher

- Gaming : analyse video impossible (6 modeles satures, verifie via les fichiers de quota avant
  tout appel). Tests sous le seuil (titres A n=15/B n=13, longueur A n=15/B n=10, vods=6-7) : rien
  a trancher, 2 slots pleins. Production (donnees seules) : Shorts 25-40s quasi tout perdus (1
  publie/69), GTA V toujours faible (3/34) - voir Knowledge.
- IRL : meme blocage Gemini. Tests sous le seuil (titres A n=21 vods=3/B n=8 vods=3, longueur A
  n=13 vods=4/B n=0) : rien a trancher, 2 slots pleins. Production : Just Chatting toujours
  dominant (9/30 publies), Shorts <25s sans aucun abandon - voir Knowledge.
- Debit : 7 VOD/24h (objectif 20+), 40 en file, 68 renvoyees en attente de Gemini aujourd'hui - pas
  un bug (modeles vraiment satures, pas sous leur limite). Proposition ajoutee : passer Gemini en
  tier payant (voir "Waiting for the owner").

### 2026-10-28 - changes made in the owner's conversation (not by the loop)

- Accepted by the owner and done on 10-27: word-by-word subtitles (Bangers, a little below the
  middle), two VODs processed at a time, prefetch of the next VOD, download cap from the measured
  bandwidth. Also: split layout (webcam on top, screen below) when a webcam sits over a shared
  screen; a framing per shot; frozen pictures never rendered; subtitles only of the streamer and
  the people with them; a moment about a video game goes to LiveActions!; every Short declared in
  English; PeakMoments Shorts also sent to TikTok as drafts.
- Waste fixed on 10-28: the prefetch kept downloading while VODs waited for Gemini (9.7 GB of
  audio, some expired unprocessed); renders limited to moments entering the top 15 (82 gaming
  renders a day for 10 uploads); speakers request only when a watched video is heard; reserve
  comparison every 12 h. Gemini refusals are logged with their quota id and retry delay
  (data/output/gemini_refusals.log): check it before concluding the quota is the bottleneck.

### 2026-10-28 - quota Gemini de nouveau sature, rien a trancher

- Gaming : quota Gemini a zero sur les 5 modeles principaux, gemini-flash-lite-latest aussi a sa
  limite (20/20) - verifie via les fichiers de quota, pas de nouvel appel tente. Aucun test au
  seuil (titres A n=13/B n=6, longueur A n=13/B n=3, vods<6 partout) : rien a trancher, aucun
  emplacement libre.
- IRL : meme quota a zero. Tests sous le seuil (titres A n=19/B n=1, longueur A n=4/B n=0) : rien
  a trancher, aucun emplacement libre.
- Production (donnees seules) : Dota 2 toujours tres gaspille sur gaming (22/29 abandonnes cette
  semaine, apres 14/17 la semaine passee) mais fenetres de 7 jours qui se chevauchent - pas une 2e
  preuve independante, a surveiller encore. IRL : Just Chatting et Fortnite dans la norme cette
  fois. Debit : 5 VOD/24h (objectif 20+), 40 en file, 75 abandonnees pour file pleine - meme
  goulot (selection Gemini) deja remonte au proprietaire, toujours sans reponse.

### 2026-10-27 - quota Gemini a sec, pas d'analyse video possible

- Gaming : analyse Gemini impossible (quota du jour atteint sur les 5 modeles, y compris
  gemini-flash-lite-latest). Tests toujours sous le seuil (titres A n=7/B n=5, longueur A n=6/B n=3,
  vods<6) : rien a trancher. 2 tests deja en cours, aucun emplacement libre.
- IRL : meme blocage Gemini (verifie une fois, quota deja a zero pour tous les modeles, pas
  reessaye sur IRL). Tests sous le seuil (titres A n=11/B n=0, longueur 0 mesure des deux cotes).
  2 tests deja en cours, aucun emplacement libre.
- Production (donnees seules, pas de confirmation Gemini) : gaming, les Shorts >40s publient mieux
  (12/55=22%) que 25-40s (8/63=13%) et <25s (8/45=18%) - va dans le sens du test longueur en cours,
  rien a changer. Dota 2 tres gaspille (14/17 abandonnes) - a surveiller. IRL : NMS Boxing quasi
  tout abandonne (16/18) et Fortnite toujours tres abandonne (7/8, comme le 25/10) - fenetres de 7
  jours qui se chevauchent, pas encore une 2e preuve independante ; a surveiller. Debit : 11 VOD/24h
  (objectif 20+), 39 en file, 44 abandonnees pour file pleine - meme goulot deja remonte au
  proprietaire (quota Gemini quotidien plein aujourd'hui confirme que l'etape de selection est bien
  le frein, pas le telechargement). Rien a coder.

### 2026-10-26 - vraie cause de la coupe en plein mot + VOD qui plantaient

- Gaming : Gemini a revu 5 hits/5 flops concurrents + nos extremes + 3 Shorts recents : les 3
  recents avaient encore une fin coupee en plein mot malgre le correctif d'hier. Vraie cause
  trouvee : quand l'appel Gemini de recadrage echoue completement (quota, reseau), les moments
  gardaient leur fin brute non recalee ; et quand Gemini ne renvoyait qu'une fin recalee (pas de
  debut utilisable), l'etape suivante plantait toute la VOD (KeyError 'start', vu 3 fois dans le
  log sur une meme VOD). Les deux corriges + testes (pytest ok). World of Warcraft : toujours les
  memes 13 moments perdus de la semaine, pas un nouvel episode, rien a changer encore.
- IRL : memes verifications, aucun defaut sur 2 Shorts sur 3 (1 sous-titres desynchronises,
  episode isole). Concurrents : tiers du haut desormais 45s vs tiers du bas 33s vs nos 31s, meme
  sens que le 23/10 (28s vs 23s). Test lance sur le 2e emplacement libre : Shorts plus longs
  30-50s (irl_length_v1).
- Debit : seulement 2 VOD rendues en 24h (objectif 20+, hier 6), 40 en file, 63 abandonnees pour
  file pleine, 14 pour trop ancien. Meme goulot deja remonte au proprietaire (etape chat ->
  selection Gemini) ; proposition de paralleliser toujours en attente.

### 2026-10-25 - bug de coupe recidive sur gaming_length_v1

- Gaming : Gemini a revu 5 hits/5 flops concurrents + nos 2 extremes + 3 Shorts recents : confirme
  accroche immediate + contexte rapide + montage nerveux. 2 Shorts sur 3 recents avaient un defaut
  (fin coupee en plein mot, debut sans contexte). Cause trouvee : le plafond fixe de 58s dans
  trimming.py rejetait les bornes plus longues de Gemini pour le test gaming_length_v1 (ideal
  45-90s), et retombait sur l'ancienne fin non recalee. Corrige (le plafond suit maintenant
  ideal_seconds du test) + teste. Tests titres et longueur toujours a 0 mesure.
- IRL : memes verifications, aucun defaut sur les 3 Shorts recents. Production : Just Chatting
  tire l'essentiel des Shorts publies (14/34), Fortnite surtout abandonne (1/8) mais echantillon
  trop petit. Pas de nouveau test.
- Debit : toujours 6 VOD rendues en 24h (objectif 20+), 40 en file, 61 abandonnees pour file
  pleine, 18 pour trop ancien. Meme goulot qu'avant (etape chat -> selection Gemini, pas le
  telechargement) ; proposition de paralleliser toujours en attente du proprietaire.

### 2026-10-24 - modele Gemini mort + debit en panne

- Gaming : Gemini a revu nos 3 Shorts recents (aucun defaut, la correction d'hier tient) et nos 2
  extremes vs 5 hits/5 flops concurrents (confirme accroche immediate + montage nerveux). Test
  lance : Shorts plus longs 45-90s (gaming_length_v1), vu l'ecart avec les chaines de clips
  (mediane 74s, jusqu'a 3 min). Tests titres toujours a 0 mesure, prochain point apres mesures.
- IRL : memes verifications (3 Shorts recents sans defaut, confirmations accroche/rythme) ; pas de
  nouveau test, aucune ligne assez forte. Test titres toujours a 0 mesure.
- Bug corrige (gemini_evaluation.py) : gemini-2.5-flash renvoie 404 pour tout le monde depuis peu
  et cette erreur n'etait pas traitee comme transitoire -> l'appel Gemini s'arretait net au lieu
  d'essayer le modele suivant (erreurs NOT_FOUND/UNAVAILABLE du log). Modele retire de la liste de
  secours. Aussi corrige : scripts/optimization_report.py plantait sur les titres avec emoji.
  Commit + redemarrage app.
- Debit : seulement 5 VOD rendues en 24h (objectif ~20+), 53 jobs en file, 69 abandonnees pour
  file pleine. Pas un probleme de telechargement (audio+transcript prets en ~5 min) : ~3h25
  d'ecart observe entre le chat et la selection Gemini sur une VOD. Proposition envoyee au
  proprietaire (paralleliser le traitement des VOD) : voir "Waiting for the owner".

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

### earlier (2026-10-23)

- Baseline : gaming 66 Shorts mesures (learned <25s +0.3, >40s -0.3, chat +0.2, cold open -0.3
  tot), IRL 0 mesure. Concurrents : 10 chaines gaming (290 Shorts), 6 chaines IRL (176 Shorts),
  longueur ideale du guide : gaming 15-45s, IRL 15-25s. Idee ouverte envoyee au proprietaire :
  sous-titres mot-par-mot au milieu de l'ecran (vu sur les meilleures chaines IRL).
- Puis : 0 nouvelle mesure, rien a trancher.
