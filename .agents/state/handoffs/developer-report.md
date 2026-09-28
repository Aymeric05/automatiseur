# Developer Report

**Status:** complete
**Stage:** gemini_selection
**Task:** Audit and finish the Gemini VOD highlight selection pipeline; fix any bugs found in vod_highlights.py and gemini_evaluation.py; add missing test coverage for vod_highlights.

## Summary

A full audit of `vod_highlights.py` and `gemini_evaluation.py` was performed. One real bug was found and fixed: `select_candidates` was called with the raw `budget` argument instead of the pre-computed clamped `requested_count`, creating a single-source-of-truth violation. The accidental correctness was due to `evaluate_candidates` internally clamping `selection_count` to `min(selection_count, len(candidates))`, but the call site should use the already-correct clamped value. A comprehensive `test_vod_highlights.py` test file was created (12 tests) covering all scenarios requested in the audit.

## Files Changed

- `src/twitch_auto_clipper/vod_highlights.py` — Line 94: changed `requested_count=budget` → `requested_count=requested_count` (pass clamped count to `select_candidates`, not raw budget)
- `tests/test_vod_highlights.py` — **New file**: 12 tests covering all audited scenarios

## Design Decisions

- No changes were made to `gemini_evaluation.py` — the audit confirmed it is correct: `_parse_response` validates all fields, `evaluate_candidates` clamps expected count, duplicates are caught, and the structured response format is enforced.
- The fix in `vod_highlights.py` is minimal (one argument changed). The latent bug was masked by `evaluate_candidates`' internal clamping, so no behavioral regression was possible in practice, but the code violated single-source-of-truth.
- `test_vod_highlights.py` mocks `select_candidates` at the `vod_highlights` module level to keep tests fast and deterministic. The fake evaluations helper mirrors what Gemini would return given the clamped count.

## Audit Findings

| Item | Status | Notes |
|------|--------|-------|
| `requested_count` handling | **Fixed** | Line 94: was passing `budget` instead of `requested_count` |
| Gemini JSON response validation | ✅ Correct | `_parse_response` fully validates all fields |
| Exact number of selected candidates | ✅ Correct | `evaluate_candidates` + `_merge_selection` both enforce exact count |
| Distinct candidate IDs | ✅ Correct | Both layers check `len(set(ids)) == count` |
| Fewer candidates than budget | ✅ Correct | `evaluate_candidates` clamps to `min(selection_count, len(context))` |
| Resumability / existing selection JSON | ✅ Correct | `_load_valid_selection` validates all 7 fields before reuse |
| Manifest updates | ✅ Correct | Success writes `gemini_selection_files`, failure writes `gemini_selection_error` |
| Error handling | ✅ Correct | All error paths caught and returned as `status="error"` |

## Test Results

```
89 passed, 12 subtests passed in 0.90s
```

New tests (12):
- `test_selects_exactly_clip_budget_candidates`
- `test_selects_all_candidates_when_budget_exceeds_candidate_count` (also asserts `requested_count=2`, not `10`)
- `test_zero_budget_skips_gemini_and_returns_empty_selection`
- `test_merge_selection_raises_on_duplicate_candidate_ids`
- `test_existing_valid_selection_is_reused_without_calling_gemini`
- `test_mismatched_selection_json_triggers_fresh_gemini_call`
- `test_manifest_records_selection_file_path_on_success`
- `test_manifest_records_error_on_gemini_failure`
- `test_missing_transcript_returns_error_status`
- `test_saved_selection_has_valid_distinct_candidate_ids`
- `test_format_error_result`
- `test_format_completed_result`

## Next Step Recommendation

QA should run the full test suite and verify the `gemini_selection` stage is complete. The next pipeline stage to implement is `generate_shorts`.

## Blockers (if any)

None.

---

# Developer Report — 2026-09-27

**Status:** complete
**Stage:** generate_shorts → cleanup
**Task:** Connect Gemini selection, Shorts generation, metadata and YouTube upload to VOD processing.

## Summary
New `vod_pipeline.VODAutomationPipeline` chains the existing stages after VOD acquisition
(called from `cli.py` in place of the bare `VODProcessingPipeline.process`). Every stage stays
in its own module and remains resumable. Publishing is opt-in (`--auto-upload-youtube`), private only.

## Findings / Changes
- `vod_shorts.py`: centered frame 80 px wider than the tight crop with small black bars (no face
  focus: it cropped gameplay onto a corner facecam); ±5 s context via `calculate_candidate_bounds`;
  180 s cap; temp output + non-empty check; statuses completed/partial/failed/empty (all-failed
  was reported as partial); ASS subtitles burned from word timestamps; skip existing/uploaded
  Shorts; manifest keeps candidate timestamps, Gemini score and justification.
- `shorts_metadata.py` (new): title/description from the clip's real transcript + channel/VOD credit.
- `shorts_upload.py` (new): private upload via `youtube.upload_video`; local Short deleted only after
  a video ID is returned and recorded; failures/interruptions keep the file.
- `vod_pipeline.py` (new), `cli.py`: orchestration + `--auto-upload-youtube`.
- `pyproject.toml`: added google-genai, yt-dlp, faster-whisper; OpenCV moved to extra `framing`.
- Tests: test_vod_shorts, test_shorts_metadata, test_shorts_upload, test_vod_pipeline, +1 CLI test.

## Blockers
- TwitchDownloaderCLI missing from PATH on this machine (chat context unavailable, non-blocking).
- Not validated against a real VOD, real Gemini call or real YouTube upload.

## Validation pass — 2026-09-27 (evening)
- Added `--max-cycles` (bounded monitoring), resume of unfinished VODs at startup
  (`automation_status` in manifest + `find_unfinished_vods`), OAuth check at startup with
  `--auto-upload-youtube`, Ctrl+C exit code 130, known-VOD path kept in acquisition,
  cleaner metadata excerpts, rounded clip bounds.
- Real local E2E on a synthetic TTS video: faster-whisper, heuristics, FFmpeg Shorts with
  subtitles, metadata, manifest, resume after a simulated failed upload. Gemini and
  YouTube upload mocked (no GEMINI_API_KEY, no upload consent). No Twitch credentials.


## Pre-real-run fixes — 2026-09-27 (late)
- Stream end confirmed after 3 consecutive successful snapshots (end_confirmation_polls); API errors never count.
- Unavailable Twitch chat retried on later runs; valid chat/timestamps never re-downloaded.
- New `--check-config` (yes/no per integration, no secrets, no network).
- Missing on this machine: TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, GEMINI_API_KEY, YOUTUBE_PRIVACY_POLICY_URL, TwitchDownloaderCLI.

## Monitoring optimisation — 2026-09-28
- `fetch_english_streams(min_viewers=...)` stops after a full page below the lowest eligible
  viewer count (5,000); dedup kept. `fetch_live_streams_by_user_ids` checks missing tracked
  streams in batches of 100 user_id. Real cycle: ~1 s (was 240 s), ~200 streams scanned.
- Only eligible streams are tracked; concise console summary, `--verbose-streams` for detail.
- Ended-stream clip budget now uses the session peak viewers (`MonitoredStream.peak_viewers`), reset per stream_id.
