# 🗓️ Organizador

Tu asistente personal de productividad. Lee tu **Google Calendar** y tus **Google Tasks**, y con **Claude** (IA de Anthropic) arma un plan realista para tu día:

- Respeta tus reuniones y eventos.
- Acomoda tus tareas en los huecos libres, empezando por las vencidas y urgentes.
- Pone el trabajo pesado en tus mejores horas y agrega descansos.
- Si no cabe todo, te dice qué conviene dejar para otro día.
- Opcional: crea los bloques de trabajo directamente en tu Google Calendar.

```
============================================================
  🌟 TU PLAN PARA HOY (2026-11-09)
============================================================

Tienes una mañana con un buen hueco antes de la reunión: úsalo para el reporte vencido...

🏆 Prioridades:
   1. Enviar el reporte (está vencido)
   2. Preparar la presentación del jueves
   3. Ir al gym

🗓️  Agenda:
   08:15-09:45  ✅ Enviar reporte
                 ↳ Empieza por el resumen ejecutivo
   09:45-10:00  ☕ Descanso
   10:00-11:00  📅 Reunión equipo
   ...
```

---

## 📱 App web (PC y celular)

Además de la terminal, el Organizador tiene una **app web** con:

- ☀️ **Hoy:** tu progreso del día, el plan creado por Claude en una línea de tiempo y tu agenda.
- 📝 **Tareas:** marca tareas como hechas, crea nuevas y filtra las urgentes.
- 🎯 **Enfoque:** temporizador Pomodoro conectado a tus tareas.
- 🤖 **Asistente:** chatea con Claude sobre tu día ("¿qué hago ahora?", "estoy cansado, reorganiza").

Se puede publicar en internet (por ejemplo en Railway) y en el celular se instala como app con
"Agregar a pantalla de inicio".

**Variables necesarias en el servidor:** `ANTHROPIC_API_KEY`, `APP_PASSWORD`, `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `ZONA_HORARIA`, `HORA_INICIO`, `HORA_FIN` y `CARPETA_DATOS=/data` (con un volumen
montado en `/data`). El cliente de Google debe ser de tipo **Aplicación web**, con la URI de redirección
`https://TU-DOMINIO/google/callback`.

**Probarla en tu PC:** `py -m organizador.web` y abre http://localhost:8000
(la URI de redirección local es `http://localhost:8000/google/callback`).

---

## 🚀 Instalación (una sola vez)

### 1. Instala Python y las dependencias

Necesitas Python 3.10 o más reciente. En una terminal, dentro de esta carpeta:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Conecta tu cuenta de Google

1. Entra a [Google Cloud Console](https://console.cloud.google.com/) y crea un proyecto nuevo (por ejemplo "Organizador").
2. Ve a **APIs y servicios → Biblioteca** y habilita:
   - **Google Calendar API**
   - **Google Tasks API**
3. Ve a **APIs y servicios → Pantalla de consentimiento de OAuth**:
   - Tipo de usuario: **Externo**.
   - Completa el nombre de la app y tu correo.
   - En **Usuarios de prueba**, agrega tu propio correo de Gmail.
4. Ve a **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**:
   - Tipo de aplicación: **App de escritorio**.
   - Descarga el archivo JSON, renómbralo a **`credentials.json`** y ponlo en esta carpeta.

> La primera vez que uses el Organizador se abrirá el navegador para que inicies sesión con Google y aceptes los permisos. Después se guarda un `token.json` y ya no te lo vuelve a pedir.

### 3. Consigue tu clave de Claude

1. Entra a [platform.claude.com](https://platform.claude.com/) y crea una **API key**.
2. Copia el archivo `.env.example` con el nombre `.env` y pega tu clave:

```env
ANTHROPIC_API_KEY=sk-ant-...
ZONA_HORARIA=America/Mexico_City
HORA_INICIO=08:00
HORA_FIN=20:00
CALENDARIO_ID=primary
```

Ajusta tu zona horaria y tu horario productivo.

> 🔒 `credentials.json`, `token.json` y `.env` son privados: el `.gitignore` evita que se suban a GitHub.

---

## 📋 Cómo se usa

| Comando | Qué hace |
|---|---|
| `python -m organizador plan` | Claude arma tu plan de hoy |
| `python -m organizador plan --agendar` | Arma el plan y (si confirmas) crea los bloques en tu calendario |
| `python -m organizador plan --manana` | Planifica el día de mañana (ideal por la noche) |
| `python -m organizador plan --nota "hoy salgo a las 5"` | Le das indicaciones extra a Claude |
| `python -m organizador agenda` | Muestra tus eventos de hoy |
| `python -m organizador tareas` | Lista tus tareas pendientes numeradas |
| `python -m organizador completar 3` | Marca como hecha la tarea número 3 |
| `python -m organizador nueva "Llamar al banco" --hoy` | Crea una tarea que vence hoy |
| `python -m organizador limpiar` | Borra los bloques que el Organizador creó hoy |

### Rutina recomendada

- ☀️ **En la mañana:** `plan --agendar` → revisa y acepta.
- ✅ **Durante el día:** `completar N` cuando termines algo.
- 🔄 **Si el día cambió:** vuelve a correr `plan --agendar`. Los bloques anteriores del Organizador se reemplazan solos; tus eventos normales nunca se tocan.
- 🌙 **En la noche:** `plan --manana` para ver cómo viene el día siguiente.

---

## 🧩 Estructura del proyecto

```
organizador/
├── web.py           # App web (Flask)
├── templates/       # Páginas HTML
├── static/          # Diseño (CSS), lógica de la pantalla (JS) e ícono
├── __main__.py      # Comandos de la terminal
├── config.py        # Lee la configuración del .env
├── google_api.py    # Conexión con Google Calendar y Google Tasks
└── planificador.py  # Claude arma el plan del día
```

## 💰 Costo

Cada plan es una sola consulta a Claude. Con un día normal (unos cuantos eventos y tareas) cuesta unos pocos centavos de dólar.
