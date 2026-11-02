// Distributors hidden from the main page's dropdown (kept in the API); same list as script.js.
const HIDDEN_DISTRIBUTOR_SLUGS = new Set([
    "pt-synnex-metrodata-indonesia",
    "pt-ecs-indo-jaya",
    "hcl",
    "exclusive-networks-turkey",
    "exclusive-networks-south-africa",
    "arrow-ecs-sau",
]);

const FIELD_COLUMNS = ["qty", "unit_cost", "terms", "amount"];
const FIELD_LABELS = { qty: "Quantity", unit_cost: "Unit price", terms: "Term", amount: "Amount" };
const STATUS_LABELS = {
    match: "Match",
    mismatch: "Mismatch",
    only_pdf: "Only in PDF",
    only_json: "Only in JSON",
};

let lastResult = null;
let activeFilter = "all";

function showMessage(text, isError) {
    const el = document.getElementById("cmp-message");
    el.textContent = text || "";
    el.hidden = !text;
    el.classList.toggle("message-error", Boolean(isError));
}

async function loadDistributors() {
    const select = document.getElementById("cmp-distributor");
    try {
        const res = await fetch("/api/distributors");
        const distributors = await res.json();
        select.innerHTML = "";
        const auto = document.createElement("option");
        auto.value = "";
        auto.textContent = "Auto-detect from files";
        select.appendChild(auto);
        for (const [slug, name] of Object.entries(distributors)) {
            if (HIDDEN_DISTRIBUTOR_SLUGS.has(slug)) continue;
            const option = document.createElement("option");
            option.value = slug;
            option.textContent = name;
            select.appendChild(option);
        }
    } catch (err) {
        showMessage("Could not load the distributor list.", true);
    }
}

// The dropdown holds "" (auto-detect) or a slug. While the user hasn't picked a
// distributor themselves, the dropdown follows what detection finds.
let userPicked = false;
let detectRun = 0;

function setDetectedNote(text, warn) {
    const note = document.getElementById("cmp-detected");
    note.textContent = text || "";
    note.hidden = !text;
    note.classList.toggle("warn", Boolean(warn));
}

function followDetection(slug) {
    if (!userPicked) document.getElementById("cmp-distributor").value = slug;
}

async function detectDistributor() {
    const pdf = document.getElementById("cmp-pdf").files[0];
    const json = document.getElementById("cmp-json").files[0];
    if (!pdf && !json) {
        followDetection("");
        return setDetectedNote("");
    }
    const form = new FormData();
    if (pdf) form.append("pdf", pdf);
    if (json) form.append("json_file", json);
    const run = ++detectRun;
    try {
        const res = await fetch("/api/compare/detect", { method: "POST", body: form });
        const body = await res.json();
        if (run !== detectRun) return; // a newer file choice is already being detected
        if (!res.ok) return setDetectedNote("");
        if (body.conflict) {
            followDetection("");
            return setDetectedNote("The JSON says " + body.json + " but the PDF looks like " + body.pdf + ". Choose the distributor.", true);
        }
        if (!body.slug) {
            followDetection("");
            return setDetectedNote("Could not tell the distributor from the files. Choose one.", true);
        }
        followDetection(body.slug);
        setDetectedNote("Detected " + body.name + " from the " + (body.source === "json" ? "JSON" : "PDF") + ".");
    } catch (err) {
        if (run === detectRun) setDetectedNote("");
    }
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

// Fills one summary box with a row of stat tiles.
function renderStats(boxId, stats) {
    const box = document.getElementById(boxId);
    box.innerHTML = "";
    for (const [label, value, tone] of stats) {
        const stat = el("div", `compare-stat ${tone}`.trim());
        stat.appendChild(el("strong", "", String(value)));
        stat.appendChild(el("span", "", label));
        box.appendChild(stat);
    }
}

// Header section: its own count in the title, and its own summary tiles.
function renderHeaderSummary(summary, header) {
    // Rows with match === null are listed for visibility but have only one side to show.
    const compared = header.filter((row) => row.match !== null);
    const matched = compared.filter((row) => row.match).length;
    const onlyPdf = header.filter((row) => headerStatus(row) === "only_pdf").length;
    const onlyJson = header.filter((row) => headerStatus(row) === "only_json").length;
    document.getElementById("cmp-header-count").textContent =
        header.length ? `(${matched} of ${compared.length} compared fields matched)` : "";
    renderStats("cmp-header-summary", [
        ["Fields compared", compared.length, ""],
        ["Fields matched", matched, "good"],
        ["Mismatches", compared.length - matched, compared.length - matched ? "bad" : "good"],
        ["Only in PDF", onlyPdf, onlyPdf ? "warn" : "good"],
        ["Only in JSON / empty", onlyJson, onlyJson ? "warn" : "good"],
    ]);
}

// Line-item section: its own count in the title, and its own summary tiles.
function renderLineSummary(summary) {
    document.getElementById("cmp-line-count").textContent =
        `(${summary.matched} of ${summary.pdf_lines} PDF lines matched)`;
    renderStats("cmp-line-summary", [
        ["PDF line items", summary.pdf_lines, ""],
        ["JSON line items", summary.json_lines, ""],
        ["Lines matched", summary.matched, "good"],
        ["Lines mismatched", summary.mismatched, summary.mismatched ? "bad" : "good"],
        ["Only in PDF", summary.only_in_pdf, summary.only_in_pdf ? "warn" : "good"],
        ["Only in JSON", summary.only_in_json, summary.only_in_json ? "warn" : "good"],
    ]);
}

function fieldCell(info, alwaysShowBoth) {
    const td = el("td");
    if (!info) {
        td.textContent = "—";
        return td;
    }
    if (info.match === null) {
        // Line exists on one side only: show whichever value there is.
        td.textContent = info.pdf || info.json || "—";
        return td;
    }
    if (info.match && !alwaysShowBoth) {
        td.textContent = info.pdf;
        return td;
    }
    // A mismatch is highlighted; a match is only listed in both columns when asked for.
    if (!info.match) td.classList.add("compare-cell-bad");
    for (const [label, value] of [["PDF", info.pdf], ["JSON", info.json]]) {
        const row = el("span", "compare-pair");
        row.appendChild(el("small", "", label));
        row.appendChild(document.createTextNode(value || "(blank)"));
        td.appendChild(row);
    }
    if (alwaysShowBoth) {
        // State the result on every line, so a match is not left for the reader to infer.
        td.appendChild(el("span", `compare-badge compare-field-badge ${info.match ? "match" : "mismatch"}`,
            info.match ? "Matched" : "Not matched"));
    }
    return td;
}

// Joins the reasons a line or header row differs into one readable cell.
function commentCell(comments) {
    const td = el("td", "compare-comment");
    if (!comments || !comments.length) {
        td.textContent = "—";
        return td;
    }
    for (const comment of comments) {
        td.appendChild(el("span", "compare-comment-line", comment));
    }
    return td;
}

function lineVisible(line) {
    if (activeFilter === "all") return true;
    if (activeFilter === "issues") return line.status !== "match";
    return line.status === activeFilter;
}

function renderLines() {
    const body = document.getElementById("cmp-body");
    body.innerHTML = "";
    const lines = (lastResult ? lastResult.lines : []).filter(lineVisible);
    if (!lines.length) {
        const tr = el("tr");
        const td = el("td", "compare-empty", "No lines to show for this filter.");
        td.colSpan = 7;
        tr.appendChild(td);
        body.appendChild(tr);
        return;
    }
    for (const line of lines) {
        const tr = el("tr");
        tr.appendChild(el("td", "", line.sku || "(no SKU)"));
        const status = el("td");
        status.appendChild(el("span", `compare-badge ${line.status}`, STATUS_LABELS[line.status]));
        tr.appendChild(status);
        for (const field of FIELD_COLUMNS) {
            tr.appendChild(fieldCell(line.fields[field], field === "unit_cost"));
        }
        tr.appendChild(commentCell(line.comments));
        body.appendChild(tr);
    }
}

// A header row's status in the same terms as a line's: match, mismatch, or the side it is
// only on (only_pdf / only_json), which the server sets on rows with nothing to compare.
function headerStatus(row) {
    if (row.match === null) return row.side || "only_json";
    return row.match ? "match" : "mismatch";
}

function headerVisible(row) {
    const status = headerStatus(row);
    if (activeFilter === "all") return true;
    if (activeFilter === "issues") return status !== "match";
    return status === activeFilter;
}

function renderHeader(header) {
    const card = document.getElementById("cmp-header-card");
    const body = document.getElementById("cmp-header-body");
    body.innerHTML = "";
    card.hidden = !header.length;
    const rows = header.filter(headerVisible);
    if (header.length && !rows.length) {
        const tr = el("tr");
        const td = el("td", "compare-empty", "No header fields to show for this filter.");
        td.colSpan = 5;
        tr.appendChild(td);
        body.appendChild(tr);
        return;
    }
    for (const row of rows) {
        const tr = el("tr");
        tr.appendChild(el("td", "", row.field));
        const badCell = row.match === false ? "compare-cell-bad" : "";
        const state = headerStatus(row);
        tr.appendChild(el("td", badCell, row.pdf || (state === "only_json" ? "—" : "")));
        tr.appendChild(el("td", badCell, row.json || (state === "only_json" ? "(empty)" : "—")));
        const status = el("td");
        const badgeText = { match: "Match", mismatch: "Mismatch", only_pdf: "Only in PDF", only_json: "Only in JSON" }[state];
        status.appendChild(el("span", `compare-badge ${state}`, badgeText));
        tr.appendChild(status);
        tr.appendChild(commentCell(row.comment ? [row.comment] : []));
        body.appendChild(tr);
    }
}

function csvCell(value) {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadCsv() {
    if (!lastResult) return;
    const header = ["SKU", "Status", "Field", "PDF value", "JSON value", "Field status", "Comments"];
    const rows = [header];
    for (const line of lastResult.lines) {
        const lineComments = (line.comments || []).join("; ");
        for (const field of FIELD_COLUMNS) {
            const info = line.fields[field];
            if (!info) continue;
            const fieldStatus = info.match === null ? "n/a" : info.match ? "match" : "mismatch";
            rows.push([line.sku, STATUS_LABELS[line.status], FIELD_LABELS[field], info.pdf, info.json, fieldStatus, info.comment || lineComments]);
        }
    }
    if (lastResult.header.length) {
        rows.push([]);
        rows.push(["Header field", "Status", "", "PDF value", "JSON value", "", "Comments"]);
        for (const row of lastResult.header) {
            const status = { match: "Match", mismatch: "Mismatch", only_pdf: "Only in PDF", only_json: "Only in JSON" }[headerStatus(row)];
            rows.push([row.field, status, "", row.pdf, row.json, "", row.comment || ""]);
        }
    }
    const blob = new Blob([rows.map((r) => r.map(csvCell).join(",")).join("\n")], { type: "text/csv" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "pdf-json-comparison.csv";
    link.click();
    URL.revokeObjectURL(link.href);
}

async function runCompare() {
    const slug = document.getElementById("cmp-distributor").value;
    const pdf = document.getElementById("cmp-pdf").files[0];
    const json = document.getElementById("cmp-json").files[0];
    if (!pdf) return showMessage("Choose the purchase order PDF.", true);
    if (!json) return showMessage("Choose the JSON file.", true);

    const form = new FormData();
    form.append("slug", slug);
    form.append("pdf", pdf);
    form.append("json_file", json);
    form.append("tolerance", document.getElementById("cmp-tolerance").value || "0.01");

    const button = document.getElementById("cmp-run");
    button.disabled = true;
    showMessage("Comparing…", false);
    document.getElementById("cmp-results").hidden = true;
    try {
        const res = await fetch("/api/compare", { method: "POST", body: form });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
            showMessage(body.detail || `Comparison failed (${res.status}).`, true);
            return;
        }
        lastResult = body;
        if (body.distributor) setDetectedNote("Compared as " + body.distributor.name + ".");
        activeFilter = "all";
        for (const b of document.querySelectorAll("#cmp-filters button")) {
            b.classList.toggle("active", b.dataset.filter === "all");
        }
        renderHeaderSummary(body.summary, body.header);
        renderHeader(body.header);
        renderLineSummary(body.summary);
        renderLines();
        document.getElementById("cmp-results").hidden = false;
        if (!body.summary.json_lines) {
            showMessage("No line items with a SKU-like key (partNumber, sku, productCode…) were found in the JSON.", true);
        } else {
            showMessage("", false);
        }
    } catch (err) {
        showMessage("Could not reach the server.", true);
    } finally {
        button.disabled = false;
    }
}

document.getElementById("cmp-run").addEventListener("click", runCompare);
document.getElementById("cmp-pdf").addEventListener("change", detectDistributor);
document.getElementById("cmp-json").addEventListener("change", detectDistributor);
document.getElementById("cmp-distributor").addEventListener("change", (event) => {
    // "Auto-detect" hands control back to detection; any other choice is the user's own.
    userPicked = event.target.value !== "";
    if (userPicked) setDetectedNote("");
    else detectDistributor();
});
document.getElementById("cmp-download").addEventListener("click", downloadCsv);
document.getElementById("cmp-filters").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-filter]");
    if (!button) return;
    activeFilter = button.dataset.filter;
    for (const b of document.querySelectorAll("#cmp-filters button")) {
        b.classList.toggle("active", b === button);
    }
    // One filter for the whole result: the header and the line items follow it together.
    if (lastResult) renderHeader(lastResult.header);
    renderLines();
});

loadDistributors();
