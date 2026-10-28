// SOQL Builder UI. Works offline (file://) for query building; when served by
// server.mjs over http://127.0.0.1 it also runs queries and saves edits via
// the sf CLI. See README.md.

const IS_FILE_PROTOCOL = location.protocol === "file:";
const AUTH_TOKEN = window.AUTH_TOKEN || "";
const MAX_LOOKUP_DEPTH = 6;

let connected = false;
let currentOrg = null;

// Multiple objects can be checked at once; each gets its own independent
// field/lookup/related-list selection and its own generated query. Only one
// object's field-tree/related-lists panel is shown at a time (the "active"
// one) — clicking a row switches the panel without changing what's checked.
const selectedObjects = new Set(); // apiNames included in the generated SOQL, in check order
let activeObject = null; // apiName currently shown in the field-tree / related-lists panels
const objectStates = new Map(); // apiName -> { selectedFields: Set<string>, expandedLookups: Set<string>, relatedLists: Map<relName, {childObject, fields: Set<string>}> }

let manualEditMode = false;
let programmaticTextareaUpdate = false;
let fieldSearchFilter = "";

// ---------- Inline field-name autocomplete (SOQL textarea) ----------
let suggestState = null; // { items, wordStart, wordEnd, activeIndex } | null
let suppressNextAutoSuggest = false;
const MARKER_RE = /^--\s*====\s*Query\s*\d+:\s*(.+?)\s*====\s*$/gm;

const $ = (sel) => document.querySelector(sel);

function relNameForDotTraversal(fieldName) {
  if (fieldName.endsWith("__c")) return fieldName.replace(/__c$/, "__r");
  if (fieldName.endsWith("Id")) return fieldName.replace(/Id$/, "");
  return fieldName;
}

function getObjectState(apiName) {
  let state = objectStates.get(apiName);
  if (!state) {
    state = { selectedFields: new Set(["Id"]), expandedLookups: new Set(), relatedLists: new Map() };
    objectStates.set(apiName, state);
  }
  return state;
}

// ---------- Object picker (multi-select via checkbox; click row to preview) ----------

function renderObjectList(filterText) {
  const list = $("#object-list");
  list.innerHTML = "";
  const filter = (filterText || "").trim().toLowerCase();
  const names = Object.keys(SCHEMA.objects).sort();
  const matches = names.filter((apiName) => {
    if (!filter) return true;
    const obj = SCHEMA.objects[apiName];
    return apiName.toLowerCase().includes(filter) || obj.label.toLowerCase().includes(filter);
  });
  const DISPLAY_CAP = 300; // keep the DOM light while typing a broad filter
  const toRender = matches.slice(0, DISPLAY_CAP);
  for (const apiName of toRender) {
    const obj = SCHEMA.objects[apiName];
    const row = document.createElement("div");
    row.className = "object-row" + (apiName === activeObject ? " selected" : "");

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "obj-check";
    checkbox.checked = selectedObjects.has(apiName);
    checkbox.title = "Include this object as a query in the generated SOQL";
    checkbox.addEventListener("change", () => toggleObjectSelected(apiName, checkbox.checked));

    const labelWrap = document.createElement("div");
    labelWrap.className = "obj-label";
    labelWrap.innerHTML = `${escapeHtml(obj.label)}<span class="api-name">${escapeHtml(apiName)}</span>`;

    row.appendChild(checkbox);
    row.appendChild(labelWrap);
    row.addEventListener("click", (e) => {
      if (e.target === checkbox) return;
      setActiveObject(apiName);
    });
    list.appendChild(row);
  }
  if (matches.length === 0) {
    list.innerHTML = `<div class="object-row">No objects match "${escapeHtml(filterText)}"</div>`;
  } else if (matches.length > DISPLAY_CAP) {
    const notice = document.createElement("div");
    notice.className = "object-row muted";
    notice.textContent = `Showing ${DISPLAY_CAP} of ${matches.length} matching objects — refine your search to see the rest.`;
    list.appendChild(notice);
  }
}

function toggleObjectSelected(apiName, checked) {
  if (checked) {
    selectedObjects.add(apiName);
    getObjectState(apiName);
    activeObject = apiName;
  } else {
    selectedObjects.delete(apiName);
    if (activeObject === apiName) {
      const remaining = [...selectedObjects];
      activeObject = remaining.length ? remaining[remaining.length - 1] : null;
    }
  }
  renderObjectList($("#object-search").value);
  renderActivePanels();
  regenerateIfAuto();
}

function setActiveObject(apiName) {
  activeObject = apiName;
  getObjectState(apiName);
  renderObjectList($("#object-search").value);
  renderActivePanels();
}

function renderActivePanels() {
  const label = $("#root-object-label");
  if (!activeObject) {
    label.innerHTML = "No object selected yet.";
  } else {
    const included = selectedObjects.has(activeObject);
    label.innerHTML =
      `Editing: <code>${escapeHtml(activeObject)}</code> — ${escapeHtml(SCHEMA.objects[activeObject].label)}` +
      (included ? "" : ` <span class="muted">(not checked — check the box to include it in the query)</span>`);
  }
  renderFieldTree();
  renderRelatedLists();
}

// ---------- Field tree (with recursive lookup expansion) ----------

function renderFieldTree() {
  const container = $("#field-tree");
  container.innerHTML = "";
  if (!activeObject) return;
  container.appendChild(buildFieldNodeList(activeObject, "", 0));
  if (connected) {
    const forObject = activeObject;
    getDescribeFields(forObject).then((fields) => {
      if (!fields || activeObject !== forObject) return;
      applyDescribeBadges(fields);
    });
  }
}

// ---------- Field usage / describe info (Inspector Advanced-style badges) ----------
// Live sf sobject describe metadata (required/read-only/unique) shown as small
// badges next to each of the active object's own top-level fields. Only
// available in connected mode; nested lookup-expansion fields and related-list
// fields are left as-is (no extra describe calls for those).

const describeCache = new Map(); // "org::apiName" -> Promise<{ [fieldName]: {...} }>

function getDescribeFields(apiName) {
  if (!connected || !currentOrg) return Promise.resolve(null);
  const key = `${currentOrg}::${apiName}`;
  if (!describeCache.has(key)) {
    describeCache.set(
      key,
      fetch(`/api/describe?sobject=${encodeURIComponent(apiName)}&org=${encodeURIComponent(currentOrg)}`, {
        headers: apiHeaders(),
      })
        .then((r) => r.json())
        .then((d) => d.fields || {})
        .catch(() => ({})),
    );
  }
  return describeCache.get(key);
}

function applyDescribeBadges(fields) {
  const container = $("#field-tree");
  const nodes = container.querySelectorAll("[data-dot-path]");
  for (const node of nodes) {
    const info = fields[node.dataset.dotPath];
    if (!info) continue;
    const badge = node.querySelector(".field-badge");
    if (!badge) continue;
    const labels = [];
    if (!info.nillable && info.createable) labels.push("required");
    if (!info.updateable && !info.createable) labels.push("read-only");
    else if (!info.updateable) labels.push("create-only");
    if (info.unique) labels.push("unique");
    if (info.externalId) labels.push("external ID");
    badge.textContent = labels.join(" · ");
    badge.classList.toggle("required", labels.includes("required"));
  }
}

function buildFieldNodeList(objApiName, pathPrefix, depth) {
  const wrap = document.createElement("div");
  const obj = SCHEMA.objects[objApiName];
  if (!obj) {
    wrap.textContent = `(unknown object ${objApiName})`;
    return wrap;
  }
  // Search only filters the top-level field list (the object currently being
  // browsed) — fields reached by expanding a lookup are a deliberate drill-down
  // the user already opened, so they stay fully visible regardless of the filter.
  const filter = depth === 0 ? fieldSearchFilter.trim().toLowerCase() : "";
  let shown = 0;
  for (const field of obj.fields) {
    if (filter && !field.label.toLowerCase().includes(filter) && !field.name.toLowerCase().includes(filter)) {
      continue;
    }
    shown++;
    wrap.appendChild(buildFieldNode(objApiName, field, pathPrefix, depth));
  }
  if (filter && shown === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = `No fields match "${fieldSearchFilter.trim()}".`;
    wrap.appendChild(empty);
  }
  return wrap;
}

function buildFieldNode(objApiName, field, pathPrefix, depth) {
  const dotPath = pathPrefix ? `${pathPrefix}.${field.name}` : field.name;
  const state = getObjectState(activeObject);
  const node = document.createElement("div");
  node.className = "field-node";
  node.dataset.dotPath = dotPath;

  const label = document.createElement("label");

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = state.selectedFields.has(dotPath);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) state.selectedFields.add(dotPath);
    else state.selectedFields.delete(dotPath);
    regenerateIfAuto();
  });
  label.appendChild(checkbox);

  const text = document.createElement("span");
  text.textContent = `${field.label} `;
  label.appendChild(text);

  const apiNameSpan = document.createElement("span");
  apiNameSpan.className = "field-api-name";
  apiNameSpan.textContent = dotPath;
  label.appendChild(apiNameSpan);

  const typeSpan = document.createElement("span");
  typeSpan.className = "field-type";
  typeSpan.textContent = field.referenceTo ? `${field.type} → ${field.referenceTo}` : field.type;
  label.appendChild(typeSpan);

  const badge = document.createElement("span");
  badge.className = "field-badge";
  label.appendChild(badge);

  const isLookup = Boolean(field.referenceTo) && SCHEMA.objects[field.referenceTo];
  if (isLookup && depth < MAX_LOOKUP_DEPTH) {
    const expandKey = dotPath;
    const expandBtn = document.createElement("button");
    expandBtn.type = "button";
    expandBtn.className = "expand-lookup";
    expandBtn.textContent = state.expandedLookups.has(expandKey) ? "▾ collapse" : "▸ expand";
    expandBtn.addEventListener("click", (e) => {
      e.preventDefault();
      if (state.expandedLookups.has(expandKey)) state.expandedLookups.delete(expandKey);
      else state.expandedLookups.add(expandKey);
      renderFieldTree();
    });
    label.appendChild(expandBtn);
  }

  node.appendChild(label);

  if (isLookup && state.expandedLookups.has(dotPath)) {
    const childWrap = document.createElement("div");
    childWrap.className = "field-children";
    const relName = relNameForDotTraversal(field.name);
    const childPathPrefix = pathPrefix ? `${pathPrefix}.${relName}` : relName;
    childWrap.appendChild(buildFieldNodeList(field.referenceTo, childPathPrefix, depth + 1));
    node.appendChild(childWrap);
  }

  return node;
}

// ---------- Related lists (child subqueries, one level deep) ----------

function renderRelatedLists() {
  const container = $("#related-lists");
  container.innerHTML = "";
  if (!activeObject) return;
  const children = SCHEMA.childRelationships[activeObject] || [];
  if (children.length === 0) {
    container.innerHTML = `<p class="muted">No child relationships found for this object.</p>`;
    return;
  }
  for (const rel of children) {
    container.appendChild(buildRelatedListPanel(rel));
  }
}

function buildRelatedListPanel(rel) {
  const details = document.createElement("details");
  details.className = "related-list-panel";
  const summary = document.createElement("summary");
  summary.innerHTML = `${escapeHtml(rel.childObject)} <span class="relationship-name">FROM ${escapeHtml(rel.relationshipName)}</span>`;
  details.appendChild(summary);

  const childObj = SCHEMA.objects[rel.childObject];
  const objState = getObjectState(activeObject);
  // Only added to objState.relatedLists (and therefore only included in the
  // generated SOQL) once the user actually checks a field below — merely
  // rendering this panel (which happens for every child relationship whenever
  // this object's panel is shown) must not opt the related list into the query.

  const fieldWrap = document.createElement("div");
  fieldWrap.className = "field-tree";
  for (const field of childObj.fields) {
    const row = document.createElement("div");
    row.className = "field-node";
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    const existing = objState.relatedLists.get(rel.relationshipName);
    checkbox.checked = Boolean(existing && existing.fields.has(field.name));
    checkbox.addEventListener("change", () => {
      let state = objState.relatedLists.get(rel.relationshipName);
      if (!state) {
        state = { childObject: rel.childObject, fields: new Set() };
        objState.relatedLists.set(rel.relationshipName, state);
      }
      if (checkbox.checked) state.fields.add(field.name);
      else state.fields.delete(field.name);
      if (state.fields.size === 0) objState.relatedLists.delete(rel.relationshipName);
      regenerateIfAuto();
    });
    label.appendChild(checkbox);
    const text = document.createElement("span");
    text.textContent = `${field.label} `;
    label.appendChild(text);
    const typeSpan = document.createElement("span");
    typeSpan.className = "field-type";
    typeSpan.textContent = field.type;
    label.appendChild(typeSpan);
    row.appendChild(label);
    fieldWrap.appendChild(row);
  }
  details.appendChild(fieldWrap);
  return details;
}

// ---------- SOQL generation ----------

function generateSOQLForObject(apiName) {
  const state = getObjectState(apiName);
  const fields = [...state.selectedFields];
  if (fields.length === 0) fields.push("Id");

  const subqueries = [];
  for (const [relationshipName, relState] of state.relatedLists.entries()) {
    if (relState.fields.size === 0) continue;
    const subFields = [...relState.fields].join(", ");
    subqueries.push(`  (SELECT ${subFields} FROM ${relationshipName})`);
  }

  const selectParts = [...fields, ...subqueries.map((s) => s.trim())];
  const multiline = selectParts.length > 4 || subqueries.length > 0;

  if (multiline) {
    return `SELECT\n  ${fields.join(",\n  ")}${subqueries.length ? ",\n" + subqueries.join(",\n") : ""}\nFROM ${apiName}\nWHERE Id != null`;
  }
  return `SELECT ${fields.join(", ")}\nFROM ${apiName}\nWHERE Id != null`;
}

// Two selected objects are "directly related" when one is a schema-known
// parent of the other (SCHEMA.childRelationships), in either check order.
function findDirectRelations(objA, objB) {
  const relations = [];
  for (const r of SCHEMA.childRelationships[objA] || []) {
    if (r.childObject === objB) relations.push({ parent: objA, child: objB, relationshipName: r.relationshipName });
  }
  for (const r of SCHEMA.childRelationships[objB] || []) {
    if (r.childObject === objA) relations.push({ parent: objB, child: objA, relationshipName: r.relationshipName });
  }
  return relations;
}

// Union-find over the checked object names: any two objects with a direct
// parent-child relationship land in the same group so they can be merged
// into one query. Objects with no detected relationship to anything else
// stay in their own singleton group (existing independent-query behavior).
function groupSelectedByRelationship(names) {
  const parentPtr = new Map(names.map((n) => [n, n]));
  const find = (x) => {
    while (parentPtr.get(x) !== x) x = parentPtr.get(x);
    return x;
  };
  const union = (a, b) => {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parentPtr.set(ra, rb);
  };

  const relations = [];
  for (let i = 0; i < names.length; i++) {
    for (let j = i + 1; j < names.length; j++) {
      const rels = findDirectRelations(names[i], names[j]);
      if (rels.length) {
        union(names[i], names[j]);
        relations.push(...rels);
      }
    }
  }

  const groupMap = new Map();
  for (const n of names) {
    const root = find(n);
    if (!groupMap.has(root)) groupMap.set(root, []);
    groupMap.get(root).push(n);
  }
  return { groups: [...groupMap.values()], relations };
}

// Builds one query rooted at `root`, folding each directly-related checked
// child object in as a `(SELECT ... FROM <relationshipName>)` subquery using
// that child's own selected fields, instead of emitting it as a separate
// top-level query.
function generateMergedSOQL(root, directRelations) {
  const state = getObjectState(root);
  const fields = [...state.selectedFields];
  if (fields.length === 0) fields.push("Id");

  const usedRelNames = new Set();
  const subqueries = [];
  for (const rel of directRelations) {
    usedRelNames.add(rel.relationshipName);
    const childState = getObjectState(rel.child);
    const childFields = [...childState.selectedFields];
    if (childFields.length === 0) childFields.push("Id");
    subqueries.push(`  (SELECT ${childFields.join(", ")} FROM ${rel.relationshipName})`);
  }
  // The root's own related-list picks still apply, as long as they don't
  // duplicate a relationship name already covered by a merged child object.
  for (const [relationshipName, relState] of state.relatedLists.entries()) {
    if (usedRelNames.has(relationshipName) || relState.fields.size === 0) continue;
    subqueries.push(`  (SELECT ${[...relState.fields].join(", ")} FROM ${relationshipName})`);
  }

  const mergeNote =
    directRelations.length > 0
      ? `-- Merged with ${directRelations.map((r) => `${r.child} (via ${r.relationshipName})`).join(", ")} — detected as a direct child relationship.\n`
      : "";

  return `${mergeNote}SELECT\n  ${fields.join(",\n  ")}${subqueries.length ? ",\n" + subqueries.join(",\n") : ""}\nFROM ${root}\nWHERE Id != null`;
}

// When exactly one object is checked, generate a single plain query (matches
// prior single-object behavior exactly). With more than one checked, any
// objects with a detected direct parent-child relationship are merged into a
// single query (parent root + child subquery); objects with no detected
// relationship to anything else checked remain independent queries, each
// group preceded by a machine-parseable marker comment so "Run Query" can
// split them back apart.
function generateSOQL() {
  if (selectedObjects.size === 0) return "";
  const names = [...selectedObjects];
  if (names.length === 1) return generateSOQLForObject(names[0]);

  const { groups, relations } = groupSelectedByRelationship(names);
  const blocks = [];
  for (const group of groups) {
    if (group.length === 1) {
      blocks.push({ apiName: group[0], soql: generateSOQLForObject(group[0]) });
      continue;
    }

    const groupRelations = relations.filter((r) => group.includes(r.parent) && group.includes(r.child));
    const rootCandidates = group.filter((m) => !groupRelations.some((r) => r.child === m));
    if (rootCandidates.length !== 1) {
      // Ambiguous (e.g. two roots, or a grandchild not directly related to
      // the root) — fall back to independent queries for this group rather
      // than guess at a nesting SOQL can't express in one level anyway.
      for (const m of group) blocks.push({ apiName: m, soql: generateSOQLForObject(m) });
      continue;
    }

    const root = rootCandidates[0];
    const directRelations = groupRelations.filter((r) => r.parent === root);
    const merged = new Set([root, ...directRelations.map((r) => r.child)]);
    blocks.push({ apiName: root, soql: generateMergedSOQL(root, directRelations) });
    for (const m of group) {
      if (!merged.has(m)) blocks.push({ apiName: m, soql: generateSOQLForObject(m) });
    }
  }

  if (blocks.length === 1) return blocks[0].soql;
  return blocks.map((b, idx) => `-- ==== Query ${idx + 1}: ${b.apiName} ====\n${b.soql}`).join("\n\n");
}

function regenerateIfAuto() {
  if (manualEditMode) return;
  setTextarea(generateSOQL());
}

function setTextarea(value) {
  programmaticTextareaUpdate = true;
  $("#soql-text").value = value;
  programmaticTextareaUpdate = false;
  refreshSoqlEditor();
}

// ---------- SOQL editor: line numbers + syntax highlighting (visual only) ----------
// Purely presentational overlay behind the real #soql-text textarea (which stays
// the single source of truth for value/selection/setRangeText). Never touches
// generateSOQL/regenerateIfAuto/runQuery/splitQueryBlocks or any query logic.

const SOQL_KEYWORDS = [
  "SELECT",
  "FROM",
  "WHERE",
  "AND",
  "OR",
  "NOT",
  "IN",
  "LIKE",
  "ORDER BY",
  "GROUP BY",
  "HAVING",
  "LIMIT",
  "OFFSET",
  "ASC",
  "DESC",
  "NULL",
  "TRUE",
  "FALSE",
];

// Universal fields every standard/custom object has, which never show up as a
// fields/*.field-meta.xml file (build-schema.mjs only walks that folder), so
// SCHEMA.objects[x].fields never contains them. Supplemented here rather than
// in build-schema.mjs since this is purely an autocomplete-suggestion concern,
// not a change to the field-tree/query-generation schema data.
const STANDARD_FIELDS = [
  { name: "Id", label: "Record ID" },
  { name: "Name", label: "Name" },
  { name: "CreatedDate", label: "Created Date" },
  { name: "CreatedById", label: "Created By ID" },
  { name: "LastModifiedDate", label: "Last Modified Date" },
  { name: "LastModifiedById", label: "Last Modified By ID" },
  { name: "SystemModstamp", label: "System Modstamp" },
  { name: "LastActivityDate", label: "Last Activity Date" },
  { name: "LastViewedDate", label: "Last Viewed Date" },
  { name: "LastReferencedDate", label: "Last Referenced Date" },
  { name: "OwnerId", label: "Owner ID" },
  { name: "IsDeleted", label: "Deleted" },
];

// Standard fields that exist on only ONE specific object (unlike the
// universal ones above), and are likewise never customized so they have no
// fields/*.field-meta.xml file for build-schema.mjs to pick up — e.g.
// OrderNumber on Order. Missing here means the autocomplete dropdown for a
// relationship path like "order.OrderN" (from OrderItem) silently has
// nothing to suggest, even though the relationship itself resolves fine.
const OBJECT_STANDARD_FIELDS = {
  Order: [{ name: "OrderNumber", label: "Order Number" }],
  Case: [{ name: "CaseNumber", label: "Case Number" }],
  Contract: [{ name: "ContractNumber", label: "Contract Number" }],
  Solution: [{ name: "SolutionNumber", label: "Solution Number" }],
};

// SOQL date literals (values, used on the right-hand side of a date/datetime
// comparison) and date-grouping functions (used in SELECT/GROUP BY). Neither
// is schema-derived — this is a fixed list per the SOQL language spec.
const SOQL_DATE_LITERALS = [
  "YESTERDAY",
  "TODAY",
  "TOMORROW",
  "LAST_WEEK",
  "THIS_WEEK",
  "NEXT_WEEK",
  "LAST_MONTH",
  "THIS_MONTH",
  "NEXT_MONTH",
  "LAST_90_DAYS",
  "NEXT_90_DAYS",
  "LAST_N_DAYS:n",
  "NEXT_N_DAYS:n",
  "N_DAYS_AGO:n",
  "LAST_N_WEEKS:n",
  "NEXT_N_WEEKS:n",
  "LAST_N_MONTHS:n",
  "NEXT_N_MONTHS:n",
  "THIS_QUARTER",
  "LAST_QUARTER",
  "NEXT_QUARTER",
  "LAST_N_QUARTERS:n",
  "NEXT_N_QUARTERS:n",
  "THIS_YEAR",
  "LAST_YEAR",
  "NEXT_YEAR",
  "LAST_N_YEARS:n",
  "NEXT_N_YEARS:n",
  "THIS_FISCAL_QUARTER",
  "LAST_FISCAL_QUARTER",
  "NEXT_FISCAL_QUARTER",
  "LAST_N_FISCAL_QUARTERS:n",
  "NEXT_N_FISCAL_QUARTERS:n",
  "THIS_FISCAL_YEAR",
  "LAST_FISCAL_YEAR",
  "NEXT_FISCAL_YEAR",
  "LAST_N_FISCAL_YEARS:n",
  "NEXT_N_FISCAL_YEARS:n",
];
const SOQL_DATE_FUNCTIONS = [
  "CALENDAR_MONTH()",
  "CALENDAR_QUARTER()",
  "CALENDAR_YEAR()",
  "DAY_IN_MONTH()",
  "DAY_IN_WEEK()",
  "DAY_IN_YEAR()",
  "DAY_ONLY()",
  "FISCAL_MONTH()",
  "FISCAL_QUARTER()",
  "FISCAL_YEAR()",
  "HOUR_IN_DAY()",
  "WEEK_IN_MONTH()",
  "WEEK_IN_YEAR()",
];

function highlightSoql(text) {
  const keywordAlternation = SOQL_KEYWORDS.slice()
    .sort((a, b) => b.length - a.length)
    .map((kw) => kw.replace(/ /g, "\\s+"))
    .join("|");
  // Anchored (^) so it only ever matches at the start of the `rest` slice
  // passed to it below — used as a lookahead-at-cursor test, not a global scan.
  const tokenRe = new RegExp(`^(--[^\n]*|//[^\n]*)|^('(?:[^'\\\\]|\\\\.)*')|^\\b(${keywordAlternation})\\b`, "i");

  let html = "";
  let i = 0;
  // true for each "(" currently open that starts a subquery, i.e. is
  // immediately (modulo whitespace) followed by SELECT — a real nested
  // SOQL query, as opposed to a function call like COUNT(Id) or plain
  // boolean grouping like (A AND B). Nested subqueries (a semi-join inside
  // a semi-join) just push another span, so the tinted background stacks
  // and gets visibly darker with depth for free.
  const subqueryStack = [];

  while (i < text.length) {
    const ch = text[i];

    if (ch === "(") {
      let j = i + 1;
      while (j < text.length && /\s/.test(text[j])) j++;
      const isSubquery = /^select\b/i.test(text.slice(j, j + 7));
      subqueryStack.push(isSubquery);
      if (isSubquery) html += `<span class="tok-subquery">`;
      html += "(";
      i++;
      continue;
    }
    if (ch === ")") {
      html += ")";
      if (subqueryStack.pop()) html += `</span>`;
      i++;
      continue;
    }

    const m = text.slice(i).match(tokenRe);
    if (m) {
      const [full, comment, str, kw] = m;
      if (comment) html += `<span class="tok-comment">${escapeHtml(comment)}</span>`;
      else if (str) html += `<span class="tok-str">${escapeHtml(str)}</span>`;
      else if (kw) html += `<span class="tok-kw">${escapeHtml(full)}</span>`;
      i += full.length;
      continue;
    }

    html += escapeHtml(ch);
    i++;
  }
  return html;
}

function renderSoqlLineNumbers(text) {
  const lineCount = text.split("\n").length;
  let html = "";
  for (let i = 1; i <= lineCount; i++) html += `<div>${i}</div>`;
  $("#soql-line-numbers").innerHTML = html;
}

function refreshSoqlEditor() {
  const text = $("#soql-text").value;
  $("#soql-highlight code").innerHTML = highlightSoql(text);
  renderSoqlLineNumbers(text);
}

$("#soql-text").addEventListener("scroll", () => {
  const ta = $("#soql-text");
  $("#soql-highlight").scrollTop = ta.scrollTop;
  $("#soql-highlight").scrollLeft = ta.scrollLeft;
  $("#soql-line-numbers").scrollTop = ta.scrollTop;
  hideSuggestBox();
});

// ---------- Inline field-name autocomplete (heuristic, not a real parser) ----------
// Mirrors the tone of highlightSoql() above: good enough for a dev tool, not
// a SOQL grammar. Suggests SOQL_KEYWORDS and, once a root object is inferred
// from the nearest preceding "FROM <ApiName>", that object's field names —
// or, one dot deep (e.g. "Account."), the related object's fields.

function getWordRange(text, caretPos) {
  let start = caretPos;
  while (start > 0 && /[A-Za-z0-9_.]/.test(text[start - 1])) start--;
  return { start, end: caretPos };
}

function findRootObjectForCaret(text, caretPos) {
  const fromRe = /\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)/gi;
  const before = text.slice(0, caretPos);
  let match;
  let last = null;
  while ((match = fromRe.exec(before))) {
    if (SCHEMA.objects[match[1]]) last = match[1];
  }
  if (last) return last;
  fromRe.lastIndex = 0;
  while ((match = fromRe.exec(text))) {
    if (SCHEMA.objects[match[1]]) return match[1];
  }
  return activeObject;
}

// Resolves a chain of relationship-name segments (e.g. ["Account"]) starting
// from rootApiName to the object at the end of the chain, using the same
// referenceTo/relNameForDotTraversal data the field-tree lookup expansion
// already uses. One level deep is the common case; supports more for free.
function resolvePathObject(rootApiName, segments) {
  let current = rootApiName;
  for (const seg of segments) {
    const obj = SCHEMA.objects[current];
    if (!obj) return null;
    // SOQL relationship names are case-insensitive ("order." and "Order."
    // both resolve), so match case-insensitively here too — otherwise a
    // lowercase-typed path segment silently fails to resolve and the
    // autocomplete dropdown never appears.
    const segLower = seg.toLowerCase();
    const field = obj.fields.find((f) => f.referenceTo && relNameForDotTraversal(f.name).toLowerCase() === segLower);
    if (!field || !SCHEMA.objects[field.referenceTo]) return null;
    current = field.referenceTo;
  }
  return current;
}

function computeSuggestions() {
  const textarea = $("#soql-text");
  if (textarea.selectionStart !== textarea.selectionEnd) return null;
  const text = textarea.value;
  const caretPos = textarea.selectionStart;
  const { start, end } = getWordRange(text, caretPos);
  const prefix = text.slice(start, end);
  if (!prefix) return null;

  const parts = prefix.split(".");
  const typed = parts[parts.length - 1];
  const pathSegments = parts.slice(0, -1);
  const typedLower = typed.toLowerCase();

  const rootObject = findRootObjectForCaret(text, caretPos);
  if (!rootObject || !SCHEMA.objects[rootObject]) return null;

  let fieldSourceObject = rootObject;
  if (pathSegments.length > 0) {
    fieldSourceObject = resolvePathObject(rootObject, pathSegments);
    if (!fieldSourceObject || !SCHEMA.objects[fieldSourceObject]) return null;
  }

  const items = [];
  if (pathSegments.length === 0) {
    for (const kw of SOQL_KEYWORDS) {
      if (kw.toLowerCase().startsWith(typedLower) && kw.toLowerCase() !== typedLower) {
        items.push({ label: kw, insertText: kw, kind: "keyword" });
      }
    }
    for (const lit of SOQL_DATE_LITERALS) {
      if (lit.toLowerCase().startsWith(typedLower) && lit.toLowerCase() !== typedLower) {
        items.push({ label: lit, insertText: lit, kind: "date literal" });
      }
    }
    for (const fn of SOQL_DATE_FUNCTIONS) {
      if (fn.toLowerCase().startsWith(typedLower) && fn.toLowerCase() !== typedLower) {
        items.push({ label: fn, insertText: fn, kind: "date function" });
      }
    }
  }
  const schemaFieldNames = new Set(SCHEMA.objects[fieldSourceObject].fields.map((f) => f.name.toLowerCase()));
  const allFields = SCHEMA.objects[fieldSourceObject].fields.concat(
    STANDARD_FIELDS.filter((f) => !schemaFieldNames.has(f.name.toLowerCase())),
    (OBJECT_STANDARD_FIELDS[fieldSourceObject] || []).filter((f) => !schemaFieldNames.has(f.name.toLowerCase())),
  );
  for (const field of allFields) {
    if (!field.name.toLowerCase().includes(typedLower) && !field.label.toLowerCase().includes(typedLower)) continue;
    const insertText = pathSegments.length ? [...pathSegments, field.name].join(".") : field.name;
    items.push({
      label: `${field.name} — ${field.label}`,
      insertText,
      kind: field.referenceTo ? "relationship" : "field",
    });
  }

  if (items.length === 0) return null;
  items.sort((a, b) => a.insertText.localeCompare(b.insertText));
  return { items: items.slice(0, 30), wordStart: start, wordEnd: end, activeIndex: 0 };
}

// Standard mirror-div technique: clone the textarea's text-affecting styles
// into an offscreen div, insert a marker span at `position`, and read its
// offset — self-contained, no dependency.
function getCaretPixelPosition(textarea, position) {
  const mirror = document.createElement("div");
  const style = getComputedStyle(textarea);
  const props = [
    "boxSizing",
    "width",
    "fontFamily",
    "fontSize",
    "fontWeight",
    "fontStyle",
    "letterSpacing",
    "lineHeight",
    "textTransform",
    "wordSpacing",
    "textIndent",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "borderTopWidth",
    "borderRightWidth",
    "borderBottomWidth",
    "borderLeftWidth",
  ];
  for (const prop of props) mirror.style[prop] = style[prop];
  mirror.style.position = "absolute";
  mirror.style.visibility = "hidden";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.wordBreak = "break-word";
  mirror.style.top = "0";
  mirror.style.left = "-9999px";
  mirror.style.height = "auto";
  document.body.appendChild(mirror);

  mirror.textContent = textarea.value.slice(0, position);
  const marker = document.createElement("span");
  marker.textContent = "​";
  mirror.appendChild(marker);

  const top = marker.offsetTop - textarea.scrollTop;
  const left = marker.offsetLeft - textarea.scrollLeft;
  const lineHeight = parseInt(style.lineHeight, 10) || 20;
  document.body.removeChild(mirror);

  // Anchor to viewport coords (textarea's own rect), not to .soql-editor-wrap,
  // since that wrapper has overflow:hidden and would clip a dropdown that
  // extends past its bottom edge. #soql-suggest-box is position:fixed for
  // exactly this reason.
  const rect = textarea.getBoundingClientRect();
  return { top: rect.top + top, left: rect.left + left, lineHeight };
}

function hideSuggestBox() {
  suggestState = null;
  $("#soql-suggest-box").classList.add("hidden");
}

function renderSuggestBox() {
  const box = $("#soql-suggest-box");
  if (!suggestState) {
    box.classList.add("hidden");
    return;
  }
  box.innerHTML = suggestState.items
    .map(
      (item, i) =>
        `<div class="soql-suggest-item${i === suggestState.activeIndex ? " active" : ""}" data-index="${i}">` +
        `<span class="soql-suggest-label">${escapeHtml(item.label)}</span>` +
        `<span class="soql-suggest-kind">${escapeHtml(item.kind)}</span></div>`,
    )
    .join("");

  const textarea = $("#soql-text");
  const { top, left, lineHeight } = getCaretPixelPosition(textarea, suggestState.wordStart);
  box.style.top = `${top + lineHeight}px`;
  box.style.left = `${left}px`;
  box.classList.remove("hidden");
}

function acceptSuggestion(index) {
  if (!suggestState) return;
  const item = suggestState.items[index];
  if (!item) return;
  const textarea = $("#soql-text");
  const { wordStart, wordEnd } = suggestState;
  suppressNextAutoSuggest = true;
  textarea.setRangeText(item.insertText, wordStart, wordEnd, "end");
  textarea.focus();
  hideSuggestBox();
  refreshSoqlEditor();
}

$("#soql-suggest-box").addEventListener("mousedown", (e) => {
  const row = e.target.closest(".soql-suggest-item");
  if (!row) return;
  e.preventDefault();
  acceptSuggestion(Number(row.dataset.index));
});

$("#soql-text").addEventListener("keydown", (e) => {
  if (!suggestState) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    suggestState.activeIndex = (suggestState.activeIndex + 1) % suggestState.items.length;
    renderSuggestBox();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    suggestState.activeIndex = (suggestState.activeIndex - 1 + suggestState.items.length) % suggestState.items.length;
    renderSuggestBox();
  } else if (e.key === "Enter" || e.key === "Tab") {
    e.preventDefault();
    acceptSuggestion(suggestState.activeIndex);
  } else if (e.key === "Escape") {
    e.preventDefault();
    hideSuggestBox();
  }
});

$("#regenerate-btn").addEventListener("click", () => {
  manualEditMode = false;
  setTextarea(generateSOQL());
  setStatus("Regenerated from current selections.", "ok");
});

$("#soql-text").addEventListener("input", () => {
  refreshSoqlEditor();
  if (programmaticTextareaUpdate) return;
  manualEditMode = true;
  if (suppressNextAutoSuggest) {
    suppressNextAutoSuggest = false;
    hideSuggestBox();
    return;
  }
  suggestState = computeSuggestions();
  renderSuggestBox();
});

$("#soql-text").addEventListener("blur", () => {
  // Deferred so a mousedown on a suggestion row (which fires before blur) can
  // still register its click before the box disappears.
  setTimeout(hideSuggestBox, 150);
});

$("#object-search").addEventListener("input", (e) => renderObjectList(e.target.value));

$("#field-search").addEventListener("input", (e) => {
  fieldSearchFilter = e.target.value;
  renderFieldTree();
});

// ---------- Select all / select none (Fields panel) ----------
// Applies only to the active object's own fields (not fields reached by
// expanding a lookup into a different object's field tree, and not related-
// list/subquery fields, which have their own per-relationship checkboxes).

$("#select-all-fields-btn").addEventListener("click", () => {
  if (!activeObject) return;
  const state = getObjectState(activeObject);
  for (const field of SCHEMA.objects[activeObject].fields) {
    state.selectedFields.add(field.name);
  }
  renderFieldTree();
  regenerateIfAuto();
});

$("#select-none-fields-btn").addEventListener("click", () => {
  if (!activeObject) return;
  const state = getObjectState(activeObject);
  for (const field of SCHEMA.objects[activeObject].fields) {
    state.selectedFields.delete(field.name);
  }
  renderFieldTree();
  regenerateIfAuto();
});

// ---------- Semi-join template ----------

function populateSemiJoinSelects() {
  const names = Object.keys(SCHEMA.objects).sort();
  for (const sel of [$("#semi-join-a"), $("#semi-join-b")]) {
    sel.innerHTML = names.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join("");
  }
}

$("#insert-semi-join-btn").addEventListener("click", () => {
  const objA = $("#semi-join-a").value;
  const objB = $("#semi-join-b").value;
  const template =
    `-- Semi-join: link two objects that share a parent but have no direct relationship.\n` +
    `-- Fill in the two lookup fields that both point at the shared parent object.\n` +
    `SELECT Id\n` +
    `FROM ${objA}\n` +
    `WHERE SharedParentLookup__c IN (\n` +
    `  SELECT SharedParentLookup__c\n` +
    `  FROM ${objB}\n` +
    `  WHERE Id != null\n` +
    `)`;
  manualEditMode = true;
  setTextarea(template);
  setStatus(`Inserted a semi-join template: ${objA} (main) matched against ${objB} (subquery) — edit the lookup field names.`, "ok");
});

// ---------- Connected mode: health, orgs ----------

function apiHeaders(extra) {
  return Object.assign({ "X-Auth-Token": AUTH_TOKEN }, extra || {});
}

async function detectConnection() {
  if (IS_FILE_PROTOCOL) {
    setMode(false);
    return;
  }
  try {
    const res = await fetch("/api/health", { headers: apiHeaders() });
    if (!res.ok) throw new Error("health check failed");
    setMode(true);
    await loadOrgs();
  } catch (e) {
    setMode(false);
  }
}

function setMode(isConnected) {
  connected = isConnected;
  const badge = $("#mode-badge");
  if (isConnected) {
    badge.textContent = "Connected to sf CLI";
    badge.className = "connected";
  } else {
    badge.textContent = "Offline (file://) — build & copy SOQL";
    badge.className = "offline";
  }
  $("#connected-controls").classList.toggle("hidden", !isConnected);
  $("#csv-paste-section").classList.toggle("hidden", isConnected);
  $("#run-query-btn").classList.toggle("hidden", !isConnected);
  $("#explain-btn").classList.toggle("hidden", !isConnected);
  $("#query-all-wrap").classList.toggle("hidden", !isConnected);
  $("#use-tooling-wrap").classList.toggle("hidden", !isConnected);
  $("#query-history-select").classList.toggle("hidden", !isConnected);
  $("#utilities-heading").classList.toggle("hidden", !isConnected);
  $("#rest-explorer-panel").classList.toggle("hidden", !isConnected);
  $("#apex-execute-panel").classList.toggle("hidden", !isConnected);
  if (!isConnected) {
    $("#query-plan-section").classList.add("hidden");
    $("#query-plan-section").innerHTML = "";
    $("#rest-response-section").innerHTML = "";
    $("#apex-result-section").innerHTML = "";
    $("#apex-json-editor-btn").disabled = true;
    lastApexResult = null;
  }
  if (isConnected) renderQueryHistorySelect();
}

async function loadOrgs() {
  try {
    const res = await fetch("/api/orgs", { headers: apiHeaders() });
    const data = await res.json();
    const sel = $("#org-select");
    sel.innerHTML = "";
    for (const org of data.orgs || []) {
      const opt = document.createElement("option");
      opt.value = org.username;
      opt.textContent = org.alias ? `${org.alias} (${org.username})` : org.username;
      sel.appendChild(opt);
    }
    currentOrg = sel.value || null;
    sel.addEventListener("change", () => {
      currentOrg = sel.value;
    });
  } catch (e) {
    setStatus(`Failed to load orgs: ${e.message}`, "error");
  }
}

// ---------- Run query (connected mode) ----------

$("#run-query-btn").addEventListener("click", runQuery);

// Unlike SOQL embedded in Apex (where the compiler strips comments before
// the query ever reaches the engine), the raw Query API that `sf data
// query` hits does not support comments at all — neither "--" nor "//"
// lines are valid there, and sending one produces a real
// MALFORMED_QUERY: unexpected token error. generateSOQL() adds comment
// lines purely for the textarea's human-readable annotations (merge notes,
// "-- ==== Query N ====" markers), so every comment-only line must be
// stripped before any block's SOQL is handed to the CLI.
function stripSoqlComments(text) {
  return text
    .split("\n")
    .filter((line) => !/^\s*(--|\/\/)/.test(line))
    .join("\n")
    .trim();
}

// Splits the textarea on "-- ==== Query N: ApiName ====" marker comments
// (added by generateSOQL() when more than one object is checked) so each
// stacked query can be run independently against the sf CLI, which only
// ever accepts one SOQL statement per call. Falls back to treating the
// whole textarea as a single query when no markers are present — covers
// the single-object case and fully hand-written/edited queries.
function splitQueryBlocks(text) {
  const markerRe = /^--\s*====\s*Query\s*\d+:\s*(.+?)\s*====\s*$/gm;
  const matches = [...text.matchAll(markerRe)];
  if (matches.length === 0) {
    return [{ apiName: activeObject, soql: stripSoqlComments(text) }];
  }
  const blocks = [];
  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].index + matches[i][0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index : text.length;
    const apiName = matches[i][1].trim();
    const soql = stripSoqlComments(text.slice(start, end));
    if (soql) blocks.push({ apiName, soql });
  }
  return blocks;
}

// ---------- Org instance URL (for "Open in Salesforce" result links) ----------

const orgInfoCache = new Map(); // org username -> Promise<string|null> (instanceUrl)

function getInstanceUrl(org) {
  if (!connected || !org) return Promise.resolve(null);
  if (!orgInfoCache.has(org)) {
    orgInfoCache.set(
      org,
      fetch(`/api/org-info?org=${encodeURIComponent(org)}`, { headers: apiHeaders() })
        .then((r) => r.json())
        .then((d) => d.instanceUrl || null)
        .catch(() => null),
    );
  }
  return orgInfoCache.get(org);
}

async function runQuery() {
  const raw = $("#soql-text").value.trim();
  if (!raw) {
    setStatus("Nothing to run — build or type a query first.", "error");
    return;
  }
  if (!currentOrg) {
    setStatus("Select a target org first.", "error");
    return;
  }

  const queryAll = $("#query-all-checkbox").checked;
  const useTooling = $("#use-tooling-checkbox").checked;
  const blocks = splitQueryBlocks(raw);
  const section = $("#results-section");
  section.innerHTML = "";
  setStatus(`Running ${blocks.length} quer${blocks.length > 1 ? "ies" : "y"}…`, "");

  const instanceUrl = await getInstanceUrl(currentOrg);

  let totalRecords = 0;
  let hadError = false;
  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i];
    const wrap = document.createElement("div");
    wrap.className = "query-result-block";
    section.appendChild(wrap);
    try {
      const startedAt = performance.now();
      const res = await fetch("/api/query", {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ soql: block.soql, org: currentOrg, queryAll, useTooling }),
      });
      const data = await res.json();
      const elapsedMs = performance.now() - startedAt;
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      const records = data.records || [];
      totalRecords += records.length;
      renderResultsTableInto(wrap, records, block.apiName, {
        heading: blocks.length > 1 ? block.apiName || `Query ${i + 1}` : null,
        instanceUrl,
        elapsedMs,
      });
    } catch (e) {
      hadError = true;
      const err = document.createElement("p");
      err.className = "row-error";
      err.textContent = `Query failed: ${e.message}`;
      wrap.appendChild(err);
    }
  }

  if (hadError) {
    setStatus(`Completed with errors — ${totalRecords} record(s) returned overall.`, "error");
  } else {
    setStatus(`Returned ${totalRecords} record(s) across ${blocks.length} quer${blocks.length > 1 ? "ies" : "y"}.`, "ok");
  }

  saveQueryHistoryEntry(raw, currentOrg);
}

// ---------- Query plan / Explain (connected mode) ----------
// Hits Salesforce's Query Plan REST resource via the beta `sf api request
// rest` command. That command is beta and may error or be unavailable on a
// given sf CLI version — per explicit decision, this shows a plain inline
// error via setStatus() rather than probing capability up front.

$("#explain-btn").addEventListener("click", explainQuery);

async function explainQuery() {
  const raw = $("#soql-text").value.trim();
  if (!raw) {
    setStatus("Nothing to explain — build or type a query first.", "error");
    return;
  }
  if (!currentOrg) {
    setStatus("Select a target org first.", "error");
    return;
  }

  const blocks = splitQueryBlocks(raw);
  const soql = blocks[0].soql;
  const planSection = $("#query-plan-section");
  planSection.classList.remove("hidden");
  planSection.innerHTML = "";
  setStatus(
    blocks.length > 1
      ? "Explaining the first query only (Query Plan runs one statement at a time)…"
      : "Fetching query plan…",
    "",
  );

  try {
    const res = await fetch(`/api/explain?soql=${encodeURIComponent(soql)}&org=${encodeURIComponent(currentOrg)}`, {
      headers: apiHeaders(),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    renderQueryPlan(planSection, data.plan);
    setStatus("Query plan retrieved.", "ok");
  } catch (e) {
    planSection.innerHTML = `<p class="row-error">Explain failed: ${escapeHtml(e.message)}</p>`;
    setStatus(`Explain failed: ${e.message}`, "error");
  }
}

function renderQueryPlan(container, plan) {
  const plans = (plan && plan.plans) || [];
  if (plans.length === 0) {
    container.innerHTML = `<p class="muted">No plan entries returned.</p>`;
    return;
  }
  let html = `<table class="query-plan-table"><thead><tr>
    <th>Cardinality</th><th>Leading Operation</th><th>Relative Cost</th><th>SObject Cardinality</th><th>Notes</th>
  </tr></thead><tbody>`;
  for (const entry of plans) {
    const notes = (entry.notes || []).map((n) => n.description || n.tableEnumOrId || "").filter(Boolean).join("; ");
    html += `<tr>
      <td>${escapeHtml(String(entry.cardinality ?? ""))}</td>
      <td>${escapeHtml(entry.leadingOperationType || "")}</td>
      <td>${escapeHtml(String(entry.relativeCost ?? ""))}</td>
      <td>${escapeHtml(String(entry.sobjectCardinality ?? ""))}</td>
      <td>${escapeHtml(notes)}</td>
    </tr>`;
  }
  html += `</tbody></table>`;
  container.innerHTML = html;
}

// ---------- Query history (localStorage, connected mode only) ----------

const QUERY_HISTORY_KEY = "soqlBuilderQueryHistory";
const QUERY_HISTORY_MAX = 20;

function loadQueryHistory() {
  try {
    const raw = localStorage.getItem(QUERY_HISTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return [];
  }
}

function saveQueryHistoryEntry(soql, org) {
  if (!connected) return;
  const history = loadQueryHistory();
  // Same query may already exist anywhere in history, not just at the front
  // (e.g. run A, run B, run A again) — drop the old entry so it moves to the
  // top instead of creating a duplicate further down the list.
  const dupIndex = history.findIndex((entry) => entry.soql === soql && entry.org === org);
  if (dupIndex !== -1) history.splice(dupIndex, 1);
  history.unshift({ soql, org, ranAt: new Date().toISOString() });
  history.length = Math.min(history.length, QUERY_HISTORY_MAX);
  try {
    localStorage.setItem(QUERY_HISTORY_KEY, JSON.stringify(history));
  } catch (e) {
    // Storage full/unavailable — history is a convenience, not critical.
  }
  renderQueryHistorySelect();
}

function renderQueryHistorySelect() {
  const sel = $("#query-history-select");
  const history = loadQueryHistory();
  sel.innerHTML = `<option value="">History…</option>`;
  history.forEach((entry, idx) => {
    const opt = document.createElement("option");
    opt.value = String(idx);
    const when = new Date(entry.ranAt).toLocaleString();
    const preview = entry.soql.replace(/\s+/g, " ").trim().slice(0, 60);
    opt.textContent = `${when} — ${preview}${entry.soql.length > 60 ? "…" : ""}`;
    sel.appendChild(opt);
  });
}

$("#query-history-select").addEventListener("change", (e) => {
  const idx = Number(e.target.value);
  if (Number.isNaN(idx)) return;
  const history = loadQueryHistory();
  const entry = history[idx];
  e.target.value = "";
  if (!entry) return;
  manualEditMode = true;
  $("#soql-text").value = entry.soql;
  refreshSoqlEditor();
  if (entry.org) {
    const orgSelect = $("#org-select");
    if ([...orgSelect.options].some((o) => o.value === entry.org)) {
      orgSelect.value = entry.org;
      currentOrg = entry.org;
    }
  }
  setStatus("Loaded query from history.", "");
});

// ---------- Results table (shared by connected-mode run + offline CSV paste) ----------

// Renders a subquery's child records as readable "Field: value" lines
// instead of dumping the raw nested JSON (which buries the actual data under
// {"attributes":{"type":...,"url":...}} noise on every child row).
function formatSubqueryRecords(records) {
  if (!Array.isArray(records) || records.length === 0) return "(0 records)";
  return records
    .map((rec, i) => {
      const pairs = Object.keys(rec)
        .filter((k) => k !== "attributes")
        .map((k) => `${k}: ${rec[k] === null || rec[k] === undefined ? "" : rec[k]}`)
        .join(", ");
      return `[${i + 1}] ${pairs}`;
    })
    .join("\n");
}

function flattenRecord(record, dotPaths) {
  const flat = { Id: record.Id, __sobjectType: record.attributes && record.attributes.type };
  for (const path of dotPaths) {
    if (path === "Id") continue;
    const parts = path.split(".");
    let cur = record;
    for (const part of parts) {
      if (cur == null) break;
      cur = cur[part];
    }
    flat[path] = cur == null ? "" : cur;
  }
  for (const key of Object.keys(record)) {
    if (key === "attributes" || key === "Id") continue;
    const val = record[key];
    if (val && typeof val === "object" && Array.isArray(val.records)) {
      flat[`${key} (subquery)`] = formatSubqueryRecords(val.records);
    }
  }
  return flat;
}

// Picks the dot-paths (columns) for a result block: prefers the checked
// fields recorded for that object while building the query, and falls back
// to whatever keys are actually present on the first record (covers a
// fully hand-written/edited query for an object we have no builder state for).
function inferDotPaths(apiName, records) {
  const state = apiName ? objectStates.get(apiName) : null;
  if (state && state.selectedFields.size) {
    return [...state.selectedFields].filter((p) => p !== "Id");
  }
  if (records.length > 0) {
    return Object.keys(records[0]).filter((k) => k !== "attributes" && k !== "Id");
  }
  return [];
}

// ---------- Export Result toolbar: clipboard copy helpers (visual only, reuses existing data) ----------

async function copyToClipboard(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text);
    setStatus(successMessage, "ok");
  } catch (e) {
    setStatus(`Copy failed: ${e.message}`, "error");
  }
}

function neutralizeCsvFormula(s) {
  // OWASP CSV injection mitigation: a cell whose first character is one that
  // spreadsheet apps (Excel, Sheets) treat as a formula trigger gets prefixed
  // with a single quote, forcing it to be read back as literal text.
  return /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
}

function rowsToDelimited(flatRows, columns, delimiter) {
  const escapeField = (value) => {
    let s = value === undefined || value === null ? "" : String(value);
    s = neutralizeCsvFormula(s);
    const needsQuote = delimiter === "," ? /[",\n]/.test(s) : /["\t\n]/.test(s);
    if (needsQuote) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [columns.map(escapeField).join(delimiter)];
  flatRows.forEach((row) => {
    lines.push(columns.map((c) => escapeField(row[c])).join(delimiter));
  });
  return lines.join("\r\n");
}

function copyRowsAsExcel(flatRows, columns) {
  return copyToClipboard(rowsToDelimited(flatRows, columns, "\t"), "Copied as Excel-compatible text.");
}

function copyRowsAsCsvText(flatRows, columns) {
  return copyToClipboard(rowsToDelimited(flatRows, columns, ","), "Copied as CSV.");
}

function copyRecordsAsJson(records) {
  return copyToClipboard(JSON.stringify(records, null, 2), "Copied as JSON.");
}

function downloadRowsAsCsv(flatRows, columns, apiName) {
  const escapeCsvField = (value) => {
    let s = value === undefined || value === null ? "" : String(value);
    s = neutralizeCsvFormula(s);
    if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [columns.map(escapeCsvField).join(",")];
  flatRows.forEach((row) => {
    lines.push(columns.map((c) => escapeCsvField(row[c])).join(","));
  });
  const csv = lines.join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${apiName || "results"}-${Date.now()}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderResultsTableInto(container, records, apiName, options = {}) {
  const { heading, instanceUrl, elapsedMs } = options;

  if (records.length === 0) {
    if (heading) {
      const h3 = document.createElement("h3");
      h3.textContent = heading;
      container.appendChild(h3);
    }
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "No records returned.";
    container.appendChild(p);
    return;
  }

  const dotPaths = inferDotPaths(apiName, records);
  const flatRows = records.map((r) => flattenRecord(r, dotPaths));
  const columns = ["Id", ...dotPaths];
  const subqueryCols = Object.keys(flatRows[0]).filter((k) => k.endsWith(" (subquery)"));
  columns.push(...subqueryCols);

  const h3 = document.createElement("h3");
  const headingText = document.createElement("span");
  headingText.textContent = heading || "Results";
  h3.appendChild(headingText);

  const meta = document.createElement("span");
  meta.className = "result-meta";
  meta.textContent =
    `${flatRows.length} record${flatRows.length === 1 ? "" : "s"}` +
    (typeof elapsedMs === "number" ? ` · ${(elapsedMs / 1000).toFixed(2)}s` : "");
  h3.appendChild(meta);

  const toolbar = document.createElement("span");
  toolbar.className = "export-toolbar";

  const copyExcelBtn = document.createElement("button");
  copyExcelBtn.type = "button";
  copyExcelBtn.className = "export-btn";
  copyExcelBtn.textContent = "Copy Excel";
  copyExcelBtn.addEventListener("click", () => copyRowsAsExcel(flatRows, columns));
  toolbar.appendChild(copyExcelBtn);

  const copyCsvBtn = document.createElement("button");
  copyCsvBtn.type = "button";
  copyCsvBtn.className = "export-btn";
  copyCsvBtn.textContent = "Copy CSV";
  copyCsvBtn.addEventListener("click", () => copyRowsAsCsvText(flatRows, columns));
  toolbar.appendChild(copyCsvBtn);

  const copyJsonBtn = document.createElement("button");
  copyJsonBtn.type = "button";
  copyJsonBtn.className = "export-btn";
  copyJsonBtn.textContent = "Copy JSON";
  copyJsonBtn.addEventListener("click", () => copyRecordsAsJson(records));
  toolbar.appendChild(copyJsonBtn);

  const downloadBtn = document.createElement("button");
  downloadBtn.type = "button";
  downloadBtn.className = "export-btn download-csv-btn";
  downloadBtn.title = "Download as CSV";
  downloadBtn.textContent = "⬇";
  downloadBtn.addEventListener("click", () => downloadRowsAsCsv(flatRows, columns, apiName));
  toolbar.appendChild(downloadBtn);

  // Selection is purely local UI state for filtering the export helpers
  // above — it never touches the save/dirty path in buildResultRow().
  const selectedRows = new Set();

  const selectedLabel = document.createElement("span");
  selectedLabel.className = "selected-count muted";
  selectedLabel.textContent = "0 selected";
  toolbar.appendChild(selectedLabel);

  const copySelectedExcelBtn = document.createElement("button");
  copySelectedExcelBtn.type = "button";
  copySelectedExcelBtn.className = "export-btn";
  copySelectedExcelBtn.textContent = "Copy Selected Excel";
  copySelectedExcelBtn.disabled = true;
  copySelectedExcelBtn.addEventListener("click", () => {
    const idxs = [...selectedRows].sort((a, b) => a - b);
    copyRowsAsExcel(idxs.map((i) => flatRows[i]), columns);
  });
  toolbar.appendChild(copySelectedExcelBtn);

  const copySelectedCsvBtn = document.createElement("button");
  copySelectedCsvBtn.type = "button";
  copySelectedCsvBtn.className = "export-btn";
  copySelectedCsvBtn.textContent = "Copy Selected CSV";
  copySelectedCsvBtn.disabled = true;
  copySelectedCsvBtn.addEventListener("click", () => {
    const idxs = [...selectedRows].sort((a, b) => a - b);
    copyRowsAsCsvText(idxs.map((i) => flatRows[i]), columns);
  });
  toolbar.appendChild(copySelectedCsvBtn);

  const copySelectedJsonBtn = document.createElement("button");
  copySelectedJsonBtn.type = "button";
  copySelectedJsonBtn.className = "export-btn";
  copySelectedJsonBtn.textContent = "Copy Selected JSON";
  copySelectedJsonBtn.disabled = true;
  copySelectedJsonBtn.addEventListener("click", () => {
    const idxs = [...selectedRows].sort((a, b) => a - b);
    copyRecordsAsJson(idxs.map((i) => records[i]));
  });
  toolbar.appendChild(copySelectedJsonBtn);

  h3.appendChild(toolbar);
  container.appendChild(h3);

  const table = document.createElement("table");
  table.className = "results-table";
  const thead = document.createElement("thead");
  thead.innerHTML = `<tr><th class="select-col"><input type="checkbox" class="select-all-checkbox" title="Select all" /></th>${columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}${instanceUrl ? "<th></th>" : ""}<th>Save</th></tr>`;
  table.appendChild(thead);
  addColumnResizeHandles(thead);

  const selectAllCheckbox = thead.querySelector(".select-all-checkbox");
  const rowCheckboxes = [];

  function updateSelectionUI() {
    const n = selectedRows.size;
    selectedLabel.textContent = `${n} selected`;
    const noneSelected = n === 0;
    copySelectedExcelBtn.disabled = noneSelected;
    copySelectedCsvBtn.disabled = noneSelected;
    copySelectedJsonBtn.disabled = noneSelected;
    selectAllCheckbox.checked = n > 0 && n === flatRows.length;
  }

  selectAllCheckbox.addEventListener("change", () => {
    rowCheckboxes.forEach((cb, i) => {
      cb.checked = selectAllCheckbox.checked;
      if (selectAllCheckbox.checked) selectedRows.add(i);
      else selectedRows.delete(i);
    });
    updateSelectionUI();
  });

  const tbody = document.createElement("tbody");
  flatRows.forEach((row, i) => {
    const tr = buildResultRow(row, columns, connected, instanceUrl, i, selectedRows, updateSelectionUI);
    const cb = tr.querySelector(".row-select-checkbox");
    if (cb) rowCheckboxes.push(cb);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);
}

function addColumnResizeHandles(thead) {
  thead.querySelectorAll("th").forEach((th) => {
    const handle = document.createElement("span");
    handle.className = "col-resize-handle";
    th.appendChild(handle);
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const startX = e.pageX;
      const startWidth = th.offsetWidth;
      const onMouseMove = (moveEvent) => {
        th.style.width = `${Math.max(30, startWidth + (moveEvent.pageX - startX))}px`;
      };
      const onMouseUp = () => {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      };
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });
  });
}

function buildResultRow(row, columns, editable, instanceUrl, rowIndex, selectedRows, onSelectionChange) {
  const tr = document.createElement("tr");
  const dirty = {}; // field -> { original, current }

  // Only the connected results table passes selectedRows — the offline
  // CSV-paste preview table calls buildResultRow() without it, so this
  // stays out of that table's column layout entirely.
  if (selectedRows) {
    const selectTd = document.createElement("td");
    selectTd.className = "select-col";
    const selectCheckbox = document.createElement("input");
    selectCheckbox.type = "checkbox";
    selectCheckbox.className = "row-select-checkbox";
    selectCheckbox.checked = selectedRows.has(rowIndex);
    selectCheckbox.addEventListener("change", () => {
      if (selectCheckbox.checked) selectedRows.add(rowIndex);
      else selectedRows.delete(rowIndex);
      if (onSelectionChange) onSelectionChange();
    });
    selectTd.appendChild(selectCheckbox);
    tr.appendChild(selectTd);
  }

  for (const col of columns) {
    const td = document.createElement("td");
    const isSubquery = col.endsWith(" (subquery)");
    const isEditable = editable && col !== "Id" && !col.includes(".") && !isSubquery;
    if (isSubquery) td.classList.add("subquery-cell");
    td.textContent = row[col] === undefined ? "" : String(row[col]);
    if (isEditable) {
      td.contentEditable = "true";
      td.addEventListener("input", () => {
        const original = row[col] === undefined ? "" : String(row[col]);
        const current = td.textContent;
        if (current !== original) {
          dirty[col] = { original, current };
          td.classList.add("dirty");
        } else {
          delete dirty[col];
          td.classList.remove("dirty");
        }
        updateRowActionCell();
      });
    }
    tr.appendChild(td);
  }

  if (instanceUrl) {
    const linkTd = document.createElement("td");
    if (row.Id) {
      const link = document.createElement("a");
      link.className = "open-in-sf-link";
      link.href = `${instanceUrl}/${row.Id}`;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open ↗";
      linkTd.appendChild(link);
    }
    tr.appendChild(linkTd);
  }

  const actionsTd = document.createElement("td");
  actionsTd.className = "row-actions";
  tr.appendChild(actionsTd);

  function buildValuesString() {
    return Object.entries(dirty)
      .map(([field, { current }]) => `${field}='${String(current).replace(/'/g, "\\'")}'`)
      .join(" ");
  }

  function updateRowActionCell() {
    actionsTd.innerHTML = "";
    const errorHolder = actionsTd.__errorHolder;
    const changedFields = Object.keys(dirty);
    if (changedFields.length === 0) {
      return;
    }
    if (!editable) {
      const note = document.createElement("div");
      note.className = "muted";
      note.textContent = "Offline — connect via npm run soql-builder to save.";
      actionsTd.appendChild(note);
      return;
    }
    const cmdPreview = document.createElement("code");
    cmdPreview.className = "cmd-preview";
    cmdPreview.textContent = `sf data update record --sobject ${row.__sobjectType} --record-id ${row.Id} --values "${buildValuesString()}" --target-org ${currentOrg} --json`;
    actionsTd.appendChild(cmdPreview);

    const saveBtn = document.createElement("button");
    saveBtn.className = "danger";
    saveBtn.textContent = "Save this row";
    saveBtn.addEventListener("click", async () => {
      const summary = changedFields.map((f) => `  ${f}: "${dirty[f].original}" → "${dirty[f].current}"`).join("\n");
      const ok = window.confirm(
        `Update ${row.__sobjectType} record ${row.Id} on org ${currentOrg}?\n\n${summary}\n\nThis writes to Salesforce immediately.`
      );
      if (!ok) return;
      saveBtn.disabled = true;
      saveBtn.textContent = "Saving…";
      try {
        const res = await fetch("/api/update-record", {
          method: "POST",
          headers: apiHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            sobject: row.__sobjectType,
            recordId: row.Id,
            values: buildValuesString(),
            org: currentOrg,
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        for (const field of changedFields) {
          row[field] = dirty[field].current;
          delete dirty[field];
        }
        [...tr.children].forEach((td) => td.classList.remove("dirty"));
        updateRowActionCell();
        setStatus(`Saved ${row.__sobjectType} ${row.Id}.`, "ok");
      } catch (e) {
        const err = document.createElement("div");
        err.className = "row-error";
        err.textContent = `Save failed: ${e.message}`;
        actionsTd.appendChild(err);
        saveBtn.disabled = false;
        saveBtn.textContent = "Save this row";
      }
    });
    actionsTd.appendChild(saveBtn);
  }

  return tr;
}

// ---------- Offline CSV-paste fallback ----------

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((r) => r.length > 1 || r[0] !== "");
}

$("#load-csv-btn").addEventListener("click", () => {
  const text = $("#csv-paste").value;
  const rows = parseCsv(text);
  if (rows.length < 2) {
    setStatus("Paste CSV with a header row plus at least one data row.", "error");
    return;
  }
  const [header, ...dataRows] = rows;
  const section = $("#results-section");
  section.innerHTML = "";
  const table = document.createElement("table");
  table.className = "results-table";
  const thead = document.createElement("thead");
  thead.innerHTML = `<tr>${header.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}<th>Save</th></tr>`;
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const dataRow of dataRows) {
    const flat = {};
    header.forEach((col, i) => (flat[col] = dataRow[i] ?? ""));
    flat.__sobjectType = activeObject;
    tbody.appendChild(buildResultRow(flat, header, false));
  }
  table.appendChild(tbody);
  section.appendChild(table);
  setStatus(`Loaded ${dataRows.length} pasted row(s) (read-only — offline mode).`, "ok");
});

// ---------- REST Explorer (connected mode) ----------

$("#rest-explorer-toggle").addEventListener("click", () => {
  const body = $("#rest-explorer-body");
  const icon = $("#rest-explorer-toggle-icon");
  const collapsed = body.classList.toggle("hidden");
  icon.textContent = collapsed ? "▶" : "▼";
});

const REST_SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

function setRestStatus(text, kind) {
  const el = $("#rest-status-line");
  el.textContent = text;
  el.className = kind || "";
}

function parseRestHeaders(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

$("#rest-method-select").addEventListener("change", () => {
  const method = $("#rest-method-select").value;
  $("#rest-warning-banner").classList.toggle("hidden", REST_SAFE_METHODS.has(method));
});

function renderRestResponse(raw) {
  const section = $("#rest-response-section");
  let pretty = raw;
  try {
    pretty = JSON.stringify(JSON.parse(raw), null, 2);
  } catch (e) {
    // Not JSON — render as-is.
  }
  section.innerHTML = `<pre class="rest-response-pre">${escapeHtml(pretty)}</pre>`;
}

async function sendRestRequest() {
  const method = $("#rest-method-select").value;
  const path = $("#rest-path-input").value.trim();
  const headers = parseRestHeaders($("#rest-headers-input").value);
  const body = $("#rest-body-input").value;

  if (!path) {
    setRestStatus("Enter a path (e.g. /services/data/v67.0/limits).", "error");
    return;
  }
  if (!currentOrg) {
    setRestStatus("Select an org first.", "error");
    return;
  }

  if (!REST_SAFE_METHODS.has(method)) {
    const bodyPreview = body ? (body.length > 200 ? body.slice(0, 200) + "…" : body) : "(empty)";
    const confirmed = window.confirm(
      `Send ${method} ${path} on org ${currentOrg}?\n\nBody:\n${bodyPreview}\n\nThis may modify data in Salesforce immediately.`,
    );
    if (!confirmed) {
      setRestStatus("Request cancelled.", "");
      return;
    }
  }

  setRestStatus(`Sending ${method} ${path}…`, "");
  try {
    const res = await fetch("/api/rest-request", {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ org: currentOrg, method, path, headers, body }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    renderRestResponse(data.raw || "");
    setRestStatus("Request completed.", "ok");
  } catch (e) {
    setRestStatus(`Request failed: ${e.message}`, "error");
  }
}

$("#rest-send-btn").addEventListener("click", sendRestRequest);

// ---------- Apex Execute Anonymous (connected mode) ----------

let lastApexResult = null;

function setApexStatus(text, kind) {
  const el = $("#apex-status-line");
  el.textContent = text;
  el.className = kind || "";
}

function renderApexResult(result) {
  const section = $("#apex-result-section");
  const parts = [];
  if (!result.compiled) {
    parts.push(
      `Compile error${result.line != null ? ` (line ${result.line}, column ${result.column})` : ""}:\n${result.compileProblem || "Unknown compile error."}`,
    );
  } else if (!result.success) {
    parts.push(
      `Exception${result.line != null ? ` (line ${result.line}, column ${result.column})` : ""}: ${result.exceptionMessage || "Unknown exception."}`,
    );
    if (result.exceptionStackTrace) parts.push(`\nStack trace:\n${result.exceptionStackTrace}`);
  } else {
    parts.push("Compiled and executed successfully.");
  }
  if (result.logs) parts.push(`\nDebug log:\n${result.logs}`);
  section.innerHTML = `<pre class="rest-response-pre">${escapeHtml(parts.join("\n"))}</pre>`;
}

async function executeApex() {
  const code = $("#apex-code-input").value;
  if (!code.trim()) {
    setApexStatus("Enter some Apex to execute.", "error");
    return;
  }
  if (!currentOrg) {
    setApexStatus("Select an org first.", "error");
    return;
  }

  const confirmed = window.confirm(
    `Execute anonymous Apex on org ${currentOrg}?\n\nThis runs arbitrary Apex against Salesforce immediately, including any DML or callouts in the code.`,
  );
  if (!confirmed) {
    setApexStatus("Execution cancelled.", "");
    return;
  }

  setApexStatus("Executing…", "");
  try {
    const res = await fetch("/api/apex-execute", {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ org: currentOrg, code }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    renderApexResult(data);
    setApexStatus(data.compiled && data.success ? "Executed successfully." : "Executed with errors.", data.compiled && data.success ? "ok" : "error");
    lastApexResult = data;
    $("#apex-json-editor-btn").disabled = false;
  } catch (e) {
    setApexStatus(`Execution failed: ${e.message}`, "error");
  }
}

$("#apex-execute-btn").addEventListener("click", executeApex);

// Finds every balanced {...} substring in text (e.g. debug-log lines like
// `...|USER_DEBUG|[2]|DEBUG|{"foo":1}`), respecting quoted strings so a `}`
// inside a string value doesn't end a match early. A log can contain more
// than one System.debug(...) JSON dump (intermediate state as well as the
// final result) — the caller decides which candidate to use.
function findBalancedJsonObjects(text) {
  const results = [];
  let searchFrom = 0;
  while (true) {
    const start = text.indexOf("{", searchFrom);
    if (start === -1) break;
    let depth = 0;
    let inString = false;
    let escape = false;
    let end = -1;
    for (let i = start; i < text.length; i++) {
      const ch = text[i];
      if (inString) {
        if (escape) escape = false;
        else if (ch === "\\") escape = true;
        else if (ch === '"') inString = false;
        continue;
      }
      if (ch === '"') inString = true;
      else if (ch === "{") depth++;
      else if (ch === "}") {
        depth--;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    if (end === -1) break;
    results.push(text.slice(start, end + 1));
    searchFrom = end + 1;
  }
  return results;
}

// Apex Execute's `logs` field is the raw debug log text — when the anonymous
// Apex does one or more System.debug(someJsonString) calls, the log can
// contain several JSON-shaped blobs (e.g. an intermediate/partial object
// debugged mid-execution, plus the final complete result debugged later).
// Pick the largest candidate that actually parses as JSON — that's
// virtually always the complete payload the user cares about, not an
// earlier partial dump — so the JSON Editor opens on the right data instead
// of whichever JSON object happens to appear first in the log.
function extractEmbeddedJsonPayload(result) {
  if (!result || typeof result.logs !== "string") return null;
  const candidates = findBalancedJsonObjects(result.logs);
  let best = null;
  let bestLength = -1;
  for (const candidate of candidates) {
    if (candidate.length <= bestLength) continue;
    try {
      const parsed = JSON.parse(candidate);
      best = parsed;
      bestLength = candidate.length;
    } catch (e) {
      // Not valid JSON on its own (e.g. `}` closed a brace that was part of
      // Apex code text, not this candidate's own object) — skip it.
    }
  }
  return best;
}

$("#apex-json-editor-btn").addEventListener("click", () => {
  if (!lastApexResult) return;
  const embedded = extractEmbeddedJsonPayload(lastApexResult);
  const payload = embedded !== null ? embedded : lastApexResult;
  const serialized = JSON.stringify(payload);
  try {
    localStorage.setItem("soql-builder-json-editor-payload", serialized);
  } catch (e) {
    // Storage may be unavailable (private browsing, quota, embedded-frame
    // restrictions) — fall through to the postMessage handoff below instead
    // of stopping here.
  }
  // Reuse a single named tab so repeated clicks always reload with the
  // latest data, instead of piling up stale tabs that still show whatever
  // (or nothing) they loaded on a previous click.
  const child = window.open("json-editor.html", "soql-builder-json-editor");
  if (!child) {
    setApexStatus("Couldn't open JSON Editor — check your browser's popup blocker.", "error");
    return;
  }
  child.focus();
  // Backup transport in case localStorage didn't stick (e.g. blocked in the
  // tab that just opened): once that tab announces it's ready, hand it the
  // payload directly.
  const respondWhenReady = (event) => {
    if (event.source !== child || !event.data || event.data.type !== "soql-builder-json-editor-ready") return;
    window.removeEventListener("message", respondWhenReady);
    child.postMessage({ type: "soql-builder-json-editor-payload", payload: serialized }, window.location.origin);
  };
  window.addEventListener("message", respondWhenReady);
});

// ---------- Misc ----------

function setStatus(text, kind) {
  const el = $("#status-line");
  el.textContent = text;
  el.className = kind || "";
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- Init ----------

renderObjectList("");
populateSemiJoinSelects();
setTextarea("-- Check one or more objects on the left to start building queries.");
detectConnection();

function setActiveSection(section) {
  $("#explorer-section").classList.toggle("hidden", section !== "explorer");
  $("#utilities-section").classList.toggle("hidden", section !== "utilities");
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.section === section);
  });
}
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => setActiveSection(btn.dataset.section));
});
