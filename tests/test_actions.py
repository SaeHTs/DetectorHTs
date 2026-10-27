# tests/test_actions.py
import actions
from detector import ProcesoHallazgo, ServicioHallazgo

def test_accion_no_ejecuta_sin_confirmacion(monkeypatch):
    def no_debe_ejecutarse(*args, **kwargs):
        raise AssertionError("no debe ejecutar nada sin confirmacion")

    monkeypatch.setattr(actions.subprocess, "run", no_debe_ejecutarse)
    monkeypatch.setattr(actions.psutil, "Process", no_debe_ejecutarse)

    proceso = ProcesoHallazgo(pid=1234, nombre="innecesario", cpu_percent=0.2, ram_mb=50)
    resultado = actions.ejecutar(proceso, confirmar=lambda h: False)
    assert resultado.ejecutado is False

def test_accion_servicio_ejecuta_tras_confirmacion(monkeypatch):
    llamadas = []
    class _MockResult:
        def __init__(self):
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    def mock_run(cmd, **kwargs):
        llamadas.append(cmd)
        return _MockResult()

    monkeypatch.setattr(actions.subprocess, "run", mock_run)

    servicio = ServicioHallazgo(nombre="Diagnostico", estado="RUNNING")
    resultado = actions.ejecutar(servicio, confirmar=lambda h: True)
    assert resultado.ejecutado is True
    assert llamadas[0] == ["sc.exe", "stop", "Diagnostico"]
    assert llamadas[1] == ["sc.exe", "config", "Diagnostico", "start=", "disabled"]
    # Optional: check retcode present
    assert resultado.retcode is None or resultado.retcode == 0

def test_accion_proceso_se_apaga_tras_confirmacion(monkeypatch):
    apagados = []

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def terminate(self):
            apagados.append(self.pid)

    monkeypatch.setattr(actions.psutil, "Process", FakeProcess)

    proceso = ProcesoHallazgo(pid=1234, nombre="innecesario", cpu_percent=0.2, ram_mb=50)
    resultado = actions.ejecutar(proceso, confirmar=lambda h: True)
    assert resultado.ejecutado is True
    assert apagados == [1234]
