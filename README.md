# Twitch Auto Clipper

An automated pipeline that discovers live Twitch streams, monitors them for viewer
activity, acquires their VODs once they end, transcribes them, collects Twitch chat
replay data, identifies potential highlight moments with heuristics, and uses Gemini
to select the best candidates for vertical short-form video clips.

> **Status:** The full pipeline — from live discovery to private YouTube Shorts publication
> with post-upload cleanup — is implemented and covered by unit tests (external services
> mocked). Each stage has been run for real on a 10-minute VOD extract, except the YouTube
> upload itself, which has not been run for real yet. Publishing to Instagram Reels /
> TikTok is planned but not yet implemented.

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
| Face-aware horizontal framing (OpenCV, manual clip commands only) | ✅ Implemented |
| ASS subtitle generation from word-level timestamps | ✅ Implemented |
| Manual YouTube Shorts upload | ✅ Implemented |
| Automated multi-clip Shorts generation per VOD (clip budget, dynamic subtitles) | ✅ Implemented |
| Titles and descriptions from the clip's real transcript | ✅ Implemented |
| Automatic private YouTube upload (`--auto-upload-youtube`) | ✅ Implemented |
| Automatic post-upload local file cleanup | ✅ Implemented |
| Instagram Reels publishing | 🔲 Planned |
| TikTok publishing | 🔲 Planned |
| Cloud / always-on deployment | 🔲 Planned |

---

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) (must be in `PATH`)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — for VOD download
- [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader) — for chat replay
  (in `tools/TwitchDownloaderCLI/` or in `PATH`)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — for transcription
- `google-genai` Python package — for Gemini evaluation
- `opencv-python-headless` — optional, face-aware framing for the manual clip commands
  (`pip install -e .[framing]`); automated Shorts always use a centered frame
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

The base install covers the whole pipeline (yt-dlp, faster-whisper, google-genai and the
YouTube API clients). FFmpeg must be installed separately and be in `PATH`.
TwitchDownloaderCLI is looked up in `tools/TwitchDownloaderCLI/` first, then in `PATH`.
For face-aware framing in the manual clip commands:

```powershell
python -m pip install -e .[framing]
```

---

## Configuration

All credentials are read from environment variables. **Never hardcode secrets.**
They can also be written as `KEY=value` lines in a `.env` file at the project root
(ignored by git, read from the current directory at startup); a variable already set in
the environment always takes precedence over `.env`.

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

Each VOD needs one Gemini request. On the free tier, flash models often answer "503 high
demand" to real-size requests: the configured model (`--gemini-model`, default
`gemini-3.6-flash`) is tried first, then `gemini-flash-latest`, then
`gemini-flash-lite-latest`. The application stays within the free tier: at most
`GEMINI_MAX_REQUESTS_PER_DAY` requests per model and per quota day (default 20; failed
requests count). When every model is overloaded the VOD waits 30 minutes; when every model
has reached its daily limit, it waits for the next quota day (08:00 UTC), the most watched
streams first. Neither counts as a failure.

### YouTube Upload

Required for publishing clips:

```powershell
$env:YOUTUBE_PRIVACY_POLICY_URL    = "https://aymeric05.github.io/automatiseur/privacy.html"
$env:YOUTUBE_EXPECTED_CHANNEL_ID   = "YOUR_YOUTUBE_CHANNEL_ID"  # optional but recommended
$env:YOUTUBE_MAX_UPLOADS_PER_DAY   = "6"  # optional, default 6
$env:YOUTUBE_PRIVACY               = "private"  # optional: private (default), unlisted or public
```

`YOUTUBE_PRIVACY` sets the visibility of automatic uploads. As long as YouTube has not
audited the API project, it keeps every upload private whatever this value.

`YOUTUBE_MAX_UPLOADS_PER_DAY` caps automatic uploads per YouTube quota day (the default
10,000-unit daily quota allows about six uploads). Beyond it, Shorts stay on disk and are
uploaded after the next quota reset (08:00 UTC is used, which is after YouTube's midnight
Pacific reset all year). A quota refusal from YouTube also closes the day early.

Place your Google Cloud OAuth Desktop JSON file at `credentials.json` in the project
root (excluded from version control). On first upload, a browser window opens to
authorize the channel. The token is then saved locally to `youtube-token.json`
(also excluded from version control).

> ⚠️ **Security:** `credentials.json` and `youtube-token.json` are listed in
> `.gitignore` and must never be committed to the repository.

---

## Usage

### Check the configuration

```powershell
python -m twitch_auto_clipper --check-config
```

Prints `oui`/`NON` for each integration (Twitch, Gemini, FFmpeg, TwitchDownloaderCLI,
YouTube). Secret values are never printed and nothing is uploaded.

### List live English Twitch streams

```powershell
python -m twitch_auto_clipper --list-twitch-streams
python -m twitch_auto_clipper --list-twitch-streams --stream-limit 50
```

Streams are returned in descending viewer-count order (Twitch Helix default).

### Process one finished VOD

```powershell
python -m twitch_auto_clipper --process-vod https://www.twitch.tv/videos/VODID --clip-budget 2
python -m twitch_auto_clipper --process-vod VODID --clip-budget 2 --test-minutes 10
```

Runs the whole pipeline on one VOD without monitoring, and never uploads. A VOD whose
stream is still live is refused. Only the VOD audio is downloaded (for the transcription);
each Short then reads its few seconds of video straight from Twitch. With
`--test-minutes N`, only the first N minutes (audio and chat) are used and everything is
written to `data/test/`, separate from production data. An audio file already downloaded
for this VOD is reused.

### Run one monitoring cycle

```powershell
python -m twitch_auto_clipper --monitor-twitch-once
```

Fetches current live streams, queues the streams that have ended, then processes the VOD
jobs that are due (see below) before exiting.

### Run continuous monitoring

```powershell
python -m twitch_auto_clipper --monitor-twitch --monitor-interval 60
```

Polls Twitch every 60 seconds. Only streams with a non-zero clip budget (5,000+ viewers by
default) are listed and tracked, so a cycle takes about a second. A tracked stream missing
from the list (for example after dropping below 5,000 viewers) is checked directly with
Twitch; it is considered ended only after three consecutive successful offline checks
(failed API calls do not count). The clip budget of an ended stream is computed from
the highest viewer count reached during that live session (a relaunch with a new stream ID
starts a new session). Output is a per-cycle summary; add `--verbose-streams`
to list every tracked stream and viewer change.

When a stream with a non-zero clip budget ends, it is added to a persistent queue and a
separate worker processes it, so a long VOD never pauses the monitoring: the VOD audio
is downloaded (about 70 MB per hour, never the multi-GB video), transcribed, its chat
replay collected, highlight candidates detected, the best moments selected by Gemini
within the clip budget, and one vertical Short with dynamic subtitles rendered per
selected moment (`data/output/<vod>_<start>-<end>_short.mp4`), reading only those
seconds of video from Twitch. Once a VOD is completed, its audio and chat files are
deleted; transcript, selection, manifest and unpublished Shorts are kept.

Nothing is lost when the program stops: tracked streams and their peaks
(`data/output/twitch_monitor_state.json`) and queued VODs
(`data/output/twitch_vod_state.json`) are saved, and every step is resumable from
`data/output/<vod>_processing.json`. A failed VOD is retried automatically (after 5, 10,
20... minutes, up to 6 hours apart) and abandoned after 8 failures, its files kept; a VOD
that Twitch never publishes is abandoned after 24 hours. Only one monitor can run on the
same data at a time. A download never starts with less than 2 GB of free disk space.

To also publish the Shorts automatically, add `--auto-upload-youtube`:

```powershell
python -m twitch_auto_clipper --monitor-twitch --auto-upload-youtube
```

Upload rights and the Privacy Policy are confirmed, and YouTube OAuth is checked, once at
startup. Shorts are uploaded
as **private** (or as set by `YOUTUBE_PRIVACY`), with a title and description built from
what is actually said in the clip,
within the daily upload limit (`YOUTUBE_MAX_UPLOADS_PER_DAY`). A local Short is deleted only
after YouTube confirms the upload with a video ID; on any failure or interruption it is
kept for a retry. Transcripts and manifests are never deleted.

The console output can be redirected to a log file: it is then written in UTF-8.

### Automatic start at Windows logon

`start_monitor.cmd` runs the monitoring with automatic uploads and appends its
output to `data/output/monitor.log`. The Windows task "Twitch Auto Clipper" (Task
Scheduler, trigger "At log on", 2-minute delay) starts it minimized. `--yes` gives the
upload-rights and Privacy Policy confirmations in advance, since nobody is at the keyboard.
Nothing runs while the computer is off or asleep: streams tracked before are picked up
again at the next start, streams that start and end in between are missed.

### Bounded run (testing)

```powershell
python -m twitch_auto_clipper --monitor-twitch --max-cycles 3 --monitor-interval 30
```

Stops after three polling cycles. Without `--max-cycles` the monitoring runs until Ctrl+C.
A VOD still being processed at that moment is picked up again at the next start; finished
steps are reused. Ctrl+C never deletes unpublished Shorts.

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

- **Richer metadata** — optionally let Gemini rephrase titles from the clip transcript.
- **Instagram Reels publishing** — automated upload after YouTube.
- **TikTok publishing** — automated upload after YouTube.
- **Cloud deployment** — run the monitoring and processing pipeline on a server or
  cloud instance without requiring a local machine.