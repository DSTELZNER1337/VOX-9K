/* Local features share the existing text cleanup/chunking and selected controls. */
const exportButton = document.getElementById("exportButton");
const exportEstimate = document.getElementById("exportEstimate");
const exportStatus = document.getElementById("exportStatus");
const exportDownload = document.getElementById("exportDownload");
const cancelExportButton = document.getElementById("cancelExport");
const backgroundFile = document.getElementById("backgroundFile");
let exportJob = null;
let exportEpoch = 0;
let exportPending = false;
let exportReadyKey = null;
let exportPollTimer = null;

function durationLabel(seconds) {
    const total = Math.max(0, Math.round(seconds));
    const minutes = Math.floor(total / 60);
    return (minutes ? minutes + " min " : "") + (total % 60) + " sec";
}
function sizeLabel(bytes) {
    return bytes < 1024 * 1024
        ? (bytes / 1024).toFixed(1) + " KB"
        : (bytes / (1024 * 1024)).toFixed(1) + " MB";
}
function estimateWav(raw, engine, speed) {
    const text = cleanText(raw);
    const words = text ? text.split(/\s+/u).length : 0;
    const effectiveWords = Math.max(words, text.replace(/\s/gu, "").length / 6);
    const seconds = effectiveWords * 60 / (engine === "qwen" ? 150 : 170);
    return {seconds, listening: seconds / Math.max(.5, Number(speed) || 1),
        bytes: 44 + Math.round(seconds * 24000) * 2, words};
}
function exportSelectionKey() {
    return JSON.stringify([cleanText(promptText.value), engineSelect.value, voiceSelect.value, computeSelect.value]);
}
function updateExportEstimate() {
    if (!exportPending && exportReadyKey && exportReadyKey !== exportSelectionKey()) {
        exportDownload.hidden = true;
        exportStatus.textContent = "Text or voice settings changed. Download WAV to generate a new recording.";
    }
    const estimate = estimateWav(promptText.value, engineSelect.value, speedSlider.value);
    exportEstimate.textContent = estimate.words
        ? "Estimated WAV: ~" + durationLabel(estimate.seconds) + " · ~" +
          sizeLabel(estimate.bytes) + " at native 1.0×. Listening at " +
          Number(speedSlider.value).toFixed(1) + "×: ~" + durationLabel(estimate.listening) + "."
        : "WAV export uses native 1.0× audio · mono 24 kHz / 16-bit.";
}
async function featureResponse(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The local operation failed.");
    return data;
}
function unlockExportUI() {
    exportPending = false;
    exportButton.disabled = false;
    readButton.disabled = false;
    cancelExportButton.hidden = true;
}
async function cancelExport() {
    exportEpoch++;
    if (exportPollTimer !== null) clearTimeout(exportPollTimer);
    const id = exportJob;
    exportJob = null;
    exportReadyKey = null;
    exportDownload.hidden = true;
    unlockExportUI();
    exportStatus.textContent = "Export cancelled.";
    if (id) {
        try { await featureResponse("/exports/" + id, {method: "DELETE"}); }
        catch (error) { exportStatus.textContent = "Cancellation requested; " + error.message; }
    }
}
async function pollExport(id, epoch, selectionKey, label) {
    try {
        const data = await featureResponse("/exports/" + id);
        if (epoch !== exportEpoch) return;
        if (data.state === "generating") {
            exportStatus.textContent = "Exporting " + data.completed + " / " + data.total + " chunks · " + label + "…";
            exportPollTimer = setTimeout(() => pollExport(id, epoch, selectionKey, label), 350);
        } else if (data.state === "ready") {
            exportReadyKey = selectionKey;
            exportDownload.href = "/exports/" + id + "/file";
            exportDownload.hidden = false;
            exportStatus.textContent = "WAV ready: " + durationLabel(data.duration) + " · " +
                sizeLabel(data.size) + " · " + label + " · native 1.0×.";
            unlockExportUI();
            updateExportEstimate();
        } else {
            exportJob = null;
            unlockExportUI();
            exportStatus.textContent = data.error || "Export cancelled.";
        }
    } catch (error) {
        if (epoch !== exportEpoch) return;
        unlockExportUI();
        exportStatus.textContent = error.message + " Retry Download WAV.";
        // A lost status response must not leave an orphan generation running.
        if (exportJob) fetch("/exports/" + exportJob, {method: "DELETE"}).catch(() => {});
        exportJob = null;
    }
}
async function startExport() {
    if (exportPending) return;
    if (isActive) {
        exportStatus.textContent = "Stop reading or wait for completion before exporting.";
        return;
    }
    const text = cleanText(promptText.value);
    if (!text) { exportStatus.textContent = "Enter some text to export."; return; }
    if (text.length > 20000) { exportStatus.textContent = "Export is limited to 20,000 characters."; return; }
    const key = exportSelectionKey();
    if (exportJob && exportReadyKey === key) {
        exportDownload.click();
        return;
    }
    if (exportJob) await cancelExport();
    const epoch = ++exportEpoch;
    exportPending = true;
    readButton.disabled = true;
    exportButton.disabled = true;
    cancelExportButton.hidden = false;
    exportDownload.hidden = true;
    exportStatus.textContent = "Preparing WAV export…";
    const selection = {chunks: splitIntoChunks(text), engine: engineSelect.value,
        voice: voiceSelect.value, compute: computeSelect.value};
    const label = selection.engine + " / " + selection.voice;
    try {
        const data = await featureResponse("/exports", {method: "POST",
            headers: {"Content-Type": "application/json"}, body: JSON.stringify(selection)});
        if (epoch !== exportEpoch) {
            fetch("/exports/" + data.id, {method: "DELETE"}).catch(() => {});
            return;
        }
        exportJob = data.id;
        await pollExport(data.id, epoch, key, label);
    } catch (error) {
        if (epoch !== exportEpoch) return;
        unlockExportUI();
        exportStatus.textContent = error.message;
    }
}
function refreshBackground() {
    document.body.style.backgroundImage =
        'linear-gradient(rgba(0,0,0,.65),rgba(0,0,0,.65)),url("/background-image?v=' + Date.now() + '")';
}
async function selectBackground(file) {
    if (!file) return;
    const status = document.getElementById("backgroundStatus");
    if (file.size > 8 * 1024 * 1024) { status.textContent = "Choose an image under 8 MB."; return; }
    status.textContent = "Checking background image…";
    try {
        await featureResponse("/background-image", {method: "POST",
            headers: {"Content-Type": "application/octet-stream"}, body: file});
        refreshBackground();
        status.textContent = "Custom background saved on this computer.";
    } catch (error) { status.textContent = error.message; }
    finally { backgroundFile.value = ""; }
}
exportButton.addEventListener("click", startExport);
cancelExportButton.addEventListener("click", cancelExport);
document.getElementById("backgroundButton").addEventListener("click", () => backgroundFile.click());
backgroundFile.addEventListener("change", () => selectBackground(backgroundFile.files[0]));
document.getElementById("restoreBackground").addEventListener("click", async () => {
    try {
        await featureResponse("/background-image", {method: "DELETE"});
        refreshBackground();
        document.getElementById("backgroundStatus").textContent = "Default background restored.";
    } catch (error) { document.getElementById("backgroundStatus").textContent = error.message; }
});
for (const element of [promptText, engineSelect, voiceSelect, computeSelect, speedSlider]) {
    element.addEventListener(element === promptText || element === speedSlider ? "input" : "change", updateExportEstimate);
}
window.addEventListener("pagehide", () => {
    if (exportJob) fetch("/exports/" + exportJob, {method: "DELETE", keepalive: true}).catch(() => {});
});
updateExportEstimate();
