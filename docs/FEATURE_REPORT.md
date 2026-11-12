# WAV export, custom backgrounds and branding — completion report

Date: 2026-11-12, America/New_York. Work is local and uncommitted on `audit/portfolio-readiness-2026-11-11` in `A:\VOX-9K`. Starting/current HEAD: `742d2d7f87a65127197007bfb1dbf3c515facfd3`. The tree was clean at the start; 36 source files were copied to ignored evidence before edits. No commit, push, publication or installer build occurred.

## Implemented behavior

Download WAV beside Read/Pause/Stop exports the entire cleaned text with the selected voice/engine into one native-speed 1.0x mono 24 kHz/16-bit PCM WAV. Approximate duration/size and speed-adjusted listening estimates appear below the controls. After generation the UI reports measured native duration/actual file bytes and exposes Save WAV. Progress, cancellation, failures, concurrent export rejection and stale-job guards are included.

The upper-right picture icon opens Change Background; Restore default sits beside it. Content is decoded/validated, stripped of metadata, re-encoded and persisted atomically in per-user storage. The overlay and cover sizing remain. The exact footer text is now **Created by: Stelz Tools**; its CSS styling is unchanged.

See [EXPORT_AND_BACKGROUNDS.md](EXPORT_AND_BACKGROUNDS.md) for the complete formulas, limits, file locations and user flow.

## Architecture and bounds

The existing playback scripts, desktop/service ownership and engines remain. Flask adds asynchronous disk-backed export jobs. Kokoro chunks are decoded from WAV, including float WAV, using SoundFile; Qwen framed float32 PCM is validated and streamed to a single WAV writer. A 5 ms ramp applies only at text-chunk edges, leaving interior PCM-frame seams unchanged and preserving sample counts. No WAV-header concatenation, speed-adjusted export, resampling or inference replacement was added.

Kokoro retains its engine's existing waveform reuse. The sidecar now best-effort records complete native Qwen text chunks in a 128 MiB/30-minute disk cache (16 MiB/chunk limit), enabling export to reuse already generated playback PCM. Partial/stretched audio is not reused. Cache I/O is outside the critical model cleanup state transition; generation ownership is cleared before releasing the model lock. An export request cannot cancel an active Qwen read. Existing playback can supersede an export, which then fails cleanly.

Within one window, finish/Stop Read before export; Read is disabled while exporting. Separate windows can still contend for Kokoro; avoid concurrent generation there. Jobs have 20,000-character, 256-chunk, 96 MiB and cooperative 30-minute bounds, plus a two-minute client lease. Ready outputs expire after ten minutes, with cleanup every 30 seconds. Open Windows downloads defer deletion until the file closes. Inference cancellation remains cooperative. CLI shutdown signals cancellation before interpreter teardown; a non-daemon worker finishes its current native step before cached engines close. Desktop ownership shutdown retains its existing bounded process termination. No whole-document PCM accumulation is introduced; one Kokoro chunk is still decoded at a time.

Background limits are 8 MiB upload, 8192 pixels/side, 16 MP decoded pixels and 32 MiB encoded output. PNG/JPEG/WebP still images are supported; active/unsupported/animated/truncated data is rejected. Default Windows storage is `%LOCALAPPDATA%\VOX-9K\background.png`; `VOX_DATA_DIR` permits isolated test storage. Temporary WAV/cache paths are under ignored `temp/`. Custom images never replace the tracked artwork. JSON requests retain 64 KiB limits; only image POST uses a larger bound.

Estimates use max(word count, non-whitespace characters/6), 170 words/min Kokoro or 150 Qwen, and WAV bytes = 44 + round(native seconds x 24000) x 2. Listening estimate divides by playback speed; exported audio remains 1.0x. These are approximate English-oriented heuristics, not known audio duration. Final metrics come from actual samples/file length.

## Automated verification

Baseline: **135 passed** (86 Python + 49 frontend).

Final: **172 passed, 0 failed, 0 skipped** (112 Python + 60 frontend). New checks cover WAV format, ordering, rates, finite PCM, seams, measured metrics, long/multiple chunks, cancellation/failure/limits/leases, cleanup including Windows open files, cache reuse, Qwen export/playback ownership, input snapshots, stale UI callbacks, estimator behavior, invalid/large raster uploads, persistence/restore and localhost guards.

The original regression suite is preserved, including WSOLA continuity and one-buffer-ahead scheduling tests. Direct function comparison against the starting snapshot confirms the accepted stretch, scheduler and highlight-promotion functions are byte-identical. Original background/screenshot/LICENSE/fast requirements are unchanged. Python syntax and Git whitespace checks pass.

Run:
```powershell
Set-Location 'A:\VOX-9K'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v
node --test tests\frontend.test.cjs
```

## Real local audio and graphical verification

These checks are separate from model-free test counts:

| Check | Actual result |
| --- | --- |
| Native Kokoro Sarah complete WAV | 2 text chunks; 14.10 seconds; 676,844 bytes; mono 24 kHz/16-bit; valid full response. |
| Native Qwen Ryan complete WAV | 2 text chunks; 13.04 seconds; 625,964 bytes; exactly 312,960 samples reused from completed playback PCM. |
| Fresh browser Qwen Aiden export | Reached Ready using uncached synthesis; estimated/actual values displayed separately, native 1.0x despite 1.5x listening setting. |
| Actual WebView2 attachment saving | Downloaded the real Ryan WAV, with the Save dialog's destination selection stubbed to an ignored file. Suggested filename VOX-9K-Recording.wav; saved file was byte-identical (625,964 bytes). |
| Browser attachment saving | Connector timed out on both download-event and downloadMedia attempts. No claim that a user completed a browser Save dialog. |
| Background | JPEG selected through actual file chooser; custom image survived page reload; restore-default visibly returned original art. Two separate model-free backend launches additionally proved persisted PNG bytes survived process restart and exact default bytes were restored. |
| Existing native controls | Real Kokoro/Qwen Read/Pause/Resume/Stop, cancellation then voice change, return to Kokoro, 1.2/1.5x speed, volume, completion, branding and native window startup/shutdown passed. |
| Owner listening | Owner heard the complete two-chunk Ryan WAV and answered **“Complete and sounds natural.”** |
| Lifecycle | Successful native run exited 0 with no owned service processes remaining. Isolated restart services also exited 0. |

Models were already installed and used with HF_HUB_OFFLINE=1. No models or inference upgrades were downloaded. The first native attempt had a harness-only false timeout: an AudioNode serialized as an empty object instead of a Boolean. Correcting the predicate allowed the full repeat to pass; production playback needed no corresponding change.

The UI was visually inspected at normal browser size. The final preview is local: `audit/features-2026-11-12/browser-features.jpg`. Actual dialogs, default Brave and additional display/DPI configurations still require owner manual acceptance. Browser/native attachment transport is distinct from file-dialog interaction.

## Known limitations and performance

Export uses one serial background generation job, not simultaneous synthesis/playback in the same window. The worker keeps HTTP status/image actions available while generating. No controlled CPU/TTFA benchmark was run; no universal latency or memory claim is made. Native PCM cache recording adds bounded disk I/O per received frame. Long exports use disk rather than a document-sized RAM buffer; image decoding can transiently hold multiple bounded pixel arrays. Existing Qwen playback can still queue PCM during prolonged pauses; this pass does not redesign that behavior.

Native-speed PCM16 export quantizes float audio and applies tiny text-edge ramps. No speed-adjusted waveform export or paragraph-specific alignment is claimed. Estimation varies by voice/language; 20,000 characters or JSON-byte limits can reject large input. Page closure/cancellation cannot interrupt a native operation mid-step. Ready files/links expire; an expired link requires regeneration. Another already-open window sees a changed background on reload. Backgrounds are shared per backend/user, not per browser tab.

Remaining owner checks: click through the physical Windows Save dialog and normal browser download flow; listen to additional voices/passages if desired. Ryan listening acceptance is scoped to the exported recording. Existing Kokoro CUDA, clean-machine setup, Mac desktop and future installer limitations remain documented.

## Exact files

Modified:
- `.gitignore`
- `README.md`
- `desktop.py`
- `index.html`
- `qwen_fast_server.py`
- `server.py`
- `requirements.txt`
- `requirements-gpu.txt`
- `requirements-test.txt`
- `tests/frontend.test.cjs`
- `tests/test_desktop.py`
- `docs/RUNNING.md`
- `docs/TESTING.md`
- `docs/THIRD_PARTY_NOTICES.md`

Added:
- `audio_export.py`
- `backgrounds.py`
- `chunk_cache.py`
- `features.js`
- `tests/test_features.py`
- `docs/EXPORT_AND_BACKGROUNDS.md`
- `docs/FEATURE_REPORT.md`

Pillow 12.3.0 and SoundFile 0.14.0 were already installed; they are now explicit requirements. Their licenses are recorded in THIRD_PARTY_NOTICES. Existing inference requirements, model weights, artwork and original license remain intact.

All baseline copies, diagnostic scripts/results, images and generated WAVs stay local under ignored `audit/features-2026-11-12/`; runtime outputs/cache are ignored under `temp/`. No private source text, cloud upload or telemetry was introduced.

## Launch and final Git state

Fresh PowerShell:
```powershell
Set-Location 'A:\VOX-9K'
.\.venv\Scripts\python.exe desktop.py
```
Browser mode instead:
```powershell
Set-Location 'A:\VOX-9K'
.\.venv\Scripts\python.exe server.py
```
Open http://127.0.0.1:5000 for browser mode. If reusing a diagnostic shell, remove VOX_SKIP_WARMUP and VOX_DISABLE_QWEN. The current environment already contains the decoder dependencies.

Branch/HEAD remain unchanged; index is untouched. All files above remain modified/untracked for owner review. Nothing was committed, pushed or published.
