"""Ventana del Restaurador de BD. Usa pywebview: WebKit en Mac, WebView2 en
Windows, de modo que la ventana es nativa y la interfaz es HTML."""
import json
import os
import threading
from pathlib import Path

import webview

from . import nucleo

CONFIG = Path.home() / ".restaurador_bd.json"
TITULO = "Restaurador de BD"

HTML = r"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<style>
  :root{
    --fondo:#f6f7f9; --tarjeta:#fff; --borde:#dfe3e8; --texto:#1d2733;
    --suave:#6b7785; --acento:#1f6feb; --ok:#1a7f37; --error:#c3312f; --aviso:#9a6700;
  }
  @media (prefers-color-scheme: dark){
    :root{ --fondo:#15181d; --tarjeta:#1d2026; --borde:#2d323b; --texto:#e7eaee;
           --suave:#99a2ad; --acento:#539bf5; --ok:#57ab5a; --error:#e5534b; --aviso:#c69026; }
  }
  *{box-sizing:border-box}
  body{margin:0;font:14px -apple-system,"Segoe UI",system-ui,sans-serif;background:var(--fondo);
       color:var(--texto);padding:22px}
  h1{font-size:19px;margin:0 0 2px}
  .sub{color:var(--suave);margin:0 0 18px}
  .tarjeta{background:var(--tarjeta);border:1px solid var(--borde);border-radius:10px;
           padding:14px 16px;margin-bottom:14px}
  .tarjeta h2{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--suave);
              margin:0 0 10px;font-weight:600}
  label{display:block;font-size:12px;color:var(--suave);margin-bottom:4px}
  input[type=text],input[type=password],input[type=number]{
    width:100%;padding:8px 10px;border:1px solid var(--borde);border-radius:7px;
    background:var(--fondo);color:var(--texto);font-size:14px}
  input:focus{outline:2px solid var(--acento);outline-offset:-1px}
  .fila{display:flex;gap:10px}
  .fila > *{flex:1}
  .ancho2{flex:2}
  button{border:1px solid var(--borde);background:var(--tarjeta);color:var(--texto);
         padding:8px 14px;border-radius:7px;font-size:14px;cursor:pointer}
  button:hover:not(:disabled){border-color:var(--acento)}
  button:disabled{opacity:.45;cursor:default}
  button.principal{background:var(--acento);border-color:var(--acento);color:#fff;font-weight:600;
                   padding:9px 22px}
  .info{color:var(--suave);font-size:13px;margin-top:8px;min-height:17px}
  .alerta{color:var(--error);font-size:12.5px;margin-top:10px}
  .barra{height:8px;background:var(--borde);border-radius:99px;overflow:hidden;margin:14px 0 8px}
  .barra > div{height:100%;width:0;background:var(--acento);transition:width .2s}
  #estado{color:var(--suave);font-size:13px;min-height:18px}
  #registro{background:#0f1216;color:#d7dce3;border-radius:8px;padding:12px;height:190px;
            overflow:auto;font:12px ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap}
  #registro .ok{color:#6ec36e} #registro .error{color:#ef8a85} #registro .aviso{color:#e3c46a}
  .pie{display:flex;align-items:center;gap:12px;margin-top:4px}
</style></head>
<body>
  <h1>Restaurar una base de datos</h1>
  <p class="sub">Toma un respaldo .sql del servidor y lo carga en el MySQL que elijas.</p>

  <div class="tarjeta">
    <h2>1 · Origen: archivo de respaldo</h2>
    <div class="fila">
      <input type="text" id="archivo" class="ancho2" placeholder="Elige el archivo .sql" readonly>
      <button onclick="examinar()" style="flex:0 0 auto">Examinar…</button>
      <button onclick="masReciente()" style="flex:0 0 auto">Más reciente</button>
    </div>
    <div class="info" id="infoArchivo"></div>
  </div>

  <div class="tarjeta">
    <h2>2 · Destino: servidor y base</h2>
    <div class="fila">
      <div><label>Servidor</label><input type="text" id="host" value="127.0.0.1"></div>
      <div style="max-width:90px"><label>Puerto</label><input type="number" id="puerto" value="3306"></div>
      <div><label>Usuario</label><input type="text" id="usuario" value="root"></div>
      <div><label>Contraseña</label><input type="password" id="clave" placeholder="(vacía)"></div>
    </div>
    <div class="fila" style="margin-top:10px">
      <div class="ancho2"><label>Base de datos destino</label><input type="text" id="base"></div>
      <div style="align-self:flex-end"><button onclick="probar()">Probar conexión</button></div>
    </div>
    <div class="info" id="infoConexion"></div>
    <div class="info" id="avisoBase" style="color:var(--aviso)"></div>
    <div class="alerta">La base destino se borra y se vuelve a crear con el contenido del respaldo.</div>
  </div>

  <div class="pie">
    <button class="principal" id="btnRestaurar" onclick="restaurar()">Restaurar</button>
    <button id="btnCancelar" onclick="cancelar()" disabled>Cancelar</button>
    <div style="flex:1">
      <div class="barra"><div id="relleno"></div></div>
      <div id="estado">Elige un respaldo para empezar.</div>
    </div>
  </div>

  <div class="tarjeta" style="margin-top:14px">
    <h2>Detalle</h2>
    <div id="registro"></div>
  </div>

<script>
let sondeo = null;
const $ = id => document.getElementById(id);

function escribir(texto, clase){
  const d = document.createElement('div');
  if (clase) d.className = clase;
  d.textContent = texto;
  $('registro').appendChild(d);
  $('registro').scrollTop = $('registro').scrollHeight;
}
function limpiarRegistro(){ $('registro').textContent = ''; }

async function examinar(){
  const r = await pywebview.api.elegir_archivo();
  if (r) ponerArchivo(r);
}
async function masReciente(){
  const r = await pywebview.api.mas_reciente();
  if (r) ponerArchivo(r); else $('infoArchivo').textContent = 'No encontré ningún dump-*.sql en Descargas.';
}
let baseAuto = '';          // ultimo nombre puesto automaticamente
let baseEditada = false;    // true si el usuario escribio el destino a mano

function ponerArchivo(info){
  $('archivo').value = info.ruta;
  $('infoArchivo').textContent = info.resumen;
  $('avisoBase').textContent = '';
  if (info.base){
    if (!$('base').value || !baseEditada){
      // el destino sigue al respaldo elegido
      $('base').value = info.base;
      baseAuto = info.base;
      baseEditada = false;
    } else if ($('base').value !== info.base){
      // lo escribio el usuario: se respeta, pero se avisa
      $('avisoBase').textContent = 'El respaldo es de la base «' + info.base +
        '», y el destino que escribiste es «' + $('base').value + '».';
    }
  }
  $('estado').textContent = 'Listo para restaurar.';
}
async function probar(){
  $('infoConexion').textContent = 'Conectando…';
  const r = await pywebview.api.probar(datos());
  $('infoConexion').textContent = r.mensaje;
}
function datos(){
  return {archivo:$('archivo').value, host:$('host').value, puerto:$('puerto').value,
          usuario:$('usuario').value, clave:$('clave').value, base:$('base').value};
}
async function restaurar(){
  const r = await pywebview.api.iniciar(datos());
  if (!r.ok){ $('estado').textContent = r.mensaje; if(r.mensaje) alert(r.mensaje); return; }
  limpiarRegistro();
  $('btnRestaurar').disabled = true; $('btnCancelar').disabled = false;
  sondeo = setInterval(refrescar, 300);
}
async function cancelar(){ await pywebview.api.cancelar(); }

async function refrescar(){
  const e = await pywebview.api.estado();
  $('relleno').style.width = e.porcentaje + '%';
  if (e.estado) $('estado').textContent = e.estado;
  for (const l of e.lineas) escribir(l.texto, l.clase);
  if (e.terminado){
    clearInterval(sondeo); sondeo = null;
    $('btnRestaurar').disabled = false; $('btnCancelar').disabled = true;
  }
}
document.addEventListener('DOMContentLoaded', () => {
  $('base').addEventListener('input', () => { baseEditada = $('base').value !== baseAuto; });
});
window.addEventListener('pywebviewready', async () => {
  const p = await pywebview.api.preferencias();
  if (p.host) $('host').value = p.host;
  if (p.puerto) $('puerto').value = p.puerto;
  if (p.usuario) $('usuario').value = p.usuario;
  const r = await pywebview.api.mas_reciente();
  if (r) ponerArchivo(r);
});
</script></body></html>
"""


def _tam(n):
    return f"{n / 1073741824:.2f} GB" if n >= 1073741824 else f"{n / 1048576:.0f} MB"


def _reloj(s):
    s = int(max(s, 0))
    return f"{s // 60:02d}:{s % 60:02d}"


class Api:
    def __init__(self):
        self.ventana = None
        self.restauracion = None
        self.servidor = None
        self.hilo = None
        self.pendientes = []
        self.porcentaje = 0
        self.estado_txt = ""
        self.terminado = True
        self._lock = threading.Lock()

    # ---------------------------------------------------------- utilidades
    def _log(self, texto, clase=""):
        with self._lock:
            self.pendientes.append({"texto": texto, "clase": clase})

    def preferencias(self):
        try:
            return json.loads(CONFIG.read_text())
        except Exception:
            return {}

    def _guardar_prefs(self, d):
        try:
            CONFIG.write_text(json.dumps({"host": d["host"], "puerto": d["puerto"],
                                          "usuario": d["usuario"]}, indent=2))
        except Exception:
            pass

    def _info(self, ruta):
        cab = nucleo.leer_cabecera(ruta)
        partes = [_tam(os.path.getsize(ruta))]
        if cab["base"]:
            partes.append(f'base «{cab["base"]}»')
        if cab["version"]:
            partes.append(cab["version"])
        return {"ruta": ruta, "base": cab["base"], "resumen": "   ·   ".join(partes)}

    # ------------------------------------------------------- acciones de UI
    def elegir_archivo(self):
        carpeta = self.preferencias().get("carpeta") or str(Path.home() / "Downloads")
        sel = self.ventana.create_file_dialog(
            webview.OPEN_DIALOG, directory=carpeta, file_types=("Respaldos SQL (*.sql)", "Todos (*.*)"))
        if not sel:
            return None
        return self._info(sel[0])

    def mas_reciente(self):
        ruta = nucleo.dump_mas_reciente()
        return self._info(ruta) if ruta else None

    def probar(self, d):
        try:
            srv = nucleo.Servidor(d["host"], int(d["puerto"] or 3306), d["usuario"], d["clave"])
        except (nucleo.ErrorRestauracion, ValueError) as e:
            return {"ok": False, "mensaje": str(e)}
        ok, err = srv.probar()
        if not ok:
            srv.limpiar()
            return {"ok": False, "mensaje": "No pude conectar: " + err}
        objetos = srv.objetos(d["base"]) if d.get("base") else 0
        modo = srv.modo
        srv.limpiar()
        detalle = f"Conexión correcta  ·  motor: {modo}"
        if d.get("base"):
            detalle += f"  ·  la base «{d['base']}» tiene {objetos} objetos que se borrarán"
        return {"ok": True, "mensaje": detalle}

    def iniciar(self, d):
        if not d["archivo"] or not os.path.isfile(d["archivo"]):
            return {"ok": False, "mensaje": "Elige un archivo de respaldo válido."}
        if not d["base"].strip():
            return {"ok": False, "mensaje": "Escribe el nombre de la base destino."}
        try:
            srv = nucleo.Servidor(d["host"], int(d["puerto"] or 3306), d["usuario"], d["clave"])
        except (nucleo.ErrorRestauracion, ValueError) as e:
            return {"ok": False, "mensaje": str(e)}
        ok, err = srv.probar()
        if not ok:
            srv.limpiar()
            return {"ok": False, "mensaje": "No pude conectar al servidor: " + err}

        objetos = srv.objetos(d["base"])
        confirmar = self.ventana.create_confirmation_dialog(
            TITULO,
            f'Se va a BORRAR la base «{d["base"]}» en {d["host"]} '
            f'({objetos} objetos) y se cargará el respaldo en su lugar.\n\n'
            f'Esto no se puede deshacer. ¿Continuar?')
        if not confirmar:
            srv.limpiar()
            return {"ok": False, "mensaje": ""}

        self.servidor = srv
        self.restauracion = nucleo.Restauracion(
            srv, d["archivo"], d["base"].strip(), auto_fk=True,
            avance=self._avance, mensaje=lambda m: self._log(m))

        hay, libre, necesario = self.restauracion.espacio_suficiente()
        if not hay:
            srv.limpiar()
            return {"ok": False,
                    "mensaje": f"Espacio insuficiente en el disco del servidor.\n\n"
                               f"Libres: {libre:.1f} GB · Necesarios: ~{necesario:.1f} GB"}

        self._guardar_prefs(d)
        with self._lock:
            self.pendientes = []
        self.terminado = False
        self.porcentaje = 0
        self._log(f'Respaldo: {d["archivo"]}')
        self._log(f'Destino : {d["base"]} en {d["host"]}:{d["puerto"]}  ·  motor: {srv.modo}')
        self.hilo = threading.Thread(target=self._correr, daemon=True)
        self.hilo.start()
        return {"ok": True, "mensaje": ""}

    def cancelar(self):
        if self.restauracion:
            self.restauracion.cancelar()
            self._log("Cancelando…", "aviso")
        return True

    def estado(self):
        with self._lock:
            lineas, self.pendientes = self.pendientes, []
        return {"porcentaje": self.porcentaje, "estado": self.estado_txt,
                "lineas": lineas, "terminado": self.terminado}

    # ----------------------------------------------------------- ejecucion
    def _avance(self, e):
        self.porcentaje = e["porcentaje"]
        self.estado_txt = (f'{e["porcentaje"]:.0f}%  ·  {_tam(e["leidos"])} de {_tam(e["total"])}'
                           f'  ·  {e["mb_s"]:.0f} MB/s  ·  faltan {_reloj(e["eta"])}'
                           + (f'  ·  {e["tabla"]}' if e["tabla"] else ""))

    def _correr(self):
        try:
            r = self.restauracion.ejecutar()
            self._resumen(r)
        except Exception as e:                                    # noqa: BLE001
            self._log("Error: " + str(e), "error")
            self.estado_txt = "La restauración falló."
        finally:
            if self.servidor:
                self.servidor.limpiar()
            self.terminado = True

    def _resumen(self, r):
        if r["cancelado"]:
            self.estado_txt = "Cancelado: la base quedó incompleta."
            self._log("Cancelado por el usuario: la base destino quedó a medias.", "aviso")
            return
        self._log("")
        self._log(f'{"":<16}{"respaldo":>9}{"cargado":>10}')
        nombres = [("tablas", "Tablas"), ("vistas", "Vistas"), ("procedures", "Procedimientos"),
                   ("functions", "Funciones"), ("triggers", "Disparadores")]
        for clave, etiqueta in nombres:
            esperado, obtenido = r["dump"].get(clave, 0), r["local"].get(clave, 0)
            if not esperado and not obtenido:
                continue
            bien = obtenido >= esperado
            self._log(f'{etiqueta:<16}{esperado:>9}{obtenido:>10}   '
                      + ("OK" if bien else f"FALTAN {esperado - obtenido}"),
                      "ok" if bien else "error")
        self._log("")
        self._log(f'{r["local"].get("mb", 0)} MB cargados en {_reloj(r["segundos"])}')
        if r["fks_rechazadas"]:
            self._log("Llaves foráneas rechazadas por MySQL: " + ", ".join(r["fks_rechazadas"]), "aviso")
        for linea in r["errores"][:15]:
            self._log(linea, "error")
        if r["ok"]:
            self.estado_txt = "Restauración completa y verificada."
            self._log("Restauración completa y verificada.", "ok")
        else:
            self.estado_txt = "Terminó con problemas: revisa el detalle."


def main():
    api = Api()
    ventana = webview.create_window(TITULO, html=HTML, js_api=api,
                                    width=940, height=860, min_size=(820, 700))
    api.ventana = ventana
    webview.start()
