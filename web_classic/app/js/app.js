const API = "/api";
const MAX_EVENTS_ROWS = 15;

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
    }
}

// Publicar nueva noticia
async function publishNew() {
    const text = document.getElementById("newsText").value;
    if (!text.trim()) return alert("Introduce un texto para verificar.");
    const res = await fetch(`${API}/publishNew`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text})
    });
    const data = await res.json();
    alert(`✅ Order creada: ${data.order_id}\nEstado: ${data.status}`); 
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

    const res = await fetch(`${API}/orders/${orderId}`);
    const data = await res.json();

    const tabs = document.getElementById("orderTabs");
    const detailsContainer = document.getElementById("fixedDetailsContainer");
    const tabContent = document.getElementById("tabContent"); 

    tabs.innerHTML = "";
    detailsContainer.innerHTML = "";
    tabContent.innerHTML = ""; 

    renderDetails(detailsContainer, data); 

    const sections = [
        {name: "Asertions", data: data.assertions || []},
        {name: "Documento", data: data.document || null},
        {name: "Validations", data: data.validations || {}}
    ];

    try {
        const resEv = await fetch(`${API}/news/${orderId}/events`);
        
        if (resEv.ok) {
            const ev = await resEv.json();
            sections.push({name: "Eventos", data: ev});
        } else {
            console.error(`Error al cargar eventos: ${resEv.status} ${resEv.statusText}`);
        }
    } catch (error) {
        console.error("Error de red al intentar cargar eventos:", error);
    }
    
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

function renderDetails(container, data) {
    container.innerHTML = '<h3>Detalles de la Orden</h3>';
    const simpleEntries = Object.entries(data).filter(([k, v]) => typeof v !== "object" || v === null);

    if (simpleEntries.length) {
        const formattedEntries = simpleEntries.map(([k, v]) => {
            let displayValue = v;
            
            if (k.toLowerCase().includes('timestamp') && v) {
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
            <tbody>${data.map(r=>`<tr>${keys.map(k=>k==="order_id"?`<td><a href="#" onclick="loadOrderById('${r[k]}')">${r[k]}</a></td>`:`<td>${r[k]}</td>`).join("")}</tr>`).join("")}</tbody>
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

// Validations en árbol con colores según resultado
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
                        <th>Validator</th>
                        <th>Resultado</th>
                        <th>Descripción</th>
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
                <td>${validator}</td>
                <td class="${resultClass}"><b>${info.approval}</b></td> 
                <td>${descriptionText}</td> 
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

function loadOrderById(orderId){
    document.getElementById("orderId").value = orderId;
    showSection("orders");
    findOrder();
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
