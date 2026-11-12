# Qwen accelerated playback investigation — 2026-11-12

Two reproduced defects were corrected while retaining the existing WSOLA, streaming protocol, engines and desktop architecture. The owner compared the same Aiden recording at 1.5x and answered **“Popping gone; speech sounds natural.”** This acceptance applies to that sample; other voices/passages still require listening judgment.

## Diagnosis and history

The strongest supported diagnosis is WSOLA output-tail truncation, compounded by callback scheduling gaps.

The old loop cropped its last aligned frame at the target output length. The resulting endpoint could differ substantially from the true PCM endpoint. The next independently stretched buffer began at the true next input sample, producing a repetitive seam discontinuity. The old scheduler also waited for an ended callback, processed the next buffer on the main thread, then called start without a scheduled time.

**A recent regression is not confirmed.** Preserved pre-audit, runtime and pre-UI snapshots have identical WSOLA function hashes. Their scheduling functions are identical after excluding the later guarded highlighting call. Older backup/public HEAD sources have no comparable Qwen implementation. The defect predates these audit/UI passes; available history cannot establish its exact introduction date.

Checkout: `A:\VOX-9K`. Branch: `audit/portfolio-readiness-2026-11-11`. HEAD unchanged: `733268d2e31a65de5f58ba96a4f91bd0ef71c824`. Starting source/status/hash copies were preserved in ignored `audit/audio-popping-2026-11-12/`.

## Exact correction

`index.html` now anchors its final synthesis frame to the actual input tail with a cosine overlap reaching full tail weight, rather than truncating an ordinary shifted frame. It returns the rounded target length and preserves the original first/final samples. Settings remain 1024 frame, 512 overlap/synthesis hop, 96-sample search radius and four-sample search stride. No cross-buffer history or new DSP dependency was introduced.

Playback schedules at most two sources: current and one ahead. The next start uses the preceding scheduled end on the AudioContext clock. Late data starts at the present time; missing audio is not concealed. Production playbackRate remains 1; only WSOLA adjusts speed. Newly prepared frames use the latest speed.

Read highlighting advances when a source becomes current, not when its successor is scheduled. Cleanup stops both nodes, removes handlers and clears the timeline. AudioContext suspension preserves pause/resume; completion waits for the final scheduled source.

Timed starts use the documented [AudioBufferSourceNode.start(when) API](https://developer.mozilla.org/en-US/docs/Web/API/AudioBufferSourceNode/start). No gain fades, permanent resampling pitch shift, inference change, framework or dependency was added.

## Controlled real-PCM measurements

Cached optimized Qwen generated one fixed, nonsensitive English passage per voice. Every later comparison reused those exact float32 mono 24 kHz frames, eliminating generation variability.

Aiden: 257,280 samples, 10.72 seconds, 17 buffers. Ryan: 322,560 samples, 13.44 seconds, 21 buffers. Typical incoming buffer length: 15,360 samples. Passage, exact frame sizes and arrival times are in `capture.json`. The existing offline cache was used without downloads.

Largest absolute adjacent-sample jump at incoming PCM seams, in normalized float amplitude:

| Voice | Speed | Raw maximum | Before | Corrected |
| --- | ---: | ---: | ---: | ---: |
| Aiden | 1.0 | 0.067017 | 0.067017 | 0.067017 |
| Aiden | 1.2 | 0.067017 | 0.444332 | 0.067017 |
| Aiden | 1.5 | 0.067017 | 0.808594 | 0.067017 |
| Aiden | 1.8 | 0.067017 | 0.603516 | 0.067017 |
| Ryan | 1.0 | 0.052246 | 0.052246 | 0.052246 |
| Ryan | 1.2 | 0.052246 | 0.281740 | 0.052246 |
| Ryan | 1.5 | 0.052246 | 0.193115 | 0.052246 |
| Ryan | 1.8 | 0.052246 | 0.428711 | 0.052246 |

A continuous 223 Hz sine independently reproduced the defect: raw seam maximum 0.028469, legacy 1.5x 0.979527, corrected 1.5x 0.028469. Corrected internal adjacent-sample deltas stay below 0.035 in the sine regressions, including slower and noninteger speeds.

These checks establish removal of an added seam jump, not universally perfect speech. Raw speech naturally has larger internal derivatives. Captured raw peaks were 0.6914/0.6641, without clipping or invalid values; corrected samples remain bounded by input amplitude. The source rate remains 24 kHz and normal device-rate conversion is unchanged. There is no evidence here that model generation, decoding, clipping or a sample-rate mismatch caused the speed-dependent defect.

## Scheduling, pitch, duration and performance

Actual native WebView2/AudioContext probes with recorded data already queued:

| Probe | Before: maximum positive scheduled gap | Corrected |
| --- | ---: | ---: |
| Aiden 1.0x | approximately 0 ms | 0 ms |
| Aiden 1.5x | 5.333 ms | 0 ms |
| Ryan 1.5x | 5.333 ms | 0 ms |

Every corrected run for both voices at 1.0/1.2/1.5/1.8x used the exact expected 17/21 sources with zero scheduled gaps. This measures requested AudioContext starts, not sound-card loopback capture. The old 1.0x alignment is not a general scheduling guarantee.

An additional native replay released each frame at its originally measured inference arrival interval. Aiden and Ryan at both 1.5x and 1.8x again had zero scheduled gaps, the exact expected source counts and no observed starvation. This does not guarantee uninterrupted generation on slower hardware or longer passages.

A separate native diagnostic played unprocessed captured PCM through actual playbackRate=1.5 for both voices, with contiguous scheduling. It bypasses WSOLA but raises pitch. Matching local diagnostic WAV files encode this rate change with a 36 kHz playback header. This path is diagnostic only.

Captured output durations are unchanged by the correction: Aiden 10.7200/8.9333/7.1467/5.9553 seconds and Ryan 13.4400/11.2000/8.9600/7.4664 seconds at 1.0/1.2/1.5/1.8x. Stretched buffers of at least 2048 samples have at most half a sample of rounding error each. A synthetic autocorrelation test keeps the 223 Hz fundamental within 4 Hz at 1.5x. This is not a formal voice pitch/quality study.

In one Node measurement pass, average processing per captured frame at 1.5x was about 4.35 ms before versus 3.95 ms corrected for Aiden, and 4.35 versus 4.00 ms for Ryan. This is DSP wall time, not whole-application CPU usage; runtime/GC variation limits comparisons. No material processing increase was observed. First playback does not wait to fill the lookahead, so no deliberate prebuffering delay was added. Fresh-inference TTFA was not benchmarked comparatively.

## Automated tests

Before: 86 Python + 36 frontend = **122 passed**.

After: 86 Python + 49 frontend = **135 passed, 0 failed, 0 skipped**. All original tests remain.

The 13 new checks cover production DSP with sine, harmonic/enveloped speech-like signals, silence, amplitude steps, short/threshold/uneven frames, consecutive buffers and slower/faster/noninteger ratios. Assertions cover finite/bounded output, endpoints/seams, duration and pitch. Playback regressions cover one-ahead timing, highlights, no dropped/duplicated buffers, completion, speed edits, pause/resume, Stop of both nodes, starvation recovery and stale callbacks.

```powershell
Set-Location 'A:\VOX-9K'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v
node --test tests\frontend.test.cjs
```

## Real playback and graphical checks

These checks are separate from the headless suite:

- Native recorded-PCM replay: both voices at all four speeds completed with the expected source count.
- Live cached-model native playback: Ryan at 1.5x, pause/resume, volume, Stop/cancellation, Aiden after cancellation, active speed change to 1.2x and completion, then switch back to Kokoro Michael. Kokoro Sarah playback/pause/resume/Stop also passed.
- Native launcher exited normally with no owned processes remaining.
- Browser, in-app Chromium: Aiden Read at 1.5x reached Finished. Ryan Read/Pause/Resume, speed 1.2x and Stop passed. Switching back to Kokoro Michael and Read reached Finished. One completion locator briefly timed out; the immediately following accessibility observation showed Finished without an app error.
- Owner listening: corrected Aiden 1.5x accepted as free of popping and natural. Ryan, 1.8x, slower playback and other passages have no separate owner listening acceptance.

These were short checks, not extended stress tests. State/scheduling checks do not establish audible quality.

## Remaining limitations

Per-buffer WSOLA can still introduce coloration/modulation on difficult material or extreme speeds. The forced tail overlap is not guaranteed optimal phase alignment. No broader WSOLA replacement was authorized or needed for the reproduced defect.

Buffers below 2048 samples keep the prior passthrough behavior (under 85.34 ms at 24 kHz), so their duration is not speed-scaled. Total deviation from ideal duration also includes the sum of `n - round(n/speed)` for those short buffers. The captured fixtures had no such short frame; deterministic tests cover this policy.

The audible remainder plus at most one ahead retains its prepared speed after a slider edit. With ordinary 640 ms input buffers this can approach 1.28 seconds at 1.0x, or 0.85 seconds at 1.5x. Volume remains immediate through the gain node. Reading highlights remain chunk-level approximations.

Genuine generation/network starvation, main-thread stalls longer than the lookahead, raw discontinuities between independent text chunks and device glitches can still interrupt audio. Stop can interrupt a nonzero waveform as before. No added fade masks these cases.

## Exact files and evidence

Only these project files changed in this investigation:

1. `index.html` — tail anchoring, bounded audio-clock scheduling and source cleanup.
2. `tests/frontend.test.cjs` — 13 new regressions and an existing fake context's clock value.
3. `docs/TESTING.md` — current totals and verification scope.
4. `docs/QWEN_AUDIO_REPORT.md` — this report.

Ignored local evidence in `audit/audio-popping-2026-11-12/` includes starting snapshots/hashes/status, historical comparison hashes, captured/raw/legacy/corrected PCM/WAV at all speeds, pitch-shift diagnostic WAV, DSP measurements, native scheduling logs/JSON, live native acceptance, browser observations, owner response and full suite logs. Local diagnostic scripts extract the production function or replay the exact recorded frames. They are investigative evidence, not runtime dependencies. Audio remains local and excluded from Git.

Existing dirty work was preserved. Tracked dirty paths remain .gitignore, README.md, index.html and server.py. Existing untracked desktop/backend/helper/test/docs/tool files remain untracked. No staging, commit, push, reset, clean or stash occurred. Inference/model/dependency files were not changed.

## Windows launch and owner review

In a fresh PowerShell terminal:

```powershell
Set-Location 'A:\VOX-9K'
.\.venv\Scripts\python.exe desktop.py
```

Browser mode instead:

```powershell
Set-Location 'A:\VOX-9K'
.\.venv\Scripts\python.exe server.py
```

Open http://127.0.0.1:5000, select Qwen3-TTS, Aiden or Ryan and 1.5x. No new installation is required. When reusing a diagnostic terminal, remove VOX_SKIP_WARMUP and VOX_DISABLE_QWEN first as described in RUNNING.md.

Changes remain uncommitted for owner review. Additional Ryan/longer-passage listening is useful before broader acceptance.
