const $ = (selector) => document.querySelector(selector);
const money = (value) => new Intl.NumberFormat("ru-RU").format(Number(value) || 0) + " ₽";
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
const customerName = (value) => {
  const name = String(value || "").trim();
  return !name || /^клиент\s*\+?[\d\s()\-]{7,}$/i.test(name) ? "Имя не указано" : name;
};
const dateTime = (value, flexible = false) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || "Время не указано";
  const day = date.toLocaleDateString("ru-RU", {day:"2-digit", month:"2-digit", weekday:"short"});
  return flexible ? `${day}, в течение дня` : `${day}, ${date.toLocaleTimeString("ru-RU", {hour:"2-digit", minute:"2-digit"})}`;
};
const numberOrNull = (value) => value === "" || value == null ? null : Number(value);

let crm = {customers:[], cars:[], appointments:[], orders:[], finance:{}};
let currentView = "dashboard";
let orderFilter = "active";

async function api(url, options = {}) {
  const response = await fetch(url, {credentials:"same-origin", ...options});
  if (response.status === 401) throw new Error("AUTH");
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Ошибка сервера");
  }
  return response.json();
}

function showLogin() { $("#dashboard").hidden = true; $("#sectionView").hidden = true; $("#loginScreen").hidden = false; }
function showApp() { $("#loginScreen").hidden = true; }
function empty(text) { return `<div class="empty">${escapeHtml(text)}</div>`; }
function toast(text) { const node=$("#toast"); node.textContent=text; node.hidden=false; clearTimeout(node.timer); node.timer=setTimeout(()=>node.hidden=true,3000); }
function carLabel(car) { return `${car?.brand || "Авто"} ${car?.model || ""}${car?.plate_number ? ` · ${car.plate_number}` : ""}`; }
function getCustomer(id) { return crm.customers.find((item) => item.id === id); }
function getCar(id) { return crm.cars.find((item) => item.id === id); }
function statusLabel(status) { return ({in_progress:"В работе", planned:"Запланирован", ready:"Выполнен", completed:"Выполнен", no_show:"Не приехал", scheduled:"Записан"})[status] || status; }

function renderAppointments(items, target = "#appointments") {
  $(target).innerHTML = items.length ? items.map((item) => `
    <article class="data-card clickable" data-edit="appointment" data-id="${item.id}">
      <span class="badge">Запись #${item.id}</span><h3>${escapeHtml(item.brand)} ${escapeHtml(item.model)}</h3>
      <p>${escapeHtml(dateTime(item.starts_at, item.is_flexible))}</p>
      <p>Клиент: ${escapeHtml(customerName(item.customer_name))}${item.customer_phone ? ` · ${escapeHtml(item.customer_phone)}` : ""}</p>
      <p>${escapeHtml(item.description)}</p>
    </article>`).join("") : empty("Предстоящих записей нет");
}

function renderOrders(items, target = "#orders") {
  $(target).innerHTML = items.length ? items.map((item) => `
    <article class="data-card clickable" data-edit="order" data-id="${item.id}">
      <span class="badge">Заказ #${item.id} · ${escapeHtml(statusLabel(item.status))}</span>
      <h3>${escapeHtml(item.brand)} ${escapeHtml(item.model)}</h3><p>Клиент: ${escapeHtml(customerName(item.customer_name))}</p>
      <p>${escapeHtml(item.description)}</p><p><strong>${money(item.labor_revenue + item.parts_revenue)}</strong></p>
    </article>`).join("") : empty("Заказов в работе нет");
}

async function loadAll() {
  const [dashboard, data] = await Promise.all([api("/api/dashboard"), api("/api/crm")]);
  crm = data;
  $("#todayProfit").textContent = money(dashboard.today_profit);
  $("#activeOrders").textContent = dashboard.active_orders;
  $("#appointmentsCount").textContent = dashboard.upcoming_appointments;
  renderAppointments(dashboard.appointments);
  renderOrders(dashboard.orders);
  if (currentView !== "dashboard") renderSection();
}

async function loadDashboard() {
  try { await loadAll(); showApp(); showView(currentView, false); }
  catch (error) { error.message === "AUTH" ? showLogin() : toast(error.message); }
}

const sectionMeta = {
  appointments:["РАСПИСАНИЕ", "Календарь записей", "appointment"],
  orders:["СЕРВИС", "Заказ-наряды", "order"],
  customers:["КЛИЕНТСКАЯ БАЗА", "Клиенты", "customer"],
  cars:["АВТОМОБИЛИ", "Автомобили", "car"],
  finance:["ФИНАНСЫ", "Финансы и аналитика", null],
};

function showView(view, updateNav = true) {
  currentView = view;
  $("#dashboard").hidden = view !== "dashboard";
  $("#sectionView").hidden = view === "dashboard";
  $(".topbar-title h1").textContent = view === "dashboard" ? "Главная" : sectionMeta[view][1];
  if (updateNav) {
    document.querySelectorAll("[data-view]").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  }
  if (view !== "dashboard") renderSection();
  window.scrollTo({top:0, behavior:"smooth"});
}

function renderSection() {
  const [eyebrow, title, createType] = sectionMeta[currentView];
  $("#sectionEyebrow").textContent = eyebrow; $("#sectionTitle").textContent = title;
  $("#sectionCreate").hidden = !createType; $("#sectionCreate").dataset.create = createType || "";
  $("#sectionTools").innerHTML = "";
  if (currentView === "appointments") renderAppointmentSection();
  if (currentView === "orders") renderOrderSection();
  if (currentView === "customers") renderCustomerSection();
  if (currentView === "cars") renderCarSection();
  if (currentView === "finance") renderFinanceSection();
}

function renderAppointmentSection() {
  $("#sectionContent").innerHTML = crm.appointments.length ? crm.appointments.map((item) => `
    <article class="entity-card"><div class="entity-card-head"><div><span class="status-badge">${escapeHtml(dateTime(item.starts_at,item.is_flexible))}</span><h3>${escapeHtml(item.brand)} ${escapeHtml(item.model)}</h3></div><button class="small-button" data-edit="appointment" data-id="${item.id}">Изменить</button></div>
      <p>${escapeHtml(item.plate_number || "Номер не указан")}</p><p><strong>${escapeHtml(customerName(item.customer_name))}</strong>${item.customer_phone ? ` · ${escapeHtml(item.customer_phone)}` : ""}</p><p>${escapeHtml(item.description)}</p>
      <div class="entity-actions"><button class="small-button success" data-appointment-action="arrived" data-id="${item.id}">Клиент приехал</button><button class="small-button danger" data-appointment-action="no_show" data-id="${item.id}">Не приехал</button></div></article>`).join("") : empty("Записей нет");
}

function renderOrderSection() {
  $("#sectionTools").innerHTML = `<button class="filter-button ${orderFilter==="active"?"active":""}" data-order-filter="active">В работе</button><button class="filter-button ${orderFilter==="ready"?"active":""}" data-order-filter="ready">Выполненные</button><button class="filter-button ${orderFilter==="all"?"active":""}" data-order-filter="all">Все</button>`;
  const items = crm.orders.filter((item) => orderFilter === "all" || (orderFilter === "active" ? item.status !== "ready" && item.status !== "completed" : item.status === "ready" || item.status === "completed"));
  $("#sectionContent").innerHTML = items.length ? items.map((item) => `
    <article class="entity-card"><div class="entity-card-head"><div><span class="status-badge ${item.status==="ready"||item.status==="completed"?"ready":""}">${escapeHtml(statusLabel(item.status))}</span><h3>Заказ #${item.id} · ${escapeHtml(item.brand)} ${escapeHtml(item.model)}</h3></div><button class="small-button" data-edit="order" data-id="${item.id}">Изменить</button></div>
      <p>${escapeHtml(customerName(item.customer_name))}${item.plate_number ? ` · ${escapeHtml(item.plate_number)}` : ""}</p><p>${escapeHtml(item.description)}</p><p>Работы: <strong>${money(item.labor_revenue)}</strong> · Запчасти: <strong>${money(item.parts_revenue)}</strong></p><p>Прибыль: <strong>${money(item.profit)}</strong></p>
      <div class="entity-actions">${item.status!=="ready"&&item.status!=="completed"?`<button class="small-button success" data-order-status="ready" data-id="${item.id}">Выполнен</button>`:`<button class="small-button" data-order-status="in_progress" data-id="${item.id}">Вернуть в работу</button>`}</div></article>`).join("") : empty("Заказ-наряды не найдены");
}

function renderCustomerSection() {
  $("#sectionContent").innerHTML = crm.customers.length ? crm.customers.map((item) => {
    const cars = crm.cars.filter((car) => car.customer_id === item.id);
    return `<article class="entity-card"><div class="entity-card-head"><div><span class="status-badge">Клиент #${item.id}</span><h3>${escapeHtml(customerName(item.full_name))}</h3></div><button class="small-button" data-edit="customer" data-id="${item.id}">Изменить</button></div><p>${escapeHtml(item.phone || "Телефон не указан")}</p><p>Автомобилей: <strong>${cars.length}</strong></p>${cars.slice(0,3).map(car=>`<p>◇ ${escapeHtml(carLabel(car))}</p>`).join("")}<div class="entity-actions"><button class="small-button" data-create="car" data-customer-id="${item.id}">＋ Автомобиль</button><button class="small-button" data-create="appointment" data-customer-id="${item.id}">＋ Запись</button></div></article>`;
  }).join("") : empty("Клиентов пока нет");
}

function renderCarSection() {
  $("#sectionContent").innerHTML = crm.cars.length ? crm.cars.map((item) => {
    const customer=getCustomer(item.customer_id); const history=crm.orders.filter(o=>o.car_id===item.id);
    return `<article class="entity-card"><div class="entity-card-head"><div><span class="status-badge">Автомобиль #${item.id}</span><h3>${escapeHtml(carLabel(item))}</h3></div><button class="small-button" data-edit="car" data-id="${item.id}">Изменить</button></div><p>Владелец: <strong>${escapeHtml(customerName(customer?.full_name))}</strong></p><p>VIN: ${escapeHtml(item.vin || "не указан")}</p><p>Пробег: ${item.mileage ? `${new Intl.NumberFormat("ru-RU").format(item.mileage)} км` : "не указан"}</p><p>История: <strong>${history.length} заказов</strong></p><div class="entity-actions"><button class="small-button" data-create="order" data-car-id="${item.id}">＋ Заказ</button><button class="small-button" data-create="appointment" data-car-id="${item.id}">＋ Запись</button></div></article>`;
  }).join("") : empty("Автомобилей пока нет");
}

function renderFinanceSection() {
  const f=crm.finance;
  $("#sectionContent").innerHTML = `<div class="finance-grid"><article class="finance-tile"><span>Прибыль сегодня</span><strong>${money(f.today_profit)}</strong></article><article class="finance-tile"><span>Общая выручка</span><strong>${money(f.revenue)}</strong></article><article class="finance-tile"><span>Общая прибыль</span><strong>${money(f.profit)}</strong></article><article class="finance-tile"><span>Расходы на запчасти</span><strong>${money(f.parts_cost)}</strong></article></div>`;
}

function selectOptions(items, selected, label) { return `<option value="">Не выбрано</option>` + items.map(item=>`<option value="${item.id}" ${item.id===selected?"selected":""}>${escapeHtml(label(item))}</option>`).join(""); }
function field(label,name,value="",type="text",extra="") { return `<label ${extra}><span>${label}</span><input name="${name}" type="${type}" value="${escapeHtml(value ?? "")}"></label>`; }

function openForm(type, item = null, preset = {}) {
  const edit = Boolean(item); $("#modal").hidden=false; document.body.style.overflow="hidden";
  $("#entityForm").dataset.type=type; $("#entityForm").dataset.id=item?.id || "";
  let html=""; let title="";
  if (type === "customer") { title=edit?"Изменить клиента":"Новый клиент"; html=field("Имя","full_name",item?.full_name||"")+field("Телефон","phone",item?.phone||"","tel"); }
  if (type === "car") { title=edit?"Изменить автомобиль":"Новый автомобиль"; html=`<label class="full"><span>Владелец</span><select name="customer_id">${selectOptions(crm.customers,item?.customer_id||numberOrNull(preset.customerId),x=>`${customerName(x.full_name)}${x.phone?` · ${x.phone}`:""}`)}</select></label>`+field("Марка","brand",item?.brand||"")+field("Модель","model",item?.model||"")+field("Год","year",item?.year||"","number")+field("Госномер","plate_number",item?.plate_number||"")+field("VIN","vin",item?.vin||"", "text", "class=\"full\"")+field("Пробег, км","mileage",item?.mileage||"","number"); }
  if (type === "appointment") { title=edit?"Изменить запись":"Новая запись"; const cars=preset.customerId?crm.cars.filter(c=>c.customer_id===numberOrNull(preset.customerId)):crm.cars; html=`<label class="full"><span>Автомобиль</span><select name="car_id" required>${selectOptions(cars,item?.car_id||numberOrNull(preset.carId),carLabel)}</select></label>`+field("Дата и время","starts_at",item?.starts_at?.slice(0,16)||"","datetime-local","class=\"full\"")+`<label class="full"><span>Причина обращения</span><textarea name="description" required>${escapeHtml(item?.description||"")}</textarea></label>`+field("Согласованная сумма","agreed_amount",item?.agreed_amount||"","number")+`<label><span>Запчасти</span><select name="parts_source"><option value="">Не указано</option><option value="workshop" ${item?.parts_source==="workshop"?"selected":""}>Наши</option><option value="customer" ${item?.parts_source==="customer"?"selected":""}>Клиента</option></select></label>`; }
  if (type === "order") { title=edit?`Заказ-наряд #${item.id}`:"Новый заказ-наряд"; html=`<label class="full"><span>Автомобиль</span><select name="car_id" required>${selectOptions(crm.cars,item?.car_id||numberOrNull(preset.carId),carLabel)}</select></label><label class="full"><span>Работы</span><textarea name="description" required>${escapeHtml(item?.description||"")}</textarea></label>`+field("Стоимость работ","labor_revenue",item?.labor_revenue||0,"number")+field("Закупка запчастей","parts_cost",item?.parts_cost||0,"number")+field("Продажа запчастей","parts_revenue",item?.parts_revenue||0,"number")+field("Доп. прибыль запчастей","parts_profit",item?.parts_profit||0,"number")+field("Согласованная сумма","agreed_amount",item?.agreed_amount||"","number")+`<label><span>Запчасти</span><select name="parts_source"><option value="">Не указано</option><option value="workshop" ${item?.parts_source==="workshop"?"selected":""}>Наши</option><option value="customer" ${item?.parts_source==="customer"?"selected":""}>Клиента</option></select></label><label class="full"><span>Рекомендации</span><textarea name="recommendations">${escapeHtml(item?.recommendations||"")}</textarea></label>`; }
  $("#modalTitle").textContent=title;
  $("#entityForm").innerHTML=html+`<div class="form-actions"><button type="button" class="small-button" data-close-modal>Отмена</button><button type="submit" class="primary-button">Сохранить</button></div>`;
}

function closeModal() { $("#modal").hidden=true; document.body.style.overflow=""; }
function formPayload(form) { const raw=Object.fromEntries(new FormData(form)); ["customer_id","year","mileage","car_id","agreed_amount","labor_revenue","parts_cost","parts_revenue","parts_profit"].forEach(k=>{if(k in raw)raw[k]=numberOrNull(raw[k]);}); return raw; }

async function saveForm(form) {
  const type=form.dataset.type, id=form.dataset.id, payload=formPayload(form);
  const path=({customer:"customers",car:"cars",appointment:"appointments",order:"orders"})[type];
  try { await api(`/api/${path}${id?`/${id}`:""}`, {method:id?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); closeModal(); await loadAll(); toast("Сохранено"); }
  catch(error){ toast(error.message); }
}

function renderSearch(data) {
  const groups=[["Клиенты",data.customers,i=>`${customerName(i.full_name)}${i.phone?` · ${i.phone}`:""}`],["Автомобили",data.cars,i=>`${i.brand} ${i.model}${i.plate_number?` · ${i.plate_number}`:""}`],["Заказ-наряды",data.orders,i=>`#${i.id} · ${i.brand} ${i.model} · ${i.description}`],["Записи",data.appointments,i=>`#${i.id} · ${i.brand} ${i.model} · ${i.description}`]];
  const html=groups.flatMap(([title,items,label])=>items?.length?[`<h3>${title}</h3>`,...items.map(i=>`<div class="data-card">${escapeHtml(label(i))}</div>`)] : []).join("");
  $("#searchResults").innerHTML=html||empty("Ничего не найдено"); $("#searchResults").hidden=false;
}
async function runSearch(){const q=$("#searchInput").value.trim();if(q.length<2)return toast("Введите минимум два символа");try{renderSearch(await api(`/api/search?q=${encodeURIComponent(q)}`));}catch(e){e.message==="AUTH"?showLogin():toast(e.message);}}

$("#loginForm").addEventListener("submit",async(e)=>{e.preventDefault();$("#loginError").textContent="";try{await api("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:$("#username").value,password:$("#password").value})});$("#password").value="";currentView="dashboard";await loadDashboard();}catch(error){$("#loginError").textContent=error.message==="AUTH"?"Неверный логин или пароль":error.message;}});
$("#entityForm").addEventListener("submit",(e)=>{e.preventDefault();saveForm(e.currentTarget);});
$("#searchButton").addEventListener("click",runSearch); $("#searchInput").addEventListener("keydown",e=>{if(e.key==="Enter")runSearch();});
$("#refreshButton").addEventListener("click",async()=>{await loadAll();toast("Данные обновлены");});
$("#focusSearch").addEventListener("click",()=>{$("#searchInput").focus();$("#searchInput").scrollIntoView({behavior:"smooth",block:"center"});});
$("#logoutButton").addEventListener("click",async()=>{await fetch("/api/logout",{method:"POST",credentials:"same-origin"}).catch(()=>{});showLogin();});
document.addEventListener("click",async(e)=>{
  const view=e.target.closest("[data-view]"); if(view){showView(view.dataset.view);return;}
  const create=e.target.closest("[data-create]"); if(create){openForm(create.dataset.create,null,{carId:create.dataset.carId,customerId:create.dataset.customerId});return;}
  const edit=e.target.closest("[data-edit]"); if(edit){const type=edit.dataset.edit,id=Number(edit.dataset.id);const source=type==="customer"?crm.customers:type==="car"?crm.cars:type==="appointment"?crm.appointments:crm.orders;openForm(type,source.find(i=>i.id===id));return;}
  if(e.target.closest("[data-close-modal]")){closeModal();return;}
  const filter=e.target.closest("[data-order-filter]"); if(filter){orderFilter=filter.dataset.orderFilter;renderOrderSection();return;}
  const ap=e.target.closest("[data-appointment-action]"); if(ap){if(!confirm(ap.dataset.appointmentAction==="arrived"?"Перевести запись в заказ-наряд?":"Отметить, что клиент не приехал?"))return;try{await api(`/api/appointments/${ap.dataset.id}/action`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:ap.dataset.appointmentAction})});await loadAll();toast("Статус обновлён");}catch(err){toast(err.message);}return;}
  const os=e.target.closest("[data-order-status]"); if(os){try{await api(`/api/orders/${os.dataset.id}/status`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:os.dataset.orderStatus})});await loadAll();toast("Статус заказа обновлён");}catch(err){toast(err.message);}return;}
});

$("#todayLabel").textContent=new Date().toLocaleDateString("ru-RU",{weekday:"long",day:"numeric",month:"long"});
const greeting=new Date().getHours()<12?"Доброе утро":new Date().getHours()<18?"Добрый день":"Добрый вечер";document.querySelector(".welcome-row h2").textContent=`${greeting}, Дмитрий`;
if("serviceWorker" in navigator)window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js"));
loadDashboard();
