// =========================================================
// UTILIDAD: Reemplazo de alert() con UI no bloqueante
// =========================================================
function alertMessage(message, type = 'info') {
    const colorMap = {
        'info': 'bg-blue-500',
        'primary': 'bg-teal-500',
        'error': 'bg-red-500'
    };
    const container = document.createElement('div');
    container.textContent = message;
    container.className = `fixed top-20 right-4 p-4 rounded-lg shadow-xl text-white ${colorMap[type] || colorMap.info} text-sm transition-opacity duration-300 opacity-0`;
    document.body.appendChild(container);

    setTimeout(() => {
        container.classList.add('opacity-100');
    }, 50);

    setTimeout(() => {
        container.classList.remove('opacity-100');
        container.classList.add('opacity-0');
        setTimeout(() => container.remove(), 300);
    }, 3000);
}


// =========================================================
// CONFIGURACIÓN GLOBAL
// =========================================================
const API = "/api";
const TX_API = "/ethereum";

const MAX_EVENTS_ROWS = 15;
const POLLING_DURATION = 20000; // 20 segundos
const POLLING_INTERVAL = 1000;  // 1 segundo

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

// Variable global para almacenar la última orden cargada
let currentOrderData = {};

// =========================================================
// UTILIDADES
// =========================================================

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
        case 1: return "APROBADA";
        case 2: return "RECHAZADA";
        case 0: return "DESCONOCIDO";
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

function navigateToOrderDetails(orderId){
    document.getElementById("orderId").value = orderId;
    showSection("orders");
    loadOrderById(orderId, true);
}

// =========================================================
// SECCIÓN Y NAVEGACIÓN
// =========================================================
function showSection(section) {
    document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
    const targetSection = document.getElementById(section);
    if(targetSection) targetSection.classList.add("active");
    else console.error(`Sección con ID "${section}" no encontrada.`);
    
    // Update nav button styles (using generic classes for separation)
    document.querySelectorAll(".nav-button").forEach(button => {
        if (button.id === `nav-${section}`) {
            button.classList.remove('bg-gray-700', 'hover:bg-primary');
            button.classList.add('bg-primary', 'hover:bg-teal-700');
        } else {
            button.classList.add('bg-gray-700', 'hover:bg-primary');
            button.classList.remove('bg-primary', 'hover:bg-teal-700');
        }
    });

    if (section === 'orders') {
        document.getElementById("fixedDetailsContainer").innerHTML = '<p class="text-sm text-gray-400">Detalles de la Orden seleccionada aparecerán aquí.</p>';
        document.getElementById("orderTabs").innerHTML = '';
        document.getElementById("tabContent").innerHTML = '<p class="text-gray-300">Contenido de la pestaña activa.</p>';
        currentOrderData = {}; 
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

// =========================================================
// OPERACIONES DE NEWS
// =========================================================
async function publishNew() {
    const text = document.getElementById("newsText").value.trim();
    if (!text) return alertMessage("Introduce un texto para verificar.", 'error');

    showSection('orders');
    document.getElementById("orderId").value = "Publicando...";

    const res = await fetch(`${API}/publishNew`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
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

async function findPrevious() {
    const text = document.getElementById("newsText").value.trim();
    if (!text) return alertMessage("Introduce un texto a buscar.", 'error');
    
    alertMessage("Buscando verificaciones previas...", 'info');
    
    try {
        const res = await fetch(`${API}/find-order-by-text`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
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
async function listOrders() {
    alertMessage("Listando todas las órdenes...", 'info');
    try {
        const res = await fetch(`${API}/news`);
        if (!res.ok) throw new Error("Error al obtener la lista de órdenes.");
        
        const data = await res.json();
        
        const tabs = document.getElementById("orderTabs");
        const detailsContainer = document.getElementById("fixedDetailsContainer");
        const tabContent = document.getElementById("tabContent");
        tabs.innerHTML = detailsContainer.innerHTML = tabContent.innerHTML = "";
        
        // Renderizar el botón 'Lista Orders' como una pestaña activa temporal
        const btn = document.createElement("button");
        btn.innerText = "Lista Orders";
        btn.classList.add("activeTab");
        
        // Replicar la funcionalidad de la pestaña activa (aunque solo haya una)
        btn.onclick = () => {
            document.querySelectorAll("#orderTabs button").forEach(b => b.classList.remove("activeTab"));
            btn.classList.add("activeTab");
            renderTableData(tabContent, data); 
        };
        tabs.appendChild(btn);
        
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
        const res = await fetch(`${API}/orders/${orderId}`);
        
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
                const resEv = await fetch(`${API}/news/${orderId}/events`);
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
                if (lit === "APROBADA") approved++;
                else if (lit === "RECHAZADA") rejected++;
                else if (lit === "DESCONOCIDO") unknownCount++;
            });
            const known = approved - rejected;
            
            if (known > 0)  trueAssertions++;
            else if (known < 0) falseAssertions++;
        }
    }
    
    let percentTrue=0;
    let percentFalse=0;
    const knownAssertions = totalAssertions - unknownCount;
    if (knownAssertions !== 0) {
        percentTrue = (trueAssertions / knownAssertions) * 100;
        percentFalse = (falseAssertions / knownAssertions) * 100;
    } 
    
    let overallTag = "Sin Validaciones", overallClass = "unknown";
    if (totalAssertions > 0) {
        if (trueAssertions > falseAssertions && trueAssertions > 0) { 
            overallTag = "Mayormente Cierta"; 
            overallClass = "true-news"; 
        }
        else if (falseAssertions > trueAssertions && falseAssertions > 0) { 
            overallTag = "Mayormente Falsa"; 
            overallClass = "fake-news"; 
        }
        else if (trueAssertions === falseAssertions && knownAssertions > 0) {
             overallTag = "Validación Mixta"; 
             overallClass = "partial-news";
        }
        else { overallTag = "Pendiente / Indefinido"; overallClass = "unknown"; }
    }
    
    // --- Contenido de las subpestañas
    const detailsHtml = `<table class="compact-table">` +
        Object.entries(data)
              .filter(([k, v]) => k !== "_id" && k !== "document" && k !== "assertions" && k !== "validations" && k !== "validators" && k !== "text" && k !== "status" && k !== "validators_pending")
              .map(([k, v]) => {
                  if (k === "text" && typeof v === "object" && v?.text) v = v.text;
                  return `<tr><th>${k}</th><td>${v || ''}</td></tr>`;
              }).join('') +
        `</table>`;

    const summaryHtml = `<table class="compact-table">
        <tr><th>ID de Orden</th><td>${data.order_id || "N/A"}</td></tr>
        <tr><th>Estado General</th><td class="status-value ${overallClass}" data-status="${data.status || 'UNKNOWN'}">${overallTag}</td></tr>
        <tr><th>Estado de Procesamiento</th><td>${data.status || "N/A"}</td></tr>
        <tr><th>Noticia (Resumen)</th><td>${data.text || "N/A"}</td></tr>
        <tr><th>Validators Pendientes</th><td>${data.validators_pending ?? 0}</td></tr>
        <tr><th>Aserciones Ciertas</th><td class="true-news">${trueAssertions} (${percentTrue.toFixed(1)}%)</td></tr>
        <tr><th>Aserciones Falsas</th><td class="fake-news">${falseAssertions} (${percentFalse.toFixed(1)}%)</td></tr>
        <tr><th>Validaciones Desconocidas</th><td class="unknown">${unknownCount}</td></tr>
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

    // --- Lógica de subpestañas
    const subTabs = container.querySelectorAll(".subTab");
    subTabs.forEach(btn => {
        btn.addEventListener('click', () => {
            container.querySelectorAll(".subTab").forEach(b => b.classList.remove('activeSubTab', 'text-primary'));
            btn.classList.add('activeSubTab', 'text-primary');
            container.querySelectorAll("#summaryTab, #detailsTab").forEach(div => div.style.display = 'none');
            container.querySelector(`#${btn.getAttribute('data-target')}`).style.display = 'block';
        });
    });
    // Set initial active state for styling
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
        // Texto de la aserción
        let assertionText = assertions.find(a => a.idAssertion === assertionId)?.text || "(Asersión sin texto)";
        if (typeof assertionText === 'object' && assertionText !== null && assertionText.text) {
            assertionText = assertionText.text;
        }

        // Determinar status global de esta aserción
        const literals = Object.values(validatorsObj).map(v => getValidationLiteral(v.approval));
        const known = literals.filter(v => v !== "DESCONOCIDO");
        const approvedCount = known.filter(v => v === "APROBADA").length;
        const rejectedCount = known.filter(v => v === "RECHAZADA").length;

        let status, color;
        if (approvedCount > rejectedCount) { status = "APROBADA"; color = "#10B981"; }
        else if (rejectedCount > approvedCount) { status = "RECHAZADA"; color = "#EF4444"; }
        else if (known.length > 0) { status = "MIXTA / EMPATE"; color = "#F59E0B"; }
        else { status = "PENDIENTE"; color = "#6B7280"; }


        // Generar tabla de validators compacta
        let tableRows = "";
        for (const [validator, info] of Object.entries(validatorsObj)) {
            const lit = getValidationLiteral(info.approval);
            let cls = 'unknown';
            if (lit === "APROBADA") cls = "true-news";
            else if (lit === "RECHAZADA") cls = "fake-news";
            
            // Descripción formateada
            let desc = info.text || "";
            if (typeof desc === 'object') desc = JSON.stringify(desc, null, 2);
            
            tableRows += `<tr>
                <td class="text-primary">${info.validator_alias || validator}</td>
                <td class="${cls}"><b>${lit}</b></td>
                <td><pre class="event-payload-pre mt-0">${desc}</pre></td>
                <td><span class="text-xs text-gray-500">${info.tx_hash ? info.tx_hash.substring(0, 10) + '...' : ""}</span></td>
            </tr>`;
        }

        html += `<details class="p-3 bg-gray-700 rounded-lg mb-3">
            <summary class="cursor-pointer" style="color:${color}; font-weight:bold; font-size:1rem;">
                ${assertionId.substring(0, 8)}... - ${assertionText} → <span style="font-size:0.9rem;">(${approvedCount} A / ${rejectedCount} R)</span>
            </summary>
            <div class="mt-3">
                <table class="compact-table">
                    <thead>
                        <tr>
                            <th>Validator</th>
                            <th>Resultado</th>
                            <th>Descripción</th>
                            <th>Tx Hash</th>
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
    if (!data?.length) {
        container.innerHTML = "<p class='text-gray-400 p-4'>No hay datos disponibles.</p>";
        return;
    }

    const keys = Object.keys(data[0]);
    container.innerHTML = `<table class="compact-table">
        <thead>
            <tr>${keys.map(k => `<th class="uppercase text-xs">${k}</th>`).join("")}</tr>
        </thead>
        <tbody>
            ${data.map(row => {
                return `<tr>${keys.map(k => {
                    let val = row[k];

                    // Resumir campos complejos
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

                    // order_id clicable
                    if (k === "order_id") {
                        return `<td><a href="#" onclick="navigateToOrderDetails('${row[k]}')">${row[k]}</a></td>`;
                    }
                    
                    // Tx Hash (corta)
                    if (k.toLowerCase().includes('hash') && typeof val === 'string' && val.length > 10) {
                        val = val.substring(0, 10) + '...';
                    }

                    return `<td>${val}</td>`;
                }).join("")}</tr>`;
            }).join("")}
        </tbody>
    </table>`;
}

function renderEventsTable(container, events){
    if(!events?.length){ container.innerHTML="<p class='text-gray-400 p-4'>No hay eventos registrados.</p>"; return; }
    const limited = events.slice(0, MAX_EVENTS_ROWS);

    const rows = limited.map(e=>{
        const payloadStr = JSON.stringify(e.payload,null,2);
        
        // El texto visible en la celda será un resumen del JSON
        const visibleSummary = payloadStr.substring(0, 50).trim() + (payloadStr.length > 50 ? '...' : '');

        return `<tr>
            <td class="text-primary">${e.action}</td>
            <td>${e.topic}</td>
            <td>${formatDate(e.timestamp)}</td>
            <td>
                <details class="event-payload-details">
                    <summary>Payload: ${visibleSummary}</summary>
                    <pre class="event-payload-pre">${payloadStr}</pre>
                </details>
            </td>
        </tr>`;
    }).join("");

    container.innerHTML = `
        <h3 class="text-lg font-bold mb-3">Eventos (Últimos ${limited.length} de ${events.length})</h3>
        <table class="compact-table">
            <thead>
                <tr>
                    <th class="uppercase text-xs">Acción</th>
                    <th class="uppercase text-xs">Topic</th>
                    <th class="uppercase text-xs">Fecha</th>
                    <th class="uppercase text-xs">Payload</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>`;
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
        <table class="compact-table">
            <thead>
                <tr>
                    <th class="uppercase text-xs">ID</th>
                    <th class="uppercase text-xs">Texto</th>
                    <th class="uppercase text-xs">Categoría</th>
                </tr>
            </thead>
            <tbody>
    `;

    assertions.forEach(a => {
        const catDesc = CATEGORY_MAP[a.categoryId] || `(${a.categoryId})`;
        const textValue = (typeof a.text === 'object' && a.text?.text) ? a.text.text : a.text;
        
        html += `
            <tr>
                <td><span class="text-xs text-gray-500">${a.idAssertion ? a.idAssertion.substring(0, 8) + '...' : "-"}</span></td>
                <td>${textValue || "-"}</td>
                <td>${catDesc}</td>
            </tr>
        `;
    });

    html += "</tbody></table>";
    container.innerHTML = html;
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
        const res = await fetch(`${TX_API}/tx/${hash}`);
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
        ["blockNumber", data.blockNumber],
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


// ===============================
// 🔹 BLOQUES
// ===============================
async function findBlock() {
    const blockId = document.getElementById("blockId").value.trim();
    const table = document.getElementById("blockTable");
    table.innerHTML = "";

    if (!blockId) return alertMessage("Introduce un número o hash de bloque", 'error');
    alertMessage("Buscando bloque...", 'info');

    try {
        const res = await fetch(`${TX_API}/block/${blockId}`);
        if (!res.ok) throw new Error("Error al obtener el bloque");
        
        const responseData = await res.json();
        // 🎯 CORRECCIÓN APLICADA: Usar el campo 'payload'
        if (!responseData.payload) throw new Error("Payload missing in block response."); 

        renderBlockTable(responseData.payload);
        alertMessage("Bloque encontrado.", 'primary');
    } catch (err) {
        console.error(err);
        table.innerHTML = "<tbody><tr><td><div class='p-3 text-red-400'>Error al obtener bloque o ID/Hash inválido.</div></td></tr></tbody>";
        alertMessage("Error al buscar el bloque.", 'error');
    }
}

function renderBlockTable(apiData) {
  const data = apiData?.payload || apiData || {};
  const blockTable = document.createElement("table");
  blockTable.id = "blockTable";

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

  const rows = [
    ["blockHash", shortHex(data.blockHash)],
    ["timestamp", formattedTime],
    ["miner", data.miner],
    ["transactionCount", data.transactionCount]
  ];

  blockTable.innerHTML = `
    <tr><th>Campo</th><th>Valor</th></tr>
    ${rows
      .map(([k, v]) => `<tr><td>${k}</td><td>${v ?? ""}</td></tr>`)
      .join("")}
  `;
  return blockTable;
}


// =========================================================
// INICIALIZACIÓN
// =========================================================
document.addEventListener('DOMContentLoaded',()=>{
    // Navigation Listeners
    document.getElementById('nav-news').addEventListener('click',()=>showSection('news'));
    document.getElementById('nav-orders').addEventListener('click',()=>showSection('orders'));
    document.getElementById("nav-tx").addEventListener("click", () => showSection("tx"));
    
    // News Listeners
    document.getElementById('btn-publishNew').addEventListener('click',publishNew);
    document.getElementById('btn-findPrevious').addEventListener('click',findPrevious);
    
    // Orders Listeners
    document.getElementById('btn-findOrder').addEventListener('click',findOrder);
    document.getElementById('btn-listOrders').addEventListener('click',listOrders);
    
    // TX Listeners
    document.getElementById("btn-findTx").addEventListener("click", findTx);
    document.getElementById("btn-findBlock").addEventListener("click", findBlock);

    // Initial view
    showSection('news');
});