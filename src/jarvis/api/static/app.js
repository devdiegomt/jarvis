// JARVIS en el iPhone: pestaña Hoy (sin IA) y chat. La clave se guarda solo en este dispositivo.
"use strict";

const KEY_STORAGE = "jarvis-clave";
const $ = (id) => document.getElementById(id);

function readKey() {
  try { return localStorage.getItem(KEY_STORAGE) || ""; } catch { return ""; }
}
function saveKey(key) {
  try { localStorage.setItem(KEY_STORAGE, key); } catch { /* modo privado: se pedirá de nuevo */ }
}
function forgetKey() {
  try { localStorage.removeItem(KEY_STORAGE); } catch { /* nada que borrar */ }
}

class AuthError extends Error {}

async function api(path, body) {
  const options = { headers: { Authorization: `Bearer ${readKey()}` } };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("No pude conectar con JARVIS. ¿Está encendido el PC y activo Tailscale?");
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) throw new AuthError(data.error || "Clave incorrecta.");
  if (!response.ok) throw new Error(data.error || `Error ${response.status}`);
  return data;
}

// --- Elementos (sin innerHTML: el texto nunca se interpreta como HTML) -----------

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function card(title, items, className) {
  const box = el("div", null, `card ${className || ""}`);
  box.append(el("h3", title));
  const list = el("ul");
  for (const [time, text, extra] of items) {
    const row = el("li");
    row.append(el("span", time, "time"), el("span", text));
    if (extra) row.append(el("span", extra, "late"));
    list.append(row);
  }
  box.append(list);
  return box;
}

// --- Login ----------------------------------------------------------------------

async function login(event) {
  event.preventDefault();
  saveKey($("key").value.trim());
  $("login-error").textContent = "";
  try {
    await api("/api/hoy");
    showApp();
  } catch (error) {
    forgetKey();
    $("login-error").textContent = error.message;
  }
}

function showLogin(message) {
  $("app").hidden = true;
  $("login").hidden = false;
  $("login-error").textContent = message || "";
}

function showApp() {
  $("login").hidden = true;
  $("app").hidden = false;
  loadToday();
}

function handleError(error, show) {
  if (error instanceof AuthError) {
    forgetKey();
    showLogin(error.message);
  } else {
    show(error.message);
  }
}

// --- Hoy -------------------------------------------------------------------------

async function loadToday() {
  const box = $("today");
  try {
    const data = await api("/api/hoy");
    renderToday(data);
  } catch (error) {
    handleError(error, (message) => box.replaceChildren(el("p", message, "error")));
  }
}

function renderToday(data) {
  $("today-date").textContent = `Hoy, ${data.dia}`;
  const cards = [];
  if (data.clima) {
    const weather = el("div", null, "card weather");
    weather.append(el("h3", "Clima"), el("div", data.clima.linea));
    cards.push(weather);
  }
  if (data.proxima) {
    const next = data.proxima;
    cards.push(card("Próxima reunión", [[next.inicio, next.titulo + (next.lugar ? ` · ${next.lugar}` : "")]], "next"));
  }
  if (data.error_calendario) {
    cards.push(card("Calendario", [["", data.error_calendario]]));
  } else {
    const meetings = data.reuniones.map((m) => [m.todo_el_dia ? "Día" : m.inicio, m.titulo]);
    cards.push(card("Reuniones", meetings.length ? meetings : [["", "Sin reuniones hoy."]]));
  }
  if (data.recordatorios.length) {
    cards.push(card("Recordatorios", data.recordatorios.map((r) => [r.hora, r.texto])));
  }
  const tasks = data.pendientes.map((t) => ["•", t.texto, t.atrasado ? "atrasado" : ""]);
  const others = data.pendientes_abiertos - data.pendientes.length;
  if (others > 0) tasks.push(["", `y ${others} más sin vencer`]);
  cards.push(card("Pendientes", tasks.length ? tasks : [["", "Nada para hoy."]]));
  $("today").replaceChildren(...cards);
}

// --- Chat ------------------------------------------------------------------------

function addMessage(text, kind) {
  const node = el("div", text, `msg ${kind || ""}`);
  $("messages").append(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

const questions = new Map(); // id de la pregunta → su burbuja

function showReply(reply) {
  for (const message of reply.mensajes) {
    if (message.tipo === "actualiza" && questions.has(message.id)) {
      const bubble = questions.get(message.id);
      bubble.textContent = message.texto;
      questions.delete(message.id);
    } else if (message.tipo === "texto") {
      addMessage(message.texto);
    }
  }
  const question = reply.pregunta;
  if (question && !questions.has(question.id)) {
    const bubble = addMessage(question.texto);
    const buttons = el("div", null, "buttons");
    for (const button of question.botones) {
      const node = el("button", button.texto);
      node.type = "button";
      node.addEventListener("click", () => send({ dato: button.dato }, button.texto));
      buttons.append(node);
    }
    bubble.append(buttons);
    questions.set(question.id, bubble);
  }
  if (!reply.terminado && !question) addMessage("JARVIS sigue trabajando: la respuesta aparecerá con tu próximo mensaje.", "note");
}

let busy = false;

async function send(body, shownText) {
  if (busy) return;
  busy = true;
  if (shownText) addMessage(shownText, "mine");
  const typing = addMessage("JARVIS está escribiendo…", "note typing");
  try {
    const reply = await api(body.texto !== undefined ? "/api/chat" : "/api/boton", body);
    typing.remove();
    showReply(reply);
  } catch (error) {
    typing.remove();
    handleError(error, (message) => addMessage(message, "note"));
  } finally {
    busy = false;
  }
}

function submitChat(event) {
  event.preventDefault();
  const input = $("text");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  resize();
  send({ texto: text }, text);
}

function resize() {
  const input = $("text");
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}

// --- Pestañas e inicio -----------------------------------------------------------

function selectTab(name) {
  for (const button of document.querySelectorAll("[data-tab]")) {
    const selected = button.dataset.tab === name;
    button.setAttribute("aria-selected", String(selected));
    $(`tab-${button.dataset.tab}`).hidden = !selected;
  }
  if (name === "hoy") loadToday();
  if (name === "chat") $("text").focus();
}

function start() {
  $("login-form").addEventListener("submit", login);
  $("chat-form").addEventListener("submit", submitChat);
  $("text").addEventListener("input", resize);
  $("text").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) submitChat(event);
  });
  $("refresh").addEventListener("click", loadToday);
  $("logout").addEventListener("click", (event) => {
    event.preventDefault();
    forgetKey();
    showLogin();
  });
  for (const button of document.querySelectorAll("[data-tab]")) {
    button.addEventListener("click", () => selectTab(button.dataset.tab));
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !$("tab-hoy").hidden && readKey()) loadToday();
  });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  if (readKey()) showApp();
  else showLogin();
}

start();
