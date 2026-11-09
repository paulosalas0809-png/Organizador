"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let datos = null;
let filtro = "todas";
let chat = [];

const FRASES = [
  "Un paso pequeño hoy vale más que un plan perfecto mañana.",
  "Haz primero lo difícil; el resto del día se siente más liviano.",
  "No tienes que hacerlo todo, solo lo importante.",
  "La constancia gana a la motivación.",
  "Termina una cosa antes de empezar otra.",
  "Descansar también es parte de ser productivo.",
  "Hecho es mejor que perfecto.",
];

// ---------------------------------------------------------------- utilidades

function guardar(clave, valor) { try { localStorage.setItem(clave, JSON.stringify(valor)); } catch (e) {} }
function leer(clave, defecto) {
  try { const v = localStorage.getItem(clave); return v ? JSON.parse(v) : defecto; } catch (e) { return defecto; }
}
function hoyClave() { const d = new Date(); return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`; }

function toast(texto) {
  const t = $("#toast");
  t.textContent = texto;
  t.classList.add("ver");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("ver"), 2800);
}

async function api(ruta, cuerpo) {
  const opciones = cuerpo === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo),
  };
  const r = await fetch(ruta, opciones);
  if (r.status === 401) { location.href = "/entrar"; throw new Error("Sesión cerrada"); }
  const j = await r.json().catch(() => ({}));
  if (j.google_desconectado) { mostrarConectar(); }
  if (!r.ok) throw new Error(j.error || "Algo salió mal");
  return j;
}

function minutos(hhmm) { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; }
function ahoraMin() { const d = new Date(); return d.getHours() * 60 + d.getMinutes(); }

// ---------------------------------------------------------------- carga

async function cargar() {
  try {
    datos = await api("/api/hoy");
  } catch (e) {
    $("#cargando").innerHTML = "😕 " + esc(e.message);
    return;
  }
  $("#cargando").hidden = true;
  const h = new Date().getHours();
  $("#saludo").textContent = h < 12 ? "Buenos días ☀️" : h < 19 ? "Buenas tardes 🌤️" : "Buenas noches 🌙";
  $("#fecha").textContent = datos.fecha;
  if (!datos.google) { mostrarConectar(); return; }
  $("#conectar").hidden = true;
  $("#contenido").hidden = false;
  pintarTodo();
  pintarChat();
}

function mostrarConectar() {
  $("#cargando").hidden = true;
  $("#contenido").hidden = true;
  $("#conectar").hidden = false;
}

function pintarTodo() {
  pintarProgreso();
  pintarPlan();
  pintarAgenda();
  pintarTareas();
}

// ---------------------------------------------------------------- progreso

function pintarProgreso() {
  const hechas = datos.completadas.length;
  const urgentes = datos.tareas.filter((t) => t.estado === "vencida" || t.estado === "hoy").length;
  const total = hechas + urgentes;
  const pct = total ? Math.round((hechas / total) * 100) : (hechas ? 100 : 0);
  $("#pct").textContent = pct + "%";
  $("#anillo-arco").style.strokeDashoffset = 238.76 * (1 - pct / 100);
  $("#st-hechas").textContent = hechas;
  $("#st-urgentes").textContent = urgentes;
  $("#st-eventos").textContent = datos.eventos.filter((e) => !e.organizador).length;
  $("#hora").textContent = datos.hora;
  const d = new Date();
  $("#frase").textContent = "“" + FRASES[(d.getDate() + d.getMonth()) % FRASES.length] + "”";
}

// ---------------------------------------------------------------- plan

function pintarPlan() {
  const caja = $("#plan");
  const plan = datos.plan;
  const formulario = `
    ${datos.ia ? '<textarea class="nota-input" id="nota" rows="2" placeholder="Indicaciones opcionales: “hoy salgo a las 6”, “estoy con poca energía”…"></textarea>' : '<div style="height:10px"></div>'}
    <button class="btn block" id="btn-plan">✨ ${plan ? "Rehacer mi plan" : "Generar mi plan"}</button>`;
  if (!plan) {
    caja.innerHTML = `<div class="plan-vacio"><div class="big">🌱</div>
      <p>${datos.ia ? "Tu asistente revisará tu agenda y tus tareas para armar un día realista." : "Ordeno tus tareas por urgencia y las acomodo en tus horas libres, con pausas."}</p></div>${formulario}`;
    $("#btn-plan").onclick = generarPlan;
    $("#plan-hora").textContent = "";
    return;
  }
  $("#plan-hora").textContent = "creado " + plan.generado;
  const ahora = ahoraMin();
  const bloques = plan.bloques.map((b) => {
    const ini = minutos(b.inicio), fin = minutos(b.fin);
    const estado = fin <= ahora ? "pasado" : ini <= ahora ? "ahora" : "";
    return `<div class="bloque ${esc(b.tipo)} ${estado}">
      <div class="hora">${esc(b.inicio)}<br>${esc(b.fin)}</div>
      <div class="caja"><div class="t">${esc(b.titulo)}</div>${b.nota ? `<div class="n">${esc(b.nota)}</div>` : ""}</div>
    </div>`;
  }).join("");
  caja.innerHTML = `
    <p class="resumen">${esc(plan.resumen)}</p>
    <ol class="prioridades">${plan.prioridades.map((p, i) => `<li><b>${i + 1}</b><span>${esc(p)}</span></li>`).join("")}</ol>
    <div class="timeline">${bloques}</div>
    ${plan.otro_dia && plan.otro_dia.length ? `<div class="otro-dia">📦 Mejor para otro día: ${plan.otro_dia.map(esc).join(", ")}</div>` : ""}
    <div class="consejo">💡 ${esc(plan.consejo)}</div>
    <div class="fila-btn">
      <button class="btn ${plan.agendado ? "sec" : ""}" id="btn-agendar">${plan.agendado ? "✓ En tu calendario" : "📅 Poner en Google Calendar"}</button>
    </div>
    <details style="margin-top:12px"><summary style="cursor:pointer;color:var(--muted);font-size:14px">Rehacer el plan</summary>${formulario}</details>`;
  $("#btn-plan").onclick = generarPlan;
  $("#btn-agendar").onclick = agendar;
}

async function generarPlan() {
  const btn = $("#btn-plan");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Tu asistente está pensando…';
  try {
    datos.plan = await api("/api/plan", { nota: ($("#nota") || {}).value || "" });
    pintarPlan();
    toast("¡Tu plan está listo! ✨");
  } catch (e) {
    toast("😕 " + e.message);
    btn.disabled = false;
    btn.textContent = "✨ Intentar de nuevo";
  }
}

async function agendar() {
  const btn = $("#btn-agendar");
  if (datos.plan.agendado && !confirm("¿Volver a poner los bloques? Se reemplazan los anteriores del Organizador.")) return;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Agendando…';
  try {
    const r = await api("/api/agendar", {});
    datos.plan.agendado = true;
    toast(`📅 Agregué ${r.creados} bloques a tu calendario`);
    await cargar();
  } catch (e) {
    toast("😕 " + e.message);
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- agenda

function pintarAgenda() {
  const ev = datos.eventos;
  $("#agenda").innerHTML = ev.length
    ? ev.map((e) => `<div class="evento-item"><div class="h">${e.todo_el_dia ? "Todo el día" : esc(e.inicio) + " – " + esc(e.fin)}</div>
        <div>${esc(e.titulo)}</div></div>`).join("")
    : '<p style="color:var(--muted);margin:0">No tienes eventos hoy. ¡Día libre para avanzar! 🚀</p>';
}

// ---------------------------------------------------------------- tareas

function pintarTareas() {
  let lista = datos.tareas;
  if (filtro === "urgentes") lista = lista.filter((t) => t.estado === "vencida" || t.estado === "hoy");
  if (filtro === "sin_fecha") lista = lista.filter((t) => t.estado === "sin_fecha");
  $("#tareas-cuenta").textContent = datos.tareas.length + " pendientes";
  const etiqueta = (t) => {
    if (t.estado === "vencida") return '<span class="badge vencida">Vencida</span>';
    if (t.estado === "hoy") return '<span class="badge hoy">Hoy</span>';
    if (t.estado === "futura") return `<span class="badge futura">${t.vence.slice(8, 10)}/${t.vence.slice(5, 7)}</span>`;
    return "";
  };
  $("#tareas").innerHTML = lista.length ? lista.map((t) => `
    <div class="tarea-item" data-id="${esc(t.id)}">
      <button class="check" title="Completar">✓</button>
      <div class="tt"><div>${esc(t.titulo)}</div><div class="meta">${etiqueta(t)}<span>${esc(t.lista)}</span></div></div>
      <button class="icon-btn enfocar" title="Enfocarme en esta" style="width:34px;height:34px;font-size:15px">🎯</button>
    </div>`).join("")
    : '<p style="color:var(--muted);margin:6px 0">Nada por aquí. 🎉</p>';
  const hechas = datos.completadas;
  $("#hechas-hoy").innerHTML = hechas.length ? "✅ Hechas hoy: " + hechas.map((t) => `<s>${esc(t)}</s>`).join(", ") : "";

  $$("#tareas .tarea-item").forEach((el) => {
    const t = datos.tareas.find((x) => x.id === el.dataset.id);
    el.querySelector(".check").onclick = () => completar(t, el);
    el.querySelector(".enfocar").onclick = () => enfocar(t);
  });
}

async function completar(t, el) {
  el.classList.add("hecha");
  try {
    await api("/api/tareas/completar", { id: t.id, lista_id: t.lista_id });
    datos.tareas = datos.tareas.filter((x) => x.id !== t.id);
    datos.completadas.push(t.titulo);
    setTimeout(() => { pintarTareas(); pintarProgreso(); }, 320);
    toast("🎉 ¡Bien hecho! " + t.titulo);
  } catch (e) {
    el.classList.remove("hecha");
    toast("😕 " + e.message);
  }
}

$("#filtros").addEventListener("click", (e) => {
  const b = e.target.closest(".chip");
  if (!b) return;
  filtro = b.dataset.f;
  $$("#filtros .chip").forEach((c) => c.classList.toggle("on", c === b));
  pintarTareas();
});

$("#form-nueva").addEventListener("submit", async (e) => {
  e.preventDefault();
  const titulo = $("#nueva-titulo").value.trim();
  if (!titulo) return;
  try {
    await api("/api/tareas/nueva", { titulo, hoy: $("#nueva-hoy").checked });
    $("#nueva-titulo").value = "";
    toast("➕ Tarea creada");
    await cargar();
  } catch (err) { toast("😕 " + err.message); }
});

// ---------------------------------------------------------------- pomodoro

const pomo = { duracion: 25 * 60, restante: 25 * 60, timer: null, fin: 0, modo: 25 };

function pintarReloj() {
  const m = Math.floor(pomo.restante / 60), s = pomo.restante % 60;
  $("#reloj").textContent = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  document.title = pomo.timer ? `${$("#reloj").textContent} · Organizador` : "Organizador";
  const ciclos = leer("pomodoros-" + hoyClave(), 0);
  $("#ciclos").textContent = `${ciclos} pomodoro${ciclos === 1 ? "" : "s"} hoy 🍅`;
}

function sonar() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.25, 0.5].forEach((t) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880; o.connect(g); g.connect(ctx.destination);
      g.gain.setValueAtTime(0.2, ctx.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.2);
      o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.22);
    });
  } catch (e) {}
  if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
}

function tick() {
  pomo.restante = Math.max(0, Math.round((pomo.fin - Date.now()) / 1000));
  pintarReloj();
  if (pomo.restante === 0) {
    clearInterval(pomo.timer); pomo.timer = null;
    $("#pomo-iniciar").textContent = "▶ Empezar";
    sonar();
    if (pomo.modo === 25) {
      guardar("pomodoros-" + hoyClave(), leer("pomodoros-" + hoyClave(), 0) + 1);
      toast("🍅 ¡Pomodoro terminado! Toma una pausa.");
      if ("Notification" in window && Notification.permission === "granted") new Notification("¡Pomodoro terminado! 🍅 Toma una pausa.");
    } else {
      toast("⏰ Pausa terminada, ¡a seguir!");
    }
    pomo.restante = pomo.duracion;
    pintarReloj();
  }
}

$("#pomo-iniciar").onclick = () => {
  if (pomo.timer) {
    clearInterval(pomo.timer); pomo.timer = null;
    $("#pomo-iniciar").textContent = "▶ Seguir";
  } else {
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    pomo.fin = Date.now() + pomo.restante * 1000;
    pomo.timer = setInterval(tick, 500);
    $("#pomo-iniciar").textContent = "⏸ Pausar";
  }
  pintarReloj();
};
$("#pomo-reiniciar").onclick = () => {
  clearInterval(pomo.timer); pomo.timer = null;
  pomo.restante = pomo.duracion;
  $("#pomo-iniciar").textContent = "▶ Empezar";
  pintarReloj();
};
$$(".modos .chip").forEach((b) => b.onclick = () => {
  $$(".modos .chip").forEach((c) => c.classList.toggle("on", c === b));
  clearInterval(pomo.timer); pomo.timer = null;
  pomo.modo = Number(b.dataset.min);
  pomo.duracion = pomo.restante = pomo.modo * 60;
  $("#pomo-iniciar").textContent = "▶ Empezar";
  pintarReloj();
});

function enfocar(t) {
  $("#pomo-tarea").textContent = "Enfocado en: " + t.titulo;
  irA("enfoque");
  toast("🎯 Dale a Empezar cuando estés listo");
}

// ---------------------------------------------------------------- chat

function pintarChat() {
  const caja = $("#mensajes");
  if (datos && !datos.ia) {
    caja.innerHTML = '<div class="msg assistant">💬 El chat con Claude necesita una clave de la API de Claude (es de pago y aparte de la suscripción Pro). Todo lo demás de la app funciona gratis. 😊</div>';
    $("#form-chat").style.display = "none";
    $("#sugerencias").style.display = "none";
    return;
  }
  caja.innerHTML = '<div class="msg assistant">¡Hola! Conozco tu agenda y tus tareas de hoy. ¿En qué te ayudo?</div>' +
    chat.map((m) => `<div class="msg ${m.role}">${esc(m.content)}</div>`).join("");
  caja.scrollTop = caja.scrollHeight;
}

async function enviarChat(texto) {
  if (!texto.trim()) return;
  if (datos && !datos.ia) { toast("Falta configurar la clave de Claude"); return; }
  chat.push({ role: "user", content: texto.trim() });
  pintarChat();
  const caja = $("#mensajes");
  caja.insertAdjacentHTML("beforeend", '<div class="msg assistant" id="pensando"><span class="spinner"></span></div>');
  caja.scrollTop = caja.scrollHeight;
  try {
    const r = await api("/api/chat", { historial: chat });
    chat.push({ role: "assistant", content: r.respuesta });
  } catch (e) {
    chat.pop();
    toast("😕 " + e.message);
  }
  guardar("chat-" + hoyClave(), chat);
  pintarChat();
}

$("#form-chat").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#chat-input").value;
  $("#chat-input").value = "";
  enviarChat(v);
});
$("#sugerencias").addEventListener("click", (e) => {
  const b = e.target.closest(".chip");
  if (b) enviarChat(b.textContent);
});

// ---------------------------------------------------------------- pestañas (celular)

function irA(vista) {
  $$(".vista").forEach((v) => v.classList.toggle("activa", v.dataset.vista === vista));
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.vista === vista));
  guardar("vista", vista);
  window.scrollTo({ top: 0 });
}
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) irA(b.dataset.vista);
});

$("#btn-recargar").onclick = () => { toast("Actualizando…"); cargar(); };

// ---------------------------------------------------------------- inicio

chat = leer("chat-" + hoyClave(), []);
pintarChat();
pintarReloj();
irA(leer("vista", "hoy"));
cargar();
