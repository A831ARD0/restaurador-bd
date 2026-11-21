"""Dos motores para cargar un dump:

- MotorCliente: usa el programa `mysql` si esta instalado (es el mas rapido).
- MotorPython : usa PyMySQL, que viaja dentro de la app, para que el equipo no
                necesite tener instalado nada de MySQL.

Ambos exponen la misma interfaz: escribir(linea), cerrar(), errores().
"""
import re
import subprocess

import pymysql
from pymysql.constants import COMMAND


class ErrorServidor(Exception):
    pass


# --------------------------------------------------------------------- comun
class _Base:
    def __init__(self):
        self._errores = []

    def errores(self):
        return list(self._errores)


class MotorCliente(_Base):
    """Canaliza el dump al programa mysql, como haria `mysql < dump.sql`."""

    def __init__(self, cliente, archivo_opciones, base, log_errores):
        super().__init__()
        self._log = log_errores
        self._fh = open(log_errores, "wb")
        self.proc = subprocess.Popen(
            [cliente, f"--defaults-extra-file={archivo_opciones}", "--force", base],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._fh)

    def escribir(self, linea):
        self.proc.stdin.write(linea)

    def cerrar(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.wait()
        self._fh.close()
        with open(self._log, "r", errors="replace") as fh:
            self._errores = [l for l in fh.read().splitlines() if l.startswith("ERROR")]

    def matar(self):
        if self.proc.poll() is None:
            self.proc.kill()


class MotorPython(_Base):
    """Arma las sentencias del dump y las ejecuta con PyMySQL.

    Los INSERT de mysqldump ocupan una linea completa terminada en ';', asi que
    se envian directo. El resto (DDL, rutinas con DELIMITER, comentarios) pasa
    por un separador que respeta cadenas, comentarios y delimitadores.
    """

    def __init__(self, conexion, base):
        super().__init__()
        self.cn = conexion
        self.base = base
        self.cur = conexion.cursor()
        self.cn._execute_command(COMMAND.COM_QUERY, f"USE `{base}`".encode())
        self.cn._read_query_result()
        self.buffer = bytearray()
        self.delimitador = b";"

    # -- ejecucion ---------------------------------------------------------
    @staticmethod
    def _solo_comentarios(texto):
        """True si la sentencia no tiene nada ejecutable (solo comentarios).

        Ojo: los bloques /*!... */ SI son ejecutables para MySQL, y la cabecera
        del dump mezcla comentarios con SETs en la misma sentencia.
        """
        limpio = re.sub(rb"/\*![^*]*\*+(?:[^/*][^*]*\*+)*/", b"X", texto)   # marca los ejecutables
        limpio = re.sub(rb"/\*.*?\*/", b"", limpio, flags=re.S)              # quita los normales
        limpio = re.sub(rb"(?m)^\s*(--[^\n]*|#[^\n]*)$", b"", limpio)
        limpio = re.sub(rb"(?m)\s+", b"", limpio)
        return not limpio

    def _ejecutar(self, sentencia):
        texto = sentencia.strip()
        if not texto or self._solo_comentarios(texto):
            return
        try:
            # Se envian los bytes tal cual vienen del dump: decodificarlos a str
            # rompe las filas que traen bytes que no son UTF-8 valido.
            self.cn._execute_command(COMMAND.COM_QUERY, texto)
            self.cn._read_query_result()
        except pymysql.MySQLError as e:
            codigo = e.args[0] if e.args else 0
            mensaje = e.args[1] if len(e.args) > 1 else str(e)
            # 1146 (tabla inexistente) es consecuencia de un CREATE que ya fallo
            self._errores.append(f"ERROR {codigo}: {mensaje}")
        except Exception as e:                                    # noqa: BLE001
            self._errores.append(f"ERROR: {e}")

    def escribir(self, linea):
        # Caso rapido: un INSERT completo en una sola linea
        if not self.buffer and linea.startswith(b"INSERT INTO") and linea.rstrip().endswith(b";"):
            self._ejecutar(linea.rstrip()[:-1])
            return
        cabeza = linea.lstrip()
        if cabeza.upper().startswith(b"DELIMITER"):
            nuevo = cabeza.split(None, 1)
            if len(nuevo) > 1:
                self.delimitador = nuevo[1].strip()
            return
        self.buffer += linea
        self._drenar()

    def _drenar(self):
        """Saca del buffer todas las sentencias completas que haya."""
        while True:
            corte = self._buscar_delimitador(self.buffer)
            if corte is None:
                return
            sentencia = self.buffer[:corte]
            del self.buffer[:corte + len(self.delimitador)]
            self._ejecutar(bytes(sentencia))

    def _buscar_delimitador(self, datos):
        """Posicion del delimitador fuera de cadenas y comentarios, o None."""
        i, n = 0, len(datos)
        delim = self.delimitador
        largo = len(delim)
        while i < n:
            c = datos[i:i + 1]
            if c == b"'" or c == b'"' or c == b"`":
                cierre = c
                i += 1
                while i < n:
                    d = datos[i:i + 1]
                    if d == b"\\" and cierre != b"`":
                        i += 2
                        continue
                    if d == cierre:
                        # '' dentro de una cadena es una comilla escapada
                        if cierre != b"`" and datos[i + 1:i + 2] == cierre:
                            i += 2
                            continue
                        i += 1
                        break
                    i += 1
                continue
            if datos[i:i + 2] == b"--" and (datos[i + 2:i + 3] in (b" ", b"\t", b"\n", b"\r", b"")):
                salto = datos.find(b"\n", i)
                if salto == -1:
                    return None
                i = salto + 1
                continue
            if c == b"#":
                salto = datos.find(b"\n", i)
                if salto == -1:
                    return None
                i = salto + 1
                continue
            if datos[i:i + 2] == b"/*":
                # Los comentarios /*! ... */ son ejecutables: forman parte de la sentencia
                fin = datos.find(b"*/", i + 2)
                if fin == -1:
                    return None
                i = fin + 2
                continue
            if datos[i:i + largo] == delim:
                return i
            i += 1
        return None

    def cerrar(self):
        if self.buffer.strip():
            self._ejecutar(bytes(self.buffer))
            self.buffer = bytearray()
        try:
            self.cn.commit()
        except Exception:
            pass
        self.cur.close()

    def matar(self):
        try:
            self.cn.close()
        except Exception:
            pass


# ------------------------------------------------------------------ consultas
class ConexionPython:
    """Conexion PyMySQL para consultas sueltas y para el MotorPython."""

    def __init__(self, host, puerto, usuario, password):
        try:
            self.cn = pymysql.connect(
                host=host, port=int(puerto), user=usuario, password=password or "",
                charset="utf8mb4", autocommit=True, local_infile=False,
                client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS)
        except pymysql.MySQLError as e:
            raise ErrorServidor(str(e.args[-1] if e.args else e))

    def escalar(self, sql):
        with self.cn.cursor() as cur:
            cur.execute(sql)
            fila = cur.fetchone()
        return fila[0] if fila else None

    def ejecutar(self, sql):
        with self.cn.cursor() as cur:
            cur.execute(sql)

    def cerrar(self):
        try:
            self.cn.close()
        except Exception:
            pass
