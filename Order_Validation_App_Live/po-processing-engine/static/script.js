const MULTILINE_FIELD_KEYS = new Set(["end_user_block", "reseller_block", "ship_to_block", "address_block", "delivery_address", "invoice_address", "licensee_address", "to_block", "supplier", "bill_to", "ship_to", "end_customer", "reseller", "freight_forwarder"]);
const LINE_ITEM_COLUMNS = ["part_number", "description", "qty", "unit_cost", "pct_disc", "terms"];

let currentSlug = null;
let currentLineItems = [];
// Values for field keys hidden from the Fields grid (see renderFields) --
// these still need to round-trip into the generate request, since generator.py
// expects a value for every key even when it derives/ignores it server-side.
let currentHiddenFieldValues = {};

async function checkHealth() {
    const statusEl = document.getElementById("status");
    try {
        const res = await fetch("/api/health");
        const data = await res.json();
        statusEl.textContent = `Server status: ${data.status}`;
    } catch (err) {
        statusEl.textContent = "Server status: unreachable";
    }
}

function showMessage(text, isError) {
    const el = document.getElementById("message");
    el.textContent = text;
    el.hidden = !text;
    el.classList.toggle("message-error", Boolean(isError));
}

async function loadSalesforceOrgs() {
    const select = document.getElementById("sf-org-select");
    try {
        const res = await fetch("/api/salesforce/orgs");
        const data = await res.json();
        select.innerHTML = "";
        for (const [alias, label] of Object.entries(data.orgs || {})) {
            const option = document.createElement("option");
            option.value = alias;
            option.textContent = `${label} (${alias})`;
            select.appendChild(option);
        }
        if (data.default) select.value = data.default;
    } catch (err) {
        showMessage("Could not load Salesforce org list.", true);
    }
}

function currentSalesforceOrg() {
    return document.getElementById("sf-org-select").value;
}

// Distributors hidden from the dropdown (still available via the API).
const HIDDEN_DISTRIBUTOR_SLUGS = new Set([
    "pt-synnex-metrodata-indonesia",
    "pt-ecs-indo-jaya",
    "hcl",
    "exclusive-networks-turkey",
    "exclusive-networks-south-africa",
    "arrow-ecs-sau",
]);

async function loadDistributors() {
    const select = document.getElementById("distributor-select");
    try {
        const res = await fetch("/api/distributors");
        const distributors = await res.json();
        select.innerHTML = "";
        for (const [slug, name] of Object.entries(distributors)) {
            if (HIDDEN_DISTRIBUTOR_SLUGS.has(slug)) continue;
            const option = document.createElement("option");
            option.value = slug;
            option.textContent = name;
            select.appendChild(option);
        }
    } catch (err) {
        showMessage("Could not load distributor list.", true);
    }
}

function renderFields(fields, hiddenKeys) {
    const hidden = new Set(hiddenKeys || []);
    currentHiddenFieldValues = {};
    const grid = document.getElementById("fields-grid");
    grid.innerHTML = "";
    for (const [key, value] of Object.entries(fields)) {
        if (hidden.has(key)) {
            currentHiddenFieldValues[key] = value || "";
            continue;
        }
        const wrapper = document.createElement("div");
        wrapper.className = "field";

        const label = document.createElement("label");
        label.textContent = key;
        label.setAttribute("for", `field-${key}`);

        const input = MULTILINE_FIELD_KEYS.has(key)
            ? document.createElement("textarea")
            : document.createElement("input");
        input.id = `field-${key}`;
        input.dataset.key = key;
        input.value = value || "";
        if (input.tagName === "TEXTAREA") {
            input.rows = 4;
        } else {
            input.type = "text";
        }

        wrapper.appendChild(label);
        wrapper.appendChild(input);
        grid.appendChild(wrapper);
    }
}

function renderLineItems() {
    const body = document.getElementById("line-items-body");
    body.innerHTML = "";
    currentLineItems.forEach((item, index) => {
        const row = document.createElement("tr");
        // Display-only row number: derived from position on every render and
        // never written into currentLineItems, so it isn't sent to /generate.
        const serialCell = document.createElement("td");
        serialCell.className = "serial-col";
        serialCell.textContent = String(index + 1);
        row.appendChild(serialCell);
        for (const col of LINE_ITEM_COLUMNS) {
            const cell = document.createElement("td");
            const input = document.createElement("input");
            input.type = "text";
            input.dataset.row = String(index);
            input.dataset.field = col;
            input.value = item[col] || "";
            input.addEventListener("input", () => {
                currentLineItems[index][col] = input.value;
            });
            cell.appendChild(input);
            row.appendChild(cell);
        }
        const removeCell = document.createElement("td");
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "secondary";
        removeBtn.textContent = "Remove";
        removeBtn.addEventListener("click", () => {
            currentLineItems.splice(index, 1);
            renderLineItems();
        });
        removeCell.appendChild(removeBtn);
        row.appendChild(removeCell);
        body.appendChild(row);
    });
}

function addEmptyRow() {
    currentLineItems.push({ part_number: "", description: "", qty: "", unit_cost: "", pct_disc: "", terms: "" });
    renderLineItems();
}

async function searchSalesforceQuotes() {
    const term = document.getElementById("sf-quote-search").value.trim();
    const resultsEl = document.getElementById("sf-search-results");
    if (term.length < 2) {
        showMessage("Enter at least 2 characters to search.", true);
        return;
    }
    const org = currentSalesforceOrg();
    showMessage(`Searching Salesforce (${org})…`, false);
    try {
        const res = await fetch(`/api/salesforce/quotes/search?q=${encodeURIComponent(term)}&org=${encodeURIComponent(org)}`);
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            showMessage(body.detail || `Salesforce search failed (${res.status}).`, true);
            resultsEl.hidden = true;
            return;
        }
        const quotes = await res.json();
        renderSalesforceResults(quotes);
        showMessage(quotes.length ? `Found ${quotes.length} quote(s) in ${org}.` : `No quotes matched in ${org}.`, false);
    } catch (err) {
        showMessage("Could not reach Salesforce search.", true);
    }
}

function renderSalesforceResults(quotes) {
    const resultsEl = document.getElementById("sf-search-results");
    resultsEl.innerHTML = "";
    resultsEl.hidden = quotes.length === 0;
    for (const quote of quotes) {
        const li = document.createElement("li");
        const label = document.createElement("span");
        label.textContent = `${quote.name} — ${quote.account_name || "?"} (${quote.opportunity_name || "?"})`;
        const useBtn = document.createElement("button");
        useBtn.type = "button";
        useBtn.className = "secondary";
        useBtn.textContent = "Use this Quote";
        useBtn.addEventListener("click", () => useSalesforceQuote(quote.id));
        li.appendChild(label);
        li.appendChild(useBtn);
        resultsEl.appendChild(li);
    }
}

async function useSalesforceQuote(quoteId) {
    const org = currentSalesforceOrg();
    showMessage(`Pulling quote data from Salesforce (${org})…`, false);
    try {
        const slugParam = currentSlug ? `&slug=${encodeURIComponent(currentSlug)}` : "";
        const res = await fetch(`/api/salesforce/quotes/${encodeURIComponent(quoteId)}/data?org=${encodeURIComponent(org)}${slugParam}`);
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            showMessage(body.detail || `Could not pull quote data (${res.status}).`, true);
            return;
        }
        const data = await res.json();

        if (data.suggested_slug) {
            document.getElementById("distributor-select").value = data.suggested_slug;
            await loadTemplate();
        } else if (!currentSlug) {
            const note = data.distributor_name
                ? `No distributor mapping found for "${data.distributor_name}". Select a distributor, load its template, then click "Use this Quote" again.`
                : "No distributor could be determined. Select a distributor, load its template, then click \"Use this Quote\" again.";
            showMessage(note, true);
            return;
        }

        // Keys whose value replaces only the first line of a multi-line box. A
        // distributor whose template has no such box (e.g. Arrow Netherlands has a
        // plain end_user_company field) falls through to the ordinary field below.
        // end_customer is itself the multi-line box (company, address, contact), so its first line is swapped in place.
        const FIRST_LINE_KEYS = { end_user_company: "end_user_block", licensee_company: "licensee_address", end_customer: "end_customer" };
        for (const [key, value] of Object.entries(data.fields || {})) {
            const block = key in FIRST_LINE_KEYS ? document.getElementById(`field-${FIRST_LINE_KEYS[key]}`) : null;
            if (block) {
                // Swap only the company line and keep the address, contact, phone and email lines.
                const rest = block.value.split("\n").slice(1);
                block.value = [value, ...rest].join("\n");
                continue;
            }
            const input = document.getElementById(`field-${key}`);
            if (input) {
                input.value = value;
            } else if (key in currentHiddenFieldValues) {
                currentHiddenFieldValues[key] = value;
            }
        }
        currentLineItems = data.line_items || [];
        renderLineItems();
        showMessage(`Quote data merged from ${org}. Review fields/line items before generating.`, false);
    } catch (err) {
        showMessage("Could not pull quote data from Salesforce.", true);
    }
}

async function loadTemplate() {
    const slug = document.getElementById("distributor-select").value;
    if (!slug) return;
    showMessage("Loading template…", false);
    try {
        const res = await fetch(`/api/distributors/${encodeURIComponent(slug)}/template`);
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            showMessage(body.detail || `Could not load template (${res.status}).`, true);
            document.getElementById("workspace").hidden = true;
            return;
        }
        const data = await res.json();
        currentSlug = slug;
        // The template's sample SKUs belong to the sample PO, not the user's
        // order, so start with no rows; a Quote pull or "+ Add line item" fills them.
        currentLineItems = [];
        renderFields(data.fields || {}, data.hidden_fields || []);
        renderLineItems();
        document.getElementById("workspace").hidden = false;
        showMessage("Template loaded. Edit fields/line items below.", false);
    } catch (err) {
        showMessage("Could not load template.", true);
    }
}

function collectFieldValues() {
    const values = { ...currentHiddenFieldValues };
    document.querySelectorAll("#fields-grid [data-key]").forEach((el) => {
        values[el.dataset.key] = el.value;
    });
    return values;
}

let lastPreviewUrl = null;

async function fetchGeneratedPdf(preview = false) {
    const res = await fetch(`/api/distributors/${encodeURIComponent(currentSlug)}/generate${preview ? "?preview=true" : ""}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: collectFieldValues(), line_items: currentLineItems }),
    });
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Could not generate PDF (${res.status}).`);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : `${currentSlug}.pdf`;
    return { blob, filename };
}

async function generateAndDownload() {
    if (!currentSlug) return;
    showMessage("Generating PDF…", false);
    try {
        const { blob, filename } = await fetchGeneratedPdf();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        showMessage("PDF generated and downloaded.", false);
        loadHistory();
    } catch (err) {
        showMessage(err.message || "Could not generate PDF.", true);
    }
}

async function previewPdf() {
    if (!currentSlug) return;
    showMessage("Generating preview…", false);
    try {
        const { blob } = await fetchGeneratedPdf(true);
        if (lastPreviewUrl) URL.revokeObjectURL(lastPreviewUrl);
        lastPreviewUrl = URL.createObjectURL(blob);
        document.getElementById("pdf-preview-frame").src = lastPreviewUrl;
        document.getElementById("pdf-preview-container").hidden = false;
        showMessage("Preview updated.", false);
    } catch (err) {
        showMessage(err.message || "Could not generate preview.", true);
    }
}

// ── History: past generated / converted POs, listed in the left panel ──
const historyList = document.getElementById("history-list");
const historyEmpty = document.getElementById("history-empty");
const historyClear = document.getElementById("history-clear");

// The time of day only: entries sit under a heading for their date, so the date isn't repeated.
function formatHistoryTime(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Local calendar day of an entry, as YYYY-MM-DD (the grouping key), or "" if unreadable.
function historyDayKey(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${date.getFullYear()}-${month}-${day}`;
}

// "Today", "Yesterday", otherwise e.g. "Mon, 27 Oct 2026".
function historyDayLabel(dayKey) {
    if (!dayKey) return "Earlier";
    const [year, month, day] = dayKey.split("-").map(Number);
    const date = new Date(year, month - 1, day);
    const startOfToday = new Date();
    startOfToday.setHours(0, 0, 0, 0);
    const daysAgo = Math.round((startOfToday - date) / 86400000);
    if (daysAgo === 0) return "Today";
    if (daysAgo === 1) return "Yesterday";
    return date.toLocaleDateString([], { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
}

async function loadHistory() {
    try {
        const res = await fetch("/api/history");
        if (!res.ok) throw new Error();
        const { entries } = await res.json();
        renderHistory(entries);
    } catch (err) {
        historyEmpty.textContent = "Could not load history.";
        historyEmpty.hidden = false;
    }
}

function renderHistory(entries) {
    historyList.innerHTML = "";
    historyEmpty.textContent = "No POs yet. Generate or convert one and it will show up here.";
    historyEmpty.hidden = entries.length > 0;
    historyClear.hidden = entries.length === 0;
    // Entries arrive newest first, so a new date heading goes in whenever the day changes.
    let currentDay = null;
    for (const entry of entries) {
        const dayKey = historyDayKey(entry.timestamp);
        if (dayKey !== currentDay) {
            currentDay = dayKey;
            const heading = document.createElement("li");
            heading.className = "history-day";
            heading.setAttribute("role", "presentation");
            heading.textContent = historyDayLabel(dayKey);
            historyList.appendChild(heading);
        }
        const li = document.createElement("li");

        const open = document.createElement("button");
        open.type = "button";
        open.className = "history-item";
        open.title = "Load this PO back into the form";

        const title = document.createElement("span");
        title.className = "history-item-title";
        const badge = document.createElement("span");
        badge.className = "history-badge";
        badge.textContent = entry.action;
        title.appendChild(badge);
        // Title: quote number followed by the distributor name. A PO with no quote number
        // falls back to its PO number, so the entry is never untitled.
        const heading = entry.quote_number || entry.po_number || "(no quote number)";
        title.appendChild(document.createTextNode(`${heading} - ${entry.distributor}`));
        title.title = `${heading} - ${entry.distributor}`;

        const meta = document.createElement("span");
        meta.className = "history-item-meta";
        const metaParts = [];
        if (entry.po_number && entry.po_number !== heading) metaParts.push(`PO ${entry.po_number}`);
        metaParts.push(`${entry.line_count} line${entry.line_count === 1 ? "" : "s"}`, formatHistoryTime(entry.timestamp));
        meta.textContent = metaParts.join(" · ");

        open.appendChild(title);
        open.appendChild(meta);
        open.addEventListener("click", () => restoreHistoryEntry(entry.id));

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "history-delete";
        remove.title = "Remove from history";
        remove.setAttribute("aria-label", "Remove from history");
        remove.textContent = "×";
        remove.addEventListener("click", async (event) => {
            event.stopPropagation();
            await fetch(`/api/history/${encodeURIComponent(entry.id)}`, { method: "DELETE" }).catch(() => {});
            loadHistory();
        });

        li.style.position = "relative";
        li.appendChild(open);
        li.appendChild(remove);
        historyList.appendChild(li);
    }
}

async function restoreHistoryEntry(entryId) {
    showMessage("Loading from history…", false);
    try {
        const res = await fetch(`/api/history/${encodeURIComponent(entryId)}`);
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            showMessage(body.detail || `Could not load that entry (${res.status}).`, true);
            loadHistory();
            return;
        }
        const entry = await res.json();
        const select = document.getElementById("distributor-select");
        if (![...select.options].some((option) => option.value === entry.slug)) {
            showMessage(`${entry.distributor} is no longer in the distributor list, so this entry can't be reloaded.`, true);
            return;
        }
        select.value = entry.slug;
        await loadTemplate();
        if (currentSlug !== entry.slug) return; // the template failed to load; loadTemplate already said why
        for (const [key, value] of Object.entries(entry.fields || {})) {
            const input = document.getElementById(`field-${key}`);
            if (input) {
                input.value = value;
            } else if (key in currentHiddenFieldValues) {
                currentHiddenFieldValues[key] = value;
            }
        }
        currentLineItems = entry.line_items || [];
        renderLineItems();
        showMessage(`Loaded ${entry.quote_number || entry.po_number || "PO"} from history. Review it before generating again.`, false);
    } catch (err) {
        showMessage("Could not load that history entry.", true);
    }
}

historyClear.addEventListener("click", async () => {
    if (!window.confirm("Remove every entry from the history?")) return;
    await fetch("/api/history", { method: "DELETE" }).catch(() => {});
    loadHistory();
});

// ── Convert & Download: pick a format, get the PO in that format ──
const convertBtn = document.getElementById("convert-btn");
const convertOptions = document.getElementById("convert-options");
let convertFormatsLoaded = false;

function setConvertMenu(open) {
    convertOptions.hidden = !open;
    convertBtn.setAttribute("aria-expanded", String(open));
}

async function loadConvertFormats() {
    if (convertFormatsLoaded) return true;
    try {
        const res = await fetch("/api/convert/formats");
        if (!res.ok) throw new Error();
        const { formats } = await res.json();
        convertOptions.innerHTML = "";
        for (const { key, label } of formats) {
            const li = document.createElement("li");
            li.setAttribute("role", "none");
            const option = document.createElement("button");
            option.type = "button";
            option.setAttribute("role", "menuitem");
            option.dataset.format = key;
            option.textContent = label;
            option.addEventListener("click", () => convertAndDownload(key, label));
            li.appendChild(option);
            convertOptions.appendChild(li);
        }
        convertFormatsLoaded = true;
        return true;
    } catch (err) {
        showMessage("Could not load the conversion formats.", true);
        return false;
    }
}

async function convertAndDownload(format, label) {
    if (!currentSlug) return;
    setConvertMenu(false);
    showMessage(`Converting to ${label}…`, false);
    convertBtn.disabled = true;
    try {
        const res = await fetch(`/api/distributors/${encodeURIComponent(currentSlug)}/convert/${encodeURIComponent(format)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fields: collectFieldValues(), line_items: currentLineItems }),
        });
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail || `Could not convert to ${label} (${res.status}).`);
        }
        const blob = await res.blob();
        const disposition = res.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename="?([^"]+)"?/);
        const filename = match ? match[1] : `${currentSlug}.${format}`;
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        showMessage(`Converted to ${label} and downloaded (${filename}).`, false);
        loadHistory();
    } catch (err) {
        showMessage(err.message || `Could not convert to ${label}.`, true);
    } finally {
        convertBtn.disabled = false;
    }
}

convertBtn.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (!convertOptions.hidden) {
        setConvertMenu(false);
        return;
    }
    if (await loadConvertFormats()) setConvertMenu(true);
});
document.addEventListener("click", (event) => {
    if (!event.target.closest(".convert-menu")) setConvertMenu(false);
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setConvertMenu(false);
});

document.getElementById("sf-search-btn").addEventListener("click", searchSalesforceQuotes);
document.getElementById("sf-quote-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") searchSalesforceQuotes();
});
document.getElementById("load-template-btn").addEventListener("click", loadTemplate);
document.getElementById("add-row-btn").addEventListener("click", addEmptyRow);
document.getElementById("preview-btn").addEventListener("click", previewPdf);
document.getElementById("generate-btn").addEventListener("click", generateAndDownload);

checkHealth();
loadDistributors();
loadSalesforceOrgs();
loadHistory();
