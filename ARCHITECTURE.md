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
| `twitch.py` | yt-dlp: VOD audio download, VOD video stream URL (for the Shorts) |
| `twitch_chat.py` | Downloads Twitch chat replay JSON via TwitchDownloaderCLI |
| `vod_acquisition.py` | Persistent queue of ended streams: VOD lookup, audio download, retries |
| `transcription.py` | Transcribes video using faster-whisper (CPU/int8, word timestamps) |
| `chat_activity.py` | Parses TwitchDownloaderCLI JSON; per-candidate chat summary for Gemini |
| `audio_events.py` | Laughter, screams, gasps found in the VOD audio (YAMNet ONNX) |
| `vod_processing.py` | Runs transcription, emotion detection and chat download once per VOD |
| `highlights.py` | Heuristic scoring of transcription segments as highlight candidates |
| `gemini_evaluation.py` | Sends candidates to Gemini API; parses and validates its JSON response |
| `vod_highlights.py` | Orchestrates heuristics → chat enrichment → Gemini selection per VOD |
| `vod_shorts.py` | Renders one vertical Short per selected moment (FFmpeg, subtitles) |
| `shorts_metadata.py` | Title and description from the clip's real transcript |
| `shorts_upload.py` | Publisher: reserve of the 30 best Shorts, uploads as soon as YouTube allows, cleanup |
| `vod_pipeline.py` | Chains all VOD stages; worker that processes the queued VODs |
| `candidate_clip.py` | Manual command: one vertical clip from a saved highlight candidate |
| `framing.py` | CPU face detection (OpenCV Haar cascade) for 9:16 crop positioning |
| `video.py` | FFmpeg command builder and executor for vertical clip output |
| `focus.py` | Where the important part of a screen-sharing stream is (Gemini, one request per VOD) |
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
twitch_monitor.py → MonitoringCycle (ended_streams[])     [monitoring thread]
    │
    ▼
vod_acquisition.py → persistent job queue (data/output/twitch_vod_state.json)
    │
    ▼  vod_pipeline.process_due_vods()                      [worker thread]
vod_acquisition.py → VODAcquisitionResult
    │   ├─ find_vod_for_stream() via twitch_api.py
    │   └─ download_twitch_vod(audio_only=True) via twitch.py + yt-dlp
    │       └─ data/input/<vod_id>_audio.<ext>
    ▼
vod_processing.py → VODProcessingResult
    │   ├─ transcribe_video() via transcription.py + faster-whisper
    │   │   └─ data/output/<vod_id>_transcript.json
    │   ├─ detect_emotions() via audio_events.py + onnxruntime (YAMNet)
    │   │   └─ data/output/<vod_id>_emotions.json
    │   ├─ download_twitch_chat() via twitch_chat.py + TwitchDownloaderCLI
    │   │   └─ data/output/<vod_id>_chat.json
    │   └─ manifest: data/output/<vod_id>_processing.json
    ▼
vod_highlights.py → VODHighlightSelectionResult
    │   ├─ analyze_transcription() via highlights.py   → heuristic candidates
    │   ├─ chat_spike_moments() via chat_activity.py   → moments the chat reacts to
    │   ├─ with_emotions()                             → laughter/scream moments, tags
    │   ├─ add_chat_signals() via chat_activity.py     → chat summary
    │   ├─ select_candidates() via gemini_evaluation.py → Gemini selection
    │   └─ data/output/<vod_id>_gemini_selection_<budget>.json
    ▼
vod_shorts.py → data/output/<vod_id>_<start>-<end>_short.mp4
    │   ├─ resolve_twitch_video_url() via twitch.py  → FFmpeg reads only these seconds
    │   └─ generate_ass_subtitles() via subtitles.py → burned subtitles
    ▼
shorts_metadata.py → title + description from the clip transcript
    ▼
vod_pipeline.py → completed: audio and chat files deleted, job closed
    ▼
cleanup_finished_vods() → once no Short of the VOD waits for publication, all its files go

Publisher thread (shorts_upload.py, publish_next): the reserve (ready Shorts of the
completed VODs) is ranked and kept to its 30 best: a standout streamer of
top_streamers.txt first, then the list, then the others, best Gemini score first. As soon
as YouTube allows uploads (at most 10 in any 24 hours), the best ones go out (youtube.py),
spread at random over one hour; after a refusal, it tries again an hour later.
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

JSON state files make every step resumable after a crash or a restart:

- **`data/output/twitch_monitor_state.json`** — written by `twitch_monitor.py` after
  each cycle: tracked live streams, their peak viewers and end-confirmation counters.
- **`data/output/twitch_vod_state.json`** — written by `vod_acquisition.py`: queued
  VOD jobs (attempts, next retry), completed and abandoned streams.
- **`data/output/<vod_id>_processing.json`** — the VOD manifest, written by every
  stage: transcript and chat status, Gemini selection, generated Shorts, metadata,
  YouTube uploads and errors, final `automation_status`.
- **`data/output/youtube_uploads.json`** — upload times of the last 24 hours, and the pause
  after a refusal.
- **`data/output/publication_hour.json`** — the current one-hour window the uploads are
  spread over.
- **`data/output/published_shorts.json`** — every published Short, what it was made of
  and its views (read every 6 hours, kept at 1, 3 and 7 days).

All files are written atomically (write to `.tmp`, then rename) to prevent corruption.
Shorts, metadata and uploads are keyed by the moment itself (`<start>-<end>` in seconds),
never by Gemini's `candidate_N` number, which changes with the candidate list.
A lock file (`data/output/.monitor.lock`) prevents two monitors on the same data.

---

## Vertical Framing

Automated Shorts: `focus.py` grabs one 360p frame per selected moment and asks Gemini
(`gemini-flash-lite-latest` first, one request per VOD) for the box of what matters on
screen; the crop window is shifted to its center (`focus_x` in the selection item).
Camera shots (full-frame webcam, IRL categories) and any failure keep a centered crop.

Manual clip commands: `framing.py` samples 5 evenly-spaced frames from the source video and runs OpenCV's
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
   excerpt with the surrounding context, and a compact chat summary (activity versus
   the surrounding minutes, laughs, repeated reactions, a few sample messages and a
   reliability flag).
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
| onnxruntime + YAMNet | `audiomagic/yamnet-onnx` from the Hugging Face cache (optional, graceful fallback) |
| OpenCV (`opencv-python-headless`) | Python API (optional, graceful fallback) |
| `google-genai` | Python API (`google.genai.Client`) |
| Google API Python Client | Python API (YouTube upload) |

All external dependencies are imported lazily and raise descriptive errors when missing,
so the rest of the pipeline remains functional.
