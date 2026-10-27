# tests/test_risk.py
import risk
from detector import ProcesoHallazgo, ServicioHallazgo

def test_nivel_agrupa_por_riesgo():
    proceso_con_alto_consumo = ProcesoHallazgo(pid=1, nombre="navegador", cpu_percent=80.0, ram_mb=1500)
    proceso_tranquilo = ProcesoHallazgo(pid=2, nombre="inactivo", cpu_percent=0.2, ram_mb=50)
    assert risk.nivel(proceso_con_alto_consumo) == "alto"
    assert risk.nivel(proceso_tranquilo) == "bajo"

def test_nivel_servicios_quedan_en_riesgo_protegido():
    # Decisión del coordinador: los servicios dudosos de la Task 3 (PlugPlay/Power)
    # deben clasificarse en riesgo alto o medio, sin lista curada de críticos.
    for nombre in ("PlugPlay", "Power"):
        servicio = ServicioHallazgo(nombre=nombre, estado="RUNNING")
        assert risk.nivel(servicio) in {"alto", "medio"}
