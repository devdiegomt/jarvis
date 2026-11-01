// JARVIS: widget para el iPhone con Scriptable (https://scriptable.app).
// Muestra el clima, la próxima reunión y los pendientes de hoy. Usa /api/hoy: no gasta IA.
//
// 1. Copia este archivo en un script nuevo de Scriptable.
// 2. Cambia URL por la dirección de `tailscale serve` (https://tu-pc.tu-red.ts.net).
// 3. Ejecútalo una vez: te pedirá la clave de `jarvis api-clave` y la guardará en el Llavero.
// 4. Agrega un widget de Scriptable a la pantalla de inicio y elige este script.

const URL = "https://tu-pc.tu-red.ts.net";
const KEY_NAME = "jarvis-clave";

const COLORS = {
  background: new Color("#0b1220"),
  accent: new Color("#38bdf8"),
  text: new Color("#e6edf7"),
  muted: new Color("#8a9bb5"),
  late: new Color("#f87171"),
};

async function askKey() {
  const alert = new Alert();
  alert.title = "Clave de JARVIS";
  alert.message = "La que te dio «jarvis api-clave». Se guarda en el Llavero del iPhone.";
  alert.addSecureTextField("Clave");
  alert.addAction("Guardar");
  alert.addCancelAction("Usar la guardada");
  if ((await alert.present()) === -1) return null;
  const key = alert.textFieldValue(0).trim();
  if (key) Keychain.set(KEY_NAME, key);
  return key || null;
}

async function loadToday(key) {
  const request = new Request(`${URL}/api/hoy`);
  request.headers = { Authorization: `Bearer ${key}` };
  request.timeoutInterval = 15;
  const data = await request.loadJSON();
  const status = request.response.statusCode;
  if (status === 401) throw new Error("Clave incorrecta: abre el script en Scriptable para cambiarla.");
  if (status !== 200) throw new Error(data.error || `Error ${status}`);
  return data;
}

function line(widget, text, color, size) {
  const item = widget.addText(text);
  item.textColor = color || COLORS.text;
  item.font = Font.systemFont(size || 13);
  item.lineLimit = 2;
  return item;
}

function build(data, error) {
  const widget = new ListWidget();
  widget.backgroundColor = COLORS.background;
  widget.url = URL;
  widget.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);

  const title = widget.addText("JARVIS");
  title.font = Font.boldSystemFont(12);
  title.textColor = COLORS.accent;
  widget.addSpacer(4);

  if (error) {
    line(widget, error, COLORS.late);
    return widget;
  }
  if (data.clima) line(widget, data.clima.linea, COLORS.muted, 12);
  widget.addSpacer(4);

  const next = data.proxima;
  if (next) line(widget, `${next.inicio}  ${next.titulo}`, COLORS.text, 15);
  else line(widget, data.reuniones.length ? "Sin más reuniones hoy" : "Sin reuniones hoy", COLORS.muted, 14);

  widget.addSpacer();
  const late = data.pendientes.filter((t) => t.atrasado).length;
  const tasks = data.pendientes.length
    ? `${data.pendientes.length} pendiente(s) para hoy${late ? `, ${late} atrasado(s)` : ""}`
    : "Nada pendiente para hoy";
  line(widget, tasks, late ? COLORS.late : COLORS.muted, 12);
  const reminder = data.recordatorios[0];
  if (reminder) line(widget, `⏰ ${reminder.hora} ${reminder.texto}`, COLORS.muted, 12);
  return widget;
}

let key = Keychain.contains(KEY_NAME) ? Keychain.get(KEY_NAME) : null;
if (config.runsInApp) key = (await askKey()) || key;

let widget;
try {
  if (!key) throw new Error("Abre el script en Scriptable para guardar la clave.");
  widget = build(await loadToday(key));
} catch (error) {
  widget = build(null, error.message || "No pude conectar con JARVIS (¿Tailscale activo?).");
}

if (config.runsInWidget) Script.setWidget(widget);
else await widget.presentMedium();
Script.complete();
