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
- Coherence (2026-11-11) : 3 des 4 derniers Shorts (VOD WoW 2924025635) finissent sur une question
  sans reponse ("What is that?", "what are you putting this on?", "Dude?"). Regle ajoutee au
  prompt de trim. Gemini : Google refuse 'PerDay 20' alors que nos compteurs sont a 0-4 ;
  hypothese : les essais 503/504 (non comptes chez nous) le sont chez Google. A verifier.
- Concurrents (2026-11-09, titres 5 hauts/5 bas non vus, 3 chaines) : hauts = le streamer reagit a un
  contenu sur lui-meme (CaseOh x3 sur son animation, ~0.75-1.2M) ou clash avec une figure connue
  ("Blizzard Roasts PirateSoftware", 950k) ; bas = discussion de mecanique de niche ("Are Racials
  Homogenized"), scene RP longue (101 s), jeu solo rate. Faible (2 chaines), va avec la ligne
  interactions du 11-06.
- Coherence (2026-11-08) : les Shorts rendus le 11-06 13:34 (apres le fix split_sentences) finissent
  encore sur 1-3 mots de la phrase suivante ("And by the way, you", "Okay. Tell", "No,") - 6 des 14
  derniers, 2 chaines. Cause : la marge de rendu apres la fin (after) attrapait le debut de la phrase
  suivante. Corrige le 11-07 (vod_shorts._clip_bounds : marges limitees au silence), commite le 11-08.
- Coherence (2026-11-06) : CORRECTION des 11-04/11-05 - l'hypothese "chemin de secours sans
  Gemini" etait fausse (trim_reason n'est jamais sauve dans le manifeste, son absence ne prouve
  rien). Vraie cause commune : split_sentences laissait des bouts de phrase en minuscule ("worry.",
  "fuck?") comme phrases a part apres une pause de 1.5-6 s ; le trim (Gemini ou secours) pouvait
  y commencer/finir. Corrige (LOWERCASE_JOIN_GAP 6 s, highlights.py). Sur 3 transcripts : 26+11
  phrases en minuscule, ~75% avec pause < 6 s.
- Concurrents (2026-11-06, 296 Shorts, 9 chaines) : tiers haut 81 s median vs bas 72 s ; ~8 des
  14 meilleurs relatifs sont des interactions (NoPixel RP, invite) ; tiers bas = tops/compilations,
  lore. Miniatures hits : visage proche + 1-2 mots en gros ("LET ME COOK", "YO!"). Test
  gaming_interaction_v1 lance.
- Coherence (2026-11-05) : 1 des 4 derniers Shorts defaillant (finit sur une anticipation non
  resolue "Here we go. Here we go. Here we go", pas de chute) ; les 3 autres se terminent sur une
  reaction/chute nette. Saturation Gemini toujours tres forte aujourd'hui (7e jour de suite,
  UNAVAILABLE/RESOURCE/quota atteint dans les logs) - meme hypothese que le 11-04 (chemin de
  secours sans Gemini qui cale sur une frontiere de phrase, pas sur une conclusion de sujet), pas
  un nouveau bug de code. Toujours pas de jour calme pour trancher. 2 emplacements de test libres,
  aucune ligne de Knowledge assez forte aujourd'hui (pas d'etude concurrents, guide vieux de 6
  jours, pas encore du).
- Coherence (2026-11-04) : 2 des 4 derniers Shorts defaillants (un termine en pleine question "I
  wouldn't be able to jump boost", un autre commence en plein mot "worry." et finit en pleine liste
  de remerciements donateurs "St. Dom,") - trim_reason absent sur les deux (chemin de secours sans
  Gemini, pas le prompt "sujet complet"). Coincide avec une saturation Gemini extreme aujourd'hui
  (presque tous les modeles CLOSED, 1 seul VOD rendu/24h contre 5 hier) - probablement la cause
  (le chemin de secours ne fait que caler sur une frontiere de phrase, jamais sur une conclusion de
  sujet), pas un nouveau bug de code distinct. A reverifier un jour sans saturation avant de
  retoucher trimming.py. Dota 2 toujours tres gaspille (2 publie/3 reserve/27 abandonnes) - memes
  causes que precedemment, aucune piste neuve.
- Fix (2026-11-02, hors boucle, commit dfdf63e) : trimming reecrit pour demarrer et finir sur un
  sujet complet (debut du declencheur, fin apres reponse/chute/reaction), avec 45s de phrases
  visibles apres le moment - repond directement a la suspicion de segmentation du 11-01. Chaque
  Short garde desormais ses mots parles (spoken) ; le rapport affiche debut/fin (section
  coherence) pour verification automatique. Aucune donnee encore (aucun Short rendu avec ce champ
  depuis le commit) - a verifier au prochain run.
- Production (2026-11-02) : Grand Theft Auto V se redresse nettement (7 publies/4 reserve/15
  abandonnes) apres plusieurs semaines faibles (poids appris -0.5) - un seul jour, a confirmer
  avant de toucher le poids. Dota 2 toujours tres gaspille (3 publies/15 reserve/34 abandonnes),
  meme surveillance.
- Gemini watch (2026-10-30, 5 hits/5 flops concurrents + notre meilleur/pire + 3 controle qualite) :
  hits = accroche forte (texte+visuel) des 3 premieres secondes, 15-45s, cadrage serre
  visage+reaction avec gros sous-titres synchro, chute nette et explicite ; notre meilleur suit
  deja la formule, notre pire manque de punch (gameplay passif, texte generique). LES 3 Shorts de
  controle qualite avaient un defaut (2x fin coupee trop tot/en plein mot, 1x debut sans contexte) -
  cause reelle trouvee (trimming.py) : quand la reponse de Gemini pour un moment est rejetee ou
  absente, seule la fin etait recalee sur une phrase, jamais le debut (qui restait sur son bord
  heuristique brut, parfois en plein milieu d'une phrase). Corrige + teste (les deux chemins de
  secours recalent maintenant debut ET fin).
- Production (2026-10-29, Gemini bloque, donnees seules) : Shorts 25-40s quasi tout perdus (1
  publie / 69 produits, 9 en reserve, 59 abandonnes), meme sens que le test gaming_length_v1 en
  cours. GTA V toujours faible (3 publies / 34 rendus, coherent avec le -0.6 appris) - a surveiller
  encore, slots de test pleins.
- Production (2026-10-30) : memes signes, 25-40s toujours tres perdant (4 publies/8 reserve/60
  abandonnes), va dans le sens du test gaming_length_v1 en cours (fenetres qui se chevauchent,
  pas une preuve independante de plus). World of Warcraft repris : 5 publies/6 reserve/9 abandonnes
  (etait 13 rendus/0 garde la semaine du 26/10) - ligne "fully wasted" retiree, plus un probleme.
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
- Production: Dota 2 wasted two weeks running (2026-10-26: 14/17 dropped; 2026-10-27: 22/29
  dropped) but the 7-day windows overlap heavily - not independent proof yet, still watching.
  (2026-10-28; absent from the 2026-10-30 top groups, sample too thin to update) Reversed on
  2026-10-31 (2 publies/12 reserve/6 abandonnes sur 20) - ligne cloturee, plus un probleme.
- Gemini watch (2026-10-26, 5 hits/5 flops vs our best/worst + 3 quality-check Shorts): confirms
  immediate hook + fast cuts = hits. The 3 quality-check Shorts ALL had the same defect again
  (cut mid-word/mid-sentence) despite the 2026-10-25 fix. Real cause found (vod_pipeline.py,
  trimming.py): when Gemini's trim call fails outright (quota, network), the VOD's moments kept
  their raw, un-snapped heuristic end entirely - and separately, when Gemini only snapped a
  moment's end (no usable start), the next step crashed the whole VOD on a missing "start" key
  (log: "KeyError('start')", 3x on VOD 2907583164). Both fixed: a failed trim call now still
  snaps every end to a sentence boundary; the crash can no longer happen.
- Production (2026-10-31, quota Gemini epuise, donnees seules) : Fortnite tres gaspille (3
  publies/1 reserve/18 abandonnes sur 22) - un seul jour, fenetre a confirmer avant d'agir.
- Gemini watch (2026-11-01, 5 hits/5 flops concurrents + notre meilleur/pire + 3 controle
  qualite) : hits = accroche visuelle/reaction forte <3s, rythme dynamique 30-60s, chute nette ;
  flops = pas d'accroche, contexte long/confus, duree etiree, fin plate. Notre meilleur proche
  des hits, notre pire rejoint les flops (accroche confuse, manque de contexte). 2 des 3 Shorts
  de controle qualite avaient un defaut (fin coupee en plein mot/son coupe net ; fin au mauvais
  moment) - meme classe de bug que les 3 correctifs precedents (10-25/26/30) ; code revu
  (trimming.py) sans trouver de nouvelle faille dans les chemins de secours - suspicion
  maintenant sur la segmentation en phrases de la transcription elle-meme (hors de portee d'un
  correctif de trim), a confirmer.
- Verdict A/B gaming_title_style_v1 (2026-11-01, seuil atteint : A n=31/vods=13, B n=21/vods=9) :
  retention B 66.5 vs A 64.4 (ecart trop faible), perf egal - pas clairement meilleur, test
  retire, titres inchanges. Nuance la ligne "concurrents titres courts/peu d'emoji" ci-dessus :
  la correlation ne se confirme pas chez nous en A/B.
- Verdict A/B gaming_length_v1 (2026-11-01, seuil atteint : A n=26/vods=9, B n=22/vods=11) :
  retention B 69.3 vs A 61.7 (+7.6 pts), perf egal - B (45-90s) devient le defaut du code pour
  gaming (experiments.py DEFAULTS), test retire. Coexiste avec le poids appris negatif pour
  length=>40s (signal different : classement predictif vs retention mesuree) - a surveiller.
- Gemini watch (2026-11-01 soir, quota quasi epuise - seul flash-lite-latest disponible) : 5
  flops concurrents (aucun hit non-vu disponible) + notre meilleur/pire + 3 controle qualite :
  flops = debut calme, plan fixe long, sujet sans impact visuel immediat ; notre meilleur
  (d_epm9yXRAE) colle au patron des hits deja connus (suspense immediat, chute nette), notre pire
  (gXkhw-Aatls) demarre lentement comme les flops. AUCUN defaut sur les 3 Shorts de controle
  qualite - 1ere fois depuis le 25/10 (4 runs avec defaut avant) ; a confirmer un 2e jour avant de
  clore la piste "segmentation de la transcription" suspectee le 11-01.
- Production (2026-11-01 soir, meme jour que l'adoption du defaut 45-90s) : len=<25s publie bien
  (6pub/3res/15drop) et Grand Theft Auto V aussi (7pub/4res/15drop), ce qui va a l'encontre du
  defaut tout juste adopte - un seul jour juste apres le changement (les Shorts en cours de
  pipeline suivent encore l'ancien reglage), pas une preuve independante, a resurveiller demain.

### PeakMoments (irl)
- Coherence (2026-11-11) : 2 des 4 derniers (VOD 2924221579) coupent en pleine scene ("You live
  here? Yeah.", "Uh-oh! No!") ou commencent en plein echange. Meme regle de trim ajoutee.
  Production : 0 Short irl jete en 7 j (tout entre en reserve), Just Chatting 11 publies.
- Concurrents (2026-11-08, miniatures 5 hauts/5 bas non vus) : hauts = Speed, histoire emotionnelle
  (pere mort, vengeance, "caught in 4K"), miniature = image du pic + 1 mot "*REVENGE*" ; bas =
  commentaire assis (Asmongold Reddit/societe). Confirme la ligne du 11-06. Test irl_cold_open_v1 lance.
- Production (2026-11-08) : 8 des 10 publies en 24 h viennent d'une seule VOD politique de HasanAbi
  (poids appris -0.5, politique = tiers bas chez les concurrents) faute d'autres VOD rendues (0/24 h).
- Cold open on PeakMoments: the learned points say -0.4 with it, +0.3 without (2026-11-06), while it
  works on LiveActions!. The owner wants MORE evidence before removing it on PeakMoments: run it
  as an A/B test (cold_open: false on half the VODs) when an irl slot frees up, decide with the
  usual bar (20+ measured per variant, 6+ VODs), and look at whether the big IRL clip channels
  open on the climax (thumbnails/titles of their top Shorts): do as they do. (2026-11-06)
- Coherence (2026-11-06) : 3 des 4 derniers Shorts defaillants, dont 2 qui commencent sur un bout
  de phrase en minuscule ("not.", "a new one?") et finissent en pleine phrase ("I walked in and",
  "I mean, look"). Meme cause que gaming (split_sentences, pas la saturation) - corrige 11-06.
- Concurrents (2026-11-06, 214 Shorts, 7 chaines) : tiers haut 41 s median vs bas 31 s, mais nos
  propres chiffres disent l'inverse (<25s +0.7, >40s -0.8, A/B longueur perdu) : on garde 15-30 s.
  Tiers bas = politique/actualite/talking heads (Hasan, Trump ; reconfirme 11-12, midterms 0.19-0.26x) ; hits = Speed/Kai, action
  physique, dialogue. Miniatures hits : visage + 1 mot ("REVENGE", "CRASHEDOUT").
- Coherence (2026-11-05) : 2 des 4 derniers Shorts defaillants (un coupe en plein mot "Hold on,
  my iMessages off... Hold on. All", un autre finit sur une question posee aux viewers sans
  reponse "What is your wing stop order? Tell the viewers") ; les 2 autres concluent proprement.
  Meme hypothese que gaming aujourd'hui : saturation Gemini (7e jour de suite), pas une rechute du
  fix split_sentences du 11-03. irl_dialogue_v1 toujours a 0 mesure. 1 emplacement de test libre,
  rien d'assez fort (pas d'etude concurrents ce run).
- Coherence (2026-11-04) : 1 des 2 derniers Shorts coupe en pleine phrase ("...to fucking
  November", trim_reason absent, chemin de secours). L'autre conclut proprement (chute "go get a
  forklift"). Meme hypothese que gaming aujourd'hui : saturation Gemini extreme (1 VOD rendu/24h),
  pas une rechute du fix split_sentences du 11-03 - a confirmer un jour sans saturation.
- Bug trouve et corrige (2026-11-03) : 2 des 3 derniers Shorts (coherence du rapport) se coupent
  en plein mot/pensee ("...I was becoming like", "...Some") malgre le trimming "sujet complet" du
  11-02 - 6e occurrence de ce defaut depuis le 10-25 malgre 3 correctifs trim deja faits. Cause
  reelle trouvee dans split_sentences (highlights.py) : une phrase sans ponctuation finale
  (hesitation, silence qui traine en plein milieu d'une idee) coupait une nouvelle "phrase" des
  qu'une pause depassait 1.5s, meme si le locuteur n'avait pas fini sa pensee - le trim/Gemini
  s'arrete alors sur cette fausse frontiere. Corrige (SENTENCE_JOIN_GAP reste 1.5s pour une phrase
  deja ponctuee, mais une phrase inachevee tolere une pause jusqu'a 4s) + teste. A confirmer sur le
  controle qualite de demain.
- Verdicts A/B (2026-11-03, seuil atteint pour les deux) : irl_title_style_v1 (A n=42/vods=7,
  retention 64.2 ; B n=24/vods=8, retention 43.9) et irl_length_v1 (A n=27/vods=7, retention 53.0,
  perf 0.3 ; B n=23/vods=6, retention 53.7, perf 0.0) - aucun des deux B pas clairement meilleur,
  tests retires, reglages A inchanges. 2 emplacements de test liberes.
- Nouveau test (2026-11-03) : irl_dialogue_v1 - favorise un moment avec dialogue/invite et chute
  claire, evite le solo silencieux, d'apres la ligne ohnepixel du 2026-10-27 (ses Shorts a 2-14M
  vues vs 60-80k pour les faibles) jamais testee jusqu'ici, slot desormais libre.
- Fix (2026-11-02, hors boucle, commit dfdf63e) : meme reecriture du trimming que gaming
  (debut/fin sur sujet complet) ; a verifier au prochain run des que des Shorts avec le champ
  "spoken" seront rendus.
- Gemini watch (2026-10-30, 5 hits/5 flops concurrents + notre meilleur/pire + 2 controle qualite) :
  hits = accroche immediate (<2s) pile sur l'element declencheur, 15-30s, montage dynamique
  (effets/zooms), chute nette juste apres la resolution, titres emotionnels/intrigants ; notre
  meilleur colle a la formule (Kai Cenat), notre pire fait pire que les flops concurrents (efface le
  streamer derriere un extrait d'anime brut). 1 des 2 Shorts de controle qualite avait le meme
  defaut qu'en gaming (fin coupee trop tot) - meme cause, meme correctif (trimming.py).
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
- Production (2026-10-31, quota Gemini epuise, donnees seules) : Just Chatting toujours
  dominant (21 publies/17 reserve/14 abandonnes), longueur >40s se tient bien (7 publies/10
  reserve/8 abandonnes) - va dans le sens du test irl_length_v1 en cours.
- Gemini watch (2026-11-01, 5 hits/5 flops concurrents + notre meilleur/pire + 3 controle
  qualite) : hits = accroche choc/son fort <2s, contexte instantane (texte/visuel), 15-30s,
  forte intensite emotionnelle, chute nette ; flops = monologues lents, pas de punchline, fin
  monotone. Notre meilleur colle aux hits (P7Jp8979Qjo), notre pire rejoint les flops (moment
  long et monotone). LES 3 Shorts de controle qualite avaient le meme defaut (fin coupee trop
  tot/en plein mot) - 4e+ occurrence malgre 3 correctifs (10-25/26/30), meme constat qu'en
  gaming aujourd'hui (voir Knowledge gaming) : suspicion sur la segmentation en phrases de la
  transcription plutot qu'un chemin de code non corrige.
- Gemini watch (2026-11-01 soir) : impossible, le quota du jour s'est epuise pendant l'appel
  gaming (seul flash-lite-latest restait, un seul appel) - aucune analyse video IRL ce run.
  Verdicts A/B : irl_title_style_v1 toujours sous le seuil (B n=17/vods=6, <20 mesures) ;
  irl_length_v1 toujours sous le seuil (A vods=5, <6 VOD) - rien a trancher, 2 slots pleins.

## Waiting for the owner

Risky or doubtful actions are never done directly: the loop writes them here (what, why with
numbers, risks, how to undo) and in its daily summary. The owner answers by writing OK or NON
at the start of the line (or tells Claude); the next run applies the OK ones, drops the NON
ones, and moves them to the entries.

- Supprimer 3 doublons deja publies sur YouTube (meme moment publie deux fois, bornes differentes,
  meme titre) : LiveActions! FbJo6C4DvNE / s_ycihm5nfw (Xaryu/Pikaboo), 8J-gHFmAjJY / EExLLXdkgqA,
  ZiYPcRgef14 / Ea7SuszotV8 (VOD 2922381949). Utilite : YouTube penalise le contenu repete, et
  chaque doublon prend une des 10 places du jour. Proposition : garder celui qui a le plus de vues,
  supprimer l'autre (a faire dans YouTube Studio). Risque : irreversible, perte de ses vues.
  Annulation : aucune (ne rien faire suffit si NON). Corrige pour l'avenir le 11-11.

## Changes under evaluation

| Since | Change | Expected effect | Metric to watch | Verdict |
|---|---|---|---|---|
| 2026-10-23 | Gemini picks each Short's start and end (trimming.py); 30 s length test dropped | Shorts understandable alone, complete endings | share watched (retention_pct), views_3d | pending |
| 2026-10-23 | Cold open 3 s, starting 1 s before the reaction | fewer swipe-aways in the first seconds | retention_pct of cold_open=yes vs no | pending (early data: -0.3 pts for cold_open=yes) |
| 2026-10-23 | Ranking learned from real results (performance.py) | better Shorts published first | correlation of predicted_points with results (reliability) | pending (needs 30 measured Shorts) |
| 2026-10-23 | Gemini score reweighted by how well it predicts results | | gemini_weight | 0.89 on gaming (2026-10-23) |
| 2026-10-23 | Competitor format guide (competitors.py, weekly) used in selection, bounds, hooks, titles | Shorts made like the ones that work elsewhere | retention_pct and views of Shorts made after it vs before | pending |
| 2026-10-22 | Sharper encoding (CRF 18, Lanczos, sharpening), Twitch source quality | better-looking Shorts | retention_pct | pending |
| 2026-10-23 | A/B gaming_title_style_v1: shorter, less emoji titles | retention/views closer to competitor hits | retention_pct, views_3d of B vs A | **not better** (2026-11-01, B retention 66.5 vs A 64.4), removed |
| 2026-10-23 | A/B irl_title_style_v1: shorter, less emoji titles | retention/views closer to competitor hits | retention_pct, views_3d of B vs A | **not better** (2026-11-03, A retention 64.2 vs B 43.9), removed |
| 2026-10-24 | A/B gaming_length_v1: longer Shorts (45-90s vs guide's 15-45s) | retention/views closer to competitor hits (median 74s) | retention_pct, views_3d of B vs A | **B wins** (2026-11-01, retention 69.3 vs 61.7) - now default (experiments.py DEFAULTS), removed |
| 2026-10-26 | A/B irl_length_v1: longer Shorts (30-50s vs guide's 15-25s) | retention/views closer to competitor hits (top third 45s) | retention_pct, views_3d of B vs A | **not better** (2026-11-03, A retention 53.0 vs B 53.7, perf A 0.3 vs B 0.0), removed |
| 2026-11-03 | A/B irl_dialogue_v1: favorise dialogue/invite avec chute claire, evite le solo silencieux (ohnepixel) | retention/views plus proches des hits | retention_pct, views_3d of B vs A | pending (0 measured) |
| 2026-11-03 | Fix (highlights.py): une phrase sans ponctuation finale (hesitation, silence qui traine) peut maintenant se continuer au-dela d'une pause de 1.5s (jusqu'a 4s) au lieu de se couper en phrase separee | moins de Shorts coupes en plein mot/pensee (irl, 2 des 3 derniers controle qualite) | coherence du rapport (debut/fin), controle qualite | pending |
| 2026-10-26 | Fix: a failed Gemini trim call (quota/network) still snaps every moment's end to a sentence boundary, instead of keeping the raw un-snapped end | fewer mid-word/mid-sentence cuts | Gemini quality-check defects on our Shorts | pending |
| 2026-10-26 | Fix: a partial trim (end only, no start) no longer crashes the whole VOD (missing "start" key) | fewer VOD retries/losses | "erreur inattendue" / KeyError in the log | pending |
| 2026-10-30 | Fix: when Gemini's trim answer for a moment is rejected or missing, its start is now also recalee on a sentence boundary (only the end was before) | fewer "no context at start" / early cuts | Gemini quality-check defects on our Shorts | pending |
| 2026-11-06 | A/B gaming_interaction_v1: favorise interactions entre personnes avec chute, evite action seule/compilations | retention/views plus proches des hits | retention_pct, views_3d of B vs A | pending (0 measured) |
| 2026-11-06 | Fix (highlights.py): un segment en minuscule rejoint la phrase precedente jusqu'a 6 s de pause | plus de Shorts qui commencent/finissent sur un bout de phrase ("not.", "I walked in and") | coherence du rapport | pending |
| 2026-11-08 | A/B irl_cold_open_v1: pas de cold open sur PeakMoments (b: cold_open false) | retention meilleure si le cold open nuit en IRL (points appris -0.4) | retention_pct, perf of B vs A | pending (0 measured) |
| 2026-11-07 | Fix (vod_shorts._clip_bounds): les marges avant/apres restent dans le silence, plus de mots de la phrase suivante/precedente | fin propre au lieu de "... Okay. Tell" | coherence du rapport | pending |
| 2026-11-12 | Fix (vod_pipeline._trimmed) : un moment encore plus long que la limite apres le trim (trim Gemini refuse/injoignable) n'est plus rendu | plus de Shorts de 126-180 s (2 publies/rendus irl le 11-11, VOD 2925140576) | duree des Shorts dans la coherence du rapport | pending |
| 2026-11-11 | Fix (shorts_upload._ready_shorts) : un moment rendu deux fois (VOD reprise apres Gemini indisponible) n'est publie qu'une fois, seul son rendu le plus recent est garde | plus de doublons publies (3 depuis le 11-09) | doublons par (candidate_id, candidate_start) dans les manifestes | pending |
| 2026-11-11 | Fix (trimming.py) : le prompt interdit de finir sur une question sans reponse ou le debut d'une nouvelle scene | moins de fins "What is that?" (3/4 gaming, 2/4 irl le 11-11) | coherence du rapport | pending |
| 2026-11-10 | Fix (transcription.py): Whisper GPU dans un sous-processus, repli CPU si crash cuDNN | l'app ne s'arrete plus en silence (3 crashs 11-07/11-09) | throughput, "Application Error" python.exe dans le journal Windows | pending |
| 2026-11-08 | DOWNLOAD_SHARE 0.10 -> 0.25 (cli.py) | telechargements plus rapides (VOD de 48 h bloquant la file) | throughput du rapport | pending |
| 2026-11-02 | Trimming reecrit (hors boucle): debut/fin cales sur un sujet complet, Shorts gardent leurs mots parles | moins de debuts/fins incomplets | coherence du rapport (debut/fin), controle qualite Gemini | pending (aucune donnee encore) |

## Entries

### 2026-11-12 - Shorts IRL de 126 s et 180 s

- Bug : quand Gemini refuse ou ne repond pas au trim, le moment gardait ses bornes brutes, sans plafond
  (VOD 2925140576 : 126 s publie eaGL6XmwnF0, 180 s rendu, fin "I would completely disagree with").
  Corrige : un moment encore trop long apres le trim n'est plus rendu (vod_pipeline, test). App relancee.
- Gaming : coherence 4/4 correctes (situation -> resultat). Aucun verdict (gaming_interaction_v1 B n=0).
  Debit 8 VOD/24h, 61 jobs jetes (file pleine), modeles Gemini au quota (RESOURCE_EXHAUSTED).
- IRL : 3/4 sont des tirades politiques de Hasan (finissent en pleine phrase) ; chez les concurrents le
  commentaire politique est dans le tiers bas (midterms, Hasan 0.19-0.26x), l'evenement IRL en haut.
  irl_dialogue_v1 A 24/4 VOD, B 15/2 ; irl_cold_open_v1 A 4 / B 5. Guide hebdo a refaire le 11-13.

### 2026-11-11 - doublons publies sur YouTube, fins sur une question sans reponse

- Bug : un moment rendu une 1re fois avec bornes de secours (Gemini 503) puis re-rendu au passage
  suivant avec d'autres bornes donnait 2 Shorts publies (3 cas depuis le 11-09). Corrige
  (shorts_upload, test) ; suppression des 3 doublons proposee au proprietaire.
- Gaming : coherence 3/4 finit sur une question sans reponse -> regle ajoutee au trim. Pas de nouveau
  test (gaming_interaction_v1 B n=0). Debit 4 VOD/24h, quota Gemini vraiment epuise selon Google.
- IRL : coherence 2/4 coupe en pleine scene (meme regle). irl_dialogue_v1 A 19/3 VOD, B 15/2 VOD ;
  irl_cold_open_v1 A 4 / B 0. Guide concurrents a refaire le 11-13.

### 2026-11-10 - l'app plantait en silence (crash cuDNN de la transcription GPU)

- Debit : 2 VOD/24h. Cause trouvee dans le journal Windows : python.exe tue par cudnn64_9.dll
  (0xc0000409) le 11-07 21:59, le 11-09 13:05 et 23:36 - l'app s'arretait sans ligne de log et ne
  repartait qu'au reveil/logon. Corrige : la transcription GPU tourne dans un sous-processus, un
  crash ne tue que lui et on repasse sur le CPU (transcription.py, test). App relancee 11-10 00:17.
- Gaming : coherence 1/4 defaillante (finit "Wait, um, bro. On bro"), pas un motif. Pas de nouveau
  test : debit trop bas, gaming_interaction_v1 encore a A n=3 / B n=0. Prochain : verdicts impossibles avant ~1 semaine de debit normal.
- IRL : coherence 4/4 correctes (question -> reponse, scene police complete). irl_dialogue_v1 A n=12
  (2 VOD) / B n=5, irl_cold_open_v1 a 0. Guide concurrents refait le 11-13 (hebdo).

### 2026-11-09 - owner's answers (main conversation)

- Gemini paid tier: NON. The owner keeps the free tier: make the most of it (selection and trimming
  first; VODs that could not enter the reserve are skipped; long VODs cut to their last 8 hours).
  Do not propose it again unless the free quota still blocks after these savings, with numbers.
- Many Shorts from one VOD: fine. If a VOD is really excellent, all of the day's Shorts may come
  from it; no cap per VOD or per streamer (owner, 2026-11-09).
- Keep-awake: OK and done - on mains power the computer no longer falls asleep on its own while
  the app works (power.py); the owner can still sleep or shut down; on battery, as before.

### 2026-11-09 - PC en veille toute la nuit, 0 VOD rendue

- Gaming : rien de neuf rendu, coherence = Shorts du 11-06 (avant le fix des marges). Concurrents :
  hits = reaction a un contenu sur soi / clash avec une figure connue. gaming_interaction_v1 a 0.
- IRL : idem, 8/10 publies toujours HasanAbi politique (seule VOD dispo). Tests a 0-3 mesures.
- Debit : veille Windows 22:43 -> 11:57 (journal systeme), pas un bug ; proposition anti-veille.

### 2026-11-08 - 0 VOD rendue en 24 h, fins qui debordent sur la phrase suivante

- Gaming : coherence 3/4 finissent sur des mots de la phrase suivante (Shorts du 11-06) : marge de
  rendu, corrigee le 11-07 et commitee. gaming_interaction_v1 a 0 mesure. Revoir coherence demain.
- IRL : meme defaut (6/10). 8 des 10 publies = une VOD politique de HasanAbi. Test irl_cold_open_v1
  lance (demande du proprietaire, slot libre). irl_dialogue_v1 : A n=12, B n=3, loin du seuil.
- Debit : app arretee ~11-06 soir -> 11-08 18:25 ; depuis, une VOD de 48 h (stableronaldo, audio
  4.4 Go a 1000 Ko/s) occupe le seul telechargement. DOWNLOAD_SHARE 0.25, app redemarree.

### 2026-11-06 - changes made in the owner's conversation

- Both channels were set "made for kids" at channel level (their Shorts were not): switched to
  "not made for kids" by the owner on 2026-11-06. Compare views and retention of the Shorts
  published after that date with those before (report: "channels set to not made for kids").
- An Emiru Short was blocked in 2 countries for the stream's background music: moments with
  music are no longer rendered (vod_pipeline.MAX_MUSIC_SHARE: 25 % non-game, 45 % game; check
  the funnel's "sans musique" count: if many moments are lost, raise the bar), and a music
  claim no longer blacklists the streamer (Emiru removed from the list).

### 2026-11-06 - vraie cause des coupes en plein mot trouvee (split_sentences), guide hebdo refait

- Gaming : coherence 1/4 defaillant ; sur les 30 derniers Shorts des 2 chaines, ~15 commencent
  ou finissent sur un bout de phrase. Ce n'etait pas la saturation : split_sentences gardait les
  bouts en minuscule apres une pause 1.5-6 s comme phrases a part -> corrige + teste. Guide refait
  (45-90 s, interactions, accroche 1-3 mots). Test gaming_interaction_v1 lance. Revoir coherence.
- IRL : coherence 3/4 defaillants ("not." / "a new one?" en debut), meme cause, meme correctif.
  irl_dialogue_v1 : B toujours a 0 mesure. Guide refait (15-30 s garde, nos chiffres priment).
- Debit : 1 VOD/24h, 14 VOD renvoyees attendre Gemini (modeles CLOSED), 61 jobs abandonnes -
  8e jour, proposition tier payant toujours en attente.

### 2026-11-05 - saturation Gemini 7e jour de suite, coherence toujours touchee des deux cotes

- Gaming : 1 des 4 derniers Shorts defaillant (fin sur anticipation non resolue, pas de chute) -
  meme hypothese saturation que le 11-04. Dota 2 toujours surveille, rien de neuf. 2 emplacements
  de test libres, rien d'assez fort (pas d'etude concurrents ce run, guide a J+6).
- IRL : 2 des 4 derniers Shorts defaillants (coupe en plein mot, fin sur question sans reponse) -
  meme hypothese. Test irl_dialogue_v1 toujours a 0 mesure. 1 emplacement libre, rien d'assez fort.
- Debit : 2 VOD/24h (objectif 20+), un peu mieux qu'hier (1) mais toujours tres loin - 7e jour de
  suite, proposition tier payant mise a jour, toujours en attente de l'OK du proprietaire. Aucun
  changement de code (cause = saturation confirmee par les logs, pas un bug).

### 2026-11-04 - defauts de coherence probablement lies a la saturation Gemini extreme du jour

- Gaming : 2 des 4 derniers Shorts defaillants (fin en pleine question, debut/fin en pleine liste
  de dons) - trim_reason absent sur les deux, chemin de secours sans Gemini. Dota 2 toujours
  gaspille (2/3/27), aucune piste neuve. 2 emplacements de test libres, rien d'assez fort.
- IRL : 1 des 2 derniers Shorts coupe en pleine phrase (meme chemin de secours), l'autre conclut
  bien. Test irl_dialogue_v1 toujours a 0 mesure (seuil non atteint). 1 emplacement libre, rien
  d'assez fort.
- Debit : 1 VOD/24h (objectif 20+, pire qu'hier/5), quasi tous les modeles Gemini CLOSED, 38 VOD
  renvoyees en attente - 6e jour de suite, proposition tier payant mise a jour avec ces chiffres,
  toujours en attente de l'OK du proprietaire. Aucun changement de code ce run (cause probable =
  saturation, pas un bug de trimming confirme) - a reverifier un jour calme.

### 2026-11-03 - bug de coupe en plein mot/pensee enfin identifie (irl), 2 verdicts A/B irl + nouveau test

- Gaming : 4 derniers Shorts tous coherents (debut/fin propres) - le trimming "sujet complet" du
  11-02 tient. Dota 2 toujours gaspille (0/5/27), aucune piste neuve. 2 emplacements de test
  libres, aucune ligne de Knowledge assez forte ce run.
- IRL : coherence montre 2 Shorts sur 3 coupes en plein mot/pensee malgre le trimming du 11-02 -
  cause reelle trouvee (highlights.py, split_sentences) : une phrase sans ponctuation finale se
  coupait des qu'une pause depassait 1.5s, meme pensee inachevee. Corrige (pause toleree jusqu'a
  4s pour une phrase inachevee) + teste, pytest ok. Verdicts A/B : irl_title_style_v1 et
  irl_length_v1 tous deux au seuil, aucun B pas clairement meilleur, tests retires (A inchange).
  Nouveau test sur un emplacement libre : irl_dialogue_v1 (favorise dialogue/invite, evite le solo
  silencieux, ligne ohnepixel du 27/10 jamais testee).
- Debit : 5 VOD/24h (objectif 20+, en baisse), 20 VOD renvoyees en attente de Gemini, 49 abandons
  pour file pleine - 5e jour de suite, meme goulot deja remonte au proprietaire (proposition tier
  payant toujours en attente). Code change : fix split_sentences + test ; commit et redemarrage.

### earlier (2026-10-23 to 2026-11-02)

- 10-23 baseline : gaming 66 mesures, IRL 0 ; tests titres lances (perdus ensuite). 10-24 test
  gaming_length_v1 (45-90s, gagne le 11-01), 10-26 irl_length_v1 (perdu le 11-03). Bugs de coupe
  corriges (fin non recalee sans Gemini, KeyError 'start', plafond 58s). 10-27/28 (proprietaire) :
  sous-titres mot a mot, 2 VOD en parallele, prefetch, cadrage split, TikTok brouillons IRL,
  rendus limites au top 15, refus Gemini dans gemini_refusals.log. Debit 2-11 VOD/24h, goulot
  quota Gemini (proposition tier payant). 10-29/31 : Gemini sature,
  tests sous le seuil ; 10-30 panne DNS (app relancee) et fin de Short non recalee corrigee (trimming).
  11-01 : gaming_length_v1 gagne (45-90s par defaut), gaming_title_style_v1 retire. 11-02 : quota
  Gemini a sec ; trimming "sujet complet" reecrit par le proprietaire (commit dfdf63e).
