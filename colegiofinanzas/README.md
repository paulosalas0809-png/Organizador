# ColegioFinanzas OS

Gestión de las finanzas del colegio: una **Mini-App móvil** para que el personal autorizado registre
ingresos y gastos, y un **Panel Directivo** con indicadores semanales y mensuales, control de accesos,
libro caja auditable y envío automático de cada movimiento a Excel Online o Google Sheets.

| Entorno | Dirección | Quién entra |
|---|---|---|
| Panel Directivo | `/colegio` | Dirección, con el PIN maestro (por defecto `0000`: cámbialo) |
| Mini-App de caja | `/colegio?view=caja` | Personal autorizado, con su PIN de 4 dígitos |

## Arquitectura

```
colegiofinanzas/                 Proyecto Vite + React + Tailwind CSS + lucide-react + recharts
└── src/
    ├── App.jsx                  Rutas por URL (?view=caja) y PIN de Dirección
    ├── context/FinanceContext.jsx   Estado global: movimientos, personal, enlace de Excel, cola de envío
    ├── components/
    │   ├── MiniAppCaja.jsx      Registro rápido en 3 toques
    │   ├── AdminDashboard.jsx   Indicadores y gráficos semanales y mensuales
    │   ├── AccessManager.jsx    Alta, permisos, topes y bloqueo del personal
    │   ├── AuditTable.jsx       Libro caja: filtros, corrección y descarga CSV
    │   └── ExcelConnector.jsx   Enlace, prueba, pendientes y código para Sheets / Power Automate
    ├── services/api.js          Cliente del backend
    ├── services/excelSync.js    Prueba de conexión, pendientes y seguimiento de cada envío
    └── lib/format.js            Moneda, fechas y catálogos

organizador/colegio.py           Backend (Flask): datos, seguridad y envío a Excel
organizador/static/colegio/      App compilada (la genera `npm run build`)
```

### Por qué hay un backend

El celular de la secretaria y la computadora de Dirección no comparten datos entre sí. Para que los
registros lleguen al tablero y el bloqueo de un acceso sea inmediato, la información vive en el servidor:

- Los **PIN, permisos, topes y bloqueos se validan en el servidor**, no en el celular.
- La Mini-App solo recibe el perfil de quien entró y sus últimos 5 registros del día.
- El **enlace del Excel nunca llega al celular**: el servidor reenvía cada movimiento, con 3 intentos.
  Esto además evita el rechazo de Power Automate a las peticiones hechas desde un navegador.
- Tras 5 PIN incorrectos seguidos, el ingreso se pausa de forma creciente.

Los datos se guardan en `CARPETA_DATOS/colegio.json` (en Railway, el volumen `/data`).

## Desarrollo

```bash
# 1. Backend (desde la raíz del repositorio)
py -m organizador.web                 # http://localhost:8000

# 2. Interfaz (en otra terminal)
cd colegiofinanzas
npm install
npm run dev                           # http://localhost:5173/static/colegio/  (reenvía /api al backend)

# 3. Compilar para publicar
npm run build                         # escribe en organizador/static/colegio/
```

Después de compilar, sube los cambios: Railway publica la carpeta ya compilada, no ejecuta Node.

## Datos que se envían a Excel

`id, fecha, hora, semana, mes, tipo, categoria, concepto, monto, metodoPago, registradoPor`, más
`nOperacion` y `accion` (`crear`, `actualizar`, `eliminar` o `prueba`). La pestaña «Conexión con Excel»
trae el código de Apps Script y el esquema JSON para Power Automate.
