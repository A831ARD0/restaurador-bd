"""Logica de restauracion de dumps MySQL/MariaDB. Sin interfaz: la GUI y el
modo consola usan estas funciones.

Traduce al vuelo la sintaxis de MariaDB que MySQL 8/9 ya no acepta y carga el
dump con el cliente `mysql`, informando el avance por callbacks.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import motor as motores

# Llaves foraneas a degradar a indice simple. Normalmente se deja vacia: la app
# detecta sola las que MySQL rechaza y reintenta con ellas (ver auto_fk).
NOFK_POR_DEFECTO = []

# Rutas tipicas del cliente mysql cuando no esta en el PATH
RUTAS_CLIENTE = [
    "/opt/homebrew/bin/mysql", "/usr/local/bin/mysql", "/usr/bin/mysql",
    r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
    r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe",
    r"C:\Program Files\MySQL\MySQL Server 9.0\bin\mysql.exe",
    r"C:\Program Files\MariaDB 10.11\bin\mysql.exe",
    r"C:\Program Files\MariaDB 11.4\bin\mysql.exe",
    r"C:\xampp\mysql\bin\mysql.exe",
    r"C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysql.exe",
]


class ErrorRestauracion(Exception):
    pass


def buscar_cliente_mysql():
    """Devuelve la ruta del cliente mysql, o None si no se encuentra."""
    for nombre in ("mysql", "mariadb"):
        ruta = shutil.which(nombre)
        if ruta:
            return ruta
    for ruta in RUTAS_CLIENTE:
        if os.path.isfile(ruta):
            return ruta
    # Windows: buscar en cualquier version instalada
    for base in (r"C:\Program Files", r"C:\Program Files (x86)"):
        p = Path(base)
        if p.is_dir():
            for hallado in p.glob("M*/[Bb]in/mysql.exe"):
                return str(hallado)
            for hallado in p.glob("M*/*/[Bb]in/mysql.exe"):
                return str(hallado)
    return None


def carpetas_de_busqueda():
    casa = Path.home()
    opciones = [casa / "Downloads", casa / "Descargas", Path.cwd()]
    return [c for c in opciones if c.is_dir()]


def dump_mas_reciente(carpetas=None):
    """El dump-*.sql modificado mas recientemente entre las carpetas dadas."""
    candidatos = []
    for carpeta in (carpetas or carpetas_de_busqueda()):
        candidatos.extend(Path(carpeta).glob("dump-*.sql"))
    if not candidatos:
        return None
    return str(max(candidatos, key=lambda p: p.stat().st_mtime))


def leer_cabecera(ruta):
    """Base de origen, host y version de servidor que declara el dump."""
    datos = {"base": "", "origen": "", "version": ""}
    with open(ruta, "rb") as fh:
        for _ in range(10):
            linea = fh.readline()
            if not linea:
                break
            texto = linea.decode("utf-8", "replace").replace("\r", "").rstrip("\n")
            if texto.startswith("-- Host:"):
                datos["origen"] = texto[3:].strip()
                m = re.search(r"Database:\s*(\S+)", texto)
                if m:
                    datos["base"] = m.group(1)
            elif texto.startswith("-- Server version"):
                datos["version"] = texto.replace("-- Server version", "").strip()
    if not datos["base"]:
        m = re.match(r"dump-(.+?)-\d+\.sql$", Path(ruta).name)
        if m:
            datos["base"] = m.group(1)
    return datos


# --------------------------------------------------------------- traducciones
def _patrones(nofk, base_origen):
    """Compila las sustituciones MariaDB -> MySQL. Trabajamos en bytes para no
    tropezar con dumps que mezclan latin1 y utf8."""
    reglas = [
        # CHECK (json_valid(col)) solo existe en MariaDB
        (re.compile(rb"\s*CHECK \(json_valid\(`[^`]+`\)\)"), b""),
        # MySQL 9 elimino utf8mb3 y sus colaciones
        (re.compile(rb"utf8mb3"), b"utf8mb4"),
        (re.compile(rb"utf8_"), b"utf8mb4_"),
        (re.compile(rb"\butf8\b"), b"utf8mb4"),
        # current_timestamp() no es default valido para DATE
        (re.compile(rb"\bdate NOT NULL DEFAULT current_timestamp\(\)", re.I), b"date NOT NULL"),
        (re.compile(rb"\bdate DEFAULT current_timestamp\(\)", re.I), b"date DEFAULT NULL"),
        # MySQL no permite DEFAULT en columnas TEXT
        (re.compile(rb"((?:tiny|medium|long)?text(?:\s+CHARACTER SET \S+)?"
                    rb"(?:\s+COLLATE \S+)?)\s+DEFAULT\s+'[^']*'", re.I), rb"\1"),
        # La base la crea y selecciona este programa
        (re.compile(rb"^CREATE DATABASE .*$"), b""),
        (re.compile(rb"^USE `[^`]*`;.*$"), b""),
    ]
    if nofk:
        alternativa = "|".join(re.escape(f) for f in nofk).encode()
        reglas.append((
            re.compile(rb"CONSTRAINT `(" + alternativa + rb")` FOREIGN KEY \((`[^)]*`)\)"
                       rb" REFERENCES [^,\n]*"),
            rb"KEY `\1_nofk` (\2)"))
    if base_origen:
        # Triggers y vistas traen la base hardcodeada: se quita para que todo
        # quede en la base destino aunque se llame distinto.
        reglas.append((re.compile(b"`" + re.escape(base_origen.encode()) + b"`\\."), b""))
    return reglas


_RE_TABLA = re.compile(rb"^-- Table structure for table `([^`]+)`")
_CONTADORES = [
    ("tablas", re.compile(rb"^CREATE TABLE ")),
    ("vistas", re.compile(rb"^/\*!50001 VIEW `")),
    ("procedures", re.compile(rb"^CREATE DEFINER=.*PROCEDURE")),
    ("functions", re.compile(rb"^CREATE DEFINER=.*FUNCTION")),
    ("triggers", re.compile(rb"^/\*!50003 CREATE\*/.*TRIGGER")),
]


# ------------------------------------------------------------------- servidor
class Servidor:
    """Envoltura del cliente mysql. La password viaja en un archivo de
    opciones temporal, nunca en la linea de comandos."""

    def __init__(self, host="127.0.0.1", puerto=3306, usuario="root", password="", cliente=None,
                 forzar_python=False):
        # Si el equipo tiene el programa `mysql` lo usamos porque es mas rapido;
        # si no, PyMySQL (incluido en la app) hace el trabajo igual.
        self.cliente = None if forzar_python else (cliente or buscar_cliente_mysql())
        self.host, self.puerto, self.usuario, self.password = host, int(puerto), usuario, password
        self._cnf = None
        self._cn = None

    @property
    def modo(self):
        return "cliente mysql" if self.cliente else "PyMySQL (incluido)"

    def _conexion(self):
        if self._cn is None:
            self._cn = motores.ConexionPython(self.host, self.puerto, self.usuario, self.password)
        return self._cn

    def _archivo_opciones(self):
        if self._cnf and os.path.exists(self._cnf):
            return self._cnf
        fd, ruta = tempfile.mkstemp(prefix="restaurador_", suffix=".cnf")
        with os.fdopen(fd, "w") as fh:
            fh.write("[client]\n")
            fh.write(f"host={self.host}\nport={self.puerto}\nuser={self.usuario}\n")
            if self.password:
                fh.write(f"password={self.password}\n")
        os.chmod(ruta, 0o600)
        self._cnf = ruta
        return ruta

    def limpiar(self):
        if self._cn is not None:
            self._cn.cerrar()
            self._cn = None
        if self._cnf and os.path.exists(self._cnf):
            os.unlink(self._cnf)
            self._cnf = None

    def _base_cmd(self):
        return [self.cliente, f"--defaults-extra-file={self._archivo_opciones()}"]

    def consulta(self, sql, base=None):
        if not self.cliente:
            try:
                valor = self._conexion().escalar(sql) if sql.lstrip().upper().startswith("SELECT") \
                    else self._conexion().ejecutar(sql)
            except motores.ErrorServidor as e:
                raise ErrorRestauracion(str(e))
            return "" if valor is None else str(valor)
        cmd = self._base_cmd() + ["-N", "-B", "-e", sql]
        if base:
            cmd.append(base)
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise ErrorRestauracion(res.stderr.strip() or "fallo la consulta")
        return res.stdout.strip()

    def probar(self):
        try:
            self.consulta("SELECT 1")
            return True, ""
        except ErrorRestauracion as e:
            return False, str(e)

    def datadir(self):
        try:
            return self.consulta("SELECT @@datadir")
        except ErrorRestauracion:
            return ""

    def objetos(self, base):
        try:
            return int(self.consulta(
                "SELECT count(*) FROM information_schema.tables "
                f"WHERE table_schema='{base}'") or 0)
        except ErrorRestauracion:
            return 0

    def conteos(self, base):
        def n(sql):
            try:
                return int(self.consulta(sql) or 0)
            except ErrorRestauracion:
                return 0
        i = "information_schema"
        return {
            "tablas": n(f"SELECT count(*) FROM {i}.tables WHERE table_schema='{base}' AND table_type='BASE TABLE'"),
            "vistas": n(f"SELECT count(*) FROM {i}.tables WHERE table_schema='{base}' AND table_type='VIEW'"),
            "procedures": n(f"SELECT count(*) FROM {i}.routines WHERE routine_schema='{base}' AND routine_type='PROCEDURE'"),
            "functions": n(f"SELECT count(*) FROM {i}.routines WHERE routine_schema='{base}' AND routine_type='FUNCTION'"),
            "triggers": n(f"SELECT count(*) FROM {i}.triggers WHERE trigger_schema='{base}'"),
            "mb": n(f"SELECT round(sum(data_length+index_length)/1024/1024) FROM {i}.tables WHERE table_schema='{base}'"),
        }


# ---------------------------------------------------------------- restauracion
class Restauracion:
    """Una restauracion en curso. `avance` recibe diccionarios con el estado y
    `mensaje` recibe texto para el registro."""

    def __init__(self, servidor, dump, base, nofk=None, auto_fk=False,
                 collate="utf8mb4_general_ci", avance=None, mensaje=None):
        self.srv = servidor
        self.dump = str(dump)
        self.base = base
        self.nofk = list(nofk if nofk is not None else NOFK_POR_DEFECTO)
        self.auto_fk = auto_fk
        self.collate = collate
        self.avance = avance or (lambda _: None)
        self.mensaje = mensaje or (lambda _: None)
        self.cancelado = False
        self._motor = None

    def cancelar(self):
        self.cancelado = True
        if self._motor is not None:
            try:
                self._motor.matar()
            except Exception:
                pass

    def espacio_suficiente(self):
        """(ok, libre_gb, necesario_gb). libre_gb es None si no se puede medir."""
        necesario = os.path.getsize(self.dump) * 1.1 / 1073741824
        datadir = self.srv.datadir()
        if not datadir or not os.path.isdir(datadir):
            return True, None, necesario
        libre = shutil.disk_usage(datadir).free / 1073741824
        return libre >= necesario, libre, necesario

    def ejecutar(self):
        """Corre la restauracion. Devuelve un dict con el resultado."""
        resultado = self._una_pasada()
        if resultado["fks_rechazadas"] and self.auto_fk and not self.cancelado:
            nuevas = [f for f in resultado["fks_rechazadas"] if f not in self.nofk]
            if nuevas:
                self.mensaje(f"Reintentando con {len(nuevas)} FK(s) degradadas a indice: "
                             + ", ".join(nuevas))
                self.nofk.extend(nuevas)
                resultado = self._una_pasada()
        return resultado

    def _una_pasada(self):
        cab = leer_cabecera(self.dump)
        total = os.path.getsize(self.dump)
        reglas = _patrones(self.nofk, cab["base"])
        conteos_dump = {k: 0 for k, _ in _CONTADORES}

        self.mensaje(f"Recreando la base {self.base}  ({self.srv.modo})...")
        # Necesario para funciones sin DETERMINISTIC cuando el binlog esta activo.
        # Si el usuario no tiene permisos seguimos: solo fallarian las funciones.
        try:
            self.srv.consulta("SET GLOBAL log_bin_trust_function_creators=1")
        except ErrorRestauracion:
            pass
        self.srv.consulta(f"DROP DATABASE IF EXISTS `{self.base}`")
        self.srv.consulta(
            f"CREATE DATABASE `{self.base}` DEFAULT CHARACTER SET utf8mb4 COLLATE {self.collate}")

        if self.srv.cliente:
            log = tempfile.NamedTemporaryFile(prefix="restaurador_err_", suffix=".log",
                                              delete=False, mode="w+")
            log.close()
            motor = motores.MotorCliente(self.srv.cliente, self.srv._archivo_opciones(),
                                         self.base, log.name)
        else:
            motor = motores.MotorPython(self.srv._conexion().cn, self.base)
            log = None
        self._motor = motor

        inicio = time.time()
        leidos = 0
        tabla_actual = ""
        ultimo_aviso = 0.0
        try:
            with open(self.dump, "rb") as fh:
                for linea in fh:
                    if self.cancelado:
                        break
                    leidos += len(linea)
                    if not linea.startswith(b"INSERT INTO"):
                        for patron, reemplazo in reglas:
                            linea = patron.sub(reemplazo, linea)
                        for clave, patron in _CONTADORES:
                            if patron.match(linea):
                                conteos_dump[clave] += 1
                        m = _RE_TABLA.match(linea)
                        if m:
                            tabla_actual = m.group(1).decode("utf-8", "replace")
                    motor.escribir(linea)

                    ahora = time.time()
                    if ahora - ultimo_aviso > 0.3:
                        ultimo_aviso = ahora
                        transcurrido = ahora - inicio
                        vel = leidos / transcurrido if transcurrido > 0 else 0
                        self.avance({
                            "porcentaje": leidos * 100.0 / total if total else 0,
                            "leidos": leidos, "total": total,
                            "mb_s": vel / 1048576,
                            "eta": (total - leidos) / vel if vel > 0 else 0,
                            "tabla": tabla_actual,
                        })
        except BrokenPipeError:
            self.mensaje("El motor de carga se cerro antes de tiempo.")
        finally:
            motor.cerrar()

        segundos = time.time() - inicio
        self.avance({"porcentaje": 100.0, "leidos": leidos, "total": total,
                     "mb_s": 0, "eta": 0, "tabla": ""})

        crudos = motor.errores()
        if log is not None:
            os.unlink(log.name)

        if self.cancelado:
            return {"cancelado": True, "errores": [], "fks_rechazadas": [],
                    "dump": conteos_dump, "local": {}, "segundos": segundos, "ok": False}

        # Los 1146 son consecuencia de un CREATE TABLE que ya fallo antes.
        errores = [l for l in crudos if "doesn't exist" not in l]
        texto = "\n".join(crudos)
        fks = sorted(set(re.findall(r"Missing unique key for constraint '([^']+)'", texto)))

        local = self.srv.conteos(self.base)
        faltan = any(local.get(k, 0) < conteos_dump.get(k, 0) for k in conteos_dump)
        return {
            "cancelado": False,
            "errores": errores,
            "fks_rechazadas": fks,
            "dump": conteos_dump,
            "local": local,
            "segundos": segundos,
            "ok": not errores and not faltan,
        }
