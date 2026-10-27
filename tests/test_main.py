# tests/test_main.py
from unittest.mock import MagicMock

# Import modules that main uses (detector, risk, actions)
import detector
import risk
import actions

# Import fake hallazgos
from detector import ProcesoHallazgo, ServicioHallazgo


def test_main_flow_with_mocks(monkeypatch):
    """Simulates the full flow with mocked detectors, risk and actions."""
    # --- Fake hallazgos ---
    proc1 = ProcesoHallazgo(pid=1001, nombre="proceso1", cpu_percent=80.0, ram_mb=300)
    proc2 = ProcesoHallazgo(pid=1002, nombre="proceso2", cpu_percent=0.5, ram_mb=50)
    svc1 = ServicioHallazgo(nombre="servicio1", estado="RUNNING")

    # Patch detector functions (una sola medicion para altos e inactivos)
    monkeypatch.setattr(detector, "clasificar_procesos",
                        MagicMock(return_value=([proc1], [proc2])))
    monkeypatch.setattr(detector, "servicios_sin_dependencias", MagicMock(return_value=[svc1]))

    # Patch risk.nivel
    def mock_nivel(h):
        if isinstance(h, ProcesoHallazgo):
            return "alto" if h.pid == 1001 else "bajo"
        else:
            return "medio"
    monkeypatch.setattr(risk, "nivel", mock_nivel)

    # Patch actions.ejecutar to record calls
    from actions import ResultadoAccion
    ejecuciones = []
    def mock_accion_ejecutar(hallazgo, confirmar):
        ejecuciones.append((hallazgo, confirmar(hallazgo)))
        return ResultadoAccion(ejecutado=True, detalle=f"acción sobre {hallazgo.nombre if isinstance(hallazgo, ProcesoHallazgo) else hallazgo.nombre}")
    monkeypatch.setattr(actions, "ejecutar", mock_accion_ejecutar)

    # Patch input to simulate user responses
    respuestas = ["si", "no", "si"]
    input_iter = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda _: next(input_iter))

    # Import main after patching (module-level imports will use the patched modules)
    import main

    # Run main.ejecutar
    main.ejecutar()

    # Verify detector calls
    detector.clasificar_procesos.assert_called_once_with(umbral_cpu=50.0, umbral_ram_mb=256)
    detector.servicios_sin_dependencias.assert_called_once()

    # Verify risk.nivel was called for each hallazgo (by side effect)
    # We can check that nivel was called at least twice (for proc1 and svc1)
    # but we don't have a direct count; trust side effect.

    # Verify actions.ejecutar called exactly for the two confirmed (proc1 and svc1)
    assert len(ejecuciones) == 2
    assert ejecuciones[0][0] == proc1
    assert ejecuciones[0][1] == True
    assert ejecuciones[1][0] == svc1
    assert ejecuciones[1][1] == True

    print("✓ test_main_flow_with_mocks passed")