

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

const CATEGORY_MAP = {
    1: "ECONOMÍA",
    2: "DEPORTES",
    3: "POLÍTICA",
    4: "TECNOLOGÍA",
    5: "SALUD",
    6: "ENTRETENIMIENTO",
    7: "CIENCIA",
    8: "CULTURA",
    9: "MEDIO AMBIENTE",
    10: "SOCIAL"
};

const keycloak = new Keycloak({
    url: '/auth', 
    realm: 'TrustNews',
    clientId: 'TrustNewsWeb'
});


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
    return `<span title="${value}">${short}</span>`;
  }
  return value;
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
    return isNaN(d.getTime()) ? "Fecha Inválida" : d.toISOString().replace("T"," ").split(".")[0];
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
function showSection(sectionId, reset = true) {
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

        if (sectionId === "orders") {
            listOrders();
        }
}





// =========================================================
// POLLING DE ÓRDENES
// =========================================================
async function pollOrder(orderId, startTime) {
    const start = startTime || Date.now();
    await loadOrderById(orderId, false); 

    const detailsContainer = document.getElementById("fixedDetailsContainer");
    const statusElement = detailsContainer.querySelector('.status-value');
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
            alertMessage("⛔ Límite alcanzado: No te quedan cuotas para generar aserciones.", "error", 5000);
            return []; // Devolvemos un array vacío para no romper la tabla de la interfaz
        }

        // Si es otro tipo de error (500, 404, etc.)
        if (!response.ok) throw new Error(`Error API: ${response.status}`);

        const data = await response.json();
        return data.payload.assertions || [];
    } catch (err) {
        console.error("Error al generar aserciones:", err);
        alertMessage("Error al conectar con el servicio de aserciones", "error");
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
                    <th>Aserción</th>
                    <th>Categoría</th>
                    <th style="width:60px;"></th>
                </tr>
            </thead>
            <tbody>
                ${assertions.map(a => `
                    <tr data-id="${a.idAssertion}">
                        <td>${a.idAssertion}</td>
                        <td contenteditable="true" class="editable-text">${a.text}</td>
                        <td>${renderCategorySelect(a.categoryId)}</td>
                        <td><button class="btn-delete-row">✖</button></td>
                    </tr>
                `).join("")}
            </tbody>
        </table>

        <button id="btn-add-row" class="btn btn-tertiary">+</button>
        <button id="btn-publish-with-assertions" class="btn btn-tertiary">Publicar con Aserciones</button>
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
            ${Object.entries(CATEGORY_MAP)
                .map(([id, name]) => `
                    <option value="${id}" ${selected == id ? "selected" : ""}>${name}</option>`
                ).join("")}
        </select>
    `;
}



// =========================================================
// OPERACIONES DE NEWS
// =========================================================
async function publishNew() {
    const text = document.getElementById("newsText").value.trim();
    if (!text) return alertMessage("Introduce un texto para verificar.", 'error');

    showSection('order');
    document.getElementById("orderId").value = "Publicando...";

    const res = await fetchWithAuth(`${API}/orders/publishNew`, {
        method: "POST",
        body: JSON.stringify({text})
    });

    if (!res.ok) {
        alertMessage("Error al publicar la noticia. Inténtalo de nuevo.", 'error');
        document.getElementById("orderId").value = "Error...";
        return;
    }
    
    const data = await res.json();
    const newOrderId = data.order_id;

    document.getElementById("orderId").value = newOrderId;
    alertMessage(`Noticia publicada. Iniciando polling para Order ID: ${newOrderId}`, 'primary');
    pollOrder(newOrderId);
}

async function publishWithAssertions() {
    const text = document.getElementById("newsText").value.trim();
    if (!text) return alertMessage("Introduce un texto para verificar.", 'error');

    const container = document.getElementById("news-assertions-container");
    if (!container) return alertMessage("No se encontró el contenedor de aserciones.", 'error');

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
        return alertMessage("Debes tener al menos una aserción", 'error');
    }

    const payload = { text, assertions };

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
        alertMessage(`Noticia publicada. Iniciando polling para Order ID: ${newOrderId}`, 'primary');
        pollOrder(newOrderId);
        
        return data;
    } catch (error) {
        console.error("Error al publicar con aserciones:", error);
        alertMessage("Error al publicar la noticia con aserciones", 'error');
        throw error;
    }
}





async function findPrevious() {
    const text = document.getElementById("newsText").value.trim();
    if (!text) return alertMessage("Introduce un texto a buscar.", 'error');
    
    alertMessage("Buscando verificaciones previas...", 'info');
    
    try {
        const res = await fetchWithAuth(`${API}/find-order-by-text`, {
            method: "POST",
            body: JSON.stringify({text})
        });
        
        if (!res.ok) throw new Error("API responded with error.");

        const data = await res.json();
        renderTableData(document.getElementById("findResults"), data); 
        alertMessage(`Se encontraron ${data.length} resultados.`, 'primary');
    } catch (e) {
        alertMessage("Error de conexión o datos inválidos al buscar.", 'error');
        document.getElementById("findResults").innerHTML = '<tr><td colspan="3">Error al cargar los resultados.</td></tr>';
    }
}

// =========================================================
// OPERACIONES DE ORDERS
// =========================================================
// =========================================================
// OPERACIONES DE ORDERS
// =========================================================
async function listOrders() {
    alertMessage("Listando todas las órdenes...", 'info');
    
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
        alertMessage(`Órdenes cargadas: ${data.length}`, 'primary');

    } catch (e) {
        alertMessage("Error al listar órdenes. Ver consola.", 'error');
        console.error("List Orders Error:", e);
    }
}

async function findOrder() {
    const orderId = document.getElementById("orderId").value.trim();
    if (!orderId) return alertMessage("Introduce un order_id.", 'error');
    await loadOrderById(orderId, true);
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
        detailsContainer.innerHTML = `<div class="p-4 text-center text-gray-400">Cargando detalles de la orden <strong>${orderId}</strong>...</div>`;
    }

    try {
        const res = await fetchWithAuth(`${API}/orders/${orderId}`);
        
        if (!res.ok) {
            const errorText = await res.text();
            detailsContainer.innerHTML = `<div class="p-3 rounded-lg bg-red-800 border border-red-500 text-red-100">
                Error ${res.status}: No se pudo encontrar la orden <strong>${orderId}</strong>.<br>
                Mensaje: ${errorText || 'Error desconocido'}
            </div>`;
            tabs.innerHTML = tabContent.innerHTML = '';
            alertMessage(`Error: Order ID ${orderId} no encontrada.`, 'error');
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

        renderDetails(detailsContainer, data);

        if (cleanup || res.status !== 304) {
            let eventsData = [];
            try {
                const resEv = await fetchWithAuth(`${API}/orders/${orderId}/events`);
                if (resEv.ok) eventsData = await resEv.json();
            } catch(e){ console.error("Error cargando eventos:", e); }

            const sections = [
                {name: "Asertions", data: data.assertions || []},
                {name: "Documento", data: data.document || null},
                {name: "Validations", data: data.validations || {}},
                {name: "Eventos", data: eventsData} 
            ];

            if (cleanup || tabs.children.length === 0) {
                tabs.innerHTML = '';
                sections.forEach((s,i) => {
                    const btn = document.createElement("button");
                    btn.innerText = s.name;
                    btn.className = 'tab-button';
                    btn.onclick = () => {
                        document.querySelectorAll("#orderTabs button").forEach(b => b.classList.remove("activeTab"));
                        btn.classList.add("activeTab");
                        renderTabContent(s.name, s.data, data.assertions); 
                    };
                    if(i===0) btn.classList.add("activeTab");
                    tabs.appendChild(btn);
                    if(i===0) renderTabContent(s.name, s.data, data.assertions);
                });
            } else {
                const activeTab = tabs.querySelector('.activeTab');
                if (activeTab) {
                    const sec = sections.find(s => s.name === activeTab.innerText);
                    if (sec) renderTabContent(sec.name, sec.data, data.assertions);
                }
            }
        }
    } catch (error) {
        detailsContainer.innerHTML = `<div class="p-3 rounded-lg bg-red-800 border border-red-500 text-red-100">
            Error de conexión o JSON inválido: ${error.message}
        </div>`;
        tabs.innerHTML = tabContent.innerHTML = '';
        console.error(error);
        alertMessage("Error crítico al cargar la orden.", 'error');
    }
}

// =========================================================
// RENDER TAB CONTENT
// =========================================================
function renderTabContent(tabName, data, assertions=[]) {
    const container = document.getElementById("tabContent"); 
    container.innerHTML = ""; 
    
    switch(tabName) {
        case "Documento": 
            container.innerHTML = `<pre class="event-payload-pre">${JSON.stringify(data,null,2)}</pre>`; 
            break;
        case "Validations": 
            renderValidationsTree(container, data, assertions); 
            break;
        case "Eventos": 
            renderEventsTable(container, data); 
            break;
        case "Asertions": 
            renderAssertions(container, data); 
            break;
        default: 
            container.innerHTML = `<pre class="event-payload-pre">${JSON.stringify(data,null,2)}</pre>`;
            break;
    }
}


// =========================================================
// RENDER DETALLES Y RESUMEN
// =========================================================

function renderProcessingFlow(currentStatus, validatorsPending = 0) {
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

                // Si es el penúltimo → mostrar número
                if (step === "VALIDATION_PENDING") {
                    label = validatorsPending > 0 ? validatorsPending : "";
                }

                // Caso especial final → todo verde sin animación
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



function renderDetails(container, data) {
    container.innerHTML = '<h3 class="text-lg font-bold mb-4">Detalles de la Orden</h3>';

    // --- Estadísticas (Resumen)
    let totalAssertions = 0, trueAssertions = 0, falseAssertions = 0, unknownCount = 0;
    if (data.validations) {
        for (const assertionId in data.validations) {
            totalAssertions++;
            const validators = data.validations[assertionId];
            let approved = 0, rejected = 0;
            Object.values(validators).forEach(v => {
                const lit = getValidationLiteral(v.approval);
                if (lit === "True") approved++;
                else if (lit === "False") rejected++;
                else if (lit === "Unknown") unknownCount++;
            });
            const known = approved - rejected;
            if (known > 0)  trueAssertions++;
            else if (known < 0) falseAssertions++;
            // Nota: En su data, ninguna aserción resulta en known === 0, 
            // por eso trueAssertions es 2 y falseAssertions es 1.
        }
    }

    let percentTrue=0;
    let percentFalse=0;
    
    // **********************************
    // ** CORRECCIÓN DE PORCENTAJES **
    // **********************************
    // FIX 1: La variable knownAssertions se redefine como el total de aserciones resueltas (2 + 1 = 3),
    // para evitar que el cálculo se bloquee (anteriormente daba 0).
    const knownAssertions = trueAssertions + falseAssertions; 
    
    if (knownAssertions !== 0) {
        // FIX 2: Se usa knownAssertions como denominador para el porcentaje de aserciones resueltas.
        percentTrue = (trueAssertions / knownAssertions) * 100; 
        percentFalse = (falseAssertions / knownAssertions) * 100;
    } 
    // **********************************


    let overallTag = "Sin Validaciones", overallClass = "unknown";
    if (totalAssertions > 0) {
        if (trueAssertions > falseAssertions && trueAssertions > 0) { 
            if (percentTrue === 100) 
                overallTag = "Totalmente Cierta: 100% Aserciones Válidas"
            else
                overallTag = "Mayoritariamente Cierta: "+percentTrue.toFixed(1)+"% Aserciones Válidas"; 
            overallClass = "true-news"; 
            
        }
        else if (falseAssertions > trueAssertions && falseAssertions > 0) { 
            // FIX 3: Usar percentFalse para el mensaje de Mayoría Falsa.
            overallTag = " Mayoritariamente Falsa: "+percentFalse.toFixed(1)+"% Aserciones Falsas"; 
            overallClass = "false-news"; 
        }
        else if (trueAssertions === falseAssertions && knownAssertions > 0) {
             overallTag = " Validación Mixta: "+percentTrue.toFixed(1)+"% Aserciones Válidas"; 
             overallClass = "partial-news";
        }
        else { overallTag = "Pendiente / Indefinido: 0.0% Aserciones Válidas"; overallClass = "unknown"; }
    }

    // --- Contenido de las subpestañas
    const detailsHtml = `<table class="compact-table">` +
        Object.entries(data)
              .filter(([k, v]) => k !== "_id" && k !== "document" && k !== "assertions" && k !== "validations" && k !== "validators" && k !== "text" && k !== "status" && k !== "validators_pending")
              .map(([k, v]) => {
                  if (k === "text" && typeof v === "object" && v?.text) v = v.text;

                  // Hacer tx_hash clicable
                  if (k === "tx_hash" && v) {
                      const safeHash = v.replace(/'/g, "\\'");
                      v = `<a href="#" onclick="event.preventDefault(); navigateToTx('${safeHash}'); return false;">${shortHex(v)}</a>`;
                  }
                  if (k === "postId" && v) { 
                      v = `<a href="#" onclick="event.preventDefault(); navigateToPost('${v}'); return false;">${v}</a>`;
                  }
                  if (k === "order_id" && v) {                       
                      v = `<a href="#" onclick="event.preventDefault(); navigateToConsistency('${v}'); return false;">${v}</a>`;
                      return `<tr><th>Validar vs blockchain</th><td>${v || ''}</td></tr>`;
                  }
                  if (k === "cid" && v) {
                      v = `<a href="#" onclick="event.preventDefault(); navigateToIpfs('${v}'); return false;">${v}</a>`;
                  }


                  return `<tr><th>${k}</th><td>${v || ''}</td></tr>`;
              }).join('') +
        `</table>`;

    const summaryHtml = `<table class="compact-table">
        <tr><th>ID de Orden</th><td>${data.order_id || "N/A"}</td></tr>
        <tr><th>Estado General</th><td class="status-value ${overallClass}" data-status="${data.status || 'UNKNOWN'}"> ${overallTag}</td></tr>
        <tr>
            <th>Estado de Procesamiento</th>
            <td>
                ${data.status || "N/A"}
                ${renderProcessingFlow(data.status || "PENDING", data.validators_pending || 0)}
            </td>
        </tr>
        <tr><th>Noticia (Resumen)</th><td>${data.text || "N/A"}</td></tr>
        <tr><th>Validators Pendientes</th><td>${data.validators_pending ?? 0}</td></tr>
        <tr><th>Aserciones Ciertas</th><td class="true-news"> ${trueAssertions} (${percentTrue.toFixed(1)}%)</td></tr>
        <tr><th>Aserciones Falsas</th><td class="false-news"> ${falseAssertions} (${percentFalse.toFixed(1)}%)</td></tr>
        <tr><th>Validaciones Desconocidas</th><td class="unknown"> ${unknownCount}</td></tr>
    </table>`;

    // --- Subpestañas internas
     container.innerHTML = `
        <div class="sub-tabs flex space-x-2 border-b border-gray-600 mb-4">
            <button class="subTab activeSubTab p-2 text-sm font-medium" data-target="summaryTab">Resumen</button>
            <button class="subTab p-2 text-sm font-medium" data-target="detailsTab">Detalles</button>
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
function renderValidationsTree(container, validations, assertions) {
    if (!validations || Object.keys(validations).length === 0) {
        container.innerHTML = "<p class='text-gray-400'>No hay validaciones disponibles para esta orden.</p>";
        return;
    }

    let html = "";

    for (const [assertionId, validatorsObj] of Object.entries(validations)) {
        let assertionText = assertions.find(a => a.idAssertion === assertionId)?.text || "(Aserción sin texto)";
        if (typeof assertionText === 'object' && assertionText !== null && assertionText.text) {
            assertionText = assertionText.text;
        }

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
                <td class="text-primary">${info.validator_alias || validator}</td>
                <td class="${cls}"><b>${lit}</b></td>
                <td><pre class="event-payload-pre mt-0">${desc}</pre></td>
                <td>${info.tx_hash ? `<a href="#" onclick="event.preventDefault(); navigateToTx('${info.tx_hash}')">${shortHex(info.tx_hash)}</a>` : ""}</td>
            </tr>`;
        }

        // Definir clase según el resultado
        let summaryClass = "";
        if (approvedCount > rejectedCount) summaryClass = "summary-green";
        else if (approvedCount < rejectedCount) summaryClass = "summary-red";
        else summaryClass = "summary-yellow";

        html += `<details class="p-3 bg-gray-700 rounded-lg mb-3">
            <summary class="cursor-pointer ${summaryClass}" style="font-weight:bold; font-size:1rem;">
                ${assertionId}. ${assertionText} → <span style="font-size:0.9rem;">(${approvedCount} A / ${rejectedCount} R)</span>
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
        container.innerHTML = "<p class='text-gray-400 p-4'>No hay datos disponibles.</p>";
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
            <tr>${keys.map(k => `<th class="uppercase text-xs">${k}</th>`).join("")}</tr>
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
                return `<td><a href="#" onclick="event.preventDefault(); navigateToOrderDetails('${val}')">${val}</a></td>`;
            }
            if (k === "tx_hash" && val !== 'N/A') {
                return `<td><a href="#" onclick="event.preventDefault(); navigateToTx('${val}')">${shortHex(val)}</a></td>`;
            }

            return `<td>${val}</td>`;
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
            >Anterior</button>

            <span class="text-sm">Página ${TABLE_PAGE_ORDERS} / ${totalPages}</span>

            <button 
                class="px-3 py-1 bg-gray-700 rounded disabled:opacity-40"
                onclick="changeTablePage(1)"
                ${TABLE_PAGE_ORDERS === totalPages ? "disabled" : ""}
            >Siguiente</button>
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
        container.innerHTML = "<p class='text-gray-400 p-4'>No hay eventos registrados.</p>";
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
        "validation_completed": "✔️"
    };

    function renderPage(page) {
        const start = (page - 1) * perPage;
        const end = start + perPage;
        const pageData = events.slice(start, end);

        const rows = pageData.map(e => {
            const payloadStr = JSON.stringify(e.payload, null, 2);
            const visibleSummary = payloadStr.substring(0, 80).trim() + (payloadStr.length > 80 ? '...' : '');
            const icon = actionIcons[e.action] || "❓";

            return `
                <tr>
                    <td class="col-icon text-center">${icon}</td>
                    <td class="col-action">${e.action}</td>
                    <td class="col-topic">${e.topic}</td>
                    <td class="col-date">${e.timestamp}</td>
                    <td class="col-payload">
                        <details class="event-payload-details">
                            <summary><span class="summary-text">${visibleSummary}</span></summary>
                            <pre class="event-payload-pre">${payloadStr}</pre>
                        </details>
                    </td>
                </tr>
            `;
        }).join("");

        container.innerHTML = `
            <h3 class="text-lg font-bold mb-3">
                Eventos (${events.length} total) — Página ${page}/${totalPages}
            </h3>
            <table class="compact-table w-full">
                <thead>
                    <tr>
                        <th class="col-icon">Icono</th>
                        <th class="col-action">Acción</th>
                        <th class="col-topic">Topic</th>
                        <th class="col-date">Fecha</th>
                        <th class="col-payload">Payload</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
            <div class="flex justify-between items-center mt-3">
                <button id="prevPage" class="px-3 py-1 bg-gray-700 rounded disabled:opacity-50">⟵ Anterior</button>
                <span class="text-sm text-gray-300">Página ${page} de ${totalPages}</span>
                <button id="nextPage" class="px-3 py-1 bg-gray-700 rounded disabled:opacity-50">Siguiente ⟶</button>
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
        container.innerHTML = "<p class='text-gray-400 p-4'>No hay aserciones disponibles.</p>";
        return;
    }

    let html = `
        <table id="assertionsTable">
            <thead>
                <tr>
                    <th class="id-col">ID</th>
                    <th class="text-col">Texto</th>
                    <th class="cat-col">Categoría</th>
                </tr>
            </thead>
            <tbody>
    `;

    assertions.forEach(a => {
        const catDesc = CATEGORY_MAP[a.categoryId] || `(${a.categoryId})`;
        const textValue = (typeof a.text === 'object' && a.text?.text) ? a.text.text : a.text;
        
        html += `
            <tr>
                <td class="id-col"><span>${a.idAssertion}</span></td>
                <td class="text-col">${textValue || "-"}</td>
                <td class="cat-col">${catDesc}</td>
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

    if (!cid) return alertMessage("Introduce un hash de IPFS", "error");

    alertMessage("Buscando contenido en IPFS...", "info");

    try {
        const res = await fetchWithAuth(`${IPFS_API}/ipfs/${cid}`);
        if (!res.ok) throw new Error("Error al obtener datos de IPFS");

        const data = await res.json();
        if (!data.content) throw new Error("Campo 'content' no encontrado en la respuesta");

        alertMessage("Contenido recuperado.", "primary");

        const box = document.createElement("div");
        box.id = "ipfsContentBox";
        box.className = "post-box dynamic-content";
        box.innerHTML = `<pre class="event-payload-pre">${escapeHTML(data.content)}</pre>`;

        const activeSection = table.closest("section"); // ✅ sección contenedora
        activeSection.appendChild(box); // ✅ dentro de la sección



    } catch (err) {
        console.error(err);

        const box = document.createElement("div");
        box.id = "ipfsContentBox";
        box.className = "post-box";
        box.innerHTML = `<div class="error">Error al obtener el contenido desde IPFS.</div>`;

        table.insertAdjacentElement("afterend", box);
        alertMessage("Error al buscar en IPFS.", "error");
    }
}


//=========================================================
// TX
//=========================================================
async function findTx() {
    const hash = document.getElementById("txHash").value.trim();
    const table = document.getElementById("txTable");
    table.innerHTML = "";

    if (!hash) return alertMessage("Introduce un transaction hash", 'error');
    alertMessage("Buscando transacción...", 'info');

    try {
        const res = await fetchWithAuth(`${TX_API}/blockchain/tx/${hash}`);
        if (!res.ok) throw new Error("Error al obtener la transacción");
        
        const responseData = await res.json();
        // 🎯 CORRECCIÓN APLICADA: Usar el campo 'payload'
        if (!responseData.payload) throw new Error("Payload missing in transaction response."); 
        alertMessage(responseData.payload);
        renderTxTable(responseData.payload);
        alertMessage("Transacción encontrada.", 'primary');
    } catch (err) {
        console.error(err);
        table.innerHTML = "<tbody><tr><td><div class='p-3 text-red-400'>Error al obtener transacción o hash inválido.</div></td></tr></tbody>";
        alertMessage("Error al buscar la transacción.", 'error');
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
                ? `<a href="#" onclick="event.preventDefault(); navigateToBlock(${data.blockNumber})">${data.blockNumber}</a>`
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
        <tr><th>Campo</th><th>Valor</th></tr>
        ${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v ?? ""}</td></tr>`).join("")}
    `;
}

// =========================================================
//Funciones de navegacion
// =========================================================


function navigateTo(section, inputId, value, loadFunction) {
    if (!value) return;

    // Cambiar de sección visualmente
    showSection(section);

    // Poner valor en el input
    const input = document.getElementById(inputId);
    input.value = value;

    // Cargar datos
    loadFunction(value);

    // Guardar estado en historial
    history.pushState(
        { section, inputId, value }, 
        "", 
        `#${section}/${value}`
    );
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

window.onpopstate = function(event) {
    if (!event.state) return;

    const { section, inputId, value } = event.state;

    // No limpiar, solo mostrar
    showSection(section, false);
    document.getElementById(inputId).value = value;

    switch (section) {
        case "orders": loadOrderById(value, false); break; // evita limpiar
        case "tx": findTx(); break;
        case "contract": findPostById(); break;
        case "blocks": findBlock(); break;
        case "consistency": checkOrderConsistency(); break;
    }
};


// ===============================
// 🔹 BLOQUES
// ===============================
async function findBlock() {
    const blockId = document.getElementById("blockId").value.trim();
    const tableContainer = document.getElementById("blockTable");
    tableContainer.innerHTML = "";

    if (!blockId) return alertMessage("Introduce un número o hash de bloque", 'error');
    alertMessage("Buscando bloque...", 'info');

    try {
        const res = await fetchWithAuth(`${TX_API}/blockchain/block/${blockId}`);
        if (!res.ok) throw new Error("Error al obtener el bloque");
        
        const responseData = await res.json();
        if (!responseData.payload) throw new Error("Payload missing in block response."); 

        // 🔹 Renderiza e inserta la tabla
        const blockTable = renderBlockTable(responseData.payload);
        tableContainer.appendChild(blockTable);

        alertMessage("Bloque encontrado.", 'primary');
    } catch (err) {
        console.error(err);
        tableContainer.innerHTML = "<tbody><tr><td><div class='p-3 text-red-400'>Error al obtener bloque o ID/Hash inválido.</div></td></tr></tbody>";
        alertMessage("Error al buscar el bloque.", 'error');
    }
}

function renderBlockTable(data) {
  const container = document.createElement("div");

  // ======= 🧱 Tabla principal del bloque =======
  const blockTable = document.createElement("table");
  blockTable.className = "compact-table";

  const timestamp = Number(data.timestamp);
  const formattedTime = !isNaN(timestamp)
    ? new Date(timestamp * 1000).toLocaleString("es-ES", {
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
    <tr><th>Campo</th><th>Valor</th></tr>
    ${blockRows.map(([k, v]) => `
      <tr>
        <th>${k}</th>
        <td>${v ?? ""}</td>
      </tr>
    `).join("")}
  `;
  container.appendChild(blockTable);

  // ======= 📦 Tabla de transacciones =======
  if (Array.isArray(data.transactions) && data.transactions.length > 0) {
    const txTitle = document.createElement("h3");
    txTitle.textContent = "Transacciones del bloque";
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
            <a href="#" onclick="event.preventDefault(); navigateToTx('${tx.tx_hash}')">
              ${shortHex(tx.tx_hash)}
            </a>
          </td>
          <td>${tx.from}</td>
          <td>${tx.to}</td>
          <td>${tx.value}</td>
          <td>${tx.gas}</td>
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
        return alertMessage("Introduce un contract address o nombre", "error");
    }

    alertMessage("Buscando contrato...", "info");

    try {
        const res = await fetchWithAuth(`${TX_API}/blockchain/post/${postId}`);

        if (!res.ok) throw new Error("Error al obtener Post");

        const responseData = await res.json();

        if (!responseData.post)
            throw new Error("Payload missing in contract response");

        // Renderiza tabla igual que bloque
        const contractPost = renderPost(responseData.post);
        tableContainer.appendChild(contractPost);

        alertMessage("Contrato encontrado.", "primary");

    } catch (err) {
        console.error(err);
        tableContainer.innerHTML =
            "<tbody><tr><td><div class='p-3 text-red-400'>Error al obtener el contrato o ID inválido.</div></td></tr></tbody>";
        alertMessage("Error al buscar contrato.", "error");
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
        ["document", post.cid]
    ];

    postTable.innerHTML = `
        <tr><th>Campo</th><th>Valor</th></tr>
        ${rows.map(([k, v]) => {

            // Si es CID, lo convertimos en enlace
            if (k === "document" && v) {
                v = `<a href="#" 
                        onclick="event.preventDefault(); navigateToIpfs('${v}'); return false;">
                        ${v}
                    </a>`;
            }

            return `
                <tr>
                    <th>${k}</th>
                    <td>${v ?? ""}</td>
                </tr>
            `;
        }).join("")}
    `;

    container.appendChild(postTable);

    // ===== Árbol de Aserciones =====
    if (Array.isArray(post.asertions) && post.asertions.length > 0) {
        const assertionsTitle = document.createElement("h3");
        assertionsTitle.textContent = `Aserciones (${post.asertions.length})`;
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
            headerText.textContent = `Aserción ${i + 1} Digest: ${a.hash_asertion?.digest ?? ""}`;
            header.appendChild(headerText);

            // Contenido colapsable
            const content = document.createElement("div");
            content.className = "assertion-content";

            // Tabla categoría
            const assertionTable = document.createElement("table");
            assertionTable.className = "compact-table";
            assertionTable.innerHTML = `
                <tr><th>Categoría</th><td>${a.categoryId}</td></tr>
            `;
            content.appendChild(assertionTable);

            // Validaciones
            if (Array.isArray(a.validations) && a.validations.length > 0) {
                const validationsTitle = document.createElement("h4");
                validationsTitle.textContent = `Validaciones (${a.validations.length})`;
                content.appendChild(validationsTitle);

                a.validations.forEach((v) => {
                    const validationTable = document.createElement("table");
                    validationTable.className = "compact-table";
                    validationTable.innerHTML = `
                        <tr><th>Validator</th><td>${v.validatorAddress}</td></tr>
                        <tr><th>Dominio</th><td>${v.domain}</td></tr>
                        <tr><th>Reputación</th><td>${v.reputation}</td></tr>
                        <tr><th>Veredicto</th><td>${mapVeredict(v.veredict)}</td></tr>
                        <tr><th>cid</th>
                            <td>
                                ${v.cid 
                                    ? `<a href="#" onclick="event.preventDefault(); navigateToIpfs('${v.cid}'); return false;">
                                            ${v.cid}
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

    // Reemplaza contenido
    const postTableContainer = document.getElementById("postTable");
    if (postTableContainer) {
        postTableContainer.innerHTML = "";
        postTableContainer.appendChild(container);
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
                Comprobando consistencia para Order ID: ${orderId}...
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

    } catch (error) {
        console.error('Error al verificar la consistencia:', error);

        table.innerHTML = `
            <tr>
                <td colspan="5" class="error">
                    Error al conectar con el servicio local.<br>
                    Detalle: ${error.message}
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
                <td>${item.test || ''}</td>
                <td><pre>${String(item.toCompare || '')}</pre></td>
                <td><pre>${String(item.compared || '')}</pre></td>
                <td>
                    <span class="${resultClass}">
                        ${item.result || ''}
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

    if (!url) {
        alert('Introduce una URL para importar');
        return;
    }

    try {
        // Llamada POST al endpoint
        
        const response = await fetchWithAuth(`${API}/extract_text_from_url`, {
            method: 'POST',
            headers: {
                'Accept': 'application/json'
            },
            body: JSON.stringify({ url })
        });

        if (!response.ok) {
            throw new Error(`Error en la solicitud: ${response.status}`);
        }

        const data = await response.json();

        // Coloca el texto recibido en el textarea
        newsText.value = data.text || '';

    } catch (err) {
        console.error(err);
        alert('Error al importar la noticia. Revisa la consola.');
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
        alertMessage("Error de conexión con el servidor de identidad", "error");
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

    document.getElementById("btn-generateAssertions").addEventListener("click", async () => {
        const text = document.getElementById("newsText").value.trim();
        if (!text) {
            alertMessage("Debes escribir o cargar una noticia", "warning");
            return;
        }
        alertMessage("Generando aserciones...", "info");
        const assertions = await generateAssertionsFromText(text);
        const container = document.getElementById("news-assertions-container");
        renderEditableAssertionsTable(container, assertions);
        alertMessage("Aserciones generadas", "success");
    });

    // 4. El resto de tus Listeners (Orders, TX, IPFS...)
    document.getElementById('btn-findOrder').addEventListener('click', findOrder);
    document.getElementById('btn-listOrders').addEventListener('click', listOrders);
    document.getElementById("btn-findTx").addEventListener("click", findTx);
    document.getElementById("btn-findBlock").addEventListener("click", findBlock);
    document.getElementById("btn-findPost").addEventListener("click", findPostById);
    document.getElementById("btn-checkConsistency").addEventListener("click", checkOrderConsistency);
    document.getElementById("btn-findIpfs").addEventListener("click", findIpfs);

    // 5. Initial view
    showSection('news');
}