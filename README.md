# Twitch Auto Clipper

An automated pipeline that discovers live Twitch streams, monitors them for viewer
activity, acquires their VODs once they end, transcribes them, collects Twitch chat
replay data, identifies potential highlight moments with heuristics, and uses Gemini
to select the best candidates for vertical short-form video clips.

> **Status:** The pipeline through Gemini highlight selection and single-clip generation
> is implemented and tested. Multi-clip generation, YouTube automation, and publishing to
> Instagram Reels / TikTok are planned but not yet implemented.

---

## Pipeline

| Stage | Status |
|---|---|
| Twitch live discovery (English streams, viewer-count order) | ✅ Implemented |
| Viewer-based clip budget assignment | ✅ Implemented |
| Continuous stream monitoring + stream-end detection | ✅ Implemented |
| VOD acquisition via Twitch Helix API + yt-dlp | ✅ Implemented |
| VOD transcription (faster-whisper, CPU/int8, word timestamps) | ✅ Implemented |
| Twitch chat replay download (TwitchDownloaderCLI) | ✅ Implemented |
| Heuristic highlight candidate detection | ✅ Implemented |
| Gemini highlight selection (single or multi-candidate) | ✅ Implemented |
| Vertical clip generation (9:16, FFmpeg) | ✅ Implemented |
| Face-aware horizontal framing (OpenCV, CPU) | ✅ Implemented |
| ASS subtitle generation from word-level timestamps | ✅ Implemented |
| Manual YouTube Shorts upload | ✅ Implemented |
| Automated multi-clip generation per VOD (clip budget) | 🔲 Planned |
| AI-generated titles and descriptions | 🔲 Planned |
| Automatic post-upload local file cleanup | 🔲 Planned |
| Instagram Reels publishing | 🔲 Planned |
| TikTok publishing | 🔲 Planned |
| Cloud / always-on deployment | 🔲 Planned |

---

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) (must be in `PATH`)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — for VOD download
- [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader) — for chat replay
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — for transcription
- `google-genai` Python package — for Gemini evaluation
- `opencv-python-headless` — for face-aware framing (optional, falls back to center crop)
- Google OAuth Desktop credentials — for YouTube upload

Verify FFmpeg is available:

```powershell
ffmpeg -version
```

---

## Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

The base install (`pyproject.toml` dependencies) covers YouTube upload and OpenCV framing.
Install optional runtime dependencies as needed:

```powershell
pip install faster-whisper yt-dlp google-genai
```

---

## Configuration

All credentials are read from environment variables. **Never hardcode secrets.**

### Twitch API

Required for stream discovery, monitoring, and VOD lookup:

```powershell
$env:TWITCH_CLIENT_ID     = "YOUR_TWITCH_CLIENT_ID"
$env:TWITCH_CLIENT_SECRET = "YOUR_TWITCH_CLIENT_SECRET"
```

Create a Twitch application at [dev.twitch.tv](https://dev.twitch.tv/console/apps) to
obtain these values. The application uses the `client_credentials` grant — no user login
is required.

### Gemini API

Required for highlight candidate evaluation:

```powershell
$env:GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"
```

### YouTube Upload

Required for publishing clips:

```powershell
$env:YOUTUBE_PRIVACY_POLICY_URL    = "https://YOUR_GITHUB_PAGES_URL/privacy.html"
$env:YOUTUBE_EXPECTED_CHANNEL_ID   = "YOUR_YOUTUBE_CHANNEL_ID"  # optional but recommended
```

Place your Google Cloud OAuth Desktop JSON file at `credentials.json` in the project
root (excluded from version control). On first upload, a browser window opens to
authorize the channel. The token is then saved locally to `youtube-token.json`
(also excluded from version control).

> ⚠️ **Security:** `credentials.json` and `youtube-token.json` are listed in
> `.gitignore` and must never be committed to the repository.

---

## Usage

### List live English Twitch streams

```powershell
python -m twitch_auto_clipper --list-twitch-streams
python -m twitch_auto_clipper --list-twitch-streams --stream-limit 50
```

Streams are returned in descending viewer-count order (Twitch Helix default).

### Run one monitoring cycle

```powershell
python -m twitch_auto_clipper --monitor-twitch-once
```

Fetches current live streams, computes clip budgets, and acquires VODs for any streams
that have ended since the last run. Transcription and chat replay are collected
automatically after download.

### Run continuous monitoring

```powershell
python -m twitch_auto_clipper --monitor-twitch --monitor-interval 60
```

Polls Twitch every 60 seconds. Streams with a non-zero clip budget trigger automatic
VOD download, transcription, chat replay download, and Gemini highlight selection when
they end. State is persisted to `data/output/twitch_vod_state.json` to avoid
reprocessing.

### Generate a clip manually (time range)

```powershell
python -m twitch_auto_clipper video.mp4 30 45
python -m twitch_auto_clipper video.mp4 30 45 --output my-clip.mp4
python -m twitch_auto_clipper video.mp4 30 45 --subtitles data/output/video_transcript.json
```

Input file must be in `data/input/`. Output is written to `data/output/`.

### Generate a clip from a saved highlight candidate

```powershell
python -m twitch_auto_clipper --generate-from-candidate `
    --source data/input/video.mp4 `
    --candidate-json data/output/video_highlights.json `
    --candidate-index 0 `
    --transcript-json data/output/video_transcript.json `
    --before 5 `
    --after 5
```

### Run the Gemini auto-clip pipeline

Selects the best highlight candidate using Gemini and generates the clip directly:

```powershell
$env:GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"
python -m twitch_auto_clipper `
    --auto-clip `
    --candidates-json data/output/video_highlights.json `
    --transcript-json data/output/video_transcript.json `
    --source data/input/video.mp4 `
    --before 5 `
    --after 5
```

Optionally include chat context:

```powershell
    --chat-json data/input/VODID_chat.json `
    --chat-window 30
```

### Upload a clip to YouTube Shorts

```powershell
python -m twitch_auto_clipper `
    --upload-youtube `
    --video data/output/clip.mp4 `
    --title "Stream Highlight" `
    --description "Best moment from the stream." `
    --privacy private `
    --not-made-for-kids
```

The CLI asks for confirmation of upload rights and acceptance of the Privacy Policy
before uploading. Use `--privacy unlisted` or `--privacy public` to change visibility.

---

## Tests

```powershell
python -m pytest tests/ -q
```

All modules have unit tests under `tests/`. The test suite uses mocking for external
dependencies (Twitch API, Gemini, FFmpeg, yt-dlp).

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed description of all modules,
their responsibilities, and the data flow between pipeline stages.

---

## Public documentation (GitHub Pages)

Static pages for the project (Privacy Policy, Terms of Use, YouTube API usage) are in
`docs/` and served via GitHub Pages. To enable:

1. Go to **Settings → Pages** in the GitHub repository
2. Choose **Deploy from a branch**, select the default branch and the `/docs` folder
3. Save

The pages identify the owner as Aymeric Leclerre-Lemoine and link to the Aymeric05
GitHub repository. The site contains no OAuth credentials, API keys, or tokens.

---

## Roadmap

Planned work, in approximate priority order:

- **Multi-clip generation per VOD** — generate one clip per Gemini-selected candidate,
  up to the assigned clip budget, rather than just one clip.
- **Automated post-upload cleanup** — delete local VOD and clip files only after a
  successful YouTube upload confirmation, to avoid data loss on failure.
- **AI-generated metadata** — use Gemini to generate titles, descriptions, and tags
  for each Short automatically.
- **Instagram Reels publishing** — automated upload after YouTube.
- **TikTok publishing** — automated upload after YouTube.
- **Cloud deployment** — run the monitoring and processing pipeline on a server or
  cloud instance without requiring a local machine.