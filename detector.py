"""Detección de procesos con alto consumo de CPU o memoria."""

import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import psutil

# Bandera de Windows para lanzar sc.exe SIN ventana de consola: sin ella,
# cada llamada a sc.exe hace parpadear una consola negra sobre la GUI.
SIN_CONSOLA = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# Consultas `sc qc` simultáneas durante el escaneo (cada una es un proceso).
MAX_CONSULTAS_PARALELAS = 8


@dataclass
class ProcesoHallazgo:
    """Proceso que supera al menos uno de los umbrales de consumo."""

    pid: int
    nombre: str
    cpu_percent: float
    ram_mb: int
    ruta: str = ""


def _obtener(proc, atributo):
    """Lee un atributo del proceso; si es callable (psutil real), lo invoca."""
    valor = getattr(proc, atributo)
    return valor() if callable(valor) else valor


def _ram_mb(proc) -> float:
    """Memoria en MB: usa memory_mb (procesos falsos de prueba) o rss de psutil."""
    if hasattr(proc, "memory_mb"):
        return float(_obtener(proc, "memory_mb"))
    return _obtener(proc, "memory_info").rss / (1024 * 1024)


def _exe(proc) -> str:
    """Ruta del ejecutable del proceso; cadena vacía si no se puede leer.

    psutil lanza AccessDenied en procesos protegidos: aquí nunca revienta.
    """
    try:
        return str(_obtener(proc, "exe") or "")
    except Exception:
        return ""


# Ventana (segundos) entre el cebado de CPU y la medición real. psutil
# devuelve 0 % en la PRIMERA lectura de cpu_percent: hay que cebarla una vez,
# esperar y recién ahí medir. Ocurre dentro del hilo de escaneo de la GUI.
VENTANA_MEDIDA_CPU = 0.5

# Pseudo-proceso del kernel: su "CPU" es el tiempo OCIOSO del sistema (puede
# marcar 600 %+ con varios núcleos). No es un proceso real ni detenable.
PROCESO_IDLE = "SYSTEM IDLE PROCESS"


def _procesos_medidos() -> list:
    """Procesos con la CPU cebada, listos para medir de verdad."""
    procs = list(psutil.process_iter())
    for proc in procs:
        try:
            _obtener(proc, "cpu_percent")  # lectura base (siempre 0 %)
        except Exception:
            pass  # procesos protegidos: se miden con lo que haya
    time.sleep(VENTANA_MEDIDA_CPU)
    return procs


def procesos_consumo_alto(umbral_cpu: float, umbral_ram_mb: int) -> list[ProcesoHallazgo]:
    """Procesos cuyo CPU (%) o RAM (MB) alcanza el umbral indicado."""
    return [h for h in _hallazgos_medidos()
            if h.cpu_percent >= umbral_cpu or h.ram_mb >= umbral_ram_mb]


# Inactividad: CPU por debajo de este umbral (%) — decisión registrada en el plan.
UMBRAL_CPU_INACTIVO = 1.0


def procesos_inactivos(horas_inactividad: float) -> list[ProcesoHallazgo]:
    """Procesos inactivos: CPU (%) por debajo de UMBRAL_CPU_INACTIVO.

    `horas_inactividad` es la ventana en horas que solicita el usuario
    (la conversión "X días" -> 24 * X la realiza el llamador).
    """
    return [h for h in _hallazgos_medidos() if h.cpu_percent < UMBRAL_CPU_INACTIVO]


def clasificar_procesos(umbral_cpu: float, umbral_ram_mb: int) -> tuple[list, list]:
    """Una sola medición -> (alto consumo, inactivos).

    Evita medir la CPU dos veces por escaneo (0,5 s de espera y dos recorridos
    de todos los procesos).
    """
    altos, inactivos = [], []
    for hallazgo in _hallazgos_medidos():
        if hallazgo.cpu_percent >= umbral_cpu or hallazgo.ram_mb >= umbral_ram_mb:
            altos.append(hallazgo)
        if hallazgo.cpu_percent < UMBRAL_CPU_INACTIVO:
            inactivos.append(hallazgo)
    return altos, inactivos


def _hallazgos_medidos() -> list[ProcesoHallazgo]:
    """Todos los procesos reales con su consumo medido (una sola vez)."""
    hallazgos = []
    for proc in _procesos_medidos():
        nombre = str(_obtener(proc, "name"))
        if nombre.upper() == PROCESO_IDLE:
            continue
        hallazgos.append(
            ProcesoHallazgo(
                pid=proc.pid,
                nombre=nombre,
                cpu_percent=float(_obtener(proc, "cpu_percent")),
                ram_mb=int(_ram_mb(proc)),
                ruta=_exe(proc),
            )
        )
    return hallazgos


# Servicios: sc.exe localiza las etiquetas (NOMBRE_SERVICIO/NOMBRE_DE_SERVICIO,
# ESTADO, DEPENDENCIAS...) pero no los valores, que van en inglés: por eso el
# análisis se apoya en la estructura de la salida y en los valores, no en las etiquetas.
ESTADOS_SERVICIO = {
    "STOPPED",
    "RUNNING",
    "PAUSED",
    "START_PENDING",
    "STOP_PENDING",
    "PAUSE_PENDING",
    "CONTINUE_PENDING",
}

# Tipos de inicio con los que Windows arranca servicios críticos del sistema.
INICIO_CRITICO = {"BOOT_START", "SYSTEM_START"}

# "TIPO_INICIO: 2 AUTO_START" (u otra variante) en la salida de sc qc.
_RE_INICIO = re.compile(r":\s*\d+\s+(BOOT_START|SYSTEM_START|AUTO_START|DEMAND_START|DISABLED)\b")


@dataclass
class ServicioHallazgo:
    """Servicio sin dependencias que no es crítico del sistema."""

    nombre: str
    estado: str
    inicio: str = ""
    ruta: str = ""
    descripcion: str = ""


@dataclass
class _ServicioInfo:
    """Servicio consultado: estado, tipo de inicio, ruta del binario y dependencias."""

    nombre: str
    estado: str
    inicio: str
    ruta: str
    dependencias: list[str]


def _sc(*args: str) -> str:
    """Ejecuta sc.exe con los argumentos indicados y devuelve su salida estándar."""
    return subprocess.run(
        ["sc.exe", *args],
        capture_output=True,
        text=True,
        errors="replace",
        creationflags=SIN_CONSOLA,
    ).stdout


def _servicios_con_estado() -> list[tuple[str, str]]:
    """Servicios del sistema con su estado, vía `sc query type= service state= all`."""
    encontrados = []
    nombre, estado = None, None
    for linea in _sc("query", "type=", "service", "state=", "all").splitlines():
        if linea and not linea[0].isspace() and not linea.startswith("[") and ":" in linea:
            # Cabecera en columna 0: la primera de cada bloque es el nombre del
            # servicio y la segunda su nombre visible (se ignora).
            if nombre is None or estado is not None:
                nombre, estado = linea.partition(":")[2].strip(), None
        elif nombre is not None and estado is None:
            # La línea de estado es la única cuyo valor es una palabra de ESTADOS_SERVICIO.
            coincide = re.match(r"^\s+\S[^:]*:\s*\d+\s+([A-Z_]+)\s*$", linea)
            if coincide and coincide.group(1) in ESTADOS_SERVICIO:
                encontrados.append((nombre, coincide.group(1)))
                nombre, estado = None, None
    return encontrados


def _qc(nombre: str) -> tuple[str, str, list[str]]:
    """Tipo de inicio, ruta del binario y dependencias de un servicio, vía `sc qc <nombre>`."""
    inicio = ""
    ruta = ""
    campo, dependencias = None, []
    for linea in _sc("qc", nombre).splitlines():
        texto = linea.strip()
        if not texto or linea.startswith("["):
            continue
        if coincide := _RE_INICIO.search(linea):
            inicio = coincide.group(1)
        elif linea[0].isspace() and texto.startswith(":"):
            # Continuación (": otro_servicio") del último campo leído.
            if campo and campo.upper().startswith("DEPEND"):
                dependencias.append(texto.lstrip(":").strip())
        elif ":" in texto:
            # Campo nuevo: la etiqueta de dependencias contiene "DEPEND"
            # (DEPENDENCIES en inglés, DEPENDENCIAS en español); la de la ruta
            # contiene "RUTA" (NOMBRE_RUTA_BINARIO) o "PATH" (BINARY_PATH_NAME).
            campo, valor = (parte.strip() for parte in texto.partition(":")[::2])
            cu = campo.upper()
            if cu.startswith("DEPEND") and valor:
                dependencias.append(valor)
            elif ("RUTA" in cu or "PATH" in cu) and valor:
                ruta = valor
    return inicio, ruta, dependencias


# Descripción del servicio en `sc qdescription`: la etiqueta es "DESCRIPCIÓN"
# (español) o "DESCRIPTION" (inglés); se compara sin acentos por el encoding.
_RE_DESCRIPCION = re.compile(
    r"^\s*(DESCRIPCI|DESCRIPTION)[^\s:]*\s*:\s*(.*)$", re.IGNORECASE)


def descripcion_de_servicio(nombre: str) -> str:
    """Descripción del servicio tal y como la reporta Windows (`sc qdescription`).

    Windows la devuelve localizada al idioma del sistema; si el servicio no
    tiene descripción (o no se puede leer), devuelve una cadena vacía.
    """
    for linea in _sc("qdescription", nombre).splitlines():
        coincide = _RE_DESCRIPCION.match(linea)
        if coincide:
            return coincide.group(2).strip()
    return ""


def _consultar_servicios() -> list[_ServicioInfo]:
    """Todos los servicios con estado, tipo de inicio, ruta y dependencias.

    Las consultas `sc qc` (una por servicio, ~35 ms cada una) van en paralelo:
    con ~275 servicios el escaneo pasa de ~10 s a ~2 s. `executor.map`
    conserva el orden de entrada, así que el resultado es idéntico.
    """
    basicos = _servicios_con_estado()
    with ThreadPoolExecutor(max_workers=MAX_CONSULTAS_PARALELAS) as ejecutor:
        detalles = list(ejecutor.map(lambda par: _qc(par[0]), basicos))
    return [
        _ServicioInfo(
            nombre=nombre,
            estado=estado,
            inicio=inicio,
            ruta=ruta,
            dependencias=dependencias,
        )
        for (nombre, estado), (inicio, ruta, dependencias) in zip(basicos, detalles)
    ]


def servicios_sin_dependencias() -> list[ServicioHallazgo]:
    """Servicios sin dependencias propias que no son críticos del sistema.

    Un servicio se considera crítico si Windows lo arranca con el sistema
    (BOOT_START/SYSTEM_START) o si otro servicio depende de él.

    La descripción NO se consulta aquí: se pide al seleccionar el servicio
    en la interfaz (ahorra una llamada a sc.exe por cada hallazgo).
    """
    servicios = _consultar_servicios()
    requeridos = {dep.upper() for s in servicios for dep in s.dependencias}
    return [
        ServicioHallazgo(nombre=s.nombre, estado=s.estado, inicio=s.inicio, ruta=s.ruta)
        for s in servicios
        if not s.dependencias
        and s.inicio not in INICIO_CRITICO
        and s.nombre.upper() not in requeridos
    ]
