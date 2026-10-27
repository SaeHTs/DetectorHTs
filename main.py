"""CLI de detección de procesos y servicios innecesarios de Windows.

Flujo:
1. Escanear procesos de alto consumo (umbral CPU 50 % / RAM 256 MB).
2. Escanear procesos inactivos (CPU < 1.0 %).
3. Escanear servicios sin dependencias.
4. Agrupar hallazgos por nivel de riesgo (usar risk.nivel).
5. Presentar cada hallazgo con su nivel y motivo.
6. Preguntar al usuario si desea actuar sobre cada hallazgo.
7. Si confirma, ejecutar acción (usar actions.ejecutar) y verificar resultado.
"""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import List

import psutil
from detector import ProcesoHallazgo, ServicioHallazgo
from detector import clasificar_procesos, servicios_sin_dependencias
from risk import nivel
from actions import ejecutar as accion_ejecutar

UMBRAL_CPU_ALTO = 50.0
UMBRAL_RAM_ALTO_MB = 256


def motivo(hallazgo, nivel_riesgo: str) -> str:
    """Devuelve un breve motivo del nivel de riesgo de un hallazgo."""
    if isinstance(hallazgo, ProcesoHallazgo):
        if nivel_riesgo == "alto":
            return f"CPU {hallazgo.cpu_percent}% >= {UMBRAL_CPU_ALTO} o RAM {hallazgo.ram_mb} MB >= {UMBRAL_RAM_ALTO_MB}"
        # bajo o inactivo
        return f"CPU {hallazgo.cpu_percent}% < 1.0% y RAM {hallazgo.ram_mb} MB < {UMBRAL_RAM_ALTO_MB}"
    elif isinstance(hallazgo, ServicioHallazgo):
        return "servicio sin dependencias y no crítico del sistema"
    return ""


def verificar_servicio(nombre: str) -> bool:
    """Devuelve True si sc.exe query el servicio devuelve éxito (código 0)."""
    try:
        result = subprocess.run(
            ["sc.exe", "query", nombre],
            capture_output=True,
            text=True,
            errors="replace",
        )
        return result.returncode == 0
    except Exception:
        return False


def verificar_proceso(pid: int) -> bool:
    """Devuelve True si el proceso con el PID dado aún existe."""
    return psutil.pid_exists(pid)


def presentar_hallazgos(hallazgos: List) -> None:
    """Imprime hallazgos agrupados por riesgo con motivos."""
    # Agrupar por nivel
    por_nivel = {}
    for h in hallazgos:
        n = nivel(h)
        por_nivel.setdefault(n, []).append(h)

    for nivel_riesgo in ["alto", "medio", "bajo"]:
        items = por_nivel.get(nivel_riesgo, [])
        if not items:
            continue
        print(f"\n=== Riesgo {nivel_riesgo.upper()} ({len(items)} hallazgos) ===")
        for h in items:
            motivo_str = motivo(h, nivel_riesgo)
            if isinstance(h, ProcesoHallazgo):
                print(f"  Proceso: {h.nombre} (PID {h.pid}), CPU {h.cpu_percent}%, RAM {h.ram_mb} MB -> {motivo_str}")
            else:
                print(f"  Servicio: {h.nombre}, estado {h.estado} -> {motivo_str}")


def preguntar_accion(hallazgo) -> bool:
    """Muestra un mensaje al usuario y devuelve True si desea actuar."""
    if isinstance(hallazgo, ProcesoHallazgo):
        texto = f"¿Desea terminar el proceso {hallazgo.nombre} (PID {hallazgo.pid})? (si/no): "
    else:
        texto = f"¿Desea detener e inhabilitar el servicio {hallazgo.nombre}? (si/no): "
    respuesta = input(texto).strip().lower()
    return respuesta == "si"


def actuar_sobre(hallazgo):
    """Ejecuta la acción tras confirmación e imprime resultado."""
    confirmado = preguntar_accion(hallazgo)
    if not confirmado:
        print(f"  Acción omitida para {hallazgo.nombre if isinstance(hallazgo, ProcesoHallazgo) else hallazgo.nombre}.")
        return

    resultado = accion_ejecutar(hallazgo, confirmar=lambda h: True)
    print(f"  Acción ejecutada: {resultado.detalle}")
    # Verificar estado para servicios (verificar con sc query)
    if isinstance(hallazgo, ServicioHallazgo):
        if verificar_servicio(hallazgo.nombre):
            print(f"  ✓ El servicio {hallazgo.nombre} fue detenido exitosamente.")
        else:
            print(f"  ✗ El servicio {hallazgo.nombre} podría no haberse detenido correctamente.")
    elif isinstance(hallazgo, ProcesoHallazgo):
        if not verificar_proceso(hallazgo.pid):
            print(f"  ✓ El proceso {hallazgo.nombre} (PID {hallazgo.pid}) fue terminado.")
        else:
            print(f"  ? El proceso {hallazgo.nombre} (PID {hallazgo.pid}) podría seguir en ejecución.")


def ejecutar() -> None:
    """Flujo completo: escaneo, agrupación, presentación y confirmación."""
    print("Iniciando detección de procesos y servicios innecesarios de Windows...")
    # Una sola medición de CPU da los altos y los inactivos. El escaneo de
    # servicios (lento, muchos sc.exe) corre a la vez que esa medición.
    with ThreadPoolExecutor(max_workers=1) as ejecutor:
        futuro_servicios = ejecutor.submit(servicios_sin_dependencias)
        procesos_altos, procesos_inactivos_lista = clasificar_procesos(
            umbral_cpu=UMBRAL_CPU_ALTO, umbral_ram_mb=UMBRAL_RAM_ALTO_MB)
        servicios = futuro_servicios.result()

    hallazgos = procesos_altos + procesos_inactivos_lista + servicios
    if not hallazgos:
        print("No se encontraron procesos o servicios innecesarios.")
        return

    presentar_hallazgos(hallazgos)

    for h in hallazgos:
        print("\n")
        actuar_sobre(h)

    print("\nDetección completada.")


if __name__ == "__main__":
    ejecutar()