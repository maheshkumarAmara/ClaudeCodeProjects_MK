// JSON Editor — self-hosted viewer/editor for arbitrary JSON, with Tree,
// Text and Flow Chart views. Loaded standalone by json-editor.html (does
// not share scope with app.js), so any helpers it needs are local copies.

const LS_KEY = "soql-builder-json-editor-payload";

const el = {
  statusLine: document.getElementById("json-status-line"),
  emptyState: document.getElementById("json-empty-state"),
  pasteInput: document.getElementById("json-paste-input"),
  loadBtn: document.getElementById("json-load-btn"),
  editorBody: document.getElementById("json-editor-body"),
  viewTreeBtn: document.getElementById("json-view-tree-btn"),
  viewTextBtn: document.getElementById("json-view-text-btn"),
  viewFlowchartBtn: document.getElementById("json-view-flowchart-btn"),
  searchInput: document.getElementById("json-search-input"),
  expandAllBtn: document.getElementById("json-expand-all-btn"),
  collapseAllBtn: document.getElementById("json-collapse-all-btn"),
  formatBtn: document.getElementById("json-format-btn"),
  copyBtn: document.getElementById("json-copy-btn"),
  treeView: document.getElementById("json-tree-view"),
  textView: document.getElementById("json-text-view"),
  textArea: document.getElementById("json-text-area"),
  flowchartView: document.getElementById("json-flowchart-view"),
  flowchartWrap: document.getElementById("json-flowchart-canvas-wrap"),
  zoomInBtn: document.getElementById("flowchart-zoom-in-btn"),
  zoomOutBtn: document.getElementById("flowchart-zoom-out-btn"),
  zoomResetBtn: document.getElementById("flowchart-zoom-reset-btn"),
  downloadPdfBtn: document.getElementById("flowchart-download-pdf-btn"),
};

let currentData = null;
let activeView = "tree";
let searchTerm = "";
let zoomLevel = 1;

const treeManualOverride = new Map(); // path -> boolean (explicit expand/collapse)
const flowchartExpanded = new Set(); // paths the user has expanded into child boxes

const DEFAULT_TREE_EXPAND_DEPTH = 2;

// ---------- shared helpers ----------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function highlightMatches(raw, term) {
  if (!term) return escapeHtml(raw);
  const lowerRaw = raw.toLowerCase();
  const lowerTerm = term.toLowerCase();
  let result = "";
  let i = 0;
  while (i < raw.length) {
    const idx = lowerRaw.indexOf(lowerTerm, i);
    if (idx === -1) {
      result += escapeHtml(raw.slice(i));
      break;
    }
    result += escapeHtml(raw.slice(i, idx));
    result += "<mark>" + escapeHtml(raw.slice(idx, idx + term.length)) + "</mark>";
    i = idx + term.length;
  }
  return result;
}

function typeOf(v) {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  return typeof v;
}

function truncateText(s, max) {
  s = String(s);
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function setStatus(msg, kind) {
  el.statusLine.textContent = msg || "";
  el.statusLine.className = kind || "";
}

// ---------- boot / data loading ----------

function tryLoadFromStorage() {
  let raw = null;
  try {
    raw = localStorage.getItem(LS_KEY);
  } catch (e) {
    raw = null;
  }
  if (!raw) return false;
  try {
    currentData = JSON.parse(raw);
  } catch (e) {
    return false;
  }
  try {
    localStorage.removeItem(LS_KEY);
  } catch (e) {
    // ignore
  }
  return true;
}

function showEmptyState() {
  el.emptyState.classList.remove("hidden");
  el.editorBody.classList.add("hidden");
}

function showEditor() {
  el.emptyState.classList.add("hidden");
  el.editorBody.classList.remove("hidden");
  switchView("tree");
}

el.loadBtn.addEventListener("click", () => {
  const raw = el.pasteInput.value.trim();
  if (!raw) {
    setStatus("Paste some JSON first.", "error");
    return;
  }
  try {
    currentData = JSON.parse(raw);
  } catch (e) {
    setStatus("Invalid JSON: " + e.message, "error");
    return;
  }
  setStatus("Loaded.", "ok");
  showEditor();
});

// ---------- view switching ----------

const VIEW_BTNS = { tree: el.viewTreeBtn, text: el.viewTextBtn, flowchart: el.viewFlowchartBtn };
const VIEW_PANELS = { tree: el.treeView, text: el.textView, flowchart: el.flowchartView };

function switchView(view) {
  if (activeView === "text" && view !== "text") {
    try {
      currentData = JSON.parse(el.textArea.value);
    } catch (e) {
      setStatus("Fix invalid JSON in Text view before switching: " + e.message, "error");
      return;
    }
  }
  activeView = view;
  Object.keys(VIEW_PANELS).forEach((v) => {
    VIEW_PANELS[v].classList.toggle("hidden", v !== view);
    VIEW_BTNS[v].classList.toggle("primary", v === view);
  });
  el.formatBtn.classList.toggle("hidden", view !== "text");

  if (view === "tree") renderTreeView();
  else if (view === "text") el.textArea.value = JSON.stringify(currentData, null, 2);
  else if (view === "flowchart") renderFlowchartView();
}

el.viewTreeBtn.addEventListener("click", () => switchView("tree"));
el.viewTextBtn.addEventListener("click", () => switchView("text"));
el.viewFlowchartBtn.addEventListener("click", () => switchView("flowchart"));

el.formatBtn.addEventListener("click", () => {
  try {
    const parsed = JSON.parse(el.textArea.value);
    el.textArea.value = JSON.stringify(parsed, null, 2);
    setStatus("Formatted.", "ok");
  } catch (e) {
    setStatus("Can't format — invalid JSON: " + e.message, "error");
  }
});

el.copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(JSON.stringify(currentData, null, 2));
    setStatus("Copied JSON to clipboard.", "ok");
  } catch (e) {
    setStatus("Copy failed: " + e.message, "error");
  }
});

el.searchInput.addEventListener("input", () => {
  searchTerm = el.searchInput.value.trim();
  if (activeView === "tree") renderTreeView();
  else if (activeView === "flowchart") renderFlowchartView();
});

// ---------- Tree view ----------

function collectMatchAncestors(value, key, path, term, resultSet) {
  const t = typeOf(value);
  let selfMatches = key !== null && String(key).toLowerCase().includes(term);
  if (t === "object" || t === "array") {
    const entries = t === "object" ? Object.entries(value) : value.map((v, i) => [String(i), v]);
    let anyChildMatch = false;
    entries.forEach(([k, v]) => {
      const childPath = t === "object" ? `${path}.${k}` : `${path}[${k}]`;
      if (collectMatchAncestors(v, k, childPath, term, resultSet)) anyChildMatch = true;
    });
    if (anyChildMatch) resultSet.add(path);
    return selfMatches || anyChildMatch;
  }
  if (String(value).toLowerCase().includes(term)) selfMatches = true;
  return selfMatches;
}

function isTreeExpanded(path, depth, matchPaths) {
  if (treeManualOverride.has(path)) return treeManualOverride.get(path);
  if (matchPaths && matchPaths.has(path)) return true;
  return depth < DEFAULT_TREE_EXPAND_DEPTH;
}

function formatScalarForTree(value, t) {
  if (t === "string") return JSON.stringify(value);
  if (t === "null") return "null";
  return String(value);
}

function buildTreeNode(value, key, path, depth, matchPaths) {
  const frag = document.createDocumentFragment();
  const t = typeOf(value);

  const label = document.createElement("div");
  label.className = "json-node-label";
  label.dataset.path = path;

  if (key !== null) {
    const keySpan = document.createElement("span");
    keySpan.className = "json-key";
    keySpan.innerHTML = (searchTerm ? highlightMatches(String(key), searchTerm) : escapeHtml(String(key))) + ":";
    label.appendChild(keySpan);
  }

  if (t === "object" || t === "array") {
    const entries = t === "object" ? Object.entries(value) : value.map((v, i) => [String(i), v]);

    const toggle = document.createElement("span");
    toggle.className = "muted";
    toggle.style.cursor = "pointer";
    label.insertBefore(toggle, label.firstChild);

    const typeSpan = document.createElement("span");
    typeSpan.className = "json-type " + (t === "object" ? "json-type-object" : "json-type-array");
    typeSpan.textContent = t === "object" ? `{${entries.length}}` : `[${entries.length}]`;
    label.appendChild(typeSpan);

    const children = document.createElement("div");
    children.className = "json-children";
    children.dataset.path = path;

    const expanded = isTreeExpanded(path, depth, matchPaths);
    toggle.textContent = expanded ? "▼" : "▶";
    if (!expanded) children.classList.add("hidden");

    entries.forEach(([k, v]) => {
      const childPath = t === "object" ? `${path}.${k}` : `${path}[${k}]`;
      children.appendChild(buildTreeNode(v, k, childPath, depth + 1, matchPaths));
    });

    label.addEventListener("click", () => {
      const isHiddenNow = children.classList.toggle("hidden");
      toggle.textContent = isHiddenNow ? "▶" : "▼";
      treeManualOverride.set(path, !isHiddenNow);
    });

    frag.appendChild(label);
    frag.appendChild(children);
  } else {
    const valueSpan = document.createElement("span");
    valueSpan.className = "json-value json-" + t;
    const raw = formatScalarForTree(value, t);
    valueSpan.innerHTML = searchTerm ? highlightMatches(raw, searchTerm) : escapeHtml(raw);
    label.appendChild(valueSpan);
    frag.appendChild(label);
  }

  return frag;
}

function renderTreeView() {
  el.treeView.innerHTML = "";
  const matchPaths = searchTerm ? (() => {
    const s = new Set();
    collectMatchAncestors(currentData, null, "$", searchTerm.toLowerCase(), s);
    return s;
  })() : null;
  el.treeView.appendChild(buildTreeNode(currentData, null, "$", 0, matchPaths));
}

function setAllTreeExpanded(expanded) {
  el.treeView.querySelectorAll(".json-node-label[data-path]").forEach((label) => {
    const children = label.nextElementSibling;
    if (!children || !children.classList.contains("json-children")) return;
    treeManualOverride.set(label.dataset.path, expanded);
    children.classList.toggle("hidden", !expanded);
    const icon = label.querySelector(".muted");
    if (icon) icon.textContent = expanded ? "▼" : "▶";
  });
}

el.expandAllBtn.addEventListener("click", () => {
  if (activeView === "flowchart") setAllFlowchartExpanded(true);
  else setAllTreeExpanded(true);
});
el.collapseAllBtn.addEventListener("click", () => {
  if (activeView === "flowchart") setAllFlowchartExpanded(false);
  else setAllTreeExpanded(false);
});

// ---------- Flow Chart view ----------

const FLOW = {
  ROW_H: 18,
  HEADER_H: 22,
  BOX_W: 240,
  PAD: 8,
  H_GAP: 70,
  V_GAP: 14,
  MAX_ROWS: 15,
};

function svgEl(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  if (attrs) {
    Object.keys(attrs).forEach((k) => node.setAttribute(k, attrs[k]));
  }
  return node;
}

function formatScalarForFlow(v, t) {
  if (t === "string") return truncateText(JSON.stringify(v), 40);
  if (t === "null") return "null";
  return truncateText(String(v), 40);
}

function buildFlowNode(value, label, path, term) {
  const t = typeOf(value);
  const isArr = t === "array";
  const entries = isArr ? value.map((v, i) => [String(i), v]) : Object.entries(value);
  const shown = entries.slice(0, FLOW.MAX_ROWS);

  const node = {
    path,
    kind: isArr ? "array" : "object",
    headerText: `${label} · ${isArr ? "Array" : "Object"} · ${entries.length}`,
    rows: [],
    isMatch: term ? String(label).toLowerCase().includes(term) : false,
  };

  shown.forEach(([k, v], i) => {
    const childPath = isArr ? `${path}[${k}]` : `${path}.${k}`;
    const vt = typeOf(v);
    let row;
    if (vt === "object" || vt === "array") {
      const expanded = flowchartExpanded.has(childPath);
      const count = vt === "array" ? v.length : Object.keys(v).length;
      row = {
        kind: "nested",
        childPath,
        expanded,
        label: `${k} (${vt === "array" ? "Array" : "Object"} · ${count})`,
        isMatch: term ? String(k).toLowerCase().includes(term) : false,
      };
      if (expanded) row.child = buildFlowNode(v, k, childPath, term);
    } else {
      row = {
        kind: "scalar",
        text: `${k}: ${formatScalarForFlow(v, vt)}`,
        isMatch: term ? (String(k).toLowerCase().includes(term) || String(v).toLowerCase().includes(term)) : false,
      };
    }
    row.rowIndex = i;
    node.rows.push(row);
  });

  if (entries.length > FLOW.MAX_ROWS) {
    node.rows.push({ kind: "moreInfo", text: `+${entries.length - FLOW.MAX_ROWS} more — see Tree view`, rowIndex: shown.length });
  }

  return node;
}

function computeHeights(node) {
  let childrenTotal = 0;
  let childCount = 0;
  node.rows.forEach((row) => {
    if (row.kind === "nested" && row.child) {
      row.childSubtreeHeight = computeHeights(row.child);
      childrenTotal += row.childSubtreeHeight;
      childCount++;
    }
  });
  if (childCount > 1) childrenTotal += (childCount - 1) * FLOW.V_GAP;
  node.boxHeight = FLOW.HEADER_H + node.rows.length * FLOW.ROW_H + FLOW.PAD * 2;
  node.subtreeHeight = Math.max(node.boxHeight, childrenTotal);
  return node.subtreeHeight;
}

function computeMaxDepth(node) {
  let maxChildDepth = 0;
  node.rows.forEach((row) => {
    if (row.kind === "nested" && row.child) {
      maxChildDepth = Math.max(maxChildDepth, computeMaxDepth(row.child));
    }
  });
  return 1 + maxChildDepth;
}

function renderFlowNode(svg, node, x, yTop) {
  const boxY = yTop + (node.subtreeHeight - node.boxHeight) / 2;
  const g = svgEl("g", { class: "flowchart-node", "data-container": "true" });

  const typeClass = node.kind === "array" ? "flowchart-node-array" : "flowchart-node-object";
  const boxClass = "flowchart-node-box " + typeClass + (node.isMatch ? " flowchart-node-match" : "");
  g.appendChild(svgEl("rect", { class: boxClass, x, y: boxY, width: FLOW.BOX_W, height: node.boxHeight, rx: 6 }));
  g.appendChild(svgEl("rect", { class: "flowchart-node-header " + typeClass, x, y: boxY, width: FLOW.BOX_W, height: FLOW.HEADER_H }));

  const headerText = svgEl("text", { class: "flowchart-node-header-text", x: x + FLOW.PAD, y: boxY + FLOW.HEADER_H / 2 + 4 });
  headerText.textContent = truncateText(node.headerText, 34);
  g.appendChild(headerText);

  node.rows.forEach((row) => {
    const rowY = boxY + FLOW.HEADER_H + FLOW.PAD + row.rowIndex * FLOW.ROW_H + FLOW.ROW_H / 2 + 4;
    if (row.kind === "scalar") {
      const t = svgEl("text", { class: "flowchart-field-row" + (row.isMatch ? " flowchart-field-row-match" : ""), x: x + FLOW.PAD, y: rowY });
      t.textContent = truncateText(row.text, 34);
      g.appendChild(t);
    } else if (row.kind === "nested") {
      const icon = svgEl("text", { class: "flowchart-toggle-icon", x: x + FLOW.PAD, y: rowY, "data-toggle-path": row.childPath });
      icon.textContent = row.expanded ? "▼" : "▶";
      icon.style.cursor = "pointer";
      g.appendChild(icon);
      const t = svgEl("text", {
        class: "flowchart-field-row" + (row.isMatch ? " flowchart-field-row-match" : ""),
        x: x + FLOW.PAD + 12,
        y: rowY,
        "data-toggle-path": row.childPath,
      });
      t.textContent = truncateText(row.label, 30);
      t.style.cursor = "pointer";
      g.appendChild(t);
    } else if (row.kind === "moreInfo") {
      const t = svgEl("text", { class: "flowchart-more-row", x: x + FLOW.PAD, y: rowY });
      t.textContent = row.text;
      g.appendChild(t);
    }
  });

  svg.appendChild(g);

  let childY = yTop;
  node.rows.forEach((row) => {
    if (row.kind === "nested" && row.child) {
      const childX = x + FLOW.BOX_W + FLOW.H_GAP;
      const edgeStartY = boxY + FLOW.HEADER_H + FLOW.PAD + row.rowIndex * FLOW.ROW_H + FLOW.ROW_H / 2;
      const childBoxY = childY + (row.childSubtreeHeight - row.child.boxHeight) / 2;
      const edgeEndY = childBoxY + FLOW.HEADER_H / 2;
      svg.appendChild(
        svgEl("path", {
          class: "flowchart-edge",
          fill: "none",
          d: `M ${x + FLOW.BOX_W} ${edgeStartY} C ${x + FLOW.BOX_W + FLOW.H_GAP / 2} ${edgeStartY}, ${childX - FLOW.H_GAP / 2} ${edgeEndY}, ${childX} ${edgeEndY}`,
        })
      );
      renderFlowNode(svg, row.child, childX, childY);
      childY += row.childSubtreeHeight + FLOW.V_GAP;
    }
  });
}

function applyZoom() {
  const svg = el.flowchartWrap.querySelector("svg");
  if (svg) {
    svg.style.transform = `scale(${zoomLevel})`;
    svg.style.transformOrigin = "top left";
  }
}

el.zoomInBtn.addEventListener("click", () => {
  zoomLevel = Math.min(2.5, +(zoomLevel + 0.1).toFixed(2));
  applyZoom();
});
el.zoomOutBtn.addEventListener("click", () => {
  zoomLevel = Math.max(0.3, +(zoomLevel - 0.1).toFixed(2));
  applyZoom();
});
el.zoomResetBtn.addEventListener("click", () => {
  zoomLevel = 1;
  applyZoom();
});
function getPrintPageStyleTag() {
  let tag = document.getElementById("print-page-size");
  if (!tag) {
    tag = document.createElement("style");
    tag.id = "print-page-size";
    document.head.appendChild(tag);
  }
  return tag;
}

// Recursively hunts `value` for a key spelled "OrderNumber" (any case) and
// returns its first match. Payload shape varies with whatever Apex query
// produced it, so this can't assume a fixed path to the field.
function findOrderNumber(value, seen) {
  if (!value || typeof value !== "object") return null;
  seen = seen || new Set();
  if (seen.has(value)) return null;
  seen.add(value);

  const entries = Array.isArray(value) ? value.map((v, i) => [String(i), v]) : Object.entries(value);
  for (const [key, val] of entries) {
    if (key.toLowerCase() === "ordernumber" && (typeof val === "string" || typeof val === "number") && String(val).trim()) {
      return String(val).trim();
    }
  }
  for (const [, val] of entries) {
    if (val && typeof val === "object") {
      const found = findOrderNumber(val, seen);
      if (found) return found;
    }
  }
  return null;
}

// Strips characters that are illegal (or awkward) in a downloaded filename.
function sanitizeFilename(str) {
  const cleaned = String(str)
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_");
  return cleaned || "Order";
}

const ORIGINAL_DOCUMENT_TITLE = document.title;

el.downloadPdfBtn.addEventListener("click", () => {
  const svg = el.flowchartWrap.querySelector("svg");
  if (!svg) {
    setStatus("Nothing to export — the current data has no Flow Chart diagram to print.", "error");
    return;
  }
  // SVG content can't reflow across page breaks, so the browser's default
  // paginated print just slices straight through node boxes wherever a page
  // boundary happens to fall. Sizing the printed page to the diagram's exact
  // (unzoomed) dimensions puts the whole thing on a single page instead.
  const MAX_PAGE_PX = 19000; // stay under browsers' practical @page size ceiling
  const box = svg.viewBox && svg.viewBox.baseVal;
  const rawWidth = Math.min(MAX_PAGE_PX, Math.ceil(box && box.width ? box.width : svg.getBoundingClientRect().width));
  const rawHeight = Math.min(MAX_PAGE_PX, Math.ceil(box && box.height ? box.height : svg.getBoundingClientRect().height));

  // Always print landscape (wider than tall). Most of these trees are
  // naturally wider than tall already; when one isn't, rotate the SVG 90°
  // so it lies sideways on the landscape page instead of clipping.
  const needsRotate = rawHeight > rawWidth;
  const pageWidth = needsRotate ? rawHeight : rawWidth;
  const pageHeight = needsRotate ? rawWidth : rawHeight;
  const rotateRule = needsRotate
    ? `#json-flowchart-canvas-wrap svg { transform: translate(${rawHeight}px, 0) rotate(90deg) !important; transform-origin: 0 0 !important; }`
    : "";
  getPrintPageStyleTag().textContent = `@page { size: ${pageWidth}px ${pageHeight}px; margin: 0; } ${rotateRule}`;

  const orderNumber = findOrderNumber(currentData);
  document.title = `${sanitizeFilename(orderNumber)}_JsonPayLoad`;
  window.addEventListener(
    "afterprint",
    () => {
      document.title = ORIGINAL_DOCUMENT_TITLE;
    },
    { once: true }
  );

  setStatus('In the print dialog, choose "Save as PDF" (or your OS equivalent) as the destination.', "ok");
  window.print();
});

function collectAllContainerPaths(value, path, result) {
  const t = typeOf(value);
  if (t !== "object" && t !== "array") return;
  const entries = t === "array" ? value.map((v, i) => [String(i), v]) : Object.entries(value);
  entries.forEach(([k, v]) => {
    const childPath = t === "array" ? `${path}[${k}]` : `${path}.${k}`;
    const childType = typeOf(v);
    if (childType === "object" || childType === "array") {
      result.add(childPath);
      collectAllContainerPaths(v, childPath, result);
    }
  });
}

function setAllFlowchartExpanded(expanded) {
  flowchartExpanded.clear();
  if (expanded) collectAllContainerPaths(currentData, "$", flowchartExpanded);
  renderFlowchartView();
}

function renderFlowchartView() {
  el.flowchartWrap.innerHTML = "";
  const t = typeOf(currentData);
  if (t !== "object" && t !== "array") {
    const p = document.createElement("div");
    p.className = "muted";
    p.textContent = "Root value is not an object or array — switch to Text view to see it.";
    el.flowchartWrap.appendChild(p);
    return;
  }

  const term = searchTerm ? searchTerm.toLowerCase() : null;
  const root = buildFlowNode(currentData, "root", "$", term);
  computeHeights(root);
  const depth = computeMaxDepth(root);
  const width = depth * FLOW.BOX_W + (depth - 1) * FLOW.H_GAP + FLOW.PAD * 2;
  const height = root.subtreeHeight + FLOW.PAD * 2;

  const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}` });
  renderFlowNode(svg, root, FLOW.PAD, FLOW.PAD);
  svg.style.transform = `scale(${zoomLevel})`;
  svg.style.transformOrigin = "top left";

  svg.addEventListener("click", (e) => {
    const path = e.target.getAttribute && e.target.getAttribute("data-toggle-path");
    if (!path) return;
    if (flowchartExpanded.has(path)) flowchartExpanded.delete(path);
    else flowchartExpanded.add(path);
    renderFlowchartView();
  });

  el.flowchartWrap.appendChild(svg);
}

// ---------- init ----------

function tryLoadFromOpener() {
  if (!window.opener || window.opener.closed) return;
  window.addEventListener("message", function onMessage(event) {
    if (event.origin !== window.location.origin) return;
    if (!event.data || event.data.type !== "soql-builder-json-editor-payload") return;
    window.removeEventListener("message", onMessage);
    try {
      currentData = JSON.parse(event.data.payload);
    } catch (e) {
      return;
    }
    showEditor();
    setStatus("Loaded automatically from Apex Execute.", "ok");
  });
  try {
    window.opener.postMessage({ type: "soql-builder-json-editor-ready" }, window.location.origin);
  } catch (e) {
    // opener is cross-origin or gone — nothing more we can do automatically
  }
}

if (tryLoadFromStorage()) {
  showEditor();
  setStatus("Loaded automatically from Apex Execute.", "ok");
} else {
  showEmptyState();
  // localStorage may not have carried the payload (private browsing, an
  // earlier reuse of this same tab having already consumed/removed the
  // one-shot key, etc.) — ask the opener directly as a backup.
  tryLoadFromOpener();
}
