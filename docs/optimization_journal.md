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
- Concurrents (2026-11-20, 8 chaines apres retrait de Rupert Spira, faux "buddha") : hauts = CaseOh dans un
  role ("Can CaseOh Slay As...?", 3 des 10 derniers hauts), miniature webcam + jeu avec 1 mot (SLAY!) ;
  classements dans les deux tiers. Production 7 j (semaine GTA) : source chat 11 pub/7 res/5 jetes vs
  transcript 6/17/15 ; GTA V 1/12/4. 9 VOD/23 finies sans aucun moment admis en reserve (transcription perdue).
- Concurrents (2026-11-17, 40 derniers Shorts) : hauts = le streamer reagit a un evenement sur lui
  (CaseOh prix Streamer Awards 8x, Backrooms 7.9x) ; bas = compilations/classements ("Ranking The Funniest", 0.1x).
  Miniatures hits : ecran partage visage + jeu/creature. Bruit : une chaine non gaming (Rupert Spira) dans la liste.
  Production 7 j : >40s 20 pub/21 res/35 jetes (26 %), ROB RUN 1/4/8. Coherence : fins sur une question
  nouvelle sans reponse (11-11, 11-13, 11-17) : corrige dans le code (_past_question).
- Concurrents (2026-11-13, 284 Shorts, 9 chaines) : la duree ne separe plus hauts et bas (30-180 s tous
  ~1.0x la mediane ; <30 s 2.6x mais n=10). Hauts = CaseOh qui reagit a une animation sur lui (4 des 5
  meilleurs, 20-31x), admin/RP avec un personnage connu ; bas = scene RP lente (poesie, journaux), hors
  jeu. Miniatures hits : 1 mot en *MAJUSCULES* rouge/jaune sur le visage (YO!, LANG!). Production :
  GTA V 0 publie/7 reserve/7 jetes en 7 j (poids appris -0.5), a surveiller avant de toucher.
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

- Production (2026-11-14, Shorts des 7 derniers jours) : World of Warcraft rend beaucoup pour peu de
  publies (5 pub / 20 reserve / 18 jetes) contre Fortnite 16/3/13 ; ROB RUN 0/2/7 ; source emotion
  1/9/3. Points appris fortnite +1.3, LoL +1.6. A suivre : si WoW reste <15 % publie une semaine de
  plus, proposer un budget de clips reduit pour WoW.
  2026-11-15 : WoW 12 pub / 15 res / 29 jetes (21 % publie), Fortnite 12/9/12 (36 %), ROB RUN 0/2/7,
  emotion 1/6/6. WoW remonte un peu ; on garde la surveillance.

- Verdict A/B gaming_interaction_v1 (2026-11-16, seuil atteint : A n=33/vods=9, B n=20/vods=8) :
  perf A 0.6 vs B 0.3, retention 53.5 vs 53.9 - B pas meilleur, test retire, selection inchangee.
  Affaiblit la ligne concurrents "interactions" (11-06/11-09) : ne se confirme pas chez nous.
- Production (2026-11-16, 7 j) : Fortnite 14 pub/5 res/14 jetes (42 %), WoW 9/15/19 (21 %), ROB RUN
  0/3/7 (0 publie en 7 j, 3e jour), len=25-40s 7/6/4 (41 %) vs >40s 18/23/39 (22 %). 14 des ~40 VOD
  traitees (2 chaines) finissent "aucun moment assez bon pour la reserve" apres l'appel Gemini (pre-gate
  au score maximal) : piste = pre-gate plus realiste, a chiffrer avant d'y toucher.

- Production (2026-11-18, 7 j) : Fortnite 14 pub/3 res/14 jetes (45 %), WoW 8/8/11 (30 %), Deadlock
  3/8/4, ROB RUN 0/4/7 (0 publie, 5e releve de suite) ; len <25s 5/2/7, 25-40s 6/9/5, >40s 17/17/28.
  Le log "Selection Gemini X/25" compte les moments restants apres l'entonnoir (admis en reserve),
  pas ce que Gemini garde : pas de perte a la selection (piste du 11-17 close).
- Coherence (2026-11-18) : 3/4 bonnes ; 1 debut sur un fragment ("One proc. Oh, the gorilla's...").
  Debuts en plein sujet : 2/4 le 11-16, 1/4 le 11-18 - en baisse depuis le garde-fou du 11-16.
- 2026-11-19 : coherence 3/4 (4 Shorts WoW d'une VOD de discussion "exploit/ban") ; 1 de 85 s finit sur
  "Yeah, do you?" (question isolee, garde-fou _past_question en place). Concurrents : 5 hauts = CaseOh
  (reaction a son animation, 0.9-1.5M), bas = classements CaseOh (300-440 vues) ; miniatures hits = visage
  + 1 mot rouge/rose ("SLAY!"), bas = liste numerotee en overlay. Confirme les lignes 11-13/11-17.

### PeakMoments (irl)
- Concurrents (2026-11-20, 6 chaines) : tiers haut 38 s vs bas 31 s (la duree seule ne separe plus) ;
  hauts = visage + 1 mot (BREATHE), bas = politique Hasan, overlays d'actualite. Production 7 j : <25s
  6 pub/5 res/1 jete. Coherence : debuts sur un mot de liaison ("And that's how...", 11-20) corriges
  (_settled_start). 0 Short IRL rendu en 24 h (file prise par GTA, attendu cette semaine).
- Concurrents (2026-11-17, 40 derniers) : hauts = reaction a un evenement/drama (Streamer Awards, H3, 5-13x) ;
  miniatures hits = deux visages ou visage + scene, flop = overlay de chat. Production 7 j : >40s 1 pub/11 res/7 jetes
  (5 %), <25s 5/5/3 (38 %) ; chat 2/9/5. Verdict irl_dialogue_v1 (2026-11-17) : B pas meilleur (perf -0.4 = -0.4,
  retention 47.7 vs 63.0), retire. Test irl_short_v1 (15-25 s) lance.
- Concurrents (2026-11-13, 215 Shorts, 7 chaines) : 6 des 7 meilleurs = Speed (17-50 s, action physique
  ou emotion forte, 19-36x) ; bas = politique (Hasan midterms, gouverneur 0.23x), clips sans sujet ("WTF",
  "HOLYY"). Miniatures : visage + 1 mot *REVENGE*/*CAUGHT 4K*. Production : source chat 1 publie/4/5 jetes
  en 7 j, poids appris -0.8 : moments du chat peu rentables, idee de test si un slot se libere.
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

- Production (2026-11-14, 7 jours) : source chat 3 pub / 2 reserve / 10 jetes (et point appris
  source=chat -0.7), transcript 21/22/16, emotion 6/2/2. Les moments du chat sont surtout rendus pour
  rien : candidat a reduire (budget ou regle de selection) si ca se confirme.
  2026-11-15 : confirme, chat 3 pub / 4 res / 11 jetes (17 % publie), point appris source=chat -0.6.
  Premier test a lancer quand un slot IRL se libere (regle de selection : pas de moment du seul chat
  sans parole claire). Longueur : nos Shorts IRL 38.5 s (guide 15-30, top concurrents 29 s) et points
  appris <25s +0.6 / >40s -0.6 : le trim depasse le guide ; second candidat de test.
- Production (2026-11-16, 7 j) : Just Chatting 35 pub/26 res/21 jetes ; len=25-40s 19/8/11 (50 %),
  <25s 7/8/4, >40s 11/11/11 (33 %) ; source chat 4/6/6 (25 %) vs transcript 29/17/17 (46 %), coherent
  avec les points appris (source=chat -0.7, length=>40s -0.7). Concurrents : tiers haut 28 s vs bas 31 s,
  nous 37 s ; titres 34 vs 38.5 caracteres, nous 49.

- Production (2026-11-18, 7 j) : Just Chatting 19 pub/26 res/15 jetes ; source chat 5/7/5 (29 %) vs
  transcript 13/15/11 (33 %) : l'ecart chat se resserre. len >40s 4/7/7 (22 %) reste le pire.
- irl_cold_open_v1 (2026-11-18, seuil atteint : A n=31/vods=9, B n=35/vods=7) : retention B 68.2 vs
  53.4 mais perf -0.4 vs -0.3 et vues 4 vs 7 : mitige, pas "clairement meilleur" sur les deux, on attend.
- Coherence (2026-11-18) : 3/4 bonnes, Shorts de 18-25 s ; 1 debut en plein sujet ("In the middle of
  the ball too...").
- Verdict irl_cold_open_v1 (2026-11-19, A n=37/9 VOD, B n=37/7 VOD) : retention B 69.2 vs 57.8 mais perf
  -0.4 vs -0.3 et vues 5 vs 9, 3e releve de suite dans ce sens : pas clairement meilleur, test retire,
  cold open garde. A retenir : sans cold open la retention monte (+11 pts) mais pas la diffusion.
- 2026-11-19 : coherence 4/4 correctes (16-33 s, chutes nettes) mais les 4 = monologues politiques de
  HasanAbi (meme VOD) malgre la regle par defaut anti-politique ; chez les concurrents les 5 bas = Hasan
  politique 60-110 s (3-8k vues), les 5 hauts = Speed emotion/evenement 18-50 s (1.1-1.9M). Cause probable :
  peu de VOD rendues (9/24 h), la reserve se remplit avec ce qui reste.

## Waiting for the owner

Risky or doubtful actions are never done directly: the loop writes them here (what, why with
numbers, risks, how to undo) and in its daily summary. The owner answers by writing OK or NON
at the start of the line (or tells Claude); the next run applies the OK ones, drops the NON
ones, and moves them to the entries.


## Changes under evaluation

| Since | Change | Expected effect | Metric to watch | Verdict |
|---|---|---|---|---|
| 2026-11-21 | Fix (vod_acquisition.record_automation) : une partie de live traitee quitte la file (avant : restait reservee, bloquait le prechargement) ; Fix : errors="replace" sur les sous-processus texte | plus de workers inactifs, plus de VOD rendues | VOD rendues/24h, taille de la file | pending |
| 2026-11-20 | Fix (trimming._settled_start) : un debut sur un mot de liaison (And, But, So...) remonte d'une phrase ; Fix (competitors.NOT_CLIP_CHANNELS) : Rupert Spira hors concurrents | moins de debuts en plein sujet ; donnees concurrents gaming propres | coherence du rapport | pending |
| 2026-11-17 | MAX_QUEUED_JOBS 40 -> 50 (palier 3 de la montee Gemini) | moins de VOD jetees file pleine (38/24h), plus de candidats | VOD rendues/24h, jobs jetes, requetes par cle, file | pending |
| 2026-11-17 | Fix (trimming._past_question) : une fin sur une question sans reponse recule a la phrase d'avant | plus de fins "What do we think about mid boss?" | coherence du rapport | pending |
| 2026-11-17 | A/B irl_short_v1 : Shorts IRL 15-25 s (ideal_seconds + trim_rules) | perf/retention meilleures (appris <25s +0.6, >40s -0.7) | retention_pct, perf of B vs A | pending (0 measured) |
| 2026-11-16 | VOD_WORKERS 2 -> 3 (palier 2 de la montee Gemini) | plus de VOD rendues/24h (12, objectif 20), cles 2/3 mieux utilisees (136 requetes/~360) | VOD rendues/24h, requetes par cle, file, charge du PC | pending |
| 2026-11-16 | Fix (trimming._settled_start + prompt) : un debut sur une phrase en minuscule (suite de la precedente) remonte d'une phrase | moins de debuts en plein sujet ("when the deal is done...", 1/4 a 2/4 par jour depuis le 11-13) | coherence du rapport | pending |
| 2026-11-16 | A/B gaming_tight_start_v1 : sujet pose dans les 3 premieres secondes (trim_rules) | retention meilleure (hits concurrents = enjeu <3 s) | retention_pct, perf of B vs A | pending (0 measured) |
| 2026-11-15 | TOP_STREAMER_CLIP_BUDGET 20 -> 25 (palier 1 de la montee Gemini) | plus de candidats par VOD de streamer top, cles 2/3 mieux utilisees | VOD rendues/24h, requetes Gemini par cle, heure de saturation, taille de la file | pending |
| 2026-11-15 | Fix (trimming._settled_end + highlights.split_sentences) : une fin qui traine ("... Oh She", "... J of K And...") s'arrete au dernier segment Whisper complet de la phrase | plus de fins en pleine phrase (2/4 irl le 11-14) | coherence du rapport | pending |
| 2026-11-14 | Fix (trimming._settled_end) : une fin sur un fragment d'un seul mot sans ponctuation (debut de la scene suivante) s'arrete a la phrase d'avant | plus de fins "There's no quest. Oh" (gaming 11-14), "Okay. Tell" (11-08) | coherence du rapport | pending |
| 2026-11-20 | GPU transcription with faster-whisper's batched pipeline (batch 16), its ~30 s segments cut into sentences (transcription._sentences); measured 3.4x faster on 20 min of a real stream, with punctuation and fewer misheard words (owner's OK). Plus, during the GTA 6 week, one worker and 10 queue places kept for the other streams | the transcription bottleneck (623 min + 315 min GPU wait per 24 h) shrinks; PeakMoments fed again | durees transcription per VOD, VODs rendered per 24 h, Short coherence (starts/ends) | pending |
| 2026-11-19 | Live clipping ON (LIVE_CLIPPING=1 in .env, owner's OK): a stream is processed in 2-hour parts while live ("<vod id>p<n>", TwitchDownloaderCLI audio range), its last part once it ends; a stream under 2 h or first seen ended is a whole VOD as before. Owner: remove it if it overloads the Gemini quota | Shorts published while the live is still on (fresher) | hours between a moment and its publication, Gemini requests per day vs before, duplicate Shorts across parts, VODs rendered per 24 h | pending |
| 2026-11-18 | App-wide Gemini pause of 10 min (OVERLOAD_PAUSE, owner's OK) once a call found every model overloaded; plus quota counts no longer lost between workers (daily_quota lock). Before: each VOD retried the 5 models on its own, up to ~170 requests burnt in the 15-17 h UTC overload of 11-17, keys 1-2 closed early | fewer requests burnt on 503, keys last longer, more VODs per day | VODs sent back for Gemini, requests per key and hour each key closes, VODs rendered per 24 h | pending |
| 2026-11-17 | Hook rule (owner's idea): when the clip itself raises a question, the hook may ask it explicitly ("Can he really pull this off?"); hook only, never a selection or score criterion | more viewers watch to the end | retention_pct and views_3d of Shorts whose hook ends with "?" vs the others, per channel | pending |
| 2026-11-17 | Bandwidth measured again every hour (cli BANDWIDTH_CHECK_SECONDS, owner's OK), between two downloads; before, one bad start-up measure (1000-1596 Ko/s instead of ~12000) capped the downloads until the next restart | no day lost to a bad measure; fairer measure of VOD_WORKERS 3 | "Telechargements des VOD limites" log lines, VODs rendered per 24 h | pending |
| 2026-11-14 | Reserve pre-gate moved before the download (vod_acquisition.worth_downloading, owner's OK): a VOD with no chance to enter its channel's reserve is no longer downloaded (~1 downloaded VOD in 3 was dropped right after) | bandwidth goes to useful VODs, more VODs rendered per 24 h | VODs rendered per 24 h, "non telechargee" log lines, keys 2/3 usage | pending |
| 2026-11-13 | MAX_OVERLOADED_TRIES 2 -> 5 (owner's OK): on 503 every model of the lane is tried before the VOD waits 30 min; 3 keys make quota no longer scarce | fewer VODs sent back to wait for Gemini, more VODs rendered per 24 h | VODs sent back (report's gemini line), VODs rendered per 24 h, keys 2/3 usage | pending |
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
| 2026-11-03 | A/B irl_dialogue_v1: favorise dialogue/invite avec chute claire, evite le solo silencieux (ohnepixel) | retention/views plus proches des hits | retention_pct, views_3d of B vs A | **not better** (2026-11-17, perf -0.4 = -0.4, retention B 47.7 vs A 63.0), removed |
| 2026-11-03 | Fix (highlights.py): une phrase sans ponctuation finale (hesitation, silence qui traine) peut maintenant se continuer au-dela d'une pause de 1.5s (jusqu'a 4s) au lieu de se couper en phrase separee | moins de Shorts coupes en plein mot/pensee (irl, 2 des 3 derniers controle qualite) | coherence du rapport (debut/fin), controle qualite | pending |
| 2026-10-26 | Fix: a failed Gemini trim call (quota/network) still snaps every moment's end to a sentence boundary, instead of keeping the raw un-snapped end | fewer mid-word/mid-sentence cuts | Gemini quality-check defects on our Shorts | pending |
| 2026-10-26 | Fix: a partial trim (end only, no start) no longer crashes the whole VOD (missing "start" key) | fewer VOD retries/losses | "erreur inattendue" / KeyError in the log | pending |
| 2026-10-30 | Fix: when Gemini's trim answer for a moment is rejected or missing, its start is now also recalee on a sentence boundary (only the end was before) | fewer "no context at start" / early cuts | Gemini quality-check defects on our Shorts | pending |
| 2026-11-06 | A/B gaming_interaction_v1: favorise interactions entre personnes avec chute, evite action seule/compilations | retention/views plus proches des hits | retention_pct, views_3d of B vs A | **not better** (2026-11-16, perf A 0.6 vs B 0.3, retention 53.5 vs 53.9), removed |
| 2026-11-06 | Fix (highlights.py): un segment en minuscule rejoint la phrase precedente jusqu'a 6 s de pause | plus de Shorts qui commencent/finissent sur un bout de phrase ("not.", "I walked in and") | coherence du rapport | pending |
| 2026-11-08 | A/B irl_cold_open_v1: pas de cold open sur PeakMoments (b: cold_open false) | retention meilleure si le cold open nuit en IRL (points appris -0.4) | retention_pct, perf of B vs A | **not better** (2026-11-19, retention B 69.2 vs 57.8 mais perf -0.4 vs -0.3, vues 5 vs 9), removed |
| 2026-11-07 | Fix (vod_shorts._clip_bounds): les marges avant/apres restent dans le silence, plus de mots de la phrase suivante/precedente | fin propre au lieu de "... Okay. Tell" | coherence du rapport | pending |
| 2026-11-13 | Fix (trimming._past_question) : une fin sur une question va jusqu'a la phrase-reponse (< 2 s apres, dans la limite) | plus de fins "can they break?" (2/8 le 11-13 malgre le prompt) | coherence du rapport | pending |
| 2026-11-12 | Fix (vod_pipeline._trimmed) : un moment encore plus long que la limite apres le trim (trim Gemini refuse/injoignable) n'est plus rendu | plus de Shorts de 126-180 s (2 publies/rendus irl le 11-11, VOD 2925140576) | duree des Shorts dans la coherence du rapport | pending |
| 2026-11-11 | Fix (shorts_upload._ready_shorts) : un moment rendu deux fois (VOD reprise apres Gemini indisponible) n'est publie qu'une fois, seul son rendu le plus recent est garde | plus de doublons publies (3 depuis le 11-09) | doublons par (candidate_id, candidate_start) dans les manifestes | pending |
| 2026-11-11 | Fix (trimming.py) : le prompt interdit de finir sur une question sans reponse ou le debut d'une nouvelle scene | moins de fins "What is that?" (3/4 gaming, 2/4 irl le 11-11) | coherence du rapport | pending |
| 2026-11-10 | Fix (transcription.py): Whisper GPU dans un sous-processus, repli CPU si crash cuDNN | l'app ne s'arrete plus en silence (3 crashs 11-07/11-09) | throughput, "Application Error" python.exe dans le journal Windows | pending |
| 2026-11-08 | DOWNLOAD_SHARE 0.10 -> 0.25 (cli.py) | telechargements plus rapides (VOD de 48 h bloquant la file) | throughput du rapport | pending |
| 2026-11-02 | Trimming reecrit (hors boucle): debut/fin cales sur un sujet complet, Shorts gardent leurs mots parles | moins de debuts/fins incomplets | coherence du rapport (debut/fin), controle qualite Gemini | pending (aucune donnee encore) |

## Entries

### 2026-11-21 - parties de live jamais closes (workers a l'arret), fix

- Gaming : coherence 4/4 (debut = declencheur, fin = chute/reaction). gaming_tight_start_v1 A 12/4 VOD,
  B 12/7 (retention B 71.7 vs 39.0, perf 0.3 vs -0.1) : prometteur, on attend 20/6. Production : moments
  "chat" 13 publies/6 reserve/5 jetes contre "transcript" 11/18/18 ; pas de nouveau test (semaine GTA).
- IRL : coherence : 4 rendus anciens (11-18), 1 debut "And that's how..." deja couvert par le fix du 11-20.
  irl_short_v1 A 3/1 VOD, B 8/3 : on attend. 1 seul rendu IRL en 24 h (GTA + blocage ci-dessous).
- Debit 9 VOD/24h, 545 jobs jetes. Cause : record_automation cherchait le job d'une partie de live sous l'id
  du stream (sans "#pN") : job jamais clos, reste "reserve" avec son audio ; 4 tels jobs = les 4 places de
  prechargement, workers inactifs 14:51-17:00 (app/PC eteints aussi 01:23-10:30 et 17:30-22:08, coupure
  reseau 22:10-23:48). Corrige + test. Transcription batched : 142 min/24h (623 avant), attente GPU 12 min.
  Aussi : sortie d'outil non decodable (cp1252) tuait un thread lecteur : errors="replace" partout (test).
  A suivre : VOD rendues/24h demain (attendu >> 9).

### 2026-11-20 - debuts sur "And..." corriges, faux concurrent retire, guide hebdo refait

- Gaming : coherence 3/4 (1 fin sur "hey over here, dude?", isolee). gaming_tight_start_v1 A 8/2 VOD,
  B 7/5 : on attend. Chaine "Buddha at the Gas Pump" (spirituel) retiree des concurrents (code + donnees).
  Guide refait (accroche = ce que fait le streamer, classements jamais un atout). Pas de nouveau test (semaine GTA).
- IRL : coherence 2/4 commencent en plein sujet ("And that's how...", "Adult child. Okay."), rendus du 11-18 :
  un debut sur un mot de liaison remonte d'une phrase (test). irl_short_v1 A 1 / B 2 mesures. 0 rendu IRL en 24 h
  (GTA prend la file, voulu). Guide : regle de duree assouplie (hits 16-45 s), ideal [15,30] garde pendant le test.
- Debit 7-8 VOD rendues/24h, 478 jobs jetes file pleine. Etape limitante = transcription : 623 min (32 VOD) +
  315 min d'attente GPU, contre 68 min de telechargement et 83 min de selection Gemini ; 9 VOD sur 23 finies sans
  moment admis en reserve. Pas de palier Gemini (semaine GTA, cle 3 ouverte).

### 2026-11-19 - verdict irl_cold_open_v1 (garde), Gemini plein a 20/modele selon Google

- Gaming : coherence 3/4 (1 fin sur "Yeah, do you?", isolee). gaming_tight_start_v1 A 3 / B 7 mesures : on
  attend. Concurrents/miniatures : rien de neuf (CaseOh reagit a lui-meme vs classements). Guide du 11-13 du le 11-20.
- IRL : irl_cold_open_v1 retire (retention B +11 pts mais perf et vues plus basses) : cold open garde. Slot
  libre, pas de nouveau test (la regle anti-politique est deja par defaut). irl_short_v1 : 0 mesure.
- Debit 9 VOD/24h, 60 jobs jetes (file pleine). Etape limitante = Gemini : 93 passages pipeline pour 9 rendus,
  58 renvois 503 + 22 quota ; Google ferme chaque modele a 20 (k1-k3 vers 14-16 h UTC, k4 vers 21 h) quand
  nos compteurs lisent 6-16 (ecart non explique). Transcription 602 min de travail/24 h, GPU 216 min d'attente.
  Pas de palier (quota deja plein, semaine GTA 6).

### 2026-11-18 - debit 6 VOD/24h (vagues de 503 Gemini), aucun verdict

- Gaming : coherence 3/4 bonnes (1 debut sur un fragment, cas isole). gaming_tight_start_v1 : 4 mesures B,
  rien a trancher. ROB RUN 0 publie en 7 j (5e releve), le modele appris le gere ; pas de nouveau test.
- IRL : coherence 3/4 (18-25 s, 1 debut en plein sujet). irl_cold_open_v1 au seuil mais mitige (retention
  B 68 vs 53, perf -0.4 vs -0.3) : on attend. irl_short_v1 : 0 mesure.
- Debit 6 VOD/24h (12 hier) : 34 renvois pour 503 UNAVAILABLE, groupes 15-17 h UTC ; cles 1-2 fermees
  (7-16 requetes comptees), cle 3 ~44. Plus de jobs jetes file pleine (1 seul, echec de telechargement).
  Pas de palier aujourd'hui (palier 3 a mesurer). Durees par etape loguees depuis 11-18 00:07 : somme demain.

### 2026-11-17 - fins sur une question sans reponse, verdict irl_dialogue_v1, palier Gemini 3

- Gaming : coherence 3/4 bonnes, 1 finit sur une question nouvelle ("What do we think about mid boss?",
  3e fois depuis le 11-11) : la fin recule a la phrase d'avant (trimming._past_question, test).
  gaming_tight_start_v1 : 0 mesure. Concurrents : hits = reaction a un evenement sur soi, flops = compilations.
- IRL : coherence 4/4 correctes (une de 42 s). irl_dialogue_v1 perdu (retention 47.7 vs 63.0), retire ;
  irl_short_v1 lance (15-25 s). irl_cold_open_v1 mitige (retention B 75 vs 51, perf -0.5 vs -0.3) : on attend.
- Debit 12 VOD/24h (12 hier, palier 2 sans effet visible), 38 jobs jetes (65) ; Gemini ~162 requetes a 23h UTC,
  cle 3 a 33, 2 renvois. Palier 3 : MAX_QUEUED_JOBS 40 -> 50. Selection Gemini garde 0-3 moments/25 : a suivre.

### 2026-11-16 - debuts en plein sujet corriges, test interactions gaming perdu, palier Gemini 2

- Gaming : coherence 2/4 commencent en plein sujet ("when the deal is done...", "Attempts somehow...").
  Garde-fou (trimming._settled_start + regle du prompt, test). gaming_interaction_v1 perdu (perf 0.6 vs 0.3,
  retention egale), retire ; gaming_tight_start_v1 lance (sujet pose en <3 s). Miniatures non regardees.
- IRL : coherence 3/4 bonnes (1 finit sur "Um, okay. Look.", cas isole). Aucun verdict : irl_dialogue_v1
  A 5 VOD (<6, B en retrait 43.6 vs 72.3) ; irl_cold_open_v1 A 3 VOD. Guide hebdo du 11-13, pas encore du.
- Debit 12 VOD/24h (11 hier), 65 jobs jetes ; Gemini ~136/360 requetes, cle 3 a 5, renvois = 503/timeout.
  Palier 2 : VOD_WORKERS 2 -> 3, a mesurer 24 h (recul si le PC ne suit pas).

### 2026-11-15 - fins IRL en pleine phrase, palier Gemini 1

- Gaming : coherence 4/4 acceptables (1 debut en plein sujet "Oh Well, whatever"). gaming_interaction_v1
  A 28/7 VOD, B 15/6 : on attend (B < 20). Pas de nouveau test (aucune ligne Knowledge assez forte).
- IRL : coherence 2/4 finissent en pleine phrase ("... Oh She", "... J of K And...") malgre le correctif
  d'hier (phrase de plusieurs mots sans ponctuation). Corrige : la fin recule au dernier segment Whisper
  complet (test). Aucun verdict : irl_dialogue_v1 5 VOD chacun (B en retrait : retention 33 vs 72) ;
  irl_cold_open_v1 A 2 VOD. Rapport : retention 0 (pas encore de chiffre YouTube) exclue des medianes.
- Debit 11 VOD/24h (8 hier), 45 jobs jetes ; renvois Gemini = 503 uniquement, cle 3 a ~13 requetes.
  Palier 1 : TOP_STREAMER_CLIP_BUDGET 20 -> 25, a mesurer 24 h avant le palier suivant (VOD_WORKERS).

### 2026-11-14 - fins sur un fragment de la scene suivante corrigees

- Gaming : coherence 2/4 mal finies (WoW "There's no quest. Oh" : fragment de la scene suivante ; WoW
  89 s finit en plein combat). Garde-fou ajoute (trimming._settled_end, test). Aucun verdict :
  gaming_interaction_v1 A 25/5 VOD, B 8/2. Pas de nouveau test (aucune ligne Knowledge assez forte).
- IRL : coherence 1/4 commence en plein sujet ("In the UK, that means..."), les autres correctes. Aucun
  verdict : irl_dialogue_v1 A 33/5, B 22/4 VOD ; irl_cold_open_v1 A 10/2, B 15/3 (retention B incoherente, peu de donnees).
- Gemini : depuis la relance de 20h30 (5 essais sur 503), 2 VOD renvoyees pour 18 pipelines finis (54 avant).
  Cle 3 a 1 requete : sous la cible, mais le palier d'hier n'a pas encore un jour de mesure ; montee suivante
  (TOP_STREAMER_CLIP_BUDGET +5) au prochain run si le debit ne remonte pas seul. Debit 8 VOD/24h, 45 jobs jetes.

### 2026-11-13 - fins sur une question corrigees dans le code, guide hebdo refait

- Gaming : coherence 1/4 finit sur une question ("can they break?"), 1/4 commence en plein decompte.
  Garde-fou ajoute (trimming._past_question, test) : une fin sur "?" va jusqu'a la reponse si elle suit
  en moins de 2 s. Guide refait (284 Shorts, 9 chaines). Aucun verdict (gaming_interaction_v1 B n=5/1 VOD).
- IRL : coherence 1/4 finit sur une question ("Is my candle cooked now?"), meme correctif. Guide refait
  (215 Shorts, 7 chaines). irl_dialogue_v1 A 29/5 VOD, B 17/3 ; irl_cold_open_v1 A 6 / B 10 : on attend.
- Debit 8 VOD/24h, 54 jobs jetes (file pleine) ; ~30 renvois "Gemini indisponible" sur ~10 VOD, tous 503
  (surcharge Google, pas le quota : cle 2 peu utilisee, cle 3 a 0). Pas de hausse d'usage Gemini (VOD renvoyees).

### 2026-11-18 - GTA 6 launch week (owner): until 2026-11-26 00:00 UTC

- launch_event.py: GTA 6 streams (Twitch category "Grand Theft Auto VI") are followed from 1000
  viewers, handled like the owner's lists (25 moments, 3 days, 12 tries), first in the queue, first
  in LiveActions!' reserve ranking, with "(GTA 6)" in the title and #gta6 #gtavi.
- Same week only: a GTA 6 Short of LiveActions! whose frames show mostly the streamer
  (on_webcam) may also be published by PeakMoments, only once LiveActions! leaves it out of its
  reserve (top 30, written to gta6_liveactions_reserve.json), then on score (owner, 2026-11-18).
- Everything goes through launch_event.boosted(): after END the app is exactly as before (git tag
  before-gta6-launch). Do NOT tune anything on this week's numbers as if it were a normal week
  (GTA 6 takes most slots on purpose); do not change END without the owner.

### 2026-11-14 - owner's rule: whitelist streamers are never blacklisted

- NEVER put a streamer of the owner's lists (top_streamers_gaming.txt, top_streamers_irl.txt,
  favored_streamers.txt) in blocked_streamers.txt, automatically or by hand. The app now refuses
  it (shorts_upload protected_streamers); kaicenat, added automatically on 11-10 after Short
  MCqUlVRdGQs disappeared from YouTube about an hour after upload, was removed from the blacklist.
  A problem on such a streamer's Short is only noted (and reported to the owner).
- Cause found (owner's Studio screenshot): both kaicenat Shorts (MCqUlVRdGQs, HgqqMsPnaHQ) were
  "Traitement abandonne" (YouTube processing failed, likely the PC shut down during publication),
  not a takedown. Such a video vanishes from the API exactly like a removed one. Since 2026-11-14 the
  app follows the processing after each upload (youtube._wait_for_processing): an abandoned one is an
  upload error, the Short is kept and sent again later. Both entries relabelled in published_shorts.json.

### earlier (2026-10-23 to 2026-11-12)

- 10-23 baseline : gaming 66 mesures, IRL 0 ; tests titres lances (perdus ensuite). 10-24 test
  gaming_length_v1 (45-90s, gagne le 11-01), 10-26 irl_length_v1 (perdu le 11-03). Bugs de coupe
  corriges (fin non recalee sans Gemini, KeyError 'start', plafond 58s). 10-27/28 (proprietaire) :
  sous-titres mot a mot, 2 VOD en parallele, prefetch, cadrage split, TikTok brouillons IRL,
  rendus limites au top 15, refus Gemini dans gemini_refusals.log. Debit 2-11 VOD/24h, goulot
  quota Gemini (proposition tier payant). 10-29/31 : Gemini sature,
  tests sous le seuil ; 10-30 panne DNS (app relancee) et fin de Short non recalee corrigee (trimming).
  11-01 : gaming_length_v1 gagne (45-90s par defaut), gaming_title_style_v1 retire. 11-02 : quota
  Gemini a sec ; trimming "sujet complet" reecrit par le proprietaire (commit dfdf63e). 11-03 : fix
  split_sentences (phrase inachevee tolere 4 s de pause), irl_title_style_v1 et irl_length_v1 perdus,
  irl_dialogue_v1 lance. 11-04 : Gemini sature, 1 VOD/24h, defauts de coherence sur le chemin de secours.
  11-05 : Gemini sature 7e jour, 2 VOD/24h. 11-06 : vraie cause des coupes en plein mot (split_sentences
  gardait les bouts en minuscule comme phrases a part) corrigee, guide refait, gaming_interaction_v1 lance.
  11-06 (proprietaire) : chaines en "not made for kids", moments avec musique plus rendus (MAX_MUSIC_SHARE).
  11-08 : app arretee ~2 jours, VOD de 48 h bloquant le telechargement, DOWNLOAD_SHARE 0.25 ; fins
  debordant sur la phrase suivante (marge de rendu) corrigees ; irl_cold_open_v1 lance. 11-09 : PC en
  veille toute la nuit (0 VOD), anti-veille accepte par le proprietaire.
  11-09 (proprietaire) : tier Gemini payant NON (ne pas reproposer sans chiffres apres economies) ;
  plusieurs Shorts d'une meme VOD OK, pas de plafond par VOD ni par streamer.
  11-10 : app tuee en silence par un crash cuDNN (transcription GPU) ; transcription GPU mise dans un
  sous-processus avec repli CPU. 2 VOD/24h.
  11-11 : doublons publies (moment re-rendu apres 503) corriges ; regle de trim "pas de fin sur une question".
  11-12 : Shorts IRL de 126-180 s (trim refuse) plus rendus ; les 3 doublons LiveActions! sont geres par le
  proprietaire lui-meme : ne plus les proposer ni les rappeler.
