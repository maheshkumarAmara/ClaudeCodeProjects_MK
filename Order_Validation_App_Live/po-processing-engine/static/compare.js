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

function renderSummary(summary) {
    const stats = [
        ["PDF lines", summary.pdf_lines, ""],
        ["JSON lines", summary.json_lines, ""],
        ["Matched", summary.matched, "good"],
        ["Mismatched", summary.mismatched, summary.mismatched ? "bad" : "good"],
        ["Only in PDF", summary.only_in_pdf, summary.only_in_pdf ? "warn" : "good"],
        ["Only in JSON", summary.only_in_json, summary.only_in_json ? "warn" : "good"],
    ];
    if (summary.header_compared) {
        stats.push(["Header mismatches", summary.header_mismatched, summary.header_mismatched ? "bad" : "good"]);
    }
    const box = document.getElementById("cmp-summary");
    box.innerHTML = "";
    for (const [label, value, tone] of stats) {
        const stat = el("div", `compare-stat ${tone}`.trim());
        stat.appendChild(el("strong", "", String(value)));
        stat.appendChild(el("span", "", label));
        box.appendChild(stat);
    }
}

function fieldCell(info) {
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
    if (info.match) {
        td.textContent = info.pdf;
        return td;
    }
    td.classList.add("compare-cell-bad");
    for (const [label, value] of [["PDF", info.pdf], ["JSON", info.json]]) {
        const row = el("span", "compare-pair");
        row.appendChild(el("small", "", label));
        row.appendChild(document.createTextNode(value || "(blank)"));
        td.appendChild(row);
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
        td.colSpan = 6;
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
            tr.appendChild(fieldCell(line.fields[field]));
        }
        body.appendChild(tr);
    }
}

function renderHeader(header) {
    const card = document.getElementById("cmp-header-card");
    const body = document.getElementById("cmp-header-body");
    body.innerHTML = "";
    card.hidden = !header.length;
    for (const row of header) {
        const tr = el("tr");
        tr.appendChild(el("td", "", row.field));
        tr.appendChild(el("td", row.match ? "" : "compare-cell-bad", row.pdf));
        tr.appendChild(el("td", row.match ? "" : "compare-cell-bad", row.json));
        const status = el("td");
        status.appendChild(el("span", `compare-badge ${row.match ? "match" : "mismatch"}`, row.match ? "Match" : "Mismatch"));
        tr.appendChild(status);
        body.appendChild(tr);
    }
}

function csvCell(value) {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadCsv() {
    if (!lastResult) return;
    const header = ["SKU", "Status", "Field", "PDF value", "JSON value", "Field status"];
    const rows = [header];
    for (const line of lastResult.lines) {
        for (const field of FIELD_COLUMNS) {
            const info = line.fields[field];
            if (!info) continue;
            const fieldStatus = info.match === null ? "n/a" : info.match ? "match" : "mismatch";
            rows.push([line.sku, STATUS_LABELS[line.status], FIELD_LABELS[field], info.pdf, info.json, fieldStatus]);
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
        renderSummary(body.summary);
        renderLines();
        renderHeader(body.header);
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
    renderLines();
});

loadDistributors();
