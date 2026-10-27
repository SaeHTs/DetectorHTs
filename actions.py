"""Acciones sobre hallazgos, siempre después de la confirmación del usuario."""

import subprocess
from dataclasses import dataclass
from typing import Optional

import psutil

from detector import ProcesoHallazgo, ServicioHallazgo, SIN_CONSOLA


@dataclass
class ResultadoAccion:
    """Resultado de intentar actuar sobre un hallazgo."""

    ejecutado: bool
    detalle: str = ""
    retcode: Optional[int] = None
    error_msg: str = ""


def ejecutar(hallazgo, confirmar) -> ResultadoAccion:
    """Apaga el proceso o detiene y deshabilita el servicio si `confirmar` lo aprueba.

    Si `confirmar(hallazgo)` devuelve False no se ejecuta nada y el resultado
    queda marcado con `ejecutado == False`.
    """
    if not confirmar(hallazgo):
        return ResultadoAccion(ejecutado=False, detalle="accion no confirmada")
    if isinstance(hallazgo, ServicioHallazgo):
        # sc.exe stop detiene el servicio y sc.exe config start= disabled
        # evita que Windows lo vuelva a arrancar (decisión 5 del diseño).
        stop_result = subprocess.run(
            ["sc.exe", "stop", hallazgo.nombre],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=SIN_CONSOLA,
        )
        config_result = subprocess.run(
            ["sc.exe", "config", hallazgo.nombre, "start=", "disabled"],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=SIN_CONSOLA,
        )
        retcode = stop_result.returncode if stop_result.returncode != 0 else config_result.returncode
        error_msg = ""
        if stop_result.returncode != 0:
            error_msg = f"sc stop falló (código {stop_result.returncode}): {stop_result.stderr.strip()}"
        elif config_result.returncode != 0:
            error_msg = f"sc config falló (código {config_result.returncode}): {config_result.stderr.strip()}"
        return ResultadoAccion(
            ejecutado=True,
            detalle=f"servicio {hallazgo.nombre} detenido y deshabilitado",
            retcode=retcode if retcode != 0 else None,
            error_msg=error_msg,
        )
    if isinstance(hallazgo, ProcesoHallazgo):
        psutil.Process(hallazgo.pid).terminate()
        return ResultadoAccion(
            ejecutado=True,
            detalle=f"proceso {hallazgo.nombre} (pid {hallazgo.pid}) terminado",
        )
    raise TypeError(f"tipo de hallazgo desconocido: {type(hallazgo).__name__}")


def ejecutar_manual(hallazgo: ServicioHallazgo) -> ResultadoAccion:
    """Cambia el inicio de un servicio a Manual (DEMAND_START)."""
    try:
        # sc config <nombre> start= demand
        resultado = subprocess.run(
            ["sc.exe", "config", hallazgo.nombre, "start=", "demand"],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=SIN_CONSOLA,
        )
        return ResultadoAccion(
            ejecutado=(resultado.returncode == 0),
            detalle="servicio puesto en modo manual" if resultado.returncode == 0 else "",
            retcode=resultado.returncode if resultado.returncode != 0 else None,
            error_msg=resultado.stderr.strip() if resultado.returncode != 0 else "",
        )
    except Exception as e:
        return ResultadoAccion(ejecutado=False, error_msg=str(e))
