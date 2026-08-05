const $ = (selector) => document.querySelector(selector);
const money = (value) => new Intl.NumberFormat("ru-RU").format(value || 0) + " ₽";
const dateTime = (value, flexible = false) => {
  const date = new Date(value);
  const options = { day: "2-digit", month: "2-digit", weekday: "short" };
  const day = date.toLocaleDateString("ru-RU", options);
  return flexible ? `${day}, в течение дня` : `${day}, ${date.toLocaleTimeString("ru-RU", {hour:"2-digit", minute:"2-digit"})}`;
};
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
const customerName = (value) => {
  const name = String(value || "").trim();
  return !name || (/^клиент\s*\+/i.test(name) && (name.match(/\d/g) || []).length >= 7)
    ? "Имя не указано" : name;
};

async function api(url, options = {}) {
  const response = await fetch(url, { credentials: "same-origin", ...options });
  if (response.status === 401) throw new Error("AUTH");
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Ошибка сервера");
  }
  return response.json();
}

function showLogin() { $("#dashboard").hidden = true; $("#loginScreen").hidden = false; }
function showDashboard() { $("#loginScreen").hidden = true; $("#dashboard").hidden = false; }
function empty(text) { return `<div class="empty">${escapeHtml(text)}</div>`; }

function renderAppointments(items) {
  $("#appointments").innerHTML = items.length ? items.map((item) => `
    <article class="data-card">
      <span class="badge">Запись #${item.id}</span>
      <h3>${escapeHtml(item.brand)} ${escapeHtml(item.model)}</h3>
      <p>${escapeHtml(dateTime(item.starts_at, item.is_flexible))}</p>
      <p>Клиент: ${escapeHtml(customerName(item.customer_name))}${item.customer_phone ? ` · ${escapeHtml(item.customer_phone)}` : ""}</p>
      <p>${escapeHtml(item.description)}</p>
    </article>`).join("") : empty("Предстоящих записей нет");
}

function renderOrders(items) {
  $("#orders").innerHTML = items.length ? items.map((item) => `
    <article class="data-card">
      <span class="badge">Заказ #${item.id}</span>
      <h3>${escapeHtml(item.brand)} ${escapeHtml(item.model)}</h3>
      <p>Клиент: ${escapeHtml(customerName(item.customer_name))}</p>
      <p>${escapeHtml(item.description)}</p>
      <p><strong>${money(item.labor_revenue + item.parts_revenue)}</strong></p>
    </article>`).join("") : empty("Заказов в работе нет");
}

async function loadDashboard() {
  try {
    const data = await api("/api/dashboard");
    showDashboard();
    $("#todayProfit").textContent = money(data.today_profit);
    $("#activeOrders").textContent = data.active_orders;
    $("#appointmentsCount").textContent = data.upcoming_appointments;
    renderAppointments(data.appointments);
    renderOrders(data.orders);
  } catch (error) {
    if (error.message === "AUTH") return showLogin();
    toast(error.message);
  }
}

function renderSearch(data) {
  const groups = [
    ["Клиенты", data.customers, (item) => `${customerName(item.full_name)}${item.phone ? ` · ${item.phone}` : ""}`],
    ["Автомобили", data.cars, (item) => `${item.brand} ${item.model}${item.plate_number ? ` · ${item.plate_number}` : ""}`],
    ["Заказ-наряды", data.orders, (item) => `#${item.id} · ${item.brand} ${item.model} · ${item.description}`],
    ["Записи", data.appointments, (item) => `#${item.id} · ${item.brand} ${item.model} · ${item.description}`],
  ];
  const html = groups.flatMap(([title, items, label]) => items?.length
    ? [`<h3>${title}</h3>`, ...items.map((item) => `<div class="data-card">${escapeHtml(label(item))}</div>`)] : []).join("");
  $("#searchResults").innerHTML = html || empty("Ничего не найдено");
  $("#searchResults").hidden = false;
}

async function runSearch() {
  const query = $("#searchInput").value.trim();
  if (query.length < 2) return toast("Введите минимум два символа");
  try { renderSearch(await api(`/api/search?q=${encodeURIComponent(query)}`)); }
  catch (error) { error.message === "AUTH" ? showLogin() : toast(error.message); }
}

function toast(text) {
  const node = $("#toast"); node.textContent = text; node.hidden = false;
  window.setTimeout(() => { node.hidden = true; }, 2800);
}

$("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault(); $("#loginError").textContent = "";
  try {
    await api("/api/login", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({username: $("#username").value, password: $("#password").value}) });
    $("#password").value = ""; await loadDashboard();
  } catch (error) { $("#loginError").textContent = error.message === "AUTH" ? "Неверный логин или пароль" : error.message; }
});
$("#searchButton").addEventListener("click", runSearch);
$("#searchInput").addEventListener("keydown", (event) => { if (event.key === "Enter") runSearch(); });
$("#refreshButton").addEventListener("click", loadDashboard);
$("#todayLabel").textContent = new Date().toLocaleDateString("ru-RU", {weekday:"long", day:"numeric", month:"long"});
if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js"));
loadDashboard();
