# modules/i18n.py
"""Idioma de la interfaz: detección del sistema, persistencia y traducción.

El idioma activo se guarda en un JSON pequeño dentro de `%APPDATA%`. Al arrancar
se lee esa preferencia; si no existe o no sirve, se detecta el idioma de Windows
(español -> español, inglés -> inglés, cualquier otro -> español).

La preferencia SOLO se escribe cuando el usuario elige el idioma a mano en la
cabecera: así, si nunca lo toca, la app sigue al idioma de Windows.
"""
import json
import os

from modules import textos

IDIOMAS = ("es", "en")
_IDIOMA_ACTIVO = "es"

# Idioma primario de Windows = 10 bits bajos del LANGID (0x0A español, 0x09 inglés)
_IDIOMA_POR_PRIMARIO = {0x0A: "es", 0x09: "en"}


def _carpeta_prefs() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DetectorHTs")


RUTA_PREFS = os.path.join(_carpeta_prefs(), "prefs.json")


def _idioma_desde_langid(langid: int) -> str:
    """Convierte el LANGID de Windows al código soportado (respaldo 'es')."""
    return _IDIOMA_POR_PRIMARIO.get(langid & 0x3FF, "es")


def _idioma_windows() -> str:
    """Idioma de la interfaz de Windows: 'es', 'en' o 'es' como respaldo."""
    try:
        import ctypes
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return _idioma_desde_langid(langid)
    except Exception:
        return "es"


def detectar_idioma() -> str:
    """Idioma del sistema: 'en' solo si Windows está en inglés; el resto -> 'es'."""
    etiqueta = _idioma_windows()
    if str(etiqueta).lower().startswith("en"):
        return "en"
    return "es"


def idioma() -> str:
    """Idioma activo de la interfaz."""
    return _IDIOMA_ACTIVO


def cargar_preferencia() -> str:
    """Lee la preferencia guardada; si no sirve, detecta el idioma del sistema."""
    try:
        with open(RUTA_PREFS, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if isinstance(datos, dict) and datos.get("idioma") in IDIOMAS:
            return datos["idioma"]
    except Exception:
        pass
    return detectar_idioma()


def guardar_preferencia(codigo: str) -> bool:
    """Guarda el idioma elegido; devuelve False si no se pudo (nunca lanza)."""
    if codigo not in IDIOMAS:
        return False
    try:
        carpeta = os.path.dirname(RUTA_PREFS)
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        # escritura atómica: primero a un temporal, luego se renombra
        temporal = RUTA_PREFS + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump({"idioma": codigo}, f, ensure_ascii=False)
        os.replace(temporal, RUTA_PREFS)
        return True
    except OSError:
        return False


def fijar_idioma(codigo: str, guardar: bool = False) -> str:
    """Cambia el idioma activo (validando). Devuelve el aplicado.

    `guardar=True` persiste la elección (la usa el selector de la cabecera);
    por defecto no se guarda, para que el arranque siga al idioma de Windows.
    """
    global _IDIOMA_ACTIVO
    if codigo not in IDIOMAS:
        codigo = "es"
    _IDIOMA_ACTIVO = codigo
    if guardar:
        guardar_preferencia(codigo)  # si falla se ignora: no debe romper la app
    return codigo


def _resolver(valor):
    """Resuelve un valor anidado: ('clave', {kwargs}) se traduce al idioma activo."""
    if isinstance(valor, tuple) and len(valor) == 2 and isinstance(valor[0], str):
        try:
            return t(valor[0], **(valor[1] or {}))
        except Exception:
            return ""
    return valor


class _Marcadores(dict):
    """Marcadores que faltan -> texto vacío (no rompe la pantalla)."""

    def __missing__(self, clave):
        return ""


def t(clave: str, **kwargs) -> str:
    """Traduce `clave` al idioma activo. Nunca revienta."""
    tabla = textos.TEXTOS.get(_IDIOMA_ACTIVO) or textos.TEXTOS["es"]
    try:
        texto = tabla.get(clave)
        if texto is None:
            texto = textos.TEXTOS["es"].get(clave)
        if texto is None:
            texto = textos.TEXTOS["en"].get(clave, clave)
    except TypeError:  # clave no hashable (por ejemplo, una tupla)
        return ""
    if not isinstance(texto, str):
        return ""
    if kwargs:
        try:
            return texto.format_map(_Marcadores(
                {k: _resolver(v) for k, v in kwargs.items()}))
        except Exception:
            return texto
    return texto
