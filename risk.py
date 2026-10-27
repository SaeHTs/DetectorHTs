"""Agrupación de hallazgos por nivel de riesgo: "bajo", "medio" o "alto"."""

from detector import ProcesoHallazgo, ServicioHallazgo

# Umbrales de "alto consumo": los mismos valores con los que la Task 1 detecta
# procesos de consumo alto (50 % de CPU o 256 MB de RAM), para que un hallazgo
# de ese detector se agrupe siempre como riesgo alto.
UMBRAL_CPU_ALTO = 50.0
UMBRAL_RAM_ALTO_MB = 256


def nivel(hallazgo) -> str:
    """Nivel de riesgo de un hallazgo: "bajo", "medio" o "alto".

    - Servicio -> "medio": actuar sobre un servicio toca el sistema, y así
      quedan protegidos los servicios dudosos detectados en la Task 3
      (PlugPlay/Power) sin necesidad de una lista curada de críticos.
    - Proceso -> "alto" si supera los umbrales de consumo alto, "bajo" en caso
      contrario.
    """
    if isinstance(hallazgo, ServicioHallazgo):
        return "medio"
    if isinstance(hallazgo, ProcesoHallazgo):
        if (
            hallazgo.cpu_percent >= UMBRAL_CPU_ALTO
            or hallazgo.ram_mb >= UMBRAL_RAM_ALTO_MB
        ):
            return "alto"
        return "bajo"
    raise TypeError(f"tipo de hallazgo desconocido: {type(hallazgo).__name__}")
