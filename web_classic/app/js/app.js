const API = "/api";
const MAX_EVENTS_ROWS = 15;
const POLLING_DURATION = 20000; // 20 segundos
const POLLING_INTERVAL = 1000; // 1 segundo

// Variable global para almacenar los datos de la última orden cargada
let currentOrderData = {};

// --- Funciones de Lógica de la Aplicación ---

// Mostrar sección activa
function showSection(section) {
    // 1. Ocultar todas las secciones
    document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
    
    // 2. Mostrar la sección solicitada
    const targetSection = document.getElementById(section);
    if(targetSection) {
        targetSection.classList.add("active");
    } else {
        console.error(`Sección con ID "${section}" no encontrada.`);
    }

    // 3. Limpiar contenido dinámico al cambiar de sección
    if (section === 'orders') {
        document.getElementById("fixedDetailsContainer").innerHTML = '';
        document.getElementById("orderTabs").innerHTML = '';
        document.getElementById("tabContent").innerHTML = '';
        // Reiniciar datos al salir de la vista de órdenes
        currentOrderData = {}; 
    }
}

// NUEVA FUNCIÓN: Inicia el sondeo de la orden
async function pollOrder(orderId, startTime) {
    const start = startTime || Date.now();
    
    // 1. Carga la orden (en modo no-cleanup/polling)
    await loadOrderById(orderId, false); 
    
    const detailsContainer = document.getElementById("fixedDetailsContainer");
    const statusElement = detailsContainer.querySelector('.status-value');
    let currentStatus = statusElement ? statusElement.getAttribute('data-status') : 'UNKNOWN';

    // 2. Comprobar si se cumple la condición de parada o tiempo límite
    if (currentStatus === 'VALIDATED' || (Date.now() - start > POLLING_DURATION)) {
        // Detener el parpadeo si existe
        if (statusElement) {
            statusElement.classList.remove('polling', 'blinking');
        }
        console.log(`Polling finalizado para ${orderId}. Estado: ${currentStatus}`);
        
        // Cargar los datos finales de las pestañas tras la validación
        if (currentStatus === 'VALIDATED') {
            await loadOrderById(orderId, true); 
        }
        
        return; 
    }

    // 3. Continuar el sondeo
    setTimeout(() => pollOrder(orderId, start), POLLING_INTERVAL);
}

// Publicar nueva noticia
async function publishNew() {
    const text = document.getElementById("newsText").value;
    if (!text.trim()) return alert("Introduce un texto para verificar.");
    
    // 1. Mostrar loading o pre-estado 
    showSection('orders');
    document.getElementById("orderId").value = "Publicando...";
    
    const res = await fetch(`${API}/publishNew`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text})
    });
    
    if (!res.ok) {
        return alert("Error al publicar la noticia. Inténtalo de nuevo.");
    }
    
    const data = await res.json();
    const newOrderId = data.order_id;

    // 2. Iniciar el sondeo y mostrar la vista de la orden
    document.getElementById("orderId").value = newOrderId;
    pollOrder(newOrderId);
}

// Buscar verificaciones previas
async function findPrevious() {
    const text = document.getElementById("newsText").value;
    if (!text.trim()) return alert("Introduce un texto a buscar.");
    const res = await fetch(`${API}/find-order-by-text`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text})
    });
    const data = await res.json();
    renderTableData(document.getElementById("findResults"), data); 
}

// Listar todas las orders
async function listOrders() {
    const res = await fetch(`${API}/news`);
    const data = await res.json();
    
    const tabs = document.getElementById("orderTabs");
    const detailsContainer = document.getElementById("fixedDetailsContainer");
    const tabContent = document.getElementById("tabContent");
    
    tabs.innerHTML = "";
    detailsContainer.innerHTML = "";
    tabContent.innerHTML = "";
    
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

// Buscar una order por ID
async function findOrder() {
    const orderId = document.getElementById("orderId").value.trim();
    if (!orderId) return alert("Introduce un order_id.");
    
    // Llama a la función central de carga
    await loadOrderById(orderId, true);
}

// FUNCIÓN CENTRAL DE CARGA Y RENDERIZADO (Con manejo de errores y refactorizada)
async function loadOrderById(orderId, cleanup = true) {
    const tabs = document.getElementById("orderTabs");
    const detailsContainer = document.getElementById("fixedDetailsContainer");
    const tabContent = document.getElementById("tabContent"); 
    
    // Limpiar contenedores al inicio de la búsqueda (si es la primera carga)
    if (cleanup) {
        tabs.innerHTML = "";
        detailsContainer.innerHTML = "";
        tabContent.innerHTML = ""; 
    }

    try {
        const res = await fetch(`${API}/orders/${orderId}`);

        if (!res.ok) {
            // Si la respuesta no es OK (404, 500, etc.)
            const errorText = await res.text();
            detailsContainer.innerHTML = `<div style="color: red; padding: 10px; border: 1px solid red; border-radius: 4px;">
                Error ${res.status}: No se pudo encontrar la orden con ID: <strong>${orderId}</strong>.
                <br>Mensaje del servidor: ${errorText || 'Error desconocido'}.
            </div>`;
            tabs.innerHTML = '';
            tabContent.innerHTML = '';
            return; // Detener la ejecución
        }

        // Si el estado es 304 (Not Modified), el cuerpo es vacío y JSON.parse fallaría.
        // Solo intentamos parsear si el estado no es 304.
        let data;
        if (res.status !== 304) {
             data = await res.json();
             currentOrderData = data; // Almacenar los datos más recientes
        } else {
            // Usar los datos de la última carga si es 304 (polling)
            data = currentOrderData; 
            if (!data.order_id) {
                 // Si no hay datos previos (lo que puede ocurrir en un 304 inicial)
                 return;
            }
        }
        
        // El renderizado de detalles siempre ocurre
        renderDetails(detailsContainer, data); 

        // Si es la primera carga (cleanup=true) o si los datos se han modificado, creamos/actualizamos las pestañas
        if (cleanup || res.status !== 304) {
            
            // 1. Obtener datos de Eventos (Se hace siempre porque los eventos cambian a menudo)
            let eventsData = [];
            try {
                const resEv = await fetch(`${API}/news/${orderId}/events`);
                if (resEv.ok) {
                    eventsData = await resEv.json();
                } else {
                    console.error(`Error al cargar eventos: ${resEv.status} ${resEv.statusText}`);
                }
            } catch (error) {
                console.error("Error de red al intentar cargar eventos:", error);
            }

            const sections = [
                {name: "Asertions", data: data.assertions || []},
                {name: "Documento", data: data.document || null},
                {name: "Validations", data: data.validations || {}},
                {name: "Eventos", data: eventsData} 
            ];

            // FIX: Si cleanup=true O si el contenedor de pestañas está vacío, se crean las pestañas
            const shouldCreateTabs = cleanup || tabs.children.length === 0;

            if (shouldCreateTabs) {
                tabs.innerHTML = '';
                sections.forEach((s, i) => {
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
                // En modo polling (cleanup=false) y tabs ya creadas, solo refrescar el contenido de la pestaña activa
                const activeTabButton = tabs.querySelector('.activeTab');
                if (activeTabButton) {
                    const tabName = activeTabButton.innerText;
                    
                    // Buscar la sección de datos correcta (incluyendo la nueva data de eventos)
                    const currentSection = sections.find(s => s.name === tabName);

                    if (currentSection) {
                        renderTabContent(tabName, currentSection.data, data.assertions);
                    }
                }
            }
        }
    } catch (error) {
        // Manejar errores de red o errores al parsear JSON
        detailsContainer.innerHTML = `<div style="color: red; padding: 10px; border: 1px solid red; border-radius: 4px;">
            Error de Conexión o JSON Inválido: ${error.message}.
        </div>`;
        tabs.innerHTML = '';
        tabContent.innerHTML = '';
        console.error("Error en loadOrderById (Catch Block):", error);
    }
}

// Renderizar contenido de pestañas
function renderTabContent(tabName, data, assertions=[]) {
    const container = document.getElementById("tabContent"); 
    container.innerHTML = ""; 
    
    switch(tabName) {
        case "Documento":
            container.innerHTML = `<pre>${JSON.stringify(data,null,2)}</pre>`;
            break;
        case "Validations":
            renderValidationsTree(container, data, assertions);
            break;
        case "Eventos":
            renderEventsTable(container, data);
            break;
        case "Asertions":
            renderTableData(container, data);
            break;
        default:
            container.innerHTML = `<pre>${JSON.stringify(data,null,2)}</pre>`;
    }
}

// MODIFICADA: Aplica estilos de color y parpadeo al status
function renderDetails(container, data) {
    container.innerHTML = '<h3>Detalles de la Orden</h3>';
    // Filtramos solo propiedades planas para el summary (excluyendo objects/arrays grandes)
    const simpleEntries = Object.entries(data).filter(([k, v]) => typeof v !== "object" || v === null); 

    if (simpleEntries.length) {
        const formattedEntries = simpleEntries.map(([k, v]) => {
            let displayValue = v;
            let valueClass = '';
            
            if (k.toLowerCase() === 'status') {
                // Lógica de color y animación
                valueClass = (v !== 'VALIDATED') ? 'polling blinking' : 'validated';
                // Añadir el valor como atributo para que pollOrder pueda leerlo
                displayValue = `<span class="status-value ${valueClass}" data-status="${v}">${v}</span>`;
            } else if (k.toLowerCase().includes('timestamp') && v) {
                displayValue = formatDate(v);
            }
            
            const keyDisplay = k.toLowerCase().includes('orderid') ? `<strong>${k}</strong>` : k;

            return `<tr><th>${keyDisplay}</th><td>${displayValue}</td></tr>`;
        });
        
        const rows = formattedEntries.join("");
        container.innerHTML += `<div class="order-details-summary"><table>${rows}</table></div><hr/>`;

    } else {
        container.innerHTML += `<pre>${JSON.stringify(data, null, 2)}</pre><hr/>`;
    }
}

// Renderiza tablas genéricas y maneja el clic en order_id
function renderTableData(container, data){
    if(!data?.length){ container.innerHTML="<p>No hay datos</p>"; return; }
    const keys = Object.keys(data[0]);
    container.innerHTML = `
        <table>
            <thead><tr>${keys.map(k=>`<th>${k}</th>`).join("")}</tr></thead>
            <tbody>${data.map(r=>`<tr>${keys.map(k=>k==="order_id"?`<td><a href="#" onclick="navigateToOrderDetails('${r[k]}')">${r[k]}</a></td>`:`<td>${r[k]}</td>`).join("")}</tr>`).join("")}</tbody>
        </table>
    `;
}

// Eventos con tooltip y fecha
function renderEventsTable(container, events){
    if(!events?.length){ 
        container.innerHTML="<p>No hay eventos</p>"; 
        return; 
    }

    const limitedEvents = events.slice(0, MAX_EVENTS_ROWS); 

    const rows = limitedEvents.map(e => {
        const payloadString = JSON.stringify(e.payload, null, 2);
        const visiblePayload = payloadString.substring(0, 15) + '...';

        return `<tr>
            <td>${e.action}</td>
            <td>${e.topic}</td>
            <td>${formatDate(e.timestamp)}</td>
            
            <td class="tooltip" title="${payloadString}"> 
                ${visiblePayload}
                
                <span class="tooltiptext">${payloadString}</span> 
            </td>
        </tr>`;
    }).join("");

    container.innerHTML = `
        <h3>Eventos (Últimos ${limitedEvents.length} de ${events.length})</h3>
        <table>
            <thead>
                <tr>
                    <th>Acción</th>
                    <th>Topic</th>
                    <th>Fecha</th>
                    <th>Payload</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;
}

// MODIFICADA: Aplicación de clases CSS a las columnas
function renderValidationsTree(container, validations, assertions){
    if(!validations || Object.keys(validations).length===0){ container.innerHTML="<p>No hay validaciones</p>"; return; }
    
    let html = "";
    
    for(const [id, valObj] of Object.entries(validations)){
        const atext = assertions.find(a=>a.idAssertion===id)?.text || "(sin texto)";
        const approvalList = Object.values(valObj).map(v=>v.approval === "TRUE");
        const allTrue = approvalList.every(v=>v===true);
        const allFalse = approvalList.every(v=>v===false);
        const status = allTrue?"TRUE":allFalse?"FALSE":"TRUE/FALSE";
        
        html += `<details><summary style="color:${allTrue?'green':allFalse?'red':'orange'}"><b>${id}</b> - ${atext} → <b>${status}</b></summary>
            <table>
                <thead>
                    <tr>
                        <th class="validator-col">Validator</th>
                        <th class="validator-col">Resultado</th>
                        <th class="description-col">Descripción</th>
                        <th>Tx Hash</th>
                    </tr>
                </thead>
                <tbody>`;
        for(const [validator, info] of Object.entries(valObj)){
            const resultClass = info.approval === "TRUE" ? 'true' : 'false';
            let descriptionText = info.text;

            const jsonMatch = info.text.match(/```json\s*([\s\S]*?)\s*```/);
            if (jsonMatch && jsonMatch[1]) {
                try {
                    const jsonPayload = JSON.parse(jsonMatch[1]);
                    descriptionText = jsonPayload.descripcion || descriptionText;
                } catch (e) {
                    console.error("Error al parsear el JSON de validación:", e);
                }
            } 
            else {
                const plaintextMatch = info.text.match(/(?:resultado:\s*(?:TRUE|FALSE|UNKNOWN)\s*descripcion:\s*)([\s\S]*)/i);
                
                if (plaintextMatch && plaintextMatch[1]) {
                    descriptionText = plaintextMatch[1].trim();
                } else {
                    descriptionText = descriptionText.replace(/Resultado:\s*(TRUE|FALSE|UNKNOWN)\s*/i, '')
                                                 .replace(/Descripción:\s*/i, '')
                                                 .replace(/Descripci(on|ón):\s*/i, '')
                                                 .trim();
                }
            }
            
            descriptionText = descriptionText.replace(/\n/g, '<br>');

            html += `<tr>
                <td class="validator-col">${validator}</td>
                <td class="validator-col ${resultClass}"><b>${info.approval}</b></td> 
                <td class="description-col">${descriptionText}</td> 
                <td>${info.tx_hash}</td>
            </tr>`;
        }
        html += `</tbody></table></details>`;
    }
    container.innerHTML = html;
}

function formatDate(ts){
    const timestampValue = parseFloat(ts); 
    if (isNaN(timestampValue) || timestampValue === 0) { return "N/A"; }
    const milliseconds = timestampValue * 1000;
    const d = new Date(milliseconds);
    if (isNaN(d.getTime())) { return "Fecha Inválida"; }
    return d.toISOString().replace("T"," ").split(".")[0];
}

// Función auxiliar para navegar y cargar detalles (evita la recursión)
function navigateToOrderDetails(orderId){
    document.getElementById("orderId").value = orderId;
    showSection("orders");
    loadOrderById(orderId, true);
}

// --- Lógica de Inicialización y Escuchadores de Eventos ---

document.addEventListener('DOMContentLoaded', () => {
    // Navegación
    document.getElementById('nav-news').addEventListener('click', () => showSection('news'));
    document.getElementById('nav-orders').addEventListener('click', () => showSection('orders'));
    
    // Botones de la sección 'news'
    document.getElementById('btn-publishNew').addEventListener('click', publishNew);
    document.getElementById('btn-findPrevious').addEventListener('click', findPrevious);

    // Botones de la sección 'orders'
    document.getElementById('btn-findOrder').addEventListener('click', findOrder);
    document.getElementById('btn-listOrders').addEventListener('click', listOrders);

    // Mostrar la sección 'news' por defecto al cargar
    showSection('news');
});