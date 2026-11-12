# Right-click paste and background security observation

Date: 2026-11-12, America/New_York. Checkout: A:\VOX-9K. Branch: audit/portfolio-readiness-2026-11-11. HEAD remains 742d2d7f87a65127197007bfb1dbf3c515facfd3. All preceding unpublished WAV/background work was preserved. Forty-three tracked/nonignored source files and the dirty inventory were copied into ignored audit/paste-security-2026-11-12/ before edits. Nothing was staged, committed, pushed or published.

## Paste root cause and correction

Installed pywebview 6.2.1's Edge Chromium backend sets AreDefaultContextMenusEnabled to its debug flag. VOX-9K correctly starts with debug=False, so native context menus were disabled. Actual WebView2 settings in a production-style native window confirmed menus=False, developer tools=False and browser accelerators=False.

Microsoft documents that disabling default menus also prevents ContextMenuRequested from firing. See [WebView2 context menus](https://learn.microsoft.com/en-us/microsoft-edge/webview2/how-to/context-menus). The fix does not turn on debug mode.

A small desktop_editing.py adapter subscribes to the native ContextMenuRequested event, keeps developer tools off and enables default context menus. The handler allows only editable targets on the exact local VOX-9K page and retains the built-in Undo/Redo, Cut, Copy, Paste, Paste and match style, and Select All commands. All nonediting commands are removed; other targets/pages retain no newly enabled menu. The engine's enabled state is preserved.

desktop.py attaches the adapter on its loaded event. Configuration is marshalled to the Windows Forms UI thread, attaches once and fails closed if the native event is unavailable. Initialization errors are logged; there is no debug or custom-clipboard fallback.

Native WebView2 performs editing at the real cursor/selection, owns focus and handles its clipboard failures/unavailable commands. The application does not add a clipboard listener, broad clipboard permission, HTTP endpoint or JavaScript clipboard bridge. Existing keyboard accelerators are not broadened. Browser-mode frontend editing code is unchanged.

Runtime: pywebview **6.2.1**, installed WebView2 **157.0.4341.46**, Windows desktop source launcher. Future backend/runtime changes should recheck native object/event access; absence of that API can leave the mouse menu unavailable while keyboard editing remains native.

## Confirmed Windows Security classification; trigger unconfirmed

The owner later supplied the exact notification: **Protected folder access blocked**, at **2026-11-12 12:45 PM**, for **msedgewebview2.exe** attempting to modify **%USERPROFILE%\Favorites**, blocked by **Controlled folder access**.

A narrowly scoped, read-only check found the corresponding Defender Operational **event 1123 at 12:45:29 PM**. Microsoft identifies 1123 as a blocked CFA event: [Controlled Folder Access monitoring](https://learn.microsoft.com/en-us/defender-endpoint/evaluate-controlled-folder-access).

This confirms the protection category and blocked operation. It is not evidence of a malware detection and does not establish which WebView2/Windows picker/profile operation requested that write. VOX-9K's background code does not reference Favorites; it validates bytes and atomically writes a fixed background.png under per-user Local AppData (or an explicit diagnostic override). It does not launch subprocesses, modify shell favorites or accept arbitrary paths.

The owner tried Change Background repeatedly and could not reproduce the notification. Therefore **the exact trigger/root cause remains undetermined and the warning is not currently reproducible**. No claim is made that this pass eliminated it. A picker/shell/profile interaction is only a possibility, not a verified diagnosis.

Per owner direction, **background runtime code is unchanged**. No Defender/SmartScreen/CFA setting, antivirus exclusion, application allowlist, elevation requirement or system policy was changed. No undocumented warning-suppression flag was introduced. The block should stay in place. If it recurs, retain the exact notification/time and record the stage of the operation; stop that selection attempt and keep the existing/default background pending investigation. The app does not need Favorites write access.

Only relevant event facts were retained locally; unrelated security history was not exported. User/machine identifiers from the event were removed from the retained summary. No security data is included in source documentation beyond generic process/target/time/classification.

## Verification

### Automated regression suite

Baseline: **172 passed** (112 Python + 60 frontend).

Final: **188 passed, 0 failed, 0 skipped** (126 Python + 62 frontend).

Added tests:
- 10 native-menu policy/UI-thread initialization tests, including failure before enabling unscoped menus, idempotence, exact page/editable-target restriction, native disabled clipboard commands and debug/accelerator preservation.
- 4 existing-background error-path tests: permission-denied save/restore, atomic replacement failure preserving the old image and cleaning its temp file, and rejection of a path-like JSON payload instead of reading an arbitrary file.
- 2 frontend unreadable-file/permission-failure reporting and retry tests.

All prior export, PCM ordering, Qwen cancellation/stream parsing, Kokoro, pause/resume, Stop, read highlighting, speed, volume, startup/shutdown and background validation/persistence/restore tests remain.

### Actual desktop and owner acceptance

Actual native settings changed from menus=False to menus=True while developer tools remained False. The owner physically right-clicked the editable field, used Paste, selected/replaced text and checked Ctrl+V, answering:

**“Menu and both paste methods work.”**

A passive native observer recorded **four actual editable-target menu requests**, showing only undo/redo/cut/copy/paste/pasteAndMatchStyle/selectAll with native enabled/disabled flags. The textarea retained focus. Owner input itself was not logged; only the known fixture-match flag and selection/length metadata were retained.

The initial automated DevTools mouse/key probes did not raise the host's native context-menu event, so those attempts were not counted as proof of mouse pasting. Physical owner acceptance provided that verification. No native clipboard-content monitor was added to production.

The corrected desktop source window started/shut down normally. The owner also confirmed that the preceding WAV-export feature works correctly.

### Browser and functional regressions

The actual loopback UI/backend was run with previously recorded Kokoro WAV and Qwen framed PCM fixtures, **without fresh neural inference**. Interactive in-app Chromium checks passed:
- Ctrl+V insertion, Select All/replacement and a **16,500-character** paste.
- Kokoro Read/Pause/Resume/Stop, followed by Qwen streaming Read/Pause/Resume/completion.
- Voice/engine switching, 1.5x speed, volume adjustment to 90%, visible reading highlights and return to editable text.
- Custom JPEG selection while paused, without changing paused playback state; Restore default; WAV generation reaching Ready afterward.

These are real UI/playback checks using mocked generation, not fresh engine/voice-quality measurements. The existing accepted audio functions and background/export runtime files were compared against the starting snapshot and preserved. No inference library/model change or download occurred. Normal Brave-specific context-menu UI was not separately controlled.

Background persistence/validation/restore checks passed in the automated suite. The unchanged implementation already passed real backend-restart persistence in the preceding feature acceptance. The original tracked background/screenshot remain unchanged.

Local evidence: audit/paste-security-2026-11-12/, including baseline copies, test logs, native settings/menu observations, owner response, sanitized event summary, browser fixture results and preview. It remains ignored.

## Files changed in this follow-up only

Modified:
- desktop.py
- README.md
- tests/test_desktop.py
- tests/test_features.py
- tests/frontend.test.cjs
- docs/TESTING.md
- docs/DESKTOP.md
- docs/EXPORT_AND_BACKGROUNDS.md

Added:
- desktop_editing.py
- tests/test_desktop_editing.py
- docs/PASTE_SECURITY_REPORT.md

All other pre-existing unpublished changes remain in place. No background/export/security-guard/inference implementation was changed in this follow-up.

## Owner verification and launch

Fresh PowerShell:
~~~powershell
Set-Location 'A:\VOX-9K'
.\.venv\Scripts\python.exe desktop.py
~~~

If reusing a diagnostic shell, remove VOX_SKIP_WARMUP and VOX_DISABLE_QWEN first. Browser mode remains the same interpreter running server.py, then http://127.0.0.1:5000.

For repeat acceptance:
1. Copy an ordinary nonsensitive passage, right-click inside the editable field and choose Paste.
2. Place the cursor between existing words and repeat; select text and paste to replace it.
3. Check Ctrl+V, Cut/Copy/Select All and a longer passage. Stop reading first if the temporary read view is active.
4. Select a valid local PNG/JPEG/WebP, restart the app to check persistence, then Restore default.
5. If the security notification reappears, do not weaken protections; capture its exact message/time and operation stage. The verified CFA classification is documented, but disappearance is not a verified code fix.

Changes remain uncommitted on the existing audit branch. HEAD/index are unchanged; all prior work/history is preserved.
