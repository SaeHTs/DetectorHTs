# tests/test_i18n.py
import json

import pytest

from modules import i18n, textos


@pytest.fixture(autouse=True)
def prefs_tmp(monkeypatch, tmp_path):
    """Redirige la carpeta de preferencias a un temporal (no toca %APPDATA% real)."""
    carpeta = tmp_path / "DetectorHTs"
    monkeypatch.setattr(i18n, "RUTA_PREFS", str(carpeta / "prefs.json"))
    i18n.fijar_idioma("es")
    yield carpeta


def test_claves_completas_en_ambos_idiomas():
    es = set(textos.TEXTOS["es"].keys())
    en = set(textos.TEXTOS["en"].keys())
    assert es == en, f"claves desiguales: {es ^ en}"


def test_traduccion_basica_y_formato():
    i18n.fijar_idioma("es")
    assert i18n.t("btn_escanear") == "Escanear"
    assert i18n.t("estado_escaneo_ok", procesos=2, servicios=3) == "Escaneo completado: 2 proceso(s), 3 servicio(s)."
    i18n.fijar_idioma("en")
    assert i18n.t("btn_escanear") == "Scan"


def test_clave_inexistente_devuelve_la_clave_sin_reventar():
    assert i18n.t("clave_que_no_existe") == "clave_que_no_existe"


def test_guardar_y_cargar_preferencia(prefs_tmp):
    i18n.fijar_idioma("en", guardar=True)
    assert i18n.idioma() == "en"
    assert json.loads((prefs_tmp / "prefs.json").read_text(encoding="utf-8")) == {"idioma": "en"}
    assert i18n.cargar_preferencia() == "en"


def test_carga_invalida_respalda_a_deteccion(prefs_tmp):
    prefs_tmp.mkdir(parents=True)
    (prefs_tmp / "prefs.json").write_text('{"idioma": "fr"}', encoding="utf-8")
    # 'fr' no es válido -> se usa la detección del sistema (en este equipo es/es o en)
    assert i18n.cargar_preferencia() in i18n.IDIOMAS


def test_fijar_idioma_invalido_usa_espanol():
    assert i18n.fijar_idioma("de") == "es"
