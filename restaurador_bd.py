#!/usr/bin/env python3
"""Restaurador de BD.

Sin argumentos abre la ventana. Con --cli corre en la terminal:

    python3 restaurador_bd.py --cli respaldo.sql [-d base] [-H host] [-u usuario] [-p pass]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from restaurador import nucleo  # noqa: E402


def _cli(args):
    dump = args.archivo or nucleo.dump_mas_reciente()
    if not dump:
        print("No encontre ningun respaldo dump-*.sql."); return 1
    cab = nucleo.leer_cabecera(dump)
    base = args.db or cab["base"]
    if not base:
        print("No pude deducir la base destino; indicala con -d."); return 1
    try:
        srv = nucleo.Servidor(args.host, args.port, args.user, args.password or "",
                              forzar_python=args.sin_cliente)
    except nucleo.ErrorRestauracion as e:
        print(e); return 1
    ok, err = srv.probar()
    if not ok:
        print(f"No pude conectar: {err}"); return 1

    print(f"\n  Archivo   {dump}")
    print(f"  Destino   {base} en {args.host}:{args.port}  "
          f"({srv.objetos(base)} objetos actuales se borraran)")
    if not args.yes:
        if input("\n  Continuar? [s/N] ").strip().lower() not in ("s", "y"):
            print("  Cancelado."); return 0

    ultimo = [0.0]

    def avance(e):
        if time.time() - ultimo[0] > 0.5:
            ultimo[0] = time.time()
            n = int(e["porcentaje"] / 5)
            sys.stdout.write(f"\r  [{'#' * n}{'.' * (20 - n)}] {e['porcentaje']:3.0f}%  "
                             f"{e['mb_s']:3.0f} MB/s  faltan {int(e['eta']) // 60:02d}:"
                             f"{int(e['eta']) % 60:02d}  {e['tabla'][:28]:<28}")
            sys.stdout.flush()

    r = nucleo.Restauracion(srv, dump, base, auto_fk=args.auto_fk,
                            avance=avance, mensaje=lambda m: print("\n  " + m))
    hay, libre, necesario = r.espacio_suficiente()
    if not hay:
        print(f"\n  Espacio insuficiente: {libre:.1f} GB libres, ~{necesario:.1f} GB necesarios")
        return 1
    res = r.ejecutar()
    print()
    if res["cancelado"]:
        print("  Cancelado."); return 1
    print(f"\n  {'':<14}{'respaldo':>9}{'cargado':>9}")
    for clave, etiqueta in (("tablas", "Tablas"), ("vistas", "Vistas"),
                            ("procedures", "Procedimientos"), ("functions", "Funciones"),
                            ("triggers", "Disparadores")):
        esperado, obtenido = res["dump"].get(clave, 0), res["local"].get(clave, 0)
        if esperado or obtenido:
            marca = "OK" if obtenido >= esperado else f"FALTAN {esperado - obtenido}"
            print(f"  {etiqueta:<14}{esperado:>9}{obtenido:>9}   {marca}")
    print(f"\n  {res['local'].get('mb', 0)} MB en {res['segundos']:.0f}s")
    for linea in res["errores"][:10]:
        print("  " + linea)
    if res["fks_rechazadas"]:
        print("  FKs rechazadas: " + ", ".join(res["fks_rechazadas"]))
    print("  Restauracion completa y verificada." if res["ok"] else "  Termino con problemas.")
    srv.limpiar()
    return 0 if res["ok"] else 1


def main():
    # macOS pasa -psn_0_xxxx al abrir un .app desde el Finder
    sys.argv = [a for a in sys.argv if not a.startswith("-psn_")]
    p = argparse.ArgumentParser(description="Restaurador de BD")
    p.add_argument("archivo", nargs="?", help="respaldo .sql")
    p.add_argument("--cli", action="store_true", help="modo terminal, sin ventana")
    p.add_argument("-d", "--db", help="base destino")
    p.add_argument("-H", "--host", default="127.0.0.1")
    p.add_argument("-P", "--port", type=int, default=3306)
    p.add_argument("-u", "--user", default="root")
    p.add_argument("-p", "--password", default="")
    p.add_argument("-y", "--yes", action="store_true")
    p.add_argument("--auto-fk", action="store_true", default=True)
    p.add_argument("--sin-cliente", action="store_true",
                   help="no usar el programa mysql aunque este instalado")
    args = p.parse_args()
    if args.cli:
        return _cli(args)
    from restaurador import interfaz
    interfaz.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
