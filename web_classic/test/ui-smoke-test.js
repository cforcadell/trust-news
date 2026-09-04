#!/usr/bin/env node

/**
 * Ejecutor E2E de un escenario de regresión del frontend clásico.
 *
 * Usa Chrome DevTools Protocol sin dependencias npm. El caso puede recibirse
 * mediante ASSERMETRY_CASE_FILE; sin él conserva el modo smoke interactivo.
 */

const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const DEFAULT_NEWS_FILE = path.join(REPO_ROOT, "docs", "fake_news", "news.txt");
const RUN_ID = process.env.ASSERMETRY_RUN_ID
  || new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-");
const CASE_FILE = process.env.ASSERMETRY_CASE_FILE
  ? path.resolve(process.env.ASSERMETRY_CASE_FILE)
  : null;
const TEST_CASE = loadCase(CASE_FILE);
const FRONTEND_URL = process.env.ASSERMETRY_URL || "https://localhost:7443/gui/";
const USERNAME = process.env.ASSERMETRY_USERNAME;
const PASSWORD = process.env.ASSERMETRY_PASSWORD;
const CHROME_BIN = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const DEBUG_PORT = positiveNumber("ASSERMETRY_DEBUG_PORT", 9223);
const CDP_TIMEOUT_MS = positiveNumber("ASSERMETRY_CDP_TIMEOUT_MS", 15000);
const VALIDATION_MODE = String(
  process.env.ASSERMETRY_VALIDATION_MODE || TEST_CASE.mode || "LIGHT",
).toUpperCase();
const RESULT_TIMEOUT_MS = positiveNumber(
  "ASSERMETRY_RESULT_TIMEOUT_MS",
  TEST_CASE.timeoutMs || 5 * 60 * 1000,
);
const MOBILE_WIDTH = positiveNumber("ASSERMETRY_MOBILE_WIDTH", 390);
const MOBILE_HEIGHT = positiveNumber("ASSERMETRY_MOBILE_HEIGHT", 844);
const ARTIFACTS_DIR = process.env.ASSERMETRY_ARTIFACTS_DIR
  ? path.resolve(process.env.ASSERMETRY_ARTIFACTS_DIR)
  : path.join(os.tmpdir(), `assermetry-ui-${RUN_ID}`);
const EXPECTED = normalizeExpected(TEST_CASE.expected || {});
const NEWS = loadNews(TEST_CASE, CASE_FILE);

validateConfiguration();

if (fs.existsSync(ARTIFACTS_DIR) && fs.readdirSync(ARTIFACTS_DIR).length > 0) {
  throw new Error(`El directorio de artefactos debe estar vacío: ${ARTIFACTS_DIR}`);
}
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), "assermetry-chrome-"));
fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });

const report = {
  schemaVersion: 1,
  runId: RUN_ID,
  status: "RUNNING",
  scenario: {
    id: TEST_CASE.id || "interactive-smoke",
    organization: TEST_CASE.organization || "unspecified",
    identityAlias: TEST_CASE.identity?.alias || "unspecified",
    validationMode: VALIDATION_MODE,
  },
  startedAt: new Date().toISOString(),
  source: {
    sha256: sha256(NEWS),
    characters: NEWS.length,
  },
  environment: collectEnvironment(),
  configuration: {
    frontendUrl: sanitizeUrl(FRONTEND_URL),
    resultTimeoutMs: RESULT_TIMEOUT_MS,
    cdpTimeoutMs: CDP_TIMEOUT_MS,
    mobileViewport: { width: MOBILE_WIDTH, height: MOBILE_HEIGHT },
    provider: optionalMetadata("ASSERMETRY_PROVIDER"),
    model: optionalMetadata("ASSERMETRY_MODEL"),
    llmHttpTimeoutSeconds: optionalNumericMetadata("ASSERMETRY_HTTP_TIMEOUT_SECONDS"),
  },
  expected: EXPECTED,
  tests: [],
  checks: [],
  browserConsole: { counts: {}, diagnosticEntries: [] },
  network: { failedResponses: [], loadingFailures: [], unexpectedFailedResponses: [] },
  createdResources: { orderIds: [] },
  artifacts: [],
};
const consoleDiagnostics = [];

let chromeSpawnError = null;
let cdp = null;
let browserCloseRequested = false;
const chrome = spawn(CHROME_BIN, [
  "--headless=new",
  "--no-sandbox",
  "--disable-gpu",
  "--disable-dev-shm-usage",
  "--ignore-certificate-errors",
  "--allow-insecure-localhost",
  `--remote-debugging-port=${DEBUG_PORT}`,
  `--user-data-dir=${profileDir}`,
  "--window-size=1440,1000",
  FRONTEND_URL,
], {
  stdio: ["ignore", "ignore", "pipe"],
  env: browserEnvironment(),
});

let chromeStderr = "";
chrome.stderr?.on("data", chunk => { chromeStderr += chunk.toString(); });
chrome.on("error", error => { chromeSpawnError = error; });

const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

function positiveNumber(name, fallback) {
  const rawValue = process.env[name];
  const value = rawValue == null || rawValue === "" ? Number(fallback) : Number(rawValue);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${name} debe ser un número positivo.`);
  }
  return value;
}

function optionalMetadata(name) {
  const value = String(process.env[name] || "").trim();
  return value || null;
}

function optionalNumericMetadata(name) {
  const value = optionalMetadata(name);
  if (value == null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function loadCase(caseFile) {
  if (!caseFile) return { id: "interactive-smoke", mode: "LIGHT", expected: {} };
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(caseFile, "utf8"));
  } catch (error) {
    throw new Error(`No se pudo cargar el caso ${caseFile}: ${error.message}`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`El caso ${caseFile} debe ser un objeto JSON.`);
  }
  return parsed;
}

function loadNews(testCase, caseFile) {
  if (process.env.ASSERMETRY_NEWS) return process.env.ASSERMETRY_NEWS.trim();
  let newsFile = process.env.ASSERMETRY_NEWS_FILE || testCase.newsFile || DEFAULT_NEWS_FILE;
  if (!path.isAbsolute(newsFile)) {
    newsFile = path.resolve(caseFile ? path.dirname(caseFile) : REPO_ROOT, newsFile);
  }
  const text = fs.readFileSync(newsFile, "utf8").trim();
  if (!text) throw new Error(`La noticia de prueba está vacía: ${newsFile}`);
  return text;
}

function normalizeExpected(expected) {
  return {
    terminalStatuses: expected.terminalStatuses || ["VALIDATED"],
    minimumAssertions: Number(expected.minimumAssertions ?? 1),
    minimumValidations: Number(expected.minimumValidations ?? 1),
    validatorsPending: Number(expected.validatorsPending ?? 0),
    requiredTabs: expected.requiredTabs || ["summary", "assertions", "evidence", "process", "technical", "events"],
    enabledTabs: expected.enabledTabs || [],
    disabledTabs: expected.disabledTabs || [],
    requiredOrderFields: expected.requiredOrderFields || ["order_id", "status", "validation_mode"],
    allowedHttpFailures: expected.allowedHttpFailures || [],
    allowedConsoleErrors: expected.allowedConsoleErrors || [],
  };
}

function validateConfiguration() {
  if (!USERNAME || !PASSWORD) {
    throw new Error("Faltan ASSERMETRY_USERNAME y/o ASSERMETRY_PASSWORD.");
  }
  if (!new Set(["LIGHT", "BLOCKCHAIN"]).has(VALIDATION_MODE)) {
    throw new Error("ASSERMETRY_VALIDATION_MODE debe ser LIGHT o BLOCKCHAIN.");
  }
  if (!Array.isArray(EXPECTED.terminalStatuses) || EXPECTED.terminalStatuses.length === 0) {
    throw new Error("expected.terminalStatuses debe contener al menos un estado.");
  }
}

function commandOutput(command, args) {
  const result = spawnSync(command, args, {
    cwd: REPO_ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  });
  return result.status === 0 ? String(result.stdout || "").trim() || null : null;
}

function collectEnvironment() {
  return {
    repositoryCommit: commandOutput("git", ["rev-parse", "HEAD"]),
    repositoryDirty: Boolean(commandOutput("git", ["status", "--porcelain"])),
    nodeVersion: process.version,
    chromeVersion: commandOutput(CHROME_BIN, ["--version"]),
  };
}

function browserEnvironment() {
  const environment = { ...process.env };
  for (const name of Object.keys(environment)) {
    if (/(PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY)/i.test(name)) delete environment[name];
  }
  return environment;
}

function sha256(value) {
  return crypto.createHash("sha256").update(String(value), "utf8").digest("hex");
}

function sanitizeUrl(value) {
  try {
    const url = new URL(value);
    return `${url.origin}${url.pathname}`;
  } catch (_) {
    return String(value || "").split(/[?#]/, 1)[0];
  }
}

function redactText(value, maximumLength = 500) {
  return String(value || "")
    .replace(/(Bearer\s+)[^\s"']+/gi, "$1[REDACTED]")
    .replace(/([?&](?:code|token|access_token|refresh_token|session_code|state)=)[^&\s]+/gi, "$1[REDACTED]")
    .replace(/((?:password|secret|token)\s*[=:]\s*)[^\s,;]+/gi, "$1[REDACTED]")
    .slice(0, maximumLength);
}

function summarizeText(value) {
  const text = String(value || "");
  return { characters: text.length, sha256: sha256(text) };
}

function valueAtPath(value, dottedPath) {
  return String(dottedPath).split(".").reduce(
    (current, key) => current == null ? undefined : current[key],
    value,
  );
}

function hasNonEmptyValue(value, dottedPath) {
  const found = valueAtPath(value, dottedPath);
  return found !== undefined && found !== null && found !== "";
}

function assertionCount(order) {
  const candidates = [
    order?.assertions,
    order?.document?.assertions,
    order?.assertions_document?.assertions,
  ];
  return candidates.find(Array.isArray)?.length || 0;
}

function validationCount(order) {
  const validations = order?.validations;
  if (Array.isArray(validations)) return validations.length;
  if (!validations || typeof validations !== "object") return 0;
  return Object.values(validations).reduce((total, assertionValidations) => {
    if (Array.isArray(assertionValidations)) return total + assertionValidations.length;
    if (assertionValidations && typeof assertionValidations === "object") {
      return total + Object.keys(assertionValidations).length;
    }
    return total;
  }, 0);
}

function summarizeOrder(order) {
  return {
    orderId: order?.order_id || null,
    status: order?.status || null,
    validationMode: order?.validation_mode || null,
    assertions: assertionCount(order),
    validations: validationCount(order),
    validators: Array.isArray(order?.validators) ? order.validators.length : 0,
    validatorsPending: Number(order?.validators_pending ?? 0),
    cid: order?.cid || null,
    postId: order?.post_id ?? order?.postId ?? null,
    transactionHash: order?.tx_hash || null,
  };
}

function addCheck(name, passed, details = {}) {
  report.checks.push({ name, status: passed ? "PASS" : "FAIL", ...details });
  return passed;
}

function matchesRule(value, rule) {
  try {
    return new RegExp(rule).test(String(value || ""));
  } catch (_) {
    return false;
  }
}

function isAllowedHttpFailure(failure) {
  return EXPECTED.allowedHttpFailures.some(rule => (
    Number(rule.status) === Number(failure.status)
    && matchesRule(failure.path, rule.pathPattern)
  ));
}

async function retry(operation, timeoutMs = 20000, intervalMs = 250) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const result = await operation();
      if (result) return result;
    } catch (error) {
      lastError = error;
    }
    await delay(intervalMs);
  }
  throw lastError || new Error(`Timeout después de ${timeoutMs} ms`);
}

class CdpClient {
  constructor(webSocketUrl, timeoutMs) {
    this.socket = new WebSocket(webSocketUrl);
    this.timeoutMs = timeoutMs;
    this.sequence = 0;
    this.pending = new Map();
    this.listeners = new Map();
  }

  async open() {
    await new Promise((resolve, reject) => {
      const timeoutId = setTimeout(
        () => reject(new Error(`Timeout abriendo CDP después de ${this.timeoutMs} ms`)),
        this.timeoutMs,
      );
      this.socket.addEventListener("open", () => {
        clearTimeout(timeoutId);
        resolve();
      }, { once: true });
      this.socket.addEventListener("error", event => {
        clearTimeout(timeoutId);
        reject(event.error || new Error("No se pudo abrir CDP"));
      }, { once: true });
    });
    this.socket.addEventListener("message", event => this.handleMessage(event));
    this.socket.addEventListener("close", () => this.rejectPending(new Error("La conexión CDP se cerró")));
    this.socket.addEventListener("error", () => this.rejectPending(new Error("Falló la conexión CDP")));
  }

  handleMessage(event) {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_) {
      return;
    }
    if (message.id) {
      const waiter = this.pending.get(message.id);
      if (!waiter) return;
      clearTimeout(waiter.timeoutId);
      this.pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message));
      else waiter.resolve(message.result);
      return;
    }
    for (const listener of this.listeners.get(message.method) || []) {
      listener(message.params || {});
    }
  }

  rejectPending(error) {
    for (const waiter of this.pending.values()) {
      clearTimeout(waiter.timeoutId);
      waiter.reject(error);
    }
    this.pending.clear();
  }

  on(method, listener) {
    if (!this.listeners.has(method)) this.listeners.set(method, []);
    this.listeners.get(method).push(listener);
  }

  send(method, params = {}) {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Timeout CDP en ${method} después de ${this.timeoutMs} ms`));
      }, this.timeoutMs);
      this.pending.set(id, { resolve, reject, timeoutId });
      try {
        this.socket.send(JSON.stringify({ id, method, params }));
      } catch (error) {
        clearTimeout(timeoutId);
        this.pending.delete(id);
        reject(error);
      }
    });
  }
}

async function run() {
  const target = await retry(async () => {
    if (chromeSpawnError) throw chromeSpawnError;
    const response = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`, {
      signal: AbortSignal.timeout(Math.min(CDP_TIMEOUT_MS, 3000)),
    });
    const targets = await response.json();
    return targets.find(item => item.type === "page");
  });

  cdp = new CdpClient(target.webSocketDebuggerUrl, CDP_TIMEOUT_MS);
  await cdp.open();
  cdp.on("Runtime.consoleAPICalled", params => {
    const type = params.type || "unknown";
    report.browserConsole.counts[type] = (report.browserConsole.counts[type] || 0) + 1;
    if (["error", "warning"].includes(type)) {
      const message = (params.args || [])
        .map(arg => arg.value ?? arg.description ?? "")
        .join(" ");
      const redactedMessage = redactText(message);
      consoleDiagnostics.push({ type, message: redactedMessage });
      report.browserConsole.diagnosticEntries.push({ type, message: summarizeText(redactedMessage) });
    }
  });
  cdp.on("Network.responseReceived", params => {
    const response = params.response || {};
    if (response.status >= 400) {
      let pathname = sanitizeUrl(response.url);
      try { pathname = new URL(response.url).pathname; } catch (_) {}
      report.network.failedResponses.push({ status: response.status, path: pathname });
    }
  });
  cdp.on("Network.loadingFailed", params => {
    if (!params.canceled) {
      report.network.loadingFailures.push({
        resourceType: params.type || null,
        error: summarizeText(redactText(params.errorText || "network loading failed")),
      });
    }
  });
  await Promise.all([
    cdp.send("Page.enable"),
    cdp.send("Runtime.enable"),
    cdp.send("Network.enable"),
  ]);

  async function evaluate(expression) {
    const response = await cdp.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (response.exceptionDetails) {
      throw new Error(response.exceptionDetails.text || "Runtime.evaluate falló");
    }
    return response.result?.value;
  }

  async function waitFor(expression, timeoutMs = 30000, intervalMs = 300) {
    return retry(async () => (await evaluate(expression)) || false, timeoutMs, intervalMs);
  }

  async function screenshot(name) {
    const image = await cdp.send("Page.captureScreenshot", {
      format: "png",
      fromSurface: true,
      captureBeyondViewport: true,
    });
    fs.writeFileSync(path.join(ARTIFACTS_DIR, name), Buffer.from(image.data, "base64"));
    report.artifacts.push(name);
  }

  async function snapshot() {
    const value = await evaluate(`(() => ({
      url: location.href,
      title: document.title,
      lang: document.documentElement.lang,
      viewport: { width: innerWidth, height: innerHeight },
      documentSize: {
        width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0),
        height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0)
      },
      headings: Array.from(document.querySelectorAll('h1,h2')).filter(element => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }).map(element => element.innerText.trim()),
      buttons: Array.from(document.querySelectorAll('button,input[type=submit]')).filter(element => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }).map(element => ({
        id: element.id || null,
        text: (element.innerText || element.value || element.getAttribute('aria-label') || '').trim()
      })),
      bodyText: document.body?.innerText || ''
    }))()`);
    value.url = sanitizeUrl(value.url);
    value.headings = value.headings.map(summarizeText);
    value.bodyText = summarizeText(value.bodyText);
    return value;
  }

  const loginStarted = Date.now();
  await waitFor("document.querySelector('#kc-form-login')");
  const login = await snapshot();
  await screenshot("01-login-desktop.png");
  await evaluate(`(() => {
    const setValue = (selector, value) => {
      const element = document.querySelector(selector);
      element.value = value;
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
    };
    setValue('#username', ${JSON.stringify(USERNAME)});
    setValue('#password', ${JSON.stringify(PASSWORD)});
    document.querySelector('#kc-form-login').requestSubmit();
    return true;
  })()`);
  await waitFor("location.pathname.startsWith('/gui') && document.querySelector('#newsText')", 45000);
  await delay(1200);
  const home = await snapshot();
  await screenshot("02-home-desktop.png");
  report.tests.push({
    id: 1,
    name: "Acceso y autenticación",
    status: "PASS",
    durationMs: Date.now() - loginStarted,
    login,
    home,
  });
  addCheck("authenticated-home-visible", true);
  console.log("TEST_1_OK acceso_y_autenticacion");

  const submissionStarted = Date.now();
  await evaluate(`(() => {
    const textarea = document.querySelector('#newsText');
    textarea.value = ${JSON.stringify(NEWS)};
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('#validationMode').checked = ${VALIDATION_MODE === "BLOCKCHAIN"};
    document.querySelector('#btn-publishNew').click();
    return true;
  })()`);
  await waitFor(`document.querySelector('#orderId')
    && !['', 'Publicando...', 'Publishing...', 'Error...'].includes(document.querySelector('#orderId').value)`, 120000, 500);
  const submission = await evaluate(`(() => ({
    orderId: document.querySelector('#orderId')?.value || '',
    statusToast: document.querySelector('#statusBar')?.innerText || '',
    url: location.href,
    bodyText: document.querySelector('#order')?.innerText || ''
  }))()`);
  submission.url = sanitizeUrl(submission.url);
  submission.statusToast = redactText(submission.statusToast);
  submission.bodyText = summarizeText(submission.bodyText);
  const validOrderId = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(submission.orderId);
  addCheck("valid-order-id", validOrderId, { actual: submission.orderId || null });
  if (validOrderId) report.createdResources.orderIds.push(submission.orderId);
  await screenshot("03-after-submit-desktop.png");
  report.tests.push({
    id: 2,
    name: "Alta de una única noticia",
    status: validOrderId ? "PASS" : "FAIL",
    durationMs: Date.now() - submissionStarted,
    submission,
  });
  console.log(`TEST_2_${validOrderId ? "OK" : "FAIL"} order_id=${submission.orderId}`);

  const trackingStarted = Date.now();
  const statusHistory = [];
  const failureStatuses = new Set([
    "ASSERTIONS_NOT_AVAILABLE",
    "QUOTA_EXCEDED",
    "NO_VALIDATORS_AVAILABLE",
    "FAILED",
    "ERROR",
  ]);
  const knownTerminalStatuses = new Set([
    ...EXPECTED.terminalStatuses.map(value => String(value).toUpperCase()),
    ...failureStatuses,
  ]);
  const deadline = Date.now() + RESULT_TIMEOUT_MS;
  let order = {};
  let reachedTerminal = false;
  while (Date.now() < deadline) {
    order = await evaluate("(() => { try { return currentOrderData || {}; } catch (_) { return {}; } })()");
    const status = String(order?.status || "UNKNOWN").toUpperCase();
    if (statusHistory.at(-1)?.status !== status) {
      statusHistory.push({ elapsedMs: Date.now() - trackingStarted, status });
      console.log(`ORDER_STATUS ${status}`);
    }
    if (knownTerminalStatuses.has(status) || status.startsWith("VALIDATED")) {
      reachedTerminal = true;
      break;
    }
    await delay(3000);
  }
  await delay(1000);
  order = await evaluate("(() => { try { return currentOrderData || {}; } catch (_) { return {}; } })()");
  const finalStatus = String(order?.status || "UNKNOWN").toUpperCase();
  const allowedStatus = EXPECTED.terminalStatuses.map(value => String(value).toUpperCase()).includes(finalStatus);
  addCheck("terminal-status-reached", reachedTerminal, { actual: finalStatus });
  addCheck("terminal-status-allowed", allowedStatus, {
    expected: EXPECTED.terminalStatuses,
    actual: finalStatus,
  });
  addCheck("validation-mode", String(order?.validation_mode || "").toUpperCase() === VALIDATION_MODE, {
    expected: VALIDATION_MODE,
    actual: order?.validation_mode || null,
  });

  const tabs = await evaluate(`Array.from(document.querySelectorAll('#orderTabs [data-tab-key]')).map(element => ({
    key: element.dataset.tabKey,
    text: element.innerText.trim(),
    disabled: element.disabled
  }))`);
  const tabContents = {};
  for (const tab of tabs || []) {
    if (tab.disabled) continue;
    await evaluate(`document.querySelector('#orderTabs [data-tab-key=${JSON.stringify(tab.key)}]')?.click()`);
    await delay(300);
    const content = await evaluate("document.querySelector('#tabContent')?.innerText || ''");
    tabContents[tab.key] = summarizeText(content);
  }
  await evaluate("document.querySelector('#orderTabs [data-tab-key=\"summary\"]')?.click()");
  await delay(300);

  const tabByKey = new Map((tabs || []).map(tab => [tab.key, tab]));
  for (const key of EXPECTED.requiredTabs) {
    addCheck(`required-tab:${key}`, tabByKey.has(key), { expected: "present" });
  }
  for (const key of EXPECTED.enabledTabs) {
    addCheck(`enabled-tab:${key}`, tabByKey.has(key) && !tabByKey.get(key).disabled, { expected: "enabled" });
  }
  for (const key of EXPECTED.disabledTabs) {
    addCheck(`disabled-tab:${key}`, tabByKey.has(key) && tabByKey.get(key).disabled, { expected: "disabled" });
  }
  for (const field of EXPECTED.requiredOrderFields) {
    addCheck(`required-order-field:${field}`, hasNonEmptyValue(order, field), { expected: "non-empty" });
  }
  const summarizedOrder = summarizeOrder(order);
  addCheck("minimum-assertions", summarizedOrder.assertions >= EXPECTED.minimumAssertions, {
    expectedMinimum: EXPECTED.minimumAssertions,
    actual: summarizedOrder.assertions,
  });
  addCheck("minimum-validations", summarizedOrder.validations >= EXPECTED.minimumValidations, {
    expectedMinimum: EXPECTED.minimumValidations,
    actual: summarizedOrder.validations,
  });
  addCheck("validators-pending", summarizedOrder.validatorsPending === EXPECTED.validatorsPending, {
    expected: EXPECTED.validatorsPending,
    actual: summarizedOrder.validatorsPending,
  });

  const resultDesktop = await snapshot();
  await screenshot("04-result-desktop.png");
  report.tests.push({
    id: 3,
    name: "Seguimiento y resultado de la misma orden",
    status: reachedTerminal && allowedStatus ? "PASS" : "FAIL",
    durationMs: Date.now() - trackingStarted,
    statusHistory,
    order: summarizedOrder,
    tabs,
    tabContents,
    resultDesktop,
  });
  console.log(`TEST_3_${reachedTerminal && allowedStatus ? "OK" : "FAIL"} final_status=${finalStatus}`);

  const responsiveStarted = Date.now();
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: MOBILE_WIDTH,
    height: MOBILE_HEIGHT,
    deviceScaleFactor: 1,
    // El escenario redimensiona una sesión de escritorio ya cargada para
    // probar el layout responsive. Activar aquí la emulación de dispositivo
    // hace que Chrome aplique shrink-to-fit sobre el contenido ancho existente
    // y el viewport CSS puede superar las dimensiones solicitadas.
    mobile: false,
  });
  await delay(600);
  const mobileResult = await snapshot();
  await screenshot("05-result-mobile.png");
  await evaluate("showSection('news', false); true");
  await delay(300);
  const mobileHome = await snapshot();
  await screenshot("06-home-mobile.png");
  const viewportMatches = mobileHome.viewport.width === MOBILE_WIDTH && mobileHome.viewport.height === MOBILE_HEIGHT;
  addCheck("mobile-viewport", viewportMatches, {
    expected: { width: MOBILE_WIDTH, height: MOBILE_HEIGHT },
    actual: mobileHome.viewport,
  });
  report.tests.push({
    id: 4,
    name: "Responsive de la misma sesión",
    status: viewportMatches ? "PASS" : "FAIL",
    durationMs: Date.now() - responsiveStarted,
    mobileResult,
    mobileHome,
  });

  report.network.unexpectedFailedResponses = report.network.failedResponses.filter(
    failure => !isAllowedHttpFailure(failure),
  );
  addCheck("unexpected-http-failures", report.network.unexpectedFailedResponses.length === 0, {
    actual: report.network.unexpectedFailedResponses.length,
  });
  addCheck("network-loading-failures", report.network.loadingFailures.length === 0, {
    actual: report.network.loadingFailures.length,
  });
  const unexpectedConsoleErrors = consoleDiagnostics.filter(entry => (
    entry.type === "error"
    && !EXPECTED.allowedConsoleErrors.some(pattern => matchesRule(entry.message, pattern))
  ));
  report.browserConsole.unexpectedErrors = unexpectedConsoleErrors.map(entry => ({
    type: entry.type,
    message: summarizeText(entry.message),
  }));
  addCheck("unexpected-console-errors", unexpectedConsoleErrors.length === 0, {
    actual: unexpectedConsoleErrors.length,
  });
  console.log(`TEST_4_${viewportMatches ? "OK" : "FAIL"} responsive`);

  report.finishedAt = new Date().toISOString();
  report.durationMs = Date.parse(report.finishedAt) - Date.parse(report.startedAt);
  report.status = report.checks.some(check => check.status === "FAIL") ? "FAIL" : "PASS";
  if (report.status !== "PASS") {
    throw new Error(`El escenario contiene ${report.checks.filter(check => check.status === "FAIL").length} comprobaciones fallidas.`);
  }
}

function writeReport() {
  if (!report.finishedAt) report.finishedAt = new Date().toISOString();
  if (!report.durationMs) report.durationMs = Date.parse(report.finishedAt) - Date.parse(report.startedAt);
  const reportPath = path.join(ARTIFACTS_DIR, "report.json");
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  return reportPath;
}

async function closeBrowser() {
  if (cdp && !browserCloseRequested) {
    browserCloseRequested = true;
    try { await cdp.send("Browser.close"); } catch (_) {}
  }
  if (chrome.exitCode == null && !chrome.killed) chrome.kill("SIGTERM");
}

run()
  .then(() => {
    const reportPath = writeReport();
    console.log(`REPORT ${reportPath}`);
    console.log(`SCENARIO_RESULT ${report.scenario.id} PASS`);
    console.log(`ORDERS_CREATED ${report.createdResources.orderIds.length}`);
  })
  .catch(error => {
    report.finishedAt = new Date().toISOString();
    report.durationMs = Date.parse(report.finishedAt) - Date.parse(report.startedAt);
    report.status = "FAIL";
    report.error = {
      type: error.name || "Error",
      message: redactText(error.message || error),
    };
    if (!report.checks.some(check => check.status === "FAIL")) {
      addCheck("runner-completed", false, { errorType: report.error.type });
    }
    if (chromeStderr) report.chromeDiagnostic = summarizeText(redactText(chromeStderr.slice(-4000), 4000));
    const reportPath = writeReport();
    console.error("TEST_FAILURE", report.error.message);
    console.log(`REPORT ${reportPath}`);
    console.log(`SCENARIO_RESULT ${report.scenario.id} FAIL`);
    process.exitCode = 1;
  })
  .finally(async () => {
    await closeBrowser();
    try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch (_) {}
  });
