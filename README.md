# Twitch Auto Clipper

Premiere etape : creer un clip vertical a partir d'une video locale avec FFmpeg.

## Prerequis

- Python 3.11 ou plus recent
- FFmpeg installe et disponible dans le `PATH`

Pour verifier FFmpeg :

```powershell
ffmpeg -version
```

## Installation

Depuis la racine du projet :

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Utilisation

Placez une video dans `data/input/`, puis lancez la commande suivante :

```powershell
python -m twitch_auto_clipper video.mp4 30 45
```

Les arguments sont :

1. le nom du fichier dans `data/input/` ;
2. le debut du clip en secondes ;
3. la fin du clip en secondes.

Le resultat est cree dans `data/output/` au format MP4 vertical 9:16, avec un nom comme `video_clip_30_45.mp4`.

Un nom de sortie peut etre precise avec `--output` :

```powershell
python -m twitch_auto_clipper video.mp4 30 45 --output meilleur-moment.mp4
```

Les sous-titres peuvent etre brules dans le clip 9:16 uniquement avec l'option
`--subtitles`, en fournissant le JSON de transcription deja genere par Whisper :

```powershell
python -m twitch_auto_clipper video.mp4 30 45 --subtitles data/output/video_transcript.json
```

Les mots sont regroupes en petits blocs ASS a partir de leurs timestamps reels.
Sans `--subtitles`, le rendu du clip reste inchange.

Un clip peut aussi etre genere directement depuis un candidat sauvegarde dans un
fichier `*_highlights.json`. L'index est zero-based et les marges valent 5
secondes avant et apres par defaut :

```powershell
python -m twitch_auto_clipper --generate-from-candidate `
	--source data/input/video.mp4 `
	--candidate-json data/output/video_highlights.json `
	--candidate-index 0 `
	--transcript-json data/output/video_transcript.json `
	--before 5 `
	--after 5
```

Le clip est cree dans `data/output/`. Les bornes sont automatiquement limitees a
la duree reelle de la video. Si `--transcript-json` est fourni, les sous-titres
ASS correspondants sont appliques automatiquement.

Le pipeline automatique Gemini (modele par defaut `gemini-3.6-flash`) selectionne ensuite un candidat existant et lance
directement sa generation :

```powershell
$env:GEMINI_API_KEY = "votre-cle"
python -m twitch_auto_clipper `
	--auto-clip `
	--candidates-json data/output/video_highlights.json `
	--transcript-json data/output/video_transcript.json `
	--chat-json data/input/123456789_chat.json `
	--source data/input/video.mp4 `
	--before 5 `
	--after 5
```

Le flux est `candidats + transcript + chat -> Gemini -> candidat valide ->
candidate_clip.py`. L'index n'est pas demande : Gemini renvoie un identifiant
de candidat valide, puis le clip est cree dans `data/output/`.

Pour publier un clip vertical deja genere sur YouTube Shorts, creez un OAuth
Client ID de type Desktop dans Google Cloud, telechargez le fichier sous
`credentials.json` a la racine du projet, puis lancez :

```powershell
python -m twitch_auto_clipper `
	--upload-youtube `
	--video data/output/video_gemini_candidate_0.mp4 `
	--title "Mon Short Twitch" `
	--description "Description du Short" `
	--privacy private `
	--not-made-for-kids
```

Le premier lancement ouvre le navigateur pour autoriser la chaîne et enregistre
le token local dans `youtube-token.json`. Les lancements suivants réutilisent et
rafraîchissent ce token. Avant l'upload, le CLI demande une confirmation des
droits de publication et de la Privacy Policy. Une déclaration explicite est
également requise avec `--made-for-kids` ou `--not-made-for-kids`.

Configurez les protections suivantes avant un upload réel :

```powershell
$env:YOUTUBE_PRIVACY_POLICY_URL = "https://[VOTRE_URL_GITHUB_PAGES]/privacy.html"
$env:YOUTUBE_EXPECTED_CHANNEL_ID = "[VOTRE_CHANNEL_ID_YOUTUBE]"
```

`YOUTUBE_EXPECTED_CHANNEL_ID` est optionnelle, mais sans elle le CLI indique que
la vérification de chaîne n'est pas active. Lorsqu'elle est configurée,
l'application appelle `youtube.channels.list` avec `mine=true` et refuse
l'upload si l'identifiant de chaîne OAuth ne correspond pas. L'authentification
utilise le scope d'upload et, pour cette vérification, le scope de lecture de
chaîne YouTube.

Le cadrage vertical analyse quelques images de la video avec OpenCV sur CPU pour
placer la fenetre 9:16 autour du plus grand visage detecte. Si aucune face n'est
detectee, si la video ne peut pas etre lue ou si OpenCV n'est pas disponible, le
recadrage central existant est utilise automatiquement. Les fonctions Twitch, IA,
transcription et publication restent independantes du cadrage.

## Tests

```powershell
python -m unittest discover -s tests
```

## Public project documentation

The static public documentation for the project is in `docs/` and is designed
for GitHub Pages. It includes the project overview, YouTube API usage, Privacy
Policy, and Terms of Use. The pages identify the owner as Aymeric
Leclerre-Lemoine, use aymeric.leclerre@gmail.com as the public contact, and link
to the Aymeric05 GitHub repository.

To enable GitHub Pages, open the repository on GitHub, go to **Settings**,
**Pages**, choose **Deploy from a branch**, select the default branch and the
`/docs` folder, then save. The final URL remains to be confirmed after
publication: `https://[URL_GITHUB_PAGES_A_CONFIRMER]/`.

The site does not contain OAuth credentials, API keys, or tokens. The local
files `credentials.json` and `youtube-token.json` are excluded by `.gitignore`.