# tests/test_detector_servicios.py
import detector
from detector import ServicioHallazgo, servicios_sin_dependencias

def test_servicios_sin_dependencias_filtra_criticos(monkeypatch):
    # Salidas falsas de sc.exe con la estructura real de Windows en español:
    # etiquetas localizadas (NOMBRE_SERVICIO / NOMBRE_DE_SERVICIO, ESTADO,
    # TIPO_INICIO, DEPENDENCIAS) y valores en inglés (RUNNING, AUTO_START...).
    QUERY = (
        "NOMBRE_SERVICIO: servicio_util\n"
        "NOMBRE_MOSTRAR : Utilidad general\n"
        "        TIPO               : 20  WIN32_OWN_PROCESS\n"
        "        ESTADO             : 4  RUNNING\n"
        "                                (STOPPABLE, NOT_PAUSABLE, IGNORES_SHUTDOWN)\n"
        "\n"
        "NOMBRE_SERVICIO: servicio_critico\n"
        "NOMBRE_MOSTRAR : Servicio critico del sistema\n"
        "        TIPO               : 20  WIN32_OWN_PROCESS\n"
        "        ESTADO             : 4  RUNNING\n"
        "\n"
        "NOMBRE_SERVICIO: servicio_boot\n"
        "NOMBRE_MOSTRAR : Servicio de arranque\n"
        "        TIPO               : 10  WIN32_OWN_PROCESS\n"
        "        ESTADO             : 4  RUNNING\n"
        "\n"
        "NOMBRE_SERVICIO: servicio_dependiente\n"
        "NOMBRE_MOSTRAR : Servicio que otros necesitan\n"
        "        TIPO               : 20  WIN32_OWN_PROCESS\n"
        "        ESTADO             : 4  RUNNING\n"
        "\n"
        "NOMBRE_DE_SERVICIO: servicio_con_dependencias\n"
        "NOMBRE_PARA_MOSTRAR: Servicio con dependencias propias\n"
        "        TIPO                         : 20  WIN32_SHARE_PROCESS\n"
        "        ESTADO                       : 1  STOPPED\n"
    )

    QC = {
        "servicio_util": (
            "[SC] QueryServiceConfig CORRECTO\n"
            "\n"
            "NOMBRE_SERVICIO: servicio_util\n"
            "        TIPO               : 20  WIN32_OWN_PROCESS\n"
            "        TIPO_INICIO        : 2   AUTO_START\n"
            "        CONTROL_ERROR      : 1   NORMAL\n"
            "        NOMBRE_RUTA_BINARIO: C:\\Windows\\system32\\servicio_util.exe\n"
            "        GRUPO_ORDEN_CARGA  : \n"
            "        ETIQUETA           : 0\n"
            "        NOMBRE_MOSTRAR     : Utilidad general\n"
            "        DEPENDENCIAS       : \n"
            "        NOMBRE_INICIO_SERVICIO: LocalSystem\n"
        ),
        "servicio_critico": (
            "[SC] QueryServiceConfig CORRECTO\n"
            "\n"
            "NOMBRE_SERVICIO: servicio_critico\n"
            "        TIPO               : 20  WIN32_OWN_PROCESS\n"
            "        TIPO_INICIO        : 2   AUTO_START\n"
            "        NOMBRE_RUTA_BINARIO: C:\\Windows\\System32\\svchost.exe\n"
            "        DEPENDENCIAS       : \n"
            "        NOMBRE_INICIO_SERVICIO: LocalSystem\n"
        ),
        "servicio_boot": (
            "[SC] QueryServiceConfig CORRECTO\n"
            "\n"
            "NOMBRE_SERVICIO: servicio_boot\n"
            "        TIPO               : 10  WIN32_OWN_PROCESS\n"
            "        TIPO_INICIO        : 0   BOOT_START\n"
            "        NOMBRE_RUTA_BINARIO: C:\\Windows\\System32\\drivers\\boot.sys\n"
            "        DEPENDENCIAS       : \n"
            "        NOMBRE_INICIO_SERVICIO: LocalSystem\n"
        ),
        "servicio_dependiente": (
            "[SC] QueryServiceConfig CORRECTO\n"
            "\n"
            "NOMBRE_SERVICIO: servicio_dependiente\n"
            "        TIPO               : 20  WIN32_OWN_PROCESS\n"
            "        TIPO_INICIO        : 2   AUTO_START\n"
            "        NOMBRE_RUTA_BINARIO: C:\\Windows\\system32\\dep.exe\n"
            "        DEPENDENCIAS       : servicio_critico\n"
            "        NOMBRE_INICIO_SERVICIO: LocalSystem\n"
        ),
        "servicio_con_dependencias": (
            "[SC] QueryServiceConfig CORRECTO\n"
            "\n"
            "NOMBRE_SERVICIO: servicio_con_dependencias\n"
            "        TIPO               : 20  WIN32_SHARE_PROCESS\n"
            "        TIPO_INICIO        : 3   DEMAND_START\n"
            "        NOMBRE_RUTA_BINARIO: C:\\Program Files\\Aplicacion\\app.exe\n"
            "        DEPENDENCIAS       : RpcSs\n"
            "                           : http\n"
            "        NOMBRE_INICIO_SERVICIO: LocalSystem\n"
        ),
    }

    class FakeResultado:
        def __init__(self, stdout):
            self.stdout = stdout

    QDESC = {
        "servicio_util": "DESCRIPCIÓN:  Utilidad general del sistema para tareas varias.\n",
        "servicio_critico": "DESCRIPTION:  Critical system service description.\n",
        "servicio_boot": "DESCRIPCIÓN:  Servicio de arranque del sistema.\n",
        "servicio_dependiente": "DESCRIPCIÓN:  Servicio que otros necesitan.\n",
        "servicio_con_dependencias": "DESCRIPCIÓN:  Servicio con dependencias propias.\n",
    }

    def fake_run(cmd, **kwargs):
        if "qdescription" in cmd:
            return FakeResultado(QDESC[cmd[-1]])
        if "qc" in cmd:
            return FakeResultado(QC[cmd[cmd.index("qc") + 1]])
        return FakeResultado(QUERY)

    monkeypatch.setattr(detector.subprocess, "run", fake_run)

    servicios = servicios_sin_dependencias()
    nombres = [s.nombre for s in servicios]
    assert "servicio_critico" not in [s.nombre for s in servicios_sin_dependencias()]
    assert "servicio_boot" not in nombres
    assert "servicio_dependiente" not in nombres
    assert "servicio_con_dependencias" not in nombres
    assert nombres == ["servicio_util"]
    assert servicios[0].estado == "RUNNING"
    assert servicios[0].inicio == "AUTO_START"
    assert servicios[0].ruta == "C:\\Windows\\system32\\servicio_util.exe"
    assert servicios[0].descripcion == ""  # perezosa: se pide al seleccionar
    assert detector.descripcion_de_servicio("servicio_util") == (
        "Utilidad general del sistema para tareas varias.")
    assert isinstance(servicios[0], ServicioHallazgo)


def test_escanear_servicios_no_consulta_descripciones(monkeypatch):
    """La descripción se pide al seleccionar, no en el escaneo (optimización)."""
    llamadas = []

    def fake_qc(nombre):
        return "AUTO_START", r"C:\Windows\System32\svchost.exe", []

    monkeypatch.setattr(detector, "_servicios_con_estado",
                        lambda: [(f"svc_{i}", "RUNNING") for i in range(5)])
    monkeypatch.setattr(detector, "_qc", fake_qc)
    monkeypatch.setattr(detector, "descripcion_de_servicio",
                        lambda n: llamadas.append(n) or "texto")

    servicios = servicios_sin_dependencias()
    assert len(servicios) == 5
    assert [s.descripcion for s in servicios] == [""] * 5
    assert llamadas == []  # ninguna consulta extra de descripción


def test_consultar_servicios_conserva_todos_y_su_orden(monkeypatch):
    """El escaneo en paralelo no debe perder servicios ni desordenarlos."""
    nombres = [f"svc_{i:02d}" for i in range(24)]
    monkeypatch.setattr(detector, "_servicios_con_estado",
                        lambda: [(n, "RUNNING") for n in nombres])

    def fake_qc(nombre):
        return "AUTO_START", f"C:\\{nombre}.exe", [f"dep_{nombre}"]

    monkeypatch.setattr(detector, "_qc", fake_qc)

    servicios = detector._consultar_servicios()
    assert [s.nombre for s in servicios] == nombres
    assert [s.ruta for s in servicios] == [f"C:\\{n}.exe" for n in nombres]
    assert [s.dependencias for s in servicios] == [[f"dep_{n}"] for n in nombres]
