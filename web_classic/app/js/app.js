const API = "/api";


// --- Funciones de Lógica de la Aplicación (Copiadas tal cual) ---

// Mostrar sección activa
function showSection(section) {
  document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
  document.getElementById(section).classList.add("active");
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
  const text = document.getElementById("findText").value;
  if (!text.trim()) return alert("Introduce un texto a buscar.");
  const res = await fetch(`${API}/find-order-by-text`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({text})
  });
  const data = await res.json();
  renderTableData(document.getElementById("findResults"), data); // Usamos renderTableData aquí
}

// Listar todas las orders
async function listOrders() {
  const res = await fetch(`${API}/news`);
  const data = await res.json();
  // Crear pestaña Detalles temporal para mostrar lista
  const tabs = document.getElementById("orderTabs");
  tabs.innerHTML = "";
  const btn = document.createElement("button");
  btn.innerText = "Lista Orders";
  btn.classList.add("activeTab");
  btn.onclick = () => {
    document.querySelectorAll("#orderTabs button").forEach(b => b.classList.remove("activeTab"));
    btn.classList.add("activeTab");
    renderTableData(document.getElementById("ordersTable"), data);
  };
  tabs.appendChild(btn);
  renderTableData(document.getElementById("ordersTable"), data);
}

// Buscar una order por ID
async function findOrder() {
  const orderId = document.getElementById("orderId").value.trim();
  if (!orderId) return alert("Introduce un order_id.");

  const res = await fetch(`${API}/orders/${orderId}`);
  const data = await res.json();

  const tabs = document.getElementById("orderTabs");
  tabs.innerHTML = "";

  const sections = [
    {name: "Detalles", data: data},
    {name: "Asertions", data: data.assertions || []},
    {name: "Documento", data: data.document || null},
    {name: "Validations", data: data.validations || {}}
  ];

  try {
    const resEv = await fetch(`${API}/news/${orderId}/events`);
    if (resEv.ok) {
      const ev = await resEv.json();
      sections.push({name: "Eventos", data: ev});
    }
  } catch (_) {}

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
  const table = document.getElementById("ordersTable");
  table.innerHTML = "";
  switch(tabName) {
    case "Documento":
      table.innerHTML = `<pre>${JSON.stringify(data,null,2)}</pre>`;
      break;
    case "Validations":
      renderValidationsTree(data, assertions);
      break;
    case "Eventos":
      renderEventsTable(data);
      break;
    case "Asertions":
      renderTableData(table, data);
      break;
    case "Detalles":
      renderDetails(table, data);
      break;
    default:
      table.innerHTML = `<pre>${JSON.stringify(data,null,2)}</pre>`;
  }
}

function renderDetails(container, data) {
  const simpleEntries = Object.entries(data).filter(([_,v])=>typeof v!=="object");
  if(simpleEntries.length){
    const rows = simpleEntries.map(([k,v])=>`<tr><th>${k}</th><td>${v}</td></tr>`).join("");
    container.innerHTML = `<table>${rows}</table>`;
  } else {
    container.innerHTML = `<pre>${JSON.stringify(data,null,2)}</pre>`;
  }
}

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
function renderEventsTable(events){
  const container = document.getElementById("ordersTable");
  if(!events?.length){ container.innerHTML="<p>No hay eventos</p>"; return; }

  const rows = events.map(e => {
    // 1. Convertir el objeto payload a una cadena JSON legible
    const payloadString = JSON.stringify(e.payload, null, 2);
    
    // 2. Truncar la cadena para la visualización en la tabla
    const truncatedPayload = payloadString.substring(0, 50) + 
                              (payloadString.length > 50 ? '...' : '');

    return `<tr>
      <td>${e.action}</td>
      <td>${formatDate(e.timestamp)}</td>
      <td class="tooltip">
        ${truncatedPayload}
                <span class="tooltiptext">${payloadString}</span> 
      </td>
    </tr>`;
  }).join("");

  container.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Acción</th>
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
function renderValidationsTree(validations, assertions){
  const container = document.getElementById("ordersTable");
  if(!validations || Object.keys(validations).length===0){ container.innerHTML="<p>No hay validaciones</p>"; return; }
  let html = "";
  for(const [id, valObj] of Object.entries(validations)){
    const atext = assertions.find(a=>a.idAssertion===id)?.text || "(sin texto)";
    const approvalList = Object.values(valObj).map(v=>v.approval === "TRUE");
    const allTrue = approvalList.every(v=>v===true);
    const allFalse = approvalList.every(v=>v===false);
    const status = allTrue?"TRUE":allFalse?"FALSE":"TRUE/FALSE";
    const statusClass = allTrue?"true":allFalse?"false":"mixed";

    html += `<details><summary style="color:${allTrue?'green':allFalse?'red':'orange'}"><b>${id}</b> - ${atext} → <b>${status}</b></summary>
      <table><thead><tr><th>Validator</th><th>Validator Text</th><th>Tx Hash</th></tr></thead><tbody>`;
    for(const [validator, info] of Object.entries(valObj)){
      const text = `Resultado: ${info.approval}\nDescripcion: ${info.text}`;
      html += `<tr>
        <td>${validator}</td>
        <td><pre>${text}</pre></td>
        <td>${info.tx_hash}</td>
      </tr>`;
    }
    html += `</tbody></table></details>`;
  }
  container.innerHTML = html;
}

function formatDate(ts){
    // Convertir a número (parseFloat maneja cadenas como "75817.24")
    const timestampValue = parseFloat(ts); 

    // Si no es un número válido, o si es un timestamp que no tiene sentido (ej. 0)
    if (isNaN(timestampValue) || timestampValue === 0) {
        return "N/A";
    }

    // Los valores son muy pequeños (ej. 75817.24), por lo que asumimos que son SEGUNDOS.
    // Para que Date() funcione, necesitamos MILISEGUNDOS (segundos * 1000).
    const milliseconds = timestampValue * 1000;
    
    const d = new Date(milliseconds);

    // Formato legible: YYYY-MM-DD HH:MM:SS
    // Si la fecha es inválida por alguna razón, devuelve un string de error.
    if (isNaN(d.getTime())) {
         return "Fecha Inválida";
    }

    return d.toISOString().replace("T"," ").split(".")[0];
}

function loadOrderById(orderId){
  document.getElementById("orderId").value = orderId;
  showSection("orders");
  findOrder();
}


// --- Lógica de Inicialización y Escuchadores de Eventos (NUEVO) ---

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