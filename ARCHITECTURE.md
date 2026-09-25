# Architecture

This document describes the module structure and data flow of the Twitch Auto Clipper
pipeline. Each section maps to an implemented component in `src/twitch_auto_clipper/`.

---

## Module Map

| Module | Responsibility |
|---|---|
| `twitch_api.py` | Twitch Helix REST client: stream discovery, VOD lookup, app-token auth |
| `clip_budget.py` | Maps viewer count to a clip count using a tiered policy |
| `twitch_monitor.py` | Polls live streams, tracks new/ended streams and viewer changes |
| `twitch.py` | Downloads Twitch VODs via yt-dlp |
| `twitch_chat.py` | Downloads Twitch chat replay JSON via TwitchDownloaderCLI |
| `vod_acquisition.py` | Orchestrates VOD download per ended stream, with dedup state file |
| `transcription.py` | Transcribes video using faster-whisper (CPU/int8, word timestamps) |
| `chat_activity.py` | Parses TwitchDownloaderCLI JSON; enriches candidates with chat counts |
| `vod_processing.py` | Runs transcription + chat download once per acquired VOD |
| `highlights.py` | Heuristic scoring of transcription segments as highlight candidates |
| `gemini_evaluation.py` | Sends candidates to Gemini API; parses and validates its JSON response |
| `vod_highlights.py` | Orchestrates heuristics → chat enrichment → Gemini selection per VOD |
| `candidate_clip.py` | Generates one vertical clip from a saved highlight candidate |
| `framing.py` | CPU face detection (OpenCV Haar cascade) for 9:16 crop positioning |
| `video.py` | FFmpeg command builder and executor for vertical clip output |
| `subtitles.py` | Generates ASS subtitle files from word-level timestamps |
| `youtube.py` | YouTube Data API v3 upload with OAuth 2.0 (Desktop flow) |
| `cli.py` | Main CLI entry point (`tac` / `python -m twitch_auto_clipper`) |

---

## Pipeline Data Flow

```
Twitch Helix API
    │
    ▼
twitch_api.py → LiveStream[]
    │
    ▼
clip_budget.py → clip_count (int)   ← viewer count tiers
    │
    ▼
twitch_monitor.py → MonitoringCycle (ended_streams[])
    │
    ▼
vod_acquisition.py → VODAcquisitionResult
    │   ├─ find_vod_for_stream() via twitch_api.py
    │   ├─ download_twitch_vod() via twitch.py + yt-dlp
    │   └─ state: data/output/twitch_vod_state.json
    │
    ▼
vod_processing.py → VODProcessingResult
    │   ├─ transcribe_video() via transcription.py + faster-whisper
    │   │   └─ data/output/<vod_id>_transcript.json
    │   ├─ download_twitch_chat() via twitch_chat.py + TwitchDownloaderCLI
    │   │   └─ data/output/<vod_id>_chat.json
    │   └─ manifest: data/output/<vod_id>_processing.json
    │
    ▼
vod_highlights.py → VODHighlightSelectionResult
    │   ├─ analyze_transcription() via highlights.py   → heuristic scores
    │   ├─ add_chat_messages() via chat_activity.py    → chat enrichment
    │   ├─ select_candidates() via gemini_evaluation.py → Gemini selection
    │   └─ data/output/<vod_id>_gemini_selection_<budget>.json
    │
    ▼
candidate_clip.py → MP4 clip in data/output/
    │   ├─ generate_ass_subtitles() via subtitles.py → .ass file
    │   └─ create_vertical_clip() via video.py + FFmpeg
    │       └─ build_vertical_filter() via framing.py + OpenCV
    │
    ▼
youtube.py → YouTube Shorts upload (manual trigger via CLI)
```

---

## Clip Budget Policy

`clip_budget.py` defines a configurable tier policy. The default:

| Minimum viewers | Clip budget |
|---|---|
| 100,000+ | 20 |
| 50,000+ | 15 |
| 20,000+ | 10 |
| 10,000+ | 5 |
| 5,000+ | 2 |
| < 5,000 | 0 (skipped) |

Streams with a budget of 0 are not downloaded.

---

## State and Deduplication

Two JSON state files prevent reprocessing:

- **`data/output/twitch_vod_state.json`** — written by `vod_acquisition.py`.
  Maps stream IDs to VOD IDs that have already been downloaded.
- **`data/output/<vod_id>_processing.json`** — written by `vod_processing.py`
  and `vod_highlights.py`. Tracks which processing steps are complete for each VOD.

Both files are written atomically (write to `.tmp`, then rename) to prevent corruption.

---

## Vertical Framing

`framing.py` samples 5 evenly-spaced frames from the source video and runs OpenCV's
Haar cascade face detector on each. If faces are detected, the 9:16 crop window is
shifted horizontally to center on the largest detected face. If OpenCV is unavailable,
not installed, or no faces are detected, a centered crop is used as fallback.

---

## Subtitle Format

`subtitles.py` produces `.ass` (Advanced SubStation Alpha) subtitle files from
word-level timestamps produced by faster-whisper. Words are grouped into blocks of
up to 4, with each block displayed for the duration of its words. The `.ass` file
is burned into the clip by FFmpeg using the `subtitles=` filter.

---

## Gemini Integration

`gemini_evaluation.py` uses the `google-genai` Python SDK. It:

1. Builds a prompt with each candidate's heuristic score, time range, transcript
   excerpt, and chat message count and details.
2. Calls the Gemini API with a structured JSON response schema.
3. Validates the response against the expected candidate IDs, score ranges, and format.
4. Returns scored evaluations sorted by score descending.

The `select_candidates()` function is used for multi-candidate selection (N clips per
VOD budget). The `select_candidate()` function selects a single best candidate (used
by `--auto-clip`).

---

## YouTube Upload

`youtube.py` uses the Google API Python Client with OAuth 2.0 (Desktop flow):

1. On first use, opens a local browser for channel authorization.
2. Saves the OAuth token to `youtube-token.json` (excluded from version control).
3. On subsequent calls, reloads and refreshes the token automatically.
4. Optionally verifies that the authenticated channel matches `YOUTUBE_EXPECTED_CHANNEL_ID`
   before uploading.
5. Uses resumable `MediaFileUpload` for reliability on large files.

The CLI requires explicit confirmation of upload rights and acceptance of the Privacy
Policy URL before any upload proceeds.

---

## External Dependencies

| Dependency | How it is invoked |
|---|---|
| FFmpeg / FFprobe | `subprocess.run()` (must be in `PATH`) |
| yt-dlp | Python API (`yt_dlp.YoutubeDL`) |
| TwitchDownloaderCLI | `subprocess.run()` (must be in `PATH`) |
| faster-whisper | Python API (`faster_whisper.WhisperModel`) |
| OpenCV (`opencv-python-headless`) | Python API (optional, graceful fallback) |
| `google-genai` | Python API (`google.genai.Client`) |
| Google API Python Client | Python API (YouTube upload) |

All external dependencies are imported lazily and raise descriptive errors when missing,
so the rest of the pipeline remains functional.
