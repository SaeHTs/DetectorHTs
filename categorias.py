"""Categorías de servicios para los apartados de la interfaz.

Heurística orientativa (NO es una garantía del fabricante):
- Si la ruta del binario está fuera de `C:\\Windows` -> terceros.
- Dentro de Windows, el nombre decide entre windows update, dispositivos y red.
- El resto de servicios de Windows -> microsoft; si no hay ruta ni coincidencia,
  -> otros.

Las claves se usan como pestañas de la GUI y como claves de traducción.
"""
import os

# Ruta de instalación de Windows (no debe contener datos propios de la máquina).
RAIZ_WINDOWS = os.environ.get("WINDIR", r"C:\Windows").rstrip("\\") + os.sep

# Nombres de servicio por categoría (mayúsculas; se compara con nombre.upper()).
_NOMBRES = {
    "wupdate": {
        "WUAUSERV",      # Windows Update
        "USOSVC",        # Update Orchestrator
        "WAASMEDICSVC",  # Windows Update Medic
        "DOSVC",         # Delivery Optimization
        "INSTALLSERVICE",# Install Service (tiendas/actualizaciones)
        "BITS",          # Transferencia inteligente en segundo plano
    },
    "dispositivos": {
        "PLUGPLAY",
        "DEVICEINSTALL",
        "DEVICEASSOCIATIONSERVICE",
        "DEVICEASSOCIATIONBROKERSVC",
        "DEVICEPICKERUSERSVC",
        "DSMSVC",
        "WDISERVICEHOST",
        "WDISYSTEMHOST",
        "HIDSERV",
        "SENSRSVC",
        "SENSORSERVICE",
        "SENSORDATASERVICE",
        "SCDEVICEENUM",
        "DEVQUERYBROKER",
        "DISPENHSVC",
        "DISPLAYENHANCEMENTSERVICE",
    },
    "red": {
        "DHCP",
        "DNSCACHE",
        "NLASVC",
        "NETPROFM",
        "WINHTTPAUTOPROXYSVC",
        "REMOTEACCESS",
        "RASMAN",
        "SHAREDACCESS",
        "WLANSVC",
        "WCMSVC",
        "NETMAN",
        "IPHLPSVC",
        "FDRESPUB",
        "UPNPHOST",
        "LANMANSERVER",
        "LANMANWORKSTATION",
        "BROWSER",
        "ICSSVC",
        "NETTCPPORTSHARING",
        "WSCSVC",
        "NPSMSVC",
    },
}

# Orden de las pestañas de la GUI.
CATEGORIAS = ("microsoft", "wupdate", "dispositivos", "red", "terceros", "otros")


def categoria_de(nombre: str, ruta: str) -> str:
    """Categoría de un servicio a partir de su nombre y la ruta de su binario."""
    nombre = (nombre or "").strip()
    ruta = (ruta or "").strip()

    if ruta:
        if not ruta.upper().startswith(RAIZ_WINDOWS.upper()):
            return "terceros"
    else:
        # Sin ruta no se puede saber de quién es: se agrupa aparte.
        if not nombre:
            return "otros"
        # Rutas desconocidas con nombre de Windows conocido: se tratan como Microsoft.
    clave = nombre.upper()
    for categoria, nombres in _NOMBRES.items():
        if clave in nombres:
            return categoria
    if ruta:
        return "microsoft"
    return "otros"
