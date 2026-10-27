# tests/test_gui.py
import tkinter as tk

import pytest

import gui
from detector import ProcesoHallazgo, ServicioHallazgo


@pytest.fixture(scope="session")
def raiz_compartida():
    """Una sola raíz Tk por sesión: Tcl/Tk se rompe si se destruye y se re-crea."""
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture()
def app(monkeypatch, raiz_compartida):
    """App real con datos falsos ya escaneados (sin tocar el sistema)."""
    altos = [
        ProcesoHallazgo(pid=101, nombre="navegador", cpu_percent=80.0, ram_mb=1500,
                        ruta=r"C:\Apps\navegador.exe"),
        ProcesoHallazgo(pid=102, nombre="juego", cpu_percent=10.0, ram_mb=900),
    ]
    inactivos = [ProcesoHallazgo(pid=103, nombre="ayuda", cpu_percent=0.0, ram_mb=40)]
    servicios = [
        ServicioHallazgo(nombre="wuauserv", estado="RUNNING",
                         inicio="AUTO_START", ruta=r"C:\Windows\System32\svchost.exe",
                         descripcion="Habilita la detección y descarga de actualizaciones."),
        ServicioHallazgo(nombre="MiAppSvc", estado="STOPPED",
                         inicio="DEMAND_START", ruta=r"C:\Program Files\MiApp\app.exe"),
        ServicioHallazgo(nombre="PlugPlay", estado="RUNNING",
                         inicio="AUTO_START", ruta=r"C:\Windows\System32\svchost.exe"),
    ]
    monkeypatch.setattr(gui, "clasificar_procesos",
                        lambda **kw: (altos, inactivos))
    monkeypatch.setattr(gui, "servicios_sin_dependencias", lambda: servicios)

    # Limpia los hijos de la sesión anterior (cada test crea su propia app).
    for hijo in list(raiz_compartida.winfo_children()):
        hijo.destroy()

    ventana = gui.DetectorGUI(raiz_compartida)
    ventana._mostrar_escaneo(altos, inactivos, servicios)
    raiz_compartida.update()
    yield ventana
    ventana.cerrar()
    raiz_compartida.withdraw()


def test_pestanas_por_categoria(app):
    esperadas = [f"cat_{c}" for c in
                 ("microsoft", "wupdate", "dispositivos", "red", "terceros", "otros")]
    tabs = app.notebook.tabs()
    assert len(tabs) == 6
    textos = [app.notebook.tab(t, "text") for t in tabs]
    from modules import i18n
    for clave, texto in zip(esperadas, textos):
        assert i18n.t(clave).split(" ")[0] in texto  # título + contador


def test_servicios_repartidos_por_categoria(app):
    # Con el filtro "solo en ejecución" desactivado se ven los 3 servicios.
    app.var_solo_ejecucion.set(False)
    app._redibujar_tablas()
    assert app.arboles_servicios["wupdate"].exists("svc_0")
    assert app.arboles_servicios["terceros"].exists("svc_1")
    assert app.arboles_servicios["dispositivos"].exists("svc_2")


def test_procesos_en_tabla_con_filtro_inactivos(app):
    # Filtro por defecto: inactivos ocultos -> solo 2 filas de alto consumo.
    assert len(app.arbol_proc.get_children()) == 2
    app.var_inactivos.set(True)
    app._redibujar_tablas()
    assert len(app.arbol_proc.get_children()) == 3


def test_filtro_solo_ejecucion(app):
    assert len(app.arboles_servicios["wupdate"].get_children()) == 1
    app.var_solo_ejecucion.set(False)
    app._redibujar_tablas()
    assert len(app.arboles_servicios["wupdate"].get_children()) == 1  # wuauserv corre
    # MiAppSvc estaba STOPPED; con el filtro apagado aparece en terceros.
    assert any(app.arboles_servicios["terceros"].get_children())


def test_accion_sin_seleccion_no_pregunta_ni_actua(app, monkeypatch):
    def no_preguntar(*a, **kw):
        raise AssertionError("no debe pedir confirmacion sin seleccion")
    def no_ejecutar(*a, **kw):
        raise AssertionError("no debe ejecutar nada sin seleccion")
    monkeypatch.setattr(gui.messagebox, "askyesno", no_preguntar)
    monkeypatch.setattr(gui.actions, "ejecutar", no_ejecutar)

    app._accion_servicios()
    app._accion_procesos()
    from modules import i18n
    assert i18n.t("estado_nada_seleccionado") in app.etiqueta_estado.cget("text")


def test_accion_servicios_cancelada_no_ejecuta(app, monkeypatch):
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: False)
    def no_ejecutar(*a, **kw):
        raise AssertionError("cancelar no debe ejecutar nada")
    monkeypatch.setattr(gui.actions, "ejecutar", no_ejecutar)

    arbol = app.arboles_servicios["wupdate"]
    arbol.selection_set("svc_0")
    app._accion_servicios()
    app.root.update()
    from modules import i18n
    assert i18n.t("estado_accion_cancelada") in app.etiqueta_estado.cget("text")


def test_accion_servicios_confirmada_ejecuta_y_registra(app, monkeypatch):
    import time

    from actions import ResultadoAccion

    def esperar_en_log(app, texto, intentos=40):
        for _ in range(intentos):
            app.root.update()
            if texto in app.log.get("1.0", "end"):
                return True
            time.sleep(0.05)
        return False

    llamadas = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: True)
    monkeypatch.setattr(gui.actions, "ejecutar",
                        lambda h, confirmar: llamadas.append(h) or ResultadoAccion(
                            ejecutado=True, detalle="ok", retcode=None))
    monkeypatch.setattr(gui, "psutil_pid_exists", lambda pid: False)

    arbol = app.arboles_servicios["wupdate"]
    arbol.selection_set("svc_0")
    app._accion_servicios()
    from modules import i18n
    assert esperar_en_log(app, i18n.t("log_servicio_ok", nombre="wuauserv"))
    assert [h.nombre for h in llamadas] == ["wuauserv"]
    assert i18n.t("estado_accion_ok", ok=1, total=1) in app.etiqueta_estado.cget("text")


def test_cambio_de_idioma_en_vivo(app):
    app._aplicar_idioma("en")
    assert app.boton_escanear.boton.cget("text") == "Scan"
    assert app.notebook.tab(app.notebook.tabs()[0], "text").startswith("Microsoft")
    app._aplicar_idioma("es")
    assert app.boton_escanear.boton.cget("text") == "Escanear"


def test_descripcion_del_servicio_al_seleccionar(app):
    app.arboles_servicios["wupdate"].selection_set("svc_0")
    app.root.update()
    assert "Habilita la detección y descarga de actualizaciones." in app.lbl_desc_serv.cget("text")


def test_descripcion_se_pide_al_seleccionar_y_se_cachea(app, monkeypatch):
    """Sin descripción en el escaneo: se pide una vez al seleccionar y se guarda."""
    llamadas = []

    def fake_desc(nombre):
        llamadas.append(nombre)
        return "Descripción obtenida en vivo."

    monkeypatch.setattr(gui, "descripcion_de_servicio", fake_desc)

    app.arboles_servicios["dispositivos"].selection_set("svc_1")  # PlugPlay, sin descripción
    app.root.update()
    assert llamadas == ["PlugPlay"]
    assert "Descripción obtenida en vivo." in app.lbl_desc_serv.cget("text")

    app.arboles_servicios["dispositivos"].selection_remove("svc_1")
    app.arboles_servicios["dispositivos"].selection_set("svc_1")
    app.root.update()
    assert llamadas == ["PlugPlay"]  # la segunda vez sale de la caché


def test_descripcion_del_proceso_muestra_la_ruta(app):
    app.var_inactivos.set(True)
    app._redibujar_tablas()
    app.arbol_proc.selection_set("proc_0")  # navegador (alto consumo)
    app.root.update()
    assert "navegador" in app.lbl_desc_proc.cget("text")
    assert "Apps" in app.lbl_desc_proc.cget("text")


def test_confirmacion_incluye_descripcion(app, monkeypatch):
    capturado = {}
    def fake_ask(titulo, texto, **kw):
        capturado["texto"] = texto
        return False  # cancelar: no debe ejecutar nada
    monkeypatch.setattr(gui.messagebox, "askyesno", fake_ask)

    app.arboles_servicios["wupdate"].selection_set("svc_0")
    app._accion_servicios()
    assert "Habilita la detección y descarga de actualizaciones." in capturado["texto"]


def test_barra_de_busqueda_filtra_procesos(app):
    from modules import i18n
    assert app.entrada_busqueda_proc.get() == i18n.t("buscar_proceso")  # placeholder
    app.var_busqueda_proc.set("navegador")
    app._redibujar_tablas()
    assert len(app.arbol_proc.get_children()) == 1
    app.var_busqueda_proc.set("xyz-nada")
    app._redibujar_tablas()
    assert len(app.arbol_proc.get_children()) == 0


def test_barra_de_busqueda_filtra_servicios(app):
    app.var_busqueda_serv.set("wua")
    app._redibujar_tablas()
    assert len(app.arboles_servicios["wupdate"].get_children()) == 1
    assert len(app.arboles_servicios["terceros"].get_children()) == 0
    assert len(app.arboles_servicios["dispositivos"].get_children()) == 0


def test_cambiar_idioma_tras_escanear_conserva_servicios(app, monkeypatch):
    """Tras escanear, cambiar de idioma no debe vaciar las tablas de servicios."""
    from modules import i18n
    monkeypatch.setattr(i18n, "guardar_preferencia", lambda _c: True)

    app._aplicar_idioma("es")
    en_es = sum(len(a.get_children()) for a in app.arboles_servicios.values())
    assert en_es == 2  # wuauserv y PlugPlay (en ejecución)

    app._aplicar_idioma("en")
    en_en = sum(len(a.get_children()) for a in app.arboles_servicios.values())
    assert en_en == en_es

    app._aplicar_idioma("es")
    de_vuelta = sum(len(a.get_children()) for a in app.arboles_servicios.values())
    assert de_vuelta == en_es


def test_cambiar_idioma_tras_escanear_conserva_procesos(app, monkeypatch):
    """Lo mismo para la tabla de procesos: el idioma no filtra nada."""
    from modules import i18n
    monkeypatch.setattr(i18n, "guardar_preferencia", lambda _c: True)

    app._aplicar_idioma("es")
    assert len(app.arbol_proc.get_children()) == 2
    app._aplicar_idioma("en")
    assert len(app.arbol_proc.get_children()) == 2


def test_cambio_idioma_conserva_la_busqueda_escrita(app, monkeypatch):
    """Una búsqueda real escrita por el usuario sobrevive al cambio de idioma."""
    from modules import i18n
    monkeypatch.setattr(i18n, "guardar_preferencia", lambda _c: True)

    app.var_busqueda_serv.set("wua")
    app._aplicar_idioma("en")
    assert len(app.arboles_servicios["wupdate"].get_children()) == 1


def _esperar_log(app, texto, intentos=40):
    import time
    for _ in range(intentos):
        app.root.update()
        if texto in app.log.get("1.0", "end"):
            return True
        time.sleep(0.05)
    return False


def test_boton_manual_ejecuta_accion_manual(app, monkeypatch):
    from actions import ResultadoAccion
    from modules import i18n

    llamadas = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: True)
    monkeypatch.setattr(
        gui.actions, "ejecutar_manual",
        lambda h: llamadas.append(h) or ResultadoAccion(ejecutado=True))

    app.arboles_servicios["wupdate"].selection_set("svc_0")
    app._accion_servicios_manual()

    assert [h.nombre for h in llamadas] == ["wuauserv"]
    assert _esperar_log(app, i18n.t("log_servicio_manual_ok", nombre="wuauserv"))


def test_boton_manual_cancelado_no_ejecuta(app, monkeypatch):
    from modules import i18n

    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: False)

    def no_ejecutar(*a, **kw):
        raise AssertionError("cancelar no debe ejecutar nada")

    monkeypatch.setattr(gui.actions, "ejecutar_manual", no_ejecutar)

    app.arboles_servicios["wupdate"].selection_set("svc_0")
    app._accion_servicios_manual()
    app.root.update()
    assert i18n.t("estado_accion_cancelada") in app.etiqueta_estado.cget("text")


def test_confirmacion_manual_incluye_descripcion(app, monkeypatch):
    capturado = {}

    def fake_ask(titulo, texto, **kw):
        capturado["texto"] = texto
        return False

    monkeypatch.setattr(gui.messagebox, "askyesno", fake_ask)

    app.arboles_servicios["wupdate"].selection_set("svc_0")
    app._accion_servicios_manual()
    assert "Habilita la detección y descarga de actualizaciones." in capturado["texto"]


def test_busqueda_no_distingue_mayusculas(app):
    app.var_busqueda_serv.set("WUAUSERV")
    app._redibujar_tablas()
    assert len(app.arboles_servicios["wupdate"].get_children()) == 1
