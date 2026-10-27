# tests/test_sin_consola.py
"""Las llamadas a sc.exe no deben abrir ventanas de consola (exe sin consola)."""
import subprocess

import detector
import actions
from detector import ServicioHallazgo


def test_la_bandera_es_create_no_window_en_windows():
    assert detector.SIN_CONSOLA == subprocess.CREATE_NO_WINDOW


def test_sc_se_ejecuta_sin_ventana_de_consola(monkeypatch):
    capturado = {}

    class FakeResultado:
        stdout = ""

    def fake_run(cmd, **kwargs):
        capturado.update(kwargs)
        return FakeResultado()

    monkeypatch.setattr(detector.subprocess, "run", fake_run)
    detector._sc("query", "type=", "service", "state=", "all")
    assert capturado.get("creationflags") == detector.SIN_CONSOLA


def test_acciones_sc_sin_ventana_de_consola(monkeypatch):
    banderas = []

    class FakeResultado:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        banderas.append(kwargs.get("creationflags"))
        return FakeResultado()

    monkeypatch.setattr(actions.subprocess, "run", fake_run)
    servicio = ServicioHallazgo(nombre="X", estado="RUNNING")
    resultado = actions.ejecutar(servicio, confirmar=lambda _h: True)
    assert resultado.ejecutado is True
    assert banderas == [actions.SIN_CONSOLA, actions.SIN_CONSOLA]
