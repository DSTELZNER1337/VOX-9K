# VOX-9K Desktop UI Polish Report

Date: 2026-11-11. Work remains uncommitted in `A:\VOX-9K` on `audit/portfolio-readiness-2026-11-11` for owner review.

## 1. Changes

- The visible header and browser title now read **VOX-9K**.
- Input/unread text is gray-white (`#bdc2c9`); the current and completed speech chunks are white (`#ffffff`).
- A temporary read view retains the full original input, including Markdown, whitespace and literal HTML. Stop, completion and errors restore the editable textarea without changing its value.
- **Created by: StelzTools** appears at the app's bottom-right in 11 px white at 28% opacity. Reserved bottom space keeps it clear of controls. Background artwork and control order are preserved.

## 2. Exact files

Modified: `index.html`, `tests/frontend.test.cjs`, `docs/TESTING.md`.

Added: `docs/UI_POLISH_REPORT.md`.

Baseline copies, logs, native results and the preview are local under ignored `audit/ui-polish-2026-11-11/`. Backend services, inference code/dependencies, desktop launcher, model assets and the MIT license were not changed.

## 3. Highlighting method

This is **chunk-level**, not word-perfect. The existing Markdown-cleanup rules are shared with an optional source-offset map. Cleaned speech chunk boundaries are mapped back to the original input. The view uses `textContent`, so pasted HTML is displayed literally.

All text starts dim. Kokoro highlights a chunk on the audio element's actual `playing` event. Qwen highlights it when the first PCM buffer for that text chunk starts. Prefetched or queued audio does not advance progress. Completed/current chunks remain white; future text stays dim.

Pause freezes highlighting. Session guards reject stale callbacks and backward updates. At new chunk boundaries the view follows the current chunk inside its own scroll area, without scrolling the whole page. Its initial height matches the textarea. Stop, completion, errors and replacement Reads restore editing with the original text intact.

## 4. Synchronization limits

The whole current chunk becomes white when its audio starts, including words not yet spoken. There is no word/token alignment or character timer. Multiple Qwen PCM frames belonging to one text chunk do not create artificial intra-chunk progress. Speed changes require no timing recalculation; pauses introduce no timer drift.

Editing while active requires Stop. Completion returns to the dim editable input with the existing Finished status. If mapping cannot be established, text remains dim rather than displaying invented positions.

## 5. Automated verification

| Suite | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| Existing Python unit/component/integration tests | 86 | 0 | 0 |
| Frontend tests | 36 | 0 | 0 |
| Total | **122** | **0** | **0** |

Ten frontend tests were added to the original 26. They cover header/footer, unchanged cleanup output, mapping of Markdown/whitespace/emoji/HTML, full-text preservation, monotonic progress, pause/stale sessions, Stop, both completion paths, queued-versus-playing Qwen PCM and error recovery. No prior tests were removed. Headless tests do not establish audible quality.

## 6. Graphical and manual verification

**Actual native window:** a separate WebView2 acceptance run using cached Kokoro CPU and Qwen CUDA passed 16 checks. These included header/footer presence, original-text preservation, current-white/future-dim contrast, frozen paused highlighting, Read/Pause/Resume/Stop, Sarah/Michael and Ryan/Aiden voice paths, engine switching, both completion states, and existing speed/volume controls (1.2x, 40%). It exercised real playback through the window API and is separate from the headless count.

The native read view measured 926 by 426 px at the default input size. The footer was below the status/control area and inside the window. The launcher exited with code 0 and zero owned service processes remained.

**Interactive browser inspection:** in the available in-app Chromium browser, Read displayed the complete original Markdown text, Resume showed a bright current chunk and dim future text, Pause held that state, and Stop restored the editable original. The full-page preview was visually inspected for contrast, preserved layout and unobtrusive attribution: `audit/ui-polish-2026-11-11/browser-progress.jpg`.

No new subjective listening assessment or word-perfect accuracy claim is made. Default Brave and additional display/DPI configurations were not independently inspected. The accepted inference/audio implementation was preserved.

## 7. Launch and Git state

Desktop:

```powershell
Set-Location A:\VOX-9K
.\.venv\Scripts\python.exe desktop.py
```

Browser:

```powershell
Set-Location A:\VOX-9K
.\.venv\Scripts\python.exe server.py
```

Open `http://127.0.0.1:5000` for browser mode.

Branch, HEAD and index remain unchanged. Earlier unpublished work is preserved. No dependencies, engines or desktop architecture changed. Nothing was committed, pushed or published; work stops for owner review.
