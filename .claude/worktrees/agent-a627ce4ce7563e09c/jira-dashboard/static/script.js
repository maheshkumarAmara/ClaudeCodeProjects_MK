let allIssues = [];
let selectedProjects = [];
let selectedSprints = [];
let selectedSprintNames = [];
let selectedStatuses = [];
let statusOperator = "equals";
let selectedQaContacts = [];
let qaOperator = "equals";
let lastFetchedType = "";
let currentSort = "key";
let lastFetchTime = null;

// ── Filter Persistence ──────────────────────────────────────────────────────
let _pendingRestoreData = (function() {
    try { return JSON.parse(localStorage.getItem("jd_filters") || "null"); } catch { return null; }
})();

function saveFiltersToStorage() {
    try {
        localStorage.setItem("jd_filters", JSON.stringify({
            projects:      selectedProjects,
            sprints:       selectedSprints,
            sprintNames:   selectedSprintNames,
            statuses:      selectedStatuses,
            statusOperator,
            qaContacts:    selectedQaContacts,
            qaOperator,
            dateFrom:      document.getElementById("date-from")?.value || "",
            dateTo:        document.getElementById("date-to")?.value || "",
            tab:           activeTab,
            typeFilter:    document.getElementById("filter-type")?.value || "",
            sortBy:        document.getElementById("sort-by")?.value || "key",
            showPassFail:  document.getElementById("toggle-pass-fail")?.checked ?? true,
            qaTableSort,
        }));
    } catch {}
}

function updateFreshnessDisplay() {
    const el = document.getElementById("fetch-freshness");
    if (!el || !lastFetchTime) return;
    const mins = Math.floor((Date.now() - lastFetchTime) / 60000);
    el.textContent = mins < 1 ? "Fetched just now" : mins === 1 ? "Fetched 1 min ago" : `Fetched ${mins} min ago`;
    el.style.display = "";
}

setInterval(updateFreshnessDisplay, 30000);

function sortIssues(issues) {
    const priorityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
    return [...issues].sort((a, b) => {
        switch (currentSort) {
            case "priority":
                return (priorityOrder[getPriorityClass(a.priority)] ?? 9) -
                       (priorityOrder[getPriorityClass(b.priority)] ?? 9);
            case "created-desc":
                return new Date(b.created || 0) - new Date(a.created || 0);
            case "created-asc":
                return new Date(a.created || 0) - new Date(b.created || 0);
            case "status":
                return (a.status || "").localeCompare(b.status || "");
            case "key":
                return (a.key || "").localeCompare(b.key || "");
            default:
                return 0;
        }
    });
}

const PRODOPS_QA_TEAM = [
    "Ashish Samar",
    "Ashwini Koppad",
    "Bhavani Marupaka",
    "Karthik Surada",
    "Teekshna Vallivireddy",
    "US Mahesh Reddy",
    "Urati Sai Krishna",
    "Amara MaheshKumar",
    "Shashi Kumar",
];

const EPIC_SIGNOFF_TASK_NAMES = [
    "QA: ProdOps Sign-Off",
    "QA: Revenue Sign-Off",
    "QA: CPQ Sign-off",
];

// --- Project Multi-Select ---

function initProjectDropdown() {
    const toggle = document.getElementById("project-toggle");
    const dropdown = document.getElementById("project-dropdown");

    toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdown.classList.toggle("open");
    });

    document.addEventListener("click", (e) => {
        if (!e.target.closest("#project-multi-select")) {
            dropdown.classList.remove("open");
        }
    });
}

function populateProjectDropdown(projects) {
    const dropdown = document.getElementById("project-dropdown");

    const pinned = ["PRDOPS", "ITNPI", "GTMIT"];
    projects.sort((a, b) => {
        const aPin = pinned.indexOf(a.key);
        const bPin = pinned.indexOf(b.key);
        if (aPin !== -1 && bPin !== -1) return aPin - bPin;
        if (aPin !== -1) return -1;
        if (bPin !== -1) return 1;
        return a.key.localeCompare(b.key);
    });

    let html = '<input type="text" id="project-search" class="multi-select-search" placeholder="Search boards...">';
    projects.forEach((p) => {
        const checked = "";
        html += `
            <label class="multi-select-item" data-label="${p.key} - ${p.name}">
                <input type="checkbox" value="${p.key}" data-project ${checked}>
                <span>${p.key} - ${p.name}</span>
            </label>
        `;
    });

    html += `
        <div class="multi-select-actions">
            <button id="project-select-all">Select All</button>
            <button id="project-clear-all">Clear All</button>
        </div>
    `;

    dropdown.innerHTML = html;

    document.getElementById("project-search").addEventListener("input", (e) => {
        const query = e.target.value.toLowerCase();
        dropdown.querySelectorAll(".multi-select-item[data-label]").forEach((item) => {
            const label = item.getAttribute("data-label").toLowerCase();
            item.style.display = label.includes(query) ? "" : "none";
        });
    });

    document.getElementById("project-search").addEventListener("click", (e) => {
        e.stopPropagation();
    });

    dropdown.querySelectorAll("input[data-project]").forEach((cb) => {
        cb.addEventListener("change", onProjectCheckboxChange);
    });

    document.getElementById("project-select-all").addEventListener("click", () => {
        dropdown.querySelectorAll("input[data-project]").forEach((cb) => { cb.checked = true; });
        onProjectCheckboxChange();
    });

    document.getElementById("project-clear-all").addEventListener("click", () => {
        dropdown.querySelectorAll("input[data-project]").forEach((cb) => { cb.checked = false; });
        onProjectCheckboxChange();
    });

    // Restore saved project selections, or pre-select DEFAULT_PROJECT on first load
    if (_pendingRestoreData?.projects?.length > 0) {
        dropdown.querySelectorAll("input[data-project]").forEach(cb => {
            cb.checked = _pendingRestoreData.projects.includes(cb.value);
        });
    } else if (DEFAULT_PROJECT) {
        const defaultCb = dropdown.querySelector(`input[data-project][value="${DEFAULT_PROJECT}"]`);
        if (defaultCb) defaultCb.checked = true;
    }
    const checked = dropdown.querySelectorAll("input[data-project]:checked");
    selectedProjects = Array.from(checked).map((cb) => cb.value);
    updateProjectToggleLabel();
}

function onProjectCheckboxChange() {
    const dropdown = document.getElementById("project-dropdown");
    const checked = dropdown.querySelectorAll("input[data-project]:checked");
    selectedProjects = Array.from(checked).map((cb) => cb.value);
    updateProjectToggleLabel();
    updateEpicOptionVisibility();
    saveFiltersToStorage();
    onProjectChange();
}

function updateEpicOptionVisibility() {
    const epicOption = document.querySelector('#filter-type option[value="epic"]');
    if (!epicOption) return;
    const hasITNPI = selectedProjects.includes("ITNPI");
    epicOption.style.display = hasITNPI ? "" : "none";
    if (!hasITNPI && document.getElementById("filter-type").value === "epic") {
        document.getElementById("filter-type").value = "";
    }
}

function updateProjectToggleLabel() {
    const toggle = document.getElementById("project-toggle");
    if (selectedProjects.length === 0) {
        toggle.textContent = "-- Select Board --";
    } else if (selectedProjects.length === 1) {
        toggle.textContent = selectedProjects[0];
    } else {
        toggle.textContent = `${selectedProjects.length} Boards Selected`;
    }
}

// --- Sprint Multi-Select ---

function initSprintDropdown() {
    const toggle = document.getElementById("sprint-toggle");
    const dropdown = document.getElementById("sprint-dropdown");

    toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdown.classList.toggle("open");
    });

    document.addEventListener("click", (e) => {
        if (!e.target.closest("#sprint-multi-select")) {
            dropdown.classList.remove("open");
        }
    });
}

function populateSprintDropdown(sprints) {
    const dropdown = document.getElementById("sprint-dropdown");
    selectedSprints = [];
    updateSprintToggleLabel();

    if (sprints.length === 0) {
        dropdown.innerHTML = '<div class="multi-select-item" style="color:#6b778c;">No sprints available</div>';
        return;
    }

    const stateOrder = { active: 0, future: 1, closed: 2 };
    sprints.sort((a, b) => (stateOrder[a.state] ?? 9) - (stateOrder[b.state] ?? 9));

    let html = "";
    sprints.forEach((s) => {
        const stateLabel = s.state === "active" ? "Active" : s.state === "future" ? "Future" : "Closed";
        html += `
            <label class="multi-select-item">
                <input type="checkbox" value="${s.id}" data-sprint data-sprint-name="${s.name}">
                <span>${s.name}</span>
                <span class="sprint-state">${stateLabel}</span>
            </label>
        `;
    });

    html += `
        <div class="multi-select-actions">
            <button id="sprint-select-all">Select All</button>
            <button id="sprint-clear-all">Clear All</button>
        </div>
    `;

    dropdown.innerHTML = html;

    dropdown.querySelectorAll("input[data-sprint]").forEach((cb) => {
        cb.addEventListener("change", onSprintCheckboxChange);
    });

    document.getElementById("sprint-select-all").addEventListener("click", () => {
        dropdown.querySelectorAll("input[data-sprint]").forEach((cb) => { cb.checked = true; });
        onSprintCheckboxChange();
    });

    document.getElementById("sprint-clear-all").addEventListener("click", () => {
        dropdown.querySelectorAll("input[data-sprint]").forEach((cb) => { cb.checked = false; });
        onSprintCheckboxChange();
    });

    // Restore saved sprint selections
    if (_pendingRestoreData?.sprints?.length > 0) {
        const storedIds = new Set(_pendingRestoreData.sprints);
        dropdown.querySelectorAll("input[data-sprint]").forEach(cb => {
            cb.checked = storedIds.has(cb.value);
        });
        const checkedSprints = dropdown.querySelectorAll("input[data-sprint]:checked");
        selectedSprints = Array.from(checkedSprints).map(cb => cb.value);
        selectedSprintNames = Array.from(checkedSprints).map(cb => cb.getAttribute("data-sprint-name"));
        updateSprintToggleLabel();
        updateDateRangeVisibility();
        _pendingRestoreData = null; // all state restored — consume the pending restore
    }
}

function onSprintCheckboxChange() {
    const dropdown = document.getElementById("sprint-dropdown");
    const checked = dropdown.querySelectorAll("input[data-sprint]:checked");
    selectedSprints = Array.from(checked).map((cb) => cb.value);
    selectedSprintNames = Array.from(checked).map((cb) => cb.getAttribute("data-sprint-name"));
    updateSprintToggleLabel();
    updateDateRangeVisibility();
    saveFiltersToStorage();
    fetchIssues();
}

// --- Date Range Filter ---

function getDateRange() {
    if (selectedSprints.length > 0) return { from: "", to: "" };
    return {
        from: document.getElementById("date-from").value,
        to: document.getElementById("date-to").value,
    };
}

function buildDateParams() {
    const { from, to } = getDateRange();
    if (!from && !to) return "";
    return (from ? `&created_from=${from}` : "") + (to ? `&created_to=${to}` : "");
}

function updateDateRangeVisibility() {
    const container = document.getElementById("date-range-filter");
    const clearBtn = document.getElementById("btn-clear-dates");
    const hasSprintsSelected = selectedSprints.length > 0;

    if (hasSprintsSelected) {
        container.style.display = "none";
        document.getElementById("date-from").value = "";
        document.getElementById("date-to").value = "";
        clearBtn.style.display = "none";
        container.classList.remove("has-dates");
    } else {
        container.style.display = "flex";
        const { from, to } = getDateRange();
        const hasDates = !!(from || to);
        clearBtn.style.display = hasDates ? "" : "none";
        container.classList.toggle("has-dates", hasDates);
    }
}

function onDateRangeChange() {
    const { from, to } = getDateRange();
    const hasDates = !!(from || to);
    const clearBtn = document.getElementById("btn-clear-dates");
    const container = document.getElementById("date-range-filter");
    clearBtn.style.display = hasDates ? "" : "none";
    container.classList.toggle("has-dates", hasDates);
    saveFiltersToStorage();

    allIssues = [];
    qaTrackingLoaded = false;
    alertsLoaded = false;
    metricsLoaded = false;

    if (activeTab === "status") fetchIssues();
    else if (activeTab === "qa-tracking") fetchQaTracking();
    else if (activeTab === "alerts") fetchAlerts();
    else if (activeTab === "metrics") fetchMetrics();
}

function updateSprintToggleLabel() {
    const toggle = document.getElementById("sprint-toggle");
    if (selectedSprints.length === 0) {
        toggle.textContent = "All Sprints";
    } else if (selectedSprintNames.length === 1) {
        toggle.textContent = selectedSprintNames[0];
    } else {
        toggle.textContent = `${selectedSprints.length} Sprints Selected`;
    }
}

// --- Data Loading ---

async function loadProjects() {
    const loading = document.getElementById("loading");
    const error = document.getElementById("error");

    loading.style.display = "block";
    loading.textContent = "Loading boards...";
    error.style.display = "none";

    try {
        const resp = await fetch("/api/projects");
        const data = await resp.json();

        if (!resp.ok) {
            throw new Error(data.error || "Failed to fetch projects.");
        }

        populateProjectDropdown(data);

        if (selectedProjects.length > 0) {
            await onProjectChange();
        } else {
            loading.style.display = "none";
        }
    } catch (err) {
        error.textContent = err.message;
        error.style.display = "block";
        loading.style.display = "none";
    }
}

async function loadSprints() {
    if (selectedProjects.length === 0) {
        populateSprintDropdown([]);
        return;
    }

    try {
        const responses = await Promise.all(
            selectedProjects.map((proj) => fetch(`/api/sprints?project=${proj}`))
        );
        const allSprints = [];
        const seenIds = new Set();

        for (const resp of responses) {
            const data = await resp.json();
            if (resp.ok && Array.isArray(data)) {
                data.forEach((s) => {
                    if (!seenIds.has(s.id)) {
                        seenIds.add(s.id);
                        allSprints.push(s);
                    }
                });
            }
        }

        populateSprintDropdown(allSprints);
    } catch {
        populateSprintDropdown([]);
    }
}

async function loadQaContacts() {
    const dropdown = document.getElementById("qa-dropdown");
    if (selectedProjects.length === 0) {
        dropdown.innerHTML = "";
        updateQaToggleLabel();
        return;
    }
    document.getElementById("qa-toggle").textContent = "Loading...";
    try {
        const resp = await fetch(`/api/qa-contacts?projects=${selectedProjects.join(",")}`);
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Failed");

        let html = "";
        data.forEach((contact) => {
            const checked = selectedQaContacts.includes(contact.name) ? "checked" : "";
            html += `
                <label class="multi-select-item">
                    <input type="checkbox" value="${contact.name}" data-qa-contact ${checked}
                           data-account-id="${contact.accountId || ""}">
                    <span>${contact.name}</span>
                </label>
            `;
        });
        html += `
            <div class="multi-select-actions">
                <button id="qa-select-all">Select All</button>
                <button id="qa-clear-all">Clear All</button>
            </div>
        `;
        dropdown.innerHTML = html;

        dropdown.querySelectorAll("input[data-qa-contact]").forEach(cb => {
            cb.addEventListener("change", onQaContactCheckboxChange);
        });
        document.getElementById("qa-select-all").addEventListener("click", () => {
            dropdown.querySelectorAll("input[data-qa-contact]").forEach(cb => { cb.checked = true; });
            onQaContactCheckboxChange();
        });
        document.getElementById("qa-clear-all").addEventListener("click", () => {
            dropdown.querySelectorAll("input[data-qa-contact]").forEach(cb => { cb.checked = false; });
            onQaContactCheckboxChange();
        });
    } catch {
        dropdown.innerHTML = "";
    }
    updateQaToggleLabel();
}

function initQaContactDropdown() {
    const toggle = document.getElementById("qa-toggle");
    const dropdown = document.getElementById("qa-dropdown");
    const operatorBtn = document.getElementById("qa-operator");

    toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdown.classList.toggle("open");
    });

    document.addEventListener("click", (e) => {
        if (!e.target.closest("#qa-multi-select")) {
            dropdown.classList.remove("open");
        }
    });

    operatorBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        qaOperator = qaOperator === "equals" ? "not-equals" : "equals";
        operatorBtn.textContent = qaOperator === "equals" ? "=" : "≠";
        operatorBtn.classList.toggle("not-equals", qaOperator === "not-equals");
        updateQaToggleLabel();
        saveFiltersToStorage();
        if (selectedQaContacts.length > 0) {
            if (activeTab === "status") renderBoard();
            else if (activeTab === "qa-tracking" && qaTrackingLoaded) renderQaTrackingFiltered();
            else if (activeTab === "alerts" && alertsLoaded) renderAlertsFiltered();
        }
    });
}

function onQaContactCheckboxChange() {
    const dropdown = document.getElementById("qa-dropdown");
    selectedQaContacts = Array.from(dropdown.querySelectorAll("input[data-qa-contact]:checked")).map(cb => cb.value);
    updateQaToggleLabel();
    saveFiltersToStorage();

    if (activeTab === "status") {
        if (selectedProjects.length === 0) {
            if (selectedQaContacts.length > 0 && qaOperator === "equals") {
                fetchAllProjectIssuesByQaContacts(selectedQaContacts);
            } else if (selectedQaContacts.length === 0) {
                allIssues = [];
                renderBoard();
            } else {
                renderBoard();
            }
        } else {
            renderBoard();
        }
    } else if (activeTab === "qa-tracking" && qaTrackingLoaded) {
        renderQaTrackingFiltered();
    } else if (activeTab === "alerts" && alertsLoaded) {
        renderAlertsFiltered();
    }
}

function updateQaToggleLabel() {
    const toggle = document.getElementById("qa-toggle");
    const prefix = qaOperator === "not-equals" ? "≠ " : "";
    if (selectedQaContacts.length === 0) {
        toggle.textContent = "All QA Contacts";
    } else if (selectedQaContacts.length === 1) {
        toggle.textContent = `${prefix}${selectedQaContacts[0]}`;
    } else {
        toggle.textContent = `${prefix}${selectedQaContacts.length} Contacts`;
    }
}

async function onProjectChange() {
    selectedSprints = [];
    selectedSprintNames = [];
    document.getElementById("filter-type").value = "";
    selectedStatuses = [];
    statusOperator = "equals";
    document.getElementById("status-operator").textContent = "=";
    document.getElementById("status-operator").classList.remove("not-equals");
    updateStatusToggleLabel();
    selectedQaContacts = [];
    qaOperator = "equals";
    document.getElementById("qa-operator").textContent = "=";
    document.getElementById("qa-operator").classList.remove("not-equals");
    updateQaToggleLabel();
    qaTrackingLoaded = false;
    alertsLoaded = false;
    metricsLoaded = false;

    // Restore persisted filter state if this is the initial page load
    const restore = _pendingRestoreData;
    _pendingRestoreData = null; // consume immediately — prevent re-apply on subsequent project changes
    if (restore) {
        if (restore.qaContacts?.length > 0) {
            selectedQaContacts = restore.qaContacts;
            qaOperator = restore.qaOperator || "equals";
            document.getElementById("qa-operator").textContent = qaOperator === "equals" ? "=" : "≠";
            document.getElementById("qa-operator").classList.toggle("not-equals", qaOperator !== "equals");
            updateQaToggleLabel();
        }
        if (restore.statuses?.length > 0) {
            selectedStatuses = restore.statuses;
            statusOperator = restore.statusOperator || "equals";
            document.getElementById("status-operator").textContent = statusOperator === "equals" ? "=" : "≠";
            document.getElementById("status-operator").classList.toggle("not-equals", statusOperator !== "equals");
            updateStatusToggleLabel();
        }
        if (restore.typeFilter) document.getElementById("filter-type").value = restore.typeFilter;
        if (restore.sortBy) { document.getElementById("sort-by").value = restore.sortBy; currentSort = restore.sortBy; }
        if (restore.dateFrom) document.getElementById("date-from").value = restore.dateFrom;
        if (restore.dateTo) document.getElementById("date-to").value = restore.dateTo;
        if (restore.showPassFail !== undefined) document.getElementById("toggle-pass-fail").checked = restore.showPassFail;
        if (restore.qaTableSort) { qaTableSort = restore.qaTableSort; }
    }

    await loadSprints();
    loadQaContacts();
    if (activeTab === "status") {
        await fetchIssues();
    } else if (activeTab === "qa-tracking") {
        await fetchQaTracking();
    } else if (activeTab === "metrics") {
        await fetchMetrics();
    } else {
        await fetchAlerts();
    }
}

async function fetchIssues() {
    const loading = document.getElementById("loading");
    const error = document.getElementById("error");
    const statsSection = document.getElementById("stats-section");
    const ownerSection = document.getElementById("owner-section");

    if (selectedProjects.length === 0) {
        loading.style.display = "none";
        statsSection.style.display = "none";
        ownerSection.style.display = "none";
        return;
    }

    const label = selectedProjects.length === 1 ? selectedProjects[0] : `${selectedProjects.length} boards`;
    loading.style.display = "block";
    loading.textContent = `Loading ${label} issues...`;
    error.style.display = "none";
    statsSection.style.display = "none";
    ownerSection.style.display = "none";

    try {
        const fetches = [];

        const typeFilter = document.getElementById("filter-type").value;
        const typeParam = typeFilter === "epic" ? "&type=epic" : "";
        const dateParams = buildDateParams();

        for (const proj of selectedProjects) {
            if (typeFilter === "epic") {
                // Epic view: one request per project — sprint filter multiplies requests
                // without benefit since _get_epic_issues fetches all epic children anyway
                fetches.push(fetch(`/api/issues?project=${proj}&type=epic${dateParams}`));
            } else if (selectedSprints.length === 0) {
                fetches.push(fetch(`/api/issues?project=${proj}${typeParam}${dateParams}`));
            } else {
                selectedSprints.forEach((sprintId) => {
                    fetches.push(fetch(`/api/issues?project=${proj}&sprintId=${sprintId}${typeParam}`));
                });
            }
        }

        const responses = await Promise.all(fetches);
        let combined = [];
        const seenKeys = new Set();

        for (const resp of responses) {
            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.error || "Failed to fetch issues.");
            }
            data.forEach((issue) => {
                if (!seenKeys.has(issue.key)) {
                    seenKeys.add(issue.key);
                    combined.push(issue);
                }
            });
        }

        allIssues = combined;
        lastFetchedType = typeFilter;
        populateStatusFilter(allIssues);
        renderBoard();
        lastFetchTime = Date.now();
        updateFreshnessDisplay();
        loadHealthScore();
    } catch (err) {
        error.textContent = err.message;
        error.style.display = "block";
    } finally {
        loading.style.display = "none";
    }
}

// --- Quality Checks ---

function checkQuality(issue) {
    const failures = [];
    const isITNPI = (issue.key || "").startsWith("ITNPI-");

    if (issue.issueType === "Task") {
        if (isITNPI && (issue.status || "").toLowerCase() === "open") {
            return { passed: false, failures: ["Signoff task is still Open"] };
        }
        return { passed: true, failures: [] };
    }

    if ((issue.status || "").toLowerCase() === "no action") {
        return { passed: true, failures: [] };
    }

    if (issue.issueType === "Epic") {
        const missingTasks = getMissingSignoffTasks(issue);
        for (const task of missingTasks) {
            failures.push(`Missing subtask: ${task}`);
        }
        if (isITNPI) {
            const openSignoffs = (issue.children || []).filter(c => {
                const s = c.summary.toLowerCase();
                const isSignoff = EPIC_SIGNOFF_TASK_NAMES.some(n => _itnpiSignoffMatches(s, n)) || s.includes("test case validation") || s.includes("test case preparation");
                return isSignoff && (c.status || "").toLowerCase() === "open";
            });
            for (const t of openSignoffs) {
                failures.push(`Signoff task still Open: ${t.summary}`);
            }
            const hasUnitTest = (issue.children || []).some(c => c.hasUnitTestSubtask);
            if (!hasUnitTest) {
                failures.push("Missing: Unit Testing subtask not created");
            } else if (!(issue.children || []).some(c => c.hasUnitTestSubtask && c.hasUnitTestComment)) {
                failures.push("Missing: Unit Test Results in comments");
            }
        }
        return { passed: failures.length === 0, failures };
    } else if (issue.issueType === "Story") {
        const subtasks = (issue.subtaskNames || []).map(s => s.toLowerCase());
        if (!isITNPI) {
            const hasExecution = subtasks.some(s => s.includes("test case execution") || s.includes("test cases execution") || s.includes("test execution"));
            if (!hasExecution) {
                failures.push("Missing subtask: Test Execution");
            }
            const hasDesign = subtasks.some(s => s.includes("test case creation") || s.includes("test case review") || s.includes("test design") || s.includes("test case design") || s.includes("test cases preparation") || s.includes("preparation") || s.includes("test case writing"));
            if (!hasDesign) {
                failures.push("Missing subtask: Test Case Design");
            }
            const hasUnitTest = subtasks.some(s => s.includes("unit test"));
            if (!hasUnitTest) {
                failures.push("Missing: Unit Testing subtask not created");
            } else if (!issue.hasUnitTestComment) {
                failures.push("Missing: Unit Test Results in comments");
            }
        }
        if (issue.designSubtaskInvalid) {
            failures.push("Subtask status invalid: Test Case Design subtask is still Open or In Progress");
        }
        if (issue.executionSubtaskInvalid) {
            failures.push("Subtask status invalid: Test Execution subtask is still Open or In Progress");
        }
        if (issue.tcSheetMissing) {
            failures.push("TC's Sheet not matched: Test Case Design subtask links to wrong or missing sheet");
        }
        if (issue.subtasksQaContactMissing && issue.subtasksQaContactMissing.length > 0) {
            for (const st of issue.subtasksQaContactMissing) {
                failures.push(`QA Contact missing on subtask: ${st.summary}`);
            }
        }
        if (issue.key.startsWith("PRDOPS-") && issue.qaUpdateMissing) {
            failures.push("Missing: QA progress update (no comment in 24h)");
        }
        if (issue.key.startsWith("PRDOPS-") && issue.uatSanityMissing) {
            failures.push("Missing: UAT Sanity Testing results comment");
        }
    } else {
        const rca = (issue.rca || "").trim();
        if (!rca) {
            failures.push("RCA is blank");
        }

        const rootCauseSummary = (issue.rootCauseSummary || "").trim();
        const placeholderText = "A short description of the actual root cause. If there are many root causes, list them here.";
        const cleanedSummary = rootCauseSummary.replace(/\\?\{color[^}]*\}/g, "").replace(/\s+/g, " ").trim();
        if (!cleanedSummary || cleanedSummary === placeholderText) {
            failures.push("Root Cause Summary is blank");
        }

        const sprints = issue.sprintNames || [];
        if (sprints.length === 0) {
            failures.push("Sprint is blank");
        }

        const qaName = issue.qaContact?.name || "";
        if (!qaName || qaName === "Unassigned") {
            failures.push("QA Contact is blank");
        }

        const desc = (issue.descriptionText || "").toLowerCase();

        // Steps to Reproduce: check Acceptance tab field first, fall back to description.
        // Regex covers: "steps to reproduce", "step to reproduce", "step to reproduct", etc.
        const stepsField = (issue.stepsToReproduce || "").trim();
        const hasStepsInDesc = /steps?\s+to\s+reprod/i.test(desc);
        if (!stepsField && !hasStepsInDesc) {
            failures.push("Missing: Steps to Reproduce");
        }

        // Expected & Actual: check Acceptance tab fields first, fall back to description
        const expectedField = (issue.expectedOutcome || "").trim();
        const actualField = (issue.actualOutcome || "").trim();
        const hasExpected = !!expectedField || desc.includes("expected");
        const hasActual = !!actualField || desc.includes("actual");
        if (!hasExpected || !hasActual) {
            failures.push("Missing: Expected & Actual Results");
        }

    }

    return { passed: failures.length === 0, failures };
}

function getMissingSubtasksList(issue) {
    const isITNPI = (issue.key || "").startsWith("ITNPI-");
    const existing = (issue.subtaskNames || []).map(s => s.toLowerCase());
    const missing = [];
    const hasDesign = existing.some(s =>
        s.includes("test case creation") || s.includes("test case review") ||
        s.includes("test design") || s.includes("test case design") ||
        s.includes("test case validation") || s.includes("test cases preparation") ||
        s.includes("preparation") || s.includes("test case writing")
    );
    if (!hasDesign) missing.push(isITNPI ? "QA: Test Case Validation" : "Test Case Design");
    if (!isITNPI) {
        const hasExecution = existing.some(s => s.includes("test case execution") || s.includes("test execution"));
        if (!hasExecution) missing.push("Test Execution");
    }
    return missing;
}

function buildSubtaskSelectorHtml(issueKey, missingSubtasks) {
    if (!missingSubtasks.length) return "";
    const checkboxes = missingSubtasks.map(name =>
        `<label class="subtask-checkbox-label">
            <input type="checkbox" class="subtask-cb" value="${name}" checked>
            <span>${name}</span>
        </label>`
    ).join("");
    return `<div class="subtask-selector">
        ${checkboxes}
        <button class="btn-create-subtasks" onclick="createSelectedSubtasks('${issueKey}', this)">+ Create Selected</button>
    </div>`;
}

async function createSelectedSubtasks(issueKey, btn) {
    const container = btn.closest(".subtask-selector");
    const checked = [...container.querySelectorAll(".subtask-cb:checked")].map(cb => cb.value);
    if (!checked.length) {
        btn.textContent = "Select at least one";
        setTimeout(() => { btn.textContent = "+ Create Selected"; }, 2000);
        return;
    }
    btn.disabled = true;
    btn.textContent = "Creating...";
    try {
        const resp = await fetch("/api/create-subtasks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                parentKey: issueKey,
                projectKey: issueKey.split("-")[0],
                subtasks: checked,
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Failed to create subtasks");
        btn.textContent = "Created!";
        setTimeout(() => fetchIssues(), 1000);
    } catch (err) {
        btn.textContent = "Error";
        btn.title = err.message;
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = "+ Create Selected";
        }, 3000);
    }
}

async function createSubtasks(issueKey, btn) {
    let issue = allIssues.find((i) => i.key === issueKey);
    if (!issue) {
        for (const parent of allIssues) {
            if (parent.children) {
                const child = parent.children.find(c => c.key === issueKey);
                if (child) { issue = child; break; }
            }
        }
    }
    if (!issue) return;

    const isITNPI = (issueKey || "").startsWith("ITNPI-");
    const existing = (issue.subtaskNames || []).map((s) => s.toLowerCase());
    const missing = [];
    const hasDesign = existing.some((s) => s.includes("test case creation") || s.includes("test case review") || s.includes("test design") || s.includes("test case design") || s.includes("test case validation"));
    if (!hasDesign) {
        missing.push(isITNPI ? "QA: Test Case Validation" : "Test Case Design");
    }
    if (!isITNPI) {
        const hasExecution = existing.some((s) => s.includes("test case execution") || s.includes("test execution"));
        if (!hasExecution) {
            missing.push("Test Execution");
        }
    }
    if (missing.length === 0) return;

    btn.disabled = true;
    btn.textContent = "Creating...";

    try {
        const resp = await fetch("/api/create-subtasks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                parentKey: issueKey,
                projectKey: issueKey.split("-")[0],
                subtasks: missing,
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Failed to create subtasks");
        btn.textContent = "Created!";
        setTimeout(() => fetchIssues(), 1000);
    } catch (err) {
        btn.textContent = "Error";
        btn.title = err.message;
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = "Create Subtasks";
        }, 3000);
    }
}

async function nudgeSanity(issueKey, qaContactName, qaAccountId, btn) {
    btn.disabled = true;
    btn.textContent = "Sending...";
    try {
        const resp = await fetch("/api/add-comment", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                issueKey,
                qaName: qaContactName,
                accountId: qaAccountId || null,
                messageSuffix: ", can you please start Sanity Testing and update the results?",
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Failed to send comment");
        btn.textContent = "Sent!";
        setTimeout(() => fetchIssues(), 1500);
    } catch (err) {
        btn.textContent = "Error";
        btn.title = err.message;
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = "UAT Sanity Results Missing";
        }, 3000);
    }
}

async function nudgeTestCaseDesign(subtaskKey, assigneeName, assigneeId, btn) {
    btn.disabled = true;
    btn.textContent = "Sending...";
    try {
        const resp = await fetch("/api/add-comment", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                issueKey: subtaskKey,
                qaName: assigneeName,
                accountId: assigneeId || null,
                messagePrefix: "Hi ",
                messageSuffix: ", can you pls review the test cases and update the status?",
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Failed to send comment");
        btn.textContent = "Sent!";
        setTimeout(() => fetchIssues(), 1500);
    } catch (err) {
        btn.textContent = "Error";
        btn.title = err.message;
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = "Nudge Test Case Design";
        }, 3000);
    }
}

async function nudgeRca(issueKey, assigneeName, assigneeAccountId, messageSuffix, btn) {
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Sending...";
    try {
        const resp = await fetch("/api/add-comment", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                issueKey,
                qaName: assigneeName,
                accountId: assigneeAccountId || null,
                messageSuffix,
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Failed to send comment");
        btn.textContent = "Sent!";
        setTimeout(() => fetchIssues(), 1500);
    } catch (err) {
        btn.textContent = "Error";
        btn.title = err.message;
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = originalLabel;
        }, 3000);
    }
}

async function nudgeQa(issueKey, qaContactName, qaAccountId, btn) {
    btn.disabled = true;
    btn.textContent = "Sending...";
    try {
        const resp = await fetch("/api/add-comment", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ issueKey, qaName: qaContactName, accountId: qaAccountId || null }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Failed to send comment");
        btn.textContent = "Sent!";
        setTimeout(() => fetchIssues(), 1500);
    } catch (err) {
        btn.textContent = "Error";
        btn.title = err.message;
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = "QA Updates Missing";
        }, 3000);
    }
}

function _itnpiSignoffMatches(existingSummary, expectedName) {
    const e = existingSummary.toLowerCase().replace(/-/g, " ");
    const stopWords = new Set(["qa", "sign", "off"]);
    const keywords = expectedName.toLowerCase().replace(/-/g, " ").split(/[\s:]+/).filter(w => w.length > 1 && !stopWords.has(w));
    return keywords.every(k => e.includes(k)) && e.includes("sign");
}

function getMissingSignoffTasks(epic) {
    const existing = (epic.children || []).map(c => c.summary.toLowerCase());
    const isITNPIEpic = epic.key.startsWith("ITNPI-");
    const missing = EPIC_SIGNOFF_TASK_NAMES.filter(name => {
        if (isITNPIEpic) {
            return !existing.some(e => _itnpiSignoffMatches(e, name));
        }
        return !existing.some(e => e === name.toLowerCase());
    });
    if (isITNPIEpic && !existing.some(e => e.includes("test case validation") || e.includes("test case preparation"))) {
        missing.push("QA: Test Case Validation");
    }
    return missing;
}

function updateSignoffBtn(epicKey) {
    const checked = document.querySelectorAll(`.signoff-task-checkbox[data-epic="${epicKey}"]:checked`).length;
    const btn = document.querySelector(`.btn-create-signoff-tasks[data-epic="${epicKey}"]`);
    if (btn) btn.textContent = `+ Create Subtasks (${checked})`;
}

async function createEpicSignoffTasks(epicKey, btn) {
    const selected = Array.from(
        document.querySelectorAll(`.signoff-task-checkbox[data-epic="${epicKey}"]:checked`)
    ).map(cb => cb.value);
    if (selected.length === 0) return;

    btn.disabled = true;
    btn.textContent = "Creating...";

    try {
        const resp = await fetch("/api/create-epic-signoff-tasks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                epicKey,
                projectKey: epicKey.split("-")[0],
                tasks: selected,
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Failed to create sign-off tasks");

        const warnings = (data.created || []).filter(t => t.warning).map(t => t.warning);
        btn.textContent = warnings.length > 0 ? "Created (warnings)" : "Created!";
        btn.title = warnings.join("; ");
        setTimeout(() => fetchIssues(), 1000);
    } catch (err) {
        btn.textContent = "Error";
        btn.title = err.message;
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = "+ Create Subtasks";
        }, 3000);
    }
}

// --- Filtering & Rendering ---

function initStatusDropdown() {
    const toggle = document.getElementById("status-toggle");
    const dropdown = document.getElementById("status-dropdown");
    const operatorBtn = document.getElementById("status-operator");

    toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdown.classList.toggle("open");
    });

    document.addEventListener("click", (e) => {
        if (!e.target.closest("#status-multi-select")) {
            dropdown.classList.remove("open");
        }
    });

    operatorBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        statusOperator = statusOperator === "equals" ? "not-equals" : "equals";
        operatorBtn.textContent = statusOperator === "equals" ? "=" : "≠";
        operatorBtn.classList.toggle("not-equals", statusOperator === "not-equals");
        updateStatusToggleLabel();
        saveFiltersToStorage();
        if (selectedStatuses.length > 0) {
            if (activeTab === "status") renderBoard();
            else if (activeTab === "metrics" && metricsLoaded) renderMetrics(allIssues);
        }
    });
}

function populateStatusFilter(issues) {
    const dropdown = document.getElementById("status-dropdown");
    const statuses = [...new Set(issues.map(i => i.status).filter(Boolean))].sort();

    let html = "";
    statuses.forEach(s => {
        const checked = selectedStatuses.includes(s) ? "checked" : "";
        html += `
            <label class="multi-select-item">
                <input type="checkbox" value="${s}" data-status ${checked}>
                <span>${s}</span>
            </label>
        `;
    });
    html += `
        <div class="multi-select-actions">
            <button id="status-select-all">Select All</button>
            <button id="status-clear-all">Clear All</button>
        </div>
    `;
    dropdown.innerHTML = html;

    dropdown.querySelectorAll("input[data-status]").forEach(cb => {
        cb.addEventListener("change", onStatusCheckboxChange);
    });
    document.getElementById("status-select-all").addEventListener("click", () => {
        dropdown.querySelectorAll("input[data-status]").forEach(cb => { cb.checked = true; });
        onStatusCheckboxChange();
    });
    document.getElementById("status-clear-all").addEventListener("click", () => {
        dropdown.querySelectorAll("input[data-status]").forEach(cb => { cb.checked = false; });
        onStatusCheckboxChange();
    });

    updateStatusToggleLabel();
}

function onStatusCheckboxChange() {
    const dropdown = document.getElementById("status-dropdown");
    selectedStatuses = Array.from(dropdown.querySelectorAll("input[data-status]:checked")).map(cb => cb.value);
    updateStatusToggleLabel();
    saveFiltersToStorage();
    if (activeTab === "status") renderBoard();
    else if (activeTab === "metrics" && metricsLoaded) renderMetrics(allIssues);
}

function updateStatusToggleLabel() {
    const toggle = document.getElementById("status-toggle");
    const prefix = statusOperator === "not-equals" ? "≠ " : "";
    if (selectedStatuses.length === 0) {
        toggle.textContent = "All Statuses";
    } else if (selectedStatuses.length === 1) {
        toggle.textContent = `${prefix}${selectedStatuses[0]}`;
    } else {
        toggle.textContent = `${prefix}${selectedStatuses.length} Statuses`;
    }
}

function getFilteredIssues() {
    const typeFilter = document.getElementById("filter-type").value;

    return allIssues.filter((issue) => {
        if (typeFilter === "story" && issue.issueType !== "Story") return false;
        if (typeFilter === "bug" && issue.issueType !== "Bug") return false;
        if (typeFilter === "epic" && issue.issueType !== "Epic") return false;
        if (selectedStatuses.length > 0) {
            const match = selectedStatuses.includes(issue.status);
            if (statusOperator === "equals" && !match) return false;
            if (statusOperator === "not-equals" && match) return false;
        }
        if (selectedQaContacts.length > 0 && selectedProjects.length > 0) {
            if (issue.issueType === "Epic") {
                const childMatch = (issue.children || []).some(
                    (c) => selectedQaContacts.some(q => (c.qaContact?.name || "").toLowerCase() === q.toLowerCase())
                );
                const passes = qaOperator === "equals" ? childMatch : !childMatch;
                if (!passes) return false;
            } else {
                const nameMatch = selectedQaContacts.some(q => (issue.qaContact?.name || "").toLowerCase() === q.toLowerCase());
                const assigneeMatch = selectedQaContacts.some(q => (issue.assignee?.name || "").toLowerCase() === q.toLowerCase());
                const match = nameMatch || assigneeMatch;
                const passes = qaOperator === "equals" ? match : !match;
                if (!passes) return false;
            }
        }
        return true;
    });
}

function getQaIssues(issues) {
    return issues.filter((issue) => {
        const qa = issue.qaContact?.name;
        return qa && qa !== "Unassigned";
    });
}

function getStatusBadgeClass(status) {
    const s = status.toLowerCase();
    if (s === "done" || s === "closed" || s === "complete" || s === "completed") return "status-done";
    if (s === "resolved") return "status-resolved";
    if (s.includes("progress") || s === "in review" || s === "in qa" || s === "in development") return "status-in-progress";
    return "status-open";
}

function getPriorityClass(priority) {
    const p = priority.toLowerCase();
    if (p === "highest" || p === "critical" || p === "p0") return "critical";
    if (p === "high" || p === "major" || p === "p1") return "high";
    if (p === "medium" || p === "normal" || p === "p2") return "medium";
    return "low";
}

function getAvatarColor(name) {
    const colors = ["#dc2626", "#ea580c", "#d97706", "#16a34a", "#0d9488", "#0284c7", "#4f46e5", "#7c3aed", "#c026d3", "#e11d48"];
    let hash = 0;
    for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
    return colors[Math.abs(hash) % colors.length];
}

function renderStats(filtered, qaIssues) {
    const statsSection = document.getElementById("stats-section");
    const statsBar = document.getElementById("stats-bar");
    const subtitle = document.getElementById("stats-subtitle");
    const badge = document.getElementById("project-badge");

    badge.textContent = selectedProjects.length > 0 ? selectedProjects.join(", ") : "All Projects";

    const checked = qaIssues.length;
    const passed = qaIssues.filter((i) => checkQuality(i).passed).length;
    const failed = checked - passed;
    const score = checked > 0 ? Math.round((passed / checked) * 100) : 0;

    const stories = qaIssues.filter((i) => i.issueType === "Story").length;
    const epics = qaIssues.filter((i) => i.issueType === "Epic").length;
    const bugs = qaIssues.filter((i) => i.issueType !== "Story" && i.issueType !== "Epic").length;

    subtitle.textContent = `${qaIssues.length} of ${filtered.length} tickets have QA contact assigned · Quality checked`;

    const epicCard = epics > 0 ? `<div class="stat-card"><div class="stat-value" style="color:#7c3aed">${epics}</div><div class="stat-label">Epics</div></div>` : "";

    statsBar.innerHTML = `
        <div class="stat-card"><div class="stat-value total">${checked}</div><div class="stat-label">Checked</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#0052cc">${score}%</div><div class="stat-label">Quality Score</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#16a34a">${passed}</div><div class="stat-label">Passed</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#dc2626">${failed}</div><div class="stat-label">Failed</div></div>
        <div class="stat-card"><div class="stat-value stories">${stories}</div><div class="stat-label">Stories</div></div>
        <div class="stat-card"><div class="stat-value defects">${bugs}</div><div class="stat-label">Defects</div></div>
        ${epicCard}
    `;

    const toggle = document.getElementById("toggle-pass-fail");
    const toggleLabel = document.getElementById("toggle-label");
    if (toggle.checked) {
        toggleLabel.textContent = `Showing Failed (${failed})`;
        toggleLabel.className = "toggle-label fail-label";
    } else {
        toggleLabel.textContent = `Showing Passed (${passed})`;
        toggleLabel.className = "toggle-label pass-label";
    }

    statsSection.style.display = "block";
}

function createIssueRow(issue) {
    const typeClass = issue.issueType === "Epic" ? "epic" : issue.issueType === "Story" ? "story" : "bug";
    const typeLabel = issue.issueType === "Epic" ? "Epic" : issue.issueType === "Story" ? "Story" : "Bug";
    const statusClass = getStatusBadgeClass(issue.status);
    const priorityClass = getPriorityClass(issue.priority);
    const role = issue.qaContact?.name === issue.reporter?.name ? "Reporter" : "QA Contact";
    const quality = checkQuality(issue);
    const qualityBadge = quality.passed
        ? '<span class="badge quality-pass">PASS</span>'
        : '<span class="badge quality-fail">FAIL</span>';
    const isITNPI = issue.key.startsWith("ITNPI-");
    const hasSubtaskFailure = !isITNPI && issue.issueType === "Story" && quality.failures.some((f) => f.startsWith("Missing subtask:"));
    const createBtn = hasSubtaskFailure
        ? `<div class="subtask-action">${buildSubtaskSelectorHtml(issue.key, getMissingSubtasksList(issue))}</div>`
        : "";
    const failReasons = quality.failures.length > 0
        ? `<div class="quality-reasons">${quality.failures.join(" &middot; ")}</div>${createBtn}`
        : "";
    const isProdOps = issue.key.startsWith("PRDOPS-");
    const qaName = (issue.qaContact?.name || "QA Contact").replace(/'/g, "\\'");
    const qaAccountId = issue.qaContact?.accountId || "";
    const nudgeBtnHtml = isProdOps && issue.issueType === "Story" && issue.qaUpdateMissing
        ? `<div class="nudge-qa-action"><button class="btn-nudge-qa" onclick="nudgeQa('${issue.key}', '${qaName}', '${qaAccountId}', this)">QA Updates Missing</button></div>`
        : "";
    const uatSanityBtnHtml = isProdOps && issue.issueType === "Story" && issue.uatSanityMissing
        ? `<div class="nudge-qa-action"><button class="btn-uat-sanity" onclick="nudgeSanity('${issue.key}', '${qaName}', '${qaAccountId}', this)">UAT Sanity Results Missing</button></div>`
        : "";
    const missingQaSubs = (issue.subtasksQaContactMissing || []);
    const autoAssignQaBtnHtml = issue.issueType === "Story" && missingQaSubs.length > 0 && qaAccountId
        ? `<div class="nudge-qa-action"><button class="btn-auto-assign-qa"
                data-subtask-keys='${JSON.stringify(missingQaSubs.map(s => s.key))}'
                data-qa-account-id="${qaAccountId}"
                onclick="assignSubtasksQa(this)">Auto-assign QA to Subtasks (${missingQaSubs.length})</button></div>`
        : "";
    const openDst = issue.openDesignSubtask;
    const designNudgeBtnHtml = issue.issueType === "Story" && issue.designSubtaskInvalid && openDst?.key
        ? `<div class="nudge-qa-action"><button class="btn-nudge-design" onclick="nudgeTestCaseDesign('${openDst.key}', '${(openDst.assigneeName || "").replace(/'/g,"\\'")}', '${openDst.assigneeId || ""}', this)">Nudge Test Case Design</button></div>`
        : "";
    const assigneeName = (issue.assignee?.name || "").replace(/'/g, "\\'");
    const assigneeAccountId = issue.assignee?.accountId || "";
    const rcaBlank = issue.issueType === "Bug" && quality.failures.some(f => f.includes("RCA is blank"));
    const rcsBlank = issue.issueType === "Bug" && quality.failures.some(f => f.includes("Root Cause Summary is blank"));
    const rcaNudgeLabel = (rcaBlank && rcsBlank) ? "Nudge RCA &amp; Root Cause Summary" : rcaBlank ? "Nudge RCA" : rcsBlank ? "Nudge Root Cause Summary" : "";
    const rcaNudgeMsgSuffix = (rcaBlank && rcsBlank) ? ", can you please update the RCA & Root Cause Summary?" : rcaBlank ? ", can you please update the RCA?" : ", can you please update the Root Cause Summary?";
    const rcaNudgeBtnHtml = rcaNudgeLabel
        ? `<div class="nudge-qa-action"><button class="btn-nudge-rca" onclick="nudgeRca('${issue.key}', '${assigneeName}', '${assigneeAccountId}', '${rcaNudgeMsgSuffix}', this)">${rcaNudgeLabel}</button></div>`
        : "";

    let latestCommentHtml = "";
    if (issue.issueType !== "Epic" && issue.latestComment) {
        const c = issue.latestComment;
        const commentDate = c.created
            ? new Date(c.created).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
            : "";
        latestCommentHtml = `
            <div class="latest-comment">
                <span class="latest-comment-label">Latest Comment:</span>
                <span class="latest-comment-author">@${c.author}${commentDate ? " &middot; " + commentDate : ""}:</span>
                <span class="latest-comment-text">${c.text}</span>
            </div>`;
    }

    let epicSignoffHtml = "";
    if (issue.issueType === "Epic") {
        const missingSignoffs = getMissingSignoffTasks(issue);
        if (missingSignoffs.length > 0) {
            const pendingList = missingSignoffs.map(t =>
                `<label class="pending-task-tag pending-task-selectable">
                    <input type="checkbox" class="signoff-task-checkbox" data-epic="${issue.key}" value="${t}" checked onchange="updateSignoffBtn('${issue.key}')">
                    ${t}
                </label>`
            ).join("");
            epicSignoffHtml = `
                <div class="epic-signoff-action">
                    <button class="btn-create-signoff-tasks" data-epic="${issue.key}"
                            onclick="createEpicSignoffTasks('${issue.key}', this)">
                        + Create Subtasks (${missingSignoffs.length})
                    </button>
                    <div class="pending-tasks-list">${pendingList}</div>
                </div>
            `;
        } else {
            let showComplete = true;
            if (isITNPI) {
                const hasOpenSignoffs = (issue.children || []).some(c => {
                    const s = c.summary.toLowerCase();
                    const isSignoff = EPIC_SIGNOFF_TASK_NAMES.some(n => _itnpiSignoffMatches(s, n)) || s.includes("test case validation") || s.includes("test case preparation");
                    return isSignoff && (c.status || "").toLowerCase() === "open";
                });
                if (hasOpenSignoffs) showComplete = false;
            }
            epicSignoffHtml = showComplete
                ? '<div class="epic-signoff-action"><span class="signoff-complete-badge">Subtasks complete</span></div>'
                : '<div class="epic-signoff-action"><span class="signoff-pending-badge">Sign-offs Open</span></div>';
        }
    }

    let epicChildrenHtml = "";
    if (issue.issueType === "Epic" && issue.children && issue.children.length > 0) {
        const baseUrl = issue.url.replace(/\/browse\/.*$/, "");
        const statusSummary = issue.childStatusSummary || {};
        const summaryParts = Object.entries(statusSummary).map(([s, c]) => {
            const cls = getStatusBadgeClass(s);
            return `<span class="badge ${cls}">${c} ${s}</span>`;
        });
        const progressHtml = summaryParts.length > 0
            ? `<div class="epic-status-breakdown">${summaryParts.join(" ")}</div>` : "";

        const childRows = issue.children.map((child) => {
            const cTypeClass = child.issueType === "Story" ? "story" : "bug";
            const cStatusClass = getStatusBadgeClass(child.status);
            const cPriorityClass = getPriorityClass(child.priority);
            const cAssignee = child.assignee?.name || "Unassigned";

            const cQuality = checkQuality(child);
            const cQualityBadge = cQuality.passed
                ? '<span class="badge quality-pass">PASS</span>'
                : '<span class="badge quality-fail">FAIL</span>';

            const cIsITNPI = child.key.startsWith("ITNPI-");
            const cHasSubtaskFailure = !cIsITNPI && child.issueType === "Story" && cQuality.failures.some(f => f.startsWith("Missing subtask:"));
            const cCreateBtn = cHasSubtaskFailure
                ? buildSubtaskSelectorHtml(child.key, getMissingSubtasksList(child))
                : "";

            const cFailHtml = cQuality.failures.length > 0
                ? `<div class="epic-child-quality"><span class="quality-reasons">${cQuality.failures.join(" &middot; ")}</span> ${cCreateBtn}</div>`
                : "";

            return `
                <div class="epic-child-row-wrap">
                    <div class="epic-child-row">
                        <a class="issue-key" href="${baseUrl}/browse/${child.key}" target="_blank">${child.key}</a>
                        <span class="badge ${cTypeClass}">${child.issueType}</span>
                        <span class="badge ${cStatusClass}">${child.status}</span>
                        <span class="priority-badge ${cPriorityClass}">${child.priority}</span>
                        ${cQualityBadge}
                        <span class="issue-summary">${child.summary}</span>
                        <span class="epic-child-assignee">${cAssignee}</span>
                    </div>
                    ${cFailHtml}
                </div>
            `;
        }).join("");

        epicChildrenHtml = `
            <div class="epic-children-section">
                <div class="epic-children-header">
                    <span class="epic-child-count">${issue.childCount} child issue${issue.childCount !== 1 ? "s" : ""}</span>
                    ${progressHtml}
                </div>
                <div class="epic-children-list">${childRows}</div>
            </div>
        `;
    }

    return `
        <div class="issue-row${issue.issueType === 'Epic' ? ' epic-row' : ''}">
            <div class="issue-row-top">
                <a class="issue-key" href="${issue.url}" target="_blank">${issue.key}</a>
                <span class="badge ${typeClass}">${typeLabel}</span>
                <span class="badge ${statusClass}">${issue.status}</span>
                ${(issue.issueType !== "Epic" || isITNPI) ? qualityBadge : ""}
            </div>
            <div class="issue-row-bottom">
                <span class="priority-badge ${priorityClass}">${issue.priority}</span>
                <span class="issue-summary">${issue.summary}</span>
                ${issue.issueType !== "Epic" ? `<span class="issue-role">${role}</span>` : ""}
            </div>
            ${latestCommentHtml}
            ${failReasons}
            ${nudgeBtnHtml}
            ${uatSanityBtnHtml}
            ${designNudgeBtnHtml}
            ${autoAssignQaBtnHtml}
            ${rcaNudgeBtnHtml}
            ${epicSignoffHtml}
            ${epicChildrenHtml}
        </div>
    `;
}

function renderBoard() {
    const filtered = getFilteredIssues();
    const isEpicView = document.getElementById("filter-type").value === "epic";
    const ownerSection = document.getElementById("owner-section");
    const ownerCards = document.getElementById("owner-cards");

    if (selectedProjects.length === 0 && allIssues.length === 0) {
        document.getElementById("tab-nav").style.display = "none";
        document.getElementById("stats-section").style.display = "none";
        ownerSection.style.display = "none";
        document.getElementById("unassigned-section").style.display = "none";
        ownerCards.innerHTML = '<div class="empty-state">Please select a board or a QA contact from the dropdown above</div>';
        return;
    }

    document.getElementById("tab-nav").style.display = "flex";

    if (isEpicView) {
        document.getElementById("unassigned-section").style.display = "none";
        document.getElementById("export-buttons-status").style.display = "none";
        renderEpicBoard(filtered);
        return;
    }

    document.querySelector(".toggle-area").style.display = "";
    document.querySelector(".owner-heading").textContent = "Owner Action Summary";
    document.getElementById("stats-title").textContent = "Story/Bug Validation Status";

    const qaIssues = getQaIssues(filtered);
    renderStats(filtered, qaIssues);
    document.getElementById("export-buttons-status").style.display = filtered.length > 0 ? "" : "none";

    const showFailed = document.getElementById("toggle-pass-fail").checked;
    const displayIssues = sortIssues(qaIssues.filter((issue) => {
        const quality = checkQuality(issue);
        return showFailed ? !quality.passed : quality.passed;
    }));

    const grouped = {};
    displayIssues.forEach((issue) => {
        const person = issue.qaContact.name;
        if (!grouped[person]) grouped[person] = [];
        grouped[person].push(issue);
    });

    const sortedPeople = Object.keys(grouped).sort((a, b) => grouped[b].length - grouped[a].length);

    let html = "";
    sortedPeople.forEach((person) => {
        const issues = grouped[person];
        const avatar = issues[0]?.qaContact?.avatar;
        const initial = person.charAt(0).toUpperCase();
        const color = getAvatarColor(person);

        const avatarHtml = avatar
            ? `<img class="owner-avatar" src="${avatar}" alt="">`
            : `<div class="owner-avatar-placeholder" style="background:${color}">${initial}</div>`;

        const countLabel = issues.length === 1 ? "1 ticket assigned" : `${issues.length} tickets assigned`;

        html += `
            <div class="owner-card">
                <div class="owner-card-header">
                    ${avatarHtml}
                    <div class="owner-info">
                        <div class="owner-name">${person}</div>
                        <div class="owner-count-label">${countLabel}</div>
                    </div>
                    <div class="owner-badge">${issues.length}</div>
                </div>
                ${issues.map(createIssueRow).join("")}
            </div>
        `;
    });

    ownerCards.innerHTML = html || '<div class="empty-state">No QA issues found</div>';
    ownerSection.style.display = "block";

    const unassignedIssues = filtered.filter(issue => {
        if (issue.issueType === "Epic" || issue.issueType === "Task") return false;
        if ((issue.status || "").toLowerCase() === "no action") return false;
        const qa = issue.qaContact?.name;
        return !qa || qa === "Unassigned";
    });
    renderUnassignedQa(unassignedIssues);
}

function renderEpicBoard(epics) {
    const statsSection = document.getElementById("stats-section");
    const ownerSection = document.getElementById("owner-section");
    const ownerCards = document.getElementById("owner-cards");
    const badge = document.getElementById("project-badge");

    badge.textContent = selectedProjects.join(", ");

    const allChildren = epics.flatMap(e => e.children || []);
    const totalChildren = allChildren.length;
    const doneChildren = epics.reduce((sum, e) => {
        const counts = e.childStatusSummary || {};
        return sum + Object.entries(counts)
            .filter(([s]) => getStatusBadgeClass(s) === "status-done")
            .reduce((s, [, c]) => s + c, 0);
    }, 0);
    const progress = totalChildren > 0 ? Math.round((doneChildren / totalChildren) * 100) : 0;

    const allItems = [...epics, ...allChildren];
    const totalChecked = allItems.length;
    const qualityPassed = allItems.filter(i => checkQuality(i).passed).length;
    const qualityFailed = totalChecked - qualityPassed;
    const qualityScore = totalChecked > 0 ? Math.round((qualityPassed / totalChecked) * 100) : 0;

    const statsBar = document.getElementById("stats-bar");
    const subtitle = document.getElementById("stats-subtitle");
    subtitle.textContent = `${epics.length} epics · ${totalChildren} child issues · ${totalChecked} quality checked`;

    statsBar.innerHTML = `
        <div class="stat-card"><div class="stat-value" style="color:#7c3aed">${epics.length}</div><div class="stat-label">Epics</div></div>
        <div class="stat-card"><div class="stat-value total">${totalChildren}</div><div class="stat-label">Child Issues</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#16a34a">${doneChildren}</div><div class="stat-label">Done</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#0052cc">${progress}%</div><div class="stat-label">Progress</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#0052cc">${qualityScore}%</div><div class="stat-label">Quality Score</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#16a34a">${qualityPassed}</div><div class="stat-label">Passed</div></div>
        <div class="stat-card"><div class="stat-value" style="color:#dc2626">${qualityFailed}</div><div class="stat-label">Failed</div></div>
    `;
    statsSection.style.display = "block";
    document.getElementById("stats-title").textContent = "Epic Overview";

    const toggle = document.getElementById("toggle-pass-fail");
    const toggleLabel = document.getElementById("toggle-label");
    document.querySelector(".toggle-area").style.display = "";
    if (toggle.checked) {
        toggleLabel.textContent = `Showing Failed (${qualityFailed})`;
        toggleLabel.className = "toggle-label fail-label";
    } else {
        toggleLabel.textContent = `Showing Passed (${qualityPassed})`;
        toggleLabel.className = "toggle-label pass-label";
    }

    const showFailed = toggle.checked;

    const filteredEpics = sortIssues(epics.filter(epic => {
        const epicQ = checkQuality(epic);
        return showFailed ? !epicQ.passed : epicQ.passed;
    }));

    let html = "";
    filteredEpics.forEach((epic) => html += createIssueRow(epic));

    ownerCards.innerHTML = html
        ? `<div class="epic-list">${html}</div>`
        : '<div class="empty-state">No matching issues found</div>';
    ownerSection.style.display = "block";
    document.querySelector(".owner-heading").textContent = "Epics";
}


// --- Unassigned QA ---

function collectQaMembers() {
    const isProdOps = selectedProjects.length === 1 && selectedProjects[0] === "PRODOPS";

    if (isProdOps) {
        return PRODOPS_QA_TEAM.map(name => ({ name, accountId: null }));
    }

    const members = [];
    const seen = new Set();
    const dropdown = document.getElementById("qa-dropdown");
    for (const cb of dropdown.querySelectorAll("input[data-qa-contact]")) {
        const name = cb.value;
        if (!name || seen.has(name)) continue;
        seen.add(name);
        let accountId = cb.dataset.accountId || null;
        if (!accountId) {
            for (const issue of allIssues) {
                if (issue.qaContact?.name === name && issue.qaContact?.accountId) {
                    accountId = issue.qaContact.accountId;
                    break;
                }
                if (issue.children) {
                    for (const child of issue.children) {
                        if (child.qaContact?.name === name && child.qaContact?.accountId) {
                            accountId = child.qaContact.accountId;
                            break;
                        }
                    }
                    if (accountId) break;
                }
            }
        }
        if (accountId) {
            members.push({ name, accountId });
        }
    }
    return members;
}

function renderUnassignedQa(unassigned) {
    const section = document.getElementById("unassigned-section");
    const container = document.getElementById("unassigned-cards");

    if (unassigned.length === 0) {
        section.style.display = "none";
        return;
    }

    const qaMembers = collectQaMembers();
    const options = qaMembers.map(m =>
        `<option value="${m.accountId || m.name}" data-type="${m.accountId ? 'id' : 'name'}">${m.name}</option>`
    ).join("");

    let html = "";
    unassigned.forEach(issue => {
        const typeClass = issue.issueType === "Story" ? "story" : "bug";
        const statusClass = getStatusBadgeClass(issue.status);
        const priorityClass = getPriorityClass(issue.priority);
        const assigneeName = issue.assignee?.name || "Unassigned";

        html += `
            <div class="issue-row">
                <div class="issue-row-top">
                    <a class="issue-key" href="${issue.url}" target="_blank">${issue.key}</a>
                    <span class="badge ${typeClass}">${issue.issueType}</span>
                    <span class="badge ${statusClass}">${issue.status}</span>
                </div>
                <div class="issue-row-bottom">
                    <span class="priority-badge ${priorityClass}">${issue.priority}</span>
                    <span class="issue-summary">${issue.summary}</span>
                    <span class="issue-role">${assigneeName}</span>
                </div>
                <div class="assign-qa-row">
                    <select class="assign-qa-select" id="qa-select-${issue.key}">
                        <option value="">-- Select QA --</option>
                        ${options}
                    </select>
                    <button class="btn-assign-qa" onclick="assignQaContact('${issue.key}', this)">Assign</button>
                </div>
            </div>
        `;
    });

    container.innerHTML = `
        <div class="owner-card unassigned-card">
            <div class="owner-card-header">
                <div class="owner-avatar-placeholder" style="background:#f59e0b">?</div>
                <div class="owner-info">
                    <div class="owner-name">Unassigned QA Contact</div>
                    <div class="owner-count-label">${unassigned.length} ticket${unassigned.length !== 1 ? "s" : ""} need QA assignment</div>
                </div>
                <div class="owner-badge" style="background:#fef9c3;color:#a16207">${unassigned.length}</div>
            </div>
            ${html}
        </div>
    `;
    section.style.display = "block";
}

async function assignQaContact(issueKey, btn) {
    const select = document.getElementById(`qa-select-${issueKey}`);
    const val = select.value;
    if (!val) return;

    const selectedOption = select.options[select.selectedIndex];
    const isName = selectedOption.dataset.type === "name";

    btn.disabled = true;
    btn.textContent = "Assigning...";

    try {
        const body = isName
            ? { issueKey, displayName: val }
            : { issueKey, accountId: val };
        const resp = await fetch("/api/assign-qa", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Failed to assign QA");
        btn.textContent = "Assigned!";
        setTimeout(() => fetchIssues(), 1000);
    } catch (err) {
        btn.textContent = "Error";
        btn.title = err.message;
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = "Assign";
        }, 3000);
    }
}

async function assignSubtasksQa(btn) {
    const subtaskKeys = JSON.parse(btn.dataset.subtaskKeys || "[]");
    const qaAccountId = btn.dataset.qaAccountId;
    if (!subtaskKeys.length || !qaAccountId) return;
    btn.disabled = true;
    btn.textContent = "Assigning...";
    try {
        for (const issueKey of subtaskKeys) {
            const resp = await fetch("/api/assign-qa", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ issueKey, accountId: qaAccountId }),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(`${issueKey}: ${data.error || "Failed"}`);
        }
        btn.textContent = "Assigned!";
        setTimeout(() => fetchIssues(), 1000);
    } catch (err) {
        btn.textContent = "Error";
        btn.title = err.message;
        setTimeout(() => {
            btn.disabled = false;
            btn.textContent = `Auto-assign QA to Subtasks (${subtaskKeys.length})`;
        }, 3000);
    }
}

// --- Tab Navigation ---

let activeTab = "status";
let qaTrackingLoaded = false;
let alertsLoaded = false;
let metricsLoaded = false;
let allQaTrackingData = [];

const tabIds = ["tab-status", "tab-qa-tracking", "tab-alerts", "tab-metrics", "tab-workload"];
let workloadLoaded = false;

function initTabs() {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.tab;
            if (tab === activeTab) return;

            document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            activeTab = tab;
            saveFiltersToStorage();

            tabIds.forEach((id) => {
                document.getElementById(id).style.display = "none";
            });

            if (tab === "status") {
                document.getElementById("tab-status").style.display = "";
            } else if (tab === "qa-tracking") {
                document.getElementById("tab-qa-tracking").style.display = "";
                if (!qaTrackingLoaded) fetchQaTracking();
            } else if (tab === "alerts") {
                document.getElementById("tab-alerts").style.display = "";
                if (!alertsLoaded) fetchAlerts();
            } else if (tab === "metrics") {
                document.getElementById("tab-metrics").style.display = "";
                if (!metricsLoaded) fetchMetrics();
            } else if (tab === "workload") {
                document.getElementById("tab-workload").style.display = "";
                if (!workloadLoaded) loadWorkload();
            }
        });
    });

    // Restore saved active tab (sets visual state; data is fetched when onProjectChange runs)
    const savedTab = _pendingRestoreData?.tab;
    if (savedTab && savedTab !== "status") {
        activeTab = savedTab;
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === savedTab));
        tabIds.forEach(id => { document.getElementById(id).style.display = id === `tab-${savedTab}` ? "" : "none"; });
    }
}

// --- QA Tracking ---

function formatDuration(hours) {
    if (hours < 1) return `${Math.round(hours * 60)}m`;
    if (hours < 24) return `${Math.round(hours)}h`;
    const days = Math.floor(hours / 24);
    const rem = Math.round(hours % 24);
    return rem > 0 ? `${days}d ${rem}h` : `${days}d`;
}

function getDurationClass(hours) {
    if (hours <= 0) return "empty";
    if (hours < 8) return "short";
    if (hours < 24) return "medium";
    if (hours < 72) return "long";
    return "very-long";
}

async function fetchQaTracking() {
    const loading = document.getElementById("qa-tracking-loading");
    const table = document.getElementById("qa-tracking-table");
    const badge = document.getElementById("qa-tracking-badge");

    if (selectedProjects.length === 0) {
        table.innerHTML = '<div class="empty-state">Please select a board from the dropdown above</div>';
        return;
    }

    loading.style.display = "block";
    table.innerHTML = "";

    try {
        const allFetches = [];
        const dateParams = buildDateParams();
        for (const proj of selectedProjects) {
            if (selectedSprints.length === 0) {
                allFetches.push(fetch(`/api/qa-tracking?project=${proj}${dateParams}`));
            } else {
                selectedSprints.forEach((sprintId) => {
                    allFetches.push(fetch(`/api/qa-tracking?project=${proj}&sprintId=${sprintId}`));
                });
            }
        }

        const responses = await Promise.all(allFetches);
        const allData = [];
        const seenKeys = new Set();
        for (const resp of responses) {
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || "Failed to fetch QA tracking");
            data.forEach((item) => {
                if (!seenKeys.has(item.key)) {
                    seenKeys.add(item.key);
                    allData.push(item);
                }
            });
        }

        allQaTrackingData = allData;
        badge.textContent = selectedProjects.join(", ");
        renderQaTrackingFiltered();
        qaTrackingLoaded = true;
        document.getElementById("export-buttons-qa-tracking").style.display = allData.length > 0 ? "" : "none";
        lastFetchTime = Date.now();
        updateFreshnessDisplay();
        loadVelocity();
    } catch (err) {
        table.innerHTML = `<div class="error">${err.message}</div>`;
    } finally {
        loading.style.display = "none";
    }
}

function renderQaTrackingFiltered() {
    const typeFilter = document.getElementById("filter-type").value;
    const filtered = allQaTrackingData.filter((item) => {
        if (typeFilter === "story" && item.issueType !== "Story") return false;
        if (typeFilter === "bug" && item.issueType !== "Bug") return false;
        if (selectedQaContacts.length > 0) {
            const match = selectedQaContacts.some(q => (item.qaContact?.name || "").toLowerCase() === q.toLowerCase());
            if (qaOperator === "equals" && !match) return false;
            if (qaOperator === "not-equals" && match) return false;
        }
        return true;
    });
    const subtitle = document.getElementById("qa-tracking-subtitle");
    subtitle.textContent = `${filtered.length} tickets with QA contact · Time spent in QA statuses`;
    renderQaTracking(filtered);
}

let qaTableSort = { col: null, dir: 1 };

function sortQaData(data, statusColumns) {
    if (!qaTableSort.col) return data;
    return [...data].sort((a, b) => {
        let va, vb;
        if (qaTableSort.col === "key") { va = a.key; vb = b.key; }
        else if (qaTableSort.col === "type") { va = a.issueType; vb = b.issueType; }
        else if (qaTableSort.col === "qa") { va = a.qaContact.name; vb = b.qaContact.name; }
        else if (qaTableSort.col === "status") { va = a.currentStatus; vb = b.currentStatus; }
        else if (qaTableSort.col === "total") {
            va = a.qaStatusTimes.reduce((s, t) => s + t.hours, 0);
            vb = b.qaStatusTimes.reduce((s, t) => s + t.hours, 0);
            return (va - vb) * qaTableSort.dir;
        } else if (statusColumns.includes(qaTableSort.col)) {
            va = (a.qaStatusTimes.find(t => t.status === qaTableSort.col) || {}).hours || 0;
            vb = (b.qaStatusTimes.find(t => t.status === qaTableSort.col) || {}).hours || 0;
            return (va - vb) * qaTableSort.dir;
        }
        return (String(va || "")).localeCompare(String(vb || "")) * qaTableSort.dir;
    });
}

function thSort(col, label, statusColumns) {
    const isActive = qaTableSort.col === col;
    const arrow = isActive ? (qaTableSort.dir === 1 ? "↑" : "↓") : "↕";
    const activeClass = isActive ? " sort-active" : "";
    return `<th class="sortable${activeClass}" onclick="onQaColSort('${col}', ${JSON.stringify(statusColumns)})">${label}<span class="sort-indicator">${arrow}</span></th>`;
}

function onQaColSort(col, statusColumns) {
    if (qaTableSort.col === col) {
        qaTableSort.dir *= -1;
    } else {
        qaTableSort.col = col;
        qaTableSort.dir = 1;
    }
    saveFiltersToStorage();
    renderQaTrackingFiltered();
}

function renderQaTracking(data) {
    const table = document.getElementById("qa-tracking-table");

    if (data.length === 0) {
        table.innerHTML = '<div class="empty-state">No QA tracking data found</div>';
        return;
    }

    const allStatuses = new Set();
    data.forEach((item) => {
        item.qaStatusTimes.forEach((t) => allStatuses.add(t.status));
    });
    const statusColumns = Array.from(allStatuses);
    const sortedData = sortQaData(data, statusColumns);

    let headerHtml = `
        ${thSort("key", "Key", statusColumns)}
        ${thSort("type", "Type", statusColumns)}
        <th>Summary</th>
        ${thSort("qa", "QA Contact", statusColumns)}
        ${thSort("status", "Current Status", statusColumns)}
    `;
    statusColumns.forEach((s) => {
        headerHtml += thSort(s, s, statusColumns);
    });
    headerHtml += thSort("total", "Total QA Time", statusColumns);

    let bodyHtml = "";
    sortedData.forEach((item) => {
        const timeMap = {};
        const spanMap = {};
        let totalHours = 0;
        item.qaStatusTimes.forEach((t) => {
            timeMap[t.status] = t.hours;
            spanMap[t.status] = t.spans || [];
            totalHours += t.hours;
        });

        const typeClass = item.issueType === "Story" ? "story" : "bug";
        const statusClass = getStatusBadgeClass(item.currentStatus);

        let row = `
            <td><a class="issue-key" href="${item.url}" target="_blank">${item.key}</a></td>
            <td><span class="badge ${typeClass}">${item.issueType}</span></td>
            <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${item.summary}">${item.summary}</td>
            <td>${item.qaContact.name}</td>
            <td><span class="badge ${statusClass}">${item.currentStatus}</span></td>
        `;

        const allSpanDetails = [];
        statusColumns.forEach((s) => {
            const hours = timeMap[s] || 0;
            const cls = getDurationClass(hours);
            const display = hours > 0 ? formatDuration(hours) : "-";
            const spans = spanMap[s] || [];
            let tooltip = "";
            if (spans.length > 0) {
                tooltip = spans.map(sp => `Entered: ${sp.entered}\nExited: ${sp.exited}`).join("\n---\n");
                tooltip = `${s}\nDuration: ${display}\n\n${tooltip}`;
                allSpanDetails.push(...spans.map(sp => ({ status: s, ...sp })));
            }
            row += `<td><span class="qa-duration ${cls}" ${tooltip ? `title="${tooltip.replace(/"/g, '&quot;')}"` : ""}>${display}</span></td>`;
        });

        const totalCls = getDurationClass(totalHours);
        const totalDisplay = totalHours > 0 ? formatDuration(totalHours) : "-";
        let totalTooltip = "";
        if (allSpanDetails.length > 0) {
            totalTooltip = allSpanDetails.map(sp => `${sp.status}\n  Entered: ${sp.entered}\n  Exited: ${sp.exited}`).join("\n\n");
            totalTooltip = `Total QA Time: ${totalDisplay}\n\n${totalTooltip}`;
        }
        row += `<td><span class="qa-duration ${totalCls}" ${totalTooltip ? `title="${totalTooltip.replace(/"/g, '&quot;')}"` : ""}>${totalDisplay}</span></td>`;

        bodyHtml += `<tr>${row}</tr>`;
    });

    // Compute per-status averages for footer
    const statusSums = {};
    const statusCounts = {};
    let grandTotalSum = 0, grandTotalCount = 0;
    sortedData.forEach(item => {
        const timeMap = {};
        let rowTotal = 0;
        item.qaStatusTimes.forEach(t => { timeMap[t.status] = t.hours; rowTotal += t.hours; });
        statusColumns.forEach(s => {
            const h = timeMap[s] || 0;
            if (h > 0) { statusSums[s] = (statusSums[s] || 0) + h; statusCounts[s] = (statusCounts[s] || 0) + 1; }
        });
        if (rowTotal > 0) { grandTotalSum += rowTotal; grandTotalCount++; }
    });

    let footHtml = `<td colspan="5" class="qa-avg-label">Avg · ${sortedData.length} issues</td>`;
    statusColumns.forEach(s => {
        const avg = statusCounts[s] > 0 ? statusSums[s] / statusCounts[s] : 0;
        const cls = getDurationClass(avg);
        footHtml += `<td><span class="qa-duration ${cls}">${avg > 0 ? formatDuration(avg) : "–"}</span></td>`;
    });
    const totalAvg = grandTotalCount > 0 ? grandTotalSum / grandTotalCount : 0;
    footHtml += `<td><span class="qa-duration ${getDurationClass(totalAvg)}">${totalAvg > 0 ? formatDuration(totalAvg) : "–"}</span></td>`;

    table.innerHTML = `
        <div class="qa-table-wrapper">
            <table class="qa-table">
                <thead><tr>${headerHtml}</tr></thead>
                <tbody>${bodyHtml}</tbody>
                <tfoot><tr class="qa-avg-row">${footHtml}</tr></tfoot>
            </table>
        </div>
    `;
}

// --- Alerts ---

let allAlertsData = [];
const _nudgeAllTargets = {};

async function nudgeAll(alertKey, btn) {
    const items = _nudgeAllTargets[alertKey] || [];
    if (!items.length) return;
    const uniquePeople = new Set(items.map(i =>
        alertKey === "bugsNoRca" ? (i.assignee?.name || "") : (i.qaContact?.name || "")
    ).filter(Boolean));
    if (!confirm(`Send nudge to ${uniquePeople.size} people across ${items.length} issue(s)?`)) return;
    const originalText = btn.textContent;
    btn.disabled = true;
    const isRca = alertKey === "bugsNoRca";
    let sent = 0, failed = 0;
    btn.textContent = `Sending 0/${items.length}…`;
    for (const item of items) {
        const name = isRca ? (item.assignee?.name || "") : (item.qaContact?.name || "");
        const accountId = isRca ? (item.assignee?.accountId || null) : (item.qaContact?.accountId || null);
        const suffix = isRca
            ? ", can you please update the RCA & Root Cause Summary?"
            : ", can you please update the QA Progress?";
        if (!name) { failed++; continue; }
        try {
            const resp = await fetch("/api/add-comment", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ issueKey: item.key, qaName: name, accountId, messageSuffix: suffix }),
            });
            if (!resp.ok) failed++; else sent++;
        } catch { failed++; }
        btn.textContent = `Sending ${sent + failed}/${items.length}…`;
        await new Promise(r => setTimeout(r, 250));
    }
    btn.textContent = failed > 0 ? `Sent ${sent}, ${failed} failed` : `Sent ${sent}!`;
    setTimeout(() => { btn.disabled = false; btn.textContent = originalText; }, 4000);
}

function daysSince(dateStr) {
    if (!dateStr) return 0;
    const created = new Date(dateStr);
    const now = new Date();
    return Math.floor((now - created) / (1000 * 60 * 60 * 24));
}

async function fetchAlerts() {
    const loading = document.getElementById("alerts-loading");
    const container = document.getElementById("alerts-container");
    const badge = document.getElementById("alerts-badge");

    if (selectedProjects.length === 0) {
        container.innerHTML = '<div class="empty-state">Please select a board from the dropdown above</div>';
        return;
    }

    loading.style.display = "block";
    container.innerHTML = "";

    try {
        // Fetch all issues (reuse existing data if available, otherwise fetch)
        let issues = allIssues;
        if (issues.length === 0) {
            const fetches = [];
            const dateParams = buildDateParams();
            for (const proj of selectedProjects) {
                fetches.push(fetch(`/api/issues?project=${proj}${dateParams}`));
            }
            const responses = await Promise.all(fetches);
            const fetched = [];
            const seenKeys = new Set();
            for (const resp of responses) {
                const data = await resp.json();
                if (resp.ok) {
                    data.forEach((issue) => {
                        if (!seenKeys.has(issue.key)) {
                            seenKeys.add(issue.key);
                            fetched.push(issue);
                        }
                    });
                }
            }
            allIssues = fetched;
            issues = fetched;
        }

        // Fetch QA tracking data for stuck-in-QA detection
        let qaData = allQaTrackingData;
        if (qaData.length === 0) {
            const dateParams = buildDateParams();
            for (const proj of selectedProjects) {
                const resp = await fetch(`/api/qa-tracking?project=${proj}${dateParams}`);
                const data = await resp.json();
                if (resp.ok) qaData = qaData.concat(data);
            }
        }

        const alerts = computeAlerts(issues, qaData);
        allAlertsData = alerts;

        badge.textContent = selectedProjects.join(", ");
        renderAlertsFiltered();
        alertsLoaded = true;
        document.getElementById("export-buttons-alerts").style.display = "";
        lastFetchTime = Date.now();
        updateFreshnessDisplay();
    } catch (err) {
        container.innerHTML = `<div class="error">${err.message}</div>`;
    } finally {
        loading.style.display = "none";
    }
}

function computeAlerts(issues, qaData) {
    const alerts = {
        bugsNoRca: { title: "Bugs Without RCA (3+ days)", severity: "critical", icon: "!!", issues: [] },
        stuckInQa: { title: "Stuck in QA (3+ days)", severity: "warning", icon: "⏳", issues: [] },
        missingQa: { title: "Missing QA Contact (2+ days)", severity: "warning", icon: "?", issues: [] },
        highPriority: { title: "High/Critical Unresolved (5+ days)", severity: "critical", icon: "!!", issues: [] },
    };

    // Rule 1: Bugs without RCA > 3 days
    const rcaPlaceholder = "A short description of the actual root cause. If there are many root causes, list them here.";
    issues.forEach((issue) => {
        if (issue.issueType !== "Story" && issue.statusCategory !== "Done") {
            const days = daysSince(issue.created);
            const rca = (issue.rca || "").trim();
            const rcs = (issue.rootCauseSummary || "").replace(/\\?\{color[^}]*\}/g, "").replace(/\s+/g, " ").trim();
            const rcsMissing = !rcs || rcs === rcaPlaceholder;
            if (days >= 3 && (!rca || rcsMissing)) {
                alerts.bugsNoRca.issues.push({ ...issue, days });
            }
        }
    });

    // Rule 2: Stories stuck in QA > 3 days
    const qaStuckStatuses = ["qa in progress", "ready for qa"];
    qaData.forEach((item) => {
        const stuckTime = item.qaStatusTimes
            .filter((t) => qaStuckStatuses.includes(t.status.toLowerCase()))
            .reduce((sum, t) => sum + t.hours, 0);
        if (stuckTime >= 72) {
            alerts.stuckInQa.issues.push({
                key: item.key,
                url: item.url,
                summary: item.summary,
                issueType: item.issueType,
                qaContact: item.qaContact,
                priority: item.priority || "None",
                days: Math.floor(stuckTime / 24),
            });
        }
    });

    // Rule 3: Missing QA Contact > 2 days
    issues.forEach((issue) => {
        if (issue.statusCategory !== "Done") {
            const days = daysSince(issue.created);
            const qaName = issue.qaContact?.name || "";
            if (days >= 2 && (!qaName || qaName === "Unassigned")) {
                alerts.missingQa.issues.push({ ...issue, days });
            }
        }
    });

    // Rule 4: High/Critical unresolved > 5 days
    issues.forEach((issue) => {
        if (issue.statusCategory !== "Done") {
            const days = daysSince(issue.created);
            const pc = getPriorityClass(issue.priority);
            if (days >= 5 && (pc === "critical" || pc === "high")) {
                alerts.highPriority.issues.push({ ...issue, days });
            }
        }
    });

    return alerts;
}

function renderAlertsFiltered() {
    const typeFilter = document.getElementById("filter-type").value;
    const alerts = allAlertsData;

    const filterIssues = (issues) => issues.filter((item) => {
        if (typeFilter === "story" && item.issueType !== "Story") return false;
        if (typeFilter === "bug" && item.issueType !== "Bug" && item.issueType !== "Story") return false;
        if (typeFilter === "bug" && item.issueType === "Story") return false;
        if (selectedQaContacts.length > 0) {
            const match = selectedQaContacts.some(q => (item.qaContact?.name || "").toLowerCase() === q.toLowerCase());
            if (qaOperator === "equals" && !match) return false;
            if (qaOperator === "not-equals" && match) return false;
        }
        return true;
    });

    let totalAlerts = 0;
    let html = "";

    const categories = [
        { key: "bugsNoRca", data: alerts.bugsNoRca },
        { key: "stuckInQa", data: alerts.stuckInQa },
        { key: "missingQa", data: alerts.missingQa },
        { key: "highPriority", data: alerts.highPriority },
    ];

    const nudgeableKeys = new Set(["bugsNoRca", "stuckInQa"]);

    categories.forEach(({ key, data }) => {
        if (!data) return;
        const filtered = filterIssues(data.issues);
        totalAlerts += filtered.length;
        if (filtered.length === 0) return;

        if (nudgeableKeys.has(key)) _nudgeAllTargets[key] = filtered;

        const cardClass = data.severity === "critical" ? "" : data.severity === "warning" ? "warning" : "info";
        const iconClass = data.severity === "critical" ? "critical" : data.severity === "warning" ? "warning" : "info";

        let issueRows = "";
        filtered.sort((a, b) => (b.days || 0) - (a.days || 0));
        filtered.forEach((item) => {
            const url = item.url || "#";
            const qaName = item.qaContact?.name || "";
            const accountId = item.qaContact?.accountId || "";
            issueRows += `
                <div class="alert-issue-row">
                    <input type="checkbox" class="alert-select-checkbox"
                        data-issue-key="${item.key}"
                        data-qa-name="${qaName}"
                        data-account-id="${accountId}"
                        title="Select for bulk ping">
                    <a class="issue-key" href="${url}" target="_blank">${item.key}</a>
                    <span class="alert-issue-summary">${item.summary}</span>
                    <span class="alert-days">${item.days}d</span>
                </div>
            `;
        });

        const nudgeAllBtn = nudgeableKeys.has(key)
            ? `<button class="btn-nudge-all" onclick="nudgeAll('${key}', this)">Nudge All (${filtered.length})</button>`
            : "";

        html += `
            <div class="alert-card ${cardClass}">
                <div class="alert-card-header">
                    <div class="alert-icon ${iconClass}">${data.icon}</div>
                    <div class="alert-title">${data.title}</div>
                    <div class="alert-count-badge">${filtered.length}</div>
                    ${nudgeAllBtn}
                </div>
                <div class="alert-issue-list">${issueRows}</div>
            </div>
        `;
    });

    const container = document.getElementById("alerts-container");
    const subtitle = document.getElementById("alerts-subtitle");

    if (totalAlerts === 0) {
        container.innerHTML = '<div class="alerts-empty">No alerts — all clear!</div>';
    } else {
        container.innerHTML = `<div class="alerts-grid">${html}</div>`;
    }

    subtitle.textContent = `${totalAlerts} issue${totalAlerts !== 1 ? "s" : ""} need attention`;

    // Update tab badge
    const tabBadge = document.getElementById("alerts-tab-count");
    if (totalAlerts > 0) {
        tabBadge.textContent = totalAlerts;
        tabBadge.style.display = "";
    } else {
        tabBadge.style.display = "none";
    }
}

// --- Alerts Export ---

function getAlertsExportRows() {
    const typeFilter = document.getElementById("filter-type").value;
    const filterIssues = (items) => items.filter(item => {
        if (typeFilter === "story" && item.issueType !== "Story") return false;
        if (typeFilter === "bug" && item.issueType !== "Bug") return false;
        if (selectedQaContacts.length > 0) {
            const match = selectedQaContacts.some(q => (item.qaContact?.name || "").toLowerCase() === q.toLowerCase());
            if (qaOperator === "equals" && !match) return false;
            if (qaOperator === "not-equals" && match) return false;
        }
        return true;
    });

    const rows = [];
    const categories = [
        { key: "bugsNoRca", label: "Bugs Without RCA (3+ days)", cols: ["Key", "Summary", "Priority", "Days"] },
        { key: "stuckInQa", label: "Stuck in QA (3+ days)", cols: ["Key", "Summary", "QA Contact", "Days"] },
        { key: "missingQa", label: "Missing QA Contact (2+ days)", cols: ["Key", "Summary", "Priority", "Days"] },
        { key: "highPriority", label: "High/Critical Unresolved (5+ days)", cols: ["Key", "Summary", "Priority", "Days"] },
    ];

    categories.forEach(({ key, label, cols }) => {
        const data = allAlertsData[key];
        if (!data) return;
        const filtered = filterIssues(data.issues || []).sort((a, b) => (b.days || 0) - (a.days || 0));
        if (filtered.length === 0) return;
        rows.push([label]);
        rows.push(cols);
        filtered.forEach(item => {
            if (key === "stuckInQa") {
                rows.push([item.key, item.summary, item.qaContact?.name || "Unassigned", item.days]);
            } else {
                rows.push([item.key, item.summary, item.priority || "None", item.days]);
            }
        });
        rows.push([]);
    });

    return rows;
}

function exportAlertsCsv() {
    const rows = getAlertsExportRows();
    if (rows.length === 0) return;
    const projectLabel = selectedProjects.join("_") || "export";
    downloadCsv(`alerts_${projectLabel}_${new Date().toISOString().slice(0, 10)}.csv`, rows);
}

function exportAlertsXlsx() {
    const rows = getAlertsExportRows();
    if (rows.length === 0) return;
    const projectLabel = selectedProjects.join("_") || "export";
    downloadXlsx(`alerts_${projectLabel}_${new Date().toISOString().slice(0, 10)}.xlsx`, [
        { name: "Alerts", rows },
    ]);
}

// --- Metrics ---

async function fetchMetrics() {
    const container = document.getElementById("metrics-container");
    const badge = document.getElementById("metrics-badge");

    if (selectedProjects.length === 0) {
        container.innerHTML = '<div class="empty-state">Please select a board from the dropdown above</div>';
        return;
    }

    container.innerHTML = '<div class="loading">Loading metrics...</div>';

    try {
        let issues = allIssues;
        if (issues.length === 0) {
            const dateParams = buildDateParams();
            const fetches = [];
            for (const proj of selectedProjects) {
                if (selectedSprints.length === 0) {
                    fetches.push(fetch(`/api/issues?project=${proj}${dateParams}`));
                } else {
                    selectedSprints.forEach(id => {
                        fetches.push(fetch(`/api/issues?project=${proj}&sprintId=${id}`));
                    });
                }
            }
            const responses = await Promise.all(fetches);
            const fetched = [];
            const seenKeys = new Set();
            for (const resp of responses) {
                const data = await resp.json();
                if (resp.ok) {
                    data.forEach(issue => {
                        if (!seenKeys.has(issue.key)) {
                            seenKeys.add(issue.key);
                            fetched.push(issue);
                        }
                    });
                }
            }
            allIssues = fetched;
            issues = fetched;
        }

        badge.textContent = selectedProjects.join(", ");
        renderMetrics(issues);
        metricsLoaded = true;
        document.getElementById("export-buttons-metrics").style.display = issues.length > 0 ? "" : "none";
        lastFetchTime = Date.now();
        updateFreshnessDisplay();
        loadSprintComparison();
    } catch (err) {
        container.innerHTML = `<div class="error">${err.message}</div>`;
    }
}

function renderMetrics(issues) {
    const container = document.getElementById("metrics-container");
    const subtitle = document.getElementById("metrics-subtitle");

    // Apply type filter
    const typeFilter = document.getElementById("filter-type").value;
    if (typeFilter === "story") issues = issues.filter(i => i.issueType === "Story");
    else if (typeFilter === "bug") issues = issues.filter(i => i.issueType === "Bug");

    // Apply status filter
    if (selectedStatuses.length > 0) {
        issues = issues.filter(i => {
            const match = selectedStatuses.includes(i.status);
            return statusOperator === "equals" ? match : !match;
        });
    }

    const stories = issues.filter(i => i.issueType === "Story");
    const defects = issues.filter(i => i.issueType === "Bug");
    const tasks = issues.filter(i => i.issueType === "Task");

    subtitle.textContent = `${issues.length} total issues · ${stories.length} stories · ${defects.length} defects · ${tasks.length} tasks`;

    const baseUrl = issues.length > 0 ? issues[0].url.replace(/\/browse\/.*$/, "") : "";

    function keysJql(issueList) {
        return `key in (${issueList.map(i => i.key).join(", ")}) ORDER BY priority DESC`;
    }

    function jiraLink(count, issueList, color) {
        if (count === 0 || !baseUrl) return `<span style="color:${color};font-weight:600">${count}</span>`;
        const url = `${baseUrl}/issues/?jql=${encodeURIComponent(keysJql(issueList))}`;
        return `<a href="${url}" target="_blank" class="metrics-link" style="color:${color}">${count}</a>`;
    }

    const priorityGroups = ["critical", "high", "medium", "low"];
    const priorityLabels = { critical: "P0 / Critical", high: "P1 / High", medium: "P2 / Medium", low: "P3 / Low" };
    const priorityColors = { critical: "#dc2626", high: "#ea580c", medium: "#d97706", low: "#16a34a" };

    const storyByPriority = {};
    const defectByPriority = {};
    const storyKeysByPriority = {};
    const defectKeysByPriority = {};
    priorityGroups.forEach(p => { storyByPriority[p] = 0; defectByPriority[p] = 0; storyKeysByPriority[p] = []; defectKeysByPriority[p] = []; });

    stories.forEach(i => { const p = getPriorityClass(i.priority); storyByPriority[p]++; storyKeysByPriority[p].push(i); });
    defects.forEach(i => { const p = getPriorityClass(i.priority); defectByPriority[p]++; defectKeysByPriority[p].push(i); });

    let priorityRows = "";
    priorityGroups.forEach(p => {
        const total = storyByPriority[p] + defectByPriority[p];
        priorityRows += `
            <tr>
                <td><span class="priority-badge ${p}">${priorityLabels[p]}</span></td>
                <td style="text-align:center">${jiraLink(storyByPriority[p], storyKeysByPriority[p], "#0052cc")}</td>
                <td style="text-align:center">${jiraLink(defectByPriority[p], defectKeysByPriority[p], "#dc2626")}</td>
                <td style="text-align:center;font-weight:700">${total}</td>
            </tr>
        `;
    });

    priorityRows += `
        <tr class="qa-total-row">
            <td><strong>Total</strong></td>
            <td style="text-align:center">${jiraLink(stories.length, stories, "#0052cc")}</td>
            <td style="text-align:center">${jiraLink(defects.length, defects, "#dc2626")}</td>
            <td style="text-align:center;font-weight:700">${stories.length + defects.length}</td>
        </tr>
    `;

    const placeholderText = "A short description of the actual root cause. If there are many root causes, list them here.";
    const rcaFilledList = defects.filter(i => (i.rca || "").trim());
    const rcaBlankList = defects.filter(i => !(i.rca || "").trim());
    const rcaPct = defects.length > 0 ? Math.round((rcaFilledList.length / defects.length) * 100) : 0;

    const rcsFilledList = defects.filter(i => {
        const val = (i.rootCauseSummary || "").replace(/\\?\{color[^}]*\}/g, "").replace(/\s+/g, " ").trim();
        return val && val !== placeholderText;
    });
    const rcsBlankList = defects.filter(i => {
        const val = (i.rootCauseSummary || "").replace(/\\?\{color[^}]*\}/g, "").replace(/\s+/g, " ").trim();
        return !val || val === placeholderText;
    });
    const rcsPct = defects.length > 0 ? Math.round((rcsFilledList.length / defects.length) * 100) : 0;

    const qaFilledList = defects.filter(i => {
        const name = i.qaContact?.name || "";
        return name && name !== "Unassigned";
    });
    const qaBlankList = defects.filter(i => {
        const name = i.qaContact?.name || "";
        return !name || name === "Unassigned";
    });
    const qaPct = defects.length > 0 ? Math.round((qaFilledList.length / defects.length) * 100) : 0;

    const qaContactMap = {};
    issues.forEach(i => {
        const name = i.qaContact?.name || "Unassigned";
        if (!qaContactMap[name]) qaContactMap[name] = { stories: [], defects: [], all: [], sprints: new Set() };
        qaContactMap[name].all.push(i);
        if (i.issueType === "Story") qaContactMap[name].stories.push(i);
        else if (i.issueType === "Bug") qaContactMap[name].defects.push(i);
        (i.sprintNames || []).forEach(sn => qaContactMap[name].sprints.add(sn));
    });
    const qaContactNames = Object.keys(qaContactMap).sort((a, b) => {
        if (a === "Unassigned") return 1;
        if (b === "Unassigned") return -1;
        return qaContactMap[b].all.length - qaContactMap[a].all.length;
    });

    let qaContactRows = "";
    qaContactNames.forEach(name => {
        const data = qaContactMap[name];
        const nameDisplay = name === "Unassigned" ? '<span style="color:#6b778c;font-style:italic">Unassigned</span>' : name;
        const sprintList = [...data.sprints];
        const sprintDisplay = sprintList.length === 0
            ? '<span style="color:#9ca3af">—</span>'
            : sprintList.map(s => `<span class="workload-sprint-tag">${s}</span>`).join(" ");
        qaContactRows += `
            <tr>
                <td>${nameDisplay}</td>
                <td class="workload-sprint-cell">${sprintDisplay}</td>
                <td style="text-align:center">${jiraLink(data.stories.length, data.stories, "#0052cc")}</td>
                <td style="text-align:center">${jiraLink(data.defects.length, data.defects, "#dc2626")}</td>
                <td style="text-align:center;font-weight:700">${jiraLink(data.all.length, data.all, "#1a1a2e")}</td>
            </tr>
        `;
    });

    const statusOrder = [];
    const statusDefects = {};
    defects.forEach(d => {
        const st = d.status || "Unknown";
        if (!statusDefects[st]) { statusDefects[st] = []; statusOrder.push(st); }
        statusDefects[st].push(d);
    });

    let statusPriorityRows = "";
    statusOrder.forEach(st => {
        const items = statusDefects[st];
        const byP = {};
        priorityGroups.forEach(p => { byP[p] = []; });
        items.forEach(d => { byP[getPriorityClass(d.priority)].push(d); });
        const statusClass = getStatusBadgeClass(st);
        statusPriorityRows += `
            <tr>
                <td><span class="badge ${statusClass}">${st}</span></td>
                <td style="text-align:center">${jiraLink(byP.critical.length, byP.critical, "#dc2626")}</td>
                <td style="text-align:center">${jiraLink(byP.high.length, byP.high, "#ea580c")}</td>
                <td style="text-align:center">${jiraLink(byP.medium.length, byP.medium, "#d97706")}</td>
                <td style="text-align:center">${jiraLink(byP.low.length, byP.low, "#16a34a")}</td>
                <td style="text-align:center;font-weight:700">${jiraLink(items.length, items, "#1a1a2e")}</td>
            </tr>
        `;
    });

    const totalByP = {};
    priorityGroups.forEach(p => { totalByP[p] = defects.filter(d => getPriorityClass(d.priority) === p); });
    statusPriorityRows += `
        <tr class="qa-total-row">
            <td><strong>Total</strong></td>
            <td style="text-align:center">${jiraLink(totalByP.critical.length, totalByP.critical, "#dc2626")}</td>
            <td style="text-align:center">${jiraLink(totalByP.high.length, totalByP.high, "#ea580c")}</td>
            <td style="text-align:center">${jiraLink(totalByP.medium.length, totalByP.medium, "#d97706")}</td>
            <td style="text-align:center">${jiraLink(totalByP.low.length, totalByP.low, "#16a34a")}</td>
            <td style="text-align:center;font-weight:700">${jiraLink(defects.length, defects, "#1a1a2e")}</td>
        </tr>
    `;

    container.innerHTML = `
        <div class="metrics-grid">
            <div class="metrics-card">
                <div class="metrics-section-title">Issue Type & Priority Breakdown</div>
                <div class="metrics-summary-cards">
                    <div class="metrics-mini-card">
                        ${stories.length > 0 && baseUrl
                            ? `<a href="${baseUrl}/issues/?jql=${encodeURIComponent(keysJql(stories))}" target="_blank" class="metrics-mini-value metrics-link" style="color:#0052cc">${stories.length}</a>`
                            : `<div class="metrics-mini-value" style="color:#0052cc">${stories.length}</div>`}
                        <div class="metrics-mini-label">Stories</div>
                    </div>
                    <div class="metrics-mini-card">
                        ${defects.length > 0 && baseUrl
                            ? `<a href="${baseUrl}/issues/?jql=${encodeURIComponent(keysJql(defects))}" target="_blank" class="metrics-mini-value metrics-link" style="color:#dc2626">${defects.length}</a>`
                            : `<div class="metrics-mini-value" style="color:#dc2626">${defects.length}</div>`}
                        <div class="metrics-mini-label">Defects</div>
                    </div>
                    <div class="metrics-mini-card">
                        ${tasks.length > 0 && baseUrl
                            ? `<a href="${baseUrl}/issues/?jql=${encodeURIComponent(keysJql(tasks))}" target="_blank" class="metrics-mini-value metrics-link" style="color:#7c3aed">${tasks.length}</a>`
                            : `<div class="metrics-mini-value" style="color:#7c3aed">${tasks.length}</div>`}
                        <div class="metrics-mini-label">Tasks</div>
                    </div>
                    <div class="metrics-mini-card">
                        <div class="metrics-mini-value" style="color:#1a1a2e">${issues.length}</div>
                        <div class="metrics-mini-label">Total</div>
                    </div>
                </div>
                <table class="qa-table" style="margin-top:16px">
                    <thead>
                        <tr>
                            <th>Priority</th>
                            <th style="text-align:center">Stories</th>
                            <th style="text-align:center">Defects</th>
                            <th style="text-align:center">Total</th>
                        </tr>
                    </thead>
                    <tbody>${priorityRows}</tbody>
                </table>
            </div>

            <div class="metrics-card">
                <div class="metrics-section-title">Defect Quality Metrics</div>
                ${defects.length === 0 ? '<div class="empty-state" style="padding:30px">No defects found</div>' : `
                    <div class="metrics-quality-row">
                        <div class="metrics-quality-label">
                            <span>RCA</span>
                            <span class="metrics-quality-count">${rcaFilledList.length} / ${defects.length} filled</span>
                        </div>
                        <div class="metrics-bar">
                            <div class="metrics-bar-fill" style="width:${rcaPct}%;background:#16a34a"></div>
                        </div>
                        <div class="metrics-bar-pct">${rcaPct}%</div>
                    </div>
                    <div class="metrics-quality-row">
                        <div class="metrics-quality-label">
                            <span>Root Cause Summary</span>
                            <span class="metrics-quality-count">${rcsFilledList.length} / ${defects.length} filled</span>
                        </div>
                        <div class="metrics-bar">
                            <div class="metrics-bar-fill" style="width:${rcsPct}%;background:#0052cc"></div>
                        </div>
                        <div class="metrics-bar-pct">${rcsPct}%</div>
                    </div>
                    <div class="metrics-quality-row">
                        <div class="metrics-quality-label">
                            <span>QA Contact Assigned</span>
                            <span class="metrics-quality-count">${qaFilledList.length} / ${defects.length} filled</span>
                        </div>
                        <div class="metrics-bar">
                            <div class="metrics-bar-fill" style="width:${qaPct}%;background:#7c3aed"></div>
                        </div>
                        <div class="metrics-bar-pct">${qaPct}%</div>
                    </div>
                    <div class="metrics-defect-detail">
                        <table class="qa-table" style="margin-top:16px">
                            <thead>
                                <tr>
                                    <th>Metric</th>
                                    <th style="text-align:center">Filled</th>
                                    <th style="text-align:center">Blank</th>
                                    <th style="text-align:center">Fill Rate</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td>RCA</td>
                                    <td style="text-align:center">${jiraLink(rcaFilledList.length, rcaFilledList, "#16a34a")}</td>
                                    <td style="text-align:center">${jiraLink(rcaBlankList.length, rcaBlankList, "#dc2626")}</td>
                                    <td style="text-align:center;font-weight:700">${rcaPct}%</td>
                                </tr>
                                <tr>
                                    <td>Root Cause Summary</td>
                                    <td style="text-align:center">${jiraLink(rcsFilledList.length, rcsFilledList, "#16a34a")}</td>
                                    <td style="text-align:center">${jiraLink(rcsBlankList.length, rcsBlankList, "#dc2626")}</td>
                                    <td style="text-align:center;font-weight:700">${rcsPct}%</td>
                                </tr>
                                <tr>
                                    <td>QA Contact</td>
                                    <td style="text-align:center">${jiraLink(qaFilledList.length, qaFilledList, "#16a34a")}</td>
                                    <td style="text-align:center">${jiraLink(qaBlankList.length, qaBlankList, "#dc2626")}</td>
                                    <td style="text-align:center;font-weight:700">${qaPct}%</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                `}
            </div>
        </div>
        ${defects.length > 0 ? `
        <div class="metrics-card metrics-full-width">
            <div class="metrics-section-title">Defect Status vs Priority</div>
            <table class="qa-table">
                <thead>
                    <tr>
                        <th>Status</th>
                        <th style="text-align:center">P0 / Critical</th>
                        <th style="text-align:center">P1 / High</th>
                        <th style="text-align:center">P2 / Medium</th>
                        <th style="text-align:center">P3 / Low</th>
                        <th style="text-align:center">Total</th>
                    </tr>
                </thead>
                <tbody>${statusPriorityRows}</tbody>
            </table>
        </div>
        ` : ""}
        <div class="metrics-card metrics-full-width">
            <div class="metrics-section-title">QA Contact Workload</div>
            <table class="qa-table">
                <thead>
                    <tr>
                        <th>QA Contact</th>
                        <th>Sprint</th>
                        <th style="text-align:center">Stories</th>
                        <th style="text-align:center">Defects</th>
                        <th style="text-align:center">Total</th>
                    </tr>
                </thead>
                <tbody>${qaContactRows}</tbody>
            </table>
        </div>
    `;

    // Sprint health trend — shown when 2+ sprints are selected
    if (selectedSprintNames.length >= 2) {
        const sprintBuckets = {};
        selectedSprintNames.forEach(name => { sprintBuckets[name] = []; });
        issues.forEach(issue => {
            (issue.sprintNames || []).forEach(sn => {
                if (sprintBuckets[sn]) sprintBuckets[sn].push(issue);
            });
        });

        const sprintData = selectedSprintNames.map(name => {
            const spIssues = sprintBuckets[name] || [];
            const qaIssues = spIssues.filter(i => i.qaContact?.name && i.qaContact.name !== "Unassigned");
            const passedIssues = qaIssues.filter(i => checkQuality(i).passed);
            const failedIssues = qaIssues.filter(i => !checkQuality(i).passed);
            const pct = qaIssues.length > 0 ? Math.round((passedIssues.length / qaIssues.length) * 100) : null;
            return { name, total: qaIssues.length, passedIssues, failedIssues, pct };
        });

        const barsHtml = sprintData.map(d => {
            const shortName = d.name.length > 38 ? d.name.slice(0, 35) + "…" : d.name;
            if (d.pct === null) return `
                <div class="trend-bar-group">
                    <div class="trend-bar-label" title="${d.name}">${shortName}</div>
                    <div class="trend-bar-empty">No QA data</div>
                </div>`;
            const color = d.pct >= 80 ? "#16a34a" : d.pct >= 60 ? "#d97706" : "#dc2626";
            const passedLink = jiraLink(d.passedIssues.length, d.passedIssues, "#16a34a");
            const totalLink = jiraLink(d.total, [...d.passedIssues, ...d.failedIssues], "#374151");
            return `
                <div class="trend-bar-group">
                    <div class="trend-bar-label" title="${d.name}">${shortName}</div>
                    <div class="trend-bar-track">
                        <div class="trend-bar-fill" style="width:${d.pct}%;background:${color}"></div>
                    </div>
                    <div class="trend-bar-pct" style="color:${color};font-weight:700">${d.pct}%</div>
                    <div class="trend-bar-sub">${passedLink}/${totalLink} passed</div>
                </div>`;
        }).join("");

        container.innerHTML += `
            <div class="metrics-card metrics-full-width">
                <div class="metrics-section-title">Sprint Quality Trend</div>
                <div class="sprint-trend-chart">${barsHtml}</div>
            </div>
        `;
    }

    // Failure reason breakdown — ranked list of what's causing failures
    const qaIssues = issues.filter(i => {
        if ((i.status || "").toLowerCase() === "no action") return false;
        const name = i.qaContact?.name || "";
        return name && name !== "Unassigned";
    });

    const failureMap = {};
    let totalFailed = 0;
    qaIssues.forEach(i => {
        const q = checkQuality(i);
        if (!q.passed) {
            totalFailed++;
            q.failures.forEach(f => {
                // Normalize variable-suffix failures to a fixed key
                let key = f;
                if (f.startsWith("QA Contact missing on subtask:")) key = "QA Contact missing on subtask";
                else if (f.startsWith("Signoff task still Open:")) key = "Signoff task still Open";
                else if (f.startsWith("Missing subtask:")) key = f; // keep specific (Test Execution vs Design)
                if (!failureMap[key]) failureMap[key] = { count: 0, issues: [] };
                failureMap[key].count++;
                if (!failureMap[key].issues.find(x => x.key === i.key)) {
                    failureMap[key].issues.push(i);
                }
            });
        }
    });

    if (Object.keys(failureMap).length > 0) {
        const sorted = Object.entries(failureMap).sort((a, b) => b[1].count - a[1].count);
        const maxCount = sorted[0][1].count;

        const breakdownRows = sorted.map(([reason, data]) => {
            const { count, issues: reasonIssues } = data;
            const barPct = Math.round((count / maxCount) * 100);
            const issuePct = qaIssues.length > 0 ? Math.round((count / qaIssues.length) * 100) : 0;
            const countLink = jiraLink(count, reasonIssues, "#dc2626");
            return `
                <div class="failure-row">
                    <div class="failure-reason" title="${reason}">${reason}</div>
                    <div class="failure-bar-track">
                        <div class="failure-bar-fill" style="width:${barPct}%"></div>
                    </div>
                    <div class="failure-count">${countLink} <span class="failure-pct">(${issuePct}%)</span></div>
                </div>
            `;
        }).join("");

        container.innerHTML += `
            <div class="metrics-card metrics-full-width">
                <div class="metrics-section-title">Top Failure Reasons
                    <span class="metrics-section-sub">${totalFailed} of ${qaIssues.length} issues failing</span>
                </div>
                <div class="failure-breakdown">${breakdownRows}</div>
            </div>
        `;
    }
}

// --- Status Tab Export ---

function getStatusExportRows() {
    const filtered = getFilteredIssues();
    const header = ["Key", "Type", "Summary", "Status", "Priority", "QA Contact", "Pass/Fail", "Failure Reasons", "Sprint(s)"];
    const rows = [header];
    filtered.forEach(issue => {
        const quality = checkQuality(issue);
        rows.push([
            issue.key,
            issue.issueType,
            issue.summary,
            issue.status,
            issue.priority,
            issue.qaContact?.name || "Unassigned",
            quality.passed ? "PASS" : "FAIL",
            quality.failures.join(" | "),
            (issue.sprintNames || []).join(", "),
        ]);
        // Include epic children as sub-rows
        if (issue.issueType === "Epic") {
            (issue.children || []).forEach(child => {
                const cq = checkQuality(child);
                rows.push([
                    child.key,
                    child.issueType,
                    child.summary,
                    child.status,
                    child.priority,
                    child.qaContact?.name || "Unassigned",
                    cq.passed ? "PASS" : "FAIL",
                    cq.failures.join(" | "),
                    (child.sprintNames || []).join(", "),
                ]);
            });
        }
    });
    return rows;
}

function exportStatusCsv() {
    const rows = getStatusExportRows();
    const projectLabel = selectedProjects.join("_") || "export";
    downloadCsv(`status_${projectLabel}_${new Date().toISOString().slice(0, 10)}.csv`, rows);
}

function exportStatusXlsx() {
    const rows = getStatusExportRows();
    const projectLabel = selectedProjects.join("_") || "export";
    downloadXlsx(`status_${projectLabel}_${new Date().toISOString().slice(0, 10)}.xlsx`, [
        { name: "Validation Status", rows },
    ]);
}

// --- CSV Export ---

function escapeCsvField(value) {
    const str = String(value ?? "");
    if (str.includes(",") || str.includes('"') || str.includes("\n")) {
        return '"' + str.replace(/"/g, '""') + '"';
    }
    return str;
}

function downloadCsv(filename, rows) {
    const csv = rows.map(row => row.map(escapeCsvField).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(link.href);
}

function exportQaTrackingCsv() {
    const typeFilter = document.getElementById("filter-type").value;
    const filtered = allQaTrackingData.filter((item) => {
        if (typeFilter === "story" && item.issueType !== "Story") return false;
        if (typeFilter === "bug" && item.issueType !== "Bug") return false;
        if (selectedQaContacts.length > 0) {
            const match = selectedQaContacts.some(q => (item.qaContact?.name || "").toLowerCase() === q.toLowerCase());
            if (qaOperator === "equals" && !match) return false;
            if (qaOperator === "not-equals" && match) return false;
        }
        return true;
    });

    const allStatuses = new Set();
    filtered.forEach((item) => {
        item.qaStatusTimes.forEach((t) => allStatuses.add(t.status));
    });
    const statusColumns = Array.from(allStatuses);

    const header = ["Key", "Type", "Summary", "QA Contact", "Assignee", "Current Status",
        ...statusColumns.map(s => s + " (hours)"), "Total QA Time (hours)"];

    const rows = [header];
    filtered.forEach((item) => {
        const timeMap = {};
        let totalHours = 0;
        item.qaStatusTimes.forEach((t) => {
            timeMap[t.status] = t.hours;
            totalHours += t.hours;
        });

        rows.push([
            item.key,
            item.issueType,
            item.summary,
            item.qaContact.name,
            item.assignee?.name || "Unassigned",
            item.currentStatus,
            ...statusColumns.map(s => timeMap[s] ? timeMap[s].toFixed(1) : "0"),
            totalHours.toFixed(1),
        ]);
    });

    const projectLabel = selectedProjects.join("_") || "export";
    downloadCsv(`qa-tracking_${projectLabel}_${new Date().toISOString().slice(0, 10)}.csv`, rows);
}

function exportMetricsCsv() {
    const issues = allIssues.length > 0 ? allIssues : [];
    const stories = issues.filter(i => i.issueType === "Story");
    const defects = issues.filter(i => i.issueType === "Bug");
    const tasks = issues.filter(i => i.issueType === "Task");

    const priorityGroups = ["critical", "high", "medium", "low"];
    const priorityLabels = { critical: "P0 / Critical", high: "P1 / High", medium: "P2 / Medium", low: "P3 / Low" };

    const rows = [];

    rows.push(["Issue Type & Priority Breakdown"]);
    rows.push(["Priority", "Stories", "Defects", "Total"]);
    priorityGroups.forEach(p => {
        const s = stories.filter(i => getPriorityClass(i.priority) === p).length;
        const d = defects.filter(i => getPriorityClass(i.priority) === p).length;
        rows.push([priorityLabels[p], s, d, s + d]);
    });
    rows.push(["Total", stories.length, defects.length, stories.length + defects.length]);
    rows.push([]);

    if (defects.length > 0) {
        const placeholderText = "A short description of the actual root cause. If there are many root causes, list them here.";
        const rcaFilled = defects.filter(i => (i.rca || "").trim()).length;
        const rcsFilled = defects.filter(i => {
            const val = (i.rootCauseSummary || "").replace(/\\?\{color[^}]*\}/g, "").trim();
            return val && val !== placeholderText;
        }).length;
        const qaFilled = defects.filter(i => {
            const name = i.qaContact?.name || "";
            return name && name !== "Unassigned";
        }).length;

        rows.push(["Defect Quality Metrics"]);
        rows.push(["Metric", "Filled", "Blank", "Fill Rate"]);
        rows.push(["RCA", rcaFilled, defects.length - rcaFilled, Math.round((rcaFilled / defects.length) * 100) + "%"]);
        rows.push(["Root Cause Summary", rcsFilled, defects.length - rcsFilled, Math.round((rcsFilled / defects.length) * 100) + "%"]);
        rows.push(["QA Contact", qaFilled, defects.length - qaFilled, Math.round((qaFilled / defects.length) * 100) + "%"]);
        rows.push([]);

        const statusDefects = {};
        const statusOrder = [];
        defects.forEach(d => {
            const st = d.status || "Unknown";
            if (!statusDefects[st]) { statusDefects[st] = []; statusOrder.push(st); }
            statusDefects[st].push(d);
        });

        rows.push(["Defect Status vs Priority"]);
        rows.push(["Status", "P0 / Critical", "P1 / High", "P2 / Medium", "P3 / Low", "Total"]);
        statusOrder.forEach(st => {
            const items = statusDefects[st];
            const byP = {};
            priorityGroups.forEach(p => { byP[p] = items.filter(d => getPriorityClass(d.priority) === p).length; });
            rows.push([st, byP.critical, byP.high, byP.medium, byP.low, items.length]);
        });
        const totalByP = {};
        priorityGroups.forEach(p => { totalByP[p] = defects.filter(d => getPriorityClass(d.priority) === p).length; });
        rows.push(["Total", totalByP.critical, totalByP.high, totalByP.medium, totalByP.low, defects.length]);
        rows.push([]);
    }

    const qaContactMap = {};
    issues.forEach(i => {
        const name = i.qaContact?.name || "Unassigned";
        if (!qaContactMap[name]) qaContactMap[name] = { stories: 0, defects: 0, total: 0, sprints: new Set() };
        qaContactMap[name].total++;
        if (i.issueType === "Story") qaContactMap[name].stories++;
        else if (i.issueType === "Bug") qaContactMap[name].defects++;
        (i.sprintNames || []).forEach(sn => qaContactMap[name].sprints.add(sn));
    });

    rows.push(["QA Contact Workload"]);
    rows.push(["QA Contact", "Sprint", "Stories", "Defects", "Total"]);
    Object.keys(qaContactMap).sort((a, b) => {
        if (a === "Unassigned") return 1;
        if (b === "Unassigned") return -1;
        return qaContactMap[b].total - qaContactMap[a].total;
    }).forEach(name => {
        const d = qaContactMap[name];
        rows.push([name, [...d.sprints].join("; "), d.stories, d.defects, d.total]);
    });
    rows.push([]);

    // Sprint Quality Trend
    if (selectedSprintNames.length >= 2) {
        const sprintBuckets = {};
        selectedSprintNames.forEach(name => { sprintBuckets[name] = []; });
        issues.forEach(issue => {
            (issue.sprintNames || []).forEach(sn => {
                if (sprintBuckets[sn]) sprintBuckets[sn].push(issue);
            });
        });
        rows.push(["Sprint Quality Trend"]);
        rows.push(["Sprint", "Total QA Issues", "Passed", "Pass Rate"]);
        selectedSprintNames.forEach(name => {
            const spIssues = sprintBuckets[name] || [];
            const qaIssues = spIssues.filter(i => i.qaContact?.name && i.qaContact.name !== "Unassigned");
            const passed = qaIssues.filter(i => checkQuality(i).passed).length;
            const pct = qaIssues.length > 0 ? Math.round((passed / qaIssues.length) * 100) + "%" : "N/A";
            rows.push([name, qaIssues.length, passed, pct]);
        });
        rows.push([]);
    }

    // Failure Reasons
    const qaIssues = issues.filter(i => {
        if ((i.status || "").toLowerCase() === "no action") return false;
        const name = i.qaContact?.name || "";
        return name && name !== "Unassigned";
    });
    const failureCount = {};
    let totalFailed = 0;
    qaIssues.forEach(i => {
        const q = checkQuality(i);
        if (!q.passed) {
            totalFailed++;
            q.failures.forEach(f => {
                let key = f;
                if (f.startsWith("QA Contact missing on subtask:")) key = "QA Contact missing on subtask";
                else if (f.startsWith("Signoff task still Open:")) key = "Signoff task still Open";
                failureCount[key] = (failureCount[key] || 0) + 1;
            });
        }
    });
    if (Object.keys(failureCount).length > 0) {
        rows.push([`Top Failure Reasons (${totalFailed} of ${qaIssues.length} issues failing)`]);
        rows.push(["Reason", "Count", "% of QA Issues"]);
        Object.entries(failureCount).sort((a, b) => b[1] - a[1]).forEach(([reason, count]) => {
            const pct = qaIssues.length > 0 ? Math.round((count / qaIssues.length) * 100) + "%" : "0%";
            rows.push([reason, count, pct]);
        });
    }

    const projectLabel = selectedProjects.join("_") || "export";
    downloadCsv(`metrics_${projectLabel}_${new Date().toISOString().slice(0, 10)}.csv`, rows);
}

// --- Excel Export ---

function downloadXlsx(filename, sheets) {
    const wb = XLSX.utils.book_new();
    sheets.forEach(({ name, rows }) => {
        const ws = XLSX.utils.aoa_to_sheet(rows);
        XLSX.utils.book_append_sheet(wb, ws, name);
    });
    XLSX.writeFile(wb, filename);
}

function exportQaTrackingXlsx() {
    const typeFilter = document.getElementById("filter-type").value;
    const filtered = allQaTrackingData.filter((item) => {
        if (typeFilter === "story" && item.issueType !== "Story") return false;
        if (typeFilter === "bug" && item.issueType !== "Bug") return false;
        if (selectedQaContacts.length > 0) {
            const match = selectedQaContacts.some(q => (item.qaContact?.name || "").toLowerCase() === q.toLowerCase());
            if (qaOperator === "equals" && !match) return false;
            if (qaOperator === "not-equals" && match) return false;
        }
        return true;
    });

    const allStatuses = new Set();
    filtered.forEach((item) => {
        item.qaStatusTimes.forEach((t) => allStatuses.add(t.status));
    });
    const statusColumns = Array.from(allStatuses);

    const header = ["Key", "Type", "Summary", "QA Contact", "Assignee", "Current Status",
        ...statusColumns.map(s => s + " (hours)"), "Total QA Time (hours)"];

    const rows = [header];
    filtered.forEach((item) => {
        const timeMap = {};
        let totalHours = 0;
        item.qaStatusTimes.forEach((t) => {
            timeMap[t.status] = t.hours;
            totalHours += t.hours;
        });

        rows.push([
            item.key,
            item.issueType,
            item.summary,
            item.qaContact.name,
            item.assignee?.name || "Unassigned",
            item.currentStatus,
            ...statusColumns.map(s => timeMap[s] ? parseFloat(timeMap[s].toFixed(1)) : 0),
            parseFloat(totalHours.toFixed(1)),
        ]);
    });

    const projectLabel = selectedProjects.join("_") || "export";
    downloadXlsx(`qa-tracking_${projectLabel}_${new Date().toISOString().slice(0, 10)}.xlsx`, [
        { name: "QA Tracking", rows },
    ]);
}

function exportMetricsXlsx() {
    const issues = allIssues.length > 0 ? allIssues : [];
    const stories = issues.filter(i => i.issueType === "Story");
    const defects = issues.filter(i => i.issueType === "Bug");

    const priorityGroups = ["critical", "high", "medium", "low"];
    const priorityLabels = { critical: "P0 / Critical", high: "P1 / High", medium: "P2 / Medium", low: "P3 / Low" };

    const sheet1 = [["Priority", "Stories", "Defects", "Total"]];
    priorityGroups.forEach(p => {
        const s = stories.filter(i => getPriorityClass(i.priority) === p).length;
        const d = defects.filter(i => getPriorityClass(i.priority) === p).length;
        sheet1.push([priorityLabels[p], s, d, s + d]);
    });
    sheet1.push(["Total", stories.length, defects.length, stories.length + defects.length]);

    const sheets = [{ name: "Priority Breakdown", rows: sheet1 }];

    if (defects.length > 0) {
        const placeholderText = "A short description of the actual root cause. If there are many root causes, list them here.";
        const rcaFilled = defects.filter(i => (i.rca || "").trim()).length;
        const rcsFilled = defects.filter(i => {
            const val = (i.rootCauseSummary || "").replace(/\\?\{color[^}]*\}/g, "").trim();
            return val && val !== placeholderText;
        }).length;
        const qaFilled = defects.filter(i => {
            const name = i.qaContact?.name || "";
            return name && name !== "Unassigned";
        }).length;

        const sheet2 = [["Metric", "Filled", "Blank", "Fill Rate"]];
        sheet2.push(["RCA", rcaFilled, defects.length - rcaFilled, Math.round((rcaFilled / defects.length) * 100) + "%"]);
        sheet2.push(["Root Cause Summary", rcsFilled, defects.length - rcsFilled, Math.round((rcsFilled / defects.length) * 100) + "%"]);
        sheet2.push(["QA Contact", qaFilled, defects.length - qaFilled, Math.round((qaFilled / defects.length) * 100) + "%"]);
        sheets.push({ name: "Quality Metrics", rows: sheet2 });

        const statusDefects = {};
        const statusOrder = [];
        defects.forEach(d => {
            const st = d.status || "Unknown";
            if (!statusDefects[st]) { statusDefects[st] = []; statusOrder.push(st); }
            statusDefects[st].push(d);
        });

        const sheet3 = [["Status", "P0 / Critical", "P1 / High", "P2 / Medium", "P3 / Low", "Total"]];
        statusOrder.forEach(st => {
            const items = statusDefects[st];
            const byP = {};
            priorityGroups.forEach(p => { byP[p] = items.filter(d => getPriorityClass(d.priority) === p).length; });
            sheet3.push([st, byP.critical, byP.high, byP.medium, byP.low, items.length]);
        });
        const totalByP = {};
        priorityGroups.forEach(p => { totalByP[p] = defects.filter(d => getPriorityClass(d.priority) === p).length; });
        sheet3.push(["Total", totalByP.critical, totalByP.high, totalByP.medium, totalByP.low, defects.length]);
        sheets.push({ name: "Status vs Priority", rows: sheet3 });
    }

    const qaContactMap = {};
    issues.forEach(i => {
        const name = i.qaContact?.name || "Unassigned";
        if (!qaContactMap[name]) qaContactMap[name] = { stories: 0, defects: 0, total: 0, sprints: new Set() };
        qaContactMap[name].total++;
        if (i.issueType === "Story") qaContactMap[name].stories++;
        else if (i.issueType === "Bug") qaContactMap[name].defects++;
        (i.sprintNames || []).forEach(sn => qaContactMap[name].sprints.add(sn));
    });

    const sheet4 = [["QA Contact", "Sprint", "Stories", "Defects", "Total"]];
    Object.keys(qaContactMap).sort((a, b) => {
        if (a === "Unassigned") return 1;
        if (b === "Unassigned") return -1;
        return qaContactMap[b].total - qaContactMap[a].total;
    }).forEach(name => {
        const d = qaContactMap[name];
        sheet4.push([name, [...d.sprints].join("; "), d.stories, d.defects, d.total]);
    });
    sheets.push({ name: "QA Workload", rows: sheet4 });

    // Sprint Quality Trend sheet
    if (selectedSprintNames.length >= 2) {
        const sprintBuckets = {};
        selectedSprintNames.forEach(name => { sprintBuckets[name] = []; });
        issues.forEach(issue => {
            (issue.sprintNames || []).forEach(sn => {
                if (sprintBuckets[sn]) sprintBuckets[sn].push(issue);
            });
        });
        const sheet5 = [["Sprint", "Total QA Issues", "Passed", "Pass Rate"]];
        selectedSprintNames.forEach(name => {
            const spIssues = sprintBuckets[name] || [];
            const qaIssues = spIssues.filter(i => i.qaContact?.name && i.qaContact.name !== "Unassigned");
            const passed = qaIssues.filter(i => checkQuality(i).passed).length;
            const pct = qaIssues.length > 0 ? Math.round((passed / qaIssues.length) * 100) + "%" : "N/A";
            sheet5.push([name, qaIssues.length, passed, pct]);
        });
        sheets.push({ name: "Sprint Trend", rows: sheet5 });
    }

    // Failure Reasons sheet
    const qaIssues = issues.filter(i => {
        if ((i.status || "").toLowerCase() === "no action") return false;
        const name = i.qaContact?.name || "";
        return name && name !== "Unassigned";
    });
    const failureCount = {};
    let totalFailed = 0;
    qaIssues.forEach(i => {
        const q = checkQuality(i);
        if (!q.passed) {
            totalFailed++;
            q.failures.forEach(f => {
                let key = f;
                if (f.startsWith("QA Contact missing on subtask:")) key = "QA Contact missing on subtask";
                else if (f.startsWith("Signoff task still Open:")) key = "Signoff task still Open";
                failureCount[key] = (failureCount[key] || 0) + 1;
            });
        }
    });
    if (Object.keys(failureCount).length > 0) {
        const sheet6 = [["Reason", "Count", "% of QA Issues"]];
        Object.entries(failureCount).sort((a, b) => b[1] - a[1]).forEach(([reason, count]) => {
            const pct = qaIssues.length > 0 ? Math.round((count / qaIssues.length) * 100) + "%" : "0%";
            sheet6.push([reason, count, pct]);
        });
        sheets.push({ name: "Failure Reasons", rows: sheet6 });
    }

    const projectLabel = selectedProjects.join("_") || "export";
    downloadXlsx(`metrics_${projectLabel}_${new Date().toISOString().slice(0, 10)}.xlsx`, sheets);
}

async function fetchAllProjectIssuesByQaContacts(qaNames) {
    const loading = document.getElementById("loading");
    const error = document.getElementById("error");

    loading.style.display = "block";
    loading.textContent = `Loading all issues for ${qaNames.join(", ")}...`;
    error.style.display = "none";

    try {
        const fetches = qaNames.map(name => fetch(`/api/issues-by-qa-contact?name=${encodeURIComponent(name)}`));
        const responses = await Promise.all(fetches);
        const seenKeys = new Set();
        const merged = [];
        for (const resp of responses) {
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || "Failed to fetch issues.");
            data.forEach(issue => {
                if (!seenKeys.has(issue.key)) {
                    seenKeys.add(issue.key);
                    merged.push(issue);
                }
            });
        }
        allIssues = merged;
        document.getElementById("tab-nav").style.display = "flex";
        renderBoard();
    } catch (err) {
        error.textContent = err.message;
        error.style.display = "block";
    } finally {
        loading.style.display = "none";
    }
}

// --- Event Listeners ---

document.getElementById("filter-type").addEventListener("change", () => {
    const currentType = document.getElementById("filter-type").value;
    const needsRefetch = (currentType === "epic") !== (lastFetchedType === "epic");
    saveFiltersToStorage();
    if (activeTab === "status") {
        if (needsRefetch) {
            fetchIssues();
        } else {
            renderBoard();
        }
    } else if (activeTab === "qa-tracking") {
        renderQaTrackingFiltered();
        if (alertsLoaded) renderAlertsFiltered();
    } else if (activeTab === "metrics") {
        if (metricsLoaded) renderMetrics(allIssues);
        if (alertsLoaded) renderAlertsFiltered();
    } else {
        renderAlertsFiltered();
    }
});
document.getElementById("btn-refresh").addEventListener("click", async () => {
    allIssues = [];
    qaTrackingLoaded = false;
    alertsLoaded = false;
    metricsLoaded = false;
    workloadLoaded = false;
    try { await fetch("/api/cache", { method: "DELETE" }); } catch {}
    if (activeTab === "status") {
        fetchIssues();
    } else if (activeTab === "qa-tracking") {
        fetchQaTracking();
    } else if (activeTab === "alerts") {
        fetchAlerts();
    } else if (activeTab === "metrics") {
        fetchMetrics();
    } else if (activeTab === "workload") {
        loadWorkload();
    }
});
document.getElementById("toggle-pass-fail").addEventListener("change", () => { saveFiltersToStorage(); renderBoard(); });
document.getElementById("btn-export-status").addEventListener("click", exportStatusCsv);
document.getElementById("btn-export-status-xlsx").addEventListener("click", exportStatusXlsx);
document.getElementById("btn-export-qa-tracking").addEventListener("click", exportQaTrackingCsv);
document.getElementById("btn-export-qa-tracking-xlsx").addEventListener("click", exportQaTrackingXlsx);
document.getElementById("btn-export-metrics").addEventListener("click", exportMetricsCsv);
document.getElementById("btn-export-metrics-xlsx").addEventListener("click", exportMetricsXlsx);
document.getElementById("btn-export-alerts").addEventListener("click", exportAlertsCsv);
document.getElementById("btn-export-alerts-xlsx").addEventListener("click", exportAlertsXlsx);

initStatusDropdown();

document.getElementById("sort-by").addEventListener("change", () => {
    currentSort = document.getElementById("sort-by").value;
    saveFiltersToStorage();
    if (activeTab === "status") renderBoard();
    else if (activeTab === "qa-tracking" && qaTrackingLoaded) renderQaTrackingFiltered();
});

document.getElementById("date-from").addEventListener("change", onDateRangeChange);
document.getElementById("date-to").addEventListener("change", onDateRangeChange);
document.getElementById("btn-clear-dates").addEventListener("click", () => {
    document.getElementById("date-from").value = "";
    document.getElementById("date-to").value = "";
    onDateRangeChange();
});

initProjectDropdown();
initSprintDropdown();
initTabs();
initQaContactDropdown();
loadProjects();

// ── Utility helpers ───────────────────────────────────────────────────────────

async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    return res.json();
}

function getApiKey() {
    return sessionStorage.getItem("jd_api_key") || "";
}

async function apiPost(url, body) {
    const headers = { "Content-Type": "application/json" };
    const key = getApiKey();
    if (key) headers["X-API-Key"] = key;
    const res = await fetch(url, { method: "POST", headers, body: JSON.stringify(body) });
    return res.json();
}

function showToast(msg, duration = 3000) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.style.display = "block";
    el.classList.add("toast-show");
    setTimeout(() => {
        el.classList.remove("toast-show");
        setTimeout(() => { el.style.display = "none"; }, 300);
    }, duration);
}

// ── Health Score ──────────────────────────────────────────────────────────────

async function loadHealthScore() {
    const banner = document.getElementById("health-score-banner");
    const scoreEl = document.getElementById("health-score-value");
    const detailEl = document.getElementById("health-score-detail");
    if (!banner || selectedProjects.length === 0) return;
    try {
        const project = selectedProjects[0];
        const sprint = selectedSprints.length > 0 ? `&sprintId=${selectedSprints[0]}` : "";
        const data = await fetchJSON(`/api/health-score?project=${project}${sprint}`);
        const score = data.score ?? 0;
        scoreEl.textContent = `${score}`;
        scoreEl.className = "health-score-value " +
            (score >= 80 ? "health-green" : score >= 60 ? "health-yellow" : "health-red");
        detailEl.textContent = `${data.alerts} alert(s), ${data.missing_subtasks} missing subtask(s) of ${data.total} issues`;
        banner.style.display = "flex";
    } catch (e) {
        banner.style.display = "none";
    }
}

// ── Workload ──────────────────────────────────────────────────────────────────

async function loadWorkload() {
    const container = document.getElementById("workload-container");
    const loading = document.getElementById("workload-loading");
    const badge = document.getElementById("workload-badge");
    if (!container) return;
    if (selectedProjects.length === 0) {
        container.innerHTML = '<div class="empty-state">Please select a board first</div>';
        return;
    }
    loading.style.display = "block";
    container.innerHTML = "";
    try {
        const project = selectedProjects[0];
        const sprint = selectedSprints.length > 0 ? `&sprintId=${selectedSprints[0]}` : "";
        const data = await fetchJSON(`/api/workload?project=${project}${sprint}`);
        workloadLoaded = true;
        if (badge) badge.textContent = project;
        renderWorkload(data.engineers || []);
    } catch (e) {
        container.innerHTML = `<div class="error">Failed to load workload: ${e.message}</div>`;
    } finally {
        loading.style.display = "none";
    }
}

function renderWorkload(engineers) {
    const container = document.getElementById("workload-container");
    if (!container) return;
    if (engineers.length === 0) {
        container.innerHTML = '<div class="empty-state">No workload data found</div>';
        return;
    }
    const maxCount = Math.max(...engineers.map(e => e.total || 0), 1);
    container.innerHTML = engineers.map(eng => {
        const pct = Math.round(((eng.total || 0) / maxCount) * 100);
        const statusBreakdown = Object.entries(eng.by_status || {})
            .map(([st, count]) => `<span class="workload-status-chip">${st}: ${count}</span>`)
            .join("");
        return `<div class="workload-row">
            <div class="workload-name">${eng.name}</div>
            <div class="workload-bar-wrap">
                <div class="workload-bar" style="width:${pct}%"></div>
            </div>
            <div class="workload-count">${eng.total}</div>
            <div class="workload-statuses">${statusBreakdown}</div>
        </div>`;
    }).join("");
}

// ── Velocity ──────────────────────────────────────────────────────────────────

async function loadVelocity() {
    const container = document.getElementById("velocity-container");
    const section = document.getElementById("velocity-section");
    if (!container || selectedProjects.length === 0) return;
    try {
        const project = selectedProjects[0];
        const sprint = selectedSprints.length > 0 ? `&sprintId=${selectedSprints[0]}` : "";
        const data = await fetchJSON(`/api/velocity?project=${project}${sprint}`);
        renderVelocity(data.engineers || []);
        if (section) section.style.display = "";
    } catch (e) {
        if (section) section.style.display = "none";
    }
}

function renderVelocity(engineers) {
    const container = document.getElementById("velocity-container");
    if (!container) return;
    if (engineers.length === 0) {
        container.innerHTML = '<div class="empty-state">No velocity data</div>';
        return;
    }
    container.innerHTML = `<table class="velocity-table">
        <thead><tr><th>Engineer</th><th>Done</th><th>In Progress</th><th>Total</th></tr></thead>
        <tbody>${engineers.map(e => `<tr>
            <td>${e.name}</td>
            <td>${e.done || 0}</td>
            <td>${e.in_progress || 0}</td>
            <td>${e.total || 0}</td>
        </tr>`).join("")}</tbody>
    </table>`;
}

// ── Sprint Comparison ─────────────────────────────────────────────────────────

async function loadSprintComparison() {
    const container = document.getElementById("sprint-comparison-container");
    const section = document.getElementById("sprint-comparison-section");
    if (!container) return;
    try {
        const project = selectedProjects.length > 0 ? `?project=${selectedProjects[0]}` : "";
        const snapshots = await fetchJSON(`/api/sprint-snapshots${project}`);
        renderSprintComparison(snapshots);
        if (section) section.style.display = "";
    } catch (e) {
        if (section) section.style.display = "none";
    }
}

function renderSprintComparison(snapshots) {
    const container = document.getElementById("sprint-comparison-container");
    if (!container) return;
    if (!snapshots || snapshots.length === 0) {
        container.innerHTML = '<div class="empty-state">No snapshots yet. Click "Take Snapshot" to record the current sprint state.</div>';
        return;
    }
    const rows = [...snapshots].reverse().slice(0, 10).map(s => {
        const dt = new Date(s.captured_at).toLocaleString();
        const statusCells = Object.entries(s.statuses || {})
            .map(([st, n]) => `${st}: ${n}`).join(", ");
        return `<tr>
            <td>${s.project || ""}</td>
            <td>${s.sprint_id || "all"}</td>
            <td>${dt}</td>
            <td>${s.total}</td>
            <td>${s.alerts}</td>
            <td class="snapshot-statuses">${statusCells}</td>
        </tr>`;
    }).join("");
    container.innerHTML = `<table class="velocity-table">
        <thead><tr><th>Project</th><th>Sprint</th><th>Captured</th><th>Total</th><th>Alerts</th><th>Statuses</th></tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}

// ── Digest Modal ──────────────────────────────────────────────────────────────

async function showDigestModal() {
    if (selectedProjects.length === 0) { showToast("Please select a board first"); return; }
    const modal = document.getElementById("digest-modal");
    const textEl = document.getElementById("digest-text");
    if (!modal || !textEl) return;
    textEl.textContent = "Loading...";
    modal.style.display = "flex";
    try {
        const project = selectedProjects[0];
        const sprint = selectedSprints.length > 0 ? `&sprintId=${selectedSprints[0]}` : "";
        const data = await fetchJSON(`/api/digest?project=${project}${sprint}`);
        textEl.textContent = data.text || "(empty)";
    } catch (e) {
        textEl.textContent = `Error: ${e.message}`;
    }
}

// ── Settings Modal ────────────────────────────────────────────────────────────

async function openSettingsModal() {
    const modal = document.getElementById("settings-modal");
    if (!modal) return;
    try {
        const data = await fetchJSON("/api/settings");
        const sla = data.sla_hours || {};
        const setVal = (id, val, fallback) => {
            const el = document.getElementById(id);
            if (el) el.value = val != null ? val : (fallback || "");
        };
        setVal("sla-ready-for-qa", sla["Ready for QA"], 24);
        setVal("sla-in-qa", sla["In QA"], 48);
        setVal("sla-qa-in-progress", sla["QA In Progress"], 48);
        setVal("sla-alert-cooldown", data.alert_cooldown_hours, 24);
        const hintEl = document.getElementById("settings-api-key-hint");
        if (hintEl) hintEl.textContent = data.api_key_set ? "API key is set." : "No API key set (write ops unrestricted).";
    } catch (e) {
        showToast("Could not load settings");
    }
    modal.style.display = "flex";
}

async function saveSettings() {
    const getVal = (id) => {
        const el = document.getElementById(id);
        return el ? parseInt(el.value, 10) || null : null;
    };
    const apiKeyEl = document.getElementById("settings-api-key");
    const payload = {
        sla_hours: {
            "Ready for QA": getVal("sla-ready-for-qa"),
            "In QA": getVal("sla-in-qa"),
            "QA In Progress": getVal("sla-qa-in-progress"),
        },
        alert_cooldown_hours: getVal("sla-alert-cooldown"),
    };
    if (apiKeyEl && apiKeyEl.value.trim()) {
        payload.api_key = apiKeyEl.value.trim();
        sessionStorage.setItem("jd_api_key", payload.api_key);
    }
    try {
        const result = await apiPost("/api/settings", payload);
        if (result.success) {
            showToast("Settings saved");
            document.getElementById("settings-modal").style.display = "none";
        } else {
            showToast("Failed to save settings");
        }
    } catch (e) {
        showToast(`Error: ${e.message}`);
    }
}

// ── Auto-refresh ──────────────────────────────────────────────────────────────

let _autoRefreshTimer = null;
const AUTO_REFRESH_INTERVAL_MS = 5 * 60 * 1000;

function startAutoRefresh() {
    stopAutoRefresh();
    _autoRefreshTimer = setInterval(() => {
        allIssues = [];
        qaTrackingLoaded = false;
        alertsLoaded = false;
        metricsLoaded = false;
        workloadLoaded = false;
        fetch("/api/cache", { method: "DELETE" }).catch(() => {});
        if (activeTab === "status") fetchIssues();
        else if (activeTab === "qa-tracking") fetchQaTracking();
        else if (activeTab === "alerts") fetchAlerts();
        else if (activeTab === "metrics") fetchMetrics();
        else if (activeTab === "workload") loadWorkload();
    }, AUTO_REFRESH_INTERVAL_MS);
}

function stopAutoRefresh() {
    if (_autoRefreshTimer) { clearInterval(_autoRefreshTimer); _autoRefreshTimer = null; }
}

// ── Bulk Ping ─────────────────────────────────────────────────────────────────

async function bulkPingSelected() {
    const checkboxes = document.querySelectorAll(".alert-select-checkbox:checked");
    if (checkboxes.length === 0) { showToast("No issues selected"); return; }
    let success = 0, skipped = 0, failed = 0;
    for (const cb of checkboxes) {
        const issueKey = cb.dataset.issueKey;   // set from data-issue-key
        const qaName = cb.dataset.qaName || "";
        const accountId = cb.dataset.accountId || undefined;
        try {
            const res = await apiPost("/api/add-comment", { issueKey, qaName, accountId });
            if (res.skipped) skipped++;
            else if (res.success) success++;
            else failed++;
        } catch {
            failed++;
        }
    }
    showToast(`Pinged: ${success} sent, ${skipped} skipped (cooldown), ${failed} failed`);
}

// ── New event listeners ───────────────────────────────────────────────────────

const autoRefreshToggle = document.getElementById("auto-refresh-toggle");
if (autoRefreshToggle) {
    autoRefreshToggle.addEventListener("change", () => {
        if (autoRefreshToggle.checked) startAutoRefresh();
        else stopAutoRefresh();
    });
}

const btnDigest = document.getElementById("btn-digest");
if (btnDigest) btnDigest.addEventListener("click", showDigestModal);

const digestModalClose = document.getElementById("digest-modal-close");
if (digestModalClose) digestModalClose.addEventListener("click", () => {
    document.getElementById("digest-modal").style.display = "none";
});

const btnDigestClose = document.getElementById("btn-digest-close");
if (btnDigestClose) btnDigestClose.addEventListener("click", () => {
    document.getElementById("digest-modal").style.display = "none";
});

const btnDigestCopy = document.getElementById("btn-digest-copy");
if (btnDigestCopy) btnDigestCopy.addEventListener("click", () => {
    const text = document.getElementById("digest-text")?.textContent || "";
    navigator.clipboard.writeText(text).then(() => showToast("Copied!")).catch(() => {});
});

const btnSettings = document.getElementById("btn-settings");
if (btnSettings) btnSettings.addEventListener("click", openSettingsModal);

const settingsModalClose = document.getElementById("settings-modal-close");
if (settingsModalClose) settingsModalClose.addEventListener("click", () => {
    document.getElementById("settings-modal").style.display = "none";
});

const btnSettingsCancel = document.getElementById("btn-settings-cancel");
if (btnSettingsCancel) btnSettingsCancel.addEventListener("click", () => {
    document.getElementById("settings-modal").style.display = "none";
});

const btnSettingsSave = document.getElementById("btn-settings-save");
if (btnSettingsSave) btnSettingsSave.addEventListener("click", saveSettings);

const alertsSelectAll = document.getElementById("alerts-select-all");
if (alertsSelectAll) {
    alertsSelectAll.addEventListener("change", () => {
        document.querySelectorAll(".alert-select-checkbox").forEach(cb => {
            cb.checked = alertsSelectAll.checked;
        });
        updateBulkCount();
    });
}

const btnBulkPing = document.getElementById("btn-bulk-ping");
if (btnBulkPing) btnBulkPing.addEventListener("click", bulkPingSelected);

function updateBulkCount() {
    const count = document.querySelectorAll(".alert-select-checkbox:checked").length;
    const countEl = document.getElementById("bulk-selected-count");
    if (countEl) countEl.textContent = `${count} selected`;
}

document.addEventListener("change", (e) => {
    if (e.target.classList.contains("alert-select-checkbox")) updateBulkCount();
});

const btnSnapshot = document.getElementById("btn-snapshot");
if (btnSnapshot) {
    btnSnapshot.addEventListener("click", async () => {
        if (selectedProjects.length === 0) { showToast("Please select a board first"); return; }
        btnSnapshot.disabled = true;
        try {
            const res = await apiPost("/api/sprint-snapshot", {
                project: selectedProjects[0],
                sprintId: selectedSprints.length > 0 ? selectedSprints[0] : null,
            });
            if (res.success) { showToast("Snapshot saved"); loadSprintComparison(); }
            else showToast("Failed to save snapshot");
        } catch (e) {
            showToast(`Error: ${e.message}`);
        } finally {
            btnSnapshot.disabled = false;
        }
    });
}

// Close modals on overlay click
document.querySelectorAll(".modal-overlay").forEach(overlay => {
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) overlay.style.display = "none";
    });
});

// Show bulk action bar when alerts tab is active
const bulkBar = document.getElementById("bulk-action-bar");
document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        if (bulkBar) bulkBar.style.display = btn.dataset.tab === "alerts" ? "flex" : "none";
    });
});
