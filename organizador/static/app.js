"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ico = (n) => `<svg class="ic"><use href="#i-${n}"/></svg>`;
const sinEmoji = (t) => String(t ?? "").replace(/[\p{Extended_Pictographic}\uFE0F\u200D]+\s*/gu, "").trim();
// Formato mínimo para las respuestas de la IA: **negrita** y viñetas
const md = (t) => esc(t)
  .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
  .replace(/^(\s*)[*-]\s+/gm, "$1• ")
  .replace(/^#{1,4}\s+(.+)$/gm, "<strong>$1</strong>");

let datos = null;
let filtro = "todas";
let chat = [];

// ---------------------------------------------------------------- utilidades

function guardar(clave, valor) { try { localStorage.setItem(clave, JSON.stringify(valor)); } catch (e) {} }
function leer(clave, defecto) {
  try { const v = localStorage.getItem(clave); return v ? JSON.parse(v) : defecto; } catch (e) { return defecto; }
}
function hoyClave() { const d = new Date(); return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`; }

function toast(texto) {
  const t = $("#toast");
  t.textContent = sinEmoji(texto);
  t.classList.add("ver");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("ver"), 2800);
}

async function api(ruta, cuerpo, metodo) {
  const opciones = metodo ? { method: metodo } : cuerpo === undefined ? {} : {
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

function mostrarDatos(primeraVez) {
  $("#cargando").hidden = true;
  const h = new Date().getHours();
  $("#saludo").textContent = (h < 12 ? "Buenos días" : h < 19 ? "Buenas tardes" : "Buenas noches") + (datos.nombre ? ", " + datos.nombre : "");
  $("#fecha").textContent = datos.fecha;
  $("#perfil-nombre").textContent = datos.nombre || "Mi cuenta";
  $("#perfil-inicial").textContent = (datos.nombre || "O").charAt(0).toUpperCase();
  if (!datos.google) { mostrarConectar(); return; }
  $("#conectar").hidden = true;
  $("#contenido").hidden = false;
  pintarTodo();
  if (primeraVez) { pintarChat(); cargarCoach(false); }
}

async function cargar(silencioso) {
  let primeraVez = !datos;
  if (primeraVez) {
    // Primero lo guardado de la última visita de hoy (aparece al instante); luego lo actual
    const guardado = leer("datos-" + hoyClave(), null);
    if (guardado && guardado.google) { datos = guardado; mostrarDatos(true); primeraVez = false; }
  }
  document.body.classList.add("actualizando");
  try {
    datos = await api("/api/hoy");
    diasCache = {};
    guardar("datos-" + hoyClave(), datos);
  } catch (e) {
    if (primeraVez) $("#cargando").textContent = e.message; else toast(e.message);
    return;
  } finally {
    document.body.classList.remove("actualizando");
  }
  mostrarDatos(primeraVez);
}

function mostrarConectar() {
  $("#cargando").hidden = true;
  $("#contenido").hidden = true;
  $("#conectar").hidden = false;
}

// ---------------------------------------------------------------- próximos pendientes

let proxTodos = false;
const DSEM = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
function pintarProximos() {
  const lista = datos.proximos || [];
  const ver = proxTodos ? lista : lista.slice(0, 6);
  $("#proximos").innerHTML = ver.length ? ver.map((e) => {
    const f = new Date(e.fecha + "T12:00:00");
    const clase = e.dias <= 3 ? "pronto" : e.dias <= 7 ? "semana" : "luego";
    const cuando = e.dias === 1 ? "mañana" : `en ${e.dias} días`;
    return `<div class="prox-item">
      <div class="prox-fecha"><small>${DSEM[f.getDay()]}</small><b>${f.getDate()}</b></div>
      <div class="pt"><div>${esc(e.titulo)}</div><small>${e.hora ? esc(e.hora) + " · " : ""}${esc(e.calendario)}</small></div>
      <span class="cuenta ${clase}">${cuando}</span></div>`;
  }).join("") + (lista.length > 6 ? `<button class="ver-mas" id="prox-mas">${proxTodos ? "Ver menos" : `Ver todos (${lista.length})`}</button>` : "")
    : '<p class="vacio">Nada en los próximos 30 días.</p>';
  const p0 = lista[0];
  $("#kpi-prox-cuando").textContent = p0 ? (p0.dias === 1 ? "Mañana" : `En ${p0.dias} días`) : "—";
  $("#kpi-prox-titulo").textContent = p0 ? p0.titulo : "Sin pendientes próximos";
  const mas = $("#prox-mas");
  if (mas) mas.onclick = () => { proxTodos = !proxTodos; pintarProximos(); };
}

// ---------------------------------------------------------------- gráficos

function pintarSemana() {
  const sem = datos.semana || [];
  const caja = $("#barras");
  if (!sem.length) { caja.innerHTML = '<p class="vacio">Sin datos de la semana.</p>'; return; }
  const max = Math.max(...sem.map((d) => d.horas), 1);
  const tope = Math.max(2, Math.ceil(max / 2) * 2);            // eje en pasos de 2 h
  const iMax = sem.findIndex((d) => d.horas === max);
  const total = sem.reduce((a, d) => a + d.horas, 0);
  $("#semana-sub").textContent = `${Math.round(total * 10) / 10} h ocupadas en los próximos 7 días`;
  const lineas = [tope, tope / 2, 0].map((v) => `<div class="eje"><span>${v} h</span><i></i></div>`).join("");
  const columnas = sem.map((d, i) => {
    const f = fechaLocal(d.fecha);
    const alto = d.horas ? Math.max(3, (d.horas / tope) * 100) : 0;
    const dia = i === 0 ? "Hoy" : DSEM[f.getDay()];
    const detalle = `${d.horas} h · ${d.eventos} evento${d.eventos === 1 ? "" : "s"}${d.tareas ? ` · ${d.tareas} tarea${d.tareas === 1 ? "" : "s"} vence${d.tareas === 1 ? "" : "n"}` : ""}`;
    return `<button class="col ${i === 0 ? "hoy" : ""}" data-f="${d.fecha}" aria-label="${dia} ${f.getDate()}: ${detalle}">
      <span class="tip"><b>${dia} ${f.getDate()}</b>${detalle}</span>
      <span class="pista">${i === 0 || i === iMax ? `<em style="bottom:${alto}%">${d.horas} h</em>` : ""}<i style="height:${alto}%"></i></span>
      <small>${dia}</small></button>`;
  }).join("");
  caja.innerHTML = `<div class="ejes">${lineas}</div><div class="cols">${columnas}</div>`;
  caja.querySelectorAll(".col").forEach((c) => c.onclick = () => {
    diaSel = c.dataset.f === datos.hoy_iso ? null : c.dataset.f;
    pintarAgenda();
    $("#dias").scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

function pintarDona() {
  const cuenta = (e) => datos.tareas.filter((t) => t.estado === e).length;
  const partes = [
    { n: "Vencidas", v: cuenta("vencida"), c: "var(--critico)" },
    { n: "Para hoy", v: cuenta("hoy"), c: "var(--aviso)" },
    { n: "Con fecha próxima", v: cuenta("futura"), c: "var(--brand)" },
    { n: "Sin fecha", v: cuenta("sin_fecha"), c: "var(--neutro)" },
  ];
  const total = partes.reduce((a, p) => a + p.v, 0);
  const R = 42, L = 2 * Math.PI * R, hueco = total && partes.filter((p) => p.v).length > 1 ? 3 : 0;
  let pos = 0;
  const arcos = partes.filter((p) => p.v).map((p) => {
    const largo = (p.v / total) * L;
    const arco = `<circle cx="60" cy="60" r="${R}" fill="none" stroke="${p.c}" stroke-width="15"
      stroke-dasharray="${Math.max(largo - hueco, 1)} ${L}" stroke-dashoffset="${-pos}"><title>${p.n}: ${p.v}</title></circle>`;
    pos += largo;
    return arco;
  }).join("");
  $("#dona").innerHTML = `
    <div class="dona">
      <svg viewBox="0 0 120 120" role="img" aria-label="Tareas por estado">
        <circle cx="60" cy="60" r="${R}" fill="none" stroke="var(--line)" stroke-width="15"/>${arcos}
      </svg>
      <div class="dona-centro"><b>${total}</b><span>pendiente${total === 1 ? "" : "s"}</span></div>
    </div>
    <div class="leyenda">${partes.map((p) => `<div><i style="background:${p.c}"></i><span>${p.n}</span><b>${p.v}</b></div>`).join("")}</div>`;
}

function pintarTodo() {
  pintarSemana();
  pintarDona();
  pintarProximos();
  pintarMetas();
  pintarProgreso();
  pintarPlan();
  pintarAgenda();
  pintarTareas();
}

// ---------------------------------------------------------------- progreso

function pintarProgreso() {
  const agendaHecha = datos.eventos.filter((e) => e.hecho).length;
  const agendaPend = datos.eventos.length - agendaHecha;
  const hechas = datos.completadas.length + agendaHecha;
  const urgentes = datos.tareas.filter((t) => t.estado === "vencida" || t.estado === "hoy").length;
  const total = hechas + urgentes + agendaPend;
  const pct = total ? Math.round((hechas / total) * 100) : (hechas ? 100 : 0);
  $("#pct").textContent = pct + "%";
  $("#anillo-arco").style.strokeDashoffset = 150.8 * (1 - pct / 100);
  $("#st-hechas").textContent = hechas;
  $("#st-urgentes").textContent = urgentes;
  $("#st-eventos").textContent = datos.eventos.length;
  $("#st-pendientes").textContent = datos.tareas.length;
  $("#st-metas").textContent = (datos.metas || []).length;
  $("#st-pomos").textContent = leer("pomodoros-" + hoyClave(), 0);
  $("#nav-tareas").textContent = urgentes || "";
}

// ---------------------------------------------------------------- plan

function pintarPlan() {
  const caja = $("#plan");
  const plan = datos.plan;
  const formulario = `
    ${datos.ia ? '<textarea class="nota-input" id="nota" rows="2" placeholder="Indicaciones opcionales: “hoy salgo a las 6”, “estoy con poca energía”…"></textarea>' : '<div style="height:10px"></div>'}
    <button class="btn block" id="btn-plan">${ico("chispa")}${plan ? "Rehacer mi plan" : "Generar mi plan"}</button>`;
  if (!plan) {
    caja.innerHTML = `<p class="plan-vacio">${datos.ia ? "Orga revisa tu agenda, tus tareas y tus metas, y arma un día realista con bloques de enfoque y descansos." : "Ordeno tus tareas por urgencia y las acomodo en tus horas libres, con pausas."}</p>${formulario}`;
    $("#btn-plan").onclick = generarPlan;
    $("#plan-hora").textContent = "";
    return;
  }
  $("#plan-hora").textContent = "Creado a las " + plan.generado;
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
    ${plan.otro_dia && plan.otro_dia.length ? `<div class="nota-plan">${ico("caja")}<span>Mejor para otro día: ${plan.otro_dia.map(esc).join(", ")}</span></div>` : ""}
    <div class="nota-plan consejo">${ico("idea")}<span>${esc(sinEmoji(plan.consejo))}</span></div>
    <div class="fila-btn">
      <button class="btn ${plan.agendado ? "sec" : ""}" id="btn-agendar">${plan.agendado ? ico("check") + "En tu calendario" : ico("calendario") + "Poner en Google Calendar"}</button>
    </div>
    <details class="rehacer"><summary>Rehacer el plan</summary>${formulario}</details>`;
  $("#btn-plan").onclick = generarPlan;
  $("#btn-agendar").onclick = agendar;
}

async function generarPlan() {
  const btn = $("#btn-plan");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Orga está armando tu plan…';
  try {
    datos.plan = await api("/api/plan", { nota: ($("#nota") || {}).value || "" });
    pintarPlan();
    toast("¡Tu plan está listo! ✨");
  } catch (e) {
    toast("😕 " + e.message);
    btn.disabled = false;
    btn.textContent = "Intentar de nuevo";
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

// La agenda se puede ver por día: hoy (con casillas) y los 6 días siguientes
let diaSel = null;            // null = hoy; si no, fecha "AAAA-MM-DD"
let diasCache = {};

function fechaLocal(iso) { return new Date(iso + "T12:00:00"); }
function sumarDias(iso, n) {
  const d = fechaLocal(iso); d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function pintarDias() {
  const hoy = datos.hoy_iso;
  $("#dias").innerHTML = Array.from({ length: 7 }, (_, i) => {
    const iso = sumarDias(hoy, i), f = fechaLocal(iso);
    const activo = (diaSel || hoy) === iso;
    return `<button class="dia ${activo ? "on" : ""}" data-f="${iso}"><small>${i === 0 ? "hoy" : i === 1 ? "mañ" : DSEM[f.getDay()]}</small><b>${f.getDate()}</b></button>`;
  }).join("");
}

function filaEvento(e, conCasilla) {
  return `<div class="evento-item ${e.hecho ? "hecho" : ""} ${e.organizador ? "de-orga" : ""}" data-id="${esc(e.id)}">
    ${conCasilla ? `<button class="check" title="${e.hecho ? "Marcar como pendiente" : "Marcar como cumplido"}">${ico("check")}</button>` : '<i class="marca-dia"></i>'}
    <div class="h">${e.todo_el_dia ? "Todo el día" : esc(e.inicio) + " – " + esc(e.fin)}</div>
    <div class="e">${esc(sinEmoji(e.titulo) || e.titulo)}${e.organizador ? ' <span class="badge plan">Plan de Orga</span>' : e.calendario ? ` <small>· ${esc(e.calendario)}</small>` : ""}</div></div>`;
}

async function pintarAgenda() {
  pintarDias();
  const hoy = datos.hoy_iso;
  const iso = diaSel || hoy;
  const esHoy = iso === hoy;
  const f = fechaLocal(iso);
  $("#agenda-titulo").textContent = esHoy ? "Agenda de hoy" : iso === sumarDias(hoy, 1) ? "Agenda de mañana" : `Agenda del ${DSEM[f.getDay()]} ${f.getDate()}`;

  let ev, tareas = [];
  if (esHoy) {
    ev = datos.eventos;
  } else {
    if (!diasCache[iso]) {
      $("#agenda").innerHTML = '<p class="vacio"><span class="spinner"></span> Cargando…</p>';
      $("#agenda-cuenta").textContent = "";
      try { diasCache[iso] = await api("/api/dia?fecha=" + iso); }
      catch (e) { if ((diaSel || hoy) === iso) $("#agenda").innerHTML = `<p class="vacio">${esc(e.message)}</p>`; return; }
      if ((diaSel || hoy) !== iso) return;   // cambió de día mientras cargaba
    }
    ev = diasCache[iso].eventos; tareas = diasCache[iso].tareas;
  }

  const bloques = ev.filter((e) => e.organizador).length;
  $("#agenda").innerHTML = (ev.length
    ? ev.map((e) => filaEvento(e, esHoy)).join("")
    : `<p class="vacio">${esHoy ? "Sin eventos hoy: tienes el día libre para avanzar." : "Todavía no hay nada programado para este día."}</p>`)
    + (tareas.length ? `<div class="tareas-dia"><b>Tareas que vencen este día</b>${tareas.map((t) => `<div>${ico("tareas")}<span>${esc(t)}</span></div>`).join("")}</div>` : "")
    + (!esHoy && datos.agente ? `<button class="link" id="planear-dia">${ico("chispa")}${bloques ? "Pedir a Orga que ajuste este día" : "Pedir a Orga que planifique este día"}</button>` : "");

  if (esHoy) {
    const cumplidos = ev.filter((e) => e.hecho).length;
    $("#agenda-cuenta").textContent = ev.length ? `${cumplidos} de ${ev.length} cumplido${ev.length === 1 ? "" : "s"}` : "";
    $$("#agenda .evento-item").forEach((el) => {
      const e = ev.find((x) => x.id === el.dataset.id);
      el.querySelector(".check").onclick = () => marcarEvento(e);
    });
  } else {
    $("#agenda-cuenta").textContent = ev.length ? `${ev.length} evento${ev.length === 1 ? "" : "s"}${bloques ? ` · ${bloques} de Orga` : ""}` : "";
    const btn = $("#planear-dia");
    if (btn) btn.onclick = () => {
      irA("agente");
      const nombre = iso === sumarDias(hoy, 1) ? "mañana" : `el ${DSEM[f.getDay()]} ${f.getDate()}`;
      enviarChat(`Planifica mi día de ${nombre} (${iso}): revisa mis eventos, mis tareas y mis metas, y agenda bloques realistas en mi calendario.`);
    };
  }
}

$("#dias").addEventListener("click", (e) => {
  const b = e.target.closest(".dia");
  if (!b) return;
  diaSel = b.dataset.f === datos.hoy_iso ? null : b.dataset.f;
  pintarAgenda();
});

async function marcarEvento(e) {
  e.hecho = !e.hecho;
  pintarAgenda(); pintarProgreso();
  try {
    await api("/api/agenda/marcar", { id: e.id, hecho: e.hecho });
    if (e.hecho) toast("Cumplido: " + e.titulo);
  } catch (err) {
    e.hecho = !e.hecho;
    pintarAgenda(); pintarProgreso();
    toast(err.message);
  }
}

// ---------------------------------------------------------------- tareas

function pintarTareas() {
  let lista = datos.tareas;
  if (filtro === "urgentes") lista = lista.filter((t) => t.estado === "vencida" || t.estado === "hoy");
  if (filtro === "sin_fecha") lista = lista.filter((t) => t.estado === "sin_fecha");
  $("#tareas-cuenta").textContent = `${datos.tareas.length} pendiente${datos.tareas.length === 1 ? "" : "s"}`;
  const etiqueta = (t) => {
    if (t.estado === "vencida") return '<span class="badge vencida">Vencida</span>';
    if (t.estado === "hoy") return '<span class="badge hoy">Hoy</span>';
    if (t.estado === "futura") return `<span class="badge futura">${t.vence.slice(8, 10)}/${t.vence.slice(5, 7)}</span>`;
    return "";
  };
  $("#tareas").innerHTML = lista.length ? lista.map((t) => `
    <div class="tarea-item" data-id="${esc(t.id)}">
      <button class="check" title="Completar">${ico("check")}</button>
      <div class="tt"><div>${esc(t.titulo)}</div><div class="meta">${etiqueta(t)}<span>${esc(t.lista)}</span></div></div>
      <button class="icon-btn chico fantasma enfocar" title="Enfocarme en esta">${ico("reloj")}</button>
    </div>`).join("")
    : '<p class="vacio" style="padding:10px 0">No hay tareas en esta vista.</p>';
  const hechas = datos.completadas;
  $("#hechas-hoy").innerHTML = hechas.length ? "Completadas hoy: " + hechas.map((t) => `<s>${esc(t)}</s>`).join(", ") : "";

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

function botonPomo(estado) {
  $("#pomo-iniciar").innerHTML = estado === "pausar" ? ico("pausa") + "Pausar" : ico("play") + (estado === "seguir" ? "Seguir" : "Empezar");
}

const pomo = { duracion: 25 * 60, restante: 25 * 60, timer: null, fin: 0, modo: 25 };

function pintarReloj() {
  const m = Math.floor(pomo.restante / 60), s = pomo.restante % 60;
  $("#reloj").textContent = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  document.title = pomo.timer ? `${$("#reloj").textContent} · Orga` : "Orga";
  $("#reloj-arco").style.strokeDashoffset = 678.6 * (1 - pomo.restante / pomo.duracion);
  const ciclos = leer("pomodoros-" + hoyClave(), 0);
  $("#ciclos").textContent = `${ciclos} pomodoro${ciclos === 1 ? "" : "s"} hoy`;
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
    botonPomo("empezar");
    sonar();
    if (pomo.modo === 25) {
      guardar("pomodoros-" + hoyClave(), leer("pomodoros-" + hoyClave(), 0) + 1);
      toast("🍅 ¡Pomodoro terminado! Toma una pausa.");
      if ("Notification" in window && Notification.permission === "granted") new Notification("Pomodoro terminado. Toma una pausa.");
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
    botonPomo("seguir");
  } else {
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    pomo.fin = Date.now() + pomo.restante * 1000;
    pomo.timer = setInterval(tick, 500);
    botonPomo("pausar");
  }
  pintarReloj();
};
$("#pomo-reiniciar").onclick = () => {
  clearInterval(pomo.timer); pomo.timer = null;
  pomo.restante = pomo.duracion;
  botonPomo("empezar");
  pintarReloj();
};
$$(".modos .chip").forEach((b) => b.onclick = () => {
  $$(".modos .chip").forEach((c) => c.classList.toggle("on", c === b));
  clearInterval(pomo.timer); pomo.timer = null;
  pomo.modo = Number(b.dataset.min);
  pomo.duracion = pomo.restante = pomo.modo * 60;
  botonPomo("empezar");
  pintarReloj();
});

function enfocar(t) {
  $("#pomo-tarea").textContent = "Enfocado en: " + t.titulo;
  irA("enfoque");
  toast("🎯 Dale a Empezar cuando estés listo");
}

// ---------------------------------------------------------------- coach (mensaje motivador)

async function cargarCoach(nuevo) {
  if (!datos || !datos.agente) { $("#card-coach").hidden = true; return; }
  $("#card-coach").hidden = false;
  if (nuevo) { $("#coach-titulo").innerHTML = '<span class="spinner"></span> Pensando en ti…'; }
  try {
    const r = await api("/api/motivacion" + (nuevo ? "?nuevo=1" : ""));
    const m = r.motivacion;
    if (!m) { $("#card-coach").hidden = true; return; }
    $("#coach-titulo").textContent = sinEmoji(m.titulo);
    $("#coach-msg").textContent = m.mensaje;
    $("#coach-enfoque").innerHTML = m.enfoque.map((p, i) => `<div class="paso"><b>${i + 1}</b><span>${esc(p)}</span></div>`).join("");
  } catch (e) {
    $("#coach-titulo").textContent = "Hoy es un buen día para avanzar";
    $("#coach-enfoque").innerHTML = "";
    $("#coach-msg").textContent = e.message;
  }
}
$("#coach-otro").onclick = () => cargarCoach(true);
$("#coach-hablar").onclick = () => irA("agente");
$("#ir-enfoque").onclick = () => irA("enfoque");
$("#planificar-semana").onclick = () => {
  irA("agente");
  enviarChat("Planifica mi semana: reparte mis tareas y mis metas en bloques realistas en mi calendario para los próximos 7 días.");
};
$("#form-pedir").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#pedir-input").value.trim();
  if (!v) return;
  $("#pedir-input").value = "";
  irA("agente");
  enviarChat(v);
});

// ---------------------------------------------------------------- metas

function pintarMetas() {
  const lista = datos.metas || [];
  $("#metas").innerHTML = lista.length ? lista.map((m) => `
    <div class="meta-item" data-id="${esc(m.id)}">
      <div class="ico">${ico("meta")}</div>
      <div class="mt"><b>${esc(m.texto)}</b>${m.porque ? `<small>${esc(m.porque)}</small>` : ""}
        ${datos.agente ? `<button class="link plan-meta">${ico("chispa")}Pedir a Orga un plan para esta meta</button>` : ""}
      </div>
      <button class="icon-btn chico fantasma quitar" title="Quitar">${ico("x")}</button>
    </div>`).join("")
    : '<p class="vacio" style="margin-bottom:10px">Todavía no tienes metas. Empieza con una a tres: estudios, salud, dinero o algo personal.</p>';
  $$("#metas .meta-item").forEach((el) => {
    const m = lista.find((x) => x.id === el.dataset.id);
    el.querySelector(".quitar").onclick = async () => {
      if (!confirm(`¿Quitar la meta "${m.texto}"?`)) return;
      datos.metas = (await api("/api/metas/" + m.id, null, "DELETE")).metas;
      pintarMetas();
    };
    const plan = el.querySelector(".plan-meta");
    if (plan) plan.onclick = () => {
      irA("agente");
      enviarChat(`Quiero cumplir esta meta: "${m.texto}". Divídela en pasos pequeños, dime qué hago esta semana y agenda los bloques en mi calendario.`);
    };
  });
}

$("#form-meta").addEventListener("submit", async (e) => {
  e.preventDefault();
  const texto = $("#meta-texto").value.trim();
  if (!texto) return;
  try {
    datos.metas = (await api("/api/metas", { texto, porque: $("#meta-porque").value })).metas;
    $("#meta-texto").value = ""; $("#meta-porque").value = "";
    pintarMetas();
    toast("🏁 ¡Meta guardada! Orga la tendrá en cuenta");
  } catch (err) { toast("😕 " + err.message); }
});

// ---------------------------------------------------------------- agente (chat)

const BIENVENIDA = "Hola, soy Orga, tu agente personal de productividad. Conozco tu agenda, tus tareas y tus metas, y puedo crear, mover y completar cosas por ti. ¿Por dónde empezamos?";

function pintarChat() {
  const caja = $("#mensajes");
  if (datos && !datos.ia) {
    caja.innerHTML = '<div class="msg assistant">Para activar a Orga falta la clave gratuita de Gemini (GEMINI_API_KEY). Todo lo demás de la app ya funciona.</div>';
    $("#form-chat").style.display = "none";
    $("#acciones-rapidas").style.display = "none";
    return;
  }
  $("#agente-modo").innerHTML = '<i class="punto"></i>' + (datos && datos.agente ? "En línea · puede actuar en tu Calendar y Tasks" : "Asistente");
  caja.innerHTML = `<div class="msg assistant">${esc(BIENVENIDA)}</div>` + chat.map((m, i) => `
    <div class="msg ${m.role}">${m.role === "assistant" ? md(m.content) : esc(m.content)}${m.foto && !m.role.startsWith("a") ? " <small>(con imagen)</small>" : ""}${m.acciones && m.acciones.length
      ? `<div class="acciones">${m.acciones.map((a) => `<span class="accion">${ico("check")}${esc(sinEmoji(a))}</span>`).join("")}</div>` : ""}${m.role === "assistant" && datos && datos.agente
      ? `<button class="escuchar" data-i="${i}" title="Escuchar">${ico("voz")}<span>Escuchar</span></button>` : ""}</div>`).join("");
  caja.scrollTop = caja.scrollHeight;
}

let imagenAdjunta = null;

async function enviarChat(texto) {
  if (!texto.trim() && imagenAdjunta) texto = "Te envío esta imagen. Revísala y ayúdame a organizar lo que aparece.";
  if (!texto.trim()) return;
  if (datos && !datos.ia) { toast("Falta la clave de Gemini"); return; }
  const imagen = imagenAdjunta;
  quitarAdjunto();
  chat.push({ role: "user", content: texto.trim(), foto: imagen ? true : undefined });
  pintarChat();
  if (imagen) {
    const ultimo = $("#mensajes").lastElementChild;
    ultimo.insertAdjacentHTML("afterbegin", `<img class="foto" src="${imagen}" alt="">`);
  }
  const caja = $("#mensajes");
  caja.insertAdjacentHTML("beforeend", '<div class="msg assistant"><span class="spinner"></span> Orga está pensando…</div>');
  caja.scrollTop = caja.scrollHeight;
  try {
    const historial = chat.map(({ role, content }) => ({ role, content }));
    const r = await api("/api/chat", { historial, imagen });
    chat.push({ role: "assistant", content: r.respuesta, acciones: r.acciones || [] });
    hablar(r.respuesta);
    if (r.acciones && r.acciones.length) cargar(true);
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
$("#acciones-rapidas").addEventListener("click", (e) => {
  const b = e.target.closest(".rapida");
  if (b) enviarChat(b.dataset.p);
});
$("#btn-chat-nuevo").onclick = () => {
  chat = []; guardar("chat-" + hoyClave(), chat); pintarChat();
};

// ---------------------------------------------------------------- fotos para el agente

function quitarAdjunto() {
  imagenAdjunta = null;
  $("#adjunto").hidden = true;
  $("#input-foto").value = "";
}
$("#adjunto-quitar").onclick = quitarAdjunto;
$("#btn-foto").onclick = () => $("#input-foto").click();
$("#input-foto").addEventListener("change", (e) => {
  const archivo = e.target.files[0];
  if (!archivo) return;
  const img = new Image();
  img.onload = () => {
    // Achicar la foto para que viaje rápido (máx. 1600 px)
    const escala = Math.min(1, 1600 / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.round(img.width * escala); c.height = Math.round(img.height * escala);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    imagenAdjunta = c.toDataURL("image/jpeg", 0.85);
    $("#adjunto-img").src = imagenAdjunta;
    $("#adjunto").hidden = false;
    URL.revokeObjectURL(img.src);
    $("#chat-input").focus();
  };
  img.onerror = () => toast("No pude abrir esa imagen");
  img.src = URL.createObjectURL(archivo);
});

// ---------------------------------------------------------------- voz

let vozSalida = leer("voz-salida", false);
function pintarVozSalida() { $("#btn-voz-salida").innerHTML = ico(vozSalida ? "voz" : "voz-off"); }
$("#btn-voz-salida").onclick = () => {
  vozSalida = !vozSalida; guardar("voz-salida", vozSalida); pintarVozSalida();
  toast(vozSalida ? "🔊 Orga leerá sus respuestas" : "🔇 Respuestas sin voz");
  if (!vozSalida) callarVoz();
};
// La voz se genera en el servidor (voz masculina natural). Si falla, se usa la del dispositivo.
const audioOrga = new Audio();
let vozPedido = 0;

function textoParaVoz(texto) {
  return sinEmoji(texto).replace(/[*_#`>]/g, "").replace(/•/g, ",").replace(/\s+/g, " ").trim();
}

function callarVoz() {
  vozPedido++;
  audioOrga.pause();
  if (window.speechSynthesis) speechSynthesis.cancel();
  $$(".escuchar.sonando").forEach((b) => b.classList.remove("sonando"));
}

function vozDelDispositivo(texto) {
  if (!window.speechSynthesis) return;
  const voces = speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("es"));
  const hombre = /jorge|diego|pablo|alvaro|álvaro|raul|raúl|carlos|juan|enrique|alonso|tomas|tomás|jaime|gerardo|male|hombre/i;
  const u = new SpeechSynthesisUtterance(texto);
  u.lang = "es-PE";
  u.voice = voces.find((v) => hombre.test(v.name)) || voces[0] || null;
  u.pitch = 0.85; u.rate = 1.02;
  speechSynthesis.speak(u);
}

async function decir(texto, boton) {
  callarVoz();
  const limpio = textoParaVoz(texto);
  if (!limpio) return;
  const pedido = vozPedido;
  if (boton) boton.classList.add("sonando");
  const terminar = () => { if (boton) boton.classList.remove("sonando"); };
  try {
    const r = await fetch("/api/hablar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto: limpio }) });
    if (!r.ok) throw new Error("sin voz");
    const url = URL.createObjectURL(await r.blob());
    if (pedido !== vozPedido) { URL.revokeObjectURL(url); return; }
    audioOrga.src = url;
    audioOrga.onended = audioOrga.onerror = () => { URL.revokeObjectURL(url); terminar(); };
    await audioOrga.play();
  } catch (e) {
    if (pedido !== vozPedido) return;
    terminar();
    vozDelDispositivo(limpio);
  }
}

function hablar(texto) {
  if (vozSalida) decir(texto);
}

$("#mensajes").addEventListener("click", (e) => {
  const b = e.target.closest(".escuchar");
  if (!b) return;
  if (b.classList.contains("sonando")) { callarVoz(); return; }
  const m = chat[Number(b.dataset.i)];
  if (m) decir(m.content, b);
});

// ---- mensajes de voz: se graba el audio, se convierte a WAV y Orga lo transcribe

const VOZ_MAX = 90; // segundos
const voz = { grabando: false, medio: null, flujo: null, trozos: [], inicio: 0, reloj: null, cancelar: false };

function pintarGrabacion() {
  const seg = Math.floor((Date.now() - voz.inicio) / 1000);
  $("#grabando-tiempo").textContent = `${Math.floor(seg / 60)}:${String(seg % 60).padStart(2, "0")}`;
  if (seg >= VOZ_MAX) detenerGrabacion(false);
}

function modoGrabacion(activo) {
  voz.grabando = activo;
  $("#form-chat").classList.toggle("rec-on", activo);
  $("#grabando").hidden = !activo;
  $("#chat-input").hidden = activo;
  $("#btn-foto").hidden = activo;
  $("#btn-mic").classList.toggle("escuchando", activo);
  $("#btn-mic").title = activo ? "Detener y enviar" : "Grabar mensaje de voz";
}

async function iniciarGrabacion() {
  if (datos && !datos.agente) { toast("Los mensajes de voz necesitan la clave de Gemini"); return; }
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    toast("Tu navegador no permite grabar audio. Prueba con Chrome o Safari."); return;
  }
  try {
    voz.flujo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (e) {
    toast(e.name === "NotAllowedError"
      ? "Permite el micrófono: toca el candado junto a la dirección y activa Micrófono"
      : "No encontré un micrófono en este dispositivo");
    return;
  }
  voz.trozos = []; voz.cancelar = false;
  voz.medio = new MediaRecorder(voz.flujo);
  voz.medio.ondataavailable = (e) => { if (e.data.size) voz.trozos.push(e.data); };
  voz.medio.onstop = terminarGrabacion;
  voz.medio.start();
  voz.inicio = Date.now();
  modoGrabacion(true);
  pintarGrabacion();
  voz.reloj = setInterval(pintarGrabacion, 250);
}

function detenerGrabacion(cancelar) {
  if (!voz.grabando) return;
  voz.cancelar = cancelar;
  clearInterval(voz.reloj);
  modoGrabacion(false);
  if (voz.medio && voz.medio.state !== "inactive") voz.medio.stop();
}

// Convierte lo grabado (webm, mp4…) a WAV mono de 16 kHz, que la IA entiende en cualquier navegador
async function aWav(blob) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  const audio = await ctx.decodeAudioData(await blob.arrayBuffer());
  ctx.close();
  const tasa = 16000;
  const largo = Math.max(1, Math.round(audio.duration * tasa));
  const off = new OfflineAudioContext(1, largo, tasa);
  const fuente = off.createBufferSource();
  fuente.buffer = audio; fuente.connect(off.destination); fuente.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const vista = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const txt = (pos, t) => { for (let i = 0; i < t.length; i++) vista.setUint8(pos + i, t.charCodeAt(i)); };
  txt(0, "RIFF"); vista.setUint32(4, 36 + pcm.length * 2, true); txt(8, "WAVEfmt ");
  vista.setUint32(16, 16, true); vista.setUint16(20, 1, true); vista.setUint16(22, 1, true);
  vista.setUint32(24, tasa, true); vista.setUint32(28, tasa * 2, true); vista.setUint16(32, 2, true);
  vista.setUint16(34, 16, true); txt(36, "data"); vista.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) {
    const v = Math.max(-1, Math.min(1, pcm[i]));
    vista.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return new Blob([vista], { type: "audio/wav" });
}

const aDataUrl = (blob) => new Promise((ok, mal) => {
  const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = mal; r.readAsDataURL(blob);
});

async function terminarGrabacion() {
  voz.flujo.getTracks().forEach((t) => t.stop());
  const duracion = (Date.now() - voz.inicio) / 1000;
  if (voz.cancelar) return;
  if (duracion < 0.7 || !voz.trozos.length) { toast("Mensaje muy corto: mantén la grabación un poco más"); return; }
  const caja = $("#mensajes");
  caja.insertAdjacentHTML("beforeend", '<div class="msg user" id="voz-pendiente"><span class="spinner"></span> Enviando mensaje de voz…</div>');
  caja.scrollTop = caja.scrollHeight;
  try {
    const wav = await aWav(new Blob(voz.trozos, { type: voz.medio.mimeType }));
    const r = await api("/api/voz", { audio: await aDataUrl(wav) });
    const p = $("#voz-pendiente"); if (p) p.remove();
    enviarChat(r.texto);
  } catch (e) {
    const p = $("#voz-pendiente"); if (p) p.remove();
    toast(e.message || "No pude procesar el audio");
  }
}

$("#btn-mic").onclick = () => (voz.grabando ? detenerGrabacion(false) : iniciarGrabacion());
$("#grabando-cancelar").onclick = () => detenerGrabacion(true);

// ---------------------------------------------------------------- pestañas (celular)

function irA(vista) {
  $$(".vista").forEach((v) => v.classList.toggle("activa", v.dataset.vista === vista));
  $$("#tabs button, #nav button").forEach((b) => b.classList.toggle("on", b.dataset.vista === vista));
  guardar("vista", vista);
  window.scrollTo({ top: 0 });
}
["#tabs", "#nav"].forEach((sel) => $(sel).addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) irA(b.dataset.vista);
}));

$$(".js-recargar").forEach((b) => b.onclick = () => { toast("Actualizando…"); cargar(true); });

// ---------------------------------------------------------------- inicio

chat = leer("chat-" + hoyClave(), []);
pintarVozSalida();
botonPomo("empezar");
pintarReloj();
irA(leer("vista", "hoy"));
cargar();
