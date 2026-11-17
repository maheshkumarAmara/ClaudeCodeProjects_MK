const MAX_BYTES = 20 * 1024 * 1024;

// One entry per chosen file: { file, status, original, final, blob, name, note }.
// status: queued | working | done | same | error
let items = [];
let running = false;

const el = (id) => document.getElementById(id);

function showMessage(text, isError) {
    const box = el("comp-message");
    box.textContent = text || "";
    box.hidden = !text;
    box.classList.toggle("message-error", Boolean(isError));
}

function formatBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function isPdfFile(file) {
    return file.type === "application/pdf" || /\.pdf$/i.test(file.name);
}

function addFiles(fileList) {
    if (running) return;
    const skipped = [];
    for (const file of fileList) {
        if (!isPdfFile(file)) {
            skipped.push(file.name);
            continue;
        }
        // Same file picked twice (same name, size and date) is added once.
        const dupe = items.some((i) => i.file.name === file.name && i.file.size === file.size
            && i.file.lastModified === file.lastModified);
        if (!dupe) items.push({ file, status: "queued", original: file.size, name: file.name });
    }
    showMessage(skipped.length ? `Skipped (not a PDF): ${skipped.join(", ")}` : "", Boolean(skipped.length));
    render();
}

function render() {
    const body = el("comp-body");
    body.innerHTML = "";
    el("comp-results").hidden = items.length === 0;
    for (const [index, item] of items.entries()) {
        const row = document.createElement("tr");

        const name = document.createElement("td");
        name.className = "comp-name";
        name.textContent = item.file.name;
        row.appendChild(name);

        const orig = document.createElement("td");
        orig.className = "comp-num";
        orig.textContent = formatBytes(item.original);
        row.appendChild(orig);

        const final = document.createElement("td");
        final.className = "comp-num";
        final.textContent = item.final != null ? formatBytes(item.final) : "–";
        row.appendChild(final);

        const saved = document.createElement("td");
        saved.className = "comp-num";
        if (item.final != null) {
            const pct = item.original ? Math.max(0, (1 - item.final / item.original) * 100) : 0;
            saved.textContent = `${pct.toFixed(1)}%`;
        } else {
            saved.textContent = "–";
        }
        row.appendChild(saved);

        const status = document.createElement("td");
        const labels = {
            queued: "Queued", working: "Compressing…", done: "Done",
            same: "Unchanged", partial: "Target not reached", error: "Failed",
        };
        const badge = document.createElement("span");
        badge.className = `comp-badge ${item.status}`;
        badge.textContent = labels[item.status];
        status.appendChild(badge);
        if (item.note) {
            const note = document.createElement("span");
            note.className = `comp-note${item.status === "error" ? " error" : ""}`;
            note.textContent = item.note;
            status.appendChild(note);
        }
        row.appendChild(status);

        const action = document.createElement("td");
        if (item.blob) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "secondary";
            button.textContent = "Download";
            button.addEventListener("click", () => downloadBlob(item.blob, item.outName));
            action.appendChild(button);
        } else if (!running) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "secondary";
            button.textContent = "Remove";
            button.addEventListener("click", () => {
                items.splice(index, 1);
                render();
            });
            action.appendChild(button);
        }
        row.appendChild(action);
        body.appendChild(row);
    }
    updateControls();
}

function updateControls() {
    const finished = items.filter((i) => i.blob);
    const pending = items.some((i) => i.status === "queued" || i.status === "error");
    el("cmp-run").disabled = running || !pending;
    el("cmp-clear").disabled = running || items.length === 0;
    el("comp-download-all").disabled = running || finished.length === 0;
    el("cmp-level").disabled = running;
    el("cmp-target").disabled = running;

    const originalTotal = finished.reduce((sum, i) => sum + i.original, 0);
    const finalTotal = finished.reduce((sum, i) => sum + i.final, 0);
    const summary = el("comp-summary");
    if (finished.length) {
        const pct = originalTotal ? Math.max(0, (1 - finalTotal / originalTotal) * 100) : 0;
        summary.textContent = `${finished.length} of ${items.length} compressed · `
            + `${formatBytes(originalTotal)} → ${formatBytes(finalTotal)} (${pct.toFixed(1)}% saved)`;
    } else {
        summary.textContent = `${items.length} file${items.length === 1 ? "" : "s"}`;
    }
}

function outputName(originalName) {
    return originalName.replace(/\.pdf$/i, "") + "_compressed.pdf";
}

// "" for the fixed levels, or the MB typed in the box when "Target size" is chosen.
function targetMb() {
    return el("cmp-level").value === "target" ? el("cmp-target").value.trim() : "";
}

function targetError() {
    if (el("cmp-level").value !== "target") return "";
    const mb = Number(el("cmp-target").value);
    return Number.isFinite(mb) && mb > 0 && mb <= 20 ? "" : "Enter a target size between 0.1 and 20 MB.";
}

async function compressOne(item, level, target) {
    item.status = "working";
    item.note = "";
    render();
    if (item.file.size > MAX_BYTES) {
        item.status = "error";
        item.note = "File is larger than 20 MB.";
        return;
    }
    const form = new FormData();
    form.append("pdf", item.file);
    form.append("level", level === "target" ? "low" : level);
    if (target) form.append("target_mb", target);
    try {
        const res = await fetch("/api/compress", { method: "POST", body: form });
        if (!res.ok) {
            let detail = `Server error (${res.status}).`;
            try { detail = (await res.json()).detail || detail; } catch (e) { /* not JSON */ }
            item.status = "error";
            item.note = detail;
            return;
        }
        item.blob = await res.blob();
        item.final = item.blob.size;
        item.outName = outputName(item.file.name);
        item.note = res.headers.get("X-PDF-Size-Note") || "";
        item.status = item.final < item.original ? "done" : "same";
        // A target the PDF could not reach is a result worth flagging, not a failure.
        if (target && item.final > Number(target) * 1024 * 1024 && item.final < item.original) item.status = "partial";
    } catch (err) {
        item.status = "error";
        item.note = "Could not reach the server.";
    }
}

async function runAll() {
    const level = el("cmp-level").value;
    const problem = targetError();
    if (problem) return showMessage(problem, true);
    const target = targetMb();
    running = true;
    showMessage("");
    // Sequential: keeps server memory low and one failing file never blocks the others.
    for (const item of items) {
        if (item.status === "done" || item.status === "same" || item.status === "partial") continue;
        item.blob = null;
        item.final = null;
        await compressOne(item, level, target);
        render();
    }
    running = false;
    render();
    const failed = items.filter((i) => i.status === "error").length;
    if (failed) showMessage(`${failed} file${failed === 1 ? "" : "s"} could not be compressed. See the Status column.`, true);
}

function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// ── Minimal store-only ZIP writer (PDFs are already compressed, so no deflate is needed) ──
const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
        let c = n;
        for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
        table[n] = c >>> 0;
    }
    return table;
})();

function crc32(bytes) {
    let crc = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime(date) {
    const time = (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1);
    const day = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
    return { time, day };
}

async function buildZip(entries) {
    const encoder = new TextEncoder();
    const { time, day } = dosDateTime(new Date());
    const parts = [];
    const central = [];
    let offset = 0;
    for (const entry of entries) {
        const nameBytes = encoder.encode(entry.name);
        const data = new Uint8Array(await entry.blob.arrayBuffer());
        const crc = crc32(data);

        const local = new DataView(new ArrayBuffer(30));
        local.setUint32(0, 0x04034b50, true);
        local.setUint16(4, 20, true);
        local.setUint16(6, 0x0800, true); // UTF-8 file names
        local.setUint16(8, 0, true); // stored
        local.setUint16(10, time, true);
        local.setUint16(12, day, true);
        local.setUint32(14, crc, true);
        local.setUint32(18, data.length, true);
        local.setUint32(22, data.length, true);
        local.setUint16(26, nameBytes.length, true);
        local.setUint16(28, 0, true);
        parts.push(local.buffer, nameBytes, data);

        const dir = new DataView(new ArrayBuffer(46));
        dir.setUint32(0, 0x02014b50, true);
        dir.setUint16(4, 20, true);
        dir.setUint16(6, 20, true);
        dir.setUint16(8, 0x0800, true);
        dir.setUint16(10, 0, true);
        dir.setUint16(12, time, true);
        dir.setUint16(14, day, true);
        dir.setUint32(16, crc, true);
        dir.setUint32(20, data.length, true);
        dir.setUint32(24, data.length, true);
        dir.setUint16(28, nameBytes.length, true);
        dir.setUint32(42, offset, true);
        central.push(dir.buffer, nameBytes);

        offset += 30 + nameBytes.length + data.length;
    }
    const centralSize = central.reduce((sum, part) => sum + part.byteLength, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, entries.length, true);
    end.setUint16(10, entries.length, true);
    end.setUint32(12, centralSize, true);
    end.setUint32(16, offset, true);
    return new Blob([...parts, ...central, end.buffer], { type: "application/zip" });
}

async function downloadAll() {
    const finished = items.filter((i) => i.blob);
    if (!finished.length) return;
    const used = new Set();
    const entries = finished.map((item) => {
        // Two inputs can share a name (same file from different folders); keep both in the ZIP.
        let name = item.outName;
        for (let n = 2; used.has(name.toLowerCase()); n++) name = item.outName.replace(/\.pdf$/i, ` (${n}).pdf`);
        used.add(name.toLowerCase());
        return { name, blob: item.blob };
    });
    if (entries.length === 1) return downloadBlob(entries[0].blob, entries[0].name);
    downloadBlob(await buildZip(entries), "compressed_pdfs.zip");
}

function init() {
    const input = el("cmp-files");
    const drop = el("cmp-drop");
    input.addEventListener("change", () => {
        addFiles(input.files);
        input.value = ""; // lets the same file be chosen again after Clear
    });
    for (const type of ["dragenter", "dragover"]) {
        drop.addEventListener(type, (event) => {
            event.preventDefault();
            drop.classList.add("dragging");
        });
    }
    for (const type of ["dragleave", "drop"]) {
        drop.addEventListener(type, (event) => {
            event.preventDefault();
            drop.classList.remove("dragging");
        });
    }
    drop.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));
    // A PDF dropped outside the zone would otherwise make the browser navigate away to it.
    for (const type of ["dragover", "drop"]) window.addEventListener(type, (event) => event.preventDefault());

    el("cmp-run").addEventListener("click", runAll);
    el("cmp-clear").addEventListener("click", () => {
        items = [];
        showMessage("");
        render();
    });
    el("comp-download-all").addEventListener("click", downloadAll);
    // Changing the level after a run makes the finished results stale; re-queue them.
    const requeue = () => {
        for (const item of items) {
            if (item.status === "done" || item.status === "same" || item.status === "partial") {
                item.status = "queued";
                item.blob = null;
                item.final = null;
                item.note = "";
            }
        }
        render();
    };
    el("cmp-level").addEventListener("change", () => {
        el("cmp-target-wrap").hidden = el("cmp-level").value !== "target";
        requeue();
    });
    el("cmp-target").addEventListener("change", requeue);
    render();
}

init();
