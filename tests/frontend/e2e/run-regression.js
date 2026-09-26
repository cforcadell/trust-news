#!/usr/bin/env node

/** Ejecuta los casos Light y Blockchain y agrega evidencia reproducible. */

const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const TEST_DIR = __dirname;
const REPO_ROOT = path.resolve(TEST_DIR, "..", "..");
const UI_RUNNER = path.join(TEST_DIR, "ui-smoke-test.js");
const DEFAULT_CASES = [
  path.join(TEST_DIR, "cases", "light.json"),
  path.join(TEST_DIR, "cases", "blockchain.json"),
];
const RUN_ID = process.env.ASSERMETRY_RUN_ID
  || `reg-${new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-")}`;
const ARTIFACTS_DIR = path.resolve(
  process.env.ASSERMETRY_ARTIFACTS_DIR
  || path.join(os.tmpdir(), `assermetry-regression-${RUN_ID}`),
);
const CASE_FILES = parseCaseFiles();
const SETUP_HOOK = optionalPath("ASSERMETRY_SETUP_HOOK");
const CLEANUP_HOOK = optionalPath("ASSERMETRY_CLEANUP_HOOK");
const REQUIRE_MANAGED_STATE = booleanEnvironment("ASSERMETRY_REQUIRE_MANAGED_STATE", false);
const CAPTURE_K8S_BASELINE = booleanEnvironment("ASSERMETRY_CAPTURE_K8S_BASELINE", false);
const REQUIRE_K8S_BASELINE = booleanEnvironment("ASSERMETRY_REQUIRE_K8S_BASELINE", false);
const STOP_ON_FAILURE = booleanEnvironment("ASSERMETRY_STOP_ON_FAILURE", false);
const VALIDATE_ONLY = process.argv.includes("--validate");

if (fs.existsSync(ARTIFACTS_DIR) && fs.readdirSync(ARTIFACTS_DIR).length > 0) {
  throw new Error(`El directorio de artefactos debe estar vacío: ${ARTIFACTS_DIR}`);
}
fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });

const manifest = {
  schemaVersion: 1,
  runId: RUN_ID,
  startedAt: new Date().toISOString(),
  repository: {
    commit: commandOutput("git", ["rev-parse", "HEAD"]),
    dirty: Boolean(commandOutput("git", ["status", "--porcelain"])),
  },
  environment: {
    nodeVersion: process.version,
    chromeVersion: commandOutput(process.env.CHROME_BIN || "/usr/bin/google-chrome", ["--version"]),
    frontendUrl: sanitizeUrl(process.env.ASSERMETRY_URL || "https://localhost:7443/gui/"),
  },
  runtimeMetadata: {
    provider: optionalValue("ASSERMETRY_PROVIDER"),
    model: optionalValue("ASSERMETRY_MODEL"),
    llmHttpTimeoutSeconds: optionalNumber("ASSERMETRY_HTTP_TIMEOUT_SECONDS"),
  },
  cases: CASE_FILES.map(file => path.relative(REPO_ROOT, file)),
  lifecycle: {
    managedStateRequired: REQUIRE_MANAGED_STATE,
    setupConfigured: Boolean(SETUP_HOOK),
    cleanupConfigured: Boolean(CLEANUP_HOOK),
    setup: "NOT_RUN",
    cleanup: "NOT_RUN",
  },
  kubernetesBaseline: {
    requested: CAPTURE_K8S_BASELINE || REQUIRE_K8S_BASELINE,
    required: REQUIRE_K8S_BASELINE,
    status: "NOT_RUN",
  },
};

const summary = {
  schemaVersion: 1,
  runId: RUN_ID,
  status: "RUNNING",
  startedAt: manifest.startedAt,
  managedState: Boolean(SETUP_HOOK && CLEANUP_HOOK),
  scenarios: [],
  totals: {
    scenarios: CASE_FILES.length,
    passed: 0,
    failed: 0,
    ordersCreated: 0,
    checksPassed: 0,
    checksFailed: 0,
    unexpectedHttpFailures: 0,
    networkLoadingFailures: 0,
    unexpectedConsoleErrors: 0,
  },
};

function booleanEnvironment(name, fallback) {
  const value = process.env[name];
  if (value == null || value === "") return fallback;
  return new Set(["1", "true", "yes", "on"]).has(String(value).toLowerCase());
}

function optionalValue(name) {
  const value = String(process.env[name] || "").trim();
  return value || null;
}

function optionalNumber(name) {
  const value = optionalValue(name);
  if (value == null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function optionalPath(name) {
  const value = optionalValue(name);
  return value ? path.resolve(value) : null;
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
    .replace(/((?:password|secret|token)\s*[=:]\s*)[^\s,;]+/gi, "$1[REDACTED]")
    .slice(0, maximumLength);
}

function commandOutput(command, args) {
  const result = spawnSync(command, args, {
    cwd: REPO_ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  });
  return result.status === 0 ? String(result.stdout || "").trim() || null : null;
}

function parseCaseFiles() {
  const configured = String(process.env.ASSERMETRY_CASES || "").trim();
  const files = configured
    ? configured.split(",").map(value => value.trim()).filter(Boolean).map(value => path.resolve(value))
    : DEFAULT_CASES;
  if (files.length === 0) throw new Error("ASSERMETRY_CASES no contiene casos.");
  for (const file of files) {
    if (!fs.existsSync(file)) throw new Error(`No existe el caso: ${file}`);
  }
  return files;
}

function loadJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function writeJson(name, value) {
  const destination = path.join(ARTIFACTS_DIR, name);
  fs.writeFileSync(destination, `${JSON.stringify(value, null, 2)}\n`);
  return destination;
}

function childEnvironment(testCase, caseFile, scenarioDir, index) {
  const environment = { ...process.env };
  for (const name of Object.keys(environment)) {
    if (/(PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY)/i.test(name)) delete environment[name];
  }
  delete environment.ASSERMETRY_NEWS;
  delete environment.ASSERMETRY_NEWS_FILE;
  delete environment.ASSERMETRY_VALIDATION_MODE;
  delete environment.ASSERMETRY_CASE_FILE;
  const usernameName = testCase.identity?.usernameEnv;
  const passwordName = testCase.identity?.passwordEnv;
  const username = usernameName ? process.env[usernameName] : process.env.ASSERMETRY_USERNAME;
  const password = passwordName ? process.env[passwordName] : process.env.ASSERMETRY_PASSWORD;
  if (!username || !password) {
    throw new Error(
      `Faltan credenciales para ${testCase.id}: ${usernameName || "ASSERMETRY_USERNAME"} y/o ${passwordName || "ASSERMETRY_PASSWORD"}.`,
    );
  }
  return {
    ...environment,
    ASSERMETRY_USERNAME: username,
    ASSERMETRY_PASSWORD: password,
    ASSERMETRY_CASE_FILE: caseFile,
    ASSERMETRY_VALIDATION_MODE: String(testCase.mode || "").toUpperCase(),
    ASSERMETRY_RUN_ID: RUN_ID,
    ASSERMETRY_ARTIFACTS_DIR: scenarioDir,
    ASSERMETRY_DEBUG_PORT: String(Number(process.env.ASSERMETRY_DEBUG_PORT || 9223) + index),
  };
}

function hookEnvironment() {
  return {
    ...process.env,
    ASSERMETRY_RUN_ID: RUN_ID,
    ASSERMETRY_ARTIFACTS_DIR: ARTIFACTS_DIR,
    ASSERMETRY_CASES: CASE_FILES.join(","),
  };
}

function runProcess(command, args, options = {}) {
  return new Promise(resolve => {
    const child = spawn(command, args, {
      cwd: REPO_ROOT,
      env: options.env || process.env,
      shell: false,
      stdio: "inherit",
    });
    child.on("error", error => resolve({ status: "FAIL", exitCode: null, error: redactText(error.message) }));
    child.on("exit", (code, signal) => resolve({
      status: code === 0 ? "PASS" : "FAIL",
      exitCode: code,
      signal: signal || null,
    }));
  });
}

async function runHook(kind, executable) {
  if (!executable) {
    manifest.lifecycle[kind] = "NOT_CONFIGURED";
    return { status: "NOT_CONFIGURED" };
  }
  if (!fs.existsSync(executable)) {
    manifest.lifecycle[kind] = "FAIL";
    return { status: "FAIL", error: `No existe el hook: ${executable}` };
  }
  console.log(`LIFECYCLE_${kind.toUpperCase()} ${path.basename(executable)}`);
  const result = await runProcess(executable, [], { env: hookEnvironment() });
  manifest.lifecycle[kind] = result.status;
  return result;
}

async function runScenario(caseFile, index) {
  const testCase = loadJson(caseFile);
  const scenarioId = String(testCase.id || `scenario-${index + 1}`);
  const safeScenarioId = scenarioId.replace(/[^a-zA-Z0-9._-]/g, "-");
  const scenarioDir = path.join(ARTIFACTS_DIR, safeScenarioId);
  fs.mkdirSync(scenarioDir, { recursive: true });
  console.log(`SCENARIO_START ${scenarioId}`);

  let result;
  try {
    result = await runProcess(process.execPath, [UI_RUNNER], {
      env: childEnvironment(testCase, caseFile, scenarioDir, index),
    });
  } catch (error) {
    result = { status: "FAIL", exitCode: null, error: redactText(error.message) };
  }

  const reportPath = path.join(scenarioDir, "report.json");
  let scenarioReport = null;
  try {
    scenarioReport = loadJson(reportPath);
  } catch (error) {
    result.status = "FAIL";
    result.error = result.error || `No se pudo leer report.json: ${redactText(error.message)}`;
  }
  const checks = scenarioReport?.checks || [];
  const scenarioSummary = {
    id: scenarioId,
    organization: testCase.organization || "unspecified",
    mode: testCase.mode || null,
    status: result.status === "PASS" && scenarioReport?.status === "PASS" ? "PASS" : "FAIL",
    exitCode: result.exitCode,
    durationMs: scenarioReport?.durationMs ?? null,
    finalStatus: scenarioReport?.tests?.find(item => item.id === 3)?.order?.status ?? null,
    ordersCreated: scenarioReport?.createdResources?.orderIds?.length || 0,
    checksPassed: checks.filter(check => check.status === "PASS").length,
    checksFailed: checks.filter(check => check.status === "FAIL").length,
    unexpectedHttpFailures: scenarioReport?.network?.unexpectedFailedResponses?.length || 0,
    networkLoadingFailures: scenarioReport?.network?.loadingFailures?.length || 0,
    unexpectedConsoleErrors: scenarioReport?.browserConsole?.unexpectedErrors?.length || 0,
    report: path.relative(ARTIFACTS_DIR, reportPath),
    error: result.error || scenarioReport?.error || null,
  };
  console.log(`SCENARIO_END ${scenarioId} ${scenarioSummary.status}`);
  return scenarioSummary;
}

function validateCaseDefinition(caseFile) {
  const testCase = loadJson(caseFile);
  if (testCase.schemaVersion !== 1) throw new Error(`${caseFile}: schemaVersion debe ser 1.`);
  if (!testCase.id || !/^[a-zA-Z0-9._-]+$/.test(testCase.id)) {
    throw new Error(`${caseFile}: id ausente o no apto para un nombre de directorio.`);
  }
  if (!new Set(["LIGHT", "BLOCKCHAIN"]).has(String(testCase.mode || "").toUpperCase())) {
    throw new Error(`${caseFile}: mode debe ser LIGHT o BLOCKCHAIN.`);
  }
  if (!testCase.identity?.alias || !testCase.identity?.usernameEnv || !testCase.identity?.passwordEnv) {
    throw new Error(`${caseFile}: identity debe declarar alias, usernameEnv y passwordEnv.`);
  }
  if (!testCase.newsFile) throw new Error(`${caseFile}: falta newsFile.`);
  const newsFile = path.resolve(path.dirname(caseFile), testCase.newsFile);
  if (!fs.existsSync(newsFile) || !fs.readFileSync(newsFile, "utf8").trim()) {
    throw new Error(`${caseFile}: newsFile no existe o está vacío.`);
  }
  if (!Array.isArray(testCase.expected?.terminalStatuses) || testCase.expected.terminalStatuses.length === 0) {
    throw new Error(`${caseFile}: expected.terminalStatuses debe ser una lista no vacía.`);
  }
  for (const name of ["minimumAssertions", "minimumValidations", "validatorsPending"]) {
    const value = Number(testCase.expected?.[name]);
    if (!Number.isInteger(value) || value < 0) {
      throw new Error(`${caseFile}: expected.${name} debe ser un entero no negativo.`);
    }
  }
  return testCase;
}

function captureKubernetesBaseline() {
  const commands = [
    {
      id: "nodes",
      args: ["get", "nodes", "-o", "custom-columns=NAME:.metadata.name,READY:.status.conditions[-1].status,VERSION:.status.nodeInfo.kubeletVersion"],
    },
    { id: "nodeResources", args: ["top", "nodes"] },
    {
      id: "pods",
      args: ["get", "pods", "-A", "-o", "custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,PHASE:.status.phase,RESTARTS:.status.containerStatuses[*].restartCount"],
    },
    { id: "podResources", args: ["top", "pods", "-A", "--containers"] },
    { id: "persistentVolumes", args: ["get", "pvc", "-A"] },
  ];
  const baseline = { capturedAt: new Date().toISOString(), commands: {} };
  let successful = true;
  for (const command of commands) {
    const result = spawnSync("kubectl", command.args, {
      cwd: REPO_ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    baseline.commands[command.id] = {
      exitCode: result.status,
      output: result.status === 0 ? String(result.stdout || "").trim() : null,
      error: result.status === 0 ? null : redactText(result.stderr || result.error?.message || "kubectl falló"),
    };
    if (result.status !== 0) successful = false;
  }
  manifest.kubernetesBaseline.status = successful ? "PASS" : "PARTIAL";
  writeJson("kubernetes-baseline.json", baseline);
  return successful;
}

function aggregateScenario(scenario) {
  summary.scenarios.push(scenario);
  if (scenario.status === "PASS") summary.totals.passed += 1;
  else summary.totals.failed += 1;
  summary.totals.ordersCreated += scenario.ordersCreated;
  summary.totals.checksPassed += scenario.checksPassed;
  summary.totals.checksFailed += scenario.checksFailed;
  summary.totals.unexpectedHttpFailures += scenario.unexpectedHttpFailures;
  summary.totals.networkLoadingFailures += scenario.networkLoadingFailures;
  summary.totals.unexpectedConsoleErrors += scenario.unexpectedConsoleErrors;
}

async function main() {
  writeJson("manifest.json", manifest);
  if (VALIDATE_ONLY) {
    const validatedCases = CASE_FILES.map(validateCaseDefinition);
    manifest.validationOnly = true;
    manifest.finishedAt = new Date().toISOString();
    summary.validationOnly = true;
    summary.status = "PASS";
    summary.finishedAt = manifest.finishedAt;
    summary.durationMs = Date.parse(summary.finishedAt) - Date.parse(summary.startedAt);
    summary.scenarios = validatedCases.map(testCase => ({
      id: testCase.id,
      organization: testCase.organization,
      mode: testCase.mode,
      status: "VALID",
    }));
    writeJson("manifest.json", manifest);
    const summaryPath = writeJson("summary.json", summary);
    console.log(`REGRESSION_CONFIG_VALID cases=${validatedCases.length}`);
    console.log(`REGRESSION_REPORT ${summaryPath}`);
    return;
  }
  let setupResult = { status: "NOT_CONFIGURED" };
  let cleanupResult = { status: "NOT_CONFIGURED" };
  let baselinePassed = !REQUIRE_K8S_BASELINE;

  try {
    CASE_FILES.forEach(validateCaseDefinition);
    if (REQUIRE_MANAGED_STATE && (!SETUP_HOOK || !CLEANUP_HOOK)) {
      throw new Error("La ejecución exige ASSERMETRY_SETUP_HOOK y ASSERMETRY_CLEANUP_HOOK.");
    }
    setupResult = await runHook("setup", SETUP_HOOK);
    if (setupResult.status === "FAIL") throw new Error(setupResult.error || "Falló el hook de preparación.");

    for (let index = 0; index < CASE_FILES.length; index += 1) {
      const scenario = await runScenario(CASE_FILES[index], index);
      aggregateScenario(scenario);
      if (STOP_ON_FAILURE && scenario.status === "FAIL") break;
    }

    if (CAPTURE_K8S_BASELINE || REQUIRE_K8S_BASELINE) {
      baselinePassed = captureKubernetesBaseline();
    }
  } catch (error) {
    summary.runnerError = { type: error.name || "Error", message: redactText(error.message) };
  } finally {
    cleanupResult = await runHook("cleanup", CLEANUP_HOOK);
  }

  manifest.finishedAt = new Date().toISOString();
  summary.finishedAt = manifest.finishedAt;
  summary.durationMs = Date.parse(summary.finishedAt) - Date.parse(summary.startedAt);
  summary.managedState = setupResult.status === "PASS" && cleanupResult.status === "PASS";
  const allScenariosRan = summary.scenarios.length === CASE_FILES.length;
  const lifecyclePassed = (!REQUIRE_MANAGED_STATE || (
    setupResult.status === "PASS" && cleanupResult.status === "PASS"
  ));
  const cleanupDidNotFail = cleanupResult.status !== "FAIL";
  summary.status = (
    !summary.runnerError
    && allScenariosRan
    && summary.totals.failed === 0
    && lifecyclePassed
    && cleanupDidNotFail
    && baselinePassed
  ) ? "PASS" : "FAIL";
  summary.lifecycle = manifest.lifecycle;
  summary.kubernetesBaseline = manifest.kubernetesBaseline;
  writeJson("manifest.json", manifest);
  const summaryPath = writeJson("summary.json", summary);
  console.log(`REGRESSION_REPORT ${summaryPath}`);
  console.log(`REGRESSION_RESULT ${summary.status}`);
  if (summary.status !== "PASS") process.exitCode = 1;
}

main().catch(error => {
  console.error("REGRESSION_FAILURE", redactText(error.message || error));
  process.exitCode = 1;
});
