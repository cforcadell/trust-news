const $ = (id) => document.getElementById(id);
const state = {campaigns: [], campaign: null, orderList: null, diagnostic: null,
  assertionId: null, runId: null, stage: "generation", view: "summary", campaignView: "summary",
  navigationView: "campaigns",
  filters: {caseId: "", validator: "", repetition: "", stage: "", code: "", type: "",
    origin: "", nature: "", severity: "", impact: ""},
  campaignFilters: {orders: {}, incidents: {}}, navigationFilters: {campaigns: {}},
  pagination: {campaigns: {page: 1, size: 10}, orders: {page: 1, size: 10}},
  sorting: {campaigns: {key: "date", direction: "desc"}, orders: {key: "date", direction: "desc"},
    incidents: {key: "date", direction: "desc"}}};
const STAGES = [["generation", "Generate Assertions"], ["router", "Source Router"],
  ["evidence_search", "Evidence Search"], ["handoff", "Entrega"],
  ["llm", "LLM"], ["citations", "Citas"], ["consensus", "Consenso"]];

function el(tag, className = "", content = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== null && content !== undefined) node.textContent = String(content);
  return node;
}
function add(parent, ...children) { for (const child of children) parent.append(child); return parent; }
function clear(parent) { parent.replaceChildren(); return parent; }
function matchesFilter(value, query) {
  return !query || String(value ?? "").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
}
function matchesColumnFilter(value, query, options = null) {
  return options ? (!query || String(value ?? "") === query) : matchesFilter(value, query);
}
function tabulatedValues(values) {
  return [...new Set(values.map(value => String(value ?? "—")))].sort((left, right) =>
    left.localeCompare(right, "es", {numeric: true, sensitivity: "base"}));
}
function filterHeader(label, key, filters, apply, className = "", sorting = null, options = null) {
  const cell = el("th", className);
  let labelNode = el("span", "column-label", label);
  if (sorting) {
    cell.dataset.sortKey = key;
    labelNode = button(label, () => {
      sorting.direction = sorting.key === key && sorting.direction === "asc" ? "desc" : "asc";
      sorting.key = key; apply(true);
    }, "column-label column-sort");
    labelNode.setAttribute("aria-label", `Ordenar por ${label}`);
  }
  if (options) {
    const select = el("select", "column-filter column-filter-select");
    select.setAttribute("aria-label", `Filtrar ${label}`);
    const all = el("option", "", "Todos"); all.value = ""; add(select, all);
    for (const value of options) {
      const option = el("option", "", value); option.value = value; add(select, option);
    }
    select.value = filters[key] || "";
    select.addEventListener("change", () => { filters[key] = select.value; apply(true); });
    return add(cell, labelNode, select);
  }
  const input = el("input", "column-filter");
  input.type = "search"; input.placeholder = "Filtrar…"; input.value = filters[key] || "";
  input.setAttribute("aria-label", `Filtrar ${label}`);
  input.addEventListener("input", () => { filters[key] = input.value; apply(true); });
  return add(cell, labelNode, input);
}
function sortedEntries(entries, sorting) {
  if (!sorting?.key) return entries;
  const factor = sorting.direction === "desc" ? -1 : 1;
  return entries.map((entry, index) => ({entry, index})).sort((left, right) => {
    const a = left.entry.sortValues?.[sorting.key] ?? left.entry.values[sorting.key];
    const b = right.entry.sortValues?.[sorting.key] ?? right.entry.values[sorting.key];
    let result;
    if (typeof a === "number" && typeof b === "number") result = a - b;
    else result = String(a ?? "").localeCompare(String(b ?? ""), "es", {numeric: true, sensitivity: "base"});
    return result ? result * factor : left.index - right.index;
  }).map(item => item.entry);
}
function updateSortHeaders(head, sorting) {
  for (const cell of head.querySelectorAll("th[data-sort-key]")) {
    const active = cell.dataset.sortKey === sorting.key;
    cell.setAttribute("aria-sort", active ? (sorting.direction === "asc" ? "ascending" : "descending") : "none");
  }
}
function formatSavedDate(value) {
  if (!value) return "—";
  if (!/[T ]\d{2}:\d{2}/.test(value)) return String(value).slice(0, 10);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("es-ES", {dateStyle: "short", timeStyle: "medium"}).format(date);
}
function outcomePresentation(value) {
  return ({ACHIEVED: ["Conseguido", "PASS"], PARTIALLY_ACHIEVED: ["Parcial", "PARTIAL"],
    NOT_ACHIEVED: ["No conseguido", "FAIL"], UNRESOLVED: ["No resuelto", "PARTIAL"],
    NOT_EVALUATED: ["No evaluado", "NOT_EVALUATED"]})[value] || [value || "No evaluado", "NOT_EVALUATED"];
}
function healthPresentation(value) {
  return ({HEALTHY: ["Saludable", "PASS"], DEGRADED: ["Degradado", "PARTIAL"],
    FAILED: ["Fallido", "FAIL"], UNKNOWN: ["Desconocido", "NOT_EVALUATED"]})[value] ||
    [value || "Desconocido", "NOT_EVALUATED"];
}
function labeledPill(label, tone) {
  const icons = {PASS: "✓", FAIL: "✕", PARTIAL: "!", NOT_EVALUATED: "?", SKIPPED: "–"};
  return el("span", `pill pill-${tone}`, `${icons[tone] || "·"} ${label}`);
}
function paginationControls(pagination, apply) {
  const node = el("div", "pagination"), summary = el("span", "pagination-summary");
  const previous = button("Anterior", () => { pagination.page -= 1; apply(); });
  const next = button("Siguiente", () => { pagination.page += 1; apply(); });
  const size = el("select", "page-size");
  size.setAttribute("aria-label", "Filas por página");
  for (const value of [10, 25, 50]) {
    const option = el("option", "", `${value} / página`); option.value = value;
    option.selected = pagination.size === value; add(size, option);
  }
  size.addEventListener("change", () => { pagination.size = Number(size.value); pagination.page = 1; apply(); });
  add(node, summary, previous, next, size);
  return {node, update(total) {
    const pages = Math.max(1, Math.ceil(total / pagination.size));
    pagination.page = Math.min(Math.max(1, pagination.page), pages);
    const first = total ? (pagination.page - 1) * pagination.size + 1 : 0;
    const last = Math.min(total, pagination.page * pagination.size);
    summary.textContent = total ? `${first}–${last} de ${total}` : "0 resultados";
    previous.disabled = pagination.page === 1; next.disabled = pagination.page === pages || !total;
    return {first: total ? first - 1 : 0, last};
  }};
}
function button(label, onClick, className = "") {
  const node = el("button", className, label); node.type = "button";
  node.addEventListener("click", onClick); return node;
}
function pill(status) {
  const icons = {PASS: "✓", FAIL: "✕", PARTIAL: "!", NOT_EVALUATED: "?", SKIPPED: "–"};
  return el("span", `pill pill-${status}`, `${icons[status] || "·"} ${status}`);
}
function recorded(value) { return value === null || value === undefined || value === "" ? "No registrado" : value; }
function strategyLabel(strategy) {
  return ({LOCAL: "RAG con dominios de Source Router", EXT_ONLY_OFFICIAL: "RAG con fuentes oficiales externas",
    EXT_OFFICIAL_FIRST: "RAG externo, fuentes oficiales primero"})[strategy] || strategy || "Estrategia no registrada";
}
function validatorKindLabel(metadata = {}) {
  const type = metadata.validator_type || "Tipo no registrado";
  return `${type} · ${strategyLabel(metadata.evidence_search_strategy)}`;
}
function stagePresentation(stage, stageKey) {
  if (!stage) return {execution: "SIN VALIDADOR", result: "—", tone: "SKIPPED"};
  if (stage.execution_status === "SKIPPED") {
    const strategy = stage.observations?.evidence_search_strategy;
    return {execution: "NO APLICA", result: strategy || "OMITIDO", tone: "SKIPPED"};
  }
  if (stage.execution_status === "NOT_RECORDED")
    return {execution: "SIN REGISTRO", result: "NO EVALUADO", tone: "NOT_EVALUATED"};
  if (stage.execution_status === "FAILED")
    return {execution: "ERROR", result: stage.assessment, tone: "FAIL"};
  if (stageKey === "router" && stage.assessment === "NOT_EVALUATED")
    return {execution: "EJECUTADO", result: "SIN REFERENCIA", tone: "EXECUTED_NOT_EVALUATED"};
  if (stageKey === "router" && stage.assessment === "PARTIAL")
    return {execution: "EJECUTADO", result: "WARNING", tone: "PARTIAL"};
  return {execution: "EJECUTADO", result: stage.assessment, tone: stage.assessment};
}
function issueType(type) { return el("span", `issue-type issue-type-${type}`, type); }
function inferredIssueType(stageKey, check, stage) {
  if (check.type) return check.type;
  // Saved v1 diagnostics predate the explicit type field. Keep their quality
  // findings out of the technical-error bucket without rewriting artifacts.
  if (stageKey === "generation" && !["GENERATION_ERROR", "MODULE_FAILED"].includes(check.code)) return "warning";
  if (stageKey === "router") {
    const sources = stage.observations?.sources || [];
    const matches = stage.observations?.matching_domains || [];
    if (sources.length && !matches.length) return "warning";
  }
  return check.status === "PARTIAL" ? "warning" : "error";
}
function inferredIssueMetadata(stageKey, check) {
  const stageOrigins = {generation: "GENERATION", router: "ROUTER", evidence_search: "RETRIEVAL",
    handoff: "EXECUTION", llm: "VALIDATOR", citations: "VALIDATOR", consensus: "CONSENSUS"};
  const benchmarkCodes = new Set(["EXPECTED_ASSERTION_MISSING", "CATEGORY_MISMATCH",
    "EXPECTED_TOPIC_CODE_MISMATCH", "EXPECTED_EVIDENCE_KIND_MISMATCH", "ROUTER_EXPECTED_DOMAIN_MISSING"]);
  const evaluationCodes = new Set(["GOLD_MATCH_INCOMPATIBLE", "UNMATCHED_GENERATED_ASSERTION"]);
  const nature = check.nature || (evaluationCodes.has(check.code) ? "EVALUATION_UNCERTAINTY" :
    benchmarkCodes.has(check.code) ? "BENCHMARK_DEVIATION" :
    check.code === "SOME_SOURCES_UNUSABLE" ? "QUALITY_DEGRADATION" : "FUNCTIONAL_FAILURE");
  return {origin: check.origin || (evaluationCodes.has(check.code) ? "EVALUATOR" :
      benchmarkCodes.has(check.code) ? "DATASET" : stageOrigins[stageKey] || "EXECUTION"),
    nature, severity: check.severity || (check.status === "FAIL" ? "HIGH" : "LOW"),
    impact: check.impact || (["BENCHMARK_DEVIATION", "EVALUATION_UNCERTAINTY", "POLICY_CONSTRAINT"].includes(nature) ?
      "METRICS_ONLY" : "UNKNOWN")};
}
function routerMisalignmentCheck(stage) {
  const observations = stage.observations || {};
  const expected = observations.acceptable_domains || [];
  const selected = (observations.sources || []).filter(source => source?.domain).map(source => {
    const type = source.source_type || "—", authority = source.authority_level || "—";
    return `${source.domain} (${type} / ${authority})`;
  });
  return {
    code: "ROUTER_EXPECTED_DOMAIN_MISSING", status: "FAIL", type: "warning",
    detail: `Desalineamiento de dominio: se esperaba ${expected.join(", ") || "ningún dominio anotado"}; Router seleccionó ${selected.join(", ") || "dominios no identificados"}. Ninguno coincide con el dominio anotado, pero Router sí devolvió fuentes elegibles; se registra como aviso de evaluación.`
  };
}
function generationIssueDetail(check, stage) {
  const observations = stage.observations || {};
  if (check.code === "GENERATION_ERROR" || check.code === "MODULE_FAILED")
    return `Generate Assertions no produjo una salida evaluable. Causa registrada: ${observations.error_type || "no disponible en el artefacto"}.`;
  const ref = (check.observation_refs || []).find(value => /generated_assertions\/\d+$/.test(value));
  const index = ref?.match(/(\d+)$/)?.[1];
  const actual = index == null ? null : observations.generated_assertions?.[Number(index)];
  const match = observations.matches?.find(item => item.assertion_id === actual?.assertion_id);
  const expected = observations.expected_assertions?.find(item => item.case_id === match?.case_id);
  if (!actual || !expected) return check.detail;
  const values = {
    CATEGORY_MISMATCH: [expected.category_ids?.join(", ") || "sin categoría anotada", actual.categoryId ?? "ausente", "categoría"],
    EXPECTED_TOPIC_CODE_MISMATCH: [expected.expected_topic_code ?? "ausente", actual.topic_code ?? "ausente", "topic_code"],
    EXPECTED_EVIDENCE_KIND_MISMATCH: [expected.expected_evidence_kind ?? "ausente", actual.evidence_kind ?? "ausente", "evidence_kind"]
  }[check.code];
  if (values) return `Desalineamiento de ${values[2]}: para ${expected.case_id} se esperaba ${values[0]} y Generate Assertions produjo ${values[1]}.`;
  return check.detail;
}
function sourceOutcomeDetail(observations) {
  const sources = observations.evidences || [];
  if (!sources.length) return "Evidence Search no devolvió fuentes candidatas, por lo que no pudo generar contexto citable.";
  return sources.map(source => {
    const name = source.domain || source.url || source.source_id || "fuente desconocida";
    const status = source.fetch_status || "estado de descarga no registrado";
    const contexts = (source.contexts || []).length;
    const normalized = source.url_normalized && source.fetched_url ? `, URL normalizada a ${source.fetched_url}` : "";
    return `${name}: ${status}, ${contexts} contextos${normalized}${source.fetch_error ? `, causa ${source.fetch_error}` : ""}`;
  }).join("; ");
}
function explainIssue(stageKey, check, stage, validation = null) {
  const obs = stage.observations || {};
  if (stageKey === "generation") return generationIssueDetail(check, stage);
  if (stageKey === "router" && (obs.acceptable_domains || []).length &&
      (obs.sources || []).length && !(obs.matching_domains || []).length)
    return routerMisalignmentCheck(stage).detail;
  if (stageKey === "router" && !(obs.sources || []).length)
    return `Router no entregó dominios elegibles. Estado de ruta=${obs.route_state || obs.status || "no registrado"}; diagnóstico=${obs.diagnostic_code || obs.diagnostics?.reason || "causa no registrada"}.`;
  if (stageKey === "evidence_search" && ["MODULE_FAILED", "NO_CITABLE_EVIDENCE", "SOME_SOURCES_UNUSABLE"].includes(check.code))
    return `La etapa quedó ${stage.assessment} por el resultado de recuperación: ${sourceOutcomeDetail(obs)}`;
  if (stageKey === "handoff" && check.code === "HANDOFF_EVIDENCE_MISMATCH")
    return `La evidencia cambió entre recuperación y validación: hash recuperado=${obs.retrieval_hash || "ausente"}; hash entregado=${obs.validator_input_hash || "ausente"}.`;
  if (stageKey === "llm" && check.code === "TECHNICAL_ERROR") {
    const errors = obs.errors || [];
    return `La validación no produjo una decisión por estos errores registrados: ${errors.map(error =>
      `etapa=${error.stage || "desconocida"}, código=${error.code || "desconocido"}, excepción=${error.exception_type || "no registrada"}${error.reason ? `, causa=${error.reason}` : ""}`
    ).join("; ") || "causa no registrada"}.`;
  }
  if (stageKey === "llm" && check.code === "WRONG_VERDICT")
    return `Decisión incorrecta: se esperaba ${obs.expected_verdict ?? "no registrado"}, pero el validador produjo ${obs.effective_verdict ?? "ausente"}; veredicto original=${obs.original_verdict ?? "ausente"}.`;
  if (stageKey === "citations" && ["INVALID_CITATION_ID", "CITATION_REJECTED"].includes(check.code)) {
    const invalid = (obs.citations || []).filter(item => !item.valid_identity);
    return `La auditoría rechazó las citas porque no pudo vincularlas a contexto citable: ${invalid.map(item =>
      `${item.source_id || "sin source_id"}/${item.context_id || "sin context_id"}: ${item.reason || "motivo no registrado"}`
    ).join("; ") || (obs.audit_issues || []).map(item => item.code || String(item)).join(", ") || "motivo no registrado"}.`;
  }
  if (stageKey === "consensus" && check.code === "CONSENSUS_ERROR") {
    const expected = obs.expected_verdict ?? validation?.stages?.llm?.observations?.expected_verdict ?? "no registrado";
    return `El consenso produjo ${obs.verdict ?? "ausente"}, pero se esperaba ${expected}. Motivo=${obs.reason_code || "no registrado"}; distribución=${JSON.stringify(obs.distribution || {})}.`;
  }
  return check.detail || `La etapa ${stageKey} terminó con ${stage.assessment}, pero el artefacto no registró la causa.`;
}
function showError(message) {
  clear($("main")); add($("main"), add(el("section", "error-list"), el("strong", "", "No se pudo abrir el artefacto"), el("p", "", message)));
}
async function api(path) {
  const response = await fetch(path, {cache: "no-store"});
  let body;
  try { body = await response.json(); } catch { throw new Error(`Respuesta inválida (HTTP ${response.status})`); }
  if (!response.ok) throw new Error(body.detail || body.error || `HTTP ${response.status}`);
  return body;
}
function enc(value) { return encodeURIComponent(value); }

async function loadCampaigns() {
  try { state.campaigns = await api("/api/campaigns"); renderCampaignIndex(); }
  catch (error) { showError(error.message); }
}
function renderNavigation() {
  const campaigns = $("nav-campaigns"), orders = $("nav-orders");
  campaigns.classList.toggle("active", state.navigationView === "campaigns");
  orders.classList.toggle("active", state.navigationView === "orders");
  campaigns.toggleAttribute("aria-current", state.navigationView === "campaigns");
  orders.toggleAttribute("aria-current", state.navigationView === "orders");
  const campaignHost = clear($("selected-campaign")), orderHost = clear($("order-menu"));
  if (state.campaign) {
    const selectedCampaign = button(state.campaign, () => {
      state.navigationView = "campaigns"; renderNavigation();
      if (state.orderList) renderCampaignOverview();
    }, "context-item active");
    selectedCampaign.title = "Volver al resumen de la campaña seleccionada"; add(campaignHost, selectedCampaign);
  }
  for (const item of state.orderList?.orders || []) {
    const selected = state.diagnostic?.identity.order_id === item.order_id;
    const order = button(item.order_id, () => openOrder(item.file), `context-item${selected ? " active" : ""}`);
    order.title = `Abrir orden ${item.order_id}`;
    add(order, el("small", "", `${item.dataset_id} · rep. ${item.repetition} · ${item.status}`)); add(orderHost, order);
  }
}
function showCampaigns() {
  state.campaign = null; state.orderList = null; state.diagnostic = null;
  state.assertionId = null; state.runId = null; state.navigationView = "campaigns";
  state.campaignFilters = {orders: {}, incidents: {}}; state.pagination.orders.page = 1;
  renderNavigation(); renderCampaignIndex();
}
function showOrders() {
  state.navigationView = "orders"; renderNavigation(); renderOrderIndex();
}
function renderCampaignIndex() {
  state.navigationView = "campaigns"; renderNavigation();
  const main = clear($("main"));
  add(main, el("div", "eyebrow", "Navegación"), el("h1", "", "Campañas"),
    el("p", "muted", "Selecciona una fila para abrir el detalle de la campaña."));
  const card = add(el("section", "card"), el("h2", "", "Campañas guardadas")); add(main, card);
  if (!state.campaigns.length) return add(card, el("p", "muted", "No hay órdenes con diagnóstico v1 en la carpeta configurada."));
  const filters = state.navigationFilters.campaigns, pagination = state.pagination.campaigns;
  const sorting = state.sorting.campaigns;
  const wrap = el("div", "table-wrap"), table = el("table", "campaign-table auto-columns"), head = el("tr"), body = el("tbody");
  const entries = [], noResults = el("p", "muted table-empty", "No hay campañas que coincidan con los filtros.");
  let pager;
  function applyFilters(resetPage = false) {
    if (resetPage) pagination.page = 1;
    const ordered = sortedEntries(entries, sorting); for (const entry of ordered) add(body, entry.node);
    const visible = ordered.filter(entry => Object.entries(filters).every(([key, query]) =>
      matchesColumnFilter(entry.values[key], query, filterOptions[key])));
    const range = pager.update(visible.length), shown = new Set(visible.slice(range.first, range.last));
    for (const entry of entries) entry.node.hidden = !shown.has(entry);
    noResults.hidden = Boolean(visible.length); updateSortHeaders(head, sorting);
  }
  const columns = [["Campaña", "campaign", "campaign-column"], ["Fecha", "date", "date-column"],
    ["Órdenes", "orders", "compact-column"], ["Estado", "status", "status-column"],
    ["Archivos con problemas", "errors", "compact-column"]];
  const filterOptions = {status: tabulatedValues(state.campaigns.map(item => item.status))};
  for (const [label, key, className] of columns)
    add(head, filterHeader(label, key, filters, applyFilters, className, sorting, filterOptions[key]));
  for (const campaign of state.campaigns) {
    const values = {campaign: campaign.campaign_id, date: formatSavedDate(campaign.created_at),
      orders: campaign.order_count, status: campaign.status, errors: campaign.errors?.length || 0};
    const dateCell = el("td", "date-column", values.date); if (campaign.created_at) dateCell.title = campaign.created_at;
    const row = add(el("tr", `clickable-row${campaign.campaign_id === state.campaign ? " selected-row" : ""}`),
      el("td", "campaign-column", values.campaign), dateCell,
      el("td", "compact-column", values.orders), el("td", "status-column", values.status),
      el("td", "compact-column", values.errors));
    const open = () => openCampaign(campaign.campaign_id);
    row.tabIndex = 0; row.title = "Abrir campaña"; row.addEventListener("click", open);
    row.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
    entries.push({node: row, values, sortValues: {date: campaign.created_at ? Date.parse(campaign.created_at) : -Infinity}}); add(body, row);
  }
  pager = paginationControls(pagination, applyFilters);
  add(table, add(el("thead"), head), body); add(wrap, table); add(card, wrap, noResults, pager.node); applyFilters();
}
async function openCampaign(campaign) {
  state.campaign = campaign; state.orderList = null; state.diagnostic = null;
  state.navigationView = "campaigns";
  state.campaignView = "summary";
  state.campaignFilters = {orders: {}, incidents: {}};
  state.pagination.orders.page = 1;
  state.filters = {caseId: "", validator: "", repetition: "", stage: "", code: "", type: ""};
  renderNavigation();
  try {
    state.orderList = await api(`/api/campaigns/${enc(campaign)}/orders`);
    renderNavigation(); renderCampaignOverview();
  } catch (error) { showError(error.message); }
}
function renderOrderIndex() {
  const main = clear($("main"));
  if (!state.campaign || !state.orderList) return add(main, add(el("section", "empty"),
    el("h1", "", "Selecciona primero una campaña"),
    el("p", "", "La tabla de órdenes muestra las órdenes de la campaña seleccionada."),
    button("Ver campañas", showCampaigns)));
  add(main, el("div", "eyebrow", "Campaña"), el("h1", "", "Órdenes"), el("p", "muted", state.campaign));
  const problems = errorBlock(state.orderList.errors); if (problems) add(main, problems);
  add(main, campaignOrderTable("Órdenes de la campaña"));
}
function errorBlock(errors) {
  if (!errors || !errors.length) return null;
  const block = el("section", "error-list"); add(block, el("strong", "", "Archivos con problemas"));
  const list = el("ul"); for (const error of errors) add(list, el("li", "", error)); add(block, list); return block;
}
function renderEmptyCampaign() {
  const main = clear($("main"));
  add(main, add(el("section", "card"), el("h1", "", state.campaign),
    el("p", "muted", "No hay órdenes legibles en esta campaña.")));
  const problems = errorBlock(state.orderList.errors); if (problems) add(main, problems);
}
function campaignTabs() {
  const tabs = el("div", "view-tabs");
  for (const [key, label] of [["summary", "Resumen"], ["orders", "Órdenes"], ["costs", "Costes"], ["incidents", "Incidencias"]]) {
    const node = button(label, () => { state.campaignView = key; renderCampaignOverview(); },
      state.campaignView === key ? "active" : "");
    node.setAttribute("role", "tab"); node.setAttribute("aria-selected", String(state.campaignView === key));
    add(tabs, node);
  }
  return tabs;
}
function campaignSummaryView() {
  const summary = state.orderList.summary || {};
  const report = state.orderList.report || {};
  const block = el("div", "stack");
  if (state.orderList.orders.length) add(block, add(el("section", "summary overview-metrics"),
      metric(`${summary.orders_achieved ?? 0}/${summary.orders_total ?? 0}`, "órdenes con objetivo conseguido"),
      metric(`${summary.assertions_achieved ?? 0}/${summary.assertions_total ?? 0}`, "aserciones correctas por consenso"),
      metric(summary.orders_degraded ?? 0, "órdenes conseguidas o ejecutadas con degradación"),
      metric(summary.consensus_rescues ?? 0, "aserciones rescatadas por consenso"),
      metric(`${summary.decisive_votes ?? 0}/${summary.assigned_votes ?? 0}`, "votos decisivos / asignados"),
      metric(summary.abstentions ?? 0, "abstenciones"),
      metric(summary.contradictions ?? 0, "contradicciones"),
      metric(summary.technical_errors ?? 0, "errores técnicos")));
  if (!state.orderList.orders.length && Object.keys(report).length) {
    add(block, add(el("section", "card status status-PARTIAL"),
      el("h2", "", "Campaña sin instantánea de orden navegable"),
      el("p", "", "La campaña y su informe existen, pero la ejecución terminó antes de guardar un diagnóstico *-viewer.json. Se muestra el resultado agregado disponible."),
      add(el("div", "summary"),
        metric(report.total_cases ?? 0, "casos del informe"),
        metric(report.end_to_end_correct ?? 0, "correctos E2E"),
        metric(report.end_to_end_incorrect ?? 0, "incorrectos E2E"),
        metric(report.not_evaluated ?? 0, "no evaluados"),
        metric(report.failures?.technical ?? 0, "fallos técnicos"))));
  }
  const card = add(el("section", "card"), el("h2", "", "Resultado por orden"),
    el("p", "muted", "El resultado E2E y la salud del proceso se muestran por separado. Una orden puede conseguir el objetivo aunque algún validador se abstenga."));
  if (!state.orderList.orders.length) add(card, el("p", "muted", "No hay órdenes legibles en esta campaña."));
  else {
    const wrap = el("div", "table-wrap"), table = el("table", "campaign-table auto-columns"), head = el("tr"), body = el("tbody");
    for (const label of ["Fecha", "Orden / dataset", "Resultado E2E", "Aserciones", "Validadores", "Participación", "Salud", "Consenso compensó"])
      add(head, el("th", "", label));
    for (const item of state.orderList.orders) {
      const value = item.summary || {};
      const [outcomeLabel, outcomeTone] = outcomePresentation(value.outcome);
      const [healthLabel, healthTone] = healthPresentation(value.health);
      const row = add(el("tr", "clickable-row"), el("td", "date-column", formatSavedDate(item.created_at)),
        add(el("td", "order-column"), el("strong", "mono", item.order_id), el("small", "table-secondary", item.dataset_id)),
        add(el("td"), labeledPill(outcomeLabel, outcomeTone)),
        el("td", "compact-column", `${value.assertions_achieved ?? 0}/${value.assertions_total ?? 0}`),
        el("td", "compact-column", value.validators_observed ?? 0),
        el("td", "compact-column", `${value.decisive_votes ?? 0}/${value.assigned_votes ?? 0} decisivos`),
        add(el("td"), labeledPill(healthLabel, healthTone)),
        el("td", "compact-column", value.consensus_rescues ?? 0));
      row.tabIndex = 0; row.title = "Abrir resumen de la orden";
      row.addEventListener("click", () => openOrder(item.file));
      row.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openOrder(item.file); }
      });
      add(body, row);
    }
    add(table, add(el("thead"), head), body); add(wrap, table); add(card, wrap);
  }
  return add(block, card);
}

function money(value) {
  return value === null || value === undefined ? "—" :
    `${new Intl.NumberFormat("es-ES", {minimumFractionDigits: 2, maximumFractionDigits: 8}).format(Number(value))} USD`;
}
function costStatus(costs) {
  return !costs.events ? "No hay consumos registrados" :
    costs.unknown_events ? `${costs.unknown_events} eventos sin coste calculable` : "Cobertura completa";
}
function knownMoney(costs) {
  return costs.priced_events ? money(costs.known_usd) : "—";
}
function tokenSummary(costs) {
  if (!costs.llm_events_with_usage) return "—";
  return `${costs.input_tokens ?? 0} / ${costs.output_tokens ?? 0}`;
}
function llmMoney(costs, field) {
  return costs.llm_priced_events ? money(costs[field]) : "—";
}
function searchMoney(costs) {
  return costs.search_priced_events ? money(costs.search_cost_usd) : "—";
}
function missingCostDetail(costs) {
  const reasons = costs.unknown_reasons || {};
  const labels = {RATE_MISSING: "sin tarifa", USAGE_MISSING: "sin tokens registrados",
    BILLING_UNKNOWN: "facturación de llamada fallida desconocida", TRACE_MISSING: "sin traza",
    RESULT_COUNT_MISSING: "sin número de resultados"};
  return Object.entries(reasons).map(([reason, count]) => `${count} ${labels[reason] || reason}`).join(" · ");
}
function campaignCostView() {
  const costs = state.orderList.costs || {};
  const block = el("div", "stack");
  add(block, add(el("section", "summary overview-metrics"),
    metric(knownMoney(costs), "coste conocido"),
    metric(!costs.events ? "Sin datos" : costs.total_usd === null ? "Incompleto" : money(costs.total_usd), "total de campaña"),
    metric(costs.events ?? 0, "eventos medidos"),
    metric(costs.unknown_events ?? 0, "eventos sin coste"),
    metric(tokenSummary(costs), "tokens entrada / salida")));
  add(block, add(el("p", "muted"),
    `${costStatus(costs)}${missingCostDetail(costs) ? ` (${missingCostDetail(costs)})` : ""}. Tarifas ${costs.rates_configured ? "guardadas en la campaña" : "no configuradas"}. ` +
    "Los importes se calculan con tarifas USD de la campaña; cómputo, alojamiento, descuentos y reintentos internos sin traza quedan fuera."));
  const breakdown = add(el("section", "card"), el("h2", "", "Por componente"));
  const componentTable = el("table"), componentBody = el("tbody");
  add(componentTable, add(el("thead"), add(el("tr"), ...["Componente", "Eventos", "Sin coste", "Tokens E / S", "Coste entrada", "Coste salida", "Coste conocido", "Total"].map(v => el("th", "", v)))), componentBody);
  for (const [name, row] of Object.entries(costs.components || {})) {
    add(componentBody, add(el("tr"), el("td", "", name), el("td", "", row.events),
      el("td", "", row.unknown_events), el("td", "", tokenSummary(row)),
      el("td", "", llmMoney(row, "input_cost_usd")), el("td", "", llmMoney(row, "output_cost_usd")),
      el("td", "", knownMoney(row)), el("td", "", money(row.total_usd))));
  }
  if (!componentBody.children.length) add(breakdown, el("p", "muted", "No hay consumos registrados."));
  else add(breakdown, add(el("div", "table-wrap"), componentTable));
  add(block, breakdown);
  const orders = add(el("section", "card"), el("h2", "", "Órdenes y validaciones"));
  const table = el("table"), body = el("tbody");
  add(table, add(el("thead"), add(el("tr"), ...["Orden / validación", "Desglose", "Eventos", "Sin coste", "Tokens E / S", "Coste entrada", "Coste salida", "Búsquedas", "Conocido", "Total"].map(v => el("th", "", v)))), body);
  add(body, add(el("tr", "cost-order-row"), el("th", "", "CAMPAÑA"), el("td", "", "Todos los componentes"),
    el("td", "", costs.events ?? 0), el("td", "", costs.unknown_events ?? 0),
    el("td", "", tokenSummary(costs)), el("td", "", llmMoney(costs, "input_cost_usd")),
    el("td", "", llmMoney(costs, "output_cost_usd")), el("td", "", searchMoney(costs)),
    el("td", "", knownMoney(costs)), el("td", "", money(costs.total_usd))));
  for (const item of state.orderList.orders) {
    const value = item.costs || {};
    const open = button(item.order_id, () => openOrder(item.file, {view: "costs"}), "mono");
    add(body, add(el("tr", "cost-order-row"), add(el("td"), open), el("td", "", `Repetición ${item.repetition}`),
      el("td", "", value.events ?? 0), el("td", "", value.unknown_events ?? 0),
      el("td", "", tokenSummary(value)), el("td", "", llmMoney(value, "input_cost_usd")),
      el("td", "", llmMoney(value, "output_cost_usd")), el("td", "", searchMoney(value)),
      el("td", "", knownMoney(value)), el("td", "", money(value.total_usd))));
    for (const validation of value.validations || []) {
      const openValidation = button(`${validation.assertion_id} · ${validation.validator_id}`,
        () => openOrder(item.file, {view: "costs", run_id: validation.run_id, assertion_id: validation.assertion_id}), "mono");
      add(body, add(el("tr"), add(el("td", "cost-validation-row"), openValidation),
        el("td", "", `${validation.provider || "—"}${validation.model ? ` / ${validation.model}` : ""}`), el("td", "", validation.events),
        el("td", "", validation.unknown_events), el("td", "", tokenSummary(validation)),
        el("td", "", llmMoney(validation, "input_cost_usd")), el("td", "", llmMoney(validation, "output_cost_usd")),
        el("td", "", searchMoney(validation)), el("td", "", knownMoney(validation)),
        el("td", "", money(validation.total_usd))));
    }
  }
  add(orders, add(el("div", "table-wrap"), table)); add(block, orders);
  return block;
}
function campaignOrderTable(title = "Órdenes de la campaña") {
  const card = add(el("section", "card"), el("h2", "", title));
  if (!state.orderList.orders.length) return add(card, el("p", "muted", "No hay órdenes legibles en esta campaña."));
  const filters = state.campaignFilters.orders;
  const pagination = state.pagination.orders;
  const sorting = state.sorting.orders;
  const wrap = el("div", "table-wrap"), table = el("table", "campaign-table auto-columns"), head = el("tr"), body = el("tbody");
  const entries = [], noResults = el("p", "muted table-empty", "No hay órdenes que coincidan con los filtros.");
  let pager;
  function applyFilters(resetPage = false) {
    if (resetPage) pagination.page = 1;
    const ordered = sortedEntries(entries, sorting); for (const entry of ordered) add(body, entry.node);
    const visible = ordered.filter(entry => Object.entries(filters).every(([key, query]) =>
      matchesColumnFilter(entry.values[key], query, filterOptions[key])));
    const range = pager.update(visible.length), shown = new Set(visible.slice(range.first, range.last));
    for (const entry of entries) entry.node.hidden = !shown.has(entry);
    noResults.hidden = Boolean(visible.length); updateSortHeaders(head, sorting);
  }
  const columns = [["Fecha", "date", "date-column"], ["Orden", "order", "order-column"], ["Dataset", "dataset", "dataset-column"],
    ["Rep.", "repetition", "compact-column"], ["Afirmaciones", "assertions", "compact-column"],
    ["Resultado E2E", "outcome", "status-column"], ["Salud", "health", "status-column"],
    ["Decisivos", "decisive", "compact-column"], ["Validaciones", "validations", "compact-column"],
    ["Avisos", "warnings", "compact-column"], ["Errores", "errors", "compact-column"],
    ["Estado", "status", "status-column"]];
  const filterOptions = {
    dataset: tabulatedValues(state.orderList.orders.map(item => item.dataset_id)),
    repetition: tabulatedValues(state.orderList.orders.map(item => item.repetition)),
    outcome: tabulatedValues(state.orderList.orders.map(item => outcomePresentation((item.summary || {}).outcome)[0])),
    health: tabulatedValues(state.orderList.orders.map(item => healthPresentation((item.summary || {}).health)[0])),
    status: tabulatedValues(state.orderList.orders.map(item => item.status)),
  };
  for (const [label, key, className] of columns)
    add(head, filterHeader(label, key, filters, applyFilters, className, sorting, filterOptions[key]));
  for (const item of state.orderList.orders) {
    const orderSummary = item.summary || {};
    const [outcomeLabel, outcomeTone] = outcomePresentation(orderSummary.outcome);
    const [healthLabel, healthTone] = healthPresentation(orderSummary.health);
    const values = {date: formatSavedDate(item.created_at), order: item.order_id, dataset: item.dataset_id, repetition: item.repetition,
      assertions: `${orderSummary.assertions_achieved ?? 0}/${orderSummary.assertions_total ?? item.assertions}`,
      outcome: outcomeLabel, health: healthLabel,
      decisive: `${orderSummary.decisive_votes ?? 0}/${orderSummary.assigned_votes ?? 0}`,
      validations: item.validations,
      warnings: item.warnings ?? 0, errors: item.errors ?? 0, status: item.status};
    const selected = state.diagnostic?.identity.order_id === item.order_id;
    const row = add(el("tr", `clickable-row${selected ? " selected-row" : ""}`), el("td", "date-column", values.date), el("td", "mono order-column", values.order),
      el("td", "dataset-column", values.dataset), el("td", "compact-column", values.repetition),
      el("td", "compact-column", values.assertions), add(el("td"), labeledPill(outcomeLabel, outcomeTone)),
      add(el("td"), labeledPill(healthLabel, healthTone)), el("td", "compact-column", values.decisive),
      el("td", "compact-column", values.validations), el("td", "compact-column", values.warnings),
      el("td", "compact-column", values.errors), el("td", "status-column", values.status));
    row.tabIndex = 0; row.title = "Abrir orden";
    row.addEventListener("click", () => openOrder(item.file));
    row.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openOrder(item.file); }
    });
    entries.push({node: row, values, sortValues: {date: item.created_at ? Date.parse(item.created_at) : -Infinity}}); add(body, row);
  }
  pager = paginationControls(pagination, applyFilters);
  add(table, add(el("thead"), head), body); add(wrap, table); add(card, wrap, noResults, pager.node); applyFilters(); return card;
}
function campaignIncidentTable() {
  const incidents = state.orderList.incidents || [];
  const summary = el("p", "muted");
  const card = add(el("section", "card"), el("h2", "", "Incidencias de la campaña"), summary);
  if (!incidents.length) return add(card, el("p", "muted", "No hay incidencias registradas."));
  const filters = state.campaignFilters.incidents;
  const sorting = state.sorting.incidents;
  const wrap = el("div", "table-wrap"), table = el("table", "campaign-incident-table campaign-table auto-columns"), head = el("tr"), body = el("tbody");
  const entries = [];
  function applyFilters() {
    let errors = 0, warnings = 0, visible = 0;
    const ordered = sortedEntries(entries, sorting); for (const entry of ordered) add(body, entry.node);
    for (const entry of ordered) {
      const shown = Object.entries(filters).every(([key, query]) =>
        matchesColumnFilter(entry.values[key], query, filterOptions[key]));
      entry.node.hidden = !shown;
      if (shown) { visible += 1; errors += entry.values.type === "error"; warnings += entry.values.type === "warning"; }
    }
    summary.textContent = `${visible} incidencias visibles · ${errors} errores · ${warnings} avisos. Selecciona una fila para abrir el detalle.`;
    updateSortHeaders(head, sorting);
  }
  const columns = [["Fecha", "date", "date-column"], ["Tipo", "type", "compact-column"], ["Orden", "order", "order-column"],
    ["Rep.", "repetition", "compact-column"], ["Módulo", "stage", "module-column"],
    ["Validador", "validator", "validator-column"], ["Código", "code", "code-column"],
    ["Detalle", "detail", "detail-column"]];
  const filterOptions = {
    type: tabulatedValues(incidents.map(item => item.type)),
    repetition: tabulatedValues(incidents.map(item => item.repetition)),
    stage: tabulatedValues(incidents.map(item => STAGES.find(([key]) => key === item.stage)?.[1] || item.stage)),
    validator: tabulatedValues(incidents.map(item => item.validator_id || "—")),
    code: tabulatedValues(incidents.map(item => item.code)),
  };
  for (const [label, key, className] of columns)
    add(head, filterHeader(label, key, filters, applyFilters, className, sorting, filterOptions[key]));
  for (const item of incidents) {
    const stageName = STAGES.find(([key]) => key === item.stage)?.[1] || item.stage;
    const values = {date: formatSavedDate(item.created_at), type: item.type, order: item.order_id, repetition: item.repetition, stage: stageName,
      validator: item.validator_id || "—", code: item.code, detail: item.detail};
    const row = add(el("tr", "clickable-row"), el("td", "date-column", values.date), add(el("td", "compact-column"), issueType(values.type)),
      el("td", "mono order-column", values.order), el("td", "compact-column", values.repetition),
      el("td", "module-column", values.stage), el("td", "mono validator-column", values.validator),
      el("td", "mono code-column", values.code), el("td", "detail-column", values.detail));
    const open = () => openOrder(item.file, item);
    row.tabIndex = 0; row.title = "Abrir el detalle de esta incidencia";
    row.addEventListener("click", open);
    row.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
    entries.push({node: row, values, sortValues: {date: item.created_at ? Date.parse(item.created_at) : -Infinity}}); add(body, row);
  }
  applyFilters(); add(table, add(el("thead"), head), body); add(wrap, table); return add(card, wrap);
}
function renderCampaignOverview() {
  const main = clear($("main"));
  add(main, el("div", "eyebrow", "Campaña"), el("h1", "", state.campaign),
    el("p", "muted", `${state.orderList.orders.length} órdenes · ${state.orderList.status}`), campaignTabs());
  const problems = errorBlock(state.orderList.errors); if (problems) add(main, problems);
  add(main, state.campaignView === "summary" ? campaignSummaryView() :
    state.campaignView === "incidents" ? campaignIncidentTable() :
    state.campaignView === "costs" ? campaignCostView() : campaignOrderTable());
}
async function openOrder(file, focus = null) {
  try {
    state.navigationView = "orders"; state.diagnostic = null; renderNavigation();
    state.diagnostic = await api(`/api/campaigns/${enc(state.campaign)}/orders/${enc(file)}`);
    state.assertionId = focus?.assertion_id || state.diagnostic.order.assertions[0]?.assertion_id || null;
    state.runId = focus?.run_id || state.diagnostic.validations.find(v => v.assertion_id === state.assertionId)?.run_id || null;
    state.stage = focus?.stage || "generation"; state.view = focus?.view || (focus ? "detail" : "summary"); renderNavigation(); renderDetail();
  } catch (error) { showError(error.message); }
}
function metric(value, label) { return add(el("div", "metric"), el("strong", "", value), el("span", "", label)); }
function metricButton(value, label, onClick) {
  const node = button("", onClick, "metric metric-button");
  node.setAttribute("aria-label", `${value} ${label}`);
  return add(node, el("strong", "", value), el("span", "", label));
}
function currentValidation() { return state.diagnostic?.validations.find(v => v.run_id === state.runId) ?? null; }
function stageData() { return state.stage === "generation" ? state.diagnostic.order.generation : currentValidation()?.stages[state.stage]; }
function selectAssertion(id) {
  state.assertionId = id;
  state.runId = state.diagnostic.validations.find(v => v.assertion_id === id)?.run_id ?? null;
  state.stage = state.runId ? "router" : "generation"; renderDetail();
}
function selectRun(id) { state.runId = id; state.stage = "router"; renderDetail(); }

function validatorSummary(validatorId) {
  const rows = state.diagnostic.validations.filter(item => item.validator_id === validatorId);
  return {
    total: rows.length,
    correct: rows.filter(item => item.stages.llm.assessment === "PASS").length,
    incorrect: rows.filter(item => item.stages.llm.assessment === "FAIL").length,
    abstentions: rows.filter(item => item.stages.llm.observations?.effective_verdict === "UNKNOWN").length,
    citationFailures: rows.filter(item => item.stages.citations.assessment === "FAIL").length,
    technicalErrors: rows.filter(item => (item.stages.llm.observations?.errors || []).length ||
      item.stages.llm.checks.some(check => ["TECHNICAL_ERROR", "INVALID_RESPONSE"].includes(check.code))).length
  };
}

function stageIssueChecks(stageKey, stage) {
  const issueChecks = (stage.checks || []).filter(check => ["FAIL", "PARTIAL"].includes(check.status));
  if (issueChecks.length) return issueChecks;
  const routerMismatch = stageKey === "router" && (stage.observations?.acceptable_domains || []).length &&
    (stage.observations?.sources || []).length &&
    !(stage.observations?.matching_domains || []).length;
  if (routerMismatch) return [routerMisalignmentCheck(stage)];
  if (stage.assessment === "FAIL")
    return [{code: "MODULE_FAILED", status: "FAIL", detail: stage.missing_reason || "La causa no quedó registrada en el artefacto.", type: "error"}];
  return [];
}

function failureRows(diagnostic) {
  const rows = [];
  const seenConsensus = new Set();
  const assertions = new Map(diagnostic.order.assertions.map(item => [item.assertion_id, item]));
  const generated = diagnostic.order.generation.observations?.generated_assertions || [];
  function addStage(stage, stageKey, assertionId = null, validation = null) {
    if (!stage || !["FAIL", "PARTIAL"].includes(stage.assessment)) return;
    const checks = stageIssueChecks(stageKey, stage);
    for (const check of checks) {
      let resolvedAssertionId = assertionId;
      if (!resolvedAssertionId && stageKey === "generation") {
        const ref = (check.observation_refs || []).find(value => /generated_assertions\/\d+$/.test(value));
        const match = ref && ref.match(/(\d+)$/);
        resolvedAssertionId = match ? generated[Number(match[1])]?.assertion_id : null;
      }
      const assertion = assertions.get(resolvedAssertionId);
      const duplicateKey = stageKey === "consensus" ? `${resolvedAssertionId}:${check.code}:${check.detail}` : null;
      if (duplicateKey && seenConsensus.has(duplicateKey)) continue;
      if (duplicateKey) seenConsensus.add(duplicateKey);
      const metadata = inferredIssueMetadata(stageKey, check);
      rows.push({stageKey, assertionId: resolvedAssertionId,
        assertionText: assertion?.text || generated.find(item => item.assertion_id === resolvedAssertionId)?.text || "—",
        caseId: assertion?.expected_case_id || "—", validatorId: validation?.validator_id || "—",
        runId: validation?.run_id || null, executionStatus: stage.execution_status,
        assessment: stage.assessment, code: check.code || "—", detail: explainIssue(stageKey, check, stage, validation),
        type: inferredIssueType(stageKey, check, stage), ...metadata,
        rootCauseId: check.root_cause_id || null, recommendedAction: check.recommended_action || null});
    }
  }
  addStage(diagnostic.order.generation, "generation");
  for (const validation of diagnostic.validations)
    for (const [stageKey, stage] of Object.entries(validation.stages))
      addStage(stage, stageKey, validation.assertion_id, validation);
  return rows;
}

function validatorAlias(index) { return `Validador ${String.fromCharCode(65 + index)}`; }
function voteTone(vote, expected) {
  if (vote?.error) return "FAIL";
  if (!vote || vote.verdict === "UNKNOWN") return "NOT_EVALUATED";
  if (["TRUE", "FALSE"].includes(expected)) return vote.verdict === expected ? "PASS" : "FAIL";
  return "NOT_EVALUATED";
}
function openSummaryCell(assertionId, validatorId) {
  const validation = state.diagnostic.validations.find(item =>
    item.assertion_id === assertionId && item.validator_id === validatorId);
  state.assertionId = assertionId;
  state.runId = validation?.run_id || null;
  state.stage = validation ? "llm" : "consensus";
  state.view = "detail";
  renderDetail();
}
function renderOrderSummary(diagnostic) {
  const summary = diagnostic.viewer_summary || {};
  const block = el("div", "stack");
  const [outcomeLabel, outcomeTone] = outcomePresentation(summary.outcome);
  const [healthLabel, healthTone] = healthPresentation(summary.health);
  const hero = add(el("section", `card outcome-hero status-${outcomeTone}`),
    add(el("div", "detail-head"), add(el("div"), el("h2", "", `Resultado E2E: ${outcomeLabel}`),
      el("p", "", `${summary.assertions_achieved ?? 0} de ${summary.assertions_total ?? 0} aserciones alcanzaron el resultado esperado mediante consenso.`)),
      labeledPill(outcomeLabel, outcomeTone)),
    add(el("p", "health-line"), labeledPill(healthLabel, healthTone),
      el("span", "", summary.health === "DEGRADED" ?
        ` El objetivo final se conserva, pero hubo ${summary.abstentions ?? 0} abstenciones, ${summary.contradictions ?? 0} contradicciones y ${summary.technical_errors ?? 0} errores técnicos.` :
        " La salud operativa se presenta separada del resultado final.")));
  add(block, hero, add(el("section", "summary overview-metrics"),
    metric(`${summary.assertions_achieved ?? 0}/${summary.assertions_total ?? 0}`, "aserciones correctas por consenso"),
    metric(summary.validators_observed ?? 0, "validadores observados"),
    metric(`${summary.decisive_votes ?? 0}/${summary.assigned_votes ?? 0}`, "votos decisivos / asignados"),
    metric(summary.abstentions ?? 0, "abstenciones"),
    metric(summary.contradictions ?? 0, "contradicciones"),
    metric(summary.consensus_rescues ?? 0, "aserciones rescatadas por consenso")));

  const validators = summary.validators || [];
  const matrixCard = add(el("section", "card"), el("h2", "", "Aserciones × validadores"),
    el("p", "muted", "Las columnas se generan a partir de los validadores observados en esta orden; no existe un número fijo."));
  if (!(summary.assertions || []).length) add(matrixCard, el("p", "muted", "La orden no contiene aserciones resumibles."));
  else {
    const wrap = el("div", "table-wrap validator-matrix-wrap"), table = el("table", "validator-matrix"), head = el("tr"), body = el("tbody");
    add(head, el("th", "sticky-column", "Aserción"), el("th", "", "Esperado"), el("th", "", "Consenso"));
    validators.forEach((validator, index) => {
      const cell = el("th", "validator-matrix-head", validatorAlias(index));
      cell.title = validator.validator_id;
      add(cell, el("small", "mono", validator.validator_id),
        el("small", "validator-kind", validatorKindLabel(validator.metadata))); add(head, cell);
    });
    add(head, el("th", "", "Cobertura"));
    for (const assertion of summary.assertions) {
      const consensusTone = assertion.consensus_assessment === "PASS" ? "PASS" :
        assertion.consensus_assessment === "FAIL" ? "FAIL" : "NOT_EVALUATED";
      const assertionCell = add(el("td", "sticky-column assertion-summary-cell"),
        el("strong", "", `Aserción ${assertion.assertion_id}`),
        el("span", "", assertion.text), el("small", "", assertion.case_id || "Sin caso emparejado"));
      const row = add(el("tr"), assertionCell, el("td", "", assertion.expected_verdict || "—"),
        add(el("td"), labeledPill(assertion.consensus_verdict || "No resuelto", consensusTone)));
      for (const validator of validators) {
        const vote = assertion.votes.find(item => item.validator_id === validator.validator_id);
        const cell = el("td", "validator-vote-cell");
        const verdict = vote?.verdict || "Sin respuesta";
        const validation = diagnostic.validations.find(item => item.assertion_id === assertion.assertion_id &&
          item.validator_id === validator.validator_id);
        const content = validation ? button("", () => openSummaryCell(assertion.assertion_id, validator.validator_id), "vote-button") :
          el("div", "vote-button vote-unavailable");
        add(content, labeledPill(verdict, voteTone(vote, assertion.expected_verdict)),
          el("small", "", vote?.error ? "Error" : verdict === "UNKNOWN" ? "Abstención" : vote ? "Voto decisivo" : "No observado"));
        if (!validation) content.title = "No hay ejecución detallada guardada para esta combinación";
        add(cell, content); add(row, cell);
      }
      const coverage = assertion.assigned ? `${assertion.decisive}/${assertion.assigned}` : "—";
      add(row, add(el("td", "compact-column"), el("strong", "", coverage),
        el("small", "", assertion.rescued_by_consensus ? "Compensado por consenso" : assertion.reason_code || "—")));
      add(body, row);
    }
    add(table, add(el("thead"), head), body); add(wrap, table); add(matrixCard, wrap);
  }
  add(block, matrixCard);

  const validatorCard = add(el("section", "card"), el("h2", "", "Resumen por validador"));
  if (!validators.length) add(validatorCard, el("p", "muted", "No hay validadores observados en esta orden."));
  else {
    const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
    for (const label of ["Validador", "Tipo / estrategia", "Asignaciones", "Decisivas", "Acordes", "Abstenciones", "Contradicciones", "Incidencias", "Errores", "Salud"])
      add(head, el("th", "", label));
    validators.forEach((validator, index) => {
      const [label, tone] = healthPresentation(validator.health);
      const identity = add(el("td", "validator-identity"), el("strong", "", validatorAlias(index)),
        el("small", "mono", validator.validator_id));
      add(body, add(el("tr"), identity, el("td", "validator-kind", validatorKindLabel(validator.metadata)), el("td", "", validator.assigned_assertions),
        el("td", "", validator.decisive), el("td", "", validator.expected_matches),
        el("td", "", validator.abstentions), el("td", "", validator.contradictions),
        el("td", "", validator.stage_issues), el("td", "", validator.errors),
        add(el("td"), labeledPill(label, tone))));
    });
    add(table, add(el("thead"), head), body); add(wrap, table); add(validatorCard, wrap);
  }
  add(block, validatorCard, el("p", "muted roster-note", summary.roster_source === "observed" ?
    "Participación reconstruida desde las validaciones y votos guardados. Un artefacto antiguo puede no distinguir un validador no asignado de uno que nunca llegó a responder." : ""));
  return block;
}

function renderViewTabs() {
  const tabs = el("div", "view-tabs");
  const summary = button("Resumen", () => { state.view = "summary"; renderDetail(); }, state.view === "summary" ? "active" : "");
  const detail = button("Detalle", () => { state.view = "detail"; renderDetail(); }, state.view === "detail" ? "active" : "");
  const failures = button("Diagnóstico", () => { state.view = "failures"; renderDetail(); }, state.view === "failures" ? "active" : "");
  const costs = button("Costes", () => { state.view = "costs"; renderDetail(); }, state.view === "costs" ? "active" : "");
  for (const [node, selected] of [[summary, state.view === "summary"], [detail, state.view === "detail"], [failures, state.view === "failures"], [costs, state.view === "costs"]]) {
    node.setAttribute("role", "tab"); node.setAttribute("aria-selected", String(selected));
  }
  return add(tabs, summary, detail, failures, costs);
}

function renderOrderCosts(diagnostic) {
  const costs = diagnostic.costs || {};
  const block = el("div", "stack");
  add(block, add(el("section", "summary overview-metrics"),
    metric(knownMoney(costs), "coste conocido"),
    metric(!costs.events ? "Sin datos" : costs.total_usd === null ? "Incompleto" : money(costs.total_usd), "total de orden"),
    metric(costs.events ?? 0, "eventos"), metric(costs.unknown_events ?? 0, "sin coste"),
    metric(tokenSummary(costs), "tokens entrada / salida")));
  const card = add(el("section", "card"), el("h2", "", "Registro de consumos"),
    el("p", "muted", "Una fila por llamada observada. Las filas sin uso o tarifa quedan pendientes de valorar."));
  const table = el("table"), body = el("tbody");
  add(table, add(el("thead"), add(el("tr"), ...["Orden / validador / llamada", "Componente", "Proveedor / modelo", "Tokens E / S", "Tarifa", "Coste entrada", "Coste salida", "Búsqueda", "Coste", "Estado"].map(v => el("th", "", v)))), body);
  function aggregateRow(label, summary, className = "") {
    return add(el("tr", className), el("th", "", label), el("td", "", `${summary.events ?? 0} eventos`),
      el("td", "", `${summary.unknown_events ?? 0} sin coste`), el("td", "", tokenSummary(summary)), el("td", "", "—"),
      el("td", "", llmMoney(summary, "input_cost_usd")), el("td", "", llmMoney(summary, "output_cost_usd")),
      el("td", "", searchMoney(summary)), el("td", "", knownMoney(summary)),
      el("td", "", summary.total_usd === null ? "Incompleto" : money(summary.total_usd)));
  }
  add(body, aggregateRow("ORDEN · todos los componentes", costs, "cost-order-row"));
  function eventRow(event) {
    const used = event.usage ? `${event.usage.input_tokens} entrada · ${event.usage.output_tokens} salida` :
      `${event.quantity} ${event.unit}`;
    const rate = event.rate?.usd_per_call !== undefined ?
      `${event.rate.usd_per_call} USD/llamada${event.rate.usd_per_additional_result !== undefined ?
        ` + ${event.rate.usd_per_additional_result} USD/resultado > ${event.rate.included_results}` : ""}` :
      event.rate?.input_usd_per_million_tokens !== undefined ?
        `${event.rate.input_usd_per_million_tokens} / ${event.rate.output_usd_per_million_tokens} USD/M tokens` : "—";
    return add(el("tr", event.run_id === state.runId ? "selected-row" : ""),
      el("td", "mono", event.run_id ? `${event.assertion_id} · ${event.validator_id}` : "Orden"),
      el("td", "", event.component), el("td", "", `${event.provider || "—"}${event.model ? ` / ${event.model}` : ""}`),
      el("td", "", used), el("td", "", rate), el("td", "", money(event.input_cost_usd)), el("td", "", money(event.output_cost_usd)),
      el("td", "", event.component.endsWith("_llm") ? "—" : money(event.cost_usd)),
      el("td", "", money(event.cost_usd)), el("td", "", event.reason || event.basis));
  }
  const generationEvents = (costs.ledger || []).filter(event => !event.validator_id);
  if (generationEvents.length) {
    add(body, aggregateRow("Generación", costs.generation, "cost-order-row"));
    for (const event of generationEvents) add(body, eventRow(event));
  }
  for (const group of costs.validators || []) {
    const children = (costs.ledger || []).filter(event => event.validator_id === group.validator_id).map(eventRow);
    const label = button(`▸ Validador ${group.validator_id} · ${group.validations.length} validaciones`, () => {
      const expanded = children.some(row => row.hidden);
      for (const row of children) row.hidden = !expanded;
      label.textContent = `${expanded ? "▾" : "▸"} Validador ${group.validator_id} · ${group.validations.length} validaciones`;
      label.setAttribute("aria-expanded", String(expanded));
    }, "mono");
    label.setAttribute("aria-expanded", "false");
    const summary = aggregateRow("", group, "cost-order-row");
    summary.firstChild.replaceWith(add(el("th"), label));
    add(body, summary);
    for (const row of children) { row.hidden = true; add(body, row); }
  }
  add(card, add(el("div", "table-wrap"), table));
  if (!body.children.length) add(card, el("p", "muted", "No hay consumos registrados en esta orden."));
  return add(block, card);
}

function openFailure(row) {
  state.view = "detail";
  if (row.assertionId) state.assertionId = row.assertionId;
  state.runId = row.runId || (row.assertionId ? state.diagnostic.validations.find(item => item.assertion_id === row.assertionId)?.run_id : null);
  state.stage = row.stageKey;
  renderDetail();
}

function renderFailureSummary(diagnostic) {
  const rows = failureRows(diagnostic).filter(row =>
    (!state.filters.caseId || row.caseId === state.filters.caseId) &&
    (!state.filters.validator || row.validatorId === state.filters.validator) &&
    (!state.filters.stage || row.stageKey === state.filters.stage) &&
    (!state.filters.code || row.code === state.filters.code) &&
    (!state.filters.type || row.type === state.filters.type) &&
    (!state.filters.origin || row.origin === state.filters.origin) &&
    (!state.filters.nature || row.nature === state.filters.nature) &&
    (!state.filters.severity || row.severity === state.filters.severity) &&
    (!state.filters.impact || row.impact === state.filters.impact));
  const modules = new Set(rows.map(row => row.stageKey === "generation" ? "generation/order" :
    `${row.stageKey}/${row.assertionId || "order"}/${row.runId || "order"}`));
  const errors = rows.filter(row => row.type === "error").length;
  const warnings = rows.filter(row => row.type === "warning").length;
  const functional = rows.filter(row => ["FUNCTIONAL_FAILURE", "TECHNICAL_FAILURE"].includes(row.nature) && row.impact !== "METRICS_ONLY").length;
  const degradations = rows.filter(row => row.nature === "QUALITY_DEGRADATION").length;
  const policy = rows.filter(row => ["POLICY_CONSTRAINT", "BENCHMARK_DEVIATION"].includes(row.nature)).length;
  const evaluation = rows.filter(row => row.nature === "EVALUATION_UNCERTAINTY").length;
  const card = add(el("section", "card"), el("h2", "", "Diagnóstico de incidencias"),
    el("p", "muted", `${functional} incidencias funcionales · ${degradations} degradaciones · ${policy} desviaciones de política/benchmark · ${evaluation} incertidumbres de evaluación. ${modules.size} módulos · ${errors} errores · ${warnings} avisos.`));
  if (!rows.length) return add(card, el("p", "muted", "No hay errores ni avisos que coincidan con los filtros actuales."));
  const wrap = el("div", "table-wrap"), table = el("table", "failure-table"), head = el("tr"), body = el("tbody");
  for (const label of ["Tipo", "Origen", "Naturaleza", "Impacto", "Gravedad", "Módulo", "Aserción", "Caso", "Validador", "Estado", "Código", "Detalle"])
    add(head, el("th", "", label));
  for (const row of rows) {
    const module = STAGES.find(([key]) => key === row.stageKey)?.[1] || row.stageKey;
    const detail = row.recommendedAction ? `${row.detail} Acción: ${row.recommendedAction}` : row.detail;
    const tableRow = add(el("tr", "clickable-row"), add(el("td"), issueType(row.type)),
      el("td", "mono", row.origin), el("td", "mono", row.nature), el("td", "mono", row.impact),
      el("td", "mono", row.severity), el("td", "", module), el("td", "", row.assertionText),
      el("td", "", row.caseId), el("td", "mono", row.validatorId), add(el("td"), pill(row.assessment)),
      el("td", "mono", row.code), el("td", "", detail));
    tableRow.tabIndex = 0;
    tableRow.title = "Abrir el contexto de este fallo";
    tableRow.addEventListener("click", () => openFailure(row));
    tableRow.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openFailure(row); }
    });
    add(body, tableRow);
  }
  add(table, add(el("thead"), head), body); add(wrap, table); return add(card, wrap);
}

function renderDetail() {
  const d = state.diagnostic; const main = clear($("main"));
  add(main, el("div", "eyebrow", `${d.identity.campaign_id} / ${d.identity.dataset_id}`),
    el("h1", "", `Orden ${d.identity.order_id}`),
    el("p", "muted", `Repetición ${d.identity.repetition} · ${d.order.status}`));
  const metrics = el("div", "summary");
  const failedModules = (["FAIL", "PARTIAL"].includes(d.order.generation.assessment) ? 1 : 0) + d.validations.reduce((n, validation) =>
    n + Object.values(validation.stages).filter(stage => ["FAIL", "PARTIAL"].includes(stage.assessment)).length, 0);
  add(metrics, metric(d.order.assertions.length, "afirmaciones"),
    metric(d.validations.length, "validaciones"),
    metricButton(failedModules, "módulos con incidencias", () => { state.view = "failures"; renderDetail(); }));
  add(main, metrics, renderViewTabs());
  const problems = errorBlock(state.orderList?.errors); if (problems) add(main, problems);
  if (state.view === "summary") { add(main, renderOrderSummary(d)); return; }
  if (state.view === "costs") { add(main, renderOrderCosts(d)); return; }
  add(main, renderFilters());
  if (state.view === "failures") { add(main, renderFailureSummary(d)); return; }
  const layout = el("div", "grid"); const left = el("div", "stack");
  const originals = add(el("section", "card"), el("h2", "", "Texto original"), el("p", "", d.order.original_text));
  const choices = add(el("section", "card"), el("h2", "", "Afirmaciones"));
  const assertions = el("div", "selector");
  for (const assertion of d.order.assertions) {
    if (state.filters.caseId && assertion.expected_case_id !== state.filters.caseId) continue;
    const node = button(assertion.text || assertion.assertion_id,
      () => selectAssertion(assertion.assertion_id),
      assertion.assertion_id === state.assertionId ? "active" : "");
    add(node, el("small", "", `ID ${assertion.assertion_id}${assertion.expected_case_id ? ` · ${assertion.expected_case_id}` : ""}`));
    add(assertions, node);
  }
  if (!d.order.assertions.length) add(assertions, el("p", "muted", "La orden no generó afirmaciones."));
  add(choices, assertions); add(left, originals, choices);
  const right = el("div", "stack"); const validators = add(el("section", "card"), el("h2", "", "Validadores"));
  const selector = el("div", "selector");
  for (const validation of d.validations.filter(v => v.assertion_id === state.assertionId)) {
    if (state.filters.validator && validation.validator_id !== state.filters.validator) continue;
    const node = button(validation.validator_id, () => selectRun(validation.run_id),
      validation.run_id === state.runId ? "active" : "");
    const metadata = validation.validator || {};
    const llm = validation.stages.llm.observations || {};
    const summary = validatorSummary(validation.validator_id);
    add(node,
      el("small", "validator-kind", validatorKindLabel(metadata)),
      el("small", "", `${metadata.provider || llm.provider || "Proveedor no registrado"} / ${metadata.model || llm.model || "Modelo no registrado"}`),
      el("small", "validator-summary", `${summary.total} validaciones · ${summary.correct} acordes · ${summary.incorrect} no acordes · ${summary.abstentions} abstenciones · ${summary.citationFailures} fallos de cita · ${summary.technicalErrors} errores técnicos`),
      el("small", "", `Run ${validation.run_id}`)); add(selector, node);
  }
  if (!selector.childElementCount) add(selector, el("p", "muted", "Sin validaciones para esta afirmación."));
  add(validators, selector); add(right, validators);
  const flow = add(el("section", "card"), el("h2", "", "Cadena de ejecución"));
  const chain = el("div", "chain");
  STAGES.forEach(([key, label], index) => {
    if (state.filters.stage && key !== state.filters.stage) return;
    const stage = key === "generation" ? d.order.generation : currentValidation()?.stages[key];
    const presentation = stagePresentation(stage, key);
    if (index) add(chain, el("span", "arrow", "→"));
    const node = button("", () => { state.stage = key; renderDetail(); },
      `status status-${presentation.tone}${state.stage === key ? " active" : ""}`);
    add(node, el("strong", "", label), el("small", "stage-execution", presentation.execution),
      el("small", "stage-result", presentation.result));
    add(chain, node);
  });
  add(flow, chain); add(right, flow, renderStage());
  if (state.assertionId) add(right, renderComparisonControl());
  add(layout, left, right); add(main, layout);
}
function renderStage() {
  const selected = STAGES.find(([key]) => key === state.stage); const stage = stageData();
  const card = el("section", `card status status-${stage?.assessment || "SKIPPED"}`);
  const head = el("div", "detail-head"); const title = el("div");
  add(title, el("h2", "", selected?.[1] || state.stage),
    el("p", "", stage ? `Ejecución: ${stage.execution_status}` : "Elige un validador para ver esta etapa."));
  add(head, title, pill(stage?.assessment || "SKIPPED")); add(card, head);
  if (!stage) return card;
  if (stage.missing_reason) add(card, el("p", "muted", stage.missing_reason));
  if (state.stage === "generation") add(card, renderGeneration(stage.observations));
  if (state.stage === "router") add(card, renderRouter(stage.observations));
  if (state.stage === "evidence_search") add(card, renderEvidenceSearch(stage.observations));
  if (state.stage === "handoff") add(card, renderHandoff(stage.observations));
  if (state.stage === "llm") add(card, renderLlm(stage.observations));
  if (state.stage === "citations") add(card, renderCitations(stage.observations));
  if (state.stage === "consensus") add(card, renderConsensus(stage.observations));
  add(card, el("h3", "", "Comprobaciones"));
  const visibleChecks = stage.checks.length ? stage.checks : stageIssueChecks(state.stage, stage);
  if (!visibleChecks.length) add(card, el("p", "muted", "No hay comprobaciones registradas."));
  else {
    const wrap = el("div", "table-wrap"); const table = el("table"); const header = el("tr");
    for (const label of ["Estado", "Tipo", "Código", "Detalle"]) add(header, el("th", "", label));
    add(table, add(el("thead"), header)); const body = el("tbody");
    for (const check of visibleChecks.filter(item => !state.filters.code || item.code === state.filters.code)) add(body, add(el("tr"),
      add(el("td"), pill(check.status)), add(el("td"), issueType(inferredIssueType(state.stage, check, stage))),
      el("td", "", check.code), el("td", "", explainIssue(state.stage, check, stage, currentValidation()))));
    add(table, body); add(wrap, table); add(card, wrap);
  }
  const observations = el("details"); add(observations, el("summary", "", "Observaciones de la etapa"));
  observations.addEventListener("toggle", () => {
    if (observations.open && observations.childElementCount === 1)
      add(observations, el("pre", "", JSON.stringify(stage.observations, null, 2)));
  });
  add(card, observations);
  const raw = el("details", "raw"); add(raw, el("summary", "", "Abrir artefacto original"));
  const controls = el("div", "toolbar");
  const ref = state.stage === "generation" ? state.diagnostic.artifact_refs.order :
    state.diagnostic.artifact_refs.results.find(r => r.run_id === state.runId)?.path;
  const output = el("pre", "", "Selecciona el archivo para cargarlo bajo demanda.");
  if (ref) add(controls, button(ref, async () => {
    try { const value = await api(`/api/campaigns/${enc(state.campaign)}/artifacts/${enc(ref)}`);
      output.textContent = JSON.stringify(value, null, 2); }
    catch (error) { output.textContent = `No se pudo abrir ${ref}: ${error.message}`; }
  }));
  add(raw, controls, output); add(card, raw); return card;
}


function renderGeneration(observations) {
  const block = el("section");
  const info = el("div", "summary");
  const usages = (observations.usage || []).filter(item =>
    Number.isInteger(item?.prompt_tokens) && Number.isInteger(item?.completion_tokens));
  add(info, metric(recorded(observations.model), "modelo"),
    metric(recorded(observations.structured_attempts), "llamadas estructuradas"),
    metric(observations.repair_used == null ? "No registrado" : observations.repair_used ? "Sí" : "No", "reparación"),
    metric(recorded(observations.duration_seconds), "segundos"),
    metric(usages.length ? usages.reduce((sum, item) => sum + item.prompt_tokens, 0) : "No registrado", "tokens entrada"),
    metric(usages.length ? usages.reduce((sum, item) => sum + item.completion_tokens, 0) : "No registrado", "tokens salida"));
  if ([observations.structured_attempts, observations.repair_used, observations.duration_seconds].some(value => value == null))
    add(block, el("p", "muted", "La orden no contiene la traza completa de Generate Assertions. Estos valores no pueden reconstruirse de forma fiable."));
  add(block, info, el("h3", "", "Esperadas y generadas"));
  const expected = observations.expected_assertions || [];
  const generated = observations.generated_assertions || [];
  const matches = observations.matches || [];
  const used = new Set(matches.map(match => match.assertion_id));
  const wrap = el("div", "table-wrap"); const table = el("table"); const header = el("tr");
  for (const label of ["Referencia", "Generada", "Coincidencia", "Categoría / tema / evidencia"]) add(header, el("th", "", label));
  add(table, add(el("thead"), header)); const body = el("tbody");
  function row(reference, actual, match) {
    const tr = el("tr"); const referenceCell = el("td");
    add(referenceCell, el("strong", "", reference?.case_id || "Sin referencia"),
      el("p", "", reference?.text || "—"));
    if (reference?.source_excerpt) add(referenceCell, el("small", "muted", `Fragmento: ${reference.source_excerpt}`));
    const generatedCell = el("td");
    add(generatedCell, el("strong", "", actual?.assertion_id ? `#${actual.assertion_id}` : "Omitida"),
      el("p", "", actual?.text || "—"));
    if (actual) {
      const detail = el("details");
      add(detail, el("summary", "", "Contexto y consultas"),
        el("pre", "", JSON.stringify({context: actual.context, context_confidence: actual.context_confidence,
          search_hints: actual.search_hints}, null, 2)));
      add(generatedCell, detail);
    }
    add(tr, referenceCell, generatedCell,
      el("td", "", match ? `${match.method} · ${match.score}` : "Sin pareja"),
      el("td", "", actual ? `${actual.categoryId ?? "—"} / ${actual.topic_code || "—"} / ${actual.evidence_kind || "—"}` : "—"));
    add(body, tr);
  }
  for (const reference of expected) {
    const match = matches.find(item => item.case_id === reference.case_id);
    row(reference, generated.find(item => item.assertion_id === match?.assertion_id), match);
  }
  for (const actual of generated.filter(item => !used.has(item.assertion_id))) row(null, actual, null);
  add(table, body); add(wrap, table); add(block, wrap,
    el("p", "muted", "El emparejamiento por palabras es una heurística; la fidelidad semántica requiere revisión."));
  return block;
}


function renderRouter(observations) {
  const block = el("section"); const trace = observations.evaluation_trace || {};
  const summary = el("div", "summary");
  add(summary, metric(observations.route_state || (observations.skip_reason ? "No aplica" : "No registrado"), "estado de ruta"),
    metric(recorded(observations.evidence_search_strategy), "estrategia"),
    metric(trace.cache_hit == null ? "No registrado" : trace.cache_hit ? "Sí" : "No", "caché"),
    metric((observations.sources || []).length, "dominios elegidos"),
    metric(observations.diagnostic_code || "—", "diagnóstico"));
  add(block, summary);
  if (trace.cache_lookup) add(block, el("p", "muted", `Consulta de caché: ${trace.cache_lookup} · procedencia del diagnóstico: ${trace.diagnostics_origin || "—"}${trace.refresh_error_type ? ` · error de refresco: ${trace.refresh_error_type}` : ""}`));
  const queries = trace.planned_queries || [];
  add(block, el("h3", "", "Consultas de descubrimiento"));
  if (!queries.length) add(block, el("p", "muted", "La consulta exacta no quedó registrada en esta orden."));
  else {
    const wrap = el("div", "table-wrap"); const table = el("table"); const header = el("tr");
    for (const label of ["Consulta prevista", "Ejecutada en esta orden"]) add(header, el("th", "", label));
    add(table, add(el("thead"), header)); const body = el("tbody");
    for (const query of queries) add(body, add(el("tr"),
      el("td", "", query.query), el("td", "", query.executed === null ? "No registrado" : query.executed ? "Sí" : "No")));
    add(table, body); add(wrap, table); add(block, wrap);
  }
  const discovery = trace.query_execution || [];
  if (discovery.length) {
    add(block, el("h3", "", "URLs devueltas por el proveedor"));
    const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
    for (const label of ["Consulta / proveedor", "Estado", "URL", "Dominio", "Decisión"]) add(head, el("th", "", label));
    for (const query of discovery) {
      if (!query.result_decisions?.length) add(body, add(el("tr"),
        el("td", "", `${query.query} · ${query.provider}`), el("td", "", query.status || "—"),
        el("td", "", "—"), el("td", "", "—"), el("td", "", query.error_type || query.outcome || "—")));
      for (const result of query.result_decisions || []) add(body, add(el("tr"),
        el("td", "", `${query.query} · ${query.provider}`), el("td", "", query.status || "—"),
        el("td", "", result.url || "—"), el("td", "", result.domain || "—"),
        el("td", "", result.decision || "—")));
    }
    add(table, add(el("thead"), head), body); add(wrap, table); add(block, wrap);
  }
  const classifications = trace.classification || [];
  if (classifications.length) {
    add(block, el("h3", "", "Clasificación y elegibilidad"));
    const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
    for (const label of ["Dominio", "Tipo / autoridad", "Jurisdicciones", "Decisión", "Puntuación base"]) add(head, el("th", "", label));
    for (const item of classifications) {
      const score = el("details");
      add(score, el("summary", "", item.classification_score ?? Object.values(item.score_components || {}).reduce((n, value) => n + Number(value || 0), 0).toFixed(4)),
        el("pre", "", JSON.stringify(item.score_components || {}, null, 2)));
      add(body, add(el("tr"), el("td", "", item.domain || "—"),
        el("td", "", `${item.source_type || "—"} / ${item.authority_level || "—"}`),
        el("td", "", (item.jurisdictions || []).map(value => value.scope + ":" + (value.region_code || value.country_code || value.jurisdiction_code || "—")).join(", ") || "—"),
        el("td", "", item.eligible ? "Apto" : (item.rejection_reasons || []).join(", ") || "Rechazado"), add(el("td"), score)));
    }
    add(table, add(el("thead"), head), body); add(wrap, table); add(block, wrap);
  }
  const persistedRejections = observations.diagnostics?.rejected_domain_details || [];
  if (!classifications.length && persistedRejections.length) {
    add(block, el("h3", "", "Motivos de rechazo por dominio"));
    const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
    for (const label of ["Dominio", "Motivos"]) add(head, el("th", "", label));
    for (const item of persistedRejections) add(body, add(el("tr"),
      el("td", "", item.domain || "—"),
      el("td", "", (item.reasons || []).join(", ") || "Motivo no registrado")));
    add(table, add(el("thead"), head), body); add(wrap, table); add(block, wrap);
  }
  const ranking = trace.ranking || [];
  if (ranking.length) {
    add(block, el("h3", "", "Ranking y límite de fuentes"));
    const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
    for (const label of ["Dominio", "Base", "Idioma", "Total", "Posición", "Decisión"]) add(head, el("th", "", label));
    for (const item of [...ranking].sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))) add(body, add(el("tr"), el("td", "", item.domain || "—"),
      el("td", "", item.base_score ?? "—"), el("td", "", item.language_bonus ?? "—"),
      el("td", "", item.route_score ?? "—"), el("td", "", item.rank ?? "—"), el("td", "", item.decision || "—")));
    add(table, add(el("thead"), head), body); add(wrap, table); add(block, wrap);
  }
  if (trace.profile_fallback_candidates?.length) {
    const details = el("details"); add(details, el("summary", "", "Perfiles de fallback considerados"),
      el("pre", "", JSON.stringify(trace.profile_fallback_candidates, null, 2))); add(block, details);
  }
  if (trace.failed_domains?.length) add(block, el("p", "muted", `Sin clasificación válida: ${trace.failed_domains.join(", ")}. El proveedor no dejó un motivo individual verificable.`));
  if (trace.preserved_domains?.length) add(block, el("p", "muted", `Candidatos conservados de la ruta anterior: ${trace.preserved_domains.join(", ")}.`));
  add(block, el("h3", "", "Dominios seleccionados"));
  const wrap = el("div", "table-wrap"); const table = el("table"); const head = el("tr");
  for (const label of ["Pos.", "Dominio", "Tipo / autoridad", "Puntuación", "Motivo"]) add(head, el("th", "", label));
  add(table, add(el("thead"), head)); const body = el("tbody");
  for (const source of observations.sources || []) add(body, add(el("tr"),
    el("td", "", source.rank ?? "—"), el("td", "", source.domain || "—"),
    el("td", "", `${source.source_type || "—"} / ${source.authority_level || "—"}`),
    el("td", "", source.route_score ?? "—"), el("td", "", `${source.reason || "—"}${observations.acceptable_domains?.length ? ` · ${observations.matching_domains?.includes(source.domain) ? "aceptable" : "fuera de referencia"}` : " · sin referencia"}`)));
  add(table, body); add(wrap, table); add(block, wrap);
  add(block, el("h3", "", "Dominios esperados"));
  const expected = observations.expected_domain_matches || (observations.acceptable_domains || []).map(domain => ({domain, matching_selected_domains: []}));
  if (!expected.length) add(block, el("p", "muted", "No hay dominios esperados anotados en el dataset; la calidad de la selección no puede evaluarse."));
  else {
    const expectedWrap = el("div", "table-wrap"), expectedTable = el("table"), expectedHead = el("tr"), expectedBody = el("tbody");
    for (const label of ["Dominio esperado", "Coincidencias seleccionadas", "Resultado"]) add(expectedHead, el("th", "", label));
    for (const item of expected) {
      const matches = item.matching_selected_domains || [];
      add(expectedBody, add(el("tr"), el("td", "", item.domain), el("td", "", matches.join(", ") || "Ninguna"),
        add(el("td"), matches.length ? pill("PASS") : issueType("warning"))));
    }
    add(expectedTable, add(el("thead"), expectedHead), expectedBody); add(expectedWrap, expectedTable); add(block, expectedWrap);
  }
  const diagnostics = observations.diagnostics || {};
  const lists = el("div", "summary");
  for (const [key, label] of [["discovered_domains", "descubiertos"], ["classified_domains", "clasificados"],
    ["rejected_domains", "rechazados"], ["failed_domains", "sin clasificar"], ["fallback_domains", "fallback"]]) {
    const values = diagnostics[key] || [];
    add(lists, metric(values.length, label));
  }
  add(block, lists);
  add(block, el("p", "muted", observations.acceptable_domains?.length ?
    `Dominios aceptables anotados: ${observations.acceptable_domains.join(", ")}` :
    "Sin dominios aceptables anotados: corrección de ruta no evaluada."));
  const details = el("details");
  add(details, el("summary", "", "Listas de diagnóstico y procedencia"),
    el("pre", "", JSON.stringify({diagnostics, evaluation_trace: trace}, null, 2)));
  add(block, details);
  if (!observations.evaluation_trace) add(block,
    el("p", "muted", "Esta orden no contiene traza detallada de Router."));
  else if (trace.execution_detail === "NOT_EXECUTED_CACHE") add(block,
    el("p", "muted", "Se reutilizó una ruta fresca. Las consultas y los motivos históricos individuales no se ejecutaron ni se guardaron en esta orden."));
  return block;
}

function renderEvidenceSearch(observations) {
  const block = el("section"); const trace = observations.evaluation_trace || {};
  const providerTrace = observations.provider_trace || {};
  const sources = observations.evidences || observations.sources || [];
  const currentRequests = providerTrace.requests || trace.query_execution || [];
  const cachedOriginRequests = providerTrace.cached_origin_requests || [];
  const legacyRequests = !currentRequests.length && !cachedOriginRequests.length ?
    (observations.queries_executed || observations.queries || []) : [];
  const requests = currentRequests.length ? currentRequests : cachedOriginRequests.length ? cachedOriginRequests : legacyRequests;
  const isCachedOrigin = !currentRequests.length && cachedOriginRequests.length > 0;
  let inferredCallSequence = 0;
  const renderedRequests = requests.map((item, index) => {
    const actualCall = Boolean(item.provider_call_id) || ["EXECUTED", "FAILED"].includes(item.status);
    if (actualCall) inferredCallSequence += 1;
    return {...item, _index: index, _callSequence: item.call_sequence || (actualCall ? inferredCallSequence : null),
      _callId: item.provider_call_id || (actualCall ? `${item.provider || providerTrace.provider || "provider"}-${inferredCallSequence}` : null)};
  });
  const actualCalls = renderedRequests.filter(item => item._callId);
  const executed = actualCalls.filter(item => item.status === "EXECUTED").length;
  const failed = actualCalls.filter(item => item.status === "FAILED").length;
  const skipped = renderedRequests.filter(item => item.status === "SKIPPED").length;
  const activeSummary = isCachedOrigin ? providerTrace.cached_origin_summary : providerTrace.summary;
  const returned = activeSummary?.urls_returned ?? actualCalls.reduce((total, item) => total + (item.returned_urls || []).length, 0);
  const uniqueReturned = activeSummary?.unique_urls_returned ?? new Set(actualCalls.flatMap(item => item.returned_urls || []).filter(Boolean)).size;
  const callsValue = observations.cached ? 0 : providerTrace.capture_status === "NOT_RECORDED_LEGACY_CACHE" ? "—" :
    actualCalls.length || (requests.length ? "No registrado" : "—");
  add(block, add(el("div", "summary"),
    metric(providerTrace.provider || actualCalls[0]?.provider || "No registrado", "proveedor"),
    metric(callsValue, "llamadas en esta validación"),
    metric(actualCalls.length ? `${executed} / ${failed}` : "—", isCachedOrigin ? "correctas / fallidas (origen)" : "correctas / fallidas"),
    metric(skipped, "consultas omitidas"),
    metric(returned, "URLs devueltas"), metric(uniqueReturned, "URLs únicas"),
    metric(sources.length, "evidencias conservadas"),
    metric(observations.cached == null ? "—" : observations.cached ? "Sí" : "No", "caché")));
  if (observations.cached) add(block, el("p", "trace-note",
    cachedOriginRequests.length ?
      `Esta validación realizó 0 llamadas al proveedor. La procedencia mostrada corresponde a las ${actualCalls.length} llamadas de la recuperación que originó la entrada de caché.` :
      "Esta validación realizó 0 llamadas al proveedor. La entrada de caché es antigua y no conserva la traza de su recuperación original."));
  else if (!providerTrace.capture_status && !trace.query_execution) add(block,
    el("p", "trace-note", "El número de llamadas no quedó registrado; las consultas mostradas son el plan de búsqueda y no prueban que se ejecutaran."));
  if (trace.limits) add(block, el("p", "muted", `Límites: ${trace.limits.max_results} URLs, ${trace.limits.max_contexts_per_source} contextos/fuente, ${trace.limits.max_contexts_total} contextos/global; ventana ±${trace.limits.window_before}/${trace.limits.window_after} chunks; tamaño ${trace.limits.chunk_size_chars}, solape ${trace.limits.chunk_overlap_chars} caracteres.`));
  add(block, el("h3", "", isCachedOrigin ? "Llamadas de la recuperación original" : "Llamadas al proveedor"));
  if (!renderedRequests.length) add(block, el("p", "muted", "No hay consultas registradas en esta orden."));
  else {
    const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
    for (const label of ["Llamada", "Proveedor", "Inicio", "Consulta", "Modo / filtros", "Estado", "Resultados", "Duración"]) add(head, el("th", "", label));
    for (const item of renderedRequests) {
      const relaxation = item.relaxation_level ?
        ` · relajación ${item.relaxation_level}${item.removed_terms?.length ? ` · retirado: ${item.removed_terms.join(", ")}` : ""}` : "";
      const row = el("tr");
      if (item._callId) row.id = `provider-call-${item._callId}`;
      const callLabel = item._callSequence ? `#${item._callSequence}` : item.status === "SKIPPED" ? "— (omitida)" : "—";
      add(body, add(row, el("td", item._callId ? "call-number" : "muted", callLabel),
        el("td", "", item.provider || providerTrace.provider || "—"),
        el("td", "", item.started_at ? formatSavedDate(item.started_at) : "—"), el("td", "", item.query || "—"),
        el("td", "", `${item.mode || item.provider || "—"} · ${(item.include_domains || []).join(", ") || item.external_source_policy || "sin filtro"}${relaxation}`),
        el("td", "", `${item.status || (observations.cached ? "NO EJECUTADA (caché)" : "No registrado")}${item.error_type ? ` · ${item.error_type}` : ""}`),
        el("td", "", item.result_count == null ? (item.error_type || "—") : `${item.result_count} devueltas · ${item.retained_result_count ?? "—"} conservadas`),
        el("td", "", item.duration_ms == null ? "—" : `${item.duration_ms} ms`)));
    }
    add(table, add(el("thead"), head), body); add(wrap, table); add(block, wrap);
  }
  const urls = new Map();
  for (const item of actualCalls) {
    const decisions = item.result_decisions || (item.returned_urls || []).map(url => ({url, decision: "DEVUELTA"}));
    for (const result of decisions) {
      const url = result.url || "";
      if (!url) continue;
      if (!urls.has(url)) urls.set(url, {url, appearances: []});
      urls.get(url).appearances.push({callId: item._callId, callSequence: item._callSequence,
        decision: result.decision, rank: result.provider_rank});
    }
  }
  if (urls.size) {
    add(block, el("h3", "", "URLs devueltas y llamadas de origen"));
    const wrap = el("div", "table-wrap"), table = el("table", "provider-url-table"), head = el("tr"), body = el("tbody");
    for (const label of ["URL", "Llamadas", "Primera aparición", "Decisiones"]) add(head, el("th", "", label));
    for (const item of urls.values()) {
      const calls = el("td", "call-links");
      for (const appearance of item.appearances) {
        const link = el("a", "call-chip", `#${appearance.callSequence}`);
        link.href = `#provider-call-${appearance.callId}`;
        link.title = appearance.callId;
        add(calls, link);
      }
      const first = item.appearances[0];
      add(body, add(el("tr"), el("td", "mono", item.url), calls,
        el("td", "", first ? `#${first.callSequence}` : "—"),
        el("td", "", item.appearances.map(entry =>
          `#${entry.callSequence}${entry.rank ? ` rango ${entry.rank}` : ""}: ${entry.decision || "—"}`).join(" · "))));
    }
    add(table, add(el("thead"), head), body); add(wrap, table); add(block, wrap);
  }
  if (trace.policy_drops?.length) add(block, el("p", "muted", `Descartes por política: ${trace.policy_drops.map(item => `${item.url} (${item.reason})`).join("; ")}`));
  if (observations.reference_evidence?.length) {
    add(block, el("h3", "", "Evidencia de referencia anotada"));
    const list = el("ul");
    for (const item of observations.reference_evidence) add(list, el("li", "", `${item.relation || "—"} · ${item.source || "—"}: ${item.text || "—"}`));
    add(block, list);
  }
  add(block, el("h3", "", "Fuentes recuperadas"));
  if (!sources.length) add(block, el("p", "muted", "No se conservaron fuentes."));
  for (const source of sources) {
    const panel = el("details", "source-panel");
    const derivedCallIds = renderedRequests.filter(item =>
      (item.returned_urls || []).includes(source.url)).map(item => item._callId).filter(Boolean);
    const sourceCallIds = source.provider_call_ids?.length ? source.provider_call_ids : derivedCallIds;
    const callLabels = sourceCallIds.map(callId => {
      const request = renderedRequests.find(item => item._callId === callId);
      return request?._callSequence ? `#${request._callSequence}` : callId;
    });
    add(panel, el("summary", "", `${source.source_id || "—"} · ${source.url || "Sin URL"} · llamadas ${callLabels.join(", ") || "no registradas"} · ${source.fetch_status || "descarga no registrada"} · ${source.chunks_total ?? "—"} chunks`));
    const info = add(el("div", "summary"), metric(source.document_length_chars ?? "—", "caracteres"),
      metric(source.content_type || "—", "tipo"), metric(source.relationship_to_origin || "—", "relación con origen"),
      metric(callLabels.join(", ") || "No registradas", "llamadas de origen"),
      metric((source.contexts || []).length, "contextos"), metric(source.citation_status || "—", "citable"));
    add(panel, info);
    if (source.fetched_url && source.fetched_url !== source.url) {
      const reason = source.normalization_reason ? ` (${source.normalization_reason})` : "";
      add(panel, el("p", "muted", `URL descargada: ${source.fetched_url}${reason}`));
    }
    if (source.fetch_attempted_urls?.length > 1) {
      add(panel, el("p", "muted", `URLs intentadas: ${source.fetch_attempted_urls.join(" → ")}`));
    }
    const chunks = source.evaluation_chunks || source.chunks || [];
    if (!chunks.length) add(panel, el("p", "muted", source.fetch_status && source.fetch_status !== "ok" ?
      "No se pudieron extraer chunks de esta URL." : "No hay detalle de chunks en este artefacto."));
    else {
      const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
      const sort = {key: "rank", ascending: true};
      const columns = [["chunk_index", "Índice"], ["rank", "Rango"], ["score", "Total"], ["lexical_score", "Léxico"]];
      function draw() {
        clear(body);
        const ordered = [...chunks].sort((a, b) => {
          const av = a[sort.key] ?? Infinity, bv = b[sort.key] ?? Infinity;
          return (Number(av) - Number(bv)) * (sort.ascending ? 1 : -1);
        });
        for (const chunk of ordered) {
          const tr = el("tr", chunk.selected ? "selected-chunk" : "");
          const detail = el("details"), boost = chunk.boost_components || chunk.boosts || {};
          add(detail, el("summary", "", chunk.chunk_id || "Abrir texto"));
          detail.addEventListener("toggle", () => {
            if (detail.open && detail.childElementCount === 1) add(detail, el("pre", "", chunk.text || ""));
          });
          add(tr, el("td", "", chunk.chunk_index ?? "—"), el("td", "", chunk.rank ?? "—"),
            el("td", "", chunk.score ?? "—"), el("td", "", chunk.lexical_score ?? "—"),
            el("td", "", JSON.stringify(boost)), el("td", "", chunk.selected ? "Sí" : chunk.included_in_context ? "En ventana" : "No"),
            el("td", "", chunk.selection_reason || "—"), el("td", "", (chunk.context_ids || []).join(", ") || "—"),
            add(el("td"), detail)); add(body, tr);
        }
      }
      for (const [key, label] of columns) add(head, add(el("th"), button(label, () => { sort.ascending = sort.key === key ? !sort.ascending : true; sort.key = key; draw(); })));
      for (const label of ["Bonificaciones", "Selección", "Motivo", "Contextos", "Texto"]) add(head, el("th", "", label));
      add(table, add(el("thead"), head), body); draw(); add(wrap, table); add(panel, wrap);
    }
    for (const context of source.contexts || []) {
      const detail = el("details"); add(detail, el("summary", "", `${context.context_id || "Contexto"} · ${context.citation_eligible ? "citable" : "no citable"} · chunk ${context.selected_chunk_id || "—"}`),
        el("pre", "", context.text || "")); add(panel, detail);
    }
    add(block, panel);
  }
  if (observations.cached && trace.chunk_detail === "NOT_RECORDED_ON_CACHE_HIT") add(block,
    el("p", "muted", "La caché compartida no conserva los chunks descartados. Ejecuta la evaluación con caché fría para capturarlos."));
  add(block, el("p", "muted", "La puntuación indica coincidencia léxica y señales; no prueba apoyo semántico."));
  return block;
}

function renderFilters() {
  const block = add(el("section", "card filters"), el("h2", "", "Filtros"));
  function field(label, key, values) {
    const holder = el("label", "filter-field", label), select = el("select");
    add(select, el("option", "", "Todos")); select.firstChild.value = "";
    for (const value of values) {
      const option = el("option", "", value); option.value = value; option.selected = state.filters[key] === value; add(select, option);
    }
    select.value = state.filters[key];
    select.addEventListener("change", () => {
      state.filters[key] = select.value;
      renderDetail();
    });
    return add(holder, select);
  }
  const d = state.diagnostic;
  const cases = [...new Set(d.order.assertions.map(item => item.expected_case_id).filter(Boolean))].sort();
  const validators = [...new Set(d.validations.map(item => item.validator_id))].sort();
  const repetitions = [...new Set((state.orderList?.orders || []).filter(item => item.dataset_id === d.identity.dataset_id)
    .map(item => String(item.repetition)))].sort((a, b) => Number(a) - Number(b));
  const codes = [...new Set([d.order.generation, ...d.validations.flatMap(item => Object.values(item.stages))]
    .flatMap(stage => stage.checks.map(item => item.code)))].sort();
  const issueRows = failureRows(d);
  const fields = el("div", "filter-row");
  add(fields, field("Caso", "caseId", cases), field("Repetición", "repetition", repetitions),
    field("Validador", "validator", validators),
    field("Módulo", "stage", STAGES.map(item => item[0])), field("Tipo", "type", ["error", "warning"]),
    field("Origen", "origin", [...new Set(issueRows.map(item => item.origin))].sort()),
    field("Naturaleza", "nature", [...new Set(issueRows.map(item => item.nature))].sort()),
    field("Gravedad", "severity", ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]),
    field("Impacto", "impact", [...new Set(issueRows.map(item => item.impact))].sort()),
    field("Código", "code", codes));
  return add(block, fields);
}
function renderComparisonControl() {
  const block = add(el("section", "card"), el("h2", "", "Comparar repeticiones"));
  const output = el("div", "comparison-output");
  add(block, button("Cargar mismo caso y validador", async () => {
    clear(output); add(output, el("p", "muted", "Cargando diagnósticos de esta campaña…"));
    const active = state.diagnostic;
    const selected = active.order.assertions.find(item => item.assertion_id === state.assertionId);
    const validator = currentValidation()?.validator_id;
    if (!selected?.expected_case_id || !validator) {
      output.textContent = "Selecciona una afirmación emparejada y un validador."; return;
    }
    try {
      const matching = state.orderList.orders.filter(item => item.dataset_id === active.identity.dataset_id);
      const diagnostics = await Promise.all(matching.map(async item => ({item, diagnostic: item.order_id === active.identity.order_id ?
        active : await api(`/api/campaigns/${enc(state.campaign)}/orders/${enc(item.file)}`).catch(() => null)})));
      const rows = diagnostics.filter(entry => entry.diagnostic).flatMap(({item: orderItem, diagnostic}) => {
        const assertion = diagnostic.order.assertions.find(item => item.expected_case_id === selected.expected_case_id);
        return diagnostic.validations.filter(item => item.assertion_id === assertion?.assertion_id && item.validator_id === validator)
          .map(item => ({identity: diagnostic.identity, validation: item, createdAt: orderItem.created_at}));
      }).sort((a, b) => (Date.parse(b.createdAt || 0) || 0) - (Date.parse(a.createdAt || 0) || 0));
      clear(output);
      if (!rows.length) return add(output, el("p", "muted", "No hay repeticiones comparables guardadas."));
      const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
      for (const label of ["Fecha", "Repetición", "Orden", ...STAGES.slice(1).map(item => item[1]), "Veredicto"]) add(head, el("th", "", label));
      for (const row of rows) {
        const cells = [el("td", "date-column", formatSavedDate(row.createdAt)),
          el("td", "", row.identity.repetition), el("td", "", row.identity.order_id)];
        for (const [key] of STAGES.slice(1)) cells.push(add(el("td"), pill(row.validation.stages[key].assessment)));
        cells.push(el("td", "", row.validation.stages.llm.observations.effective_verdict || "—"));
        add(body, add(el("tr"), ...cells));
      }
      add(table, add(el("thead"), head), body); add(wrap, table); add(output, wrap);
    } catch (error) { output.textContent = error.message; }
  }), output); return block;
}

function renderHandoff(obs) {
  const block = el("section"); add(block, add(el("div", "summary"),
    metric(obs.retrieval_hash || "No registrado", "hash de recuperación"),
    metric(obs.validator_input_hash || "No registrado", "hash entregado")));
  if (obs.retrieval_hash && obs.validator_input_hash) add(block, el("p", "", obs.retrieval_hash === obs.validator_input_hash ?
    "Los hashes coinciden." : "Los hashes difieren; revisar el artefacto original."));
  return block;
}
function renderLlm(obs) {
  const block = el("section"); add(block, add(el("div", "summary"),
    metric(obs.model || "—", "modelo"), metric(obs.provider || "—", "proveedor"),
    metric(obs.validation_seconds ?? "—", "segundos"), metric(obs.original_verdict || "—", "veredicto original"),
    metric(obs.effective_verdict || "—", "veredicto efectivo"), metric(obs.expected_verdict || "—", "esperado")));
  add(block, el("p", "muted", `Versión de configuración: ${obs.config_version ?? "—"} · temperatura: ${obs.temperature ?? "—"} · hash de prompt: ${obs.prompt_hash || "—"}`));
  const audit = obs.grounding || {};
  if (Object.keys(audit).length) {
    add(block, el("h3", "", "Auditoría de citas y grounding"),
      el("p", "", `${audit.status || "—"} · ${audit.basis || "—"} · declaradas ${audit.claimed_count ?? "—"}, verificadas ${audit.verified_count ?? "—"}, rechazadas ${audit.rejected_count ?? "—"}`));
    if (obs.original_verdict && obs.effective_verdict && obs.original_verdict !== obs.effective_verdict)
      add(block, el("p", "error-list", "El veredicto cambió tras la auditoría. Revisa los motivos registrados a continuación."));
    const list = el("ul"); for (const issue of audit.issues || []) add(list, el("li", "", `${issue.code || "—"} · ${issue.context_id || issue.source_id || issue.verdict || ""}`));
    add(block, list);
  }
  if (obs.errors?.length) {
    add(block, el("h3", "", "Errores")); const list = el("ul");
    for (const issue of obs.errors) add(list, el("li", "", `${issue.stage || "—"} · ${issue.code || "—"} · ${issue.exception_type || ""}`));
    add(block, list);
  }
  return block;
}
function renderCitations(obs) {
  const block = el("section"); const citations = obs.citations || [];
  add(block, add(el("div", "summary"), metric(obs.claimed_count ?? "—", "declaradas"),
    metric(obs.verified_count ?? "—", "verificadas"), metric(obs.rejected_count ?? "—", "rechazadas"),
    metric((obs.contexts || []).length, "contextos entregados")));
  add(block, el("h3", "", "Citas declaradas"));
  if (!citations.length) add(block, el("p", "muted", "No hay citas individuales conservadas en este artefacto."));
  else {
    const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
    for (const label of ["Fuente", "Contexto", "Identidad", "Motivo", "Texto entregado"]) add(head, el("th", "", label));
    for (const item of citations) {
      const detail = el("details"); add(detail, el("summary", "", item.context?.url || "No localizado"),
        el("pre", "", item.context?.text || "Sin texto entregado"));
      add(body, add(el("tr"), el("td", "", item.source_id || "—"), el("td", "", item.context_id || "—"),
        add(el("td"), pill(item.valid_identity ? "PASS" : "FAIL")), el("td", "", item.reason || "—"), add(el("td"), detail)));
    }
    add(table, add(el("thead"), head), body); add(wrap, table); add(block, wrap);
  }
  add(block, el("h3", "", "Contextos entregados"));
  const used = new Set(citations.map(item => `${item.source_id}/${item.context_id}`));
  for (const context of obs.contexts || []) {
    const detail = el("details"); add(detail, el("summary", "", `${context.source_id}/${context.context_id} · ${used.has(`${context.source_id}/${context.context_id}`) ? "citado" : "sin citar"} · ${context.citation_eligible ? "citable" : "no citable"}`),
      el("pre", "", context.text || "")); add(block, detail);
  }
  if (obs.audit_issues?.length) add(block, el("p", "muted", `Motivos de auditoría: ${obs.audit_issues.map(item => item.code || "—").join(", ")}`));
  add(block, el("p", "muted", "La identidad y elegibilidad de una cita no prueban apoyo semántico."));
  return block;
}
function renderConsensus(obs) {
  const block = el("section"); add(block, add(el("div", "summary"),
    metric(obs.verdict || "—", "veredicto"), metric(obs.status || "—", "estado"),
    metric(obs.reason_code || "—", "motivo"),
    metric(obs.counts?.abstentions ?? "—", "abstenciones"), metric(obs.counts?.errors ?? obs.errors_count ?? "—", "errores")));
  const votes = obs.votes || obs.validator_votes || [];
  if (Array.isArray(votes) && votes.length) {
    const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
    for (const label of ["Validador", "Voto", "Peso", "Estado / motivo"]) add(head, el("th", "", label));
    for (const vote of votes) add(body, add(el("tr"), el("td", "", vote.validator_id || vote.validator || "—"),
      el("td", "", vote.verdict || vote.vote || "—"), el("td", "", vote.weight ?? "—"),
      el("td", "", vote.error || vote.audit_status || "—")));
    add(table, add(el("thead"), head), body); add(wrap, table); add(block, wrap);
  } else add(block, el("p", "muted", "Este artefacto no contiene votos individuales ni pesos."));
  if (obs.distribution) add(block, el("p", "muted", `Distribución: ${JSON.stringify(obs.distribution)} · política: ${obs.consensus_policy_version || "—"}`));
  if (obs.excluded_validators?.length) add(block, el("p", "muted", `Validadores excluidos: ${obs.excluded_validators.join(", ")}`));
  return block;
}

$("nav-campaigns").addEventListener("click", showCampaigns);
$("nav-orders").addEventListener("click", showOrders);
renderNavigation();
loadCampaigns();
