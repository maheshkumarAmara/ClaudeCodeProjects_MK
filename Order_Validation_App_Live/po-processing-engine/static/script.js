const MULTILINE_FIELD_KEYS = new Set(["end_user_block", "reseller_block", "ship_to_block", "address_block", "delivery_address", "invoice_address"]);
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

        for (const [key, value] of Object.entries(data.fields || {})) {
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

async function fetchGeneratedPdf() {
    const res = await fetch(`/api/distributors/${encodeURIComponent(currentSlug)}/generate`, {
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
    } catch (err) {
        showMessage(err.message || "Could not generate PDF.", true);
    }
}

async function previewPdf() {
    if (!currentSlug) return;
    showMessage("Generating preview…", false);
    try {
        const { blob } = await fetchGeneratedPdf();
        if (lastPreviewUrl) URL.revokeObjectURL(lastPreviewUrl);
        lastPreviewUrl = URL.createObjectURL(blob);
        document.getElementById("pdf-preview-frame").src = lastPreviewUrl;
        document.getElementById("pdf-preview-container").hidden = false;
        showMessage("Preview updated.", false);
    } catch (err) {
        showMessage(err.message || "Could not generate preview.", true);
    }
}

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
