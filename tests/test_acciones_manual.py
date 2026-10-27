# tests/test_acciones_manual.py
"""Pruebas para la acción de cambiar servicios a modo Manual."""
import subprocess
import actions
from detector import ServicioHallazgo, SIN_CONSOLA

def test_ejecutar_manual_lanza_comando_correcto(monkeypatch):
    """Verifica que la acción 'manual' ejecute sc config <nombre> start= demand."""
    capturado = []

    def fake_run(cmd, **kwargs):
        capturado.append((cmd, kwargs))
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    
    servicio = ServicioHallazgo(nombre="TestSvc", estado="RUNNING")
    # Simulamos que el usuario quiere ponerlo en manual
    # En la implementación real, esto será una opción en el diálogo.
    resultado = actions.ejecutar_manual(servicio)
    
    assert resultado.ejecutado is True
    # Verificamos el comando exacto
    cmd, kwargs = capturado[0]
    assert cmd == ["sc.exe", "config", "TestSvc", "start=", "demand"]
    assert kwargs.get("creationflags") == SIN_CONSOLA

def test_ejecutar_manual_maneja_error(monkeypatch):
    """Verifica que si sc.exe falla, el resultado refleje el error."""
    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 1075 # Ejemplo de error de Windows
            stdout = ""
            stderr = "Error"
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    
    servicio = ServicioHallazgo(nombre="FailSvc", estado="RUNNING")
    resultado = actions.ejecutar_manual(servicio)
    
    assert resultado.ejecutado is False
    assert resultado.retcode == 1075
