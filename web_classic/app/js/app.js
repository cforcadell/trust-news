const API = "/api";

// Mostrar sección activa
function showSection(section) {
  document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
  document.getElementById(section).classList.add("active");
}

// Publicar nueva noticia
async function publishNew() {
  const text = document.getElementById("newsText").value;
  if (!text.trim()) {
    alert("Introduce un texto para verificar.");
    return;
  }

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
  if (!text.trim()) {
    alert("Introduce un texto a buscar.");
    return;
  }

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
  if (!orderId) {
    alert("Introduce un order_id para buscar.");
    return;
  }

  const res = await fetch(`${API}/orders/${orderId}`);
  const data = await res.json();

  const tabs = document.getElementById("orderTabs");
  tabs.innerHTML = "";

  const sections = [
    {name: "Detalles", data: data},
    {name: "Asertions", data: data.assertions},
    {name: "Documento", data: data.document},
    {name: "Validations", data: data.validations}
  ];

  // Añadir pestaña de eventos si existen
  try {
    const resEv = await fetch(`${API}/news/${orderId}/events`);
    if (resEv.ok) {
      const ev = await resEv.json();
      sections.push({name: "Eventos", data: ev});
    }
  } catch (_) {}

  // Crear botones de pestañas
  sections.forEach((s, i) => {
    const btn = document.createElement("button");
    btn.innerText = s.name;
    btn.onclick = () => renderTabContent(s.data);
    tabs.appendChild(btn);
    if (i === 0) renderTabContent(s.data);
  });
}

// Renderizar contenido de pestañas
function renderTabContent(data) {
  const table = document.getElementById("ordersTable");
  table.innerHTML = "";

  // Si es array -> tabla normal
  if (Array.isArray(data)) {
    renderTable("ordersTable", data);
    return;
  }

  // Si es objeto -> solo claves simples
  if (typeof data === "object" && data !== null) {
    const simpleEntries = Object.entries(data).filter(([_, v]) => typeof v !== "object");
    if (simpleEntries.length) {
      const rows = simpleEntries
        .map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`)
        .join("");
      table.innerHTML = `<table>${rows}</table>`;
      return;
    }
  }

  // Fallback
  table.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
}

// Renderizar tabla genérica (con order_id clicable)
function renderTable(id, data) {
  const table = document.getElementById(id);
  if (!data || data.length === 0) {
    table.innerHTML = "<tr><td>No hay resultados</td></tr>";
    return;
  }

  const keys = Object.keys(data[0]);
  table.innerHTML = `
    <thead><tr>${keys.map(k => `<th>${k}</th>`).join("")}</tr></thead>
    <tbody>
      ${data
        .map(
          r =>
            `<tr>${keys
              .map(k => {
                if (k === "order_id")
                  return `<td><a href="#" onclick="loadOrderById('${r[k]}')">${r[k]}</a></td>`;
                return `<td>${r[k]}</td>`;
              })
              .join("")}</tr>`
        )
        .join("")}
    </tbody>
  `;
}

// Función auxiliar: cargar una order al hacer clic en su ID
function loadOrderById(orderId) {
  document.getElementById("orderId").value = orderId;
  showSection("orders");
  findOrder();
}
