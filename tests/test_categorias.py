# tests/test_categorias.py
from categorias import CATEGORIAS, categoria_de


def test_terceros_por_ruta_fuera_de_windows():
    assert categoria_de("MiApp", r"C:\Program Files\MiApp\app.exe") == "terceros"
    assert categoria_de("Steam Client Service", r"D:\Steam\bin\steam.exe") == "terceros"


def test_windows_update_por_nombre():
    assert categoria_de("wuauserv", r"C:\Windows\System32\svchost.exe") == "wupdate"
    assert categoria_de("UsoSvc", r"C:\Windows\System32\svchost.exe") == "wupdate"
    assert categoria_de("BITS", r"C:\Windows\System32\svchost.exe") == "wupdate"


def test_dispositivos_por_nombre():
    assert categoria_de("PlugPlay", r"C:\Windows\System32\svchost.exe") == "dispositivos"
    assert categoria_de("DeviceInstall", r"C:\Windows\System32\svchost.exe") == "dispositivos"


def test_red_por_nombre():
    assert categoria_de("Dhcp", r"C:\Windows\System32\svchost.exe") == "red"
    assert categoria_de("WlanSvc", r"C:\Windows\System32\svchost.exe") == "red"


def test_microsoft_genérico_por_ruta_de_windows():
    assert categoria_de("TrustedInstaller", r"C:\Windows\servicing\TrustedInstaller.exe") == "microsoft"
    assert categoria_de("cbd hsvc_60b41".replace(" ", ""), r"C:\Windows\System32\svchost.exe") == "microsoft"


def test_otros_sin_ruta_ni_coincidencia():
    assert categoria_de("Raro", "") == "otros"
    assert categoria_de("", "") == "otros"


def test_conocido_sin_ruta_se_trata_por_nombre():
    assert categoria_de("wuauserv", "") == "wupdate"


def test_orden_de_pestanas():
    assert CATEGORIAS == ("microsoft", "wupdate", "dispositivos", "red", "terceros", "otros")
