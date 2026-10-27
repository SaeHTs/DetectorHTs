# tests/test_detector.py
import psutil
import detector
import pytest
from detector import procesos_consumo_alto, procesos_inactivos

@pytest.fixture(autouse=True)
def sin_espera_real(monkeypatch):
    """Los tests de escaneo no deben esperar la ventana real de medición."""
    monkeypatch.setattr(detector.time, "sleep", lambda s: None)

def test_procesos_consumo_alto_filtra_por_umbral(monkeypatch):
    class FakeProceso:
        def __init__(self, pid, nombre, cpu, ram_mb, exe=None):
            self.pid, self.name, self.cpu_percent, self.memory_mb = pid, nombre, cpu, ram_mb
            self.exe = exe

    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [
        FakeProceso(1, "alto_cpu", 80.0, 100, exe=r"C:\Apps\alto_cpu.exe"),
        FakeProceso(2, "bajo_cpu", 1.0, 50),
    ])
    hallazgos = procesos_consumo_alto(umbral_cpu=50.0, umbral_ram_mb=256)
    assert [h.nombre for h in hallazgos] == ["alto_cpu"]
    assert hallazgos[0].ruta == "C:\\Apps\\alto_cpu.exe"


def test_no_reporta_system_idle_process(monkeypatch):
    """El 'System Idle Process' es el tiempo OCIOSO de la CPU, no un proceso."""
    class FakeProceso:
        def __init__(self, pid, nombre, cpu, ram):
            self.pid, self.name, self.cpu_percent, self.memory_mb = pid, nombre, cpu, ram

    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [
        FakeProceso(0, "System Idle Process", 90.0, 0),
        FakeProceso(1, "proceso_real", 80.0, 100),
    ])
    hallazgos = procesos_consumo_alto(umbral_cpu=50.0, umbral_ram_mb=256)
    assert [h.nombre for h in hallazgos] == ["proceso_real"]

def test_procesos_inactivos_filtra_por_horas(monkeypatch):
    class FakeProceso:
        def __init__(self, pid, nombre, cpu, ram_mb):
            self.pid, self.name, self.cpu_percent, self.memory_mb = pid, nombre, cpu, ram_mb

    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [
        FakeProceso(1, "inactivo", 0.0, 50),
        FakeProceso(2, "activo", 70.0, 500),
    ])
    hallazgos = procesos_inactivos(horas_inactividad=24.0)
    assert [h.nombre for h in hallazgos] == ["inactivo"]
    assert hallazgos[0].ruta == ""  # el proceso falso no expone exe


def test_procesos_consumo_alto_mide_cpu_tras_ventana_de_cebado(monkeypatch):
    """psutil da 0 % en la primera lectura: se ceba, se espera y se mide."""
    lecturas = {"n": 0}

    class FakeProceso:
        pid, name, memory_mb = 1, "medidor", 100

        def cpu_percent(self, interval=None):
            lecturas["n"] += 1
            return 0.0 if lecturas["n"] == 1 else 80.0

    esperas = []
    monkeypatch.setattr(detector.time, "sleep", lambda s: esperas.append(s))
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [FakeProceso()])

    hallazgos = procesos_consumo_alto(umbral_cpu=50.0, umbral_ram_mb=256)
    assert hallazgos[0].cpu_percent == 80.0          # no el 0 % del cebado
    assert esperas == [detector.VENTANA_MEDIDA_CPU]  # se esperó la ventana


def test_procesos_inactivos_tambien_ceba_la_cpu(monkeypatch):
    lecturas = {"n": 0}

    class FakeProceso:
        pid, name, memory_mb = 1, "tranquilo", 30

        def cpu_percent(self, interval=None):
            lecturas["n"] += 1
            return 0.0 if lecturas["n"] == 1 else 0.5

    monkeypatch.setattr(detector.time, "sleep", lambda s: None)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [FakeProceso()])

    hallazgos = procesos_inactivos(horas_inactividad=24.0)
    assert hallazgos[0].cpu_percent == 0.5
    assert lecturas["n"] == 2  # cebado + medición


def test_clasificar_procesos_mide_la_cpu_una_sola_vez(monkeypatch):
    """Un escaneo = una ventana de medición, aunque se pidan ambas listas."""
    class FakeProceso:
        def __init__(self, pid, nombre, cpu, ram):
            self.pid, self.name, self.cpu_percent, self.memory_mb = pid, nombre, cpu, ram

    mediciones = []
    procs = [FakeProceso(1, "jugador", 90.0, 900),
             FakeProceso(2, "tranquilo", 0.2, 20),
             FakeProceso(3, "memoria", 0.0, 700)]

    def medir():
        mediciones.append(1)
        return procs

    monkeypatch.setattr(detector, "_procesos_medidos", medir)

    altos, inactivos = detector.clasificar_procesos(umbral_cpu=50.0, umbral_ram_mb=256)
    assert len(mediciones) == 1
    assert [p.nombre for p in altos] == ["jugador", "memoria"]
    assert [p.nombre for p in inactivos] == ["tranquilo", "memoria"]
