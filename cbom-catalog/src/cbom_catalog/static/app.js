"use strict";

const API_BASE = "/api/v1";
const PAGE_SIZE = 50;
const FIPS_RESULT_LIMIT = 100;

const state = {
  view: "overview",
  collection: "",
  group: "",
  collections: [],
  groups: [],
  overview: null,
  latestRun: null,
  inventory: {
    entity: "documents",
    query: "",
    type: "",
    offset: 0,
    rows: [],
    sortKey: "",
    sortDirection: "ascending",
    request: 0,
  },
  graph: {
    documents: [],
    data: null,
    selectedRef: "",
    request: 0,
  },
  integrity: {
    entity: "fingerprints",
    query: "",
    rows: [],
    request: 0,
  },
  fips: {
    data: null,
    tab: "assessment",
    query: "",
    filter: "all",
    request: 0,
  },
};

const viewTitles = {
  overview: "Overview",
  inventory: "Inventory",
  graph: "Dependencies",
  integrity: "Refresh integrity",
  fips: "FIPS / POA&M",
};

const inventoryLabels = {
  documents: {
    caption: "Catalog documents",
    searchLabel: "Filter source path",
    placeholder: "Path contains…",
    typeLabel: "Format / version",
  },
  components: {
    caption: "Canonical components",
    searchLabel: "Search name, PURL, or CPE",
    placeholder: "e.g. openssl or pkg:rpm…",
    typeLabel: "Component type",
  },
  artifacts: {
    caption: "Artifacts",
    searchLabel: "Search artifact, PURL, or key",
    placeholder: "Artifact name or digest…",
    typeLabel: "Artifact type",
  },
  evidence: {
    caption: "Evidence and assessment records",
    searchLabel: "Filter this result page",
    placeholder: "Provider, type, or artifact…",
    typeLabel: "Record type",
  },
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const byId = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value) {
  const number = Number(value ?? 0);
  return Number.isFinite(number) ? new Intl.NumberFormat().format(number) : "0";
}

function formatBytes(value) {
  let bytes = Number(value ?? 0);
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  const units = ["B", "KiB", "MiB", "GiB"];
  let unit = 0;
  while (bytes >= 1024 && unit < units.length - 1) {
    bytes /= 1024;
    unit += 1;
  }
  return `${bytes >= 10 || unit === 0 ? bytes.toFixed(0) : bytes.toFixed(1)} ${units[unit]}`;
}

function formatDate(value, includeTime = true) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    ...(includeTime ? { timeStyle: "short" } : {}),
  }).format(date);
}

function relativeDate(value) {
  if (!value) return "not recorded";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return formatDate(value);
  const seconds = Math.round((timestamp - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}

function truncate(value, length = 72) {
  const text = String(value ?? "");
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

function first(array, fallback = "—") {
  return Array.isArray(array) && array.length ? array[0] : fallback;
}

function humanize(value) {
  return String(value ?? "unknown")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function badge(value, tone = "") {
  const label = humanize(value || "unknown");
  const toneClass = tone ? ` status-${tone}` : "";
  return `<span class="${tone ? "status-badge" : "badge"}${toneClass}">${escapeHtml(label)}</span>`;
}

function statusTone(value) {
  const status = String(value ?? "").toLowerCase();
  if (["completed", "loaded", "linked", "unchanged", "resolved", "ok"].includes(status)) {
    return "good";
  }
  if (["warning", "partial", "external", "completed_with_errors", "empty"].includes(status)) {
    return "warning";
  }
  if (["error", "failed", "invalid", "ambiguous"].includes(status)) return "error";
  return "";
}

function buildUrl(path, params = {}) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const resolvedPath = normalizedPath === "/healthz" || normalizedPath.startsWith("/api/")
    ? normalizedPath
    : `${API_BASE}${normalizedPath}`;
  const url = new URL(resolvedPath, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    if (Array.isArray(value)) {
      value.forEach((item) => url.searchParams.append(key, item));
    } else {
      url.searchParams.set(key, String(value));
    }
  });
  return url;
}

async function fetchJson(path, params = {}) {
  const response = await fetch(buildUrl(path, params), {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_error) {
      // Keep the HTTP status as the actionable message.
    }
    throw new Error(detail);
  }
  return response.json();
}

function toast(message, kind = "info") {
  const element = document.createElement("div");
  element.className = `toast${kind === "error" ? " is-error" : ""}`;
  element.textContent = message;
  byId("toast-region").append(element);
  window.setTimeout(() => element.remove(), 4500);
}

function debounce(callback, delay = 320) {
  let timeout;
  return (...args) => {
    window.clearTimeout(timeout);
    timeout = window.setTimeout(() => callback(...args), delay);
  };
}

function setConnection(status, label) {
  const element = byId("connection-state");
  element.classList.toggle("is-online", status === "online");
  element.classList.toggle("is-offline", status === "offline");
  $("span:last-child", element).textContent = label;
}

async function checkHealth() {
  try {
    const health = await fetchJson("/healthz");
    setConnection("online", `${health.database || "Catalog"} online`);
  } catch (_error) {
    setConnection("offline", "Catalog unavailable");
  }
}

function initializeTheme() {
  const stored = window.localStorage.getItem("cbom-theme");
  const preferred = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  applyTheme(stored || preferred);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  window.localStorage.setItem("cbom-theme", theme);
  byId("theme-toggle").setAttribute(
    "aria-label",
    theme === "dark" ? "Use light theme" : "Use dark theme",
  );
}

function installTabs(container, dataAttribute, callback) {
  const buttons = $$(`[${dataAttribute}]`, container);
  const dataKey = dataAttribute
    .replace(/^data-/, "")
    .replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
  const activate = (button, moveFocus = false) => {
    buttons.forEach((candidate) => {
      const selected = candidate === button;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
    });
    callback(button.dataset[dataKey]);
    if (moveFocus) button.focus();
  };
  buttons.forEach((button) => {
    button.addEventListener("click", () => activate(button));
    button.addEventListener("keydown", (event) => {
      const current = buttons.indexOf(button);
      let next = current;
      if (event.key === "ArrowRight") next = (current + 1) % buttons.length;
      if (event.key === "ArrowLeft") next = (current - 1 + buttons.length) % buttons.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = buttons.length - 1;
      if (next !== current) {
        event.preventDefault();
        activate(buttons[next], true);
      }
    });
  });
}

function showView(view, options = {}) {
  if (!viewTitles[view]) view = "overview";
  state.view = view;
  $$("[data-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.panel !== view;
  });
  $$("[data-view]").forEach((button) => {
    const selected = button.dataset.view === view;
    button.classList.toggle("is-active", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  byId("page-title").textContent = viewTitles[view];
  document.title = `${viewTitles[view]} · CBOM Workbench`;
  if (options.updateHistory !== false && window.location.hash !== `#${view}`) {
    window.history.pushState(null, "", `#${view}`);
  }
  if (options.focus) byId("main-content").focus({ preventScroll: true });
  if (view === "overview") loadOverview();
  if (view === "inventory") loadInventory();
  if (view === "graph") loadDependencyDocuments();
  if (view === "integrity") loadIntegrity();
  if (view === "fips") loadFipsAssessment();
}

function scopeParams() {
  return {
    source_collection: state.collection,
    service_group: state.group,
  };
}

function updateScopeSummary() {
  const collection = state.collections.find((item) => item.slug === state.collection);
  const group = state.groups.find((item) => item.slug === state.group);
  let label = "All collections";
  if (collection) label = collection.display_name || collection.slug;
  if (group) label += ` / ${group.display_name || group.slug}`;
  byId("scope-summary").textContent = label;
  byId("clear-scope").hidden = !state.collection && !state.group;

  if (collection?.last_ingested_at) {
    byId("freshness-summary").textContent = `Last refresh ${relativeDate(collection.last_ingested_at)}`;
  } else if (state.collection) {
    byId("freshness-summary").textContent = "No completed refresh recorded";
  } else {
    const timestamps = state.collections
      .map((item) => item.last_ingested_at)
      .filter(Boolean)
      .sort();
    byId("freshness-summary").textContent = timestamps.length
      ? `Most recent refresh ${relativeDate(timestamps.at(-1))}`
      : "Refresh time not recorded";
  }
}

async function loadCollections() {
  state.collections = await fetchJson("/source-collections");
  const select = byId("collection-filter");
  const prior = window.sessionStorage.getItem("cbom-collection") || "";
  select.innerHTML = `<option value="">All collections</option>${state.collections
    .map(
      (item) =>
        `<option value="${escapeHtml(item.slug)}">${escapeHtml(item.display_name || item.slug)}</option>`,
    )
    .join("")}`;
  if (state.collections.some((item) => item.slug === prior)) state.collection = prior;
  else if (state.collections.length === 1) state.collection = state.collections[0].slug;
  select.value = state.collection;
  await loadGroups();
  updateScopeSummary();
}

async function loadGroups() {
  const select = byId("group-filter");
  state.group = "";
  select.value = "";
  if (!state.collection) {
    state.groups = [];
    select.disabled = true;
    select.innerHTML = '<option value="">Choose a collection first</option>';
    return;
  }
  state.groups = await fetchJson("/service-groups", { source_collection: state.collection });
  select.innerHTML = `<option value="">All service groups</option>${state.groups
    .map(
      (item) =>
        `<option value="${escapeHtml(item.slug)}">${escapeHtml(item.display_name || item.slug)}</option>`,
    )
    .join("")}`;
  select.disabled = false;
}

async function setScope(collection, group = "") {
  state.collection = collection || "";
  window.sessionStorage.setItem("cbom-collection", state.collection);
  byId("collection-filter").value = state.collection;
  await loadGroups();
  state.group = group && state.groups.some((item) => item.slug === group) ? group : "";
  byId("group-filter").value = state.group;
  updateScopeSummary();
  state.overview = null;
  state.inventory.offset = 0;
  state.graph.documents = [];
  state.graph.data = null;
  state.fips.data = null;
  refreshCurrentView();
}

function refreshCurrentView() {
  if (state.view === "overview") loadOverview(true);
  if (state.view === "inventory") loadInventory();
  if (state.view === "graph") loadDependencyDocuments(true);
  if (state.view === "integrity") loadIntegrity();
  if (state.view === "fips") loadFipsAssessment(true);
}

function setMetric(id, value) {
  byId(id).textContent = formatNumber(value);
}

function chartEmpty(message) {
  return `<div class="empty-state" style="min-height:10rem"><p>${escapeHtml(message)}</p></div>`;
}

function renderBarChart(element, rows, options) {
  if (!rows.length) {
    element.innerHTML = chartEmpty(options.empty || "No chart data in this scope.");
    return;
  }
  const visible = rows.slice(0, options.limit || 8);
  const maximum = Math.max(...visible.map((row) => Number(row[options.valueKey] || 0)), 1);
  element.innerHTML = visible
    .map((row, index) => {
      const label = options.label(row);
      const value = Number(row[options.valueKey] || 0);
      const width = Math.max(0.8, (value / maximum) * 100);
      const attributes = options.action
        ? `data-chart-action="${escapeHtml(options.action)}" data-chart-index="${index}"`
        : "disabled";
      return `
        <button class="bar-row" type="button" ${attributes} aria-label="${escapeHtml(label)}: ${formatNumber(value)}">
          <span class="bar-label" title="${escapeHtml(label)}">${escapeHtml(label)}</span>
          <span class="bar-track" aria-hidden="true"><span class="bar-value" style="width:${width}%"></span></span>
          <span class="bar-number">${formatNumber(value)}</span>
        </button>`;
    })
    .join("");
  if (options.action) element._chartRows = visible;
}

function renderServiceGroups(groups) {
  byId("service-group-count").textContent = `${formatNumber(groups.length)} groups with files`;
  const chart = byId("service-group-chart");
  const top = groups.slice(0, 10);
  if (!top.length) {
    chart.innerHTML = chartEmpty("No service groups in this scope.");
  } else {
    const maximum = Math.max(...top.map((item) => Number(item.source_files || 0)), 1);
    chart.innerHTML = top
      .map((item, index) => {
        const height = Math.max(4, (Number(item.source_files || 0) / maximum) * 100);
        return `
          <button class="rank-column" type="button" data-group-index="${index}"
            aria-label="Scope to ${escapeHtml(item.display_name)}: ${formatNumber(item.source_files)} files">
            <span class="rank-column-bar" style="height:${height}%" aria-hidden="true"></span>
            <span class="rank-column-label" title="${escapeHtml(item.display_name)}">${escapeHtml(item.display_name)}</span>
          </button>`;
      })
      .join("");
    chart._groups = top;
  }

  byId("service-group-table").innerHTML = groups
    .map(
      (item) => `
        <tr>
          <td>
            <button class="row-button" type="button" data-service-scope="${escapeHtml(item.slug)}"
              data-service-collection="${escapeHtml(item.source_collection)}">
              <span class="cell-main">${escapeHtml(item.source_collection)} / ${escapeHtml(item.display_name)}</span>
              <span class="cell-sub">${escapeHtml(item.slug)}</span>
            </button>
          </td>
          <td class="numeric">${formatNumber(item.source_files)}</td>
          <td class="numeric">${formatNumber(item.unique_documents)}</td>
          <td class="numeric">${item.issues ? badge(`${item.issues} issues`, "warning") : badge("0 issues", "good")}</td>
        </tr>`,
    )
    .join("");
}

function renderRefreshSnapshot(run, counts) {
  const element = byId("refresh-snapshot");
  element.classList.remove("loading-block");
  if (!run) {
    element.innerHTML = '<p class="run-meta">No ingestion run has been recorded for this collection.</p>';
    return;
  }
  const coverage = Number(counts.source_files)
    ? (Number(counts.fingerprinted_source_files) / Number(counts.source_files)) * 100
    : 0;
  element.innerHTML = `
    <div class="refresh-run">
      <div><span>Unchanged</span><strong>${formatNumber(run.files_unchanged)}</strong></div>
      <div><span>Loaded</span><strong>${formatNumber(run.files_loaded)}</strong></div>
      <div><span>Linked</span><strong>${formatNumber(run.files_linked)}</strong></div>
      <div><span>Failed</span><strong>${formatNumber(run.files_failed)}</strong></div>
    </div>
    <p class="run-meta">${badge(run.status, statusTone(run.status))} · run ${escapeHtml(run.id)} · ${formatDate(run.completed_at)}</p>
    <p class="run-meta"><strong>${coverage.toFixed(coverage === 100 ? 0 : 1)}%</strong> of scoped source files have a current SHA-256 fingerprint.</p>`;
}

async function loadOverview(force = false) {
  if (state.overview && !force) {
    renderOverview(state.overview, state.latestRun);
    return;
  }
  $$("#metric-grid strong").forEach((element) => (element.textContent = "—"));
  byId("format-chart").innerHTML = chartEmpty("Loading format coverage…");
  byId("component-chart").innerHTML = chartEmpty("Loading component types…");
  try {
    const [overview, runs] = await Promise.all([
      fetchJson("/dashboard/overview", scopeParams()),
      fetchJson("/ingest-runs", {
        source_collection: state.collection,
        limit: 1,
      }),
    ]);
    state.overview = overview;
    state.latestRun = runs[0] || null;
    renderOverview(overview, state.latestRun);
  } catch (error) {
    byId("format-chart").innerHTML = `<div class="error-panel">Could not load overview: ${escapeHtml(error.message)}</div>`;
    byId("component-chart").innerHTML = "";
    toast(`Overview unavailable: ${error.message}`, "error");
  }
}

function renderOverview(overview, latestRun) {
  const counts = overview.counts || {};
  setMetric("metric-documents", counts.unique_documents);
  setMetric("metric-components", counts.unique_components);
  setMetric("metric-occurrences", counts.component_occurrences);
  setMetric("metric-edges", counts.dependency_edges);
  setMetric("metric-files", counts.source_files);
  setMetric("metric-artifacts", counts.artifacts);
  setMetric("metric-evidence", counts.external_records);
  setMetric("metric-errors", counts.ingest_errors);
  byId("metric-errors-card").classList.toggle("has-error", Number(counts.ingest_errors) > 0);

  const formats = overview.format_coverage || [];
  renderBarChart(byId("format-chart"), formats, {
    valueKey: "source_files",
    label: (row) => `${humanize(row.document_kind)} · ${row.format_name || "native"} ${row.spec_version || ""}`.trim(),
    action: "format",
    limit: 8,
  });
  const formatKinds = new Set(formats.map((row) => row.document_kind)).size;
  byId("format-summary").textContent = formats.length
    ? `${formatNumber(formats.reduce((sum, row) => sum + Number(row.source_files || 0), 0))} source-file observations across ${formatNumber(formatKinds)} document kinds. Select a bar to filter the inventory.`
    : "No document formats are available in this scope.";

  renderBarChart(byId("component-chart"), overview.component_types || [], {
    valueKey: "component_occurrences",
    label: (row) => humanize(row.component_type),
    action: "component",
    limit: 8,
  });
  renderServiceGroups(overview.service_groups || []);
  renderRefreshSnapshot(latestRun, counts);
}

function inventoryTypeOptions(entity) {
  if (entity === "documents") {
    return (state.overview?.format_coverage || []).map((row) => ({
      value: `${row.document_kind}|${row.spec_version || ""}`,
      label: `${humanize(row.document_kind)} · ${row.format_name || "native"} ${row.spec_version || ""}`.trim(),
    }));
  }
  if (entity === "components") {
    return (state.overview?.component_types || []).map((row) => ({
      value: row.component_type,
      label: humanize(row.component_type),
    }));
  }
  if (entity === "evidence") {
    return [...new Set(state.inventory.rows.map((row) => row.record_type).filter(Boolean))]
      .sort()
      .map((value) => ({ value, label: humanize(value) }));
  }
  if (entity === "artifacts") {
    return [...new Set(state.inventory.rows.map((row) => row.artifact_type).filter(Boolean))]
      .sort()
      .map((value) => ({ value, label: humanize(value) }));
  }
  return [];
}

function updateInventoryControls() {
  const entity = state.inventory.entity;
  const labels = inventoryLabels[entity];
  byId("inventory-caption").textContent = labels.caption;
  byId("inventory-search-label").textContent = labels.searchLabel;
  byId("inventory-search").placeholder = labels.placeholder;
  byId("inventory-search").value = state.inventory.query;
  byId("inventory-type-label").textContent = labels.typeLabel;
  const options = inventoryTypeOptions(entity);
  const field = byId("inventory-type-field");
  field.hidden = entity === "artifacts" && !options.length;
  const select = byId("inventory-type-filter");
  select.innerHTML = `<option value="">All ${entity === "documents" ? "formats" : "types"}</option>${options
    .map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`)
    .join("")}`;
  if (options.some((option) => option.value === state.inventory.type)) select.value = state.inventory.type;
  else if (state.inventory.type) select.value = state.inventory.type;
}

function inventoryParams() {
  const entity = state.inventory.entity;
  const params = {
    ...scopeParams(),
    limit: PAGE_SIZE,
    offset: state.inventory.offset,
  };
  if (state.inventory.query) {
    if (entity === "documents") params.path_query = state.inventory.query;
    if (entity === "components" || entity === "artifacts") params.query = state.inventory.query;
  }
  if (state.inventory.type) {
    if (entity === "documents") {
      const [kind, version] = state.inventory.type.split("|");
      params.kind = kind;
      if (version) params.spec_version = version;
    }
    if (entity === "components") params.component_type = state.inventory.type;
    if (entity === "evidence") params.record_type = state.inventory.type;
  }
  return params;
}

function inventoryEndpoint(entity) {
  return {
    documents: "/documents",
    components: "/components",
    artifacts: "/artifacts",
    evidence: "/external-records",
  }[entity];
}

function loadingRows(columns = 5) {
  return `<tr><td colspan="${columns}"><span class="skeleton skeleton-line"></span></td></tr>`.repeat(5);
}

async function loadInventory() {
  const request = ++state.inventory.request;
  updateInventoryControls();
  byId("inventory-empty").hidden = true;
  byId("inventory-table-frame").hidden = false;
  byId("inventory-body").innerHTML = loadingRows();
  byId("inventory-result-count").textContent = "Loading…";
  try {
    const needsOverview = !state.overview;
    let [rows, overview] = await Promise.all([
      fetchJson(inventoryEndpoint(state.inventory.entity), inventoryParams()),
      needsOverview ? fetchJson("/dashboard/overview", scopeParams()) : Promise.resolve(state.overview),
    ]);
    if (request !== state.inventory.request) return;
    state.overview = overview;
    if (state.inventory.entity === "evidence" && state.inventory.query) {
      const needle = state.inventory.query.toLowerCase();
      rows = rows.filter((row) =>
        [row.record_type, row.provider, row.artifact_name, row.external_id]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(needle)),
      );
    }
    if (state.inventory.entity === "artifacts" && state.inventory.type) {
      rows = rows.filter((row) => row.artifact_type === state.inventory.type);
    }
    state.inventory.rows = rows;
    updateInventoryControls();
    renderInventory();
  } catch (error) {
    if (request !== state.inventory.request) return;
    byId("inventory-head").innerHTML = "";
    byId("inventory-body").innerHTML = `<tr><td><div class="error-panel">Could not load inventory: ${escapeHtml(error.message)}</div></td></tr>`;
    byId("inventory-result-count").textContent = "Request failed";
    toast(`Inventory unavailable: ${error.message}`, "error");
  }
}

function inventoryColumns(entity) {
  return {
    documents: [
      { key: "source", label: "Source / checksum" },
      { key: "document_kind", label: "Kind" },
      { key: "spec_version", label: "Format" },
      { key: "service_groups", label: "Service scope" },
      { key: "generated_at_text", label: "Generated" },
    ],
    components: [
      { key: "name", label: "Component" },
      { key: "component_type", label: "Type" },
      { key: "canonical_purl", label: "Package identity" },
      { key: "document_count", label: "Documents", numeric: true },
      { key: "service_groups", label: "Service scope" },
    ],
    artifacts: [
      { key: "name", label: "Artifact" },
      { key: "artifact_type", label: "Type" },
      { key: "digest", label: "Registry / digest" },
      { key: "document_count", label: "Documents", numeric: true },
      { key: "service_groups", label: "Service scope" },
    ],
    evidence: [
      { key: "record_type", label: "Evidence type" },
      { key: "provider", label: "Provider" },
      { key: "artifact_name", label: "Artifact" },
      { key: "observed_at_text", label: "Observed" },
      { key: "payload_sha256", label: "Payload fingerprint" },
    ],
  }[entity];
}

function sortValue(row, key, entity) {
  if (key === "source") return first(row.source_paths, "");
  if (key === "service_groups") return first(row.service_groups, "");
  if (key === "spec_version") return `${row.format_name || ""} ${row.spec_version || ""}`;
  const value = row[key];
  if (["document_count"].includes(key)) return Number(value || 0);
  if (entity === "documents" && key === "generated_at_text") return value || "";
  return String(value ?? "").toLowerCase();
}

function sortedInventoryRows() {
  const rows = [...state.inventory.rows];
  const { sortKey, sortDirection, entity } = state.inventory;
  if (!sortKey) return rows;
  const direction = sortDirection === "ascending" ? 1 : -1;
  return rows.sort((a, b) => {
    const left = sortValue(a, sortKey, entity);
    const right = sortValue(b, sortKey, entity);
    if (left < right) return -1 * direction;
    if (left > right) return 1 * direction;
    return 0;
  });
}

function renderInventoryHead(columns) {
  byId("inventory-head").innerHTML = `<tr>${columns
    .map((column) => {
      const active = state.inventory.sortKey === column.key;
      const aria = active ? state.inventory.sortDirection : "none";
      return `<th scope="col" aria-sort="${aria}" class="${column.numeric ? "numeric" : ""}">
        <button class="sort-button" type="button" data-sort="${escapeHtml(column.key)}">${escapeHtml(column.label)}</button>
      </th>`;
    })
    .join("")}</tr>`;
}

function inventoryRow(row, entity) {
  if (entity === "documents") {
    return `<tr>
      <td><button class="row-button" type="button" data-detail="document" data-id="${row.document_id}">
        <span class="cell-main" title="${escapeHtml(first(row.source_paths))}">${escapeHtml(first(row.source_paths))}</span>
        <span class="cell-sub mono">sha256:${escapeHtml(truncate(row.sha256, 20))}</span>
      </button></td>
      <td>${badge(row.document_kind)}</td>
      <td><span class="cell-main">${escapeHtml(row.format_name || "Native")}</span><span class="cell-sub">${escapeHtml(row.spec_version || "Unversioned")}</span></td>
      <td><span class="cell-main">${escapeHtml(first(row.service_groups))}</span><span class="cell-sub">${formatNumber(row.source_alias_count)} source alias${Number(row.source_alias_count) === 1 ? "" : "es"}</span></td>
      <td><span class="cell-main">${escapeHtml(row.generated_at_text || "Not supplied")}</span></td>
    </tr>`;
  }
  if (entity === "components") {
    return `<tr>
      <td><button class="row-button" type="button" data-detail="component" data-id="${row.component_id}">
        <span class="cell-main">${escapeHtml(row.name || "Unnamed component")}</span>
        <span class="cell-sub">${escapeHtml(row.version || "Version not supplied")}</span>
      </button></td>
      <td>${badge(row.component_type)}</td>
      <td><span class="cell-main mono" title="${escapeHtml(row.canonical_purl || row.cpe || "")}">${escapeHtml(row.canonical_purl || row.cpe || "Not supplied")}</span></td>
      <td class="numeric">${formatNumber(row.document_count)}</td>
      <td><span class="cell-main">${escapeHtml(first(row.service_groups))}</span><span class="cell-sub">${formatNumber((row.service_groups || []).length)} scoped group${(row.service_groups || []).length === 1 ? "" : "s"}</span></td>
    </tr>`;
  }
  if (entity === "artifacts") {
    return `<tr>
      <td><button class="row-button" type="button" data-detail="artifact" data-id="${row.id}">
        <span class="cell-main">${escapeHtml(row.name || row.canonical_key)}</span>
        <span class="cell-sub">${escapeHtml(row.version || row.tag || "Version not supplied")}</span>
      </button></td>
      <td>${badge(row.artifact_type)}</td>
      <td><span class="cell-main">${escapeHtml(row.registry || row.repository || "Not supplied")}</span><span class="cell-sub mono">${escapeHtml(truncate(row.digest || row.purl || "", 38))}</span></td>
      <td class="numeric">${formatNumber(row.document_count)}</td>
      <td><span class="cell-main">${escapeHtml(first(row.service_groups))}</span></td>
    </tr>`;
  }
  return `<tr>
    <td><button class="row-button" type="button" data-detail="evidence" data-id="${row.id}">
      <span class="cell-main">${escapeHtml(humanize(row.record_type))}</span>
      <span class="cell-sub">${escapeHtml(row.external_id)}</span>
    </button></td>
    <td><span class="cell-main">${escapeHtml(row.provider || "Not supplied")}</span></td>
    <td><span class="cell-main">${escapeHtml(row.artifact_name || "Unlinked")}</span><span class="cell-sub">${escapeHtml(first(row.service_groups))}</span></td>
    <td>${escapeHtml(row.observed_at_text || "Not supplied")}</td>
    <td><span class="hash" title="${escapeHtml(row.payload_sha256)}">${escapeHtml(row.payload_sha256)}</span></td>
  </tr>`;
}

function renderInventory() {
  const entity = state.inventory.entity;
  const columns = inventoryColumns(entity);
  const rows = sortedInventoryRows();
  renderInventoryHead(columns);
  byId("inventory-body").innerHTML = rows.map((row) => inventoryRow(row, entity)).join("");
  const empty = rows.length === 0;
  byId("inventory-empty").hidden = !empty;
  byId("inventory-table-frame").hidden = empty;
  const start = empty ? 0 : state.inventory.offset + 1;
  const end = state.inventory.offset + rows.length;
  byId("inventory-result-count").textContent = `${formatNumber(rows.length)} rows on this page`;
  byId("inventory-page").textContent = `Rows ${formatNumber(start)}–${formatNumber(end)}`;
  byId("inventory-prev").disabled = state.inventory.offset === 0;
  byId("inventory-next").disabled = state.inventory.rows.length < PAGE_SIZE;
}

function switchInventoryEntity(entity, options = {}) {
  state.inventory.entity = entity;
  state.inventory.query = options.query || "";
  state.inventory.type = options.type || "";
  state.inventory.offset = 0;
  state.inventory.sortKey = "";
  $$('[data-entity]').forEach((button) => {
    const selected = button.dataset.entity === entity;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  showView("inventory", { focus: options.focus, updateHistory: options.updateHistory });
}

function detailDefinition(label, value, classes = "") {
  return `<div><dt>${escapeHtml(label)}</dt><dd class="${classes}">${value ?? "—"}</dd></div>`;
}

function copyLine(value) {
  if (!value) return "Not supplied";
  return `<span class="copy-line"><span class="hash" title="${escapeHtml(value)}">${escapeHtml(value)}</span>
    <button class="copy-button" type="button" data-copy="${escapeHtml(value)}" aria-label="Copy value">
      <svg class="icon icon-sm"><use href="#i-copy"></use></svg>
    </button></span>`;
}

function showDetailDialog(kicker, title, loading = true) {
  byId("detail-kicker").textContent = kicker;
  byId("detail-title").textContent = title;
  byId("detail-body").innerHTML = loading
    ? '<span class="skeleton skeleton-line"></span><br><span class="skeleton skeleton-line short"></span>'
    : "";
  const dialog = byId("detail-dialog");
  if (!dialog.open) dialog.showModal();
}

async function openDetail(type, id) {
  const row = state.inventory.rows.find((item) => String(item.document_id || item.component_id || item.id) === String(id));
  const label = row?.name || row?.artifact_name || first(row?.source_paths, row?.record_type || "Record");
  showDetailDialog(`${humanize(type)} detail`, label || "Record detail");
  try {
    if (type === "document") {
      const detail = await fetchJson(`/documents/${id}`);
      renderDocumentDetail(detail);
    } else if (type === "component") {
      const usage = await fetchJson(`/components/${id}/usage`);
      renderComponentDetail(row, usage);
    } else if (type === "artifact") {
      renderArtifactDetail(row);
    } else {
      renderEvidenceDetail(row);
    }
  } catch (error) {
    byId("detail-body").innerHTML = `<div class="error-panel">Could not load detail: ${escapeHtml(error.message)}</div>`;
  }
}

function renderDocumentDetail(detail) {
  byId("detail-title").textContent = first(detail.source_files?.map((item) => item.source_path), `Document ${detail.id}`);
  byId("detail-body").innerHTML = `
    <section class="detail-section">
      <h3>Identity</h3>
      <dl class="detail-list detail-grid">
        ${detailDefinition("Document ID", escapeHtml(detail.id))}
        ${detailDefinition("Kind", badge(detail.document_kind))}
        ${detailDefinition("Format", escapeHtml(`${detail.format_name || "Native"} ${detail.spec_version || ""}`.trim()))}
        ${detailDefinition("Parser", escapeHtml(detail.parser_version || "Not recorded"))}
        ${detailDefinition("Size", escapeHtml(formatBytes(detail.byte_size)))}
        ${detailDefinition("Generated", escapeHtml(detail.generated_at_text || "Not supplied"))}
      </dl>
      <dl class="detail-list" style="margin-top:.8rem">
        ${detailDefinition("SHA-256", copyLine(detail.sha256))}
        ${detailDefinition("Serial number", escapeHtml(detail.serial_number || "Not supplied"))}
      </dl>
    </section>
    <section class="detail-section">
      <h3>Normalized facts</h3>
      <dl class="detail-list detail-grid">
        ${detailDefinition("Components", formatNumber(detail.component_count))}
        ${detailDefinition("Relationships", formatNumber(detail.dependency_count))}
        ${detailDefinition("Evidence records", formatNumber(detail.external_record_count))}
        ${detailDefinition("Artifact links", formatNumber(detail.artifacts?.length || 0))}
      </dl>
    </section>
    <section class="detail-section">
      <h3>Source provenance</h3>
      ${(detail.source_files || [])
        .map(
          (source) => `<dl class="detail-list" style="margin-bottom:.9rem">
            ${detailDefinition("Collection / service", escapeHtml(`${source.source_collection} / ${source.service_group}`))}
            ${detailDefinition("Path", escapeHtml(source.source_path), "mono")}
            ${detailDefinition("Parse status", badge(source.parse_status, statusTone(source.parse_status)))}
          </dl>`,
        )
        .join("") || "<p>No source path is linked.</p>"}
    </section>
    <section class="detail-section">
      <h3>Artifacts</h3>
      ${(detail.artifacts || [])
        .map(
          (artifact) => `<dl class="detail-list" style="margin-bottom:.9rem">
            ${detailDefinition("Name", escapeHtml(artifact.name || artifact.canonical_key))}
            ${detailDefinition("Role / confidence", escapeHtml(`${artifact.role} · ${artifact.confidence}`))}
            ${detailDefinition("Digest", copyLine(artifact.digest))}
          </dl>`,
        )
        .join("") || "<p>No artifact identity was linked to this document.</p>"}
    </section>`;
}

function renderComponentDetail(component, usage) {
  byId("detail-title").textContent = component?.name || "Component";
  byId("detail-body").innerHTML = `
    <section class="detail-section">
      <h3>Canonical identity</h3>
      <dl class="detail-list">
        ${detailDefinition("Name / version", escapeHtml(`${component?.name || "Unknown"}${component?.version ? ` @ ${component.version}` : ""}`))}
        ${detailDefinition("Type", badge(component?.component_type))}
        ${detailDefinition("PURL", copyLine(component?.canonical_purl))}
        ${detailDefinition("CPE", copyLine(component?.cpe))}
      </dl>
    </section>
    <section class="detail-section">
      <h3>Document usage <span class="quiet-label">${formatNumber(usage.length)} occurrences</span></h3>
      ${usage
        .map(
          (item) => `<dl class="detail-list" style="margin-bottom:1rem">
            ${detailDefinition("Document", escapeHtml(`${item.document_kind} ${item.spec_version || ""} · #${item.document_id}`))}
            ${detailDefinition("BOM reference", copyLine(item.bom_ref))}
            ${detailDefinition("Scope", escapeHtml(item.scope || "Not supplied"))}
            ${detailDefinition("Service scope", escapeHtml((item.service_groups || []).join(", ")))}
          </dl>`,
        )
        .join("") || "<p>No document usage was returned.</p>"}
    </section>`;
}

function renderArtifactDetail(artifact) {
  byId("detail-title").textContent = artifact?.name || artifact?.canonical_key || "Artifact";
  byId("detail-body").innerHTML = `
    <section class="detail-section"><h3>Artifact identity</h3><dl class="detail-list">
      ${detailDefinition("Canonical key", copyLine(artifact?.canonical_key))}
      ${detailDefinition("Type", badge(artifact?.artifact_type))}
      ${detailDefinition("Version / tag", escapeHtml(artifact?.version || artifact?.tag || "Not supplied"))}
      ${detailDefinition("Registry", escapeHtml(artifact?.registry || "Not supplied"))}
      ${detailDefinition("Repository", escapeHtml(artifact?.repository || "Not supplied"))}
      ${detailDefinition("Digest", copyLine(artifact?.digest))}
      ${detailDefinition("PURL", copyLine(artifact?.purl))}
      ${detailDefinition("Documents", formatNumber(artifact?.document_count))}
      ${detailDefinition("Service scope", escapeHtml((artifact?.service_groups || []).join(", ")))}
    </dl></section>`;
}

function renderEvidenceDetail(record) {
  byId("detail-title").textContent = humanize(record?.record_type || "Evidence record");
  byId("detail-body").innerHTML = `
    <section class="detail-section"><h3>Observation</h3><dl class="detail-list">
      ${detailDefinition("External ID", escapeHtml(record?.external_id || "Not supplied"))}
      ${detailDefinition("Provider", escapeHtml(record?.provider || "Not supplied"))}
      ${detailDefinition("Observed", escapeHtml(record?.observed_at_text || "Not supplied"))}
      ${detailDefinition("Artifact", escapeHtml(record?.artifact_name || "Unlinked"))}
      ${detailDefinition("Payload SHA-256", copyLine(record?.payload_sha256))}
      ${detailDefinition("Parent record", escapeHtml(record?.parent_external_id || "None"))}
    </dl></section>
    <section class="detail-section"><h3>Preserved payload</h3>
      <pre class="detail-code">${escapeHtml(JSON.stringify(record?.data ?? {}, null, 2))}</pre>
    </section>`;
}

async function loadDependencyDocuments(force = false) {
  if (state.graph.documents.length && !force) {
    populateGraphDocuments();
    if (!state.graph.data) loadGraph();
    return;
  }
  const request = ++state.graph.request;
  const select = byId("graph-document");
  select.innerHTML = '<option value="">Loading dependency-bearing documents…</option>';
  select.disabled = true;
  try {
    const documents = await fetchJson("/dependency-documents", {
      ...scopeParams(),
      limit: 100,
    });
    if (request !== state.graph.request) return;
    state.graph.documents = documents;
    state.graph.data = null;
    populateGraphDocuments();
    if (documents.length) loadGraph();
    else renderGraphEmpty("No dependency data supplied in this scope", "Choose another collection or service group.");
  } catch (error) {
    select.innerHTML = '<option value="">Could not load documents</option>';
    renderGraphEmpty("Dependency documents unavailable", error.message);
    toast(`Dependency explorer unavailable: ${error.message}`, "error");
  }
}

function populateGraphDocuments() {
  const select = byId("graph-document");
  const current = select.value;
  if (!state.graph.documents.length) {
    select.innerHTML = '<option value="">No dependency-bearing documents</option>';
    select.disabled = true;
    updateGraphRelationshipOptions(null);
    return;
  }
  select.disabled = false;
  select.innerHTML = state.graph.documents
    .map((document) => {
      const path = first(document.source_paths, `Document ${document.document_id}`);
      return `<option value="${document.document_id}">${escapeHtml(truncate(path, 74))} · ${formatNumber(document.dependency_edges)} edges</option>`;
    })
    .join("");
  if (state.graph.documents.some((document) => String(document.document_id) === current)) {
    select.value = current;
  }
  const document = state.graph.documents.find((item) => String(item.document_id) === select.value);
  updateGraphRelationshipOptions(document);
}

function updateGraphRelationshipOptions(document) {
  const select = byId("graph-relationship");
  const types = document?.relationship_types?.length ? document.relationship_types : ["DEPENDS_ON"];
  const prior = select.value;
  select.innerHTML = types.map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`).join("");
  if (types.includes(prior)) select.value = prior;
}

function renderGraphEmpty(title, detail) {
  byId("graph-empty").hidden = false;
  byId("graph-empty").innerHTML = `<svg class="icon icon-xl"><use href="#i-graph"></use></svg><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span>`;
  byId("dependency-graph").innerHTML = "";
  byId("edge-table-body").innerHTML = "";
  byId("graph-title").textContent = title;
  byId("graph-description").textContent = detail;
  byId("graph-stats").innerHTML = "<span><strong>0</strong> nodes shown</span><span><strong>0</strong> edges shown</span>";
  renderNodeInspector(null);
}

async function loadGraph() {
  const documentId = byId("graph-document").value;
  if (!documentId) return;
  const request = ++state.graph.request;
  state.graph.data = null;
  byId("load-graph").disabled = true;
  byId("load-graph").textContent = "Rendering…";
  renderGraphEmpty("Loading dependency graph", "Resolving component labels and typed edges…");
  try {
    const data = await fetchJson(`/documents/${documentId}/dependency-graph`, {
      relationship_type: byId("graph-relationship").value,
      node_limit: byId("graph-node-limit").value,
      edge_limit: 500,
    });
    if (request !== state.graph.request) return;
    state.graph.data = data;
    state.graph.selectedRef = data.nodes.find((node) => node.is_subject)?.ref || data.nodes[0]?.ref || "";
    renderGraph(data);
  } catch (error) {
    renderGraphEmpty("Could not render this graph", error.message);
    toast(`Graph request failed: ${error.message}`, "error");
  } finally {
    if (request === state.graph.request) {
      byId("load-graph").disabled = false;
      byId("load-graph").textContent = "Render graph";
    }
  }
}

function graphLayout(nodes, edges) {
  const incoming = new Map(nodes.map((node) => [node.ref, 0]));
  const outgoing = new Map(nodes.map((node) => [node.ref, []]));
  edges.forEach((edge) => {
    incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1);
    outgoing.get(edge.source)?.push(edge.target);
  });
  let roots = nodes.filter((node) => node.is_subject || incoming.get(node.ref) === 0);
  if (!roots.length && nodes.length) roots = [nodes[0]];
  const levels = new Map();
  const queue = roots.map((node) => [node.ref, 0]);
  while (queue.length) {
    const [ref, level] = queue.shift();
    if (levels.has(ref) && levels.get(ref) <= level) continue;
    levels.set(ref, Math.min(level, 7));
    (outgoing.get(ref) || []).forEach((target) => {
      if (!levels.has(target)) queue.push([target, level + 1]);
    });
  }
  nodes.forEach((node, index) => {
    if (!levels.has(node.ref)) levels.set(node.ref, Math.min(1 + (index % 7), 7));
  });
  const groups = new Map();
  nodes.forEach((node) => {
    const level = levels.get(node.ref);
    if (!groups.has(level)) groups.set(level, []);
    groups.get(level).push(node);
  });
  const width = Math.max(960, (Math.max(...groups.keys(), 0) + 1) * 215 + 80);
  const largestGroup = Math.max(...[...groups.values()].map((group) => group.length), 1);
  const height = Math.max(520, largestGroup * 78 + 80);
  const positions = new Map();
  [...groups.entries()]
    .sort(([left], [right]) => left - right)
    .forEach(([level, group]) => {
      group.forEach((node, index) => {
        positions.set(node.ref, {
          x: 42 + level * 215,
          y: 38 + index * 78,
        });
      });
    });
  return { width, height, positions };
}

function graphPath(source, target) {
  const startX = source.x + 174;
  const startY = source.y + 26;
  const endX = target.x;
  const endY = target.y + 26;
  if (endX > startX) {
    const curve = Math.max(35, (endX - startX) * 0.48);
    return `M${startX},${startY} C${startX + curve},${startY} ${endX - curve},${endY} ${endX},${endY}`;
  }
  const offset = Math.max(36, Math.abs(endY - startY) * 0.35 + 28);
  return `M${startX},${startY} C${startX + offset},${startY} ${endX - offset},${endY} ${endX},${endY}`;
}

function renderGraph(data) {
  if (!data.nodes.length) {
    renderGraphEmpty("No matching edges", "Try another relationship type or document.");
    return;
  }
  byId("graph-empty").hidden = true;
  const path = first(data.document.source_paths, `Document ${data.document.document_id}`);
  byId("graph-title").textContent = truncate(path, 90);
  const summary = data.summary;
  byId("graph-description").textContent = `${formatNumber(summary.shown_nodes)} of ${formatNumber(summary.total_nodes)} nodes and ${formatNumber(summary.shown_edges)} of ${formatNumber(summary.total_edges)} edges are shown for ${data.relationship_types.join(", ")}.`;
  byId("graph-stats").innerHTML = `
    <span><strong>${formatNumber(summary.shown_nodes)}</strong> of ${formatNumber(summary.total_nodes)} nodes shown</span>
    <span><strong>${formatNumber(summary.shown_edges)}</strong> of ${formatNumber(summary.total_edges)} edges shown</span>
    <span><strong>${escapeHtml(data.relationship_types.join(", "))}</strong> relationship</span>
    ${summary.truncated ? '<span class="status-badge status-warning">Rendering capped</span>' : '<span class="status-badge status-good">Complete rendering</span>'}`;

  const { width, height, positions } = graphLayout(data.nodes, data.edges);
  const svg = byId("dependency-graph");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.style.width = `${Math.max(width, 960)}px`;
  const edges = data.edges
    .map((edge) => {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      if (!source || !target) return "";
      return `<path class="graph-edge is-${escapeHtml(edge.resolution_status)}" data-edge-source="${escapeHtml(edge.source)}" data-edge-target="${escapeHtml(edge.target)}" d="${graphPath(source, target)}"><title>${escapeHtml(`${edge.source} ${edge.relationship_type} ${edge.target} · ${edge.resolution_status}`)}</title></path>`;
    })
    .join("");
  const nodes = data.nodes
    .map((node) => {
      const position = positions.get(node.ref);
      const classes = ["graph-node", node.is_subject ? "is-subject" : "", !node.resolved ? "is-external" : ""]
        .filter(Boolean)
        .join(" ");
      return `<g class="${classes}" data-node-ref="${escapeHtml(node.ref)}" transform="translate(${position.x} ${position.y})"
        tabindex="${node.ref === state.graph.selectedRef ? "0" : "-1"}" role="button"
        aria-label="${escapeHtml(`${node.label}; ${node.component_type}; ${node.resolved ? "resolved" : "unresolved"}`)}">
        <rect width="174" height="52"></rect>
        <text class="node-title" x="10" y="21">${escapeHtml(truncate(node.label, 24))}</text>
        <text class="node-meta" x="10" y="39">${escapeHtml(`${humanize(node.component_type)}${node.is_subject ? " · subject" : ""}`)}</text>
      </g>`;
    })
    .join("");
  svg.innerHTML = `<defs><marker id="arrowhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="var(--graph-edge)"></path></marker></defs>${edges}${nodes}`;
  selectGraphNode(state.graph.selectedRef, false);
}

function selectGraphNode(ref, moveFocus = false) {
  const data = state.graph.data;
  if (!data || !data.nodes.some((node) => node.ref === ref)) return;
  state.graph.selectedRef = ref;
  $$(".graph-node", byId("dependency-graph")).forEach((node) => {
    const selected = node.dataset.nodeRef === ref;
    node.classList.toggle("is-selected", selected);
    node.tabIndex = selected ? 0 : -1;
    if (selected && moveFocus) node.focus();
  });
  $$(".graph-edge", byId("dependency-graph")).forEach((edge) => {
    edge.classList.toggle(
      "is-selected",
      edge.dataset.edgeSource === ref || edge.dataset.edgeTarget === ref,
    );
  });
  const node = data.nodes.find((candidate) => candidate.ref === ref);
  renderNodeInspector(node);
  renderEdgeTable(data, ref);
}

function renderNodeInspector(node) {
  const title = byId("node-inspector-title");
  const body = byId("node-inspector-body");
  const hasGraph = Boolean(state.graph.data?.nodes?.length);
  byId("node-prev").disabled = !hasGraph;
  byId("node-next").disabled = !hasGraph;
  if (!node) {
    title.textContent = "Nothing selected";
    body.className = "inspector-empty";
    body.textContent = "Select a node in the graph or an edge in the table to inspect its identity.";
    return;
  }
  title.textContent = truncate(node.label, 34);
  body.className = "";
  const connected = state.graph.data.edges.filter((edge) => edge.source === node.ref || edge.target === node.ref);
  body.innerHTML = `<dl class="detail-list">
    ${detailDefinition("BOM reference", copyLine(node.ref))}
    ${detailDefinition("Component type", badge(node.component_type))}
    ${detailDefinition("Resolution", badge(node.resolved ? "resolved" : "external", node.resolved ? "good" : "warning"))}
    ${detailDefinition("Role", escapeHtml(node.is_subject ? "Document subject" : "Dependency node"))}
    ${detailDefinition("Connected edges", formatNumber(connected.length))}
    ${detailDefinition("PURL", copyLine(node.purl))}
  </dl>`;
}

function graphNodeLabel(ref) {
  return state.graph.data?.nodes.find((node) => node.ref === ref)?.label || ref;
}

function renderEdgeTable(data, selectedRef = "") {
  const connected = selectedRef
    ? data.edges.filter((edge) => edge.source === selectedRef || edge.target === selectedRef).length
    : 0;
  byId("edge-filter-label").textContent = selectedRef
    ? `${formatNumber(connected)} connected · ${formatNumber(data.edges.length)} total`
    : `${formatNumber(data.edges.length)} edges`;
  byId("edge-table-body").innerHTML = data.edges
    .map((edge) => {
      const selected = selectedRef && (edge.source === selectedRef || edge.target === selectedRef);
      return `<tr class="edge-row${selected ? " is-selected" : ""}" tabindex="0" data-edge-source="${escapeHtml(edge.source)}" data-edge-target="${escapeHtml(edge.target)}">
        <td><span class="cell-main">${escapeHtml(graphNodeLabel(edge.source))}</span><span class="cell-sub mono">${escapeHtml(truncate(edge.source, 48))}</span></td>
        <td>${badge(edge.relationship_type)}</td>
        <td><span class="cell-main">${escapeHtml(graphNodeLabel(edge.target))}</span><span class="cell-sub mono">${escapeHtml(truncate(edge.target, 48))}</span></td>
        <td>${badge(edge.resolution_status, statusTone(edge.resolution_status))}</td>
      </tr>`;
    })
    .join("");
}

function moveGraphSelection(delta) {
  const nodes = state.graph.data?.nodes || [];
  if (!nodes.length) return;
  const current = Math.max(0, nodes.findIndex((node) => node.ref === state.graph.selectedRef));
  const next = (current + delta + nodes.length) % nodes.length;
  selectGraphNode(nodes[next].ref, true);
}

function fipsEvidenceSummary(finding) {
  const evidence = Array.isArray(finding.evidence) ? finding.evidence : [];
  if (!evidence.length) return "No normalized evidence reference";
  return evidence
    .slice(0, 2)
    .map((item) => item.property_name || item.evidence_kind || "Evidence record")
    .join(" · ");
}

function fipsServiceRows(rows) {
  if (!rows.length) {
    return `<tr><td colspan="5"><div class="empty-state" style="min-height:10rem"><p>No service-group rollups are available for this scope.</p></div></td></tr>`;
  }
  return rows.map((row) => {
    const coverageDetail = Number(row.documents || 0)
      ? `${formatNumber(row.documents_with_fips_evidence)} with signals · ${formatNumber(row.documents_without_fips_evidence)} without`
      : Number(row.source_files || 0)
        ? `${formatNumber(row.source_files)} source file(s) · no parsed documents`
        : "No catalog documents — evidence request required";
    return `<tr>
    <td><span class="cell-main mono">${escapeHtml(row.service)}</span></td>
    <td class="numeric">${formatNumber(row.documents)}</td>
    <td><span class="cell-main">${escapeHtml(`${Number(row.evidence_coverage_percent || 0).toFixed(1)}%`)}</span><span class="cell-sub">${escapeHtml(coverageDetail)}</span></td>
    <td class="numeric">${formatNumber(row.poam_candidate_findings)}</td>
    <td class="numeric">${formatNumber(row.needs_review_findings)}</td>
  </tr>`;
  }).join("");
}

function fipsFindingRows(rows) {
  if (!rows.length) {
    return `<tr><td colspan="6"><div class="empty-state" style="min-height:13rem"><svg class="icon icon-xl"><use href="#i-shield"></use></svg><h3>No candidate findings</h3><p>This scope has no findings under the configured evidence rules.</p></div></td></tr>`;
  }
  return rows.map((finding) => `<tr>
    <td><button class="row-button" type="button" data-fips-finding="${escapeHtml(finding.finding_id)}">
      <span class="cell-main mono">${escapeHtml(finding.finding_id)}</span><span class="cell-sub">${escapeHtml(finding.title)} · inspect evidence</span>
    </button></td>
    <td><span class="cell-main" title="${escapeHtml(finding.subject_identity)}">${escapeHtml(finding.subject_name)}</span><span class="cell-sub mono">${escapeHtml(truncate(finding.subject_identity, 52))}</span></td>
    <td>${badge(finding.assertion_state, finding.poam_eligible ? "warning" : "")}</td>
    <td><span class="cell-main">${formatNumber((finding.affected_services || []).length)}</span><span class="cell-sub">${escapeHtml((finding.affected_services || []).join(", ") || "Scope not resolved")}</span></td>
    <td><span class="cell-main">${escapeHtml(fipsEvidenceSummary(finding))}</span><span class="cell-sub">${formatNumber((finding.evidence || []).length)} reference(s)</span></td>
    <td>${badge(finding.proposed_risk, finding.poam_eligible ? "warning" : "")}</td>
  </tr>`).join("");
}

function fipsPoamRows(rows) {
  if (!rows.length) {
    return `<tr><td colspan="5"><div class="empty-state" style="min-height:13rem"><svg class="icon icon-xl"><use href="#i-file"></use></svg><h3>No draft POA&amp;M candidates</h3><p>Evidence-review findings remain visible on the Assessment tab and are not exported as POA&amp;M rows.</p></div></td></tr>`;
  }
  return rows.map((item) => `<tr>
    <td><button class="row-button" type="button" data-fips-poam="${escapeHtml(item.poam_candidate_id)}">
      <span class="cell-main mono">${escapeHtml(item.poam_candidate_id)}</span><span class="cell-sub">${escapeHtml(item.status)} · inspect draft</span>
    </button></td>
    <td><span class="cell-main">${escapeHtml(item.title)}</span><span class="cell-sub" title="${escapeHtml(item.remediation_plan)}">${escapeHtml(truncate(item.remediation_plan, 110))}</span></td>
    <td><span class="cell-main">${formatNumber(item.affected_service_count)}</span><span class="cell-sub">${escapeHtml((item.affected_services || []).join(", ") || "Scope not resolved")}</span></td>
    <td><span class="cell-main">${formatNumber((item.source_paths || []).length)} source file(s)</span><span class="cell-sub mono">${escapeHtml(truncate((item.evidence_sha256 || []).join(", ") || "No evidence hash", 54))}</span></td>
    <td>${badge(item.proposed_risk, "warning")}<span class="cell-sub">Authorized review required</span></td>
  </tr>`).join("");
}

function filteredFipsFindings() {
  const rows = state.fips.data?.findings || [];
  const query = state.fips.query.toLowerCase();
  return rows.filter((finding) => {
    if (state.fips.filter === "candidate" && !finding.poam_eligible) return false;
    if (state.fips.filter === "review" && finding.poam_eligible) return false;
    if (state.fips.filter.startsWith("FIPS1403-") && finding.rule_id !== state.fips.filter) return false;
    if (!query) return true;
    return [
      finding.finding_id,
      finding.rule_id,
      finding.gap_code,
      finding.title,
      finding.subject_name,
      finding.subject_identity,
      ...(finding.affected_services || []),
    ].some((value) => String(value || "").toLowerCase().includes(query));
  });
}

function renderFipsFindingTable() {
  const matching = filteredFipsFindings();
  const visible = matching.slice(0, FIPS_RESULT_LIMIT);
  byId("fips-findings-body").innerHTML = fipsFindingRows(visible);
  const total = state.fips.data?.findings?.length || 0;
  const suffix = matching.length > visible.length ? ` · first ${formatNumber(visible.length)} shown` : "";
  byId("fips-findings-count").textContent = `${formatNumber(matching.length)} matching of ${formatNumber(total)}${suffix}`;
}

function renderFipsFindingDetail(finding) {
  showDetailDialog("FIPS candidate finding", finding.finding_id, false);
  const services = (finding.affected_services || []).join(", ") || "Scope not resolved";
  const scopes = (finding.scopes || []).map((scope) => `<dl class="detail-list" style="margin-bottom:.9rem">
    ${detailDefinition("Collection / service", escapeHtml(`${scope.source_collection || "Unknown"} / ${scope.service_group || "Unknown"}`))}
    ${detailDefinition("Source path", escapeHtml(scope.source_path || "Not supplied"), "mono")}
    ${detailDefinition("Source SHA-256", copyLine(scope.source_sha256))}
  </dl>`).join("");
  const evidence = (finding.evidence || []).map((item) => `<dl class="detail-list" style="margin-bottom:.9rem">
    ${detailDefinition("Kind", badge(item.evidence_kind))}
    ${detailDefinition("Property", escapeHtml(item.property_name || "Not supplied"), "mono")}
    ${detailDefinition("Observed value", escapeHtml(item.property_value ?? "Not supplied"))}
    ${detailDefinition("Evidence SHA-256", copyLine(item.evidence_sha256))}
    ${detailDefinition("Observed", escapeHtml(item.observed_at || "Not supplied"))}
  </dl>`).join("");
  byId("detail-body").innerHTML = `
    <section class="detail-section"><h3>Assessment</h3><dl class="detail-list">
      ${detailDefinition("Rule", escapeHtml(`${finding.rule_id} · ${finding.gap_code}`))}
      ${detailDefinition("State", badge(finding.assertion_state, finding.poam_eligible ? "warning" : ""))}
      ${detailDefinition("Subject", escapeHtml(finding.subject_name || "Unresolved"))}
      ${detailDefinition("Subject identity", copyLine(finding.subject_identity))}
      ${detailDefinition("Affected services", escapeHtml(services))}
      ${detailDefinition("Proposed risk", escapeHtml(finding.proposed_risk || "To be determined"))}
      ${detailDefinition("POA&M eligible", escapeHtml(finding.poam_eligible ? "Draft candidate after authorized review" : "No — evidence review only"))}
    </dl></section>
    <section class="detail-section"><h3>Weakness</h3><p>${escapeHtml(finding.weakness)}</p><h3>Risk rationale</h3><p>${escapeHtml(finding.risk_rationale)}</p><h3>Proposed remediation</h3><p>${escapeHtml(finding.remediation)}</p></section>
    <section class="detail-section"><h3>Normalized evidence <span class="quiet-label">${formatNumber((finding.evidence || []).length)} references</span></h3>${evidence || "<p>No evidence references were returned.</p>"}</section>
    <section class="detail-section"><h3>Source provenance</h3>${scopes || "<p>No source scope was returned.</p>"}</section>`;
}

function renderFipsPoamDetail(item) {
  showDetailDialog("Draft POA&M candidate", item.poam_candidate_id, false);
  const sourceRows = (item.source_paths || []).map((path) => `<dl class="detail-list" style="margin-bottom:.9rem">
    ${detailDefinition("Source path", escapeHtml(path), "mono")}
  </dl>`).join("");
  const sourceHashes = (item.source_sha256 || []).map((hash) => `<dl class="detail-list" style="margin-bottom:.9rem">
    ${detailDefinition("Source SHA-256", copyLine(hash))}
  </dl>`).join("");
  byId("detail-body").innerHTML = `
    <section class="detail-section"><h3>Review gate</h3><dl class="detail-list">
      ${detailDefinition("Status", badge(item.status, "warning"))}
      ${detailDefinition("ATO boundary", escapeHtml(item.ato_boundary || "Unassigned — review required"))}
      ${detailDefinition("Control", escapeHtml(item.control_id || "SC-13"))}
      ${detailDefinition("Proposed risk", badge(item.proposed_risk, "warning"))}
      ${detailDefinition("Responsible owner", escapeHtml(item.responsible_owner || "Unassigned"))}
      ${detailDefinition("Affected services", escapeHtml((item.affected_services || []).join(", ") || "Scope not resolved"))}
      ${detailDefinition("Linked findings", escapeHtml((item.linked_finding_ids || []).join(", ") || "None"))}
      ${detailDefinition("Dedupe key", copyLine(item.dedupe_key))}
    </dl></section>
    <section class="detail-section"><h3>Draft content</h3><p><strong>${escapeHtml(item.title)}</strong></p><p>${escapeHtml(item.weakness)}</p><h3>Remediation plan</h3><p>${escapeHtml(item.remediation_plan)}</p><h3>Planned milestone</h3><p>${escapeHtml(item.planned_milestone)}</p></section>
    <section class="detail-section"><h3>Dedupe boundary</h3><p>${escapeHtml(item.dedupe_scope_basis || "Confirm the ATO boundary before accepting consolidation.")}</p></section>
    <section class="detail-section"><h3>Source provenance</h3>${sourceRows || "<p>No source path was returned.</p>"}${sourceHashes}</section>`;
}

function renderFipsAssessment(data) {
  const summary = data.summary || {};
  const policy = data.policy || {};
  const total = Number(summary.documents_in_scope || 0);
  const evidence = Number(summary.documents_with_fips_evidence || 0);
  const coverage = total ? (evidence / total) * 100 : 0;
  setMetric("fips-poam-count", summary.deduplicated_poam_candidates);
  setMetric("fips-review-count", summary.needs_review_findings);
  setMetric("fips-service-count", summary.affected_services);
  byId("fips-coverage-count").textContent = total ? `${coverage.toFixed(coverage === 100 ? 0 : 1)}%` : "—";
  byId("fips-coverage-caption").textContent = `${formatNumber(evidence)} of ${formatNumber(total)} documents with FIPS-related catalog evidence`;

  const days = Number(policy.days_until_historical);
  const historic = policy.historical_effective_date || "2026-09-22";
  const lastNew = policy.last_new_system_date || "2026-09-21";
  byId("fips-deadline-copy").textContent = `Last active day for new-system use: ${lastNew}. Historical-list effective date: ${historic}.`;
  byId("fips-deadline-count").textContent = Number.isFinite(days)
    ? (days >= 0 ? `${days} day${days === 1 ? "" : "s"}` : `${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"} past`)
    : "Review date";
  byId("fips-disclaimer").textContent = data.disclaimer || "Candidate output only; authorized assessor review is required.";
  byId("fips-service-body").innerHTML = fipsServiceRows(data.service_groups || []);
  byId("fips-poam-body").innerHTML = fipsPoamRows(data.poam_items || []);
  renderFipsFindingTable();
  byId("fips-export").href = buildUrl("/fips/poam.csv", scopeParams()).toString();

  const sources = (policy.authoritative_sources || []).map((source) => source.authority).filter(Boolean);
  byId("fips-boundary").innerHTML = `
    <p><strong>Primary control:</strong> SC-13. SC-8(1) and SC-28(1) are conditional on the affected data flow or store.</p>
    <p><strong>Assessment date:</strong> ${escapeHtml(policy.assessment_date || "Not recorded")} (${escapeHtml(policy.assessment_timezone || "UTC")})</p>
    <p><strong>Evidence sources:</strong> ${escapeHtml([...new Set(sources)].join(" · ") || "Not recorded")}</p>
    <p class="quiet-copy">A component, version, image tag, FIPS label, or FIPS-mode signal cannot establish a CMVP deployment match by itself.</p>`;
  applyFipsTab();
}

function applyFipsTab() {
  const poam = state.fips.tab === "poam";
  byId("fips-assessment-panel").hidden = poam;
  byId("fips-poam-panel").hidden = !poam;
  $$('[data-fips-tab]').forEach((button) => {
    const selected = button.dataset.fipsTab === state.fips.tab;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
}

async function loadFipsAssessment(force = false) {
  if (state.fips.data && !force) {
    renderFipsAssessment(state.fips.data);
    return;
  }
  const request = ++state.fips.request;
  byId("fips-service-body").innerHTML = loadingRows(5);
  byId("fips-findings-body").innerHTML = loadingRows(6);
  byId("fips-poam-body").innerHTML = loadingRows(5);
  byId("fips-findings-count").textContent = "Loading…";
  try {
    const data = await fetchJson("/fips/assessment", {
      ...scopeParams(),
      include_findings: true,
      poam_limit: 250,
    });
    if (request !== state.fips.request) return;
    state.fips.data = data;
    renderFipsAssessment(data);
  } catch (error) {
    if (request !== state.fips.request) return;
    const message = `Could not load the FIPS assessment: ${escapeHtml(error.message)}`;
    byId("fips-service-body").innerHTML = `<tr><td colspan="5"><div class="error-panel">${message}</div></td></tr>`;
    byId("fips-findings-body").innerHTML = `<tr><td colspan="6"><div class="error-panel">${message}</div></td></tr>`;
    byId("fips-poam-body").innerHTML = `<tr><td colspan="5"><div class="error-panel">${message}</div></td></tr>`;
    byId("fips-findings-count").textContent = "Request failed";
    toast(`FIPS assessment unavailable: ${error.message}`, "error");
  }
}

function integrityEndpoint(entity) {
  return { fingerprints: "/fingerprints", runs: "/ingest-runs", issues: "/issues" }[entity];
}

function integrityParams() {
  const entity = state.integrity.entity;
  const params = { limit: 100, ...scopeParams() };
  if (entity === "runs") delete params.service_group;
  if (state.integrity.query && (entity === "fingerprints" || entity === "issues")) {
    params.path_query = state.integrity.query;
  }
  return params;
}

async function loadIntegrity() {
  const request = ++state.integrity.request;
  byId("integrity-body").innerHTML = loadingRows(7);
  byId("integrity-result-count").textContent = "Loading…";
  try {
    const needsSummary = !state.overview;
    const [rows, overview, runs] = await Promise.all([
      fetchJson(integrityEndpoint(state.integrity.entity), integrityParams()),
      needsSummary ? fetchJson("/dashboard/overview", scopeParams()) : Promise.resolve(state.overview),
      fetchJson("/ingest-runs", { source_collection: state.collection, limit: 1 }),
    ]);
    if (request !== state.integrity.request) return;
    state.overview = overview;
    state.latestRun = runs[0] || null;
    state.integrity.rows = filterIntegrityRows(rows);
    renderIntegritySummary(overview.counts || {}, state.latestRun);
    renderIntegrity();
  } catch (error) {
    if (request !== state.integrity.request) return;
    byId("integrity-head").innerHTML = "";
    byId("integrity-body").innerHTML = `<tr><td><div class="error-panel">Could not load integrity data: ${escapeHtml(error.message)}</div></td></tr>`;
    byId("integrity-result-count").textContent = "Request failed";
    toast(`Integrity view unavailable: ${error.message}`, "error");
  }
}

function filterIntegrityRows(rows) {
  if (!state.integrity.query || state.integrity.entity !== "runs") return rows;
  const needle = state.integrity.query.toLowerCase();
  return rows.filter((row) =>
    [row.status, row.root_path, row.parser_version, row.id]
      .filter((value) => value !== null && value !== undefined)
      .some((value) => String(value).toLowerCase().includes(needle)),
  );
}

function renderIntegritySummary(counts, run) {
  const files = Number(counts.source_files || 0);
  const coverage = files ? (Number(counts.fingerprinted_source_files || 0) / files) * 100 : 0;
  byId("integrity-coverage").textContent = `${coverage.toFixed(coverage === 100 ? 0 : 1)}%`;
  byId("integrity-versions").textContent = formatNumber(counts.fingerprint_versions);
  byId("integrity-unchanged").textContent = run ? formatNumber(run.files_unchanged) : "—";
  byId("integrity-failed").textContent = run ? formatNumber(run.files_failed) : "—";
}

function renderIntegrity() {
  const entity = state.integrity.entity;
  const rows = state.integrity.rows;
  const configurations = {
    fingerprints: {
      caption: "Source fingerprints",
      search: "Filter source path",
      columns: ["Source path", "Parse state", "Current SHA-256", "Size", "Versions", "Last verified"],
      row: (item) => `<tr>
        <td><span class="cell-main">${escapeHtml(item.source_path)}</span><span class="cell-sub">${escapeHtml(`${item.source_collection} / ${item.service_group}`)}</span></td>
        <td>${badge(item.parse_status, statusTone(item.parse_status))}</td>
        <td><span class="hash" title="${escapeHtml(item.current_checksum)}">${escapeHtml(item.current_checksum || "Not fingerprinted")}</span></td>
        <td>${escapeHtml(formatBytes(item.byte_size))}</td>
        <td class="numeric"><span class="cell-main">${formatNumber(item.fingerprint_versions)}</span><span class="cell-sub">${formatNumber(item.verification_observations)} observations</span></td>
        <td>${escapeHtml(formatDate(item.last_verified_at))}</td>
      </tr>`,
    },
    runs: {
      caption: "Catalog refresh runs",
      search: "Filter run status or path",
      columns: ["Run", "Status", "Seen", "Loaded", "Linked", "Unchanged", "Failed", "Completed"],
      row: (item) => `<tr>
        <td><span class="cell-main">Run ${escapeHtml(item.id)}</span><span class="cell-sub">${escapeHtml(item.parser_version)}</span></td>
        <td>${badge(item.status, statusTone(item.status))}</td>
        <td class="numeric">${formatNumber(item.files_seen)}</td>
        <td class="numeric">${formatNumber(item.files_loaded)}</td>
        <td class="numeric">${formatNumber(item.files_linked)}</td>
        <td class="numeric">${formatNumber(item.files_unchanged)}</td>
        <td class="numeric">${formatNumber(item.files_failed)}</td>
        <td>${escapeHtml(formatDate(item.completed_at))}</td>
      </tr>`,
    },
    issues: {
      caption: "Parser and ingestion quality issues",
      search: "Filter source path",
      columns: ["Severity", "Issue", "Source path", "Message", "Recorded"],
      row: (item) => `<tr>
        <td>${badge(item.severity, statusTone(item.severity))}</td>
        <td><span class="cell-main mono">${escapeHtml(item.issue_code)}</span></td>
        <td><span class="cell-main">${escapeHtml(item.source_path || "Run-level issue")}</span></td>
        <td><span class="cell-main" title="${escapeHtml(item.message)}">${escapeHtml(item.message)}</span></td>
        <td>${escapeHtml(formatDate(item.created_at))}</td>
      </tr>`,
    },
  };
  const config = configurations[entity];
  byId("integrity-caption").textContent = config.caption;
  byId("integrity-search-label").textContent = config.search;
  byId("integrity-head").innerHTML = `<tr>${config.columns
    .map((column) => `<th scope="col">${escapeHtml(column)}</th>`)
    .join("")}</tr>`;
  byId("integrity-body").innerHTML = rows.map(config.row).join("");
  byId("integrity-result-count").textContent = `${formatNumber(rows.length)} records shown`;
  byId("integrity-empty").hidden = rows.length > 0;
  byId("integrity-table").hidden = rows.length === 0;
}

function switchIntegrityEntity(entity) {
  state.integrity.entity = entity;
  state.integrity.query = "";
  byId("integrity-search").value = "";
  $$('[data-integrity]').forEach((button) => {
    const selected = button.dataset.integrity === entity;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  loadIntegrity();
}

function installEventHandlers() {
  $$("[data-view]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view, { focus: true }));
  });
  $$('[data-go-view]').forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.goView, { focus: true }));
  });
  $$('[data-open-inventory]').forEach((button) => {
    button.addEventListener("click", () => switchInventoryEntity(button.dataset.openInventory, { focus: true }));
  });

  byId("theme-toggle").addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
  byId("collection-filter").addEventListener("change", (event) => setScope(event.target.value));
  byId("group-filter").addEventListener("change", (event) => {
    state.group = event.target.value;
    updateScopeSummary();
    state.overview = null;
    state.inventory.offset = 0;
    state.graph.documents = [];
    state.graph.data = null;
    state.fips.data = null;
    refreshCurrentView();
  });
  byId("clear-scope").addEventListener("click", () => setScope(""));
  byId("reload-overview").addEventListener("click", () => loadOverview(true));
  byId("reload-fips").addEventListener("click", () => loadFipsAssessment(true));

  byId("global-search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const query = byId("global-search").value.trim();
    switchInventoryEntity("components", { query, focus: true });
  });
  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const isTyping = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
    if (event.key === "/" && !isTyping && !byId("detail-dialog").open) {
      event.preventDefault();
      byId("global-search").focus();
    }
  });

  byId("format-chart").addEventListener("click", (event) => {
    const button = event.target.closest("[data-chart-index]");
    if (!button) return;
    const row = byId("format-chart")._chartRows?.[Number(button.dataset.chartIndex)];
    if (row) switchInventoryEntity("documents", { type: `${row.document_kind}|${row.spec_version || ""}`, focus: true });
  });
  byId("component-chart").addEventListener("click", (event) => {
    const button = event.target.closest("[data-chart-index]");
    if (!button) return;
    const row = byId("component-chart")._chartRows?.[Number(button.dataset.chartIndex)];
    if (row) switchInventoryEntity("components", { type: row.component_type, focus: true });
  });
  byId("service-group-chart").addEventListener("click", (event) => {
    const button = event.target.closest("[data-group-index]");
    if (!button) return;
    const group = byId("service-group-chart")._groups?.[Number(button.dataset.groupIndex)];
    if (group) setScope(group.source_collection, group.slug);
  });
  byId("service-group-table").addEventListener("click", (event) => {
    const button = event.target.closest("[data-service-scope]");
    if (button) setScope(button.dataset.serviceCollection, button.dataset.serviceScope);
  });

  installTabs($("[aria-label='Inventory type']"), "data-entity", (entity) => {
    if (entity !== state.inventory.entity) switchInventoryEntity(entity);
  });
  const runInventorySearch = debounce(() => {
    state.inventory.query = byId("inventory-search").value.trim();
    state.inventory.offset = 0;
    loadInventory();
  });
  byId("inventory-search").addEventListener("input", runInventorySearch);
  byId("inventory-type-filter").addEventListener("change", (event) => {
    state.inventory.type = event.target.value;
    state.inventory.offset = 0;
    loadInventory();
  });
  const resetInventory = () => {
    state.inventory.query = "";
    state.inventory.type = "";
    state.inventory.offset = 0;
    byId("inventory-search").value = "";
    byId("inventory-type-filter").value = "";
    loadInventory();
  };
  byId("reset-inventory").addEventListener("click", resetInventory);
  byId("inventory-empty-reset").addEventListener("click", resetInventory);
  byId("inventory-prev").addEventListener("click", () => {
    state.inventory.offset = Math.max(0, state.inventory.offset - PAGE_SIZE);
    loadInventory();
  });
  byId("inventory-next").addEventListener("click", () => {
    state.inventory.offset += PAGE_SIZE;
    loadInventory();
  });
  byId("inventory-head").addEventListener("click", (event) => {
    const button = event.target.closest("[data-sort]");
    if (!button) return;
    if (state.inventory.sortKey === button.dataset.sort) {
      state.inventory.sortDirection = state.inventory.sortDirection === "ascending" ? "descending" : "ascending";
    } else {
      state.inventory.sortKey = button.dataset.sort;
      state.inventory.sortDirection = "ascending";
    }
    renderInventory();
  });
  byId("inventory-body").addEventListener("click", (event) => {
    const button = event.target.closest("[data-detail]");
    if (button) openDetail(button.dataset.detail, button.dataset.id);
  });

  byId("graph-document").addEventListener("change", () => {
    const document = state.graph.documents.find((item) => String(item.document_id) === byId("graph-document").value);
    updateGraphRelationshipOptions(document);
    loadGraph();
  });
  byId("graph-relationship").addEventListener("change", loadGraph);
  byId("load-graph").addEventListener("click", loadGraph);
  byId("dependency-graph").addEventListener("click", (event) => {
    const node = event.target.closest("[data-node-ref]");
    if (node) selectGraphNode(node.dataset.nodeRef);
  });
  byId("dependency-graph").addEventListener("keydown", (event) => {
    if (!["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const nodes = state.graph.data?.nodes || [];
    if (event.key === "Home" && nodes.length) selectGraphNode(nodes[0].ref, true);
    else if (event.key === "End" && nodes.length) selectGraphNode(nodes.at(-1).ref, true);
    else moveGraphSelection(["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1);
  });
  byId("edge-table-body").addEventListener("click", (event) => {
    const row = event.target.closest("[data-edge-source]");
    if (row) selectGraphNode(row.dataset.edgeSource, true);
  });
  byId("edge-table-body").addEventListener("keydown", (event) => {
    const row = event.target.closest("[data-edge-source]");
    if (row && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      selectGraphNode(row.dataset.edgeSource, true);
    }
  });
  byId("node-prev").addEventListener("click", () => moveGraphSelection(-1));
  byId("node-next").addEventListener("click", () => moveGraphSelection(1));

  installTabs($("[aria-label='Integrity data type']"), "data-integrity", (entity) => {
    if (entity !== state.integrity.entity) switchIntegrityEntity(entity);
  });
  byId("integrity-search").addEventListener(
    "input",
    debounce(() => {
      state.integrity.query = byId("integrity-search").value.trim();
      loadIntegrity();
    }),
  );

  installTabs($("[aria-label='FIPS assessment view']"), "data-fips-tab", (tab) => {
    state.fips.tab = tab;
    applyFipsTab();
  });
  byId("fips-findings-body").addEventListener("click", (event) => {
    const button = event.target.closest("[data-fips-finding]");
    const finding = state.fips.data?.findings?.find((row) => row.finding_id === button?.dataset.fipsFinding);
    if (finding) renderFipsFindingDetail(finding);
  });
  byId("fips-search").addEventListener(
    "input",
    debounce(() => {
      state.fips.query = byId("fips-search").value.trim();
      renderFipsFindingTable();
    }),
  );
  byId("fips-state-filter").addEventListener("change", (event) => {
    state.fips.filter = event.target.value;
    renderFipsFindingTable();
  });
  byId("fips-poam-body").addEventListener("click", (event) => {
    const button = event.target.closest("[data-fips-poam]");
    const item = state.fips.data?.poam_items?.find((row) => row.poam_candidate_id === button?.dataset.fipsPoam);
    if (item) renderFipsPoamDetail(item);
  });

  byId("close-detail").addEventListener("click", () => byId("detail-dialog").close());
  byId("detail-dialog").addEventListener("click", (event) => {
    if (event.target === byId("detail-dialog")) byId("detail-dialog").close();
  });
  byId("detail-body").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      toast("Copied to clipboard");
    } catch (_error) {
      toast("Clipboard access was not available", "error");
    }
  });

  window.addEventListener("popstate", () => {
    showView(window.location.hash.slice(1) || "overview", { updateHistory: false });
  });
}

async function initialize() {
  initializeTheme();
  installEventHandlers();
  checkHealth();
  try {
    await loadCollections();
    const initialView = viewTitles[window.location.hash.slice(1)] ? window.location.hash.slice(1) : "overview";
    showView(initialView, { updateHistory: false });
  } catch (error) {
    setConnection("offline", "Catalog unavailable");
    byId("freshness-summary").textContent = "Could not load catalog scope";
    byId("format-chart").innerHTML = `<div class="error-panel">Could not connect to the catalog API: ${escapeHtml(error.message)}</div>`;
    toast(`Catalog initialization failed: ${error.message}`, "error");
  }
}

initialize();
