# gui.py
"""Detector de procesos y servicios innecesarios de Windows - GUI principal.

Interfaz Tkinter con la temática cyberdark de Drivers-HTs: paleta cian/azul
sobre fondo oscuro, rejilla HUD, línea degradada bajo la cabecera, portada
centrada, chip de estado y selector de idioma ES|EN en vivo.

Apartados: los servicios detectados se agrupan por categoría del sistema
(Microsoft, Windows Update, Dispositivos, Red, Terceros, Otros) en pestañas;
los procesos se listan aparte (alto consumo e inactivos). Ninguna acción se
ejecuta sin confirmación explícita del usuario.
"""
import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox, ttk

from modules import i18n, textos
from detector import (
    ProcesoHallazgo,
    ServicioHallazgo,
    clasificar_procesos,
    descripcion_de_servicio,
    servicios_sin_dependencias,
)
from risk import nivel
import actions
from categorias import CATEGORIAS, categoria_de

# Version de la app: una sola fuente de verdad (titulo de la ventana).
VERSION = "1.0.0"

# Umbrales del motor (los mismos del diseño original).
UMBRAL_CPU_ALTO = 50.0
UMBRAL_RAM_ALTO_MB = 256


def ruta_recurso(nombre: str) -> str:
    """Resuelve un recurso empaquetado (compatible con PyInstaller --onefile)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    candidatos = [os.path.join(base, nombre), os.path.join(base, "docs", nombre)]
    for ruta in candidatos:
        if os.path.exists(ruta):
            return ruta
    return candidatos[0]


COLOR_FONDO = "#05080f"
COLOR_FONDO_ALT = "#070d18"
COLOR_PANEL = "#0a1422"
COLOR_PANEL_ALT = "#0d1b2e"
COLOR_BORDE = "#1b5570"
COLOR_TEXTO = "#dbeafe"
COLOR_TEXTO_TENUE = "#7c93b5"
COLOR_ACENTO = "#22d3ee"
COLOR_ACENTO_HOVER = "#67e8f9"
COLOR_ACENTO_2 = "#1e5bff"
COLOR_OK = "#34d399"
COLOR_ERROR = "#fb7185"
COLOR_AVISO = "#fbbf24"

FUENTE = "Segoe UI"
FUENTE_MONO = "Consolas"


def mezclar_color(c1: str, c2: str, t: float) -> str:
    """Interpola dos colores hex (#rrggbb) con t entre 0 y 1."""
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def linea_degradado(padre) -> tk.Canvas:
    """Linea neon de 2 px con degradado cian -> azul."""
    lienzo = tk.Canvas(padre, height=2, bg=COLOR_FONDO, highlightthickness=0, bd=0)

    def dibujar(event):
        lienzo.delete("all")
        ancho = max(1, event.width)
        for x in range(0, ancho, 4):
            color = mezclar_color(COLOR_ACENTO, COLOR_ACENTO_2, x / ancho)
            lienzo.create_rectangle(x, 0, x + 4, 2, fill=color, outline=color)

    lienzo.bind("<Configure>", dibujar)
    return lienzo


def portada_cabecera(padre, alto: int = 62):
    """Portada centrada en la cabecera (portada_limpia.png o portada.png)."""
    ruta = ruta_recurso("portada_limpia.png")
    if not os.path.exists(ruta):
        ruta = ruta_recurso("portada.png")
        if not os.path.exists(ruta):
            return None
    try:
        imagen = tk.PhotoImage(file=ruta)
        factor = max(1, imagen.height() // alto)
        reducida = imagen.subsample(factor, factor)
        reducida._referencia_cabecera = padre  # evita el recolector de basura
        return reducida
    except tk.TclError:
        return None


def boton_con_halo(padre, texto, estilo, comando, color_halo=COLOR_ACENTO, **opciones):
    """Botón con halo de 1 px que se ilumina al pasar el mouse."""
    contenedor = tk.Frame(padre, bg=padre["bg"])
    boton = ttk.Button(contenedor, text=texto, style=estilo, command=comando, **opciones)
    boton.pack(padx=1, pady=1)

    def entrar(_e):
        contenedor.configure(bg=color_halo)

    def salir(_e):
        contenedor.configure(bg=padre["bg"])

    boton.bind("<Enter>", entrar)
    boton.bind("<Leave>", salir)
    contenedor.boton = boton
    return contenedor


def es_admin() -> bool:
    """True si el proceso tiene permisos de administrador (False si no puede saberse)."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return True


class DetectorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(i18n.t("app_titulo", version=VERSION))
        self.root.geometry("1100x700")
        self.root.minsize(980, 640)
        self.root.configure(bg=COLOR_FONDO)
        try:
            self.root.iconbitmap(ruta_recurso("icono_axiios_glow.ico"))
        except tk.TclError:
            try:
                self.root.iconbitmap(ruta_recurso("icono_axiios.ico"))
            except tk.TclError:
                pass  # icono no disponible: se usa el de Tk por defecto

        self.cola = queue.Queue(maxsize=400)

        # Datos del último escaneo (en memoria, para re-traducir y filtrar).
        self._altos: list[ProcesoHallazgo] = []
        self._inactivos: list[ProcesoHallazgo] = []
        self._servicios: list[ServicioHallazgo] = []
        self._mapa_servicios: dict[str, ServicioHallazgo] = {}
        self._mapa_procesos: dict[str, ProcesoHallazgo] = {}

        # Idioma: la preferencia guardada (si el usuario la eligió) o la del sistema
        self._textos_registrados: list = []
        i18n.fijar_idioma(i18n.cargar_preferencia())
        self._estado_clave = "estado_listo"
        self._estado_kwargs: dict = {}
        self._estado_texto = i18n.t("estado_listo")
        self._estado_color = COLOR_TEXTO
        self._chip_clave = "chip_listo"
        self._chip_color = COLOR_TEXTO
        self._escaneando = False
        self._redibujo_pendiente = None  # debounce de las barras de búsqueda
        self._placeholders = []          # (entrada, clave, variable)
        self._busquedas = {}             # tipo -> (variable, clave)

        self._configurar_estilos()
        self._crear_widgets()
        self._aplicar_idioma(self.idioma_actual, inicial=True)
        if not es_admin():
            self._log_t("aviso_admin", COLOR_AVISO)
        self._after_id = self.root.after(100, self._procesar_cola)

    def cerrar(self):
        """Cierra la app de forma limpia (cancela temporizadores pendientes)."""
        for temporizador in (self._after_id, self._redibujo_pendiente):
            if temporizador is not None:
                try:
                    self.root.after_cancel(temporizador)
                except Exception:
                    pass
        for hijo in self.root.winfo_children():
            try:
                hijo.destroy()
            except tk.TclError:
                pass

    # ------------------------------------------------------------- interfaz
    def _configurar_estilos(self):
        estilo = ttk.Style(self.root)
        estilo.theme_use("clam")
        estilo.configure(".", background=COLOR_FONDO, foreground=COLOR_TEXTO,
                         fieldbackground=COLOR_PANEL, borderwidth=0,
                         font=(FUENTE, 9))
        estilo.configure("TFrame", background=COLOR_FONDO)
        estilo.configure("Card.TFrame", background=COLOR_PANEL)
        estilo.configure("TLabel", background=COLOR_FONDO, foreground=COLOR_TEXTO)
        estilo.configure("Card.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXTO)

        estilo.configure("TButton", background=COLOR_PANEL_ALT, foreground=COLOR_TEXTO,
                         bordercolor=COLOR_BORDE, lightcolor=COLOR_PANEL_ALT,
                         darkcolor=COLOR_PANEL_ALT, padding=(14, 8),
                         font=(FUENTE, 9, "bold"), relief="flat")
        estilo.map("TButton",
                   background=[("disabled", COLOR_PANEL), ("active", "#12314a")],
                   foreground=[("disabled", "#4b5f78")])
        estilo.configure("Accent.TButton", background=COLOR_ACENTO, foreground="#04121a",
                         bordercolor=COLOR_ACENTO, lightcolor=COLOR_ACENTO,
                         darkcolor=COLOR_ACENTO, padding=(14, 8),
                         font=(FUENTE, 9, "bold"), relief="flat")
        estilo.map("Accent.TButton",
                   background=[("pressed", "#06b6d4"), ("active", COLOR_ACENTO_HOVER)],
                   foreground=[("active", "#04121a")])
        estilo.configure("Blue.TButton", background=COLOR_ACENTO_2, foreground="#f5f9ff",
                         bordercolor=COLOR_ACENTO_2, lightcolor=COLOR_ACENTO_2,
                         darkcolor=COLOR_ACENTO_2, padding=(14, 8),
                         font=(FUENTE, 9, "bold"), relief="flat")
        estilo.map("Blue.TButton",
                   background=[("pressed", "#133fc4"), ("active", "#7aa8ff")],
                   foreground=[("active", "#ffffff")])
        estilo.configure("Ghost.TButton", background=COLOR_FONDO_ALT, foreground=COLOR_ACENTO,
                         bordercolor=COLOR_BORDE, lightcolor=COLOR_BORDE,
                         darkcolor=COLOR_BORDE, padding=(12, 8),
                         font=(FUENTE, 9, "bold"), relief="flat")
        estilo.map("Ghost.TButton",
                   background=[("active", "#0f2233")],
                   foreground=[("active", COLOR_ACENTO_HOVER)])

        estilo.configure("Treeview", background=COLOR_PANEL, fieldbackground=COLOR_PANEL,
                         foreground=COLOR_TEXTO, rowheight=26,
                         bordercolor=COLOR_BORDE, lightcolor=COLOR_BORDE,
                         darkcolor=COLOR_BORDE)
        estilo.map("Treeview",
                   background=[("selected", "#0e4a63")],
                   foreground=[("selected", "#ffffff")])
        estilo.configure("Treeview.Heading", background="#0e2a40", foreground=COLOR_ACENTO,
                         font=(FUENTE, 9, "bold"), relief="flat", padding=(6, 6))
        estilo.map("Treeview.Heading", background=[("active", "#154866")])

        # Pestañas de categorías de servicios
        estilo.configure("TNotebook", background=COLOR_PANEL, borderwidth=0)
        estilo.configure("TNotebook.Tab", background=COLOR_PANEL_ALT,
                         foreground=COLOR_TEXTO_TENUE, padding=(10, 6),
                         font=(FUENTE, 9, "bold"))
        estilo.map("TNotebook.Tab",
                   background=[("selected", "#0e2a40")],
                   foreground=[("selected", COLOR_ACENTO)])

        estilo.configure("Horizontal.TProgressbar", background=COLOR_ACENTO,
                         troughcolor="#08111d", bordercolor="#08111d",
                         lightcolor=COLOR_ACENTO, darkcolor=COLOR_ACENTO,
                         thickness=12)
        estilo.configure("TCheckbutton", background=COLOR_PANEL, foreground=COLOR_TEXTO_TENUE,
                         focuscolor=COLOR_ACENTO, font=(FUENTE, 9))
        estilo.map("TCheckbutton",
                   background=[("active", COLOR_PANEL)],
                   foreground=[("active", COLOR_TEXTO)])

    def _crear_widgets(self):
        raiz = tk.Frame(self.root, bg=COLOR_FONDO)
        raiz.pack(fill="both", expand=True)

        # Cabecera
        cabecera = tk.Frame(raiz, bg=COLOR_FONDO_ALT, height=78)
        cabecera.pack(fill="x")
        cabecera.pack_propagate(False)

        marca = tk.Frame(cabecera, bg=COLOR_FONDO_ALT)
        marca.pack(side="left", padx=18, pady=10)
        fila = tk.Frame(marca, bg=COLOR_FONDO_ALT)
        fila.pack(anchor="w")
        self._lbl_marca1 = tk.Label(fila, bg=COLOR_FONDO_ALT, fg=COLOR_TEXTO,
                                    font=(FUENTE, 17, "bold"))
        self._lbl_marca1.pack(side="left")
        self._lbl_marca2 = tk.Label(fila, bg=COLOR_FONDO_ALT, fg=COLOR_ACENTO_2,
                                    font=(FUENTE, 17, "bold"))
        self._lbl_marca2.pack(side="left", padx=(6, 0))
        self._registrar_texto(
            tk.Label(marca, bg=COLOR_FONDO_ALT, fg=COLOR_TEXTO_TENUE,
                     font=(FUENTE_MONO, 8)),
            "marca_edicion").pack(anchor="w")

        self.chip = tk.Label(cabecera, bg="#04222e",
                             fg=COLOR_ACENTO, font=(FUENTE_MONO, 8, "bold"),
                             padx=12, pady=6, highlightbackground=COLOR_ACENTO,
                             highlightthickness=1)
        self.chip.pack(side="right", padx=18)
        self._chip_por_color(COLOR_TEXTO, "chip_listo")

        # Selector de idioma (a la derecha del todo; el chip queda a su izquierda)
        selector = tk.Frame(cabecera, bg=COLOR_FONDO_ALT)
        selector.pack(side="right", padx=(0, 6), pady=23)
        self._lbl_idioma = {}
        tk.Label(selector, text="|", bg=COLOR_FONDO_ALT, fg=COLOR_BORDE,
                 font=(FUENTE_MONO, 8, "bold")).pack(side="right", padx=4)
        for codigo in reversed(i18n.IDIOMAS):
            lbl = tk.Label(selector, text=codigo.upper(), bg=COLOR_FONDO_ALT,
                           fg=COLOR_TEXTO_TENUE, font=(FUENTE_MONO, 8, "bold"),
                           padx=5, cursor="hand2")
            lbl.pack(side="right")
            lbl.bind("<Button-1>", lambda _e, c=codigo: self._aplicar_idioma(c))
            self._lbl_idioma[codigo] = lbl

        # SOLO la portada va centrada, sin mover el resto
        portada = portada_cabecera(cabecera, 62)
        if portada is not None:
            etiqueta_portada = tk.Label(cabecera, image=portada, bg=COLOR_FONDO_ALT)
            etiqueta_portada.image = portada  # evita el recolector de basura
            etiqueta_portada.place(relx=0.5, rely=0.5, anchor="center")

        # Linea neon degradada bajo la cabecera
        linea_degradado(raiz).pack(fill="x")

        cuerpo = tk.Canvas(raiz, bg=COLOR_FONDO, highlightthickness=0, bd=0)
        cuerpo.pack(fill="both", expand=True)
        self.lienzo = cuerpo

        # Acciones
        acciones = tk.Frame(cuerpo, bg=COLOR_PANEL, highlightbackground=COLOR_ACENTO,
                            highlightthickness=1, padx=12, pady=10)

        fila_botones = tk.Frame(acciones, bg=COLOR_PANEL)
        fila_botones.pack(fill="x")
        self.boton_escanear = boton_con_halo(fila_botones, i18n.t("btn_escanear"),
                                             "Accent.TButton", self._accion_escanear)
        self.boton_escanear.pack(side="left")
        self.boton_procesos = boton_con_halo(
            fila_botones, i18n.t("btn_procesos"), "Ghost.TButton",
            self._accion_procesos, "#7aa8ff")
        self.boton_procesos.pack(side="right")
        self.boton_servicios = boton_con_halo(
            fila_botones, i18n.t("btn_servicios"), "Blue.TButton",
            self._accion_servicios, "#7aa8ff")
        self.boton_servicios.pack(side="right", padx=(0, 8))
        self.boton_manual = boton_con_halo(
            fila_botones, i18n.t("btn_poner_manual"), "Ghost.TButton",
            self._accion_servicios_manual, COLOR_ACENTO)
        self.boton_manual.pack(side="right", padx=(0, 8))
        for halo, clave in ((self.boton_escanear, "btn_escanear"),
                            (self.boton_procesos, "btn_procesos"),
                            (self.boton_servicios, "btn_servicios"),
                            (self.boton_manual, "btn_poner_manual")):
            self._registrar_texto(halo.boton, clave)

        fila_filtros = tk.Frame(acciones, bg=COLOR_PANEL)
        fila_filtros.pack(fill="x", pady=(8, 0))
        self.var_inactivos = tk.BooleanVar(value=False)
        self.var_solo_ejecucion = tk.BooleanVar(value=True)
        self.chk_inactivos = tk.Checkbutton(
            fila_filtros, variable=self.var_inactivos, command=self._redibujar_tablas,
            bg=COLOR_PANEL, fg=COLOR_TEXTO_TENUE, selectcolor=COLOR_FONDO,
            activebackground=COLOR_PANEL, activeforeground=COLOR_TEXTO,
            highlightthickness=0, bd=0, anchor="w", font=(FUENTE, 9))
        self.chk_inactivos.pack(side="left")
        self._textos_registrados.append((self.chk_inactivos, "chk_inactivos"))
        self.chk_solo_ejecucion = tk.Checkbutton(
            fila_filtros, variable=self.var_solo_ejecucion, command=self._redibujar_tablas,
            bg=COLOR_PANEL, fg=COLOR_TEXTO_TENUE, selectcolor=COLOR_FONDO,
            activebackground=COLOR_PANEL, activeforeground=COLOR_TEXTO,
            highlightthickness=0, bd=0, anchor="w", font=(FUENTE, 9))
        self.chk_solo_ejecucion.pack(side="left", padx=(16, 0))
        self._textos_registrados.append((self.chk_solo_ejecucion, "chk_ejecucion"))

        # Listas lado a lado (tarjetas directas sobre el lienzo con rejilla)
        borde_izq, izq = self._panel_lista(cuerpo, "panel_proc", "panel_proc_sub")
        # Barra de búsqueda de procesos (filtra en vivo, sin bloquear la ventana).
        self.var_busqueda_proc = tk.StringVar()
        self.entrada_busqueda_proc = self._entrada_con_placeholder(
            izq, self.var_busqueda_proc, "proc", "buscar_proceso")
        self.arbol_proc = ttk.Treeview(
            izq, columns=("tipo", "nombre", "pid", "cpu", "ram", "riesgo"),
            show="headings", selectmode="extended")
        for col_id, clave_i18n, ancho, ancla in (
                ("tipo", "col_tipo", 90, "center"), ("nombre", "col_nombre", 150, "w"),
                ("pid", "col_pid", 50, "center"), ("cpu", "col_cpu", 55, "center"),
                ("ram", "col_ram", 65, "center"), ("riesgo", "col_riesgo", 55, "center")):
            self.arbol_proc.heading(col_id, text=i18n.t(clave_i18n))
            self.arbol_proc.column(col_id, width=ancho, anchor=ancla)
        self.arbol_proc.tag_configure("alto", foreground=COLOR_ERROR)
        self.arbol_proc.tag_configure("inactivo", foreground=COLOR_TEXTO_TENUE)
        self.arbol_proc.pack(fill="both", expand=True)
        # Descripción del proceso seleccionado (para qué se utiliza / su ruta).
        self.lbl_desc_proc = tk.Label(izq, bg=COLOR_PANEL, fg=COLOR_TEXTO_TENUE,
                                      font=(FUENTE, 8), wraplength=380,
                                      justify="left", anchor="w")
        self.lbl_desc_proc.pack(fill="x", pady=(6, 0))
        self._textos_registrados.append((self.lbl_desc_proc, "lbl_descripcion"))
        self.arbol_proc.bind("<<TreeviewSelect>>",
                             lambda _e: self._mostrar_descripcion("proc"))

        borde_der, der = self._panel_lista(cuerpo, "panel_serv", "panel_serv_sub")
        # Barra de búsqueda de servicios (filtra en vivo, sin bloquear).
        self.var_busqueda_serv = tk.StringVar()
        self.entrada_busqueda_serv = self._entrada_con_placeholder(
            der, self.var_busqueda_serv, "serv", "buscar_servicio")
        self.notebook = ttk.Notebook(der)
        self.arboles_servicios: dict[str, ttk.Treeview] = {}
        for cat in CATEGORIAS:
            tab = tk.Frame(self.notebook, bg=COLOR_PANEL)
            self.notebook.add(tab, text=i18n.t(f"cat_{cat}"))
            arbol = ttk.Treeview(
                tab, columns=("servicio", "estado", "inicio", "riesgo"),
                show="headings", selectmode="extended")
            for col_id, clave_i18n, ancho, ancla in (
                    ("servicio", "col_servicio", 150, "w"), ("estado", "col_estado", 80, "center"),
                    ("inicio", "col_inicio", 80, "center"), ("riesgo", "col_riesgo", 55, "center")):
                arbol.heading(col_id, text=i18n.t(clave_i18n))
                arbol.column(col_id, width=ancho, anchor=ancla)
            arbol.tag_configure("medio", foreground=COLOR_AVISO)
            arbol.pack(fill="both", expand=True)
            self.arboles_servicios[cat] = arbol
        # Descripción del servicio seleccionado (la reporta Windows, localizada).
        self.lbl_desc_serv = tk.Label(der, bg=COLOR_PANEL, fg=COLOR_TEXTO_TENUE,
                                      font=(FUENTE, 8), wraplength=430,
                                      justify="left", anchor="w")
        self.lbl_desc_serv.pack(fill="x", pady=(6, 0))
        self._textos_registrados.append((self.lbl_desc_serv, "lbl_descripcion"))
        for arbol in self.arboles_servicios.values():
            arbol.bind("<<TreeviewSelect>>",
                       lambda _e: self._mostrar_descripcion("serv"))
        self.notebook.pack(fill="both", expand=True)

        # Panel inferior: progreso, estado y log
        inferior = tk.Frame(cuerpo, bg=COLOR_PANEL, highlightbackground=COLOR_BORDE,
                            highlightthickness=1, padx=12, pady=10)

        fila_progreso = tk.Frame(inferior, bg=COLOR_PANEL)
        fila_progreso.pack(fill="x")
        self.barra = ttk.Progressbar(fila_progreso, mode="determinate")
        self.barra.pack(fill="x")

        self.etiqueta_estado = ttk.Label(inferior, style="Card.TLabel")
        self.etiqueta_estado.pack(anchor="w", pady=(6, 0))
        self._etiqueta_estado_actual()

        self.log = tk.Text(inferior, height=6, bg=COLOR_PANEL, fg=COLOR_TEXTO,
                           bd=0, highlightthickness=0, font=(FUENTE_MONO, 8),
                           state="disabled", wrap="word")
        for tag, color in (("ok", COLOR_OK), ("error", COLOR_ERROR),
                           ("aviso", COLOR_AVISO), ("info", COLOR_TEXTO_TENUE)):
            self.log.tag_configure(tag, foreground=color)
        self.log.pack(fill="both", expand=True, pady=(8, 0))

        # Tarjetas como ventanas del lienzo (dejan ver la rejilla de fondo)
        self.acciones = acciones
        self.inferior = inferior
        self._win_acciones = cuerpo.create_window(14, 12, window=acciones, anchor="nw")
        self._win_izq = cuerpo.create_window(14, 150, window=borde_izq, anchor="nw")
        self._win_der = cuerpo.create_window(530, 150, window=borde_der, anchor="nw")
        self._win_inferior = cuerpo.create_window(14, 560, window=inferior, anchor="nw")
        cuerpo.bind("<Configure>", self._layout_cuerpo)

    def _layout_cuerpo(self, event):
        ancho, alto = event.width, event.height
        self._dibujar_rejilla(ancho, alto)
        alto_acciones = self.acciones.winfo_reqheight()
        alto_inferior = self.inferior.winfo_reqheight()
        margen, separacion = 14, 12
        ancho_util = max(200, ancho - margen * 2)
        y_listas = margen + alto_acciones + separacion
        alto_listas = max(120, alto - margen - alto_inferior - separacion - y_listas)
        ancho_izq = max(120, (ancho_util - 16) * 46 // 100)
        ancho_der = max(120, ancho_util - ancho_izq - 16)
        self.lienzo.itemconfigure(self._win_acciones, width=ancho_util, height=alto_acciones)
        self.lienzo.coords(self._win_acciones, margen, margen)
        self.lienzo.itemconfigure(self._win_izq, width=ancho_izq, height=alto_listas)
        self.lienzo.coords(self._win_izq, margen, y_listas)
        self.lienzo.itemconfigure(self._win_der, width=ancho_der, height=alto_listas)
        self.lienzo.coords(self._win_der, margen + ancho_izq + 16, y_listas)
        self.lienzo.itemconfigure(self._win_inferior, width=ancho_util, height=alto_inferior)
        self.lienzo.coords(self._win_inferior, margen, alto - margen - alto_inferior)

    def _dibujar_rejilla(self, ancho: int, alto: int):
        self.lienzo.delete("rejilla")
        paso = 28
        for x in range(0, ancho, paso):
            color = "#0e2a40" if x % (paso * 4) == 0 else "#0a1a2a"
            self.lienzo.create_line(x, 0, x, alto, fill=color, tags="rejilla")
        for y in range(0, alto, paso):
            color = "#0e2a40" if y % (paso * 4) == 0 else "#0a1a2a"
            self.lienzo.create_line(0, y, ancho, y, fill=color, tags="rejilla")
        self.lienzo.tag_lower("rejilla")

    def _panel_lista(self, padre, clave_titulo: str, clave_subtitulo: str):
        """Tarjeta con borde neon, cabecera y cuerpo para una lista."""
        borde = tk.Frame(padre, bg=COLOR_PANEL, highlightbackground=COLOR_BORDE,
                         highlightthickness=1)
        cab = tk.Frame(borde, bg=COLOR_PANEL)
        cab.pack(fill="x", padx=12, pady=(10, 0))
        tk.Frame(cab, bg=COLOR_ACENTO, width=3, height=16).pack(side="left", padx=(0, 8))
        textos = tk.Frame(cab, bg=COLOR_PANEL)
        textos.pack(side="left")
        lbl_titulo = tk.Label(textos, bg=COLOR_PANEL, fg=COLOR_TEXTO,
                              font=(FUENTE, 9, "bold"))
        lbl_titulo.pack(anchor="w")
        lbl_sub = tk.Label(textos, bg=COLOR_PANEL, fg=COLOR_TEXTO_TENUE,
                           font=(FUENTE_MONO, 7))
        lbl_sub.pack(anchor="w")
        self._textos_registrados.append((lbl_titulo, clave_titulo))
        self._textos_registrados.append((lbl_sub, clave_subtitulo))
        lbl_titulo.configure(text=i18n.t(clave_titulo))
        lbl_sub.configure(text=i18n.t(clave_subtitulo))
        cuerpo = tk.Frame(borde, bg=COLOR_PANEL)
        cuerpo.pack(fill="both", expand=True, padx=10, pady=(8, 10))
        return borde, cuerpo

    # ------------------------------------------------------- búsqueda en vivo
    def _entrada_con_placeholder(self, padre, variable, tipo: str, clave: str):
        """Entry ciberdark con texto guía; filtra en vivo con un pequeño retardo.

        La búsqueda nunca bloquea la ventana: cada pulsación solo reprograma un
        redibujado (200 ms) y el escaneo pesado ya corre en su propio hilo.
        """
        entrada = ttk.Entry(padre, textvariable=variable)
        entrada.pack(fill="x", pady=(0, 6))
        self._placeholders.append((entrada, clave, variable))
        self._busquedas[tipo] = (variable, clave)
        self._colocar_placeholder(entrada, clave, variable)
        entrada.bind("<FocusIn>",
                     lambda _e: self._quitar_placeholder(entrada, clave, variable))
        entrada.bind("<FocusOut>",
                     lambda _e: self._colocar_placeholder(entrada, clave, variable))
        variable.trace_add("write", self._programar_redibujo)
        return entrada

    def _colocar_placeholder(self, entrada, clave: str, variable):
        if not variable.get() or self._es_placeholder(clave, variable.get()):
            variable.set(i18n.t(clave))
            entrada.configure(foreground=COLOR_TEXTO_TENUE)

    def _quitar_placeholder(self, entrada, clave: str, variable):
        if self._es_placeholder(clave, variable.get()):
            variable.set("")
            entrada.configure(foreground=COLOR_TEXTO)

    @staticmethod
    def _es_placeholder(clave: str, texto: str) -> bool:
        """True si `texto` es el texto guía de esa caja en CUALQUIER idioma.

        Necesario al cambiar de idioma: la caja todavía muestra el texto guía
        anterior y, sin esto, se confundiría con una búsqueda real (y las
        tablas aparecerían vacías).
        """
        return any(tabla.get(clave) == texto for tabla in textos.TEXTOS.values())

    def _texto_busqueda(self, tipo: str) -> str:
        """Texto de filtro real ("" si la caja muestra el texto guía)."""
        datos = self._busquedas.get(tipo)
        if not datos:
            return ""
        variable, clave = datos
        texto = variable.get()
        if self._es_placeholder(clave, texto):
            return ""
        return texto.strip().lower()

    def _programar_redibujo(self, *_args):
        """Debounce: reagrupa el redibujado mientras el usuario escribe."""
        if self._redibujo_pendiente is not None:
            try:
                self.root.after_cancel(self._redibujo_pendiente)
            except Exception:
                pass
        self._redibujo_pendiente = self.root.after(200, self._redibujo_ahora)

    def _redibujo_ahora(self):
        self._redibujo_pendiente = None
        self._redibujar_tablas()

    # ------------------------------------------------------------- idioma
    @property
    def idioma_actual(self) -> str:
        """Idioma vigente de la interfaz."""
        return i18n.idioma()

    def _registrar_texto(self, widget, clave: str):
        """Guarda el widget y su clave para poder re-traducirlo al cambiar idioma."""
        widget.configure(text=i18n.t(clave))
        self._textos_registrados.append((widget, clave))
        return widget

    def _aplicar_idioma(self, codigo: str, inicial: bool = False):
        """Cambia el idioma y reescribe TODO el texto visible (estático y dinámico)."""
        if not inicial:
            # guardar=True: el usuario eligió el idioma, se recuerda entre sesiones
            i18n.fijar_idioma(codigo, guardar=True)
        self._lbl_marca1.configure(text=i18n.t("marca_titulo_1"))
        self._lbl_marca2.configure(text=i18n.t("marca_titulo_2"))
        for c, lbl in self._lbl_idioma.items():
            lbl.configure(fg=COLOR_ACENTO if c == self.idioma_actual else COLOR_TEXTO_TENUE)
        for widget, clave in self._textos_registrados:
            widget.configure(text=i18n.t(clave))
        for col_id, clave_i18n, ancho, ancla in (
                ("tipo", "col_tipo", 90, "center"), ("nombre", "col_nombre", 150, "w"),
                ("pid", "col_pid", 50, "center"), ("cpu", "col_cpu", 55, "center"),
                ("ram", "col_ram", 65, "center"), ("riesgo", "col_riesgo", 55, "center")):
            self.arbol_proc.heading(col_id, text=i18n.t(clave_i18n))
        for cat, arbol in self.arboles_servicios.items():
            for col_id, clave_i18n, ancho, ancla in (
                    ("servicio", "col_servicio", 150, "w"), ("estado", "col_estado", 80, "center"),
                    ("inicio", "col_inicio", 80, "center"), ("riesgo", "col_riesgo", 55, "center")):
                arbol.heading(col_id, text=i18n.t(clave_i18n))
        for widget, clave in ((self.boton_escanear.boton, "btn_escanear"),
                              (self.boton_procesos.boton, "btn_procesos"),
                              (self.boton_servicios.boton, "btn_servicios"),
                              (self.boton_manual.boton, "btn_poner_manual")):
            widget.configure(text=i18n.t(clave))
        self.root.title(i18n.t("app_titulo", version=VERSION))
        self._chip_por_color(self._chip_color, self._chip_clave)
        self._etiqueta_estado_actual()
        # Los textos guía se actualizan ANTES de redibujar: si se hiciera al
        # revés, el texto guía del idioma anterior se tomaría como búsqueda.
        for entrada, clave, variable in self._placeholders:
            if not variable.get() or self._es_placeholder(clave, variable.get()):
                variable.set("")
                self._colocar_placeholder(entrada, clave, variable)
        self._redibujar_tablas()
        self._mostrar_descripcion("proc")
        self._mostrar_descripcion("serv")

    def _traducir_estado(self, estado: str) -> str:
        texto = i18n.t(f"estado_{estado}")
        return texto if texto != f"estado_{estado}" else estado

    def _traducir_inicio(self, inicio: str) -> str:
        if not inicio:
            return "-"
        texto = i18n.t(f"inicio_{inicio}")
        return texto if texto != f"inicio_{inicio}" else inicio

    def _traducir_riesgo(self, riesgo: str) -> str:
        texto = i18n.t(f"riesgo_{riesgo}")
        return texto if texto != f"riesgo_{riesgo}" else riesgo

    def _redibujar_tablas(self):
        """Vuelve a poblar las tablas desde los datos en memoria, traducidos."""
        # Procesos: alto consumo siempre; inactivos solo si el filtro lo pide.
        filtro_proc = self._texto_busqueda("proc")
        sel_proc = self.arbol_proc.selection()
        self.arbol_proc.delete(*self.arbol_proc.get_children())
        self._mapa_procesos.clear()
        indice = 0
        visibles_proc = list(self._altos)
        if self.var_inactivos.get():
            visibles_proc += list(self._inactivos)
        for p in visibles_proc:
            if filtro_proc and filtro_proc not in p.nombre.lower() \
                    and str(p.pid) != filtro_proc:
                continue
            tipo = "alto" if p in self._altos else "inactivo"
            iid = f"proc_{indice}"
            self._mapa_procesos[iid] = p
            self.arbol_proc.insert("", "end", iid=iid,
                                   values=(i18n.t(f"tipo_{tipo}"), p.nombre, p.pid,
                                           f"{p.cpu_percent:g}", p.ram_mb,
                                           self._traducir_riesgo(nivel(p))),
                                   tags=(tipo,))
            indice += 1
        for iid in sel_proc:
            if self.arbol_proc.exists(iid):
                self.arbol_proc.selection_add(iid)

        # Servicios: por categoría, con filtro "solo en ejecución" y búsqueda.
        solo_ejecucion = self.var_solo_ejecucion.get()
        filtro_serv = self._texto_busqueda("serv")
        self._mapa_servicios.clear()
        visibles = [s for s in self._servicios
                    if (not solo_ejecucion or s.estado == "RUNNING")
                    and (not filtro_serv or filtro_serv in s.nombre.lower())]
        for cat in CATEGORIAS:
            arbol = self.arboles_servicios[cat]
            arbol.delete(*arbol.get_children())
        for i, s in enumerate(visibles):
            cat = categoria_de(s.nombre, s.ruta)
            arbol = self.arboles_servicios[cat]
            iid = f"svc_{i}"
            self._mapa_servicios[iid] = s
            arbol.insert("", "end", iid=iid,
                         values=(s.nombre, self._traducir_estado(s.estado),
                                 self._traducir_inicio(s.inicio),
                                 self._traducir_riesgo(nivel(s))),
                         tags=(nivel(s),))
        # Contador en cada pestaña
        for cat in CATEGORIAS:
            arbol = self.arboles_servicios[cat]
            n = len(arbol.get_children())
            self.notebook.tab(list(self.arboles_servicios).index(cat),
                              text=f"{i18n.t(f'cat_{cat}')} ({n})")

    # ------------------------------------------------------------- utilidad
    def _recortar(self, texto: str, n: int = 110) -> str:
        """Una línea, recortada a n caracteres (para diálogos de confirmación)."""
        texto = " ".join((texto or "").split())
        return texto if len(texto) <= n else texto[:n - 1].rstrip() + "…"

    def _mostrar_descripcion(self, tipo: str):
        """Muestra para qué sirve el elemento seleccionado (o una pista)."""
        if tipo == "proc":
            sel = self.arbol_proc.selection()
            hallazgo = self._mapa_procesos.get(sel[0]) if sel else None
            if hallazgo is None:
                self.lbl_desc_proc.configure(text=i18n.t("lbl_descripcion"))
                return
            detalle = hallazgo.ruta or i18n.t("sin_ruta")
            self.lbl_desc_proc.configure(
                text=f"{hallazgo.nombre} — {detalle}")
        else:
            sel = None
            for arbol in self.arboles_servicios.values():
                if arbol.selection():
                    sel = arbol.selection()[0]
                    break
            hallazgo = self._mapa_servicios.get(sel) if sel else None
            if hallazgo is None:
                self.lbl_desc_serv.configure(text=i18n.t("lbl_descripcion"))
                return
            detalle = self._descripcion(hallazgo) or i18n.t("sin_descripcion")
            self.lbl_desc_serv.configure(
                text=f"{hallazgo.nombre} — {detalle}")

    @staticmethod
    def _descripcion(hallazgo: ServicioHallazgo) -> str:
        """Descripción del servicio bajo demanda (y se guarda en el hallazgo).

        El escaneo ya no pide descripciones: cada `sc qdescription` cuesta
        ~35 ms y con ~100 hallazgos sumaba varios segundos de espera.
        """
        if not hallazgo.descripcion:
            try:
                hallazgo.descripcion = descripcion_de_servicio(hallazgo.nombre)
            except Exception:  # noqa: BLE001 - sin descripción no se rompe nada
                hallazgo.descripcion = ""
        return hallazgo.descripcion

    def _log(self, texto: str, color: str = COLOR_TEXTO):
        self._estado_texto = texto
        self._estado_color = color
        self._estado_clave = None
        self._estado_kwargs = {}
        self.etiqueta_estado.configure(text=texto, foreground=color)
        self._chip_por_color(color, None)

    def _log_t(self, clave: str, color: str = COLOR_TEXTO, **kwargs):
        """Log traducible: guarda la clave para re-renderizar al cambiar idioma."""
        self._log(i18n.t(clave, **kwargs), color)
        self._estado_clave = clave
        self._estado_kwargs = kwargs

    def _log_texto(self, texto: str, tag: str = "info"):
        """Añade una línea al log inferior con el color del tag."""
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _cola_estado(self, clave: str, color: str = COLOR_TEXTO, **kwargs):
        """Encola un estado traducible (lo consume el hilo principal)."""
        self._encolar(("estado_clave", (clave, color, kwargs)))

    def _encolar(self, item):
        try:
            self.cola.put_nowait(item)
        except queue.Full:
            pass  # la cola nunca debe romper la app

    def _etiqueta_estado_actual(self):
        """Reescribe la etiqueta de estado con el idioma vigente."""
        clave = getattr(self, "_estado_clave", None)
        if clave:
            texto = i18n.t(clave, **getattr(self, "_estado_kwargs", {}))
        else:
            texto = getattr(self, "_estado_texto", "")
        self.etiqueta_estado.configure(
            text=texto, foreground=getattr(self, "_estado_color", COLOR_TEXTO))

    _CHIP_POR_COLOR = {COLOR_ERROR: "chip_error", COLOR_OK: "chip_activo"}

    def _chip_por_color(self, color, clave=None):
        """Pinta el chip según su estado real (la clave se guarda para traducir)."""
        if clave is None:
            clave = self._CHIP_POR_COLOR.get(color, "chip_trabajando")
        self._chip_clave = clave
        self._chip_color = color
        fg = color if color in (COLOR_OK, COLOR_ERROR) else COLOR_ACENTO
        self.chip.configure(text=i18n.t(clave), fg=fg, highlightbackground=fg)

    def _ejecutar_hilo(self, funcion, *args):
        threading.Thread(target=funcion, args=args, daemon=True).start()

    # ------------------------------------------------------------- escaneo
    def _accion_escanear(self):
        if self._escaneando:
            return
        self._escaneando = True
        self.boton_escanear.boton.state(["disabled"])
        self._cola_estado("estado_escaneando", COLOR_TEXTO)
        self._encolar(("progreso", "inicio"))
        self._ejecutar_hilo(self._trabajo_escaneo)

    def _trabajo_escaneo(self):
        try:
            # El escaneo de servicios (muchos sc.exe) corre a la vez que la
            # medición de CPU: son independientes y así se solapa la espera.
            with ThreadPoolExecutor(max_workers=1) as ejecutor:
                futuro_servicios = ejecutor.submit(servicios_sin_dependencias)
                altos, inactivos = clasificar_procesos(
                    umbral_cpu=UMBRAL_CPU_ALTO, umbral_ram_mb=UMBRAL_RAM_ALTO_MB)
                servicios = futuro_servicios.result()
        except Exception as e:  # noqa: BLE001 - el hilo no debe morir en silencio
            self._encolar(("escaneo_error", str(e)))
            return
        self._encolar(("escaneo", (altos, inactivos, servicios)))

    def _mostrar_escaneo(self, altos, inactivos, servicios):
        # Orden útil para el público: primero lo que más consume.
        self._altos = sorted(altos, key=lambda p: (p.ram_mb, p.cpu_percent),
                             reverse=True)
        self._inactivos = sorted(inactivos, key=lambda p: p.ram_mb, reverse=True)
        self._servicios = list(servicios)
        self._redibujar_tablas()
        self.barra.stop()
        self.barra.configure(mode="determinate", value=100)
        self.boton_escanear.boton.state(["!disabled"])
        self._escaneando = False
        if not altos and not inactivos and not servicios:
            self._log_t("estado_sin_hallazgos", COLOR_OK)
            return
        self._log_t("estado_escaneo_ok", COLOR_OK,
                    procesos=len(altos) + len(inactivos), servicios=len(servicios))

    # ------------------------------------------------------------- acciones
    def _accion_procesos(self):
        seleccion = self.arbol_proc.selection()
        if not seleccion:
            self._log_t("estado_nada_seleccionado", COLOR_AVISO)
            return
        objetivos = [self._mapa_procesos[iid] for iid in seleccion
                     if iid in self._mapa_procesos]
        if not objetivos:
            self._log_t("estado_nada_seleccionado", COLOR_AVISO)
            return
        lista = "\n".join(
            f"- {p.nombre} (PID {p.pid}) [{self._traducir_riesgo(nivel(p))}]"
            f" — {self._recortar(p.ruta) if p.ruta else i18n.t('sin_ruta')}"
            for p in objetivos)
        if not messagebox.askyesno(
                i18n.t("confirm_titulo"),
                i18n.t("confirm_procesos", n=len(objetivos), lista=lista)):
            self._log_t("estado_accion_cancelada", COLOR_AVISO)
            return
        self._cola_estado("estado_escaneando", COLOR_TEXTO)
        self._encolar(("progreso", "inicio"))
        self._ejecutar_hilo(self._trabajo_procesos, objetivos)

    def _trabajo_procesos(self, objetivos):
        ok = 0
        for p in objetivos:
            try:
                resultado = actions.ejecutar(p, confirmar=lambda _h: True)
                correcto = resultado.ejecutado and not psutil_pid_exists(p.pid)
            except Exception:  # noqa: BLE001 - cada hallazgo falla por su lado
                correcto = False
            self._encolar(("log_proceso", (p.nombre, correcto)))
            ok += 1 if correcto else 0
        self._encolar(("accion_fin", (ok, len(objetivos))))

    def _accion_servicios(self):
        objetivos = []
        for arbol in self.arboles_servicios.values():
            for iid in arbol.selection():
                hallazgo = self._mapa_servicios.get(iid)
                if hallazgo is not None:
                    objetivos.append(hallazgo)
        if not objetivos:
            self._log_t("estado_nada_seleccionado", COLOR_AVISO)
            return
        lista = "\n".join(
            f"- {s.nombre} [{self._traducir_estado(s.estado)}, "
            f"{self._traducir_riesgo(nivel(s))}]"
            f" — {self._recortar(self._descripcion(s)) or i18n.t('sin_descripcion')}"
            for s in objetivos)
        if not messagebox.askyesno(
                i18n.t("confirm_titulo"),
                i18n.t("confirm_servicios", n=len(objetivos), lista=lista)):
            self._log_t("estado_accion_cancelada", COLOR_AVISO)
            return
        self._cola_estado("estado_escaneando", COLOR_TEXTO)
        self._encolar(("progreso", "inicio"))
        self._ejecutar_hilo(self._trabajo_servicios, objetivos)

    def _servicios_seleccionados(self) -> list[ServicioHallazgo]:
        """Hallazgos de servicio seleccionados en cualquier pestaña."""
        objetivos = []
        for arbol in self.arboles_servicios.values():
            for iid in arbol.selection():
                hallazgo = self._mapa_servicios.get(iid)
                if hallazgo is not None:
                    objetivos.append(hallazgo)
        return objetivos

    def _accion_servicios_manual(self):
        """Pone en Manual (DEMAND_START) los servicios seleccionados."""
        objetivos = self._servicios_seleccionados()
        if not objetivos:
            self._log_t("estado_nada_seleccionado", COLOR_AVISO)
            return
        lista = "\n".join(
            f"- {s.nombre} [{self._traducir_estado(s.estado)}, "
            f"{self._traducir_riesgo(nivel(s))}]"
            f" — {self._recortar(self._descripcion(s)) or i18n.t('sin_descripcion')}"
            for s in objetivos)
        if not messagebox.askyesno(
                i18n.t("confirm_titulo"),
                i18n.t("confirm_manual", n=len(objetivos), lista=lista)):
            self._log_t("estado_accion_cancelada", COLOR_AVISO)
            return
        self._cola_estado("estado_escaneando", COLOR_TEXTO)
        self._encolar(("progreso", "inicio"))
        self._ejecutar_hilo(self._trabajo_servicios_manual, objetivos)



    def _trabajo_servicios(self, objetivos):
        ok = 0
        for s in objetivos:
            try:
                resultado = actions.ejecutar(s, confirmar=lambda _h: True)
                correcto = resultado.ejecutado and (resultado.retcode is None
                                                    or resultado.retcode == 0)
                denegado = resultado.retcode == 5
            except Exception:  # noqa: BLE001 - cada hallazgo falla por su lado
                correcto, denegado = False, False
            if correcto:
                self._encolar(("log_servicio_ok", (s.nombre,)))
            elif denegado:
                self._encolar(("log_servicio_permiso", (s.nombre,)))
            else:
                self._encolar(("log_servicio_fail", (s.nombre, "")))
            ok += 1 if correcto else 0
        self._encolar(("accion_fin", (ok, len(objetivos))))

    def _trabajo_servicios_manual(self, objetivos):
        """Cambia a Manual cada servicio seleccionado (hilo de fondo)."""
        ok = 0
        for s in objetivos:
            try:
                resultado = actions.ejecutar_manual(s)
                correcto = resultado.ejecutado
                denegado = resultado.retcode == 5
            except Exception:  # noqa: BLE001 - cada hallazgo falla por su lado
                correcto, denegado = False, False
            if correcto:
                self._encolar(("log_servicio_manual_ok", (s.nombre,)))
            elif denegado:
                self._encolar(("log_servicio_permiso", (s.nombre,)))
            else:
                self._encolar(("log_servicio_fail", (s.nombre, "")))
            ok += 1 if correcto else 0
        self._encolar(("accion_fin", (ok, len(objetivos))))

    # ------------------------------------------------------------- cola
    def _procesar_cola(self):
        try:
            while True:
                mensaje, datos = self.cola.get_nowait()
                if mensaje == "estado_clave":
                    clave, color, kwargs = datos
                    self._log_t(clave, color, **kwargs)
                elif mensaje == "progreso":
                    if datos == "inicio":
                        self.barra.configure(mode="indeterminate", value=0)
                        self.barra.start(12)
                elif mensaje == "escaneo":
                    self._mostrar_escaneo(*datos)
                elif mensaje == "escaneo_error":
                    self.barra.stop()
                    self.barra.configure(mode="determinate", value=0)
                    self.boton_escanear.boton.state(["!disabled"])
                    self._escaneando = False
                    self._log(f"ERROR: {datos}", COLOR_ERROR)
                elif mensaje == "log_proceso":
                    nombre, correcto = datos
                    self._log_texto(
                        i18n.t("log_proceso_ok" if correcto else "log_proceso_fail",
                               nombre=nombre),
                        "ok" if correcto else "error")
                elif mensaje == "log_servicio_ok":
                    self._log_texto(i18n.t("log_servicio_ok", nombre=datos[0]), "ok")
                elif mensaje == "log_servicio_manual_ok":
                    self._log_texto(
                        i18n.t("log_servicio_manual_ok", nombre=datos[0]), "ok")
                elif mensaje == "log_servicio_permiso":
                    self._log_texto(i18n.t("log_sin_permiso", nombre=datos[0]), "error")
                elif mensaje == "log_servicio_fail":
                    self._log_texto(
                        i18n.t("log_servicio_fail", nombre=datos[0], detalle=datos[1]),
                        "error")
                elif mensaje == "accion_fin":
                    ok, total = datos
                    self.barra.stop()
                    self.barra.configure(mode="determinate", value=100)
                    self._log_t("estado_accion_ok", COLOR_OK if ok == total
                                else COLOR_AVISO, ok=ok, total=total)
        except queue.Empty:
            pass
        self._after_id = self.root.after(100, self._procesar_cola)


def psutil_pid_exists(pid: int) -> bool:
    """Wrapper aparte para poder parchearlo en pruebas sin tocar psutil."""
    import psutil
    return psutil.pid_exists(pid)


def main():
    root = tk.Tk()
    app = DetectorGUI(root)

    def salir():
        app.cerrar()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", salir)
    root.mainloop()


if __name__ == "__main__":
    main()
