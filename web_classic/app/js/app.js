// =========================================================
// CONFIGURACIÓN GLOBAL
// =========================================================
const API = "/api";
const MAX_EVENTS_ROWS = 15;
const POLLING_DURATION = 20000; // 20 segundos
const POLLING_INTERVAL = 1000;  // 1 segundo

// Variable global para almacenar la última orden cargada
let currentOrderData = {};

// =========================================================
// UTILIDADES
// =========================================================
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

    if (section === 'orders') {
        document.getElementById("fixedDetailsContainer").innerHTML = '';
        document.getElementById("orderTabs").innerHTML = '';
        document.getElementById("tabContent").innerHTML = '';
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
    if (!text) return alert("Introduce un texto para verificar.");

    showSection('orders');
    document.getElementById("orderId").value = "Publicando...";

    const res = await fetch(`${API}/publishNew`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text})
    });

    if (!res.ok) return alert("Error al publicar la noticia. Inténtalo de nuevo.");
    const data = await res.json();
    const newOrderId = data.order_id;

    document.getElementById("orderId").value = newOrderId;
    pollOrder(newOrderId);
}

async function findPrevious() {
    const text = document.getElementById("newsText").value.trim();
    if (!text) return alert("Introduce un texto a buscar.");
    const res = await fetch(`${API}/find-order-by-text`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text})
    });
    const data = await res.json();
    renderTableData(document.getElementById("findResults"), data); 
}

// =========================================================
// OPERACIONES DE ORDERS
// =========================================================
async function listOrders() {
    const res = await fetch(`${API}/news`);
    const data = await res.json();
    
    const tabs = document.getElementById("orderTabs");
    const detailsContainer = document.getElementById("fixedDetailsContainer");
    const tabContent = document.getElementById("tabContent");
    tabs.innerHTML = detailsContainer.innerHTML = tabContent.innerHTML = "";

    const btn = document.createElement("button");
    btn.innerText = "Lista Orders";
    btn.classList.add("activeTab");
    btn.onclick = () => {
        document.querySelectorAll("#orderTabs button").forEach(b => b.classList.remove("activeTab"));
        btn.classList.add("activeTab");
        renderTableData(tabContent, data); 
    };
    tabs.appendChild(btn);
    renderTableData(tabContent, data);
}

async function findOrder() {
    const orderId = document.getElementById("orderId").value.trim();
    if (!orderId) return alert("Introduce un order_id.");
    await loadOrderById(orderId, true);
}

// =========================================================
// CARGA CENTRAL DE ÓRDENES
// =========================================================
async function loadOrderById(orderId, cleanup = true) {
    const tabs = document.getElementById("orderTabs");
    const detailsContainer = document.getElementById("fixedDetailsContainer");
    const tabContent = document.getElementById("tabContent"); 

    if (cleanup) tabs.innerHTML = detailsContainer.innerHTML = tabContent.innerHTML = "";

    try {
        const res = await fetch(`${API}/orders/${orderId}`);
        if (!res.ok) {
            const errorText = await res.text();
            detailsContainer.innerHTML = `<div style="color:red;padding:10px;border:1px solid red;border-radius:4px;">
                Error ${res.status}: No se pudo encontrar la orden <strong>${orderId}</strong>.<br>
                Mensaje: ${errorText || 'Error desconocido'}
            </div>`;
            tabs.innerHTML = tabContent.innerHTML = '';
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
        detailsContainer.innerHTML = `<div style="color:red;padding:10px;border:1px solid red;border-radius:4px;">
            Error de conexión o JSON inválido: ${error.message}
        </div>`;
        tabs.innerHTML = tabContent.innerHTML = '';
        console.error(error);
    }
}

// =========================================================
// RENDER TAB CONTENT
// =========================================================
function renderTabContent(tabName, data, assertions=[]) {
    const container = document.getElementById("tabContent"); 
    container.innerHTML = ""; 
    
    switch(tabName) {
        case "Documento": container.innerHTML = `<pre>${JSON.stringify(data,null,2)}</pre>`; break;
        case "Validations": renderValidationsTree(container, data, assertions); break;
        case "Eventos": renderEventsTable(container, data); break;
        case "Asertions": renderTableData(container, data); break;
        default: container.innerHTML = `<pre>${JSON.stringify(data,null,2)}</pre>`;
    }
}

// =========================================================
// RENDER DETALLES Y RESUMEN
// =========================================================
// =========================================================
// RENDER DETALLES Y RESUMEN
// =========================================================
// =========================================================
// RENDER DETALLES Y RESUMEN
// =========================================================
// =========================================================
// RENDER DETALLES Y RESUMEN
// =========================================================
function renderDetails(container, data) {
    container.innerHTML = '<h3>Detalles de la Orden</h3>';

    // --- 1. Estadísticas (Resumen)
    let totalAssertions = 0, trueAssertions = 0, falseAssertions = 0, unknownCount = 0;
    if (data.validations) {
        for (const assertionId in data.validations) {
            const validators = data.validations[assertionId];
            let approved = 0, rejected = 0;
            Object.values(validators).forEach(v => {
                const lit = getValidationLiteral(v.approval);
                if (lit === "APROBADA") approved++;
                else if (lit === "RECHAZADA") rejected++;
                else if (lit === "DESCONOCIDO") unknownCount++;
            });
            const known = approved + rejected;
            if (known > 0) {
                totalAssertions++;
                if (rejected === 0) trueAssertions++;
                else falseAssertions++;
            }
        }
    }
    const percentTrue = totalAssertions ? (trueAssertions / totalAssertions) * 100 : 0;
    const percentFalse = totalAssertions ? (falseAssertions / totalAssertions) * 100 : 0;

    let overallTag = "Sin Validaciones", overallClass = "unknown";
    if (totalAssertions > 0) {
        if (percentTrue === 100) { overallTag = "Noticia Cierta"; overallClass = "true-news"; }
        else if (percentFalse === 100) { overallTag = "Fake News"; overallClass = "fake-news"; }
        else { overallTag = `Parcialmente Cierta: ${percentTrue.toFixed(2)}%`; overallClass = "partial-news"; }
    }
    
    // ⬇️ Obtener el texto para el resumen
    let newsText = data.text || (data.document?.text) || "Texto no disponible";
    
    // --- 2. Contenido de las subpestañas (Detalles)
    const detailsHtml = `<table class="compact-table">` +
        Object.entries(data)
            // FILTRA _id y document completamente
            .filter(([k, v]) => k !== "_id" && k !== "document") 
            .map(([k, v]) => {
                let displayValue = v || '';

                // Transformar campos complejos para una visualización simple en la tabla
                switch (k) {
                    case "text":
                        // Usamos un resumen del texto aquí, el completo va a la pestaña Resumen
                        displayValue = String(newsText).length > 150
                            ? String(newsText).substring(0, 150) + "..."
                            : String(newsText);
                        break;
                    case "assertions":
                    case "validators":
                        displayValue = Array.isArray(v) ? `${v.length} elementos` : v;
                        break;
                    case "validations":
                        displayValue = v ? `${Object.keys(v).length} aserciones validadas` : 0;
                        break;
                    case "validators_pending":
                        displayValue = v; 
                        break;
                }

                return `<tr><th>${k}</th><td>${displayValue}</td></tr>`;
            }).join('') +
        `</table>`;

    // --- 3. HTML del Resumen (Añadiendo el texto)
    const summaryHtml = `
        <p><strong>Texto Analizado:</strong></p>
        <div style="border: 1px dashed #ccc; padding: 10px; margin-bottom: 15px; background-color: #f9f9f9;">
            ${newsText}
        </div>
        
        <table class="compact-table">
            <tr><th>Estado General</th><td><span class="${overallClass}">${overallTag}</span></td></tr>
            <tr><th>% Aserciones Ciertas</th><td><span class="${overallClass}">${percentTrue.toFixed(2)}%</span></td></tr>
            <tr><th>% Aserciones Falsas</th><td><span class="${overallClass}">${percentFalse.toFixed(2)}%</span></td></tr>
            <tr><th>Validaciones Desconocidas</th><td><span class="unknown">${unknownCount}</span></td></tr>
            <tr><th>Total Aserciones Evaluadas</th><td>${totalAssertions}</td></tr>
        </table>
    `;

    // --- 4. Subpestañas internas
    container.innerHTML += `
        <div class="sub-tabs">
            <button class="subTab activeSubTab" data-target="summaryTab">Resumen</button>
            <button class="subTab" data-target="detailsTab">Detalles</button>
        </div>
        <div id="summaryTab">${summaryHtml}</div>
        <div id="detailsTab" style="display:none;">${detailsHtml}</div>
    `;

    // --- 5. Lógica de subpestañas
    const subTabs = container.querySelectorAll(".subTab");
    subTabs.forEach(btn => {
        btn.addEventListener('click', () => {
            container.querySelectorAll(".subTab").forEach(b => b.classList.remove('activeSubTab'));
            btn.classList.add('activeSubTab');
            container.querySelectorAll("#summaryTab, #detailsTab").forEach(div => div.style.display = 'none');
            container.querySelector(`#${btn.getAttribute('data-target')}`).style.display = 'block';
        });
    });
}



// =========================================================
// RENDER VALIDATIONS TREE
// =========================================================
// =========================================================
// RENDER VALIDATIONS TREE OPTIMIZADO
// =========================================================
function renderValidationsTree(container, validations, assertions) {
    if (!validations || Object.keys(validations).length === 0) {
        container.innerHTML = "<p>No hay validaciones</p>";
        return;
    }

    let html = "";

    for (const [assertionId, validatorsObj] of Object.entries(validations)) {
        // Texto de la aserción
        let assertionText = assertions.find(a => a.idAssertion === assertionId)?.text || "(sin texto)";
        if (typeof assertionText === 'object' && assertionText !== null && assertionText.text) {
            assertionText = assertionText.text;
        }

        // Determinar status global de esta aserción
        const literals = Object.values(validatorsObj).map(v => getValidationLiteral(v.approval));
        const known = literals.filter(v => v !== "DESCONOCIDO");
        const allApproved = known.length > 0 && known.every(v => v === "APROBADA");
        const allRejected = known.length > 0 && known.every(v => v === "RECHAZADA");
        const status = allApproved ? "APROBADA" : allRejected ? "RECHAZADA" : "MIXTA";
        const color = allApproved ? "green" : allRejected ? "red" : "orange";

        // Generar tabla de validators compacta
        let tableRows = "";
        for (const [validator, info] of Object.entries(validatorsObj)) {
            const lit = getValidationLiteral(info.approval);
            const cls = lit === "APROBADA" ? "true" : lit === "RECHAZADA" ? "false" : "unknown";

            // Descripción formateada
            let desc = info.text || "";
            const jsonMatch = info.text?.match(/```json\s*([\s\S]*?)\s*```/);
            if (jsonMatch && jsonMatch[1]) {
                try { desc = JSON.parse(jsonMatch[1]).descripcion || desc; } catch { }
            } else {
                desc = desc.replace(/^\s*Resultado:\s*(TRUE|FALSE|UNKNOWN|DESCONOCIDA)\s*\n/i, '');
            }
            if (typeof desc === 'object') desc = JSON.stringify(desc, null, 2);
            desc = desc.replace(/\n/g, '<br>');

            tableRows += `<tr>
                <td>${info.validator_alias || validator}</td>
                <td class="${cls}"><b>${lit}</b></td>
                <td>${desc}</td>
                <td>${info.tx_hash || ""}</td>
            </tr>`;
        }

        html += `<details>
            <summary style="color:${color}; font-weight:bold; font-size:0.85rem;">${assertionId} - ${assertionText} → ${status}</summary>
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
        </details>`;
    }

    container.innerHTML = html;
}


// =========================================================
// RENDER TABLAS Y EVENTOS
// =========================================================
function renderTableData(container, data) {
    if (!data?.length) {
        container.innerHTML = "<p>No hay datos</p>";
        return;
    }

    const keys = Object.keys(data[0]);
    container.innerHTML = `<table class="compact-table">
        <thead>
            <tr>${keys.map(k => `<th>${k}</th>`).join("")}</tr>
        </thead>
        <tbody>
            ${data.map(row => {
                return `<tr>${keys.map(k => {
                    let val = row[k];

                    // Resumir campos complejos
                    switch(k) {
                        case "validators_pending":
                            val = row[k]; // mostrar número directamente
                            break;
                        case "assertions":
                            val = Array.isArray(row[k]) ? row[k].length : 0;
                            break;

                        case "validators":
                            val = Array.isArray(row[k]) ? row[k].length : 0;
                            break;
                        case "validations":
                            val = row[k] ? Object.keys(row[k]).length : 0;
                            break;
                        case "text":
                            if (typeof val === "object" && val?.text) val = val.text;
                            break;
                    }

                    // order_id clicable
                    if (k === "order_id") {
                        return `<td><a href="#" onclick="navigateToOrderDetails('${row[k]}')">${row[k]}</a></td>`;
                    }

                    return `<td>${val}</td>`;
                }).join("")}</tr>`;
            }).join("")}
        </tbody>
    </table>`;
}




function renderEventsTable(container, events){
    if(!events?.length){ container.innerHTML="<p>No hay eventos</p>"; return; }
    const limited = events.slice(0, MAX_EVENTS_ROWS);
    const rows = limited.map(e=>{
        const payloadStr = JSON.stringify(e.payload,null,2);
        const visible = payloadStr.substring(0,15)+"...";
        return `<tr>
            <td>${e.action}</td>
            <td>${e.topic}</td>
            <td>${formatDate(e.timestamp)}</td>
            <td class="tooltip" title="${payloadStr}">${visible}<span class="tooltiptext">${payloadStr}</span></td>
        </tr>`;
    }).join("");
    container.innerHTML = `<h3>Eventos (Últimos ${limited.length} de ${events.length})</h3>
        <table><thead><tr><th>Acción</th><th>Topic</th><th>Fecha</th><th>Payload</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// =========================================================
// INICIALIZACIÓN
// =========================================================
document.addEventListener('DOMContentLoaded',()=>{
    document.getElementById('nav-news').addEventListener('click',()=>showSection('news'));
    document.getElementById('nav-orders').addEventListener('click',()=>showSection('orders'));
    document.getElementById('btn-publishNew').addEventListener('click',publishNew);
    document.getElementById('btn-findPrevious').addEventListener('click',findPrevious);
    document.getElementById('btn-findOrder').addEventListener('click',findOrder);
    document.getElementById('btn-listOrders').addEventListener('click',listOrders);
    showSection('news');
});
