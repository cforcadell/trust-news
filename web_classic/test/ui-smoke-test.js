#!/usr/bin/env node

/**
 * Smoke/E2E visual del frontend clásico mediante Chrome DevTools Protocol.
 *
 * No requiere Playwright ni Selenium. Ejecuta cuatro escenarios sobre una sola
 * orden: login, alta, seguimiento del resultado y revisión responsive.
 */

const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const DEFAULT_NEWS_FILE = path.join(REPO_ROOT, "docs", "fake_news", "news.txt");
const FRONTEND_URL = process.env.ASSERMETRY_URL || "https://localhost:7443/gui/";
const USERNAME = process.env.ASSERMETRY_USERNAME;
const PASSWORD = process.env.ASSERMETRY_PASSWORD;
const CHROME_BIN = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const DEBUG_PORT = Number(process.env.ASSERMETRY_DEBUG_PORT || 9223);
const VALIDATION_MODE = String(process.env.ASSERMETRY_VALIDATION_MODE || "LIGHT").toUpperCase();
const RESULT_TIMEOUT_MS = Number(process.env.ASSERMETRY_RESULT_TIMEOUT_MS || 5 * 60 * 1000);
const MOBILE_WIDTH = Number(process.env.ASSERMETRY_MOBILE_WIDTH || 390);
const MOBILE_HEIGHT = Number(process.env.ASSERMETRY_MOBILE_HEIGHT || 844);
const runId = new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-");
const ARTIFACTS_DIR = process.env.ASSERMETRY_ARTIFACTS_DIR
  || path.join(os.tmpdir(), `assermetry-ui-${runId}`);

function loadNews() {
  if (process.env.ASSERMETRY_NEWS) return process.env.ASSERMETRY_NEWS.trim();
  const newsFile = process.env.ASSERMETRY_NEWS_FILE || DEFAULT_NEWS_FILE;
  return fs.readFileSync(newsFile, "utf8").trim();
}

if (!USERNAME || !PASSWORD) {
  console.error("Faltan ASSERMETRY_USERNAME y/o ASSERMETRY_PASSWORD.");
  process.exit(2);
}

if (!new Set(["LIGHT", "BLOCKCHAIN"]).has(VALIDATION_MODE)) {
  console.error("ASSERMETRY_VALIDATION_MODE debe ser LIGHT o BLOCKCHAIN.");
  process.exit(2);
}

const NEWS = loadNews();
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), "assermetry-chrome-"));
fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });

const report = {
  startedAt: new Date().toISOString(),
  frontendUrl: FRONTEND_URL,
  validationMode: VALIDATION_MODE,
  tests: [],
  console: [],
  failedResponses: [],
  artifacts: [],
};

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
], { stdio: ["ignore", "ignore", "pipe"] });

let chromeStderr = "";
chrome.stderr.on("data", chunk => { chromeStderr += chunk.toString(); });

const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

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
  constructor(webSocketUrl) {
    this.socket = new WebSocket(webSocketUrl);
    this.sequence = 0;
    this.pending = new Map();
    this.listeners = new Map();
  }

  async open() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", event => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const waiter = this.pending.get(message.id);
        if (!waiter) return;
        this.pending.delete(message.id);
        if (message.error) waiter.reject(new Error(message.error.message));
        else waiter.resolve(message.result);
        return;
      }
      for (const listener of this.listeners.get(message.method) || []) {
        listener(message.params || {});
      }
    });
  }

  on(method, listener) {
    if (!this.listeners.has(method)) this.listeners.set(method, []);
    this.listeners.get(method).push(listener);
  }

  send(method, params = {}) {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
}

async function run() {
  const target = await retry(async () => {
    const response = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`);
    const targets = await response.json();
    return targets.find(item => item.type === "page");
  });

  const cdp = new CdpClient(target.webSocketDebuggerUrl);
  await cdp.open();
  cdp.on("Runtime.consoleAPICalled", params => {
    report.console.push({
      type: params.type,
      values: (params.args || []).map(arg => arg.value ?? arg.description ?? "").join(" "),
    });
  });
  cdp.on("Network.responseReceived", params => {
    const response = params.response || {};
    if (response.status >= 400) {
      report.failedResponses.push({ status: response.status, url: response.url });
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
    const outputPath = path.join(ARTIFACTS_DIR, name);
    fs.writeFileSync(outputPath, Buffer.from(image.data, "base64"));
    report.artifacts.push(outputPath);
  }

  async function snapshot() {
    return evaluate(`(() => ({
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
  }

  // Prueba 1: acceso, certificado autofirmado, Keycloak y página autenticada.
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
  report.tests.push({ id: 1, name: "Acceso y autenticación", login, home });
  console.log("TEST_1_OK acceso_y_autenticacion");

  // Prueba 2: única operación que crea una orden y consume cuotas.
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
  await screenshot("03-after-submit-desktop.png");
  report.tests.push({ id: 2, name: "Alta de una única noticia", submission });
  console.log(`TEST_2_OK order_id=${submission.orderId}`);

  // Prueba 3: observa esa misma orden y recorre sus pestañas; no crea otra.
  const statusHistory = [];
  const terminal = new Set([
    "ASSERTIONS_NOT_AVAILABLE",
    "QUOTA_EXCEDED",
    "NO_VALIDATORS_AVAILABLE",
    "FAILED",
    "ERROR",
  ]);
  const deadline = Date.now() + RESULT_TIMEOUT_MS;
  let order = {};
  while (Date.now() < deadline) {
    order = await evaluate("(() => { try { return currentOrderData || {}; } catch (_) { return {}; } })()");
    const status = String(order?.status || "UNKNOWN");
    if (statusHistory.at(-1)?.status !== status) {
      statusHistory.push({ at: new Date().toISOString(), status });
      console.log(`ORDER_STATUS ${status}`);
    }
    if (status.startsWith("VALIDATED") || terminal.has(status.toUpperCase())) break;
    await delay(3000);
  }
  await delay(1000);
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
    tabContents[tab.key] = await evaluate("document.querySelector('#tabContent')?.innerText || ''");
  }
  await evaluate("document.querySelector('#orderTabs [data-tab-key=\"summary\"]')?.click()");
  await delay(300);
  const resultDesktop = await snapshot();
  await screenshot("04-result-desktop.png");
  report.tests.push({
    id: 3,
    name: "Seguimiento y resultado de la misma orden",
    statusHistory,
    order,
    tabs,
    tabContents,
    resultDesktop,
  });
  console.log(`TEST_3_DONE final_status=${order?.status || "UNKNOWN"}`);

  // Prueba 4: cambia únicamente el viewport; no crea otra orden.
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: MOBILE_WIDTH,
    height: MOBILE_HEIGHT,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await delay(600);
  const mobileResult = await snapshot();
  await screenshot("05-result-mobile.png");
  await evaluate("showSection('news', false); true");
  await delay(300);
  const mobileHome = await snapshot();
  await screenshot("06-home-mobile.png");
  report.tests.push({ id: 4, name: "Responsive de la misma sesión", mobileResult, mobileHome });
  console.log("TEST_4_OK responsive");

  report.finishedAt = new Date().toISOString();
  report.orderCountCreated = 1;
  const reportPath = path.join(ARTIFACTS_DIR, "report.json");
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(`REPORT ${reportPath}`);
  console.log("ORDERS_CREATED 1");
  await cdp.send("Browser.close");
}

run()
  .catch(error => {
    report.finishedAt = new Date().toISOString();
    report.error = error.stack || error.message;
    fs.writeFileSync(path.join(ARTIFACTS_DIR, "report-error.json"), JSON.stringify(report, null, 2));
    console.error("TEST_FAILURE", error.stack || error.message);
    console.error(chromeStderr.slice(-4000));
    chrome.kill("SIGTERM");
    process.exitCode = 1;
  })
  .finally(() => {
    try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch (_) {}
  });
