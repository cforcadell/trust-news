

// =========================================================
// CONFIGURACIÓN GLOBAL
// =========================================================
const BACKEND_BASE = "/backend";

const API = BACKEND_BASE;
const TX_API = BACKEND_BASE;
const IPFS_API = BACKEND_BASE;
const GENERATE_API = BACKEND_BASE;

const MAX_EVENTS_ROWS = 15;
const POLLING_DURATION = 0; // 20 segundos
const POLLING_INTERVAL = 1000;  // 1 segundo

const TABLE_PAGE_SIZE_ORDERS = 10;   // cantidad por página
let TABLE_PAGE_ORDERS = 1;           // página actual

const CATEGORY_IDS = window.I18N?.getCategoryIds() || [];

const VALIDATOR_TYPE_LABELS = {
    1: "LLM memoria",
    2: "LLM con búsqueda",
    3: "RAG con evidencias",
    4: "Determinista",
    5: "Humano",
    LLM_MEMORY_VALIDATION: "LLM memoria",
    LLM_SEARCH_VALIDATION: "LLM con búsqueda",
    RAG_EVIDENCE_VALIDATION: "RAG con evidencias",
    DETERMINISTIC_VALIDATION: "Determinista",
    HUMAN: "Humano"
};

const keycloak = new Keycloak({
    url: '/auth',
    realm: 'TrustNews',
    clientId: 'TrustNewsWeb'
});

function t(key, params = {}) {
    return window.I18N?.t(key, params) || key;
}

function categoryLabel(id) {
    return t(`ui.categoriesMap.${id}`);
}


// =========================================================
// UTILIDAD: Toast Notifications (UI no bloqueante)
// =========================================================
function alertMessage(message, type = 'info', duration = 3000) {
    const bar = document.getElementById('statusBar');

    // Resetear clases y aplicar el mensaje
    bar.className = 'status-toast';
    bar.textContent = message;

    // Aplicar tipo (color)
    if(type === 'error') bar.style.backgroundColor = '#ef4444';
    else if(type === 'primary' || type === 'success') bar.style.backgroundColor = '#10b981';
    else bar.style.backgroundColor = '#3b82f6';
    bar.style.color = '#fff';

    // Forzar reflow para reiniciar la animación y mostrar
    void bar.offsetWidth;
    bar.classList.add('show');

    setTimeout(() => {
        bar.classList.remove('show');
    }, duration);
}






// Variable global para almacenar la última orden cargada
let currentOrderData = {};
let currentOrderEvents = [];
let restoringHistoryState = false;

function buildHistoryUrl(state) {
    if (!state?.section) return window.location.pathname;
    const value = state.value ? `/${encodeURIComponent(state.value)}` : "";
    return `#${state.section}${value}`;
}

function updateAppHistory(state, replace = false) {
    if (restoringHistoryState) return;
    if (!state?.section) return;
    const current = history.state || {};
    const sameState =
        current.section === state.section &&
        current.inputId === state.inputId &&
        current.value === state.value;
    if (sameState && !replace) return;

    const method = replace ? "replaceState" : "pushState";
    history[method](state, "", buildHistoryUrl(state));
}

function isEditableTarget(target) {
    if (!target) return false;
    const tag = target.tagName ? target.tagName.toLowerCase() : "";
    return (
        tag === "input" ||
        tag === "textarea" ||
        tag === "select" ||
        target.isContentEditable
    );
}

// =========================================================
// UTILIDADES
// =========================================================
// Nuevo Helper para llamadas al Backend
async function fetchWithAuth(url, options = {}) {
    try {
        // Actualizar token si expira en menos de 30s
        await keycloak.updateToken(30);
    } catch (error) {
        console.error("Fallo al refrescar el token", error);
        keycloak.login();
        return;
    }

    const headers = {
        ...options.headers,
        'Authorization': `Bearer ${keycloak.token}`,
        'Content-Type': 'application/json'
    };

    return fetch(url, { ...options, headers });
}

function escapeHTML(str) {
    return str.replace(/[&<>"']/g, function(match) {
        return ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        })[match];
    });
}


function shortHex(value) {
  if (!value || typeof value !== "string") return "";
  if (value.startsWith("0x") && value.length > 16) {
    const short = value.slice(0, 10) + "…" + value.slice(-6);
    return `<span title="${safeText(value)}">${safeText(short)}</span>`;
  }
  return safeText(value);
}

function getSelectedValidationMode() {
    return document.getElementById("validationMode")?.value || "BLOCKCHAIN";
}

function isLightOrder(order) {
    return String(order?.validation_mode || "BLOCKCHAIN").toUpperCase() === "LIGHT";
}

function updateValidationModeHelp() {
    const selected = getSelectedValidationMode();
    document.querySelectorAll("[data-mode-help]").forEach(el => {
        el.hidden = el.getAttribute("data-mode-help") !== selected;
    });
}

function getValidationLiteral(value) {
    const numericValue = parseInt(value, 10);
    if (isNaN(numericValue)) return "DESCONOCIDO";

    switch (numericValue) {
        case 1: return "True";
        case 2: return "False";
        case 0: return "Unknown";
        default: return "VALOR ERRONEO";
    }
}

function formatDate(ts) {
    const timestampValue = parseFloat(ts);
    if (isNaN(timestampValue) || timestampValue === 0) return "N/A";
    const milliseconds = timestampValue * 1000;
    const d = new Date(milliseconds);
    return isNaN(d.getTime()) ? t("ui.invalidDate") : d.toISOString().replace("T"," ").split(".")[0];
}


function mapVeredict(v) {
    switch (v) {
        case 0: return "<span class='partial-news'>Unknown</span>";
        case 1: return "<span class='true-news'>True</span>";
        case 2: return "<span class='false-news'>False</span>";
        default: return "<span class='unknown'>?</span>";
    }
}

// =========================================================
// SECCIÓN Y NAVEGACIÓN
// =========================================================
function showSection(sectionId, reset = true, updateHistory = true) {
    const sections = document.querySelectorAll("section");
    sections.forEach(sec => sec.classList.remove("active"));

    const activeSection = document.getElementById(sectionId);
    if (!activeSection) {
        console.warn(`No se encontró la sección con id '${sectionId}'`);
        return;
    }
    activeSection.classList.add("active");
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.getAttribute('onclick').includes(`'${sectionId}'`)) {
            btn.classList.add('active');
        }
    });

    if(reset) {
        // ===== RESET de inputs de usuario =====
        const inputs = activeSection.querySelectorAll("input:not([type=button]):not([type=submit]), textarea");
        inputs.forEach(input => input.value = "");

        // ===== RESET de tablas generadas dinámicamente =====
        const tables = activeSection.querySelectorAll("table");
        tables.forEach(table => table.innerHTML = "");

        // ===== RESET de divs dinámicos si los hay =====
        const divsDinamicos = activeSection.querySelectorAll(".dynamic-content");
        divsDinamicos.forEach(div => div.innerHTML = "");
    }

        if (updateHistory) {
            updateAppHistory({ section: sectionId });
        }

        if (sectionId === "orders") {
            listOrders();
        }

        if (sectionId === "validators" && reset) {
            listValidatorsCache();
        }
}





// =========================================================
// POLLING DE ÓRDENES
// =========================================================
async function pollOrder(orderId, startTime) {
    const start = startTime || Date.now();
    await loadOrderById(orderId, false);

    const detailsContainer = document.getElementById("fixedDetailsContainer");
    const statusElement = detailsContainer.querySelector('.status-value') || document.querySelector('#tabContent .status-value');
    const currentStatus = statusElement?.getAttribute('data-status') || 'UNKNOWN';

    if (currentStatus === 'VALIDATED' || (Date.now() - start > POLLING_DURATION)) {
        statusElement?.classList.remove('polling', 'blinking');
        console.log(`Polling finalizado para ${orderId}. Estado: ${currentStatus}`);
        if (currentStatus === 'VALIDATED') await loadOrderById(orderId, true);
        return;
    }

    setTimeout(() => pollOrder(orderId, start), POLLING_INTERVAL);
}

// ========================================================
// OPERACIONES DE ASSERTIONS
// ========================================================

function renderAssertionsProgress(container, message, percent = 0) {
    if (!container) return;
    container.innerHTML = `
        <div class="validation-progress">
            <span>${escapeHTML(message)}</span>
            <div class="validation-progress-bar">
                <div class="validation-progress-fill" style="width:${Math.min(100, Math.max(0, percent))}%;"></div>
            </div>
        </div>
    `;
}

async function generateAssertionsFromText(text) {
    try {
        const response = await fetchWithAuth(`${GENERATE_API}/assertions/generate`, {
            method: "POST",
            headers: {
                "Accept": "application/json"
            },
            body: JSON.stringify({ text })
        });

        // 🟢 NUEVO: Detectar si el usuario se ha quedado sin cuota (Status 429)
        if (response.status === 429) {
            alertMessage(t("ui.quotaReached"), "error", 5000);
            return []; // Devolvemos un array vacío para no romper la tabla de la interfaz
        }

        // Si es otro tipo de error (500, 404, etc.)
        if (!response.ok) throw new Error(`Error API: ${response.status}`);

        const data = await response.json();
        return data.payload.assertions || [];
    } catch (err) {
        console.error("Error al generar aserciones:", err);
        alertMessage(t("ui.assertionsServiceError"), "error");
        return [];
    }
}

function attachAssertionTableEvents(container) {

    // ======================
    // Borrar fila existente
    // ======================
    container.querySelectorAll(".btn-delete-row").forEach(btn => {
        btn.addEventListener("click", e => {
            e.target.closest("tr").remove();
        });
    });

    // ======================
    // Añadir fila nueva
    // ======================
    const addBtn = container.querySelector("#btn-add-row");
    if (!addBtn) return;  // seguridad

    addBtn.addEventListener("click", () => {

        const tbody = container.querySelector("tbody");

        // Calcular último ID numérico existente
        let lastId = 0;
        tbody.querySelectorAll("tr").forEach(row => {
            const cell = row.children[0]?.textContent.trim();
            if (cell && !isNaN(cell)) {
                lastId = Math.max(lastId, parseInt(cell, 10));
            }
        });

        const nextId = lastId + 1;

        // Crear fila nueva
        const row = document.createElement("tr");
        row.setAttribute("data-id", nextId);

        row.innerHTML = `
            <td>${nextId}</td>
            <td contenteditable="true" class="editable-text"></td>
            <td>${renderCategorySelect(1)}</td>
            <td><button class="btn-delete-row">✖</button></td>
        `;

        tbody.appendChild(row);

        // Añadir evento borrar a la nueva fila
        row.querySelector(".btn-delete-row").addEventListener("click", () => {
            row.remove();
        });
    });
}


function renderEditableAssertionsTable(container, assertions) {
    container.innerHTML = `
        <table class="compact-table">
            <thead>
                <tr>
                    <th>ID</th>
                    <th>${t("ui.assertion")}</th>
                    <th>${t("ui.category")}</th>
                    <th style="width:60px;"></th>
                </tr>
            </thead>
            <tbody>
                ${assertions.map((a, index) => {
                    const assertionId = getAssertionId(a, index + 1);
                    return `
                    <tr data-id="${safeText(assertionId)}">
                        <td>${safeText(assertionId)}</td>
                        <td contenteditable="true" class="editable-text">${safeText(extractAssertionText(a))}</td>
                        <td>${renderCategorySelect(getAssertionCategory(a) || 1)}</td>
                        <td><button class="btn-delete-row">✖</button></td>
                    </tr>`;
                }).join("")}
            </tbody>
        </table>

        <button id="btn-add-row" class="btn btn-tertiary">+</button>
        <button id="btn-publish-with-assertions" class="btn btn-tertiary">${t("ui.publishWithAssertions")}</button>
    `;

    // Conectar los eventos de edición y borrado
    attachAssertionTableEvents(container);

    // -----------------------------
    // Listener para publicar con aserciones
    // -----------------------------
    const publishBtn = container.querySelector("#btn-publish-with-assertions");
    if (publishBtn) {
        publishBtn.addEventListener("click", async () => {
            try {
                await publishWithAssertions();
            } catch (err) {
                console.error("Error al publicar con aserciones:", err);
            }
        });
    }
}


function renderCategorySelect(selected) {
    return `
        <select class="category-select">
            ${CATEGORY_IDS
                .map(id => `
                    <option value="${id}" ${selected == id ? "selected" : ""}>${categoryLabel(id)}</option>`
                ).join("")}
        </select>
    `;
}



// =========================================================
// OPERACIONES DE NEWS
// =========================================================
async function publishNew() {
    const text = document.getElementById("newsText").value.trim();
    if (!text) return alertMessage(t("ui.publishTextRequired"), 'error');

    showSection('order');
    document.getElementById("orderId").value = t("ui.publishing");

    const res = await fetchWithAuth(`${API}/orders/publishNew`, {
        method: "POST",
        body: JSON.stringify({text, validation_mode: getSelectedValidationMode()})
    });

    if (!res.ok) {
        alertMessage(t("ui.publishError"), 'error');
        document.getElementById("orderId").value = "Error...";
        return;
    }

    const data = await res.json();
    const newOrderId = data.order_id;

    document.getElementById("orderId").value = newOrderId;
    updateAppHistory({ section: "order", inputId: "orderId", value: newOrderId }, true);
    alertMessage(t("ui.newsPublished", { orderId: newOrderId }), 'primary');
    pollOrder(newOrderId);
}

async function publishWithAssertions() {
    const text = document.getElementById("newsText").value.trim();
    if (!text) return alertMessage(t("ui.publishTextRequired"), 'error');

    const container = document.getElementById("news-assertions-container");
    if (!container) return alertMessage(t("ui.assertionsContainerMissing"), 'error');

    // Construir lista de aserciones desde la tabla
    const assertions = [];
    const rows = container.querySelectorAll("tbody tr");
    rows.forEach(row => {
        const idAssertion = row.dataset.id || crypto.randomUUID(); // Genera ID si no existe
        const textCell = row.querySelector(".editable-text");
        const categorySelect = row.querySelector(".category-select");

        if (textCell && categorySelect) {
            assertions.push({
                idAssertion: idAssertion,
                text: textCell.innerText.trim(),
                categoryId: parseInt(categorySelect.value)
            });
        }
    });

    if (assertions.length === 0) {
        return alertMessage(t("ui.assertionRequired"), 'error');
    }

    const payload = { text, assertions, validation_mode: getSelectedValidationMode() };

    try {
        const response = await fetchWithAuth(`${API}/orders/publishWithAssertions`, {
            method: "POST",
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorDetail = await response.text();
            throw new Error(`Error ${response.status}: ${errorDetail}`);
        }

        const data = await response.json();

        showSection('order');

        const newOrderId = data.order_id;

        document.getElementById("orderId").value = newOrderId;
        updateAppHistory({ section: "order", inputId: "orderId", value: newOrderId }, true);
        alertMessage(t("ui.newsPublished", { orderId: newOrderId }), 'primary');
        pollOrder(newOrderId);

        return data;
    } catch (error) {
        console.error("Error al publicar con aserciones:", error);
        alertMessage(t("ui.publishAssertionsError"), 'error');
        throw error;
    }
}





async function findPrevious() {
    const text = document.getElementById("newsText").value.trim();
    if (!text) return alertMessage(t("ui.searchTextRequired"), 'error');

    alertMessage(t("ui.searchingPrevious"), 'info');

    try {
        const res = await fetchWithAuth(`${API}/find-order-by-text`, {
            method: "POST",
            body: JSON.stringify({text, validation_mode: getSelectedValidationMode()})
        });

        if (!res.ok) throw new Error("API responded with error.");

        const data = await res.json();
        renderTableData(document.getElementById("findResults"), data);
        alertMessage(t("ui.resultsFound", { count: data.length }), 'primary');
    } catch (e) {
        alertMessage(t("ui.searchError"), 'error');
        document.getElementById("findResults").innerHTML = `<tr><td colspan="3">${safeText(t("ui.resultsLoadError"))}</td></tr>`;
    }
}

// =========================================================
// OPERACIONES DE ORDERS
// =========================================================
// =========================================================
// OPERACIONES DE ORDERS
// =========================================================
async function listOrders() {
    alertMessage(t("messages.listingOrders"), 'info');

    // 1. Leemos si el check de admin está marcado (si no existe o no está marcado, valdrá false)
    const chkViewAll = document.getElementById('chk-viewAll');
    const viewAll = chkViewAll ? chkViewAll.checked : false;

    // 2. Construimos la URL con el parámetro view_all
    const url = `${API}/orders/list?view_all=${viewAll}`;

    try {
        // 3. Usamos tu helper fetchWithAuth en lugar de fetch directamente
        const res = await fetchWithAuth(url);
        if (!res.ok) throw new Error("Error al obtener la lista de órdenes.");

        const data = await res.json();

        const tabs = document.getElementById("listOrderTabs");
        const detailsContainer = document.getElementById("listFixedDetailsContainer");
        const tabContent = document.getElementById("listTabContent");
        tabs.innerHTML = detailsContainer.innerHTML = tabContent.innerHTML = "";

        renderTableData(tabContent, data);
        alertMessage(t("messages.ordersLoaded", { count: data.length }), 'primary');

    } catch (e) {
        alertMessage(t("messages.listOrdersError"), 'error');
        console.error("List Orders Error:", e);
    }
}

async function findOrder() {
    const orderId = document.getElementById("orderId").value.trim();
    if (!orderId) return alertMessage(t("messages.enterOrderId"), 'error');
    await loadOrderById(orderId, true);
    updateAppHistory({ section: "order", inputId: "orderId", value: orderId });
}

// =========================================================
// CARGA CENTRAL DE ÓRDENES
// =========================================================
async function loadOrderById(orderId, cleanup = true) {
    const tabs = document.getElementById("orderTabs");
    const detailsContainer = document.getElementById("fixedDetailsContainer");
    const tabContent = document.getElementById("tabContent");

    if (cleanup) tabs.innerHTML = '';

    if (cleanup) {
        detailsContainer.innerHTML = `<div class="p-4 text-center text-gray-400">${safeText(t("messages.loadingOrder", { orderId }))}</div>`;
    }

    try {
        const res = await fetchWithAuth(`${API}/orders/${orderId}`);

        if (!res.ok) {
            const errorText = await res.text();
            detailsContainer.innerHTML = `<div class="p-3 rounded-lg bg-red-800 border border-red-500 text-red-100">
                Error ${res.status}: No se pudo encontrar la orden <strong>${safeText(orderId)}</strong>.<br>
                Mensaje: ${safeText(errorText || 'Error desconocido')}
            </div>`;
            tabs.innerHTML = tabContent.innerHTML = '';
            alertMessage(t("messages.orderNotFound", { orderId }), 'error');
            return;
        }

        let data;
        if (res.status !== 304) {
            data = await res.json();
            currentOrderData = data;
        } else {
            data = currentOrderData;
            if (!data.order_id) return;
        }

        let eventsData = currentOrderEvents;

        if (cleanup || res.status !== 304) {
            eventsData = [];
            try {
                const resEv = await fetchWithAuth(`${API}/orders/${orderId}/events`);
                if (resEv.ok) eventsData = await resEv.json();
            } catch(e){ console.error("Error cargando eventos:", e); }
            currentOrderEvents = eventsData;

            const lightMode = isLightOrder(data);
            const orderAssertions = collectOrderAssertions(data.assertions, data);
            const sections = [
                {key: "summary", name: t("tabs.summary"), data},
                {key: "assertions", name: t("tabs.assertions"), data: orderAssertions},
                {key: "evidence", name: t("ui.evidence"), data: data.validations || {}},
                {key: "process", name: t("ui.process"), data: eventsData},
                {key: "technical", name: t("ui.technical"), data},
                {key: "ipfs", name: "IPFS", data: data.document || null, disabled: lightMode},
                {key: "events", name: t("tabs.events"), data: eventsData}
            ];

            if (cleanup || tabs.children.length === 0) {
                tabs.innerHTML = '';
                const defaultTabKey = data.status === "VALIDATED" ? "summary" : "process";
                sections.forEach((s) => {
                    const btn = document.createElement("button");
                    btn.innerText = s.name;
                    btn.dataset.tabKey = s.key;
                    btn.className = 'tab-button';
                    if (s.disabled) {
                        btn.disabled = true;
                        btn.classList.add("disabled-tab");
                        btn.title = t("ui.lightUnavailable");
                    }
                    btn.onclick = () => {
                        if (s.disabled) return;
                        document.querySelectorAll("#orderTabs button").forEach(b => b.classList.remove("activeTab"));
                        btn.classList.add("activeTab");
                        renderTabContent(s.key, s.data, orderAssertions, data, eventsData);
                    };
                    if(s.key === defaultTabKey) btn.classList.add("activeTab");
                    tabs.appendChild(btn);
                    if(s.key === defaultTabKey) renderTabContent(s.key, s.data, orderAssertions, data, eventsData);
                });
            } else {
                const activeTab = tabs.querySelector('.activeTab');
                if (activeTab) {
                    const sec = sections.find(s => s.key === activeTab.dataset.tabKey);
                    if (sec && !sec.disabled) renderTabContent(sec.key, sec.data, orderAssertions, data, eventsData);
                }
            }
        }

        detailsContainer.innerHTML = '<span class="status-value" data-status="' + safeText(data.status || "UNKNOWN") + '"></span>';
    } catch (error) {
        detailsContainer.innerHTML = `<div class="p-3 rounded-lg bg-red-800 border border-red-500 text-red-100">
            Error de conexión o JSON inválido: ${safeText(error.message)}
        </div>`;
        tabs.innerHTML = tabContent.innerHTML = '';
        console.error(error);
        alertMessage(t("messages.criticalOrderError"), 'error');
    }
}

// =========================================================
// RENDER TAB CONTENT
// =========================================================
function renderTabContent(tabName, data, assertions=[], orderData=null, events=[]) {
    const container = document.getElementById("tabContent");
    container.innerHTML = "";

    switch(tabName) {
        case "summary":
            renderOrderSummary(container, orderData || data, events);
            break;
        case "ipfs":
            if (isLightOrder(orderData)) {
                container.innerHTML = `<p class="empty-state">${safeText(t("ui.lightUnavailable"))}</p>`;
                break;
            }
            container.innerHTML = `
                <div class="json-box-header">${safeText(t("ui.ipfsDocument"))}</div>
                <div class="json-tree">${renderJsonTree(data)}</div>
            `;
            break;
        case "evidence":
            renderValidationsTree(container, data, assertions, orderData);
            break;
        case "process":
            renderOrderProcess(container, orderData, data);
            break;
        case "technical":
            renderTechnicalDetails(container, orderData || data);
            break;
        case "events":
            renderEventsTable(container, data);
            break;
        case "assertions":
            renderOrderAssertions(container, data, orderData);
            break;
        default:
            container.innerHTML = `<pre class="event-payload-pre">${safeText(JSON.stringify(data,null,2))}</pre>`;
            break;
    }
}


// =========================================================
// RENDER DETALLES Y RESUMEN
// =========================================================

function getExpectedValidationCount(data) {
    if (Array.isArray(data.validators)) {
        return data.validators.reduce((sum, validator) => {
            const list = validator?.validatorAddresses;
            return sum + (Array.isArray(list) ? list.length : 0);
        }, 0);
    }
    return 0;
}

function renderProcessingFlow(currentStatus, validatorsPending = 0, totalValidations = 0) {
    const steps = [
        "PENDING",
        "ASSERTIONS_REQUESTED",
        "DOCUMENT_CREATED",
        "IPFS_PENDING",
        "IPFS_UPLOADED",
        "BLOCKCHAIN_PENDING",
        "VALIDATION_PENDING",
        "VALIDATED"
    ];

    const currentIndex = steps.indexOf(currentStatus);
    const isValidated = currentStatus === "VALIDATED";
    return `
        <div class="process-flow">
            ${steps.map((step, i) => {
                let cls = "process-step";
                let label = "";

                if (isValidated) {
                    cls += " done";
                } else {
                    if (i < currentIndex) cls += " done";
                    else if (i === currentIndex) cls += " current";
                }

                return `<div class="${cls}" title="${step}">${label}</div>`;
            }).join('')}
        </div>
    `;
}



function pluralizeEs(count, singular, plural) {
    return `${count} ${count === 1 ? singular : plural}`;
}

function formatMaxTwoDecimals(value) {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return "0";
    return (Math.round(n * 100) / 100).toFixed(2).replace(/\.?0+$/, "");
}

function parseEventTimestamp(value) {
    if (value === null || value === undefined || value === "") return null;

    if (typeof value === "number") {
        const milliseconds = value > 9999999999 ? value : value * 1000;
        const date = new Date(milliseconds);
        return Number.isNaN(date.getTime()) ? null : date;
    }

    const raw = String(value).trim();
    const eventMatch = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$/);
    if (eventMatch) {
        const [, month, day, year, hours, minutes, seconds = "0"] = eventMatch;
        const date = new Date(Number(year), Number(month) - 1, Number(day), Number(hours), Number(minutes), Number(seconds));
        return Number.isNaN(date.getTime()) ? null : date;
    }

    const date = new Date(raw);
    return Number.isNaN(date.getTime()) ? null : date;
}

function parseOrderTimestamp(value) {
    if (value === null || value === undefined || value === "") return null;

    const raw = String(value).trim();
    const orderMatch = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$/);
    if (orderMatch) {
        const [, day, month, year, hours, minutes, seconds = "0"] = orderMatch;
        const date = new Date(Number(year), Number(month) - 1, Number(day), Number(hours), Number(minutes), Number(seconds));
        return Number.isNaN(date.getTime()) ? null : date;
    }

    return parseEventTimestamp(value);
}

function formatDurationMinutesSeconds(milliseconds) {
    if (!Number.isFinite(milliseconds) || milliseconds < 0) return "";
    return formatDurationSeconds(milliseconds / 1000);
}

function formatDurationSeconds(secondsValue) {
    const totalSeconds = Math.round(Number(secondsValue));
    if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return "-";
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = String(totalSeconds % 60).padStart(2, "0");
    return `${minutes}:${seconds}`;
}

function getEndToEndValidationDuration(order, events = []) {
    if (!Array.isArray(events) || events.length === 0) return "";

    const startActions = new Set(["request_validation", "validation_requested", "light_validation_request"]);
    const completionActions = new Set(["validation_completed", "light_validation_completed"]);
    const validationStarts = events
        .filter(event => startActions.has(event?.action))
        .map(event => parseEventTimestamp(event.timestamp))
        .filter(Boolean);
    const validationCompletions = events
        .filter(event => completionActions.has(event?.action))
        .map(event => parseEventTimestamp(event.timestamp))
        .filter(Boolean);

    if (validationCompletions.length === 0) return "";

    const startDate = validationStarts.length
        ? new Date(Math.min(...validationStarts.map(date => date.getTime())))
        : parseOrderTimestamp(order.created || order.created_at || order.createdAt);
    const endDate = new Date(Math.max(...validationCompletions.map(date => date.getTime())));

    if (!startDate || Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return "";
    return formatDurationMinutesSeconds(endDate.getTime() - startDate.getTime());
}

function getAssertionId(assertion, fallbackIndex) {
    if (!assertion || typeof assertion !== "object") return String(fallbackIndex);
    return String(assertion.idAssertion ?? assertion.id ?? assertion.assertion_id ?? fallbackIndex);
}

function collectOrderAssertions(assertions = [], orderData = null) {
    const sources = [
        assertions,
        orderData?.assertions,
        orderData?.assertions_document?.assertions,
        orderData?.document?.assertions,
        orderData?.document?.assertions_document?.assertions
    ];
    const collected = [];
    const seen = new Set();

    sources.forEach(source => {
        if (!Array.isArray(source)) return;
        source.forEach((assertion, index) => {
            if (!assertion || typeof assertion !== "object") return;
            const key = `${getAssertionId(assertion, index)}:${assertion.assertion_index ?? ""}:${extractAssertionText(assertion)}`;
            if (seen.has(key)) return;
            seen.add(key);
            collected.push(assertion);
        });
    });

    return collected;
}

function extractAssertionText(assertion) {
    if (!assertion) return "";
    if (typeof assertion === "string") return assertion;

    const candidates = [
        assertion.text,
        assertion.assertion_text,
        assertion.statement,
        assertion.claim,
        assertion.content,
        assertion.assertion?.text,
        assertion.payload?.assertion?.text,
        assertion.payload?.assertion_text
    ];

    for (const candidate of candidates) {
        if (candidate === null || candidate === undefined) continue;
        if (typeof candidate === "object" && candidate.text) return String(candidate.text).trim();
        const text = String(candidate).trim();
        if (text) return text;
    }

    return "";
}

function assertionMatchesId(assertion, assertionId, fallbackIndex) {
    if (!assertion || typeof assertion !== "object") return false;
    const expected = String(assertionId);
    const candidates = [
        assertion.idAssertion,
        assertion.id,
        assertion.assertion_id,
        assertion.assertion_index,
        Number.isFinite(Number(assertion.assertion_index)) ? Number(assertion.assertion_index) + 1 : null,
        fallbackIndex,
        Number.isFinite(Number(fallbackIndex)) ? Number(fallbackIndex) + 1 : null
    ];
    return candidates.some(candidate => candidate !== null && candidate !== undefined && String(candidate) === expected);
}

function findAssertionById(assertions = [], assertionId) {
    return (assertions || []).find((assertion, index) => assertionMatchesId(assertion, assertionId, index));
}

function resolveAssertionText(assertionId, assertions = [], orderData = null, validatorsObj = null) {
    const allAssertions = collectOrderAssertions(assertions, orderData);
    const assertion = findAssertionById(allAssertions, assertionId);
    const assertionText = extractAssertionText(assertion);
    if (assertionText) return assertionText;

    const validationText = Object.values(validatorsObj || {})
        .map(info => extractAssertionText(info?.payload?.assertion) || info?.assertion_text || info?.payload?.assertion_text)
        .find(Boolean);
    return validationText || `(${t("ui.assertionWithoutText")})`;
}

function getAssertionCategory(assertion) {
    return assertion?.categoryId;
}

function buildVerificationSummary(order, events = []) {
    const weightedResults = order.assertion_results || {};
    const validations = order.validations || {};
    const validationRequestCount = Object.values(order.validation_requests || {}).reduce((sum, items) => {
        return sum + (Array.isArray(items) ? items.length : 0);
    }, 0);

    const expectedValidations = getExpectedValidationCount(order);
    const completedValidations = Object.values(validations).reduce((sum, validators) => {
        return sum + (validators && typeof validators === "object" ? Object.keys(validators).length : 0);
    }, 0);
    const totalValidations = validationRequestCount || expectedValidations || Math.max(completedValidations + Number(order.validators_pending || 0), 0);
    const pendingValidations = Math.max(Number(order.validators_pending || 0), totalValidations - completedValidations, 0);

    const assertionIds = new Set(Object.keys(validations).map(String));
    collectOrderAssertions(order.assertions, order).forEach((assertion, index) => assertionIds.add(getAssertionId(assertion, index + 1)));

    const validatorVotes = { true: 0, false: 0, unknown: 0 };
    let confirmedAssertions = 0;
    let contradictedAssertions = 0;
    let inconclusiveAssertions = 0;

    assertionIds.forEach(assertionId => {
        const weighted = weightedResults[String(assertionId)];
        if (weighted) {
            const scores = weighted.scores || {};
            validatorVotes.true += scores.TRUE || 0;
            validatorVotes.false += scores.FALSE || 0;
            validatorVotes.unknown += scores.UNKNOWN || 0;
            if (weighted.winner === "TRUE") confirmedAssertions++;
            else if (weighted.winner === "FALSE") contradictedAssertions++;
            else inconclusiveAssertions++;
            return;
        }

        const validators = validations[assertionId] || {};
        let trueVotes = 0;
        let falseVotes = 0;
        let unknownVotes = 0;

        Object.values(validators).forEach(v => {
            const lit = getValidationLiteral(v?.approval);
            if (lit === "True") trueVotes++;
            else if (lit === "False") falseVotes++;
            else unknownVotes++;
        });

        validatorVotes.true += trueVotes;
        validatorVotes.false += falseVotes;
        validatorVotes.unknown += unknownVotes;

        if (trueVotes > falseVotes) confirmedAssertions++;
        else if (falseVotes > trueVotes) contradictedAssertions++;
        else inconclusiveAssertions++;
    });

    const totalAssertions = assertionIds.size;
    const hasMixedResult = [confirmedAssertions, contradictedAssertions, inconclusiveAssertions].filter(Boolean).length > 1;
    let statusKey = "inconclusive";

    if (totalValidations > 0 && completedValidations < totalValidations) {
        statusKey = "pending";
    } else if (totalAssertions === 0) {
        statusKey = completedValidations > 0 ? "inconclusive" : "pending";
    } else if (contradictedAssertions > confirmedAssertions && contradictedAssertions >= inconclusiveAssertions) {
        statusKey = "contradicted";
    } else if (inconclusiveAssertions > confirmedAssertions && inconclusiveAssertions >= contradictedAssertions) {
        statusKey = "inconclusive";
    } else if (confirmedAssertions > 0 && contradictedAssertions === 0 && confirmedAssertions >= inconclusiveAssertions) {
        statusKey = inconclusiveAssertions > 0 ? "partial" : "verified";
    } else if (hasMixedResult) {
        statusKey = "partial";
    }

    const statusMap = {
        verified: { statusLabel: t("summary.verified"), statusIcon: "🟢" },
        partial: { statusLabel: t("summary.partial"), statusIcon: "🟡" },
        contradicted: { statusLabel: t("summary.contradicted"), statusIcon: "🔴" },
        inconclusive: { statusLabel: t("summary.inconclusive"), statusIcon: "🟠" },
        pending: { statusLabel: t("summary.pending"), statusIcon: "⚪" }
    };

    const joinWord = window.I18N?.getLanguage() === "en" ? " and " : " y ";
    const assertionBreakdown = `${pluralizeEs(confirmedAssertions, t("summary.confirmedOne"), t("summary.confirmedMany"))}, ${pluralizeEs(contradictedAssertions, t("summary.disprovedOne"), t("summary.disprovedMany"))}${joinWord}${pluralizeEs(inconclusiveAssertions, t("summary.inconclusiveOne"), t("summary.inconclusiveMany"))}`;
    const knownAssertions = confirmedAssertions + contradictedAssertions;
    const confidenceLabel = knownAssertions > 0
        ? t("summary.confirmedAmongVerified", { confirmed: confirmedAssertions, known: knownAssertions })
        : t("summary.noVerifiedAssertions");

    let conclusionText;
    if (statusKey === "pending") {
        conclusionText = t("summary.pendingConclusion", { completed: completedValidations, total: totalValidations || completedValidations });
    } else if (statusKey === "verified") {
        conclusionText = t("summary.verifiedConclusion", { breakdown: assertionBreakdown });
    } else if (statusKey === "contradicted") {
        conclusionText = t("summary.disprovedConclusion", { breakdown: assertionBreakdown });
    } else if (statusKey === "partial") {
        conclusionText = t("summary.partialConclusion", { breakdown: assertionBreakdown });
    } else {
        conclusionText = t("summary.inconclusiveConclusion", { breakdown: assertionBreakdown });
    }

    return {
        statusKey,
        statusLabel: statusMap[statusKey].statusLabel,
        statusIcon: statusMap[statusKey].statusIcon,
        confidenceLabel,
        conclusionText,
        totalAssertions,
        confirmedAssertions,
        contradictedAssertions,
        inconclusiveAssertions,
        totalValidations,
        completedValidations,
        pendingValidations,
        validationDuration: pendingValidations === 0 && completedValidations > 0
            ? getEndToEndValidationDuration(order, events)
            : "",
        validatorVotes
    };
}


function assertionOutcome(orderData, assertionId) {
    const result = getAssertionResult(orderData, assertionId);
    if (result?.winner === "TRUE") return "confirmed";
    if (result?.winner === "FALSE") return "contradicted";
    if (result?.winner === "UNKNOWN") return "inconclusive";

    const validators = orderData?.validations?.[String(assertionId)] || {};
    const votes = Object.values(validators).map(item => getValidationLiteral(item?.approval));
    const approved = votes.filter(vote => vote === "True").length;
    const rejected = votes.filter(vote => vote === "False").length;
    if (approved > rejected) return "confirmed";
    if (rejected > approved) return "contradicted";
    return "inconclusive";
}

function outcomeMeta(outcome) {
    const values = {
        confirmed: { label: t("ui.confirmed"), icon: "✓", className: "confirmed" },
        contradicted: { label: t("ui.disproved"), icon: "×", className: "contradicted" },
        inconclusive: { label: t("summary.inconclusive"), icon: "?", className: "inconclusive" }
    };
    return values[outcome] || values.inconclusive;
}

function percentage(part, total) {
    return total > 0 ? Math.round((Number(part || 0) / total) * 100) : 0;
}

function renderOrderSummary(container, data, events = []) {
    const summary = buildVerificationSummary(data, events);
    const assertions = collectOrderAssertions(data.assertions, data);
    const totalAssertions = summary.totalAssertions || assertions.length;
    const confirmedPercent = percentage(summary.confirmedAssertions, totalAssertions);
    const contradictedPercent = percentage(summary.contradictedAssertions, totalAssertions);
    const inconclusivePercent = Math.max(0, 100 - confirmedPercent - contradictedPercent);
    const totalWeight = summary.validatorVotes.true + summary.validatorVotes.false + summary.validatorVotes.unknown;
    const truePercent = percentage(summary.validatorVotes.true, totalWeight);
    const falsePercent = percentage(summary.validatorVotes.false, totalWeight);
    const unknownPercent = Math.max(0, 100 - truePercent - falsePercent);
    const progressPercent = percentage(summary.completedValidations, summary.totalValidations || summary.completedValidations);
    const problematic = assertions.filter((assertion, index) => assertionOutcome(data, getAssertionId(assertion, index + 1)) !== "confirmed").slice(0, 3);
    const statusIcon = summary.statusKey === "verified" ? "✓" : summary.statusKey === "contradicted" ? "×" : summary.statusKey === "pending" ? "…" : "!";

    const problemRows = problematic.length ? problematic.map((assertion, index) => {
        const assertionId = getAssertionId(assertion, index + 1);
        const meta = outcomeMeta(assertionOutcome(data, assertionId));
        return `<li><span>${safeText(assertionId)}. ${safeText(compactText(extractAssertionText(assertion), 76))}</span><b class="outcome-badge ${meta.className}">${meta.label}</b></li>`;
    }).join("") : `<li class="no-problems">${safeText(t("ui.noProblematicAssertions"))}</li>`;

    const newsText = typeof data.text === "object" ? data.text?.text || JSON.stringify(data.text) : data.text || t("ui.noNewsText");

    container.innerHTML = `
        <div class="order-summary">
            <div class="summary-hero status-${summary.statusKey}">
                <div class="summary-verdict">
                    <span class="verdict-icon">${statusIcon}</span>
                    <div>
                        <h2>${safeText(summary.statusLabel)}</h2>
                        <p>${safeText(summary.conclusionText)}</p>
                    </div>
                </div>
                <dl class="order-meta-card">
                    <div><dt>${t("ui.orderId")}</dt><dd>${shortValue(data.order_id, 30)}</dd></div>
                    <div><dt>${t("ui.date")}</dt><dd>${formatAnyDate(data.created_at || data.created)}</dd></div>
                    <div><dt>${t("ui.validationMode")}</dt><dd><span class="mode-badge">${safeText(data.validation_mode || "BLOCKCHAIN")}</span></dd></div>
                </dl>
            </div>

            <div class="summary-grid-main">
                <article class="dashboard-card assertion-overview">
                    <h3>${t("ui.assertionSummary")} <span>(${t("ui.totalCount", { count: totalAssertions })})</span></h3>
                    <div class="assertion-distribution" aria-label="${safeText(t("ui.assertionSummary"))}">
                        <span class="confirmed" style="width:${confirmedPercent}%">${confirmedPercent ? `${confirmedPercent}%` : ""}</span>
                        <span class="contradicted" style="width:${contradictedPercent}%">${contradictedPercent ? `${contradictedPercent}%` : ""}</span>
                        <span class="inconclusive" style="width:${inconclusivePercent}%">${inconclusivePercent ? `${inconclusivePercent}%` : ""}</span>
                    </div>
                    <div class="assertion-counts">
                        <div><i class="confirmed">✓</i><strong>${summary.confirmedAssertions} ${t("ui.confirmed")}</strong><small>${t("ui.confirmedHelp")}</small></div>
                        <div><i class="contradicted">×</i><strong>${summary.contradictedAssertions} ${t("ui.disproved")}</strong><small>${t("ui.disprovedHelp")}</small></div>
                        <div><i class="inconclusive">?</i><strong>${summary.inconclusiveAssertions} ${t("ui.inconclusive")}</strong><small>${t("ui.inconclusiveHelp")}</small></div>
                    </div>
                </article>

                <article class="dashboard-card vote-overview">
                    <h3>${t("ui.weightedValidatorVote")}</h3>
                    <div class="vote-content">
                        <div class="vote-donut" style="--true:${truePercent * 3.6}deg;--false:${(truePercent + falsePercent) * 3.6}deg"><span>◎</span></div>
                        <div class="vote-legend">
                            <div><i class="confirmed"></i><span>${t("ui.inFavor")}</span><b>${formatMaxTwoDecimals(summary.validatorVotes.true)} (${truePercent}%)</b></div>
                            <div><i class="contradicted"></i><span>${t("ui.against")}</span><b>${formatMaxTwoDecimals(summary.validatorVotes.false)} (${falsePercent}%)</b></div>
                            <div><i class="inconclusive"></i><span>${t("ui.noConclusion")}</span><b>${formatMaxTwoDecimals(summary.validatorVotes.unknown)} (${unknownPercent}%)</b></div>
                            <strong>${t("ui.weightedTotal")}: ${formatMaxTwoDecimals(totalWeight)}</strong>
                        </div>
                    </div>
                </article>
            </div>

            <div class="summary-grid-secondary">
                <article class="dashboard-card metric-card"><span class="metric-icon confirmed">♙</span><div><small>${t("ui.validationSummary")}</small><strong>${summary.completedValidations} / ${summary.totalValidations || summary.completedValidations}</strong><p>${t("ui.validationsCompleted")}</p><b class="metric-tag">${t("ui.percentCompleted", { percent: progressPercent })}</b></div></article>
                <article class="dashboard-card metric-card"><span class="metric-icon time">◷</span><div><small>${t("ui.totalValidationTime")}</small><strong>${safeText(summary.validationDuration || t("ui.inProgress"))}</strong><p>${summary.pendingValidations ? t("ui.pendingCount", { count: summary.pendingValidations }) : t("ui.processCompleted")}</p></div></article>
                <article class="dashboard-card problems-card"><h3>${t("ui.problematicAssertions")}</h3><ol>${problemRows}</ol><button type="button" onclick="activateOrderTab('assertions')">${t("ui.viewAllAssertions")}</button></article>
            </div>

            <article class="dashboard-card news-card">
                <h3>▤ ${t("ui.newsSummary")}</h3>
                <div class="news-summary-text">${safeText(newsText)}</div>
                <button type="button" class="news-summary-toggle" hidden
                    aria-expanded="false" title="${safeText(t("summary.expandNewsSummaryHint"))}">
                    ${safeText(t("summary.showMore"))}
                </button>
            </article>
        </div>`;

    const newsSummary = container.querySelector(".news-summary-text");
    const newsSummaryToggle = container.querySelector(".news-summary-toggle");
    if (newsSummary && newsSummaryToggle) {
        newsSummaryToggle.hidden = newsSummary.scrollHeight <= newsSummary.clientHeight + 1;
        newsSummaryToggle.addEventListener("click", () => {
            const expanded = newsSummary.classList.toggle("expanded");
            newsSummaryToggle.setAttribute("aria-expanded", String(expanded));
            newsSummaryToggle.textContent = t(expanded ? "summary.showLess" : "summary.showMore");
            newsSummaryToggle.title = t(expanded ? "summary.collapseNewsSummaryHint" : "summary.expandNewsSummaryHint");
        });
    }
}

function activateOrderTab(tabKey) {
    const button = document.querySelector(`#orderTabs [data-tab-key="${tabKey}"]`);
    button?.click();
}

function renderOrderAssertions(container, assertions, orderData) {
    if (!assertions?.length) {
        container.innerHTML = `<p class="empty-state">${safeText(t("ui.noAssertions"))}</p>`;
        return;
    }
    const cards = assertions.map((assertion, index) => {
        const assertionId = getAssertionId(assertion, index + 1);
        const categoryId = getAssertionCategory(assertion);
        const category = categoryId != null
            ? `${categoryLabel(categoryId)} (${categoryId})`
            : "-";
        const meta = outcomeMeta(assertionOutcome(orderData, assertionId));
        const validators = orderData?.validations?.[String(assertionId)] || {};
        const evidenceCount = Object.values(validators).reduce((sum, info) => sum + validationEvidenceItems(info).length, 0);
        return `<article class="assertion-card ${meta.className}">
            <span class="assertion-number">${safeText(assertionId)}</span>
            <div class="assertion-copy"><h3>${safeText(extractAssertionText(assertion) || t("ui.assertionWithoutText"))}</h3><div><span>${t("ui.category")} <b>${safeText(category)}</b></span><span>${t("ui.result")} <b class="outcome-badge ${meta.className}">${meta.label}</b></span><span>${t("ui.validators")} <b>${Object.keys(validators).length}</b></span><span>${t("ui.evidence")} <b>${evidenceCount}</b></span></div></div>
            <button type="button" onclick="activateOrderTab('evidence')">${t("ui.viewDetail")}</button>
        </article>`;
    }).join("");
    container.innerHTML = `<div class="assertions-toolbar"><strong>${assertions.length} ${t("ui.assertions").toLowerCase()}</strong><span>${t("ui.weightedValidatorVote")}</span></div><div class="assertion-card-list">${cards}</div>`;
}

function buildOrderProcessRows(orderData, events = []) {
    const labels = {
        CREATED: t("status.CREATED"), ASSERTIONS_REQUESTED: t("status.ASSERTIONS_REQUESTED"),
        DOCUMENT_CREATED: t("status.DOCUMENT_CREATED"), IPFS_PENDING: t("status.IPFS_PENDING"),
        IPFS_UPLOADED: t("status.IPFS_UPLOADED"), BLOCKCHAIN_PENDING: t("status.BLOCKCHAIN_PENDING"),
        VALIDATION_PENDING: t("status.VALIDATION_PENDING"), VALIDATED: t("status.VALIDATED"),
        NO_VALIDATORS_AVAILABLE: t("status.NO_VALIDATORS_AVAILABLE"),
        ASSERTIONS_NOT_AVAILABLE: t("status.ASSERTIONS_NOT_AVAILABLE"), QUOTA_EXCEDED: t("status.QUOTA_EXCEDED")
    };
    const transitions = {
        generate_assertions: ["ASSERTIONS_REQUESTED"], assertions_generated: ["DOCUMENT_CREATED"],
        upload_ipfs: ["IPFS_PENDING"], ipfs_uploaded: ["IPFS_UPLOADED", "BLOCKCHAIN_PENDING"],
        blockchain_registered: ["VALIDATION_PENDING"], light_validation_request: ["VALIDATION_PENDING"],
        assertions_not_generated: ["ASSERTIONS_NOT_AVAILABLE"]
    };
    const sorted = [...(events || [])].sort((x, y) =>
        (parseEventTimestamp(x?.timestamp)?.getTime() || 0) - (parseEventTimestamp(y?.timestamp)?.getTime() || 0)
    );
    const rows = [];
    const add = (status, date, action) => {
        if (!status || rows.at(-1)?.status === status) return;
        rows.push({ status, label: labels[status] || status.replaceAll("_", " "), date, action });
    };
    add("CREATED", orderData?.created_at || orderData?.created, "Creación de la orden");
    sorted.forEach(event => (transitions[event.action] || []).forEach(status => add(status, event.timestamp, event.action)));
    add(orderData?.status, orderData?.updated_at || sorted.at(-1)?.timestamp || orderData?.created_at, "Estado actual");
    return rows;
}
function getProcessStageState(orderData, mode, count) {
    const status = String(orderData?.status || "CREATED").toUpperCase();
    if (status === "VALIDATED") return { currentIndex: count - 1, reached: count, complete: true };
    const light = { CREATED: 1, ASSERTIONS_REQUESTED: 1, DOCUMENT_CREATED: 2, VALIDATION_PENDING: 3, NO_VALIDATORS_AVAILABLE: 4, ASSERTIONS_NOT_AVAILABLE: 1, QUOTA_EXCEDED: 1 };
    const blockchain = { CREATED: 1, ASSERTIONS_REQUESTED: 1, DOCUMENT_CREATED: 2, IPFS_PENDING: 3, IPFS_UPLOADED: 4, BLOCKCHAIN_PENDING: 4, VALIDATION_PENDING: 5, NO_VALIDATORS_AVAILABLE: 6, ASSERTIONS_NOT_AVAILABLE: 1, QUOTA_EXCEDED: 1 };
    const currentIndex = Math.min((mode === "LIGHT" ? light : blockchain)[status] ?? 0, count - 1);
    return { currentIndex, reached: currentIndex + 1, complete: false };
}
function countProcessVotes(orderData) {
    const counts = { confirmed: 0, contradicted: 0, inconclusive: 0 };
    Object.values(orderData?.validations || {}).forEach(validators => Object.values(validators || {}).forEach(validation => {
        const literal = getValidationLiteral(validation?.approval);
        if (literal === "True") counts.confirmed++;
        else if (literal === "False") counts.contradicted++;
        else counts.inconclusive++;
    }));
    return counts;
}
function getProcessElapsedTime(orderData) {
    const start = parseOrderTimestamp(orderData?.created_at || orderData?.created || orderData?.createdAt);
    if (!start) return "-";
    const final = String(orderData?.status || "").toUpperCase() === "VALIDATED";
    const end = final ? parseOrderTimestamp(orderData?.updated_at || orderData?.updatedAt) || new Date() : new Date();
    return formatDurationMinutesSeconds(Math.max(0, end.getTime() - start.getTime()));
}
function getLastValidationAge(events = []) {
    const actions = new Set(["validation_completed", "light_validation_completed"]);
    const dates = events.filter(event => actions.has(event?.action)).map(event => parseEventTimestamp(event.timestamp)).filter(Boolean);
    if (!dates.length) return t("ui.noValidationYet");
    const seconds = Math.max(0, Math.round((Date.now() - Math.max(...dates.map(date => date.getTime()))) / 1000));
    return seconds < 60 ? t("ui.lastValidationSeconds", { count: seconds }) : t("ui.lastValidationMinutes", { count: Math.floor(seconds / 60) });
}
function renderOrderProcess(container, orderData, events = []) {
    const mode = isLightOrder(orderData) ? "LIGHT" : "BLOCKCHAIN";
    const summary = buildVerificationSummary(orderData || {}, events);
    const rows = buildOrderProcessRows(orderData, events);
    const stages = mode === "LIGHT"
        ? [{ label: t("ui.orderCreated"), icon: "✓" }, { label: t("ui.assertions"), icon: "A" }, { label: t("ui.evidenceSearch"), icon: "⌕" }, { label: t("ui.validations"), icon: "V" }, { label: t("ui.consensusResult"), icon: "◎" }]
        : [{ label: t("ui.orderCreated"), icon: "✓" }, { label: t("ui.assertions"), icon: "A" }, { label: t("ui.document"), icon: "D" }, { label: "IPFS", icon: "I" }, { label: t("ui.blockchain"), icon: "B" }, { label: t("ui.validations"), icon: "V" }, { label: t("ui.consensusResult"), icon: "◎" }];
    const stage = getProcessStageState(orderData, mode, stages.length);
    const processPercent = Math.round((stage.reached / stages.length) * 100);
    const votes = countProcessVotes(orderData);
    const received = votes.confirmed + votes.contradicted + votes.inconclusive;
    const total = summary.totalValidations || received;
    const validationPercent = percentage(received, total || received);
    const confirmedPercent = percentage(votes.confirmed, received);
    const contradictedPercent = percentage(votes.contradicted, received);
    const pending = summary.pendingValidations;
    const complete = String(orderData?.status || "").toUpperCase() === "VALIDATED";
    const currentStage = stages[stage.currentIndex]?.label || t("ui.process");
    const provisional = summary.confirmedAssertions > summary.contradictedAssertions ? { label: t("ui.clearTrend"), className: "confirmed" } : summary.contradictedAssertions > summary.confirmedAssertions ? { label: t("ui.disprovedTrend"), className: "contradicted" } : { label: t("ui.noClearTrend"), className: "inconclusive" };
    const recent = rows.slice(-4).reverse();
    const ratio = total ? `${received}/${total}` : String(received);
    const stageHtml = stages.map((item, index) => {
        const state = stage.complete || index < stage.currentIndex ? "completed" : index === stage.currentIndex ? "current" : "pending";
        return `<div class="process-stage ${state}"><span class="process-stage-marker">${safeText(state === "completed" ? "✓" : item.icon)}</span><b>${index + 1}</b><small>${safeText(item.label)}</small></div>`;
    }).join("");
    container.innerHTML = `
        <div class="process-dashboard mode-${mode.toLowerCase()}">
            <section class="process-hero"><div class="process-radar"><span></span></div><div><div class="process-mode-label">${t("ui.mode").toUpperCase()} ${mode}</div><h2>${complete ? t("ui.verificationCompleted") : t("ui.verificationInProgress")}</h2><p>${complete ? t("ui.completedExplanation") : t("ui.progressExplanation")}</p></div><div class="process-live"><strong>${complete ? t("ui.completed") : t("ui.inProgress")}</strong><small>${t("ui.lastUpdate")}: ${formatAnyDate(orderData?.updated_at || events.at(-1)?.timestamp || orderData?.created_at)}</small></div></section>
            <section class="process-stage-card" data-process-widget="flow"><div class="process-section-title"><strong>${t("ui.visualStageFlow", { mode })}</strong><span>${stage.reached}/${stages.length}</span></div><div class="process-stages">${stageHtml}</div><div class="process-progress-header"><strong>${t("ui.processProgress")}</strong><span>${processPercent}%</span></div><div class="process-progress-copy"><span><b>${t("ui.stagesReached", { reached: stage.reached, total: stages.length })}</b></span><span>${t("ui.currentPhase")}: <b>${safeText(currentStage)}</b></span></div><div class="process-progress-track" role="progressbar" aria-label="${safeText(t("ui.processProgress"))}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${processPercent}"><span style="width:${processPercent}%"></span></div></section>
            <div class="process-main-grid">
                <section class="process-card process-now" data-process-widget="current-activity"><h3>${t("ui.currentActivity")}</h3><ul><li><i>◷</i><span>${complete ? t("ui.allValidationsReceived") : pending ? t("ui.waitingValidations", { count: pending }) : t("ui.waitingUpdate")}</span></li><li><i>◎</i><span>${complete ? t("ui.consensusClosed") : t("ui.consensusOpen")}</span></li><li><i>↻</i><span>${safeText(getLastValidationAge(events))}</span></li><li><i>◇</i><span>${complete ? t("ui.definitiveResult") : t("ui.provisionalMayChange")}</span></li></ul></section>
                <section class="process-card process-validations"><h3>${t("ui.receivedValidations")}</h3><div class="process-validation-content"><div class="process-donut" style="--confirmed:${confirmedPercent * 3.6}deg;--contradicted:${(confirmedPercent + contradictedPercent) * 3.6}deg"><span><b>${safeText(ratio)}</b><small>${t("ui.percentCompleted", { percent: validationPercent })}</small></span></div><div class="process-validation-breakdown"><div><i class="confirmed"></i><span>${t("ui.confirmed")}</span><b>${votes.confirmed}</b></div><div><i class="contradicted"></i><span>${t("ui.disproved")}</span><b>${votes.contradicted}</b></div><div><i class="inconclusive"></i><span>${t("ui.inconclusive")}</span><b>${votes.inconclusive}</b></div><strong>${t("ui.pendingCount", { count: pending })}</strong></div></div></section>
                <section class="process-card process-provisional"><div class="process-section-title"><h3>${t("ui.provisionalResult")}</h3><span>${t("ui.provisional")}</span></div><strong class="provisional-result ${provisional.className}">${safeText(provisional.label)}</strong><div class="provisional-counts"><div><b>${summary.confirmedAssertions}</b><small>${t("ui.confirmed")}</small></div><div><b>${summary.contradictedAssertions}</b><small>${t("ui.disproved")}</small></div><div><b>${summary.inconclusiveAssertions}</b><small>${t("ui.inconclusive")}</small></div></div><p>${t("ui.provisionalNotice")}</p></section>
                <section class="process-card process-activity" data-process-widget="recent-activity"><div class="process-section-title"><h3>${t("ui.recentActivity")}</h3><span>${t("ui.changesCount", { count: rows.length })}</span></div><ol>${recent.map(row => `<li><i>•</i><span><b>${safeText(row.label)}</b><small>${formatAnyDate(row.date)}</small></span></li>`).join("") || `<li>${t("ui.noActivity")}</li>`}</ol></section>
            </div>
            <div class="process-kpi-grid"><article><i>V</i><div><small>${t("ui.validationSummary")}</small><strong>${safeText(ratio)}</strong><span>${t("ui.percentCompleted", { percent: validationPercent })}</span></div></article><article><i>◷</i><div><small>${t("ui.elapsedTime")}</small><strong>${safeText(getProcessElapsedTime(orderData))}</strong><span>${t("ui.sinceOrderCreation")}</span></div></article><article><i>◎</i><div><small>${t("ui.currentStatus")}</small><strong>${safeText(currentStage)}</strong><span>${pending ? t("ui.pendingCount", { count: pending }) : complete ? t("ui.consensusComplete") : t("ui.updating")}</span></div></article><article><i>↻</i><div><small>${t("ui.statusChanges")}</small><strong>${rows.length}</strong><span>${t("ui.untilNow")}</span></div></article></div>
            <div class="process-auto-note">ⓘ ${t("ui.autoSummaryNotice")}</div>
        </div>`;
}
function renderTechnicalDetails(container, data) {
    const excluded = new Set(["_id", "document", "assertions", "text", "validators", "validations", "validation_requests", "assertion_results"]);
    const rows = Object.entries(data || {}).filter(([key]) => !excluded.has(key)).map(([key, value]) => {
        let rendered;
        const safeValue = String(value ?? "").replace(/'/g, "\\'");
        if (key === "cid" && value) {
            rendered = `<a href="#" onclick="event.preventDefault(); navigateToIpfs('${safeValue}'); return false;">${safeText(value)}</a>`;
        } else if ((key === "post_id" || key === "postId") && value !== null && value !== undefined && value !== "") {
            rendered = `<a href="#" onclick="event.preventDefault(); navigateToPost('${safeValue}'); return false;">${safeText(value)}</a>`;
        } else if (key === "tx_hash" && value) {
            rendered = `<a href="#" onclick="event.preventDefault(); navigateToTx('${safeValue}'); return false;">${safeText(value)}</a>`;
        } else {
            rendered = typeof value === "object" && value !== null ? `<pre class="event-payload-pre">${safeText(JSON.stringify(value, null, 2))}</pre>` : safeText(value ?? "N/A");
        }
        return `<tr><th>${safeText(key)}</th><td>${rendered}</td></tr>`;
    }).join("");
    container.innerHTML = `<div class="technical-panel"><table class="compact-table"><tbody>${rows}</tbody></table></div>`;
}
function renderDetails(container, data, events = []) {
    container.innerHTML = `<h3 class="text-lg font-bold mb-4">${t("tabs.details")}</h3>`;

    const summary = buildVerificationSummary(data, events);
    const progressPercent = summary.totalValidations > 0 ? Math.round((summary.completedValidations / summary.totalValidations) * 100) : 0;
    const consensusLabel = summary.pendingValidations === 0 && summary.totalValidations > 0 ? t("summary.fullConsensus") : t("summary.partialConsensus");
    const completedValidationsLabel = t("summary.completedValidations", {
        completed: summary.completedValidations,
        total: summary.totalValidations || summary.completedValidations,
        consensus: consensusLabel
    });

    const lightMode = isLightOrder(data);
    const formatDetailValue = value => {
        if (value === null || value === undefined) return "";
        if (typeof value === "object") return `<pre class="event-payload-pre mt-0">${safeText(JSON.stringify(value, null, 2))}</pre>`;
        return safeText(value);
    };
    // --- Contenido de las subpestañas
    const detailsHtml = `<table class="compact-table">` +
        Object.entries(data)
              .filter(([k, v]) => !["_id", "document", "assertions", "text", "status", "validators_pending", "validation_requests", "validators", "validations", "assertion_results"].includes(k))
              .filter(([k]) => !(lightMode && k === "assertions_without_validator"))
              .map(([k, v]) => {
                  if (k === "text" && typeof v === "object" && v?.text) v = v.text;

                  if (lightMode && ["tx_hash", "postId", "post_id", "cid"].includes(k)) {
                      return `<tr><th>${safeText(k)}</th><td><span class="text-muted">not_available</span></td></tr>`;
                  }
                  if (k === "tx_hash" && v) {
                      const safeHash = String(v).replace(/'/g, "\\'");
                      return `<tr><th>${safeText(k)}</th><td><a href="#" onclick="event.preventDefault(); navigateToTx('${safeHash}'); return false;">${shortHex(v)}</a></td></tr>`;
                  }
                  if ((k === "postId" || k === "post_id") && v) {
                      const safeId = String(v).replace(/'/g, "\\'");
                      return `<tr><th>${safeText(k)}</th><td><a href="#" onclick="event.preventDefault(); navigateToPost('${safeId}'); return false;">${safeText(v)}</a></td></tr>`;
                  }
                  if (k === "order_id" && v) {
                      const safeOrder = String(v).replace(/'/g, "\\'");
                      return `<tr><th>Validar vs blockchain</th><td><a href="#" onclick="event.preventDefault(); navigateToConsistency('${safeOrder}'); return false;">${safeText(v)}</a></td></tr>`;
                  }
                  if (k === "cid" && v) {
                      const safeCid = String(v).replace(/'/g, "\\'");
                      return `<tr><th>${safeText(k)}</th><td><a href="#" onclick="event.preventDefault(); navigateToIpfs('${safeCid}'); return false;">${safeText(v)}</a></td></tr>`;
                  }

                  if (typeof v === "object") {
                      v = formatDetailValue(v);
                  } else {
                      v = safeText(v);
                  }

                  return `<tr><th>${safeText(k)}</th><td>` + (v || "") + `</td></tr>`;
              }).join('') +
        `</table>`;

    const summaryHtml = `
        <div class="verification-summary-card status-${summary.statusKey}">
            <div class="verification-summary-main">
                <div>
                    <span class="summary-kicker">${t("summary.verificationResult")}</span>
                    <div class="verification-headline">${summary.statusIcon} ${safeText(summary.statusLabel)}</div>
                    <p class="verification-conclusion">${safeText(summary.conclusionText)}</p>
                </div>
                <span class="summary-confidence">${safeText(summary.confidenceLabel)}</span>
            </div>
            <div class="verification-chip-grid assertion-result-grid" aria-label="Resultado por afirmaciones">
                <span class="summary-kicker">${t("summary.resultByAssertion")}</span>
                <span class="summary-chip chip-confirmed">✅ ${t("summary.confirmed")}: ${summary.confirmedAssertions} ${t("summary.of")} ${summary.totalAssertions}</span>
                <span class="summary-chip chip-contradicted">❌ ${t("summary.disproved")}: ${summary.contradictedAssertions} ${t("summary.of")} ${summary.totalAssertions}</span>
                <span class="summary-chip chip-inconclusive">❔ ${t("summary.notConclusive")}: ${summary.inconclusiveAssertions} ${t("summary.of")} ${summary.totalAssertions}</span>
            </div>
            <div class="verification-ai-row">
                <div class="validation-progress">
                    <span>${safeText(completedValidationsLabel)}</span>
                    <div class="validation-progress-bar">
                        <div class="validation-progress-fill" style="width:${progressPercent}%;"></div>
                    </div>
                </div>
                <div class="validator-votes" aria-label="Votos de validadores">
                    <span class="summary-kicker">${t("summary.validatorVotes")}</span>
                    ${renderSummaryVoteChip(summary.validatorVotes.true, "True", "chip-confirmed")}
                    ${renderSummaryVoteChip(summary.validatorVotes.false, "False", "chip-contradicted")}
                    ${renderSummaryVoteChip(summary.validatorVotes.unknown, "Unknown", "chip-inconclusive")}
                </div>
            </div>
        </div>
        <table class="compact-table summary-metrics-table">
            <tr><th>${t("summary.orderId")}</th><td>${safeText(data.order_id || "N/A")}</td></tr>
            <tr><th>${t("summary.progress")}</th><td>${renderStatusBadge(data.status || "N/A")}${renderProcessingFlow(data.status || "PENDING", summary.pendingValidations, summary.totalValidations)}</td></tr>
            <tr>
                <th>${t("summary.newsSummary")}</th>
                <td>
                    <div class="news-summary-text">${safeText(data.text || "N/A")}</div>
                    <button type="button" class="news-summary-toggle" hidden
                        aria-expanded="false" title="${safeText(t("summary.expandNewsSummaryHint"))}">
                        ${safeText(t("summary.showMore"))}
                    </button>
                </td>
            </tr>
            <tr><th>${t("ui.mode")}</th><td>${safeText(data.validation_mode || "BLOCKCHAIN")}</td></tr>
            <tr><th>${t("summary.validationTotalTime")}</th><td>${safeText(summary.validationDuration || "N/A")}</td></tr>
        </table>`;

    // --- Subpestañas internas
     container.innerHTML = `
        <div class="sub-tabs flex space-x-2 border-b border-gray-600 mb-4">
            <button class="subTab activeSubTab p-2 text-sm font-medium" data-target="summaryTab">${t("tabs.summary")}</button>
            <button class="subTab p-2 text-sm font-medium" data-target="detailsTab">${t("tabs.details")}</button>
        </div>
        <div id="summaryTab" class="bg-gray-800 p-4 rounded-lg">${summaryHtml}</div>
        <div id="detailsTab" style="display:none;" class="bg-gray-800 p-4 rounded-lg">${detailsHtml}</div>
    `;

    // Lógica de subpestañas
    const subTabs = container.querySelectorAll(".subTab");
    subTabs.forEach(btn => {
        btn.addEventListener('click', () => {
            container.querySelectorAll(".subTab").forEach(b => b.classList.remove('activeSubTab', 'text-primary'));
            btn.classList.add('activeSubTab', 'text-primary');
            container.querySelectorAll("#summaryTab, #detailsTab").forEach(div => div.style.display = 'none');
            container.querySelector(`#${btn.getAttribute('data-target')}`).style.display = 'block';
        });
    });
    container.querySelector(".subTab.activeSubTab")?.classList.add('text-primary');

    const newsSummary = container.querySelector(".news-summary-text");
    const newsSummaryToggle = container.querySelector(".news-summary-toggle");
    if (newsSummary && newsSummaryToggle) {
        newsSummaryToggle.hidden = newsSummary.scrollHeight <= newsSummary.clientHeight + 1;
        newsSummaryToggle.addEventListener("click", () => {
            const expanded = newsSummary.classList.toggle("expanded");
            newsSummaryToggle.setAttribute("aria-expanded", String(expanded));
            newsSummaryToggle.textContent = t(expanded ? "summary.showLess" : "summary.showMore");
            newsSummaryToggle.title = t(expanded ? "summary.collapseNewsSummaryHint" : "summary.expandNewsSummaryHint");
        });
    }

    // Add polling indicator if status is PENDING/SUBMITTED
    if (data.status && (data.status.includes('PENDING') || data.status.includes('SUBMITTED'))) {
        const statusEl = container.querySelector('.status-value');
        if (statusEl) {
            statusEl.classList.add('polling', 'blinking');
        }
    }
}



// =========================================================
// RENDER VALIDATIONS TREE OPTIMIZADO
// =========================================================
function renderValidationsTree(container, validations, assertions, orderData = null) {
    if (!validations || Object.keys(validations).length === 0) {
        container.innerHTML = `<p class="text-gray-400">${safeText(t("ui.noOrderValidations"))}</p>`;
        return;
    }

    let html = "";

    for (const [assertionId, validatorsObj] of Object.entries(validations)) {
        const assertionText = resolveAssertionText(assertionId, assertions, orderData, validatorsObj);

        const literals = Object.values(validatorsObj).map(v => getValidationLiteral(v.approval));
        const known = literals.filter(v => v !== "Unknown");
        const approvedCount = known.filter(v => v === "True").length;
        const rejectedCount = known.filter(v => v === "False").length;

        let status;
        if (approvedCount > rejectedCount) status = "True";
        else if (rejectedCount > approvedCount) status = "False";
        else if (known.length > 0) status = "Unknown";
        else status = "Pending";

        let tableRows = "";
        for (const [validator, info] of Object.entries(validatorsObj)) {
            const lit = getValidationLiteral(info.approval);
            let cls = 'unknown'; // Por defecto gris
            if (lit === "True") cls = "true-news";
            else if (lit === "False") cls = "false-news";
            else if (lit === "Unknown") cls = "partial-news";

            let desc = info.text || "";
            if (typeof desc === 'object') desc = JSON.stringify(desc, null, 2);

            tableRows += `<tr>
                <td class="text-primary">${safeText(info.validator_alias || validator)}</td>
                <td class="${cls}"><b>${lit}</b></td>
                <td><pre class="event-payload-pre mt-0">${safeText(desc)}</pre></td>
                <td>${safeText(info.tx_hash || "")}</td>
            </tr>`;
        }

        // Definir clase según el resultado
        let summaryClass = "";
        if (approvedCount > rejectedCount) summaryClass = "summary-green";
        else if (approvedCount < rejectedCount) summaryClass = "summary-red";
        else summaryClass = "summary-yellow";

        html += `<details class="p-3 bg-gray-700 rounded-lg mb-3">
            <summary class="cursor-pointer ${summaryClass}" style="font-weight:bold; font-size:1rem;">
                ${safeText(assertionId)}. ${safeText(assertionText)} → <span style="font-size:0.9rem;">(${safeText(approvedCount)} A / ${safeText(rejectedCount)} R)</span>
            </summary>
            <div class="mt-3">
                <table class="compact-table">
                    <thead>
                        <tr>
                            <th>Validator</th>
                            <th>Resultado</th>
                            <th>Descripción</th>
                            <th>tx_hash</th>
                        </tr>
                    </thead>
                    <tbody>${tableRows}</tbody>
                </table>
            </div>
        </details>`;
    }

    container.innerHTML = html;
}



// =========================================================
// RENDER TABLAS Y EVENTOS
// =========================================================


function renderTableData(container, data) {
    // =====================================================
    // Si no hay datos
    // =====================================================
    if (!data?.length) {
        container.innerHTML = `<p class="text-gray-400 p-4">${safeText(t("ui.noData"))}</p>`;
        return;
    }

    // =====================================================
    // Cálculos de paginación
    // =====================================================
    const totalItems = data.length;
    const totalPages = Math.ceil(totalItems / TABLE_PAGE_SIZE_ORDERS);

    if (TABLE_PAGE_ORDERS < 1) TABLE_PAGE_ORDERS = 1;
    if (TABLE_PAGE_ORDERS > totalPages) TABLE_PAGE_ORDERS = totalPages;

    const start = (TABLE_PAGE_ORDERS - 1) * TABLE_PAGE_SIZE_ORDERS;
    const end = start + TABLE_PAGE_SIZE_ORDERS;
    const pageData = data.slice(start, end);

    // =====================================================
    // Generación de tabla
    // =====================================================

    // MEJORA: En lugar de coger solo las keys del primer elemento,
    // recopilamos todas las keys de todos los elementos para que no falte 'client_id'
    const keysSet = new Set();
    data.forEach(row => Object.keys(row).forEach(k => keysSet.add(k)));

    // Opcional: Si quieres forzar que order_id y client_id salgan siempre primero,
    // puedes ordenarlo aquí. Si no, simplemente lo convertimos a array:
    const keys = Array.from(keysSet);

    let html = `<table class="compact-table">
        <thead>
            <tr>${keys.map(k => `<th class="uppercase text-xs">${safeText(k)}</th>`).join("")}</tr>
        </thead>
        <tbody>`;

    html += pageData.map(row => {
        return `<tr>${keys.map(k => {
            // Si la fila no tiene esta propiedad, mostramos 'N/A'
            let val = row[k] !== undefined ? row[k] : 'N/A';

            // Resumir tipos complejos
            switch(k) {
                case "validators_pending":
                    val = row[k];
                    break;
                case "assertions":
                case "validators":
                    val = Array.isArray(row[k]) ? row[k].length : 0;
                    break;
                case "validations":
                    val = row[k] ? Object.keys(row[k]).length : 0;
                    break;
                case "text":
                    if (typeof val === "object" && val?.text) val = val.text;
                    if (typeof val === "string") val = val.substring(0, 50) + (val.length > 50 ? '...' : '');
                    break;
            }

            // links especiales
            if (k === "order_id" && val !== 'N/A') {
                return `<td>${safeText(val)}</td>`;
            }
            if (k === "tx_hash" && val !== 'N/A') {
                return `<td>${shortHex(val)}</td>`;
            }

            return `<td>${safeText(val)}</td>`;
        }).join("")}</tr>`;
    }).join("");

    html += `</tbody></table>`;

    // =====================================================
    // Controles de paginación
    // =====================================================
    html += `
        <div class="pagination flex items-center justify-center gap-4 mt-4">
            <button
                class="px-3 py-1 bg-gray-700 rounded disabled:opacity-40"
                onclick="changeTablePage(-1)"
                ${TABLE_PAGE_ORDERS === 1 ? "disabled" : ""}
            >${t("ui.previous")}</button>

            <span class="text-sm">${t("ui.pageOf", { page: TABLE_PAGE_ORDERS, total: totalPages })}</span>

            <button
                class="px-3 py-1 bg-gray-700 rounded disabled:opacity-40"
                onclick="changeTablePage(1)"
                ${TABLE_PAGE_ORDERS === totalPages ? "disabled" : ""}
            >${t("ui.next")}</button>
        </div>
    `;

    container.innerHTML = html;

    // Guardar dataset para repintar
    container._fullData = data;
}

function changeTablePage(delta) {
    TABLE_PAGE_ORDERS += delta;

    const container = document.getElementById("listTabContent");
    renderTableData(container, container._fullData);
}


function renderEventsTable(container, events) {
    if (!events?.length) {
        container.innerHTML = `<p class="text-gray-400 p-4">${safeText(t("ui.noEvents"))}</p>`;
        return;
    }

    let currentPage = 1;
    const perPage = MAX_EVENTS_ROWS;
    const totalPages = Math.ceil(events.length / perPage);

    // Map de iconos por acción
    const actionIcons = {
        "assertions_generated": "📝",
        "upload_ipfs": "📤",
        "ipfs_uploaded": "✅",
        "register_blockchain": "⛓️",
        "blockchain_registered": "🔗",
        "request_validation": "🔍",
        "validation_requested": "🔍",
        "light_validation_request": "🔍",
        "validation_completed": "✔️",
        "light_validation_completed": "✔️"
    };

    function renderPage(page) {
        const start = (page - 1) * perPage;
        const end = start + perPage;
        const pageData = events.slice(start, end);

        const rows = pageData.map(e => {
            const payloadStr = JSON.stringify(e.payload, null, 2);
            const safePayloadStr = safeText(payloadStr);
            const visibleSummary = payloadStr.substring(0, 80).trim() + (payloadStr.length > 80 ? '...' : '');
            const safeVisibleSummary = safeText(visibleSummary);
            const icon = actionIcons[e.action] || "❓";

            return `
                <tr>
                    <td class="col-icon text-center">${icon}</td>
                    <td class="col-action">${safeText(e.action)}</td>
                    <td class="col-topic">${safeText(e.topic)}</td>
                    <td class="col-date">${safeText(e.timestamp)}</td>
                    <td class="col-payload">
                        <details class="event-payload-details">
                            <summary><span class="summary-text">${safeVisibleSummary}</span></summary>
                            <pre class="event-payload-pre">${safePayloadStr}</pre>
                        </details>
                    </td>
                </tr>
            `;
        }).join("");

        container.innerHTML = `
            <h3 class="text-lg font-bold mb-3">
                ${t("ui.eventsCount", { count: events.length })} — ${t("ui.pageOf", { page, total: totalPages })}
            </h3>
            <table class="compact-table w-full">
                <thead>
                    <tr>
                        <th class="col-icon">Icono</th>
                        <th class="col-action">Acción</th>
                        <th class="col-topic">Topic</th>
                        <th class="col-date">${t("ui.date")}</th>
                        <th class="col-payload">Payload</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
            <div class="flex justify-between items-center mt-3">
                <button id="prevPage" class="px-3 py-1 bg-gray-700 rounded disabled:opacity-50">⟵ ${t("ui.previous").replace("‹ ", "")}</button>
                <span class="text-sm text-gray-300">${t("ui.pageOf", { page, total: totalPages })}</span>
                <button id="nextPage" class="px-3 py-1 bg-gray-700 rounded disabled:opacity-50">${t("ui.next").replace(" ›", "")} ⟶</button>
            </div>
        `;

        const prevBtn = container.querySelector("#prevPage");
        const nextBtn = container.querySelector("#nextPage");
        prevBtn.disabled = page === 1;
        nextBtn.disabled = page === totalPages;

        prevBtn.onclick = () => renderPage(page - 1);
        nextBtn.onclick = () => renderPage(page + 1);
    }

    renderPage(currentPage);
}





// =========================
// Renderizado de aserciones
// =========================
function renderAssertions(container, assertions) {
    if (!assertions || assertions.length === 0) {
        container.innerHTML = `<p class="text-gray-400 p-4">${safeText(t("ui.noAssertionsAvailable"))}</p>`;
        return;
    }

    let html = `
        <table id="assertionsTable">
            <thead>
                <tr>
                    <th class="id-col">ID</th>
                    <th class="text-col">${t("ui.text")}</th>
                    <th class="cat-col">${t("ui.category")}</th>
                </tr>
            </thead>
            <tbody>
    `;

    assertions.forEach((a, index) => {
        const category = getAssertionCategory(a);
        const catDesc = category ? categoryLabel(category) : "-";
        const textValue = extractAssertionText(a);

        html += `
            <tr>
                <td class="id-col"><span>${safeText(getAssertionId(a, index + 1))}</span></td>
                <td class="text-col">${safeText(textValue || "-")}</td>
                <td class="cat-col">${safeText(catDesc)}</td>
            </tr>
        `;
    });

    html += "</tbody></table>";
    container.innerHTML = html;
}



//=========================================================
// IPFS
//=========================================================
async function findIpfs() {
    const cid = document.getElementById("ipfsHash").value.trim();
    const table = document.getElementById("ipfsTable");

    // Limpiar tabla y contenedor previo
    table.innerHTML = "";
    const oldBox = document.getElementById("ipfsContentBox");
    if (oldBox) oldBox.remove();

    if (!cid) return alertMessage(t("ui.enterIpfsHash"), "error");

    alertMessage(t("ui.searchingIpfs"), "info");

    try {
        const res = await fetchWithAuth(`${IPFS_API}/ipfs/${cid}`);
        if (!res.ok) throw new Error("Error al obtener datos de IPFS");

        const data = await res.json();
        if (!data.content) throw new Error("Campo 'content' no encontrado en la respuesta");

        alertMessage(t("ui.contentRetrieved"), "primary");

        const rawContent = typeof data.content === "string" ? data.content.trim() : data.content;
        const normalizedContent = typeof rawContent === "string" && /^b['"]/.test(rawContent)
            ? rawContent.slice(2, -1)
            : rawContent;

        const parsedContent = (() => {
            try {
                return JSON.parse(normalizedContent);
            } catch {
                return normalizedContent;
            }
        })();

        const box = document.createElement("div");
        box.id = "ipfsContentBox";
        box.className = "post-box dynamic-content";

        if (typeof parsedContent === "string") {
            box.innerHTML = `
                <div class="json-box-header">${t("ui.ipfsContent")}</div>
                <pre class="event-payload-pre json-highlight">${escapeHTML(parsedContent)}</pre>
            `;
        } else {
            box.innerHTML = `
                <div class="json-box-header">${t("ui.ipfsContent")}</div>
                <div class="json-tree">${renderJsonTree(parsedContent)}</div>
            `;
        }

        const activeSection = table.closest("section"); // ✅ sección contenedora
        activeSection.appendChild(box); // ✅ dentro de la sección
        updateAppHistory({ section: "ipfs", inputId: "ipfsHash", value: cid });


    } catch (err) {
        console.error(err);

        const box = document.createElement("div");
        box.id = "ipfsContentBox";
        box.className = "post-box";
        box.innerHTML = `<div class="error">${safeText(t("ui.ipfsContentError"))}</div>`;

        table.insertAdjacentElement("afterend", box);
        alertMessage(t("ui.ipfsSearchError"), "error");
    }
}


//=========================================================
// TX
//=========================================================
async function findTx() {
    const hash = document.getElementById("txHash").value.trim();
    const table = document.getElementById("txTable");
    table.innerHTML = "";

    if (!hash) return alertMessage(t("ui.enterTxHash"), 'error');
    alertMessage(t("ui.searchingTransaction"), 'info');

    try {
        const res = await fetchWithAuth(`${TX_API}/blockchain/tx/${hash}`);
        if (!res.ok) throw new Error("Error al obtener la transacción");

        const responseData = await res.json();
        // 🎯 CORRECCIÓN APLICADA: Usar el campo 'payload'
        if (!responseData.payload) throw new Error("Payload missing in transaction response.");
        alertMessage(responseData.payload);
        renderTxTable(responseData.payload);
        updateAppHistory({ section: "tx", inputId: "txHash", value: hash });
        alertMessage(t("ui.transactionFound"), 'primary');
    } catch (err) {
        console.error(err);
        table.innerHTML = `<tbody><tr><td><div class="p-3 text-red-400">${safeText(t("ui.invalidTransaction"))}</div></td></tr></tbody>`;
        alertMessage(t("ui.transactionSearchError"), 'error');
    }
}

function renderTxTable(apiData) {
    const data = apiData?.payload || apiData || {};
    const txTable = document.getElementById("txTable"); // EXISTENTE en el HTML
    txTable.innerHTML = "";

    const rows = [
        ["from", data.from],
        ["to", data.to],
        [
            "blockNumber",
            data.blockNumber
                ? `<a href="#" onclick="event.preventDefault(); navigateToBlock(${Number(data.blockNumber) || 0})">${safeText(data.blockNumber)}</a>`
                : ""
        ],
        ["gas", data.gas],
        ["gasPrice", data.gasPrice],
        ["nonce", data.nonce],
        ["value", data.value],
        ["status", data.status],
        ["blockHash", shortHex(data.blockHash)],
        ["transactionIndex", data.transactionIndex],
        ["gasUsed", data.gasUsed],
        ["cumulativeGasUsed", data.cumulativeGasUsed]
    ];

    txTable.innerHTML = `
        <tr><th>${t("ui.field")}</th><th>${t("ui.value")}</th></tr>
        ${rows.map(([k, v]) => `<tr><td>${safeText(k)}</td><td>${k === "blockNumber" || k === "blockHash" ? (v ?? "") : safeText(v ?? "")}</td></tr>`).join("")}
    `;
}

// =========================================================
//Funciones de navegacion
// =========================================================


function navigateTo(section, inputId, value, loadFunction) {
    if (!value) return;

    // Cambiar de sección visualmente
    showSection(section, true, false);

    // Poner valor en el input
    const input = document.getElementById(inputId);
    input.value = value;

    // Cargar datos
    loadFunction(value);

    // Guardar estado en historial
    updateAppHistory({ section, inputId, value });
}


function navigateToOrderDetails(orderId) {
    navigateTo("order", "orderId", orderId, (v) => loadOrderById(v, true));
}

function navigateToTx(hash) {
    navigateTo("tx", "txHash", hash, findTx);
}

function navigateToPost(postId) {
    navigateTo("contract", "postId", postId, findPostById);
}

function navigateToBlock(hash) {
    navigateTo("blocks", "blockId", hash, findBlock);
}

function navigateToConsistency(orderId) {
    navigateTo("consistency", "orderIdCons", orderId, checkOrderConsistency);
}

function navigateToIpfs(ipfsHash) {
    navigateTo("ipfs", "ipfsHash", ipfsHash, findIpfs);
}

window.onpopstate = async function(event) {
    if (!event.state) return;

    const { section, inputId, value } = event.state;

    restoringHistoryState = true;
    try {
        // No limpiar, solo mostrar
        showSection(section, false, false);
        if (inputId) {
            const input = document.getElementById(inputId);
            if (input) input.value = value || "";
        }

        switch (section) {
            case "order": if (value) await loadOrderById(value, true); break;
            case "tx": await findTx(); break;
            case "contract": await findPostById(); break;
            case "blocks": await findBlock(); break;
            case "consistency": await checkOrderConsistency(); break;
            case "ipfs": await findIpfs(); break;
        }
    } finally {
        restoringHistoryState = false;
    }
};


// ===============================
// 🔹 BLOQUES
// ===============================
async function findBlock() {
    const blockId = document.getElementById("blockId").value.trim();
    const tableContainer = document.getElementById("blockTable");
    tableContainer.innerHTML = "";

    if (!blockId) return alertMessage(t("ui.enterBlock"), 'error');
    alertMessage(t("ui.searchingBlock"), 'info');

    try {
        const res = await fetchWithAuth(`${TX_API}/blockchain/block/${blockId}`);
        if (!res.ok) throw new Error("Error al obtener el bloque");

        const responseData = await res.json();
        if (!responseData.payload) throw new Error("Payload missing in block response.");

        // 🔹 Renderiza e inserta la tabla
        const blockTable = renderBlockTable(responseData.payload);
        tableContainer.appendChild(blockTable);
        updateAppHistory({ section: "blocks", inputId: "blockId", value: blockId });

        alertMessage(t("ui.blockFound"), 'primary');
    } catch (err) {
        console.error(err);
        tableContainer.innerHTML = `<tbody><tr><td><div class="p-3 text-red-400">${safeText(t("ui.invalidBlock"))}</div></td></tr></tbody>`;
        alertMessage(t("ui.blockSearchError"), 'error');
    }
}

function renderBlockTable(data) {
  const container = document.createElement("div");

  // ======= 🧱 Tabla principal del bloque =======
  const blockTable = document.createElement("table");
  blockTable.className = "compact-table";

  const timestamp = Number(data.timestamp);
  const formattedTime = !isNaN(timestamp)
    ? new Date(timestamp * 1000).toLocaleString(window.I18N?.getLanguage?.() === "en" ? "en-US" : "es-ES", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
      })
    : "";

  const blockRows = [
    ["blockNumber", data.blockNumber],
    ["blockHash", shortHex(data.blockHash)],
    ["timestamp", formattedTime],
    ["miner", data.miner],
    ["transactionCount", data.transactionCount]
  ];

  blockTable.innerHTML = `
    <tr><th>${t("ui.field")}</th><th>${t("ui.value")}</th></tr>
    ${blockRows.map(([k, v]) => `
      <tr>
        <th>${safeText(k)}</th>
        <td>${safeText(v ?? "")}</td>
      </tr>
    `).join("")}
  `;
  container.appendChild(blockTable);

  // ======= 📦 Tabla de transacciones =======
  if (Array.isArray(data.transactions) && data.transactions.length > 0) {
    const txTitle = document.createElement("h3");
    txTitle.textContent = t("ui.blockTransactions");
    txTitle.style.marginTop = "20px";
    txTitle.style.color = "#0D9488";
    container.appendChild(txTitle);

    const txTable = document.createElement("table");
    txTable.className = "compact-table";

    txTable.innerHTML = `
      <tr>
        <th>tx_hash</th>
        <th>from</th>
        <th>to</th>
        <th>value</th>
        <th>gas</th>
      </tr>
      ${data.transactions.map(tx => `
        <tr>
          <td>
            <a href="#" onclick="event.preventDefault(); navigateToTx('${String(tx.tx_hash || "").replace(/'/g, "\\'")}')">
              ${shortHex(tx.tx_hash)}
            </a>
          </td>
          <td>${safeText(tx.from)}</td>
          <td>${safeText(tx.to)}</td>
          <td>${safeText(tx.value)}</td>
          <td>${safeText(tx.gas)}</td>
        </tr>
      `).join("")}
    `;
    container.appendChild(txTable);
  }

  // Reemplaza contenido actual del contenedor
  const blockTableContainer = document.getElementById("blockTable");
  if (blockTableContainer) {
    blockTableContainer.innerHTML = "";
    blockTableContainer.appendChild(container);
  }

  return container;
}


// =======================================================
// BUSCAR POST POR ID
// =======================================================
async function findPostById() {
    const postId = document.getElementById("postId").value.trim();
    const tableContainer = document.getElementById("postTable");
    tableContainer.innerHTML = "";

    if (!postId) {
        return alertMessage(t("ui.enterContract"), "error");
    }

    alertMessage(t("ui.searchingContract"), "info");

    try {
        const res = await fetchWithAuth(`${TX_API}/blockchain/post/${postId}`);

        if (!res.ok) throw new Error("Error al obtener Post");

        const responseData = await res.json();

        if (!responseData.post)
            throw new Error("Payload missing in contract response");

        // Renderiza tabla igual que bloque
        const contractPost = renderPost(responseData.post);
        tableContainer.appendChild(contractPost);
        updateAppHistory({ section: "contract", inputId: "postId", value: postId });

        alertMessage(t("ui.contractFound"), "primary");

    } catch (err) {
        console.error(err);
        tableContainer.innerHTML =
            `<tbody><tr><td><div class="p-3 text-red-400">${safeText(t("ui.invalidContract"))}</div></td></tr></tbody>`;
        alertMessage(t("ui.contractSearchError"), "error");
    }
}


function renderPost(post) {
    const container = document.createElement("div");

    // ===== Tabla principal del Post =====
    const postTable = document.createElement("table");
    postTable.className = "compact-table";

    const rows = [
        ["postId", post.postId],
        ["publisher", post.publisher],
        ["document", post.document || post.cid],
        ["hash_new", post.hash_new]
    ].filter(([, value]) => value !== undefined && value !== null);

    postTable.innerHTML = `
        <tr><th>${t("ui.field")}</th><th>${t("ui.value")}</th></tr>
        ${rows.map(([k, v]) => {
            if (k === "document" && v) {
                v = `<a href="#" onclick="event.preventDefault(); navigateToIpfs('${String(v).replace(/'/g, "\\'")}'); return false;">${safeText(v)}</a>`;
            }

            return `
                <tr>
                    <th>${safeText(k)}</th>
                    <td>${k === "document" ? (v ?? "") : safeText(v ?? "")}</td>
                </tr>
            `;
        }).join("")}
    `;

    container.appendChild(postTable);

    // ===== Árbol de Aserciones =====
    if (Array.isArray(post.asertions) && post.asertions.length > 0) {
        const assertionsTitle = document.createElement("h3");
        assertionsTitle.textContent = `${t("ui.assertions")} (${post.asertions.length})`;
        container.appendChild(assertionsTitle);

        post.asertions.forEach((a, i) => {
            const assertionBox = document.createElement("div");
            assertionBox.className = "assertion-box";

            // ===== Header colapsable con flecha a la izquierda =====
            const header = document.createElement("div");
            header.className = "assertion-header";

            const arrow = document.createElement("span");
            arrow.className = "arrow"; // flecha
            header.appendChild(arrow);

            const headerText = document.createElement("span");
            headerText.textContent = `${t("ui.assertion")} ${i + 1} Digest: ${a.hash_asertion?.digest ?? ""}`;
            header.appendChild(headerText);

            // Contenido colapsable
            const content = document.createElement("div");
            content.className = "assertion-content";

            // Tabla categoría
            const assertionTable = document.createElement("table");
            assertionTable.className = "compact-table";
            assertionTable.innerHTML = `
                <tr><th>${t("ui.category")}</th><td>${safeText(a.categoryId)}</td></tr>
            `;
            content.appendChild(assertionTable);

            // Validaciones
            if (Array.isArray(a.validations) && a.validations.length > 0) {
                const validationsTitle = document.createElement("h4");
                validationsTitle.textContent = `${t("ui.validations")} (${a.validations.length})`;
                content.appendChild(validationsTitle);

                a.validations.forEach((v) => {
                    const validationTable = document.createElement("table");
                    validationTable.className = "compact-table";
                    validationTable.innerHTML = `
                        <tr><th>Validator</th><td>${safeText(v.validatorAddress)}</td></tr>
                        <tr><th>${t("ui.domain")}</th><td>${safeText(v.domain)}</td></tr>
                        <tr><th>${t("ui.reputation")}</th><td>${safeText(v.reputation)}</td></tr>
                        <tr><th>${t("ui.verdict")}</th><td>${mapVeredict(v.veredict)}</td></tr>
                        <tr><th>cid</th>
                            <td>
                                ${v.cid
                                    ? `<a href="#" onclick="event.preventDefault(); navigateToIpfs('${String(v.cid || "").replace(/'/g, "\\'")}'); return false;">
                                            ${safeText(v.cid)}
                                    </a>`
                                    : ""
                                }
                            </td>
                        </tr>
                    `;

                    content.appendChild(validationTable);
                });
            }

            // Toggle colapsado al hacer click
            header.addEventListener("click", () => {
                const isOpen = content.style.display === "block";
                content.style.display = isOpen ? "none" : "block";
                header.classList.toggle("open", !isOpen);
            });

            assertionBox.appendChild(header);
            assertionBox.appendChild(content);
            container.appendChild(assertionBox);
        });
    }

    return container;
}


// =========================================================
// CONSISTENCY CHECK
// =========================================================

/**
     * Llama al endpoint local para verificar la consistencia de la orden
     * con IPFS y Ethereum.
     */
async function checkOrderConsistency() {
    const orderIdInput = document.getElementById('orderIdCons');
    const orderId = orderIdInput.value.trim();
    const table = document.getElementById('postConsistency');

    const apiUrl = `${API}/orders/checkOrderConsistency/${orderId}`;

    if (!orderId) {
        table.innerHTML = '<tr><td colspan="5" class="error">Por favor, introduce un Order ID válido.</td></tr>';
        return;
    }

    // Mostrar indicador de carga con estilo
    table.innerHTML = `
        <tr>
            <td colspan="5" class="loading">
                Comprobando consistencia para Order ID: ${safeText(orderId)}...
            </td>
        </tr>
    `;

    try {
        const response = await fetchWithAuth(apiUrl);

        if (!response.ok) {
            throw new Error(`Error HTTP: ${response.status} ${response.statusText}`);
        }

        const data = await response.json();

        // Renderiza la tabla con los datos obtenidos
        renderConsistencyTable(data);
        updateAppHistory({ section: "consistency", inputId: "orderIdCons", value: orderId });

    } catch (error) {
        console.error('Error al verificar la consistencia:', error);

        table.innerHTML = `
            <tr>
                <td colspan="5" class="error">
                    ${safeText(t("ui.localServiceError"))}<br>
                    Detalle: ${safeText(error.message)}
                </td>
            </tr>`;
    }
}

window.onload = () => {
    showSection('news');

    document
        .getElementById('btn-checkConsistency')
        .addEventListener('click', checkOrderConsistency);
};


// =======================
//   RENDER TABLA
// =======================
function renderConsistencyTable(results) {
    const table = document.getElementById('postConsistency');
    table.innerHTML = '';

    if (!results || results.length === 0) {
        table.innerHTML = '<tr><td class="error">No se encontraron resultados.</td></tr>';
        return;
    }

    let html = `
        <thead>
            <tr>
                <th>Prueba</th>
                <th>Argumento Base</th>
                <th>Argumento a Comparar</th>
                <th>Resultado</th>
            </tr>
        </thead>
        <tbody>
    `;

    results.forEach(item => {
        const resultClass =
            item.result === 'OK'
                ? 'result-ok'
                : 'result-ko';

        html += `
            <tr>
                <td>${safeText(item.test || '')}</td>
                <td><pre>${safeText(String(item.toCompare || ''))}</pre></td>
                <td><pre>${safeText(String(item.compared || ''))}</pre></td>
                <td>
                    <span class="${resultClass}">
                        ${safeText(item.result || '')}
                    </span>
                </td>
            </tr>
        `;
    });

    html += '</tbody>';
    table.innerHTML = html;
}

// =========================================================
// IMPORTAR NOTICIA
// =========================================================

async function importarNoticia() {
    const url = document.getElementById('newsUrl').value.trim();
    const newsText = document.getElementById('newsText');
    const importBtn = document.getElementById('btn-importarNew');

    if (!url) {
        alertMessage(t("messages.importUrl"), "error");
        return;
    }

    try {
        if (importBtn) importBtn.disabled = true;

        const response = await fetchWithAuth(`${API}/extract_text_from_url`, {
            method: 'POST',
            headers: {
                'Accept': 'application/json'
            },
            body: JSON.stringify({ url })
        });

        let data = null;
        try {
            data = await response.json();
        } catch (_) {
            data = null;
        }

        if (!response.ok) {
            const detail = data?.detail || `HTTP ${response.status}`;
            throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
        }

        const text = String(data?.text || "").trim();
        if (!text) throw new Error("La importación no devolvió texto utilizable.");

        newsText.value = text;
        alertMessage("Noticia importada correctamente", "success");

    } catch (err) {
        console.error("Error importando noticia:", err);
        alertMessage(`Error al importar: ${err.message || t("messages.importError")}`, "error", 6000);
    } finally {
        if (importBtn) importBtn.disabled = false;
    }
}

let IS_ADMIN = false;

async function checkAdminStatus() {
    try {
        const response = await fetch(`${API}/auth/is-admin`, {
            headers: { 'Authorization': `Bearer ${keycloak.token}` }
        });
        if (response.ok) {
            const data = await response.json();
            IS_ADMIN = data.is_admin;

            // Si es admin, mostramos el checkbox en la vista de órdenes
            if (IS_ADMIN) {
                document.getElementById('admin-view-container').style.display = 'flex';
            }
        }
    } catch (error) {
        console.error("Error comprobando el rol de administrador:", error);
    }
}

// =========================================================
// INICIALIZACIÓN CON PROTECCIÓN
// =========================================================
document.addEventListener('DOMContentLoaded', () => {

    keycloak.init({
        onLoad: 'login-required', // Obliga a loguearse al cargar la web
        checkLoginIframe: false   // Recomendado para evitar problemas de cookies en localhost
    }).then(authenticated => {
        if (authenticated) {
            console.log("Autenticado con éxito.");
            checkAdminStatus();
            // Una vez autenticado, cargamos los listeners y la vista
            document.body.classList.add('authenticated');
            initializeApp();
        }
    }).catch(err => {
        console.error("Error al inicializar Keycloak:", err);
        alertMessage(t("messages.identityError"), "error");
    });

});

// Extraemos la lógica original a una función aparte
function initializeApp() {
    // 1. Mostrar quién está logueado (Opcional pero recomendado)
    console.log("User:", keycloak.tokenParsed.preferred_username);

    // 2. Navigation Listeners (Tu código original)
    document.querySelectorAll('.menu-title').forEach(title => {
        title.addEventListener('click', () => {
            const submenu = title.nextElementSibling;
            if (submenu) {
                submenu.style.display = submenu.style.display === 'block' ? 'none' : 'block';
            }
        });
    });

    // 3. News Listeners
    document.getElementById('btn-importarNew').addEventListener('click', importarNoticia);
    document.getElementById('btn-publishNew').addEventListener('click', publishNew);
    document.getElementById('validationMode')?.addEventListener('change', updateValidationModeHelp);
    updateValidationModeHelp();

    document.getElementById("btn-generateAssertions").addEventListener("click", async () => {
        const text = document.getElementById("newsText").value.trim();
        const container = document.getElementById("news-assertions-container");
        if (!text) {
            alertMessage(t("messages.writeNews"), "warning");
            return;
        }
        if (container) {
            renderAssertionsProgress(container, t("messages.generatingAssertions"), 20);
        }
        alertMessage(t("messages.generatingAssertions"), "info");
        const assertions = await generateAssertionsFromText(text);
        if (container) {
            if (!assertions || assertions.length === 0) {
                renderAssertionsProgress(container, t("messages.assertionsGenerated"), 100);
                container.innerHTML += `<div class="mt-4">${t("messages.noAssertionsFound") || "No se generaron aserciones."}</div>`;
            } else {
                renderAssertionsProgress(container, t("messages.assertionsGenerated"), 100);
            }
        }
        renderEditableAssertionsTable(container, assertions);
        alertMessage(t("messages.assertionsGenerated"), "success");
    });

    // 4. El resto de tus Listeners (Orders, TX, IPFS...)
    document.getElementById('btn-findOrder').addEventListener('click', findOrder);
    document.getElementById('btn-listOrders').addEventListener('click', listOrders);
    document.getElementById("btn-findTx").addEventListener("click", findTx);
    document.getElementById("btn-findBlock").addEventListener("click", findBlock);
    document.getElementById("btn-findPost").addEventListener("click", findPostById);
    document.getElementById("btn-checkConsistency").addEventListener("click", checkOrderConsistency);
    document.getElementById("btn-findIpfs").addEventListener("click", findIpfs);

    if (!document.body.dataset.backspaceBound) {
        document.body.dataset.backspaceBound = "true";
        document.addEventListener("keydown", event => {
            if (event.key === "Backspace" && !isEditableTarget(event.target)) {
                event.preventDefault();
                if (history.length > 1) history.back();
            }
        });
    }

    // 5. Initial view
    updateAppHistory({ section: "news" }, true);
    showSection('news', true, false);
}

// =========================================================
// UX V1 INTEGRATED OVERRIDES
// Mantiene la funcionalidad original y mejora presentación visual.
// =========================================================
function safeText(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return escapeHTML(JSON.stringify(value));
    return escapeHTML(String(value));
}

function validatorTypeLabel(value) {
    if (value === null || value === undefined || value === "") return "-";
    const enumToId = {
        LLM_MEMORY_VALIDATION: 1,
        LLM_SEARCH_VALIDATION: 2,
        RAG_EVIDENCE_VALIDATION: 3,
        DETERMINISTIC_VALIDATION: 4,
        HUMAN: 5
    };
    const typeId = enumToId[value] || Number(value);
    return Number.isFinite(typeId) && typeId >= 1 && typeId <= 5 ? t(`ui.validatorTypes.${typeId}`) : String(value);
}

function syntaxHighlightJson(json) {
    let str = typeof json === "string" ? json : JSON.stringify(json, null, 2);
    try {
        if (typeof json !== "string") {
            str = JSON.stringify(json, null, 2);
        } else {
            const parsed = JSON.parse(json);
            str = JSON.stringify(parsed, null, 2);
        }
    } catch {
        str = String(json);
    }

    str = escapeHTML(str);
    return str.replace(/("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, match => {
        let cls = "json-number";
        if (/^\".*\"\s*:$/.test(match)) {
            cls = "json-key";
        } else if (/^\"/.test(match)) {
            cls = "json-string";
        } else if (/true|false/.test(match)) {
            cls = "json-boolean";
        } else if (/null/.test(match)) {
            cls = "json-null";
        }
        return `<span class="${cls}">${match}</span>`;
    });
}

function renderJsonTree(value, key = null) {
    if (value === null || value === undefined) {
        const label = key ? `<span class="json-node-key">${escapeHTML(key)}:</span> ` : "";
        return `<div class="json-node"><span class="json-node-key">${label}</span><span class="json-null">null</span></div>`;
    }

    if (Array.isArray(value)) {
        const items = value.map(item => renderJsonTree(item)).join("");
        return `
            <details class="json-details" open>
                <summary><span class="json-node-key">${key ? escapeHTML(key) : "Array"}</span> <span class="json-value">[Array, ${value.length}]</span></summary>
                <div class="json-children">${items}</div>
            </details>
        `;
    }

    if (typeof value === "object") {
        const entries = Object.entries(value).map(([k, v]) => renderJsonTree(v, k)).join("");
        return `
            <details class="json-details" open>
                <summary><span class="json-node-key">${key ? escapeHTML(key) : "Object"}</span> <span class="json-value">{Object}</span></summary>
                <div class="json-children">${entries}</div>
            </details>
        `;
    }

    let content = escapeHTML(String(value));
    let cls = "json-string";
    if (typeof value === "number") cls = "json-number";
    else if (typeof value === "boolean") cls = "json-boolean";
    else if (value === null) cls = "json-null";
    const label = key ? `<span class="json-node-key">${escapeHTML(key)}:</span> ` : "";
    return `<div class="json-node">${label}<span class="${cls}">${content}</span></div>`;
}

function statusClass(status) {
    const normalized = String(status || "unknown").toLowerCase().replace(/[^a-z0-9]+/g, "_");
    if (normalized.includes("validated")) return "status-validated";
    if (normalized.includes("error") || normalized.includes("fail")) return "status-error";
    if (normalized.includes("pending")) return `status-${normalized}`;
    if (normalized.includes("requested") || normalized.includes("uploaded") || normalized.includes("created") || normalized.includes("registered")) return `status-${normalized}`;
    return "status-unknown";
}

function renderStatusBadge(status) {
    const rawStatus = String(status || "UNKNOWN");
    const label = safeText(t(`status.${rawStatus}`) === `status.${rawStatus}` ? rawStatus : t(`status.${rawStatus}`));
    return `<span class="status-badge ${statusClass(rawStatus)}">${label}</span>`;
}

function formatAnyDate(value) {
    if (!value) return "N/A";
    const raw = String(value);
    const date = new Date(raw);
    if (!Number.isNaN(date.getTime())) {
        return date.toLocaleString("es-ES", {
            day: "2-digit", month: "2-digit", year: "numeric",
            hour: "2-digit", minute: "2-digit"
        });
    }
    return safeText(raw);
}

function shortValue(value, size = 18) {
    if (!value) return "N/A";
    const text = String(value);
    if (text.length <= size) return safeText(text);
    return `<span title="${safeText(text)}">${safeText(text.slice(0, Math.ceil(size/2)))}…${safeText(text.slice(-Math.floor(size/2)))}</span>`;
}

function renderVotePill(count, label, className) {
    const zeroClass = Number(count) === 0 ? " vote-pill-zero" : "";
    return `<span class="vote-pill ${className}${zeroClass}">${safeText(count)} ${safeText(label)}</span>`;
}

function renderSummaryVoteChip(value, label, className) {
    const zeroClass = Number(value || 0) === 0 ? " summary-chip-zero" : "";
    return `<span class="summary-chip ${className}${zeroClass}">${formatMaxTwoDecimals(value)} ${safeText(label)}</span>`;
}

function compactText(value, size = 90) {
    if (!value) return "";
    const text = String(value).replace(/\s+/g, " ").trim();
    return text.length > size ? `${text.slice(0, size)}…` : text;
}

// Tabla de órdenes/listados con columnas más visuales, badges de estado y hashes compactos.
function renderTableData(container, data) {
    if (!data?.length) {
        container.innerHTML = `<p class="empty-state">${safeText(t("ui.noData"))}</p>`;
        container._fullData = data || [];
        return;
    }

    const isOrdersContainer = container.id === "listTabContent";
    const totalItems = data.length;
    const totalPages = Math.max(1, Math.ceil(totalItems / TABLE_PAGE_SIZE_ORDERS));
    if (TABLE_PAGE_ORDERS < 1) TABLE_PAGE_ORDERS = 1;
    if (TABLE_PAGE_ORDERS > totalPages) TABLE_PAGE_ORDERS = totalPages;

    const start = (TABLE_PAGE_ORDERS - 1) * TABLE_PAGE_SIZE_ORDERS;
    const pageData = data.slice(start, start + TABLE_PAGE_SIZE_ORDERS);

    let keys;
    if (isOrdersContainer) {
        const preferred = ["order_id", "client_id", "validation_mode", "status", "hash_text", "tx_hash", "created_at", "updated_at", "validators_pending"];
        const existing = new Set();
        data.forEach(row => Object.keys(row).forEach(k => existing.add(k)));
        keys = preferred.filter(k => existing.has(k));
        [...existing].forEach(k => { if (!keys.includes(k) && !["_id", "document", "assertions", "validations", "validators", "assertion_results", "text"].includes(k)) keys.push(k); });
    } else {
        const keysSet = new Set();
        data.forEach(row => Object.keys(row).forEach(k => keysSet.add(k)));
        keys = Array.from(keysSet);
    }

    const headerLabels = {
        order_id: "Order ID",
        client_id: "Client ID",
        validation_mode: t("ui.mode"),
        status: t("ui.status"),
        hash_text: t("ui.textHash"),
        tx_hash: "Tx hash",
        created_at: t("ui.created"),
        updated_at: t("ui.updated"),
        validators_pending: t("ui.pending")
    };

    const rows = pageData.map(row => {
        return `<tr>${keys.map(k => {
            let val = row[k] !== undefined ? row[k] : "N/A";

            if (k === "order_id" && val !== "N/A") {
                return `<td><a class="order-id-link" href="#" onclick="event.preventDefault(); navigateToOrderDetails('${String(val).replace(/'/g, "\\'")}')">#${shortValue(val, 20)} ↗</a></td>`;
            }

            if (k === "status") {
                return `<td>${renderStatusBadge(val)}</td>`;
            }

            if (k === "hash_text" || k === "tx_hash" || String(k).toLowerCase().includes("hash")) {
                const safe = String(val || "").replace(/'/g, "\\'");
                if (k === "tx_hash" && val && val !== "N/A") {
                    return `<td><a class="hash-chip" href="#" onclick="event.preventDefault(); navigateToTx('${safe}')">${shortValue(val, 20)}</a></td>`;
                }
                return `<td><span class="hash-chip">${shortValue(val, 22)}</span></td>`;
            }

            if (k === "created_at" || k === "updated_at" || k === "timestamp" || k === "createdAt") {
                return `<td>${formatAnyDate(val)}</td>`;
            }

            if (k === "validators_pending") {
                return `<td><span class="vote-pill vote-unknown">${safeText(val)}</span></td>`;
            }

            switch(k) {
                case "assertions":
                case "validators":
                    val = Array.isArray(row[k]) ? row[k].length : 0;
                    return `<td><span class="vote-pill vote-unknown">${val}</span></td>`;
                case "validations":
                    val = row[k] ? Object.keys(row[k]).length : 0;
                    return `<td><span class="vote-pill vote-true">${val}</span></td>`;
                case "text":
                    if (typeof val === "object" && val?.text) val = val.text;
                    if (typeof val === "string") val = val.substring(0, 80) + (val.length > 80 ? "…" : "");
                    return `<td>${safeText(val)}</td>`;
                default:
                    return `<td>${safeText(val)}</td>`;
            }
        }).join("")}</tr>`;
    }).join("");

    container.innerHTML = `
        <table class="compact-table visual-orders-table">
            <thead><tr>${keys.map(k => `<th>${headerLabels[k] || safeText(k)}</th>`).join("")}</tr></thead>
            <tbody>${rows}</tbody>
        </table>
        <div class="pagination">
            <button onclick="changeTablePage(-1)" ${TABLE_PAGE_ORDERS === 1 ? "disabled" : ""}>${t("ui.previous")}</button>
            <span class="vote-pill vote-true">${t("ui.pageOf", { page: TABLE_PAGE_ORDERS, total: totalPages })}</span>
            <button onclick="changeTablePage(1)" ${TABLE_PAGE_ORDERS === totalPages ? "disabled" : ""}>${t("ui.next")}</button>
        </div>
        <p style="color:var(--text-secondary);font-size:.82rem;margin:10px 0 0;">${t("ui.showingOrders", { shown: pageData.length, total: totalItems })}</p>
    `;
    container._fullData = data;
}

// Árbol de validaciones más visual, con cards por validador y votos coloreados.

function getAssertionResult(orderData, assertionId) {
    return orderData?.assertion_results?.[String(assertionId)] || null;
}

function scorePercent(value) {
    const n = Number(value || 0);
    return `${formatMaxTwoDecimals(n * 100)}%`;
}

function renderScorePill(value, label, className) {
    const roundedPercent = Number(formatMaxTwoDecimals(Number(value || 0) * 100));
    const zeroClass = roundedPercent === 0 ? " vote-pill-zero" : "";
    return `<span class="vote-pill ${className}${zeroClass}">${safeText(label)} ${scorePercent(value)}</span>`;
}

function renderScorePills(result) {
    const scores = result?.scores || {TRUE: 0, FALSE: 0, UNKNOWN: 0};
    return `
        <div class="vote-pills score-pills">
            ${renderScorePill(scores.TRUE, "TRUE", "vote-true")}
            ${renderScorePill(scores.FALSE, "FALSE", "vote-false")}
            ${renderScorePill(scores.UNKNOWN, "UNKNOWN", "vote-unknown")}
        </div>
    `;
}

function preferredDomainsStatusFromPolicy(usePreferredDomains) {
    if (usePreferredDomains === true) {
        return { enabled: true, label: t("ui.yes"), title: "EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=true", className: "preferred-domains-on" };
    }
    if (usePreferredDomains === false) {
        return { enabled: false, label: "No", title: "EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS=false", className: "preferred-domains-off" };
    }
    return null;
}

function normalizeBooleanFlag(value) {
    if (typeof value === "boolean") return value;
    if (typeof value === "string") {
        const normalized = value.trim().toLowerCase();
        if (["true", "1", "yes", "si", "sí"].includes(normalized)) return true;
        if (["false", "0", "no"].includes(normalized)) return false;
    }
    return null;
}

function preferredDomainsStatusFromEvidenceResponse(response) {
    if (!response || typeof response !== "object") return null;

    const explicitPolicy = normalizeBooleanFlag(response.search_policy?.use_preferred_domains);
    const fromPolicy = preferredDomainsStatusFromPolicy(explicitPolicy);
    if (fromPolicy) return fromPolicy;

    const resolution = response.domain_resolution || {};
    const preferredDomains = Array.isArray(resolution.preferred_domains) ? resolution.preferred_domains : [];
    const queries = Array.isArray(response.queries_executed) ? response.queries_executed : [];
    const hasSiteQueries = queries.some(query => String(query || "").trim().startsWith("site:"));

    if (preferredDomains.length || hasSiteQueries) {
        return {
            enabled: true,
            label: preferredDomains.length ? `${t("ui.yes")} (${preferredDomains.length})` : t("ui.yes"),
            title: preferredDomains.map(item => item.domain).filter(Boolean).join(", "),
            className: "preferred-domains-on"
        };
    }

    return null;
}

function preferredDomainsInfoForValidation(info = {}) {
    const config = info.validator_config?.config || info.config || info.validator_config || {};
    const explicitPolicy = normalizeBooleanFlag(
        info.search_policy?.use_preferred_domains
        ?? info.payload?.search_policy?.use_preferred_domains
        ?? config.evidence_search_use_preferred_domains
    );
    return preferredDomainsStatusFromPolicy(explicitPolicy)
        || preferredDomainsStatusFromEvidenceResponse(info.evidence_search_response || info.payload?.evidence_search_response)
        || { enabled: null, label: t("ui.noRecord"), title: "Sin política explícita en esta validación", className: "preferred-domains-unknown" };
}

function renderPreferredDomainsBadge(info) {
    if (!info) return "";
    const title = info.title ? ` title="${safeText(info.title)}"` : "";
    return `<span class="preferred-domains-badge ${info.className}"${title}>preferred domains: ${safeText(info.label)}</span>`;
}

function validationEvidenceItems(info = {}) {
    const candidates = [
        info.sources,
        info.evidence_used,
        info.evidence_search_response?.evidences,
        info.payload?.sources,
        info.payload?.evidence_used,
        info.payload?.evidence_search_response?.evidences
    ];
    return candidates.find(items => Array.isArray(items) && items.length) || [];
}

function renderEvidenceLinks(info = {}) {
    const items = validationEvidenceItems(info);
    if (!items.length) return "";

    const rows = items.slice(0, 6).map((src, index) => {
        const url = src.url || src.source_url || "";
        const title = src.title || src.source_id || src.domain || src.source_domain || url || `Evidencia ${index + 1}`;
        const reason = src.why_selected || src.reason || src.snippet || src.excerpt || src.content || src.description || "";
        const meta = [
            src.source_type,
            src.reliability,
            src.supports,
            src.trust_score !== undefined && src.trust_score !== "" ? `trust ${src.trust_score}` : "",
            Array.isArray(src.matched_profiles) && src.matched_profiles.length ? src.matched_profiles.join(", ") : ""
        ].filter(Boolean).join(" · ");
        return `
            <li>
                <div class="evidence-title">${url ? `<a href="${safeText(url)}" target="_blank" rel="noopener noreferrer">${safeText(title)}</a>` : safeText(title)}</div>
                ${url ? `<div class="evidence-url">${safeText(url)}</div>` : ""}
                ${reason ? `<div class="evidence-reason">${safeText(compactText(reason, 220))}</div>` : ""}
                ${meta ? `<div class="evidence-meta">${safeText(meta)}</div>` : ""}
            </li>
        `;
    }).join("");

    return `
        <details class="validator-evidence-summary">
            <summary>${t("ui.viewEvidence", { count: items.length })}</summary>
            <ul>${rows}</ul>
        </details>
    `;
}

function renderValidatorProviderModelTitle(info = {}) {
    const config = info.validator_config?.config || info.config || info.validator_config || {};
    const provider = config.provider || info.provider;
    const model = config.model || info.model;
    if (!provider && !model) return "";
    return `title="${safeText(provider || "-")} | ${safeText(model || "-")}"`;
}

function renderValidationsTree(container, validations, assertions, orderData = null) {
    if (!validations || Object.keys(validations).length === 0) {
        container.innerHTML = `<p class="empty-state">${safeText(t("messages.noValidationsRegistered"))}</p>`;
        return;
    }

    let html = `<div class="validation-tree">`;

    for (const [assertionId, validatorsObj] of Object.entries(validations)) {
        const assertionText = resolveAssertionText(assertionId, assertions, orderData, validatorsObj);

        const assertionResult = getAssertionResult(orderData, assertionId);
        const literals = Object.values(validatorsObj).map(v => getValidationLiteral(v.approval));
        const approvedCount = literals.filter(v => v === "True").length;
        const rejectedCount = literals.filter(v => v === "False").length;
        const unknownCount = literals.filter(v => v === "Unknown").length;

        let status = "unknown";
        if (assertionResult?.winner === "TRUE") status = "true";
        else if (assertionResult?.winner === "FALSE") status = "false";
        else if (approvedCount > rejectedCount) status = "true";
        else if (rejectedCount > approvedCount) status = "false";
        else if (unknownCount > 0) status = "pending";

        const validatorsHtml = Object.entries(validatorsObj).map(([validator, info]) => {
            const lit = getValidationLiteral(info.approval);
            const litClass = lit === "True" ? "true-news" : lit === "False" ? "false-news" : "partial-news";
            let desc = info.text || t("ui.noDescription");
            if (typeof desc === "object") desc = JSON.stringify(desc, null, 2);
            const tx = info.tx_hash ? `<a href="#" onclick="event.preventDefault(); navigateToTx('${String(info.tx_hash).replace(/'/g, "\\'")}')">${shortValue(info.tx_hash, 18)}</a>` : "-";
            const responseTime = formatDurationSeconds(info.response_time_seconds);
            const validatorTooltip = renderValidatorProviderModelTitle(info);
            const weightedDetail = assertionResult?.details?.find(d => String(d.validator).toLowerCase() === String(validator).toLowerCase());
            const typeLabel = weightedDetail ? validatorTypeLabel(weightedDetail.validator_type) : validatorTypeLabel(info.validator_config?.config?.type || info.config?.type || info.validator_type);
            const preferredDomainsBadge = renderPreferredDomainsBadge(preferredDomainsInfoForValidation(info));
            const reputationHtml = weightedDetail ? `<span>rep ${safeText(formatMaxTwoDecimals(weightedDetail.reputation))}</span>` : "";
            const weightHtml = `<div class="validator-weights"><span>${safeText(typeLabel)}</span>${reputationHtml}${preferredDomainsBadge}</div>`;
            return `
                <div class="validator-card">
                    <div class="validator-name"><a href="#" ${validatorTooltip} onclick="event.preventDefault(); showValidatorDetail('${validatorHashForJs(validator)}')">${safeText(info.validator_alias || validator)}</a></div>
                    <div class="validator-result ${litClass}">${lit}</div>
                    <div class="validator-desc">${safeText(desc)}</div>
                    <div class="validator-meta">
                        ${weightHtml}
                        <div class="validator-response-time" title="${safeText(t("ui.requestResponseTime"))}"><span class="clock-icon" aria-hidden="true"></span>${safeText(responseTime)}</div>
                    </div>
                    <div class="validator-tx" title="${safeText(t("ui.transactionHash"))}">${tx}</div>
                    ${renderEvidenceLinks(info)}
                </div>
            `;
        }).join("");

        html += `
            <details class="validation-node">
                <summary class="validation-summary">
                    <div class="assertion-title ${status}">▸ ${safeText(assertionId)}. ${safeText(assertionText)}${assertionResult ? ` → ${safeText(assertionResult.winner)}` : ""}</div>
                    ${assertionResult ? renderScorePills(assertionResult) : `<div class="vote-pills">
                        ${renderVotePill(approvedCount, "True", "vote-true")}
                        ${renderVotePill(rejectedCount, "False", "vote-false")}
                        ${renderVotePill(unknownCount, "Unknown", "vote-unknown")}
                    </div>`}
                </summary>
                <div class="validator-grid">
                    ${validatorsHtml}
                </div>
            </details>
        `;
    }

    html += `</div>`;
    container.innerHTML = html;
}

function renderValidatorValidationsByOrder(container, groupedOrders) {
    if (!groupedOrders || !Object.keys(groupedOrders).length) {
        container.innerHTML = `<p class="empty-state">${safeText(t("ui.noValidatorValidations"))}</p>`;
        return;
    }

    let html = `<div class="validation-tree">`;

    for (const [orderId, orderData] of Object.entries(groupedOrders)) {
        const assertionsCount = Object.keys(orderData.validations || {}).length;
        const titleText = compactText(orderData.text || t("ui.noNewsTextShort"), 110);
        const safeOrder = String(orderId).replace(/'/g, "\\'");
        html += `
            <details class="validation-node order-validation-node" open>
                <summary class="validation-summary order-validation-summary">
                    <div>
                        <div class="assertion-title">${t("ui.order")} ${shortValue(orderId, 26)}</div>
                        <div class="text-muted">(${safeText(titleText)})</div>
                    </div>
                    <div class="vote-pills">
                        <span class="vote-pill vote-unknown">${assertionsCount} ${t("ui.assertions").toLowerCase()}</span>
                        <a class="btn-secondary btn-small" href="#" onclick="event.preventDefault(); navigateToOrderDetails('${safeOrder}');">${t("ui.viewOrder")}</a>
                    </div>
                </summary>
                <div class="order-validation-content">
                    <div id="validator-order-${safeText(orderId).replace(/[^a-zA-Z0-9_-]/g, "-")}"></div>
                </div>
            </details>
        `;
    }

    html += `</div>`;
    container.innerHTML = html;

    for (const [orderId, orderData] of Object.entries(groupedOrders)) {
        const targetId = `validator-order-${String(orderId).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
        const target = document.getElementById(targetId);
        if (target) renderValidationsTree(target, orderData.validations, orderData.assertions, orderData);
    }
}



// =========================================================
// VALIDATORS CACHE
// =========================================================
function renderValidatorCategories(categories = []) {
    if (!Array.isArray(categories) || !categories.length) return "-";
    const labels = categories.map(cat => {
        const id = cat.id ?? cat.categoryId ?? cat;
        const name = cat.name || categoryLabel(id) || `${t("ui.category")} ${id}`;
        return `${name} (${id})`;
    });
    const preview = labels.slice(0, 2).join(", ");
    const extra = labels.length > 2 ? ` +${labels.length - 2}` : "";
    return `<span class="category-summary" title="${safeText(labels.join("\n"))}">${safeText(preview)}${safeText(extra)}</span>`;
}

function renderValidatorStats(stats = {}) {
    return {
        requests: safeText(stats.requests_sent ?? 0),
        responses: safeText(stats.successful_responses ?? 0),
        avgResponseTime: formatDurationSeconds(stats.avg_response_time_seconds)
    };
}

function validatorHashForJs(value) {
    return String(value || "").replace(/'/g, "\\'");
}

function renderValidatorsTable(validators) {
    return `
        <table class="compact-table visual-orders-table">
            <thead>
                <tr>
                    <th>Validator Hash</th>
                    <th>${t("ui.name")}</th>
                    <th>${t("ui.type")}</th>
                    <th>${t("ui.provider")}</th>
                    <th>${t("ui.model")}</th>
                    <th>${t("ui.categories")}</th>
                    <th>${t("ui.status")}</th>
                    <th>${t("ui.ipfsConfig")}</th>
                    <th>${t("ui.actions")}</th>
                </tr>
            </thead>
            <tbody>
                ${validators.map(v => {
                    const cfg = v.config || {};
                    const validator = v.validator || "";
                    return `
                        <tr>
                            <td><a href="#" onclick="event.preventDefault(); showValidatorDetail('${validatorHashForJs(validator)}')">${shortValue(validator, 18)}</a></td>
                            <td>${safeText(cfg.name || "-")}</td>
                            <td>${safeText(validatorTypeLabel(cfg.type))}</td>
                            <td>${safeText(cfg.provider || "-")}</td>
                            <td>${safeText(cfg.model || "-")}</td>
                            <td>${renderValidatorCategories(v.categories)}</td>
                            <td>${safeText(cfg.status || "-")}</td>
                            <td>${v.ipfs_hash ? shortValue(v.ipfs_hash, 18) : "-"}</td>
                            <td><button class="btn-secondary btn-small" onclick="showValidatorValidations('${validatorHashForJs(validator)}')">${t("ui.viewValidations")}</button></td>
                        </tr>
                    `;
                }).join("")}
            </tbody>
        </table>
    `;
}

async function listValidatorsCache() {
    const container = document.getElementById("validatorsTableContainer");
    const detail = document.getElementById("validatorDetailContainer");
    if (!container) return;

    container.innerHTML = `<p class="empty-state">${safeText(t("ui.loadingValidators"))}</p>`;
    if (detail) detail.innerHTML = "";

    try {
        const response = await fetchWithAuth(`${API}/validators/cache?recover_ipfs=true`);
        if (!response.ok) throw new Error(`Error API: ${response.status}`);
        const data = await response.json();
        const validators = data.validators || [];

        if (!validators.length) {
            container.innerHTML = `<p class="empty-state">${safeText(t("ui.noValidators"))}</p>`;
            return;
        }

        container.innerHTML = renderValidatorsTable(validators);
    } catch (error) {
        console.error("Error cargando validadores:", error);
        container.innerHTML = `<p class="empty-state">${safeText(t("ui.validatorsLoadError"))}</p>`;
        alertMessage(t("ui.validatorsLoadError"), "error");
    }
}

async function showValidatorDetail(validatorHash) {
    const container = document.getElementById("validatorsTableContainer");
    const detail = document.getElementById("validatorDetailContainer");
    if (!detail) return;
    detail.innerHTML = `<p class="empty-state">${safeText(t("ui.loadingConfig"))}</p>`;
    showSection('validators', false);

    try {
        const response = await fetchWithAuth(`${API}/validators/cache/${encodeURIComponent(validatorHash)}`);
        if (!response.ok) throw new Error(`Error API: ${response.status}`);
        const data = await response.json();
        const cfg = data.config || {};
        const stats = renderValidatorStats(data.stats);
        if (container) container.innerHTML = renderValidatorsTable([data]);
        detail.innerHTML = `
            <div class="validator-detail-card">
                <h3>${t("ui.validatorConfig")}</h3>
                <table class="compact-table">
                    <tbody>
                        <tr><th>Validator Hash</th><td>${safeText(data.validator || validatorHash)}</td></tr>
                        <tr><th>${t("ui.ipfsConfig")}</th><td>${safeText(data.ipfs_hash || "-")}</td></tr>
                        <tr><th>${t("ui.name")}</th><td>${safeText(cfg.name || "-")}</td></tr>
                        <tr><th>${t("ui.type")}</th><td>${safeText(validatorTypeLabel(cfg.type))}</td></tr>
                        <tr><th>${t("ui.provider")}</th><td>${safeText(cfg.provider || "-")}</td></tr>
                        <tr><th>${t("ui.model")}</th><td>${safeText(cfg.model || "-")}</td></tr>
                        <tr><th>${t("ui.categories")}</th><td>${renderValidatorCategories(data.categories)}</td></tr>
                        <tr><th>${t("ui.requestsSent")}</th><td>${stats.requests}</td></tr>
                        <tr><th>${t("ui.successfulResponses")}</th><td>${stats.responses}</td></tr>
                        <tr><th>${t("ui.averageResponseTime")}</th><td>${stats.avgResponseTime}</td></tr>
                        <tr><th>${t("ui.activeDate")}</th><td>${safeText(cfg.active_date || "-")}</td></tr>
                        <tr><th>${t("ui.updatedDate")}</th><td>${safeText(cfg.updated_date || "-")}</td></tr>
                        <tr><th>${t("ui.endDate")}</th><td>${safeText(cfg.end_date || "-")}</td></tr>
                        <tr><th>${t("ui.status")}</th><td>${safeText(cfg.status || "-")}</td></tr>
                    </tbody>
                </table>
                <button class="btn-secondary" onclick="showValidatorValidations('${String(validatorHash).replace(/'/g, "\\'")}')">${t("ui.viewCompletedValidations")}</button>
            </div>
        `;
    } catch (error) {
        console.error("Error cargando detalle de validador:", error);
        detail.innerHTML = `<p class="empty-state">${safeText(t("ui.validatorConfigError"))}</p>`;
    }
}

async function showValidatorValidations(validatorHash) {
    const container = document.getElementById("validatorsTableContainer");
    const detail = document.getElementById("validatorDetailContainer");
    if (!detail) return;
    detail.innerHTML = `<p class="empty-state">${safeText(t("ui.loadingValidations"))}</p>`;
    showSection('validators', false);

    try {
        const response = await fetchWithAuth(`${API}/validators/cache/${encodeURIComponent(validatorHash)}/validations?include_validations=true&include_order_link=true`);
        if (!response.ok) throw new Error(`Error API: ${response.status}`);
        const data = await response.json();
        const validations = data.validations || [];
        if (container) {
            container.innerHTML = renderValidatorsTable([{
                validator: data.validator || validatorHash,
                ipfs_hash: data.ipfs_hash,
                config: data.config,
                categories: data.categories,
                stats: data.stats
            }]);
        }

        const groupedOrders = {};
        validations.forEach(v => {
            const orderId = String(v.order_id || "sin-order");
            const assertionId = String(v.idAssertion || "-");
            const assertionText = v.assertion_text || v.payload?.assertion_text || "";

            if (!groupedOrders[orderId]) {
                groupedOrders[orderId] = {
                    text: v.order_text || "",
                    validations: {},
                    assertions: []
                };
            }
            if (!groupedOrders[orderId].validations[assertionId]) {
                groupedOrders[orderId].validations[assertionId] = {};
                groupedOrders[orderId].assertions.push({
                    idAssertion: assertionId,
                    text: assertionText || `${t("ui.assertion")} ${assertionId}`
                });
            }

            groupedOrders[orderId].validations[assertionId][validatorHash] = {
                approval: v.approval,
                text: v.payload?.descripcion || v.payload?.text || v.text || "",
                tx_hash: v.tx_hash,
                validator_alias: data.config?.name || validatorHash,
                validator_config: { config: data.config || {} },
                order_id: v.order_id,
                response_time_seconds: v.response_time_seconds,
                sources: v.sources || v.payload?.sources || [],
                evidence_used: v.evidence_used || v.payload?.evidence_used || [],
                evidence_search_response: v.evidence_search_response || v.payload?.evidence_search_response || null,
                search_policy: v.search_policy || v.payload?.search_policy || null,
                payload: v.payload || {}
            };
        });

        detail.innerHTML = `
            <div class="validator-detail-card">
                <h3>${t("ui.completedValidationsTitle")}</h3>
                <p class="text-muted">Validator: ${safeText(validatorHash)}</p>
                ${validations.length ? `<div id="validatorValidationsTree"></div>` : `<p class="empty-state">${safeText(t("ui.noValidatorValidations"))}</p>`}
            </div>
        `;

        if (validations.length) {
            const tree = document.getElementById("validatorValidationsTree");
            renderValidatorValidationsByOrder(tree, groupedOrders);
        }
    } catch (error) {
        console.error("Error cargando validaciones del validador:", error);
        detail.innerHTML = `<p class="empty-state">${safeText(t("ui.validatorValidationsError"))}</p>`;
    }
}

window.addEventListener("trustnews:languagechange", () => {
    if (currentOrderData?.order_id) {
        const tabs = document.getElementById("orderTabs");
        const detailsContainer = document.getElementById("fixedDetailsContainer");
        const tabContent = document.getElementById("tabContent");
        const activeTabKey = tabs?.querySelector(".activeTab")?.dataset.tabKey;
        const translatedTabNames = {
            summary: t("tabs.summary"),
            assertions: t("tabs.assertions"),
            evidence: t("ui.evidence"),
            process: t("ui.process"),
            technical: t("ui.technical"),
            ipfs: "IPFS",
            events: t("tabs.events")
        };

        tabs?.querySelectorAll("[data-tab-key]").forEach(button => {
            const translatedName = translatedTabNames[button.dataset.tabKey];
            if (translatedName) button.textContent = translatedName;
        });

        if (detailsContainer) {
            detailsContainer.innerHTML = `<span class="status-value" data-status="${safeText(currentOrderData.status || "UNKNOWN")}"></span>`;
        }

        if (tabContent && activeTabKey) {
            const assertions = collectOrderAssertions(currentOrderData.assertions, currentOrderData);
            const activeTabData = {
                summary: currentOrderData,
                assertions,
                evidence: currentOrderData.validations || {},
                process: currentOrderEvents,
                technical: currentOrderData,
                ipfs: currentOrderData.document || null,
                events: currentOrderEvents
            }[activeTabKey];
            renderTabContent(activeTabKey, activeTabData, assertions, currentOrderData, currentOrderEvents);
        }
    }
    const activeSectionId = document.querySelector("main section.active")?.id || document.querySelector("section.active")?.id;
    if (activeSectionId === "orders") {
        const listContainer = document.getElementById("listTabContent");
        if (listContainer?._fullData) renderTableData(listContainer, listContainer._fullData);
    } else if (activeSectionId === "validators") {
        listValidatorsCache();
    }

    const badge = document.getElementById("sessionBadge");
    if (badge && keycloak?.tokenParsed?.preferred_username) {
        badge.textContent = `${t("header.protectedSession")} · ${keycloak.tokenParsed.preferred_username}`;
    }
});

// Refuerzo visual de detalles: mantener la tabla original, pero más integrada y compacta.
const __tnOriginalInitializeApp = initializeApp;
initializeApp = function initializeAppUXIntegrated() {
    __tnOriginalInitializeApp();

    window.I18N?.applyTranslations(document);

    const languageSelector = document.getElementById("languageSelector");
    if (languageSelector && !languageSelector.dataset.bound) {
        languageSelector.dataset.bound = "true";
        languageSelector.value = window.I18N?.getLanguage?.() || "es";
        languageSelector.addEventListener("change", event => window.I18N?.setLanguage(event.target.value));
    }

    const logoutBtn = document.getElementById("btn-logout");
    if (logoutBtn && !logoutBtn.dataset.bound) {
        logoutBtn.dataset.bound = "true";
        logoutBtn.addEventListener("click", () => keycloak.logout({ redirectUri: window.location.origin }));
    }

    const badge = document.getElementById("sessionBadge");
    if (badge && keycloak?.tokenParsed?.preferred_username) {
        badge.textContent = `${t("header.protectedSession")} · ${keycloak.tokenParsed.preferred_username}`;
    }

    const validatorsBtn = document.getElementById("btn-listValidators");
    if (validatorsBtn && !validatorsBtn.dataset.bound) {
        validatorsBtn.dataset.bound = "true";
        validatorsBtn.addEventListener("click", () => listValidatorsCache());
    }

    const chk = document.getElementById("chk-viewAll");
    if (chk && !chk.dataset.bound) {
        chk.dataset.bound = "true";
        chk.addEventListener("change", () => {
            TABLE_PAGE_ORDERS = 1;
            listOrders();
        });
    }
};
