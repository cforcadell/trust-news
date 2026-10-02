const $ = (id) => document.getElementById(id);
const state = {campaigns: [], campaign: null, orderList: null, diagnostic: null,
  assertionId: null, runId: null, stage: "generation", view: "detail",
  filters: {caseId: "", validator: "", repetition: "", stage: "", code: ""}};
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
function button(label, onClick, className = "") {
  const node = el("button", className, label); node.type = "button";
  node.addEventListener("click", onClick); return node;
}
function pill(status) {
  const icons = {PASS: "✓", FAIL: "✕", PARTIAL: "!", NOT_EVALUATED: "?", SKIPPED: "–"};
  return el("span", `pill pill-${status}`, `${icons[status] || "·"} ${status}`);
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
  try { state.campaigns = await api("/api/campaigns"); renderCampaigns(); }
  catch (error) { showError(error.message); }
}
function renderCampaigns() {
  const host = clear($("campaigns"));
  if (!state.campaigns.length) return add(host, el("p", "", "No hay órdenes con diagnóstico v1 en la carpeta configurada."));
  for (const campaign of state.campaigns) {
    const item = button(campaign.campaign_id, () => openCampaign(campaign.campaign_id),
      campaign.campaign_id === state.campaign ? "active" : "");
    const date = campaign.created_at ? ` · ${campaign.created_at.slice(0, 10)}` : "";
    add(item, el("small", "", `${campaign.order_count} órdenes · ${campaign.status}${date}`)); add(host, item);
  }
}
async function openCampaign(campaign) {
  state.campaign = campaign; state.diagnostic = null;
  state.filters = {caseId: "", validator: "", repetition: "", stage: "", code: ""};
  renderCampaigns();
  try { state.orderList = await api(`/api/campaigns/${enc(campaign)}/orders`); renderOrders();
    if (state.orderList.orders.length) await openOrder(state.orderList.orders[0].file);
    else renderEmptyCampaign();
  } catch (error) { showError(error.message); }
}
function renderOrders() {
  const host = clear($("orders"));
  for (const item of state.orderList.orders) {
    if (state.filters.repetition && String(item.repetition) !== state.filters.repetition) continue;
    const selected = state.diagnostic && state.diagnostic.identity.order_id === item.order_id;
    const node = button(item.order_id, () => openOrder(item.file), selected ? "active" : "");
    add(node, el("small", "", `${item.dataset_id} · rep. ${item.repetition} · ${item.status}`)); add(host, node);
  }
  if (!state.orderList.orders.length) add(host, el("p", "", "No hay órdenes válidas."));
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
async function openOrder(file) {
  try {
    state.diagnostic = await api(`/api/campaigns/${enc(state.campaign)}/orders/${enc(file)}`);
    state.assertionId = state.diagnostic.order.assertions[0]?.assertion_id ?? null;
    state.runId = state.diagnostic.validations.find(v => v.assertion_id === state.assertionId)?.run_id ?? null;
    state.stage = "generation"; state.view = "detail"; renderOrders(); renderDetail();
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

function failureRows(diagnostic) {
  const rows = [];
  const assertions = new Map(diagnostic.order.assertions.map(item => [item.assertion_id, item]));
  const generated = diagnostic.order.generation.observations?.generated_assertions || [];
  function addStage(stage, stageKey, assertionId = null, validation = null) {
    if (!stage || stage.assessment !== "FAIL") return;
    const failedChecks = (stage.checks || []).filter(check => check.status === "FAIL");
    const checks = failedChecks.length ? failedChecks : [{code: "MODULE_FAILED", detail: stage.missing_reason || "El módulo terminó con fallo."}];
    for (const check of checks) {
      let resolvedAssertionId = assertionId;
      if (!resolvedAssertionId && stageKey === "generation") {
        const ref = (check.observation_refs || []).find(value => /generated_assertions\/\d+$/.test(value));
        const match = ref && ref.match(/(\d+)$/);
        resolvedAssertionId = match ? generated[Number(match[1])]?.assertion_id : null;
      }
      const assertion = assertions.get(resolvedAssertionId);
      rows.push({stageKey, assertionId: resolvedAssertionId,
        assertionText: assertion?.text || generated.find(item => item.assertion_id === resolvedAssertionId)?.text || "—",
        caseId: assertion?.expected_case_id || "—", validatorId: validation?.validator_id || "—",
        runId: validation?.run_id || null, executionStatus: stage.execution_status,
        assessment: stage.assessment, code: check.code || "—", detail: check.detail || "—"});
    }
  }
  addStage(diagnostic.order.generation, "generation");
  for (const validation of diagnostic.validations)
    for (const [stageKey, stage] of Object.entries(validation.stages))
      addStage(stage, stageKey, validation.assertion_id, validation);
  return rows;
}

function renderViewTabs() {
  const tabs = el("div", "view-tabs");
  const detail = button("Detalle", () => { state.view = "detail"; renderDetail(); }, state.view === "detail" ? "active" : "");
  const failures = button("Resumen de fallos", () => { state.view = "failures"; renderDetail(); }, state.view === "failures" ? "active" : "");
  for (const [node, selected] of [[detail, state.view === "detail"], [failures, state.view === "failures"]]) {
    node.setAttribute("role", "tab"); node.setAttribute("aria-selected", String(selected));
  }
  return add(tabs, detail, failures);
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
    (!state.filters.code || row.code === state.filters.code));
  const modules = new Set(rows.map(row => row.stageKey === "generation" ? "generation/order" :
    `${row.stageKey}/${row.assertionId || "order"}/${row.runId || "order"}`));
  const card = add(el("section", "card"), el("h2", "", "Resumen de fallos"),
    el("p", "muted", `${modules.size} módulos con fallo · ${rows.length} comprobaciones fallidas. Selecciona una fila para abrir su contexto.`));
  if (!rows.length) return add(card, el("p", "muted", "No hay fallos que coincidan con los filtros actuales."));
  const wrap = el("div", "table-wrap"), table = el("table", "failure-table"), head = el("tr"), body = el("tbody");
  for (const label of ["Módulo", "Aserción", "Caso", "Validador", "Estado", "Código", "Detalle"])
    add(head, el("th", "", label));
  for (const row of rows) {
    const module = STAGES.find(([key]) => key === row.stageKey)?.[1] || row.stageKey;
    const tableRow = add(el("tr", "clickable-row"), el("td", "", module), el("td", "", row.assertionText),
      el("td", "", row.caseId), el("td", "mono", row.validatorId), add(el("td"), pill(row.assessment)),
      el("td", "mono", row.code), el("td", "", row.detail));
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
  const failedModules = (d.order.generation.assessment === "FAIL" ? 1 : 0) + d.validations.reduce((n, validation) =>
    n + Object.values(validation.stages).filter(stage => stage.assessment === "FAIL").length, 0);
  add(metrics, metric(d.order.assertions.length, "afirmaciones"),
    metric(d.validations.length, "validaciones"),
    metricButton(failedModules, "módulos con fallos", () => { state.view = "failures"; renderDetail(); }));
  add(main, metrics, renderViewTabs(), renderFilters());
  const problems = errorBlock(state.orderList?.errors); if (problems) add(main, problems);
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
    add(node, el("small", "", `Run ${validation.run_id}`)); add(selector, node);
  }
  if (!selector.childElementCount) add(selector, el("p", "muted", "Sin validaciones para esta afirmación."));
  add(validators, selector); add(right, validators);
  if (state.assertionId) add(right, renderComparisonControl());
  const flow = add(el("section", "card"), el("h2", "", "Cadena de ejecución"));
  const chain = el("div", "chain");
  STAGES.forEach(([key, label], index) => {
    if (state.filters.stage && key !== state.filters.stage) return;
    const stage = key === "generation" ? d.order.generation : currentValidation()?.stages[key];
    if (index) add(chain, el("span", "arrow", "→"));
    const node = button("", () => { state.stage = key; renderDetail(); },
      `status status-${stage?.assessment || "SKIPPED"}${state.stage === key ? " active" : ""}`);
    add(node, el("strong", "", label), el("small", "", stage?.assessment || "Sin validador"));
    add(chain, node);
  });
  add(flow, chain); add(right, flow, renderStage()); add(layout, left, right); add(main, layout);
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
  if (!stage.checks.length) add(card, el("p", "muted", "No hay comprobaciones registradas."));
  else {
    const wrap = el("div", "table-wrap"); const table = el("table"); const header = el("tr");
    for (const label of ["Estado", "Código", "Detalle"]) add(header, el("th", "", label));
    add(table, add(el("thead"), header)); const body = el("tbody");
    for (const check of stage.checks.filter(item => !state.filters.code || item.code === state.filters.code)) add(body, add(el("tr"),
      add(el("td"), pill(check.status)), el("td", "", check.code), el("td", "", check.detail)));
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
  add(info, metric(observations.model || "—", "modelo"),
    metric(observations.structured_attempts ?? "—", "llamadas estructuradas"),
    metric(observations.repair_used == null ? "—" : observations.repair_used ? "Sí" : "No", "reparación"),
    metric(observations.duration_seconds ?? "—", "segundos"));
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
  add(summary, metric(observations.route_state || "—", "estado de ruta"),
    metric(trace.cache_hit == null ? "—" : trace.cache_hit ? "Sí" : "No", "caché"),
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
  const sources = observations.evidences || observations.sources || [];
  add(block, add(el("div", "summary"), metric(observations.cached == null ? "—" : observations.cached ? "Sí" : "No", "caché"),
    metric(sources.length, "URLs conservadas"), metric(sources.reduce((n, source) => n + (source.chunks_total || 0), 0), "chunks"),
    metric(trace.chunk_detail || "No registrada", "captura de chunks")));
  if (trace.limits) add(block, el("p", "muted", `Límites: ${trace.limits.max_results} URLs, ${trace.limits.max_contexts_per_source} contextos/fuente, ${trace.limits.max_contexts_total} contextos/global; ventana ±${trace.limits.window_before}/${trace.limits.window_after} chunks; tamaño ${trace.limits.chunk_size_chars}, solape ${trace.limits.chunk_overlap_chars} caracteres.`));
  add(block, el("h3", "", "Consultas y URLs devueltas"));
  const requests = trace.query_execution || observations.queries_executed || observations.queries || [];
  if (!requests.length) add(block, el("p", "muted", "No hay consultas registradas en esta orden."));
  else {
    const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
    for (const label of ["Consulta", "Modo / filtros", "Estado", "URLs y decisión"]) add(head, el("th", "", label));
    for (const item of requests) {
      const urls = el("td");
      const decisions = item.result_decisions || (item.returned_urls || []).map(url => ({url, decision: "DEVUELTA"}));
      if (!decisions.length) add(urls, el("span", "muted", "Sin URLs registradas"));
      for (const result of decisions) add(urls, el("div", "", `${result.decision || "—"}: ${result.url || "—"}`));
      add(body, add(el("tr"), el("td", "", item.query || "—"),
        el("td", "", `${item.mode || item.provider || "—"} · ${(item.include_domains || []).join(", ") || item.external_source_policy || "sin filtro"}`),
        el("td", "", item.status || (observations.cached ? "NO EJECUTADA (caché)" : "No registrado")), urls));
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
    add(panel, el("summary", "", `${source.source_id || "—"} · ${source.url || "Sin URL"} · ${source.fetch_status || "descarga no registrada"} · ${source.chunks_total ?? "—"} chunks`));
    const info = add(el("div", "summary"), metric(source.document_length_chars ?? "—", "caracteres"),
      metric(source.content_type || "—", "tipo"), metric(source.relationship_to_origin || "—", "relación con origen"),
      metric((source.contexts || []).length, "contextos"), metric(source.citation_status || "—", "citable"));
    add(panel, info);
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
      if (key === "repetition") renderOrders();
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
  const fields = el("div", "filter-row");
  add(fields, field("Caso", "caseId", cases), field("Repetición", "repetition", repetitions),
    field("Validador", "validator", validators),
    field("Módulo", "stage", STAGES.map(item => item[0])), field("Código", "code", codes));
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
      const diagnostics = await Promise.all(matching.map(item => item.order_id === active.identity.order_id ?
        Promise.resolve(active) : api(`/api/campaigns/${enc(state.campaign)}/orders/${enc(item.file)}`).catch(() => null)));
      const rows = diagnostics.filter(Boolean).flatMap(diagnostic => {
        const assertion = diagnostic.order.assertions.find(item => item.expected_case_id === selected.expected_case_id);
        return diagnostic.validations.filter(item => item.assertion_id === assertion?.assertion_id && item.validator_id === validator)
          .map(item => ({identity: diagnostic.identity, validation: item}));
      }).sort((a, b) => a.identity.repetition - b.identity.repetition);
      clear(output);
      if (!rows.length) return add(output, el("p", "muted", "No hay repeticiones comparables guardadas."));
      const wrap = el("div", "table-wrap"), table = el("table"), head = el("tr"), body = el("tbody");
      for (const label of ["Repetición", "Orden", ...STAGES.slice(1).map(item => item[1]), "Veredicto"]) add(head, el("th", "", label));
      for (const row of rows) {
        const cells = [el("td", "", row.identity.repetition), el("td", "", row.identity.order_id)];
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

loadCampaigns();
