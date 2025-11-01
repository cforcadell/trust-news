const API = "/api";

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
  renderTable("findResults", data);
}

// Listar todas las orders
async function listOrders() {
  const res = await fetch(`${API}/news`);
  const data = await res.json();
  renderTable("ordersTable", data);
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

  // Añadir pestaña de eventos si existen
  try {
    const resEv = await fetch(`http://news-handler:8072/news/${orderId}/events`);

    if (resEv.ok) {
      const ev = await resEv.json();
      sections.push({name: "Eventos", data: ev});
    }
  } catch (_) {}

  // Crear botones de pestañas
  sections.forEach((s, i) => {
    const btn = document.createElement("button");
    btn.innerText = s.name;
    btn.onclick = () => renderTabContent(s.name, s.data, data.assertions);
    tabs.appendChild(btn);
    if (i === 0) renderTabContent(s.name, s.data, data.assertions);
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

// Detalles (solo campos simples)
function renderDetails(container, data) {
  const simpleEntries = Object.entries(data).filter(([_,v])=>typeof v!=="object");
  if(simpleEntries.length){
    const rows = simpleEntries.map(([k,v])=>`<tr><th>${k}</th><td>${v}</td></tr>`).join("");
    container.innerHTML = `<table>${rows}</table>`;
  } else {
    container.innerHTML = `<pre>${JSON.stringify(data,null,2)}</pre>`;
  }
}

// Tabla genérica
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

// Eventos con tooltip
function renderEventsTable(events){
  const container = document.getElementById("ordersTable");
  if(!events?.length){ container.innerHTML="<p>No hay eventos</p>"; return; }
  const rows = events.map(e=>`<tr>
    <td>${formatDate(e.timestamp)}</td>
    <td>${e.action}</td>
    <td class="tooltip">Ver
      <span class="tooltiptext">${JSON.stringify(e.payload,null,2)}</span>
    </td>
  </tr>`).join("");
  container.innerHTML = `<table><thead><tr><th>Fecha</th><th>Acción</th><th>Payload</th></tr></thead>${rows}</table>`;
}

// Validations en árbol
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

    html += `<details><summary><b>${id}</b> - ${atext} → <b class="${statusClass}">${status}</b></summary>
      <table><thead><tr><th>Validator</th><th>Validator Text</th><th>Tx Hash</th></tr></thead>
      <tbody>`;
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

// Formato ISO
function formatDate(ts){
  const d = new Date(ts);
  return d.toISOString().replace("T"," ").split(".")[0];
}

// Cargar order al hacer clic
function loadOrderById(orderId){
  document.getElementById("orderId").value = orderId;
  showSection("orders");
  findOrder();
}
