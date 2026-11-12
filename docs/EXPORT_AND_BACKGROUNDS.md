# WAV export and custom backgrounds

## Download WAV

Enter the full text, select engine/voice/compute and click **Download WAV**. After generation click **Save WAV**, or Download WAV again, to save `VOX-9K-Recording.wav`.

Export is native **1.0x synthesis speed**, regardless of the interactive speed/volume sliders. It produces one uncompressed RIFF/WAVE file: mono, 24,000 Hz, signed 16-bit PCM. Engine/voice/compute and the entire cleaned chunk sequence are captured when export starts. Editing the input/settings requires a new export; changing speed alone does not regenerate a native-speed file.

Finish or Stop playback before exporting in the same window. Read is disabled during generation; **Cancel export** releases it. Pause/Stop remain playback controls. Background changes do not stop speech. Only one export generates per backend. Qwen export refuses to supersede another window's active generation. New Qwen playback in another window can supersede an export, which fails cleanly instead of cancelling playback. Avoid concurrent Kokoro generation across separate windows.

Before generation, estimates use actual cleaned input and selected engine:

- Effective words = maximum of whitespace-delimited words and non-whitespace characters / 6.
- Kokoro: 170 effective words/minute; Qwen: 150 effective words/minute.
- Native duration = effective words x 60 / rate; listening duration = native duration / playback speed.
- WAV bytes = 44 + round(native seconds x 24000) x 2.
- KB/MB labels use 1024/1024-squared byte units.

These are approximate heuristics. Voice, language, punctuation and model variation can make them inaccurate. After generation, duration is actual PCM sample count / 24000 and size is the completed file's byte length. Final values describe the native-speed WAV.

## Audio and resource behavior

A background worker incrementally writes one WAV. Kokoro WAV chunks, including float WAV, are decoded; Qwen framed float32 PCM is validated. Standalone WAV headers are never concatenated. Unexpected rate/channel formats are rejected. PCM is clipped to its valid range and quantized to 16-bit.

Incoming Qwen PCM-frame seams are untouched. Only the first/last 120 samples (5 ms) of each generated text chunk are ramped to/from zero to reduce concatenation clicks. No samples or synthetic pauses are added/dropped. Existing generated pauses remain; no exact paragraph-timing claim is made.

Kokoro retains existing synthesizer waveform reuse. Completed native Qwen chunks are recorded under `temp/qwen-audio-cache/`, keyed by a SHA-256 of text/voice/format. Matching complete playback chunks can be reused for export. Stretched playback PCM and interrupted chunks are not cached. The opportunistic cache expires after 30 minutes, is bounded to 128 MiB total and refuses chunks above 16 MiB. Recording is best effort; cache failure must not break playback.

Limits: 20,000 cleaned characters, 256 chunks maximum, 3,000 characters/chunk, one generating job, eight retained jobs, 96 MiB WAV maximum and 30-minute generation time checked between frames/chunks. The existing 64 KiB JSON-body cap can reject multibyte input before the character limit.

Temporary output is `temp/exports/<random-job-id>.wav`. The whole document is not accumulated in a RAM array. Failed/cancelled partial files are removed when the worker unwinds. Ready files expire after ten minutes; cleanup checks every 30 seconds and removes stale feature-owned files after restart. A generating job without a status heartbeat for two minutes is cancelled at the next cleanup pass. Page close requests cancellation. Lost create-responses cannot be cancelled immediately but the lease bounds abandonment. Cancellation/time limits cannot interrupt a running native inference step. Browser-mode Ctrl+C cancels the export and waits for the in-flight worker step before engine teardown; desktop ownership shutdown retains its existing bounded process-exit behavior. Closing an owning desktop closes its services; crash leftovers are cleaned subsequently.

Browser saving uses the ordinary attachment/download mechanism and browser preferences. Windows desktop enables pywebview/WebView2's Save dialog handler. No endpoint accepts a destination path. Ready downloads can be repeated until expiry; expired links require regeneration.

## Change Background

The upper-right picture button has tooltip/screen-reader label **Change Background** and opens the normal file picker. **Restore default** is the Restore Default Background action.

Pillow decodes actual PNG/JPEG/WebP content; extensions/MIME types are not trusted. SVG, GIF, malformed/truncated files and animated images are rejected. Limits: 8 MiB upload, 8192 pixels/side, 16 million pixels, 32 MiB re-encoded PNG. EXIF orientation is applied. Transparency is composited over the dark base. Re-encoding drops metadata and appended content.

The custom PNG is stored per user:

- Windows: `%LOCALAPPDATA%\VOX-9K\background.png`.
- Other source-mode systems: `$XDG_DATA_HOME/VOX-9K/background.png`, falling back to `~/.local/share/VOX-9K/background.png`.
- Optional `VOX_DATA_DIR` overrides the directory for isolated diagnostics.

Atomic persistence survives backend/browser/desktop restarts. Windows sharing a backend/user share the preference; already-open other windows refresh it on reload. Restore removes only the custom file and falls back to the tracked default. The original tracked background/screenshot are unchanged. Dark overlay, cover, centering and fixed-background behavior remain.

Images are sent only to loopback, never external services. No base64 localStorage or arbitrary file-path endpoint exists. Existing Host/Origin/fetch-site rules apply. Only the binary background POST has the larger body limit. This is per-user local storage, not a new authentication system.

Pillow 12.3.0 and SoundFile 0.14.0 were already installed and are now declared in CPU/GPU/test requirements. No inference dependency was upgraded. Clean installations need these decoding packages; optional desktop and fast-Qwen stacks remain separate.

## Branding and verification

The footer is now **Created by: Stelz Tools**, with its existing size, opacity, position, color and spacing unchanged. See [FEATURE_REPORT.md](FEATURE_REPORT.md) for exact tests, real export results and remaining owner acceptance.

## Windows Security observation

An owner-supplied notification and a narrowly scoped event-log check identified **Controlled Folder Access** blocking **msedgewebview2.exe** from modifying **%USERPROFILE%\Favorites** at 12:45 PM on 2026-11-12. This identifies the warning category and blocked operation, not the exact picker/profile operation that initiated it. It is separate from VOX-9K's background storage under Local AppData.

Repeated owner attempts no longer reproduced the warning. Its disappearance is not claimed as a code fix. The background implementation and all Windows security protections remain unchanged. If it recurs, stop that background-selection attempt, keep the block in place, and record the exact message, time and stage (opening picker, selecting, saving/applying, restoring or restarting). VOX-9K does not require write access to Favorites; no automatic exclusion, broad application allowance or policy change is recommended. Continue using the existing/default background while the operation is investigated.

See [PASTE_SECURITY_REPORT.md](PASTE_SECURITY_REPORT.md) for evidence and limits.
