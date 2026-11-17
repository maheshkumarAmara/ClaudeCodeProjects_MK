const MAX_BYTES = 20 * 1024 * 1024;
// Same shape the server accepts for a new address: one address, nothing else in the box.
const EMAIL_RE = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$/;

let file = null;
// One entry per address found: { address, pages, count, value }; value is what is typed in the box.
let rows = [];
let busy = false;

const el = (id) => document.getElementById(id);

function showMessage(text, isError) {
    const box = el("ee-message");
    box.textContent = text || "";
    box.hidden = !text;
    box.classList.toggle("message-error", Boolean(isError));
}

function isPdfFile(f) {
    return f.type === "application/pdf" || /\.pdf$/i.test(f.name);
}

function whereText(row) {
    const pages = row.pages.length === 1 ? `page ${row.pages[0]}` : `pages ${row.pages.join(", ")}`;
    return `${pages} · ${row.count} time${row.count === 1 ? "" : "s"}`;
}

function rowState(row) {
    const value = row.value.trim();
    if (value === row.address) return "same";
    if (!value) return "blank";
    return EMAIL_RE.test(value) ? "changed" : "invalid";
}

function render() {
    const body = el("ee-body");
    body.innerHTML = "";
    el("ee-results").hidden = rows.length === 0 && !file;
    for (const row of rows) {
        const tr = document.createElement("tr");

        const old = document.createElement("td");
        old.className = "ee-old";
        old.textContent = row.address;
        tr.appendChild(old);

        const where = document.createElement("td");
        where.className = "ee-where";
        where.textContent = whereText(row);
        tr.appendChild(where);

        const cell = document.createElement("td");
        cell.className = "ee-new";
        const input = document.createElement("input");
        input.type = "email";
        input.value = row.value;
        input.spellcheck = false;
        input.setAttribute("aria-label", `New address for ${row.address}`);
        const note = document.createElement("span");
        note.className = "ee-error";
        note.hidden = true;
        const paint = () => {
            const state = rowState(row);
            input.classList.toggle("changed", state === "changed");
            input.classList.toggle("invalid", state === "invalid" || state === "blank");
            note.hidden = state !== "invalid" && state !== "blank";
            note.textContent = state === "blank" ? "Enter an address, or reset this row." : "Not a valid email address.";
            updateControls();
        };
        input.addEventListener("input", () => {
            row.value = input.value;
            markPreviewStale();
            paint();
        });
        cell.append(input, note);
        tr.appendChild(cell);

        const reset = document.createElement("td");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary";
        button.textContent = "Reset";
        button.addEventListener("click", () => {
            row.value = row.address;
            input.value = row.address;
            markPreviewStale();
            paint();
        });
        reset.appendChild(button);
        tr.appendChild(reset);

        body.appendChild(tr);
        paint();
    }
    updateControls();
}

function updateControls() {
    const states = rows.map(rowState);
    const changed = states.filter((s) => s === "changed").length;
    const problems = states.filter((s) => s === "invalid" || s === "blank").length;
    el("ee-generate").disabled = busy || changed === 0 || problems > 0;
    el("ee-preview").disabled = busy || changed === 0 || problems > 0;
    el("ee-reset").disabled = busy || rows.length === 0;
    el("ee-clear").disabled = busy;
    el("ee-summary").textContent = rows.length
        ? `${rows.length} found · ${changed} to change`
        : "";
}

function resetAll() {
    for (const row of rows) row.value = row.address;
    markPreviewStale();
    render();
}

// The preview shows the PDF as it was when Preview PDF was clicked. Once an address changes it no
// longer matches what Generate would deliver, so say so rather than leave it looking current.
function markPreviewStale() {
    if (!el("pdf-preview-container").hidden) el("ee-stale").hidden = false;
}

function hidePreview() {
    el("pdf-preview-container").hidden = true;
    el("pdf-preview-pages").replaceChildren();
    el("ee-stale").hidden = true;
}

function clearAll() {
    file = null;
    rows = [];
    hidePreview();
    el("ee-drop-title").textContent = "Drop a PDF here or click to choose";
    el("ee-drop-sub").textContent = "One PDF at a time. Up to 20 MB.";
    showMessage("");
    render();
}

async function errorDetail(res) {
    let detail = `Server error (${res.status}).`;
    try { detail = (await res.json()).detail || detail; } catch (e) { /* not JSON */ }
    return detail;
}

async function loadFile(chosen) {
    if (busy || !chosen) return;
    if (!isPdfFile(chosen)) return showMessage(`${chosen.name} is not a PDF.`, true);
    if (chosen.size > MAX_BYTES) return showMessage("File is larger than 20 MB.", true);
    busy = true;
    file = chosen;
    rows = [];
    hidePreview();
    el("ee-drop-title").textContent = chosen.name;
    el("ee-drop-sub").textContent = "Reading the PDF…";
    showMessage("");
    render();
    const form = new FormData();
    form.append("pdf", chosen);
    try {
        const res = await fetch("/api/email-editor/scan", { method: "POST", body: form });
        if (!res.ok) {
            showMessage(await errorDetail(res), true);
            file = null;
            el("ee-drop-title").textContent = "Drop a PDF here or click to choose";
            el("ee-drop-sub").textContent = "One PDF at a time. Up to 20 MB.";
        } else {
            const data = await res.json();
            rows = data.emails.map((e) => ({ ...e, value: e.address }));
            el("ee-drop-sub").textContent = "Click to choose a different PDF.";
            if (!rows.length) {
                showMessage("No email addresses were found in this PDF. If it is a scan, it has no text to read.", true);
            }
        }
    } catch (err) {
        showMessage("Could not reach the server.", true);
        file = null;
    }
    busy = false;
    render();
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

// Only the addresses that were changed are sent; the rest stay exactly as printed. Preview and
// download use the same request, so the preview is the PDF the download delivers.
function changedMapping() {
    const mapping = {};
    for (const row of rows) {
        if (rowState(row) === "changed") mapping[row.address] = row.value.trim();
    }
    return mapping;
}

function requestBody(mapping) {
    const form = new FormData();
    form.append("pdf", file);
    form.append("mapping", JSON.stringify(mapping));
    return form;
}

async function preview() {
    if (busy || !file) return;
    const mapping = changedMapping();
    if (!Object.keys(mapping).length) return;
    busy = true;
    showMessage("");
    el("ee-preview").textContent = "Generating preview…";
    updateControls();
    try {
        // Page images, not the PDF in an <iframe>: this page can run inside Streamlit's sandboxed
        // iframe, where Chrome blocks its PDF viewer.
        const res = await fetch("/api/email-editor/preview", { method: "POST", body: requestBody(mapping) });
        if (!res.ok) {
            showMessage(await errorDetail(res), true);
        } else {
            const { pages } = await res.json();
            el("pdf-preview-pages").replaceChildren(...pages.map((data, index) => {
                const img = document.createElement("img");
                img.src = `data:image/png;base64,${data}`;
                img.alt = `PDF page ${index + 1} of ${pages.length}`;
                return img;
            }));
            el("ee-stale").hidden = true;
            el("pdf-preview-container").hidden = false;
            el("pdf-preview-container").scrollIntoView({ behavior: "smooth", block: "nearest" });
            showMessage("Preview updated. Nothing has been downloaded yet.");
        }
    } catch (err) {
        showMessage("Could not reach the server.", true);
    }
    busy = false;
    el("ee-preview").textContent = "Preview PDF";
    updateControls();
}

async function generate() {
    if (busy || !file) return;
    const mapping = changedMapping();
    if (!Object.keys(mapping).length) return;
    busy = true;
    showMessage("");
    el("ee-generate").textContent = "Generating…";
    updateControls();
    const form = requestBody(mapping);
    try {
        const res = await fetch("/api/email-editor/apply", { method: "POST", body: form });
        if (!res.ok) {
            showMessage(await errorDetail(res), true);
        } else {
            downloadBlob(await res.blob(), file.name.replace(/\.pdf$/i, "") + "_emails.pdf");
            const n = Object.keys(mapping).length;
            showMessage(`Downloaded. ${n} address${n === 1 ? "" : "es"} changed; the rest of the PDF is unchanged.`);
        }
    } catch (err) {
        showMessage("Could not reach the server.", true);
    }
    busy = false;
    el("ee-generate").textContent = "Generate & download PDF";
    updateControls();
}

function init() {
    const input = el("ee-file");
    const drop = el("ee-drop");
    input.addEventListener("change", () => {
        loadFile(input.files[0]);
        input.value = ""; // lets the same file be chosen again
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
    drop.addEventListener("drop", (event) => loadFile(event.dataTransfer.files[0]));
    // A PDF dropped outside the zone would otherwise make the browser navigate away to it.
    for (const type of ["dragover", "drop"]) window.addEventListener(type, (event) => event.preventDefault());

    el("ee-preview").addEventListener("click", preview);
    el("ee-generate").addEventListener("click", generate);
    el("ee-reset").addEventListener("click", resetAll);
    el("ee-clear").addEventListener("click", clearAll);
    render();
}

init();
