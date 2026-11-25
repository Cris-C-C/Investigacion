# %% Importaciones
import argparse
import hashlib
import itertools
import logging
import math
import os
import pickle
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from functools import wraps
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from scipy import __version__ as scipy_version
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import find_objects, label as _label_cc, maximum_filter
from scipy.optimize import linear_sum_assignment
from scipy.stats import gaussian_kde
from tqdm import tqdm

LOG = logging.getLogger("mapas_estabilidad")

# %% Configuración
BW_FIJO = 0.55
N_BOOTSTRAP_INCERTIDUMBRE = 1000
SEMILLA_BOOTSTRAP = 12345
N_PLANETAS_ESPERADO = 448
MODO_PESO_DEFECTO = "fraccion"
SIGMAS = (1, 2, 3)
_CACHE_VERSION = "v6"


@dataclass(frozen=True)
class ConfiguracionKDE:
    """Parámetros del ajuste y del remuestreo que también identifican la caché."""

    bw: float = BW_FIJO
    malla: int = 150
    replicas: int = N_BOOTSTRAP_INCERTIDUMBRE
    replicas_solar: int = 5000
    semilla: int = SEMILLA_BOOTSTRAP
    nivel: float = 90.9
    nivel_min_pico: float = 20.0
    nivel_min_pico_solar: float = 10.0
    niveles: tuple = (90.9, 80.8, 70.7, 60.6, 50.5, 40.4, 30.3, 20.2, 10.1)
    niveles_por_altura: bool = True
    ventana_dex: float = 0.4
    gap_dex: float = 0.08
    tolerancia_x_dex: float = 0.5
    tolerancia_y_dex: float = 1.0
    modo_regiones: str = "picos"
    modo_umbral: str = "pico"
    masa_hdr: float = 0.5
    covarianza_fija: bool = True
    remuestrear_sistemas: bool = True
    metodo_error: str = "basico"
    piso_celdas: float = 0.5
    recuperacion_minima: float = 0.68
    minimo_validas: int = 5
    minimo_por_cola_3sigma: int = 10

    def __post_init__(self):
        if not math.isfinite(self.bw) or self.bw <= 0 or self.malla < 3:
            raise ValueError("Se requiere ancho de banda positivo y una malla de al menos 3 puntos")
        if min(self.replicas, self.replicas_solar) < 0:
            raise ValueError("El número de réplicas debe ser no negativo")
        if self.semilla < 0 or self.metodo_error not in ("basico", "percentil", "std"):
            raise ValueError("Semilla o método de error inválido")
        if self.modo_regiones not in ("picos", "umbral") or self.modo_umbral not in ("pico", "hdr"):
            raise ValueError("Modo de regiones o de umbral inválido")
        if not (self.piso_celdas > 0 and self.tolerancia_x_dex > 0 and self.tolerancia_y_dex > 0):
            raise ValueError("El piso y las tolerancias deben ser positivos")


@dataclass(frozen=True)
class ConfiguracionSalida:
    """Estado local de cada ejecución, incluidas las opciones de lectura de caché."""

    carpeta_cache: Path | None = None
    cache: bool = True
    recalcular: bool = False
    mostrar: bool = False


_KDE = ContextVar("configuracion_kde", default=ConfiguracionKDE())
_SALIDA = ContextVar("configuracion_salida", default=ConfiguracionSalida())

LEYENDA_DEFECTO = {"fs": 9.0, "ms": 7, "ncol": 2, "y": -0.16, "fs_cajas": 8.5}
LEYENDA_POR_TIPO = {                # ajustes por tipo espectral (se suman a LEYENDA_DEFECTO)
    "F": {"fs": 9.5, "ncol": 2, "y": -0.18},
}
LEYENDA_SOLAR = {"fs": 12, "ms": 8, "ncol": 3, "y": -0.15, "fs_cajas": 10}
LEYENDA_COMPARACION_FS = 10.5      # leyenda de la figura Sistema Solar vs. G
ANCHO_PANEL_TIPO = 7.4             # ancho (pulgadas) por panel en plot_figuras_por_tipo
ANCHO_PANEL_MATRIZ = 7.2           # ídem en plot_matriz_tipo_multiplicidad
ANCHO_PANEL_FILA = 7.6             # ídem en plot_tipos_espectrales_fila

# ---- Sistema Solar -----------------------------------------------------------------
# Ya NO se mezcla con las estrellas tipo G: las figuras F, G, K, M se hacen sin él y el
# Sistema Solar tiene su propia figura unificada (etapa "solar").
SISTEMA_SOLAR = {
    "activo": True,
    "tipo_estrella": "G",          # solo se usa en la etapa "comparar" (Sistema Solar vs. G)
    "nombre_sistema": "Solar System",
    "n_planetas_total": 8,
    "marcador": "*", "color": "gold",
    # nombre: (a [UA], masa [M_tierra], A_estable, A_inestable, A_colisión_m2 [km²],
    #          zonas_estables, zonas_inestables, zonas_colisión_m2)   (colisión m1 = 0)
    "planetas": {
        "Mercury": (0.387, 0.0553, 3.01e12, 5.33e14, 2.15e12,  56, 9904, 40),
        "Venus":   (0.723, 0.815,  1.27e13, 1.85e15, 4.29e12,  68, 9909, 23),
        "Earth":   (1.000, 1.000,  2.59e13, 3.57e15, 7.92e12,  72, 9906, 22),
        "Mars":    (1.524, 0.107,  5.16e13, 8.24e15, 2.58e13,  62, 9907, 31),
        "Jupiter": (5.203, 317.8,  6.82e15, 9.00e16, 9.68e12, 704, 9295,  1),
        "Saturn":  (9.537, 95.16,  1.29e16, 3.13e17, 2.61e14, 397, 9595,  8),
        "Uranus":  (19.19, 14.54,  2.03e16, 1.30e18, 1.85e15, 154, 9832, 14),
        "Neptune": (30.07, 17.15,  5.57e16, 3.18e18, 4.53e15, 172, 9814, 14),
    },
}

JUPITER_UA, JUPITER_MASA = 5.2, 317.8
COLOR_TIERRA = "#1e90ff"
COLOR_JUPITER = "#e08a3c"

# Región más estable (líneas de región a_min / a_max): densidad relativa >= 90.9 %

# Zoom por tipo espectral en plot_figuras_por_tipo: {tipo: (margen_x, margen_y)} en dex.
# Para quitar el zoom: ZOOM_POR_TIPO = {}
ZOOM_POR_TIPO = {"F": (0.6, 0.8)}

# ISOLÍNEAS DIFUMINADAS: se desvanecen (menor opacidad y grosor) lejos del centro.
ALPHA_CENTRO, ALPHA_BORDE = 0.95, 0.15
LW_CENTRO, LW_BORDE = 1.6, 0.6

COLORES_REGIONES = ["lime", "red", "dodgerblue", "magenta"]
# (estilo a_min, estilo a_max) por región; el estilo distingue la región
LS_REGIONES = [("-", "--"),
               ("-.", ":"),
               ((0, (5, 1.5)), (0, (1, 1))),
               ((0, (3, 1, 1, 1, 1, 1)), (0, (5, 5)))]

REGIONES_FILA = {"F": 2,       # isla de ~1 M_Tierra + isla de masas neptunianas
                 "G": 2,       # región principal (90.9 %) + isla cercana a Júpiter
                 "K": 3,
                 "M": 1}       # solo la región acotada al 90.9 %
# Figuras por multiplicidad: (tipo, nº de planetas) -> nº de regiones
REGIONES_MULT = {("F", 3): 3,
                 ("K", 3): 3, ("K", 4): 3, ("K", 5): 1,
                 ("M", 3): 1, ("M", 4): 1, ("M", 5): 1, ("M", 7): 1}

DIBUJAR_ISOLINEAS = True           # isolíneas blancas difuminadas (False = sin isolíneas)

# ---- límites de masa de cada región (líneas horizontales / "cuadrados de masa") ---------------
# Para cada región se dibuja el RECTÁNGULO de la isla: las líneas verticales a_min / a_max (de altura
# completa) y las horizontales m_min / m_max entre a_min y a_max, con un relleno tenue del color de la región.
DIBUJAR_LIMITES_MASA = True
LIMITES_MASA_ANCHO_COMPLETO = False   # False: la línea cubre solo [a_min, a_max]; True: cruza todo el panel
RELLENO_CAJA_MASA = 0.08              # alpha del relleno del rectángulo de cada región (0 = sin relleno)
COLOR_KDE_SISTEMA = "#6bb7ff"
COLORES_BANDAS_REGION = ["white", "cyan", "gold", "orchid"]
COLOR_LIMITES = "lime"
COLOR_LIMITES_SUP = "red"
DIBUJAR_BANDAS_SIGMA = False
SIGMAS_DIBUJAR = (1, 2, 3)
ALPHA_BANDA_SIGMA = 0.07
LIM_SISTEMA_SOLAR_X = (-1.0, 2.0)
LIM_SISTEMA_SOLAR_Y = None
MARCA_X_SISTEMA_SOLAR = math.log10(46.0)

# %% Utilidades
@contextmanager
def _configurar(configuracion=None, salida=None):
    clave_kde = _KDE.set(configuracion or _KDE.get())
    clave_salida = _SALIDA.set(salida or _SALIDA.get())
    try:
        yield
    finally:
        _SALIDA.reset(clave_salida)
        _KDE.reset(clave_kde)


def _cerrar_figuras_al_salir(funcion):
    @wraps(funcion)
    def envuelta(*args, **kwargs):
        figuras_previas = set(plt.get_fignums())
        try:
            return funcion(*args, **kwargs)
        finally:
            for numero in set(plt.get_fignums()) - figuras_previas:
                plt.close(numero)
    return envuelta


def _mostrar_o_cerrar(fig):
    try:
        if _SALIDA.get().mostrar:
            plt.show()
    finally:
        plt.close(fig)


def _guardar_csv(datos, ruta):
    datos.to_csv(ruta, index=False, encoding="utf-8-sig")


def _datos_fisicos(df):
    """Valida coordenadas de DataFrames construidos fuera del lector."""
    v = df[["Distancia_UA", "Masa_Tierra"]].to_numpy(dtype=float)
    validas = (np.isfinite(v) & (v > 0)).all(axis=1)
    if not validas.all():
        LOG.warning("Se excluyen %d filas con coordenadas no físicas del panel", (~validas).sum())
    return df.loc[validas]


def _seleccionar_estrellas(df):
    d = df.copy()
    if "Sistema" not in d:
        d["Sistema"] = d["Planeta"].str.rsplit(" ", n=1).str[0]
    d["Tipo_Estrella"] = d["Tipo_Estrella"].str.strip().str.upper()
    return _datos_fisicos(d[d["Sistema"] != SISTEMA_SOLAR["nombre_sistema"]])


def _limites_estrellas(df, margen_y=(0.8, 0.5)):
    x, y = np.log10(df[["Distancia_UA", "Masa_Tierra"]].to_numpy(dtype=float)).T
    return ((min(x.min(), 0.0) - 0.4, max(x.max(), np.log10(JUPITER_UA)) + 0.4),
            (min(y.min(), 0.0) - margen_y[0], max(y.max(), np.log10(JUPITER_MASA)) + margen_y[1]))


def _safe_log10(x):
    """Compresión de áreas no negativas para los modos de peso area y neto."""
    return np.log1p(np.asarray(x, dtype=float)) / math.log(10)


def _calcular_pesos(df_sub: pd.DataFrame, modo=None) -> np.ndarray:
    """Calcula pesos con las tres áreas en km² y admite columnas de tablas históricas."""
    modo = modo or MODO_PESO_DEFECTO
    columnas = [nombre if nombre in df_sub else alias for nombre, alias in AREAS]
    faltantes = [nombre for (nombre, _), col in zip(AREAS, columnas) if col not in df_sub]
    if faltantes:
        raise ValueError(f"Faltan columnas de área: {', '.join(faltantes)}")
    for nombre, alias in AREAS:
        if nombre != alias and nombre in df_sub and alias in df_sub:
            if not np.array_equal(df_sub[nombre], df_sub[alias]):
                raise ValueError(f"Columnas de área contradictorias: {nombre}, {alias}")
    est, ine, col = df_sub[columnas].to_numpy(dtype=float).T
    if not (np.isfinite([est, ine, col]).all() and (np.array([est, ine, col]) >= 0).all()):
        raise ValueError("Las áreas deben ser finitas y no negativas")
    if modo == "fraccion":
        # La escala común evita desbordamiento sin modificar la fracción.
        escala = np.maximum.reduce([est, ine, col])
        est, ine, col = np.divide(
            [est, ine, col], escala, out=np.zeros((3, len(est))), where=escala > 0)
        total = est + ine + col
        return np.divide(est, total, out=np.zeros_like(est), where=total > 0)
    if modo == "area":
        return _safe_log10(est)
    if modo == "neto":
        return _safe_log10(np.maximum((est - ine) - col, 0))
    raise ValueError(f"Modo de peso desconocido: {modo!r}")


def _pesos_validos(w) -> bool:
    w = np.asarray(w, dtype=float)
    return bool(np.isfinite(w).all() and (w >= 0).all() and (w > 0).any())


class _CachePrimitiva(pickle.Unpickler):
    """Impide resolver funciones o clases al leer archivos de caché."""

    def find_class(self, modulo, nombre):
        raise pickle.UnpicklingError(f"El objeto {modulo}.{nombre} no pertenece a la caché")


def _hash_cache(*partes):
    h = hashlib.sha256()
    identificadores = (_CACHE_VERSION, asdict(_KDE.get()), REGIONES_FILA, REGIONES_MULT,
                       np.__version__, scipy_version)
    for p in (*identificadores, *partes):
        if isinstance(p, np.ndarray):
            h.update(repr((p.dtype.str, p.shape)).encode())
            h.update(np.ascontiguousarray(p).tobytes())
        else:
            h.update(repr(p).encode())
        h.update(b"\0")
    return h.hexdigest()[:32]


def _cache_obtener(etiqueta, clave, calcular):
    """Reutiliza resultados de la misma configuración mediante un reemplazo atómico.

    Advertencia: pickle.load sobre archivos no confiables puede ejecutar código.
    Este lector exige datos primitivos y la versión y clave exactas del ajuste.
    """
    cfg = _SALIDA.get()
    if not cfg.cache or cfg.carpeta_cache is None:
        return calcular()
    ruta = cfg.carpeta_cache / f"kde_panel_{clave}.pkl"
    if not cfg.recalcular and ruta.is_file():
        try:
            with ruta.open("rb") as entrada:
                version, guardada, malla, resto = _CachePrimitiva(entrada).load()
            if version != _CACHE_VERSION or guardada != clave:
                raise ValueError("versión o clave incompatible")
            if malla is not None:
                shape, datos = malla
                malla = tuple(np.frombuffer(a, dtype="<f8").copy().reshape(shape) for a in datos)
            if not isinstance(resto, dict) or not {"regiones", "boot", "diagnostico"} <= resto.keys():
                raise ValueError("estructura incompleta")
            LOG.info("KDE reutilizado de caché para %s", etiqueta)
            return {**resto, "malla": malla}
        except (OSError, EOFError, pickle.UnpicklingError, TypeError, ValueError, AttributeError) as exc:
            LOG.warning("Caché ilegible, se recalcula %s: %s", ruta, exc)
    res = calcular()
    temporal = None
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        malla = res["malla"]
        guardable = None if malla is None else (
            malla[0].shape, tuple(np.asarray(a, dtype="<f8").tobytes() for a in malla))
        resto = {k: v for k, v in res.items() if k != "malla"}
        with tempfile.NamedTemporaryFile("wb", dir=ruta.parent, delete=False) as f:
            temporal = Path(f.name)
            pickle.dump((_CACHE_VERSION, clave, guardable, resto), f, protocol=pickle.HIGHEST_PROTOCOL)
        temporal.replace(ruta)
    except OSError as exc:
        LOG.warning("No se pudo guardar la caché de %s: %s", etiqueta, exc)
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
    return res

# %% Lectura de datos
AREAS = (
    ("Area_Estable_km2", "Area_Estable_km2"),
    ("Area_Inestable_km2", "Area_Inestable"),
    ("Area_Colision_m2_km2", "Area_Colision_m2"),
)
_NUMERO = re.compile(
    r"^([+-]?(?:[0-9][0-9.,]*|[.,][0-9]+)(?:[eE][+-]?[0-9]+)?)(?:\s*(.*))?$")
_PARAMETROS = (
    ("Distancia_UA", r"semi[ -]?eje\s+mayor(?:\s+de\s+la\s+orbita)?|semimajor axis",
     {"ua": 1.0, "au": 1.0, "unidad astronomica": 1.0, "unidades astronomicas": 1.0}),
    ("Masa_Tierra", r"masa\s+(?:del\s+planeta|planetaria)|planet mass",
     {"masas terrestres": 1.0, "masa terrestre": 1.0, "m_tierra": 1.0, "m⊕": 1.0}),
    ("Masa_Estrella", r"masa\s+(?:de\s+la\s+estrella|estelar)|stellar mass",
     {"masas solares": 1.0, "masa solar": 1.0, "m_sol": 1.0, "m☉": 1.0}),
)
_ETIQUETAS_AREAS = (r"area\s+estable", r"area\s+inestable",
                   r"area\s+(?:de\s+)?colision\s+(?:con\s+)?m\s*2")
_UNIDADES_AREA = {"km2": 1.0, "km^2": 1.0, "m2": 1e-6, "m^2": 1e-6}
_ETIQUETAS_ZONAS = ("estables", "inestables", "colision m1", "colision m2")
_COLUMNAS_DATOS = [
    "Sistema", "Planeta", "Tipo_Estrella", "Distancia_UA", "Masa_Tierra", "Masa_Estrella",
    "Num_Planetas", "Zonas Estables", "Zonas Inestables", "Zonas Colisión m1",
    "Zonas Colisión m2", *(c for c, _ in AREAS), "Area_Inestable", "Area_Colision_m2"]


def _normalizar(texto):
    caracteres = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in caracteres if not unicodedata.combining(c)).replace("−", "-")


def _numero(texto):
    """Acepta coma o punto decimal y valida el agrupamiento si aparecen ambos."""
    texto = texto.strip()
    if "," in texto and "." in texto:
        sep = "," if texto.rfind(",") > texto.rfind(".") else "."
        miles = "." if sep == "," else ","
        patron = rf"[+-]?\d{{1,3}}(?:{re.escape(miles)}\d{{3}})+{re.escape(sep)}\d+(?:[eE][+-]?\d+)?"
        if not re.fullmatch(patron, texto):
            raise ValueError(f"número ambiguo: {texto}")
        texto = texto.replace(miles, "")
    valor = float(texto.replace(",", "."))
    if not math.isfinite(valor):
        raise ValueError(f"número no finito: {texto}")
    return valor


def _campos(texto):
    """Indexa rótulos y unidades de encabezado sin atravesar saltos de línea."""
    for linea in _normalizar(texto).splitlines():
        rotulo, sep, valor = linea.partition(":")
        if sep:
            m = re.fullmatch(r"\s*([^([]+?)\s*(?:[(\[]([^()\[\]]+)[)\]])?\s*", rotulo)
            if m:
                yield " ".join(m[1].split()), (m[2] or "").strip(), valor.strip()


def _leer_campo(campos, patron, nombre, unidades=None, opcional=False):
    coincidencias = [(unidad, valor) for rotulo, unidad, valor in campos
                     if re.fullmatch(patron, rotulo)]
    if not coincidencias:
        if opcional:
            return None
        raise ValueError(f"falta {nombre}")
    valores = set()
    for unidad, texto in coincidencias:
        m = _NUMERO.fullmatch(texto)
        if m is None:
            raise ValueError(f"valor inválido para {nombre}: {texto!r}")
        sufijo = (m[2] or "").strip()
        if unidades is None and (unidad or sufijo):
            raise ValueError(f"unidad inesperada para {nombre}: {unidad or sufijo!r}")
        unidad = unidad.strip("()[]")
        sufijo = sufijo.strip("()[]")
        factores = unidades or {}
        try:
            escalas = {factores[u] for u in (unidad, sufijo) if u}
        except KeyError as exc:
            raise ValueError(f"unidad no reconocida para {nombre}: {exc.args[0]!r}") from exc
        if len(escalas) > 1:
            raise ValueError(f"unidades contradictorias para {nombre}")
        valor = _numero(m[1]) * next(iter(escalas), 1.0)
        if not math.isfinite(valor):
            raise ValueError(f"valor fuera de rango para {nombre}")
        valores.add(valor)
    if len(valores) != 1:
        raise ValueError(f"valores contradictorios para {nombre}")
    return valores.pop()


def _seleccionar_carpetas():
    """Abre el selector de carpetas solo cuando se solicita el modo gráfico."""
    try:
        import tkinter as tk
        from tkinter import filedialog, simpledialog
    except ImportError as exc:
        raise ValueError("Tkinter no está disponible. Usa --carpeta") from exc
    try:
        raiz = tk.Tk()
    except tk.TclError as exc:
        raise ValueError("No hay pantalla para el selector. Usa --carpeta") from exc
    try:
        raiz.withdraw()
        raiz.attributes("-topmost", True)
        n = simpledialog.askinteger("Cantidad de carpetas", "¿Cuántos tipos vas a seleccionar?",
                                    minvalue=1, maxvalue=4, parent=raiz)
        seleccion = []
        for _ in range(n or 0):
            tipo = simpledialog.askstring("Tipo de estrella", "Tipo espectral (F, G, K, M)", parent=raiz)
            if not tipo:
                return []
            ruta = filedialog.askdirectory(title=f"Elige los datos del tipo {tipo}", parent=raiz)
            if not ruta:
                return []
            seleccion.append((tipo.strip().upper(), Path(ruta)))
        return seleccion
    finally:
        raiz.destroy()


def _carpetas_espectrales(carpeta):
    if carpeta is None:
        return _seleccionar_carpetas()
    raiz = Path(carpeta).expanduser().resolve(strict=True)
    patron = r"Resultados_Estrellas_([FGKM])"
    m = re.fullmatch(patron, raiz.name, flags=re.IGNORECASE)
    if m and raiz.is_dir():
        return [(m[1].upper(), raiz)]
    encontradas = [(m[1].upper(), p) for p in sorted(raiz.iterdir()) if p.is_dir()
                   and (m := re.fullmatch(patron, p.name, flags=re.IGNORECASE))]
    if not encontradas:
        raise ValueError(f"No hay carpetas Resultados_Estrellas_F/G/K/M en {raiz}")
    return encontradas


def _clave_nombre(nombre):
    return " ".join(_normalizar(nombre.replace("_", " ")).split())


def _inventariar_planetas(raiz):
    """Cuenta las carpetas de planeta antes de validar sus archivos científicos."""
    for sistema in sorted((p for p in raiz.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        planetas = []
        for planeta in sorted((p for p in sistema.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
            archivos = sorted((p for p in planeta.iterdir() if p.is_file()), key=lambda p: p.name.casefold())
            readmes = [a for a in archivos if re.fullmatch(r"readme(?:[ _.-].*)?", a.name, re.I)
                       and a.suffix.casefold() in ("", ".txt", ".md")]
            resumenes = [a for a in archivos if re.search(r"(?:^|[ _-])resumen\.txt$", a.name, re.I)]
            # Un nombre que corresponde a la estrella y termina en letra orbital también
            # cuenta si la carpeta quedó vacía. Se excluyen las carpetas de gráficos y caché.
            nombre_orbital = re.fullmatch(
                re.escape(_clave_nombre(sistema.name)) + r" [b-z]", _clave_nombre(planeta.name))
            huella = any(re.search(r"(?:mapa_estabilidad|_estables\.txt$)", a.name, re.I) for a in archivos)
            if readmes or resumenes or nombre_orbital or huella:
                planetas.append((planeta, readmes, resumenes))
        if planetas:
            yield sistema, planetas


def extraer_datos_personalizados(carpeta=None, esperado=None):
    """Lee el catálogo con o sin diálogos y adjunta los descartes a DataFrame.attrs."""
    seleccion = _carpetas_espectrales(carpeta)
    registros, descartes = [], []
    directorios, identidades, estrellas = set(), set(), {}
    candidatos = Counter()
    for tipo, raiz in seleccion:
        raiz = raiz.resolve(strict=True)
        if tipo not in "FGKM" or len(tipo) != 1 or raiz in directorios:
            raise ValueError(f"Carpeta repetida o tipo espectral inválido: {tipo!r}, {raiz}")
        directorios.add(raiz)
        for sistema, planetas in _inventariar_planetas(raiz):
            nombre_sistema = sistema.name.replace("_", " ")
            clave_sistema = _clave_nombre(nombre_sistema)
            if clave_sistema in estrellas:
                raise ValueError(f"Sistema duplicado: {sistema} y {estrellas[clave_sistema]}")
            estrellas[clave_sistema] = sistema
            candidatos[tipo] += len(planetas)
            # Se admite un total de catálogo explícito, validado incluso si un planeta falla.
            textos, totales = {}, set()
            for planeta, lecturas, _ in planetas:
                if len(lecturas) != 1:
                    continue
                try:
                    campos = list(_campos(lecturas[0].read_text(encoding="utf-8-sig")))
                    total = _leer_campo(campos, r"(?:numero|total)(?:\s+de)?\s+planetas",
                                       "total de planetas", opcional=True)
                    if total is not None:
                        if not total.is_integer() or total < len(planetas):
                            raise ValueError("total de catálogo menor que el inventario o no entero")
                        totales.add(int(total))
                    textos[planeta] = campos
                except (OSError, UnicodeError, ValueError) as exc:
                    textos[planeta] = exc
            if len(totales) > 1:
                raise ValueError(f"Multiplicidades contradictorias en {sistema}: {sorted(totales)}")
            multiplicidad = next(iter(totales), len(planetas))
            for planeta, lecturas, resumenes in planetas:
                nombre_planeta = planeta.name.replace("_", " ")
                identidad = (clave_sistema, _clave_nombre(nombre_planeta))
                archivo = planeta
                try:
                    if identidad in identidades:
                        raise ValueError("planeta duplicado")
                    identidades.add(identidad)
                    if len(lecturas) != 1 or len(resumenes) != 1:
                        raise ValueError(f"se requiere un README y un resumen (hay {len(lecturas)} y {len(resumenes)})")
                    archivo = lecturas[0]
                    campos = textos[planeta]
                    if isinstance(campos, Exception):
                        raise campos
                    fisica = {nom: _leer_campo(campos, patron, nom, unidades)
                              for nom, patron, unidades in _PARAMETROS}
                    if min(fisica.values()) <= 0:
                        raise ValueError("distancia y masas deben ser positivas")
                    archivo = resumenes[0]
                    campos = list(_campos(archivo.read_text(encoding="utf-8-sig")))
                    areas = {nom: _leer_campo(campos, patron, nom, _UNIDADES_AREA)
                             for (nom, _), patron in zip(AREAS, _ETIQUETAS_AREAS)}
                    if min(areas.values()) < 0 or not any(areas.values()):
                        raise ValueError("área negativa o total de áreas nulo")
                    zonas = {}
                    for etiqueta, columna in zip(_ETIQUETAS_ZONAS, _COLUMNAS_DATOS[7:11]):
                        v = _leer_campo(campos, f"total {etiqueta}", columna, opcional=True)
                        if v is not None and (v < 0 or not v.is_integer()):
                            raise ValueError(f"recuento inválido para {columna}")
                        zonas[columna] = None if v is None else int(v)
                    registros.append({"Sistema": nombre_sistema, "Planeta": nombre_planeta,
                                      "Tipo_Estrella": tipo, "Num_Planetas": multiplicidad,
                                      **fisica, **areas, **zonas,
                                      "Area_Inestable": areas["Area_Inestable_km2"],
                                      "Area_Colision_m2": areas["Area_Colision_m2_km2"]})
                except (OSError, UnicodeError, ValueError) as exc:
                    descartes.append({"Tipo_Estrella": tipo, "Sistema": nombre_sistema,
                                      "Planeta": nombre_planeta, "Archivo": str(archivo), "Motivo": str(exc)})
                    LOG.warning("Planeta descartado %s (%s): %s", nombre_planeta, archivo, exc)
    df = pd.DataFrame(registros, columns=_COLUMNAS_DATOS).sort_values(
        ["Sistema", "Planeta"], ignore_index=True)
    df.attrs["lectura"] = {
        "candidatos": dict(candidatos), "validos": df["Tipo_Estrella"].value_counts().to_dict(),
        "descartados": descartes, "esperado": esperado}
    LOG.info("Lectura: %d candidatos, %d planetas válidos, %d descartes",
             sum(candidatos.values()), len(df), len(descartes))
    if esperado is not None and esperado != len(df):
        LOG.warning("Se esperaban %d planetas válidos y se leyeron %d", esperado, len(df))
    return df, str(seleccion[0][1]) if seleccion else ""

def construir_sistema_solar() -> pd.DataFrame:
    """DataFrame con los 8 planetas del Sistema Solar en el formato de extraer_datos_personalizados()."""
    ss = SISTEMA_SOLAR
    nombre, tipo = ss["nombre_sistema"], ss["tipo_estrella"]
    registros = []
    omitidos = []
    for pl, (a, m, a_est, a_in, a_col, z_e, z_i, z_c) in ss["planetas"].items():
        if a_est is None:
            omitidos.append(pl)
            continue
        registros.append({
            "Sistema": nombre, "Planeta": f"{nombre} {pl}", "Tipo_Estrella": tipo,
            "Distancia_UA": float(a), "Masa_Tierra": float(m), "Masa_Estrella": 1.0,
            "Num_Planetas": ss["n_planetas_total"],
            "Zonas Estables": z_e, "Zonas Inestables": z_i,
            "Zonas Colisión m1": 0, "Zonas Colisión m2": z_c,
            "Area_Estable_km2": float(a_est), "Area_Inestable": float(a_in),
            "Area_Colision_m2": float(a_col),
            "Area_Inestable_km2": float(a_in), "Area_Colision_m2_km2": float(a_col),
        })
    if omitidos:
        LOG.warning("Sistema Solar: sin área estable para %s", ", ".join(omitidos))
    return pd.DataFrame(registros)

# %% KDE y regiones
def _malla(xlims, ylims, res):
    limites = np.array([xlims, ylims], dtype=float)
    if limites.shape != (2, 2) or not np.isfinite(limites).all() or not np.all(np.diff(limites) > 0):
        raise ValueError("Los límites de malla deben ser finitos y crecientes")
    puntos = complex(0, res)
    return np.mgrid[xlims[0]:xlims[1]:puntos, ylims[0]:ylims[1]:puntos]


def _normalizar_densidad(Z):
    maximo = Z.max()
    if not math.isfinite(maximo) or maximo <= 0:
        raise ValueError("Densidad sin máximo finito y positivo en la malla")
    return (Z / maximo) * 100.0


def _malla_nominal(x, y, w, X, Y, bw):
    kde = gaussian_kde(np.vstack([x, y]), weights=w, bw_method=bw)
    Z = kde(np.vstack([X.ravel(), Y.ravel()])).reshape(X.shape)
    return _normalizar_densidad(Z), np.asarray(kde.covariance)


@dataclass(frozen=True)
class _Isla:
    limites: tuple
    ypico: float
    pico: float
    umbral: float

    @property
    def centro(self):
        lo, hi, ylo, yhi = self.limites
        return ((lo + hi) / 2, (ylo + yhi) / 2)


def _cotas_eje(eje, tramo):
    """Una celda aislada conserva una anchura de una celda, recortada a los ejes."""
    lo, hi = float(eje[tramo.start]), float(eje[tramo.stop - 1])
    if lo == hi:
        semipaso = float(eje[1] - eje[0]) / 2
        return max(float(eje[0]), lo - semipaso), min(float(eje[-1]), hi + semipaso)
    return lo, hi


def _limites_isla(X, Y, tramo):
    return (*_cotas_eje(X[:, 0], tramo[0]), *_cotas_eje(Y[0, :], tramo[1]))


def _cajas_solapadas(a, b):
    return min(a[1], b[1]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[2], b[2])


def _nivel_isla(h, nivel_local):
    cfg = _KDE.get()
    if not cfg.niveles_por_altura:
        return (nivel_local / 100) * h
    return max((nv for nv in cfg.niveles if nv <= h), default=h)


def _umbral_region(Z, nivel):
    cfg = _KDE.get()
    if cfg.modo_umbral != "hdr":
        return nivel
    z = np.sort(Z.ravel())[::-1]
    i = np.searchsorted(np.cumsum(z), cfg.masa_hdr * z.sum())
    return float(z[min(i, len(z) - 1)])


def _regiones_por_umbral(Z, X, Y, umbral):
    """Proyecta el umbral en distancia y obtiene masa sobre las mismas celdas."""
    mask = Z >= umbral
    columnas = np.flatnonzero(mask.any(axis=1))
    if not columnas.size:
        return []
    xs = X[:, 0]
    # El gap cierra huecos interiores. Celdas contiguas siempre quedan juntas.
    saltos = np.diff(xs[columnas]) - (xs[1] - xs[0])
    cortes = np.flatnonzero(saltos > _KDE.get().gap_dex + 1e-12) + 1
    regiones = []
    for bloque in np.split(columnas, cortes):
        inicio, fin = bloque[0], bloque[-1] + 1
        mi, mj = np.where(mask[inicio:fin])
        k = np.argmax(Z[mi + inicio, mj])
        tramo = (slice(inicio, fin), slice(mj.min(), mj.max() + 1))
        regiones.append(_Isla(_limites_isla(X, Y, tramo), float(Y[0, mj[k]]),
                              float(Z[mi[k] + inicio, mj[k]]), float(umbral)))
    return regiones


def _regiones_por_picos(Z, X, Y, nivel_local=None, nivel_min=None, n_max=None):
    """Conserva componentes 2D separadas con contornos de densidad por pico."""
    cfg = _KDE.get()
    nivel_local = cfg.nivel if nivel_local is None else nivel_local
    nivel_min = cfg.nivel_min_pico if nivel_min is None else nivel_min
    # Ventana impar y centrada en ambos ejes. Su tamaño se expresa en dex.
    ventana = tuple(max(3, int(round(cfg.ventana_dex / abs(paso))) // 2 * 2 + 1)
                    for paso in (X[1, 0] - X[0, 0], Y[0, 1] - Y[0, 0]))
    maximos = (Z == maximum_filter(Z, size=ventana, mode="nearest")) & (Z >= nivel_min)
    centros, _ = _label_cc(maximos)
    picos = []
    for i, tramo in enumerate(find_objects(centros), 1):
        local = np.where(centros[tramo] == i, Z[tramo], -np.inf)
        k, l = np.unravel_index(local.argmax(), local.shape)
        picos.append((k + tramo[0].start, l + tramo[1].start))
    picos.sort(key=lambda p: (-Z[p], p))

    regiones, previos = [], []
    componentes = {}
    for p in picos:
        if n_max is not None and len(regiones) >= n_max:
            break
        px, py = X[p], Y[p]
        if any(lo < px < hi and ylo < py < yhi
               for lo, hi, ylo, yhi in (r.limites for r in regiones)):
            continue
        h = float(Z[p])
        t = _nivel_isla(h, nivel_local)
        if cfg.modo_umbral == "hdr":
            t = min(h, _umbral_region(Z, t))
        while True:
            if t not in componentes:
                lab, _ = _label_cc(Z >= t)
                componentes[t] = lab, find_objects(lab)
            lab, tramos = componentes[t]
            comp = lab[p]
            caja = _limites_isla(X, Y, tramos[comp - 1])
            if not any(lab[q] == comp for q in previos) and not any(
                    _cajas_solapadas(caja, r.limites) for r in regiones):
                regiones.append(_Isla(caja, float(Y[p]), h, t))
                previos.append(p)
                break
            if t >= h:
                break
            # Fuera del nivel discreto de partida, subir gradualmente separa las cajas.
            t = min(t + 0.25, h)
    return sorted(regiones, key=lambda r: (r.limites[0], r.limites[2]))


def _detectar_regiones(Z, X, Y, nivel_min, n_regiones):
    cfg = _KDE.get()
    if cfg.modo_regiones == "picos":
        return _regiones_por_picos(Z, X, Y, nivel_min=nivel_min, n_max=n_regiones)
    regiones = _regiones_por_umbral(Z, X, Y, _umbral_region(Z, cfg.nivel))
    if n_regiones is not None:
        regiones = sorted(regiones, key=lambda r: -r.pico)[:n_regiones]
    return sorted(regiones, key=lambda r: r.limites[0])

# %% Bootstrap e intervalos
def _nucleos_fijos(x, y, cov, X, Y):
    """Precalcula cada gaussiana unitaria para combinarla en todas las réplicas."""
    inversa = np.linalg.inv(cov)
    dx = X.ravel()[None, :] - x[:, None]
    dy = Y.ravel()[None, :] - y[:, None]
    d2 = (inversa[0, 0] * dx * dx + 2 * inversa[0, 1] * dx * dy + inversa[1, 1] * dy * dy)
    return np.exp(-0.5 * d2)


def _remuestreos(x, y, w, X, Y, grupos, cov, n):
    """Calcula densidades en bloques con la misma secuencia de sorteos por réplica."""
    cfg = _KDE.get()
    inv = np.arange(len(x)) if grupos is None else np.unique(grupos, return_inverse=True)[1]
    unidades = int(inv.max()) + 1
    rng = np.random.default_rng(cfg.semilla)
    fijos = _nucleos_fijos(x, y, cov, X, Y) if cfg.covarianza_fija and n else None
    bloque = 32
    for inicio in range(0, n, bloque):
        sorteos = rng.integers(0, unidades, size=(min(bloque, n - inicio), unidades))
        mult = np.array([np.bincount(sel, minlength=unidades) for sel in sorteos])[:, inv]
        pesos = mult * w
        mallas = (pesos @ fijos).reshape((-1, *X.shape)) if fijos is not None else None
        for i, (m, p) in enumerate(zip(mult, pesos)):
            activos = p > 0
            if not activos.any():
                yield None, "pesos_nulos"
                continue
            if np.ptp(x[activos]) == 0 or np.ptp(y[activos]) == 0:
                yield None, "varianza_nula"
                continue
            try:
                if mallas is None:
                    idx = np.repeat(np.arange(len(x)), m)
                    Z, _ = _malla_nominal(x[idx], y[idx], w[idx], X, Y, cfg.bw)
                else:
                    Z = _normalizar_densidad(mallas[i])
                yield Z, None
            except (np.linalg.LinAlgError, ValueError):
                yield None, "kde_no_estimable"


def _emparejar(regiones, nominales):
    """Empareja regiones uno a uno en el plano con una tolerancia elíptica."""
    if not regiones:
        return []
    cfg = _KDE.get()
    a = np.asarray([r.centro for r in nominales])
    b = np.asarray([r.centro for r in regiones])
    d = (a[:, None, :] - b[None, :, :]) / [cfg.tolerancia_x_dex, cfg.tolerancia_y_dex]
    dist = np.linalg.norm(d, axis=2)
    penalidad = len(nominales) + 1
    costos = np.column_stack([np.where(dist <= 1, dist, np.inf),
                              np.full((len(nominales), len(nominales)), penalidad)])
    filas, columnas = linear_sum_assignment(costos)
    return [(i, regiones[j]) for i, j in zip(filas, columnas) if j < len(regiones)]


def _bootstrap_regiones(x, y, weights, X, Y, regiones_nom, n_bootstrap, grupos, cov,
                        nivel_min_pico):
    """Remuestrea sistemas completos y registra réplicas inválidas y sin correspondencia."""
    out = [[] for _ in regiones_nom]
    descartes = Counter()
    for Z, motivo in tqdm(_remuestreos(x, y, weights, X, Y, grupos, cov, n_bootstrap),
                          total=n_bootstrap, desc="Bootstrap regiones", leave=False, unit="rep",
                          disable=None):
        if motivo is not None:
            descartes[motivo] += 1
            continue
        # Se evalúan también islas secundarias. Un cambio de rango no equivale a desaparición.
        islas = _detectar_regiones(Z, X, Y, nivel_min_pico, None)
        pares = _emparejar(islas, regiones_nom)
        if not pares:
            descartes["sin_region_asignada"] += 1
        for i, isla in pares:
            out[i].append(isla.limites)
    return out, dict(descartes)


def _cobertura_gauss(k):
    return math.erf(k / math.sqrt(2.0))


def _intervalo_sigma(valores_log, k, central=None, metodo=None, piso=0):
    """Devuelve el intervalo en dex, sujeto al mínimo de soporte de las colas."""
    cfg = _KDE.get()
    v = np.asarray(valores_log, dtype=float)
    v = v[np.isfinite(v)]
    if v.size < cfg.minimo_validas:
        return None
    metodo = metodo or cfg.metodo_error
    if metodo == "std":
        c = float(v.mean()) if central is None else central
        s = max(float(v.std(ddof=1)), piso)
        return c - k * s, c + k * s
    cola = (1.0 - _cobertura_gauss(k)) / 2
    if k >= 3 and v.size * cola < cfg.minimo_por_cola_3sigma:
        return None
    if metodo == "basico":
        c = float(np.median(v)) if central is None else central
        # El cuantil del error absoluto alrededor del nominal conserva el sesgo
        # observable. El semipaso cubre el redondeo del contorno en la malla.
        s = float(np.quantile(np.abs(v - c), 1 - 2 * cola)) + piso
        return c - s, c + s
    lo, med, hi = np.quantile(v, [cola, 0.5, 1.0 - cola])
    return float(min(lo, med - k * piso)), float(max(hi, med + k * piso))


def _error_simetrico(central, replicas, piso):
    """Convierte la semianchura nominal en dex a un error lineal simétrico."""
    if len(replicas) >= _KDE.get().minimo_validas:
        lo, hi = _intervalo_sigma(replicas, 1, central, piso=piso)
        sigma = max((hi - lo) / 2, piso)
    else:
        sigma = piso
    return (10 ** (central + sigma) - 10 ** (central - sigma)) / 2


def _filas_sigma(contexto, boot, ks=None, diagnostico=None):
    filas = []
    info = diagnostico or {}
    unidad = info.get("unidad")
    intentadas = info.get("replicas", 0)
    for nombre, (central, vals) in boot.items():
        n = len(vals)
        eje = "x" if nombre.startswith("a_") else "y"
        piso = info.get(f"piso_{eje}_dex", 0)
        for metodo in ("std", "percentil", "basico"):
            for k in tuple(SIGMAS if ks is None else ks):
                iv = _intervalo_sigma(vals, k, central, metodo, piso=piso)
                motivo = ("muestra_insuficiente" if n < _KDE.get().minimo_validas
                          else "cola_insuficiente")
                filas.append({**contexto, "Limite": nombre, "Valor": 10 ** central,
                              "Unidad": "UA" if eje == "x" else "M_Tierra",
                              "Metodo": metodo, "k_sigma": k,
                              "Cobertura_%": 100.0 * _cobertura_gauss(k),
                              "N_replicas": n, "N_replicas_intentadas": intentadas,
                              "Tasa_recuperacion": n / intentadas if intentadas else None,
                              "Unidad_remuestreo": unidad, "Piso_dex": piso,
                              "Inf": 10 ** iv[0] if iv else None,
                              "Sup": 10 ** iv[1] if iv else None,
                              "Estado": "estimado" if iv else motivo})
    return filas


def _guardar_tabla_sigma(filas, ruta):
    if filas:
        _guardar_csv(pd.DataFrame(filas), ruta)


def calcular_kde_panel(df_subset, xlims, ylims, modo_peso=None, n_bootstrap=None,
                       nivel_min_pico=None, etiqueta="panel", n_regiones=None,
                       *, unidad_bootstrap=None):
    """Calcula densidad relativa, contornos e incertidumbres de un panel en una malla común."""
    cfg = _KDE.get()
    modo = modo_peso or MODO_PESO_DEFECTO
    nb = cfg.replicas if n_bootstrap is None else n_bootstrap
    nmp = cfg.nivel_min_pico if nivel_min_pico is None else nivel_min_pico
    if nb < 0 or (n_regiones is not None and n_regiones < 0):
        raise ValueError("El número de réplicas y de regiones debe ser no negativo")
    df = _datos_fisicos(df_subset)
    w = _calcular_pesos(df, modo)
    x, y = np.log10(df[["Distancia_UA", "Masa_Tierra"]].to_numpy(dtype=float)).T
    bloques = df["Sistema"].astype(str).to_numpy(dtype=str) if "Sistema" in df else None
    n_sistemas = int(np.unique(bloques).size) if bloques is not None else 0
    grupos = bloques if cfg.remuestrear_sistemas and n_sistemas >= 2 and unidad_bootstrap is None else None
    unidad = unidad_bootstrap or ("sistemas" if grupos is not None else
                                  "planetas_intrasistema" if n_sistemas == 1 else "planetas")

    clave = _hash_cache(x, y, w, tuple(xlims), tuple(ylims), modo, nb, nmp, n_regiones,
                        unidad, bloques if bloques is not None else None)

    def _calc():
        d = {"estado": "estimado", "unidad": unidad, "replicas": nb, "evaluadas": 0,
             "n_planetas": len(df), "n_sistemas": n_sistemas, "descartes": {}}
        res = {"malla": None, "regiones": [], "boot": {}, "diagnostico": d}
        if len(df) < 3:
            d["estado"] = "menos_de_tres_planetas"
        elif not _pesos_validos(w) or np.count_nonzero(w) < 3:
            d["estado"] = "menos_de_tres_pesos_positivos"
        elif np.ptp(x[w > 0]) == 0 or np.ptp(y[w > 0]) == 0:
            d["estado"] = "varianza_nula"
        if d["estado"] != "estimado":
            return res
        X, Y = _malla(xlims, ylims, cfg.malla)
        px, py = (float(X[1, 0] - X[0, 0]) * cfg.piso_celdas,
                  float(Y[0, 1] - Y[0, 0]) * cfg.piso_celdas)
        d.update(piso_x_dex=px, piso_y_dex=py)
        try:
            Z, cov = _malla_nominal(x, y, w, X, Y, cfg.bw)
        except (np.linalg.LinAlgError, ValueError) as exc:
            d["estado"] = "kde_no_estimable"
            LOG.info("KDE no estimable para %s: %s", etiqueta, exc)
            return res
        res["malla"] = (X, Y, Z)
        islas = _detectar_regiones(Z, X, Y, nmp, n_regiones)
        if not islas:
            d["estado"] = "sin_regiones"
            return res
        muestras, descartes = _bootstrap_regiones(
            x, y, w, X, Y, islas, nb, grupos, cov, nmp)
        d.update(descartes=descartes, evaluadas=nb)
        for k, (isla, vals) in enumerate(zip(islas, muestras), 1):
            lo, hi, ylo, yhi = isla.limites
            columnas = list(zip(*vals)) if vals else [()] * 4
            errores = []
            for nom, central, v, piso in zip(("a_min", "a_max", "m_min", "m_max"),
                                             isla.limites, columnas, (px, px, py, py)):
                res["boot"][f"{nom}_{k}"] = (central, list(v))
                errores.append(_error_simetrico(central, v, piso))
            e1, e2, e3, e4 = errores
            tasa = len(vals) / nb if nb else None
            res["regiones"].append({
                "region": k, "lmin": lo, "lmax": hi, "a_min": 10 ** lo, "a_max": 10 ** hi,
                "m_min": 10 ** ylo, "m_max": 10 ** yhi, "m_pico": 10 ** isla.ypico,
                "pico": isla.pico, "nivel": isla.umbral,
                "s_min": e1, "s_max": e2, "sm_min": e3, "sm_max": e4,
                "dn_min": e1, "up_min": e1, "dn_max": e2, "up_max": e2,
                "dnm_min": e3, "upm_min": e3, "dnm_max": e4, "upm_max": e4,
                "a_min_en_borde": bool(lo <= xlims[0] + 1e-12),
                "a_max_en_borde": bool(hi >= xlims[1] - 1e-12),
                "m_min_en_borde": bool(ylo <= ylims[0] + 1e-12),
                "m_max_en_borde": bool(yhi >= ylims[1] - 1e-12),
                "n_validas": len(vals), "recuperacion": tasa,
                "solo_resolucion": len(vals) < cfg.minimo_validas,
                "inestable": tasa is None or tasa < cfg.recuperacion_minima
                or len(vals) < cfg.minimo_validas})
        return res

    res = _cache_obtener(etiqueta, clave, _calc)
    d = res["diagnostico"]
    nivel = logging.INFO if d["estado"] == "estimado" else logging.WARNING
    LOG.log(nivel, "%s · %s · %d planetas, %d sistemas · %d réplicas por %s · descartes %s · válidas %s",
            etiqueta, d["estado"], d["n_planetas"], d["n_sistemas"], d["evaluadas"], d["unidad"],
            d["descartes"], [r["n_validas"] for r in res["regiones"]])
    return res

# %% Figuras y exportación
def _cfg_leyenda(tipo=None, extra=None):
    """Configuración de leyenda: defecto + ajuste del tipo espectral + extra."""
    cfg = dict(LEYENDA_DEFECTO)
    cfg.update(LEYENDA_POR_TIPO.get(tipo, {}))
    cfg.update(extra or {})
    return cfg


def _n_entradas_leyenda(d, lineas_extra=None):
    """Estimación conservadora: sistemas + Tierra y Júpiter + hasta 3 regiones
    (a_min/a_max y m_min/m_max = 12 entradas)."""
    return d["Sistema"].nunique() + 2 + 12 + len(lineas_extra or [])


def _filas_leyenda(n_ent, cfg):
    ncol = cfg.get("ncol") or (2 if n_ent <= 8 else 3)
    return math.ceil(n_ent / ncol)


def _alto_leyenda(filas, cfg):
    """Altura (pulgadas) que ocupa una leyenda de `filas` filas con la fuente de cfg."""
    return 0.2 * filas * cfg["fs"] / 6.3


def _dibujar_isolineas_difuminadas(ax, X, Y, Z_pct, niveles=None,
                                   color="white"):
    """
    Dibuja una isolínea por nivel de densidad relativa (%). El nivel más alto
    (centro) es el más nítido y los niveles bajos se van desvaneciendo.
    """
    niveles = _KDE.get().niveles if niveles is None else niveles
    n = len(niveles)
    zmin, zmax = float(Z_pct.min()), float(Z_pct.max())
    for k, nv in enumerate(sorted(niveles, reverse=True)):
        if not (zmin < nv < zmax):
            continue
        t = k / (n - 1) if n > 1 else 0.0
        alpha = ALPHA_CENTRO + (ALPHA_BORDE - ALPHA_CENTRO) * t
        lw = LW_CENTRO + (LW_BORDE - LW_CENTRO) * t
        ax.contour(X, Y, Z_pct, levels=[nv], colors=[color],
                   linewidths=lw, alpha=alpha, zorder=4)


def _dibujar_bandas_sigma(ax, valores_log, central, color, zorder, alpha_unico):
    """Bandas anidadas k-sigma (las más anchas primero). Con un solo k usa alpha_unico.
    Si DIBUJAR_BANDAS_SIGMA es False no dibuja nada (el bootstrap y los CSV no cambian)."""
    if not DIBUJAR_BANDAS_SIGMA:
        return
    ks = sorted(SIGMAS_DIBUJAR, reverse=True)
    alpha = alpha_unico if len(ks) == 1 else ALPHA_BANDA_SIGMA
    for k in ks:
        iv = _intervalo_sigma(valores_log, k, central)
        if iv is not None:
            ax.axvspan(iv[0], iv[1], color=color, alpha=alpha, zorder=zorder, linewidth=0)


def _region_principal(regs, malla):
    """
    Región que contiene el máximo global de densidad (la "principal"). Si ninguna lo contiene,
    la más cercana en distancia. Las cajas sobre el panel muestran a_min / a_max de ESTA región,
    no el a_min de la primera y el a_max de la última (que mezclaba regiones distintas).
    """
    if not regs:
        return None
    if malla is None:
        return regs[0]
    X, Y, Z = malla
    i, j = np.unravel_index(np.argmax(Z), Z.shape)
    px, py = float(X[i, j]), float(Y[i, j])
    for r in regs:
        if r["lmin"] - 1e-9 <= px <= r["lmax"] + 1e-9:
            if r.get("m_min") is None or (math.log10(r["m_min"]) - 1e-9 <= py
                                          <= math.log10(r["m_max"]) + 1e-9):
                return r
    return min(regs, key=lambda r: abs((r["lmin"] + r["lmax"]) / 2.0 - px))


def dibujar_panel_kde(ax, df_subset, res, titulo, estilos_sistema, xlims, ylims,
                      cmap="magma", mostrar_ylabel=True, lineas_extra=None, leyenda=None,
                      *, modo_peso=None, dibujar_individuales=True):
    """
    Dibuja un panel compacto con los resultados `res` de calcular_kde_panel:
    mapa de densidad + isolíneas difuminadas, líneas de a_min / a_max por región (verticales, de altura
    completa), RECTÁNGULO de masas de cada región (líneas horizontales m_min / m_max entre a_min y
    a_max + relleno tenue), cajas con los valores de la región principal, puntos por sistema,
    Tierra y Júpiter y una leyenda debajo.
    `leyenda` es un dict como LEYENDA_DEFECTO (fs, ms, ncol, y, fs_cajas).
    """
    cfg = {**LEYENDA_DEFECTO, **(leyenda or {})}
    ax.set_facecolor("black")
    df_valid = _datos_fisicos(df_subset)

    # ---------------- Mapa de densidad ----------------
    if res["malla"] is not None:
        X, Y, Z_pct = res["malla"]
        ax.contourf(X, Y, Z_pct, levels=np.linspace(0.0, 100.0, 100),
                    cmap=cmap, extend="min", zorder=1)
        if DIBUJAR_ISOLINEAS:
            _dibujar_isolineas_difuminadas(ax, X, Y, Z_pct)

    # ---------------- Regiones (líneas a_min / a_max y m_min / m_max) ----------------
    regs, boot = res["regiones"], res["boot"]
    multi = len(regs) > 1
    handles_lim = []
    handles_masa = []
    for r in regs:
        k = r["region"]
        ls_min, ls_max = LS_REGIONES[(k - 1) % len(LS_REGIONES)]
        col_banda = COLORES_BANDAS_REGION[(k - 1) % len(COLORES_BANDAS_REGION)]
        col_reg = COLORES_REGIONES[(k - 1) % len(COLORES_REGIONES)]
        marca = " †" if r["inestable"] else ""
        for lval, nom, ls, color in ((r["lmin"], "a_min", ls_min, COLOR_LIMITES),
                                      (r["lmax"], "a_max", ls_max, COLOR_LIMITES_SUP)):
            _dibujar_bandas_sigma(ax, boot[f"{nom}_{k}"][1], lval, col_banda, 3, 0.15)
            ax.axvline(lval, color=color, linestyle=ls, linewidth=1.6, zorder=6)

        # límites en masa (líneas horizontales) de la propia isla: cierran el rectángulo de la región
        mm = ((math.log10(r["m_min"]), math.log10(r["m_max"]))
              if (DIBUJAR_LIMITES_MASA and r.get("m_min") is not None) else None)
        if mm is not None:
            if RELLENO_CAJA_MASA > 0 and not LIMITES_MASA_ANCHO_COMPLETO:
                ax.add_patch(Rectangle((r["lmin"], mm[0]), r["lmax"] - r["lmin"], mm[1] - mm[0],
                                       facecolor=col_reg, edgecolor="none",
                                       alpha=RELLENO_CAJA_MASA, zorder=3))
            for yv, ls in ((mm[0], ls_min), (mm[1], ls_max)):
                if LIMITES_MASA_ANCHO_COMPLETO:
                    ax.axhline(yv, color=col_reg, linestyle=ls, linewidth=1.6, zorder=6)
                else:
                    ax.hlines(yv, r["lmin"], r["lmax"], colors=col_reg, linestyles=ls,
                              linewidth=1.8, zorder=6)
            s_min = f"min,{k}" if multi else "min"
            s_max = f"max,{k}" if multi else "max"
            handles_masa += [
                Line2D([], [], color=col_reg, ls=ls_min, lw=1.6,
                       label=_txt_masa(s_min, 10 ** mm[0], r.get("dnm_min"), r.get("upm_min"), marca)),
                Line2D([], [], color=col_reg, ls=ls_max, lw=1.6,
                       label=_txt_masa(s_max, 10 ** mm[1], r.get("dnm_max"), r.get("upm_max"), marca)),
            ]

        sub_min = f"min,{k}" if multi else "min"
        sub_max = f"max,{k}" if multi else "max"
        handles_lim += [
            Line2D([], [], color=COLOR_LIMITES, ls=ls_min, lw=1.6,
                   label=_txt_lim(sub_min, r["a_min"], r["dn_min"], r["up_min"], marca)),
            Line2D([], [], color=COLOR_LIMITES_SUP, ls=ls_max, lw=1.6,
                   label=_txt_lim(sub_max, r["a_max"], r["dn_max"], r["up_max"], marca)),
        ]

    if regs:
        # Cajas sobre el panel: a_min y a_max de la región PRINCIPAL (la que contiene el máximo
        # global de densidad). Las demás regiones están en la leyenda.
        caja = dict(facecolor="white", alpha=0.95, edgecolor="black",
                    boxstyle="square,pad=0.2", linewidth=0.6)
        rp = _region_principal(regs, res["malla"])
        ax.text(0.0, 1.015, _txt_lim("min", rp["a_min"], rp["dn_min"], rp["up_min"], " †" if rp["inestable"] else ""),
                transform=ax.transAxes, ha="left", va="bottom", fontsize=cfg["fs_cajas"],
                fontweight="bold", bbox=caja)
        ax.text(1.0, 1.015, _txt_lim("max", rp["a_max"], rp["dn_max"], rp["up_max"], " †" if rp["inestable"] else ""),
                transform=ax.transAxes, ha="right", va="bottom", fontsize=cfg["fs_cajas"],
                fontweight="bold", bbox=caja)

    # ---------------- Líneas verticales extra opcionales ----------------
    handles_extra = []
    for etiqueta, ua, color, ls in (lineas_extra or []):
        ax.axvline(np.log10(ua), color=color, linestyle=ls, linewidth=1.4, zorder=6)
        handles_extra.append(Line2D([], [], color=color, ls=ls, lw=1.4,
                                    label=f"{etiqueta} = {ua:.3f} AU"))

    # ---------------- Puntos por sistema ----------------
    nombre_ss = SISTEMA_SOLAR["nombre_sistema"]
    handles_sis = []
    for sist in df_valid["Sistema"].unique():
        d = df_valid[df_valid["Sistema"] == sist]
        p = estilos_sistema.get(sist, {"marker": "o", "color": "white"})
        es_ss = (sist == nombre_ss)
        h = ax.scatter(np.log10(d["Distancia_UA"]), np.log10(d["Masa_Tierra"]),
                       marker=p["marker"], color=p["color"], s=95 if es_ss else 38,
                       edgecolor="black" if es_ss else "white",
                       linewidth=0.7 if es_ss else 0.5, label=sist,
                       zorder=10 if es_ss else 5)
        if dibujar_individuales and _contorno_sistema(ax, d, xlims, ylims, modo_peso, p.get("ls", "-"), sist):
            h = Line2D([], [], color=COLOR_KDE_SISTEMA, ls=p.get("ls", "-"), lw=0.9,
                       marker=p["marker"], markersize=5.5, markerfacecolor=p["color"],
                       markeredgecolor="white", label=sist)
        handles_sis.append(h)

    # ---------------- Tierra y Júpiter ----------------
    ax.scatter(0, 0, s=150, color=COLOR_TIERRA, edgecolor="white", linewidth=0.8, zorder=9)
    ax.text(0, -0.38, "Earth", color=COLOR_TIERRA, fontsize=8, fontweight="bold",
            ha="center", va="top", zorder=9, clip_on=True)
    xj, yj = np.log10(JUPITER_UA), np.log10(JUPITER_MASA)
    ax.scatter(xj, yj, s=150, color=COLOR_JUPITER, edgecolor="white", linewidth=0.8, zorder=9)
    ax.text(xj, yj - 0.38, "Jupiter", color=COLOR_JUPITER, fontsize=8, fontweight="bold",
            ha="center", va="top", zorder=9, clip_on=True)
    handles_ref = [
        Line2D([], [], marker="o", ls="", color=COLOR_TIERRA, markeredgecolor="white",
               markersize=cfg["ms"], label=r"Earth (1 AU, 1 $M_\oplus$)"),
        Line2D([], [], marker="o", ls="", color=COLOR_JUPITER, markeredgecolor="white",
               markersize=cfg["ms"], label=r"Jupiter (5.2 AU, 317.8 $M_\oplus$)"),
    ]

    # ---------------- Formato ----------------
    ax.set_title(titulo, fontsize=12, fontweight="bold", pad=24)
    ax.set_xlim(xlims)
    ax.set_ylim(ylims)
    ax.set_box_aspect(1)
    ax.set_anchor("N")                       # alinear arriba; la leyenda cae debajo
    ax.set_xlabel("log[Distance] (AU)", fontsize=10)
    if mostrar_ylabel:
        ax.set_ylabel(r"log[Planetary Mass] ($M_\oplus$)", fontsize=10)
    ax.tick_params(labelsize=8)
    ax.grid(True, ls="--", color="white", alpha=0.15, zorder=2)

    # ---------------- Leyenda (tamaño y posición desde cfg) ----------------
    handles = handles_sis + handles_ref + handles_lim + handles_masa + handles_extra
    n = len(handles)
    ncol = cfg.get("ncol") or (2 if n <= 8 else 3)
    esc = cfg["fs"] / 6.3                     # los espaciados escalan con la fuente
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, cfg["y"]),
              ncol=ncol, fontsize=cfg["fs"], frameon=True, framealpha=0.95,
              handletextpad=0.3 * esc, columnspacing=0.8 * esc, borderpad=0.4 * esc,
              labelspacing=0.25 * esc, markerscale=max(1.0, 0.8 * esc))

    return {**res, "n_leyenda": n}


def _dibujar_panel_matriz(ax, df_subset, titulo, estilos_sistema, xlims, ylims,
                          cmap="magma", mostrar_ylabel=True, lineas_extra=None,
                          color_limites=COLOR_LIMITES, modo_peso=None, n_bootstrap=None,
                          nivel_min_pico=None, leyenda=None, etiqueta=None, n_regiones=None,
                          *, unidad_bootstrap=None, dibujar_individuales=True):
    """
    Atajo: capa 1 (calcular_kde_panel, con caché) + capa 2 (dibujar_panel_kde).
    Mantiene la firma que usan las funciones de figuras.
    n_regiones: None = todas las islas; N = las N de mayor densidad (REGIONES_FILA / REGIONES_MULT).
    """
    res = calcular_kde_panel(df_subset, xlims, ylims, modo_peso=modo_peso,
                             n_bootstrap=n_bootstrap, nivel_min_pico=nivel_min_pico,
                             etiqueta=etiqueta or titulo, n_regiones=n_regiones,
                             unidad_bootstrap=unidad_bootstrap)
    return dibujar_panel_kde(ax, df_subset, res, titulo, estilos_sistema, xlims, ylims,
                             cmap=cmap, mostrar_ylabel=mostrar_ylabel,
                             lineas_extra=lineas_extra, leyenda=leyenda, modo_peso=modo_peso,
                             dibujar_individuales=dibujar_individuales)


@_cerrar_figuras_al_salir
def plot_matriz_tipo_multiplicidad(df: pd.DataFrame, base_dir: str,
                                   cmap: str = "magma",
                                   tipos=("F", "G", "K", "M"),
                                   lineas_extra=None,
                                   modo_peso=None):
    """
    Una sola figura:
      - una fila por tipo espectral (F, G, K, M),
      - una columna por multiplicidad (cada fila usa solo las que existen),
      - barra de color única y compartida (Relative Probability Density, %),
      - isolíneas difuminadas, líneas a_min / a_max (verticales) y m_min / m_max (horizontales),
      - leyenda individual bajo cada panel.

    Devuelve un DataFrame con a_min, a_max, m_min, m_max y sus σ por panel y región.
    """
    modo_peso = modo_peso or MODO_PESO_DEFECTO
    df_f = _seleccionar_estrellas(df)
    estilos = _asignar_estilos_sistema(df_f)
    if len(df_f) < 3:
        print("No hay suficientes datos válidos para generar la matriz.")
        return pd.DataFrame()

    # Límites comunes a todos los paneles (incluyen Tierra y Júpiter)
    xlims, ylims = _limites_estrellas(df_f)

    filas = []
    for tipo in tipos:
        d_t = df_f[df_f["Tipo_Estrella"] == tipo]
        if d_t.empty:
            continue
        filas.append((tipo, d_t, sorted(d_t["Num_Planetas"].unique())))
    if not filas:
        print("Ningún tipo espectral con datos.")
        return pd.DataFrame()

    nrows = len(filas)
    ncols = max(len(f[2]) for f in filas)

    # Altura de cada fila según el tamaño de su leyenda más grande
    alturas = []
    for tipo, d_t, mults in filas:
        cfg = _cfg_leyenda(tipo)
        max_filas_leyenda = 0
        for pn in mults:
            n_ent = _n_entradas_leyenda(d_t[d_t["Num_Planetas"] == pn], lineas_extra)
            max_filas_leyenda = max(max_filas_leyenda, _filas_leyenda(n_ent, cfg))
        alturas.append(6.0 + _alto_leyenda(max_filas_leyenda, cfg))

    fig = plt.figure(figsize=(ANCHO_PANEL_MATRIZ * ncols + 1.4, sum(alturas) + 1.0))
    gs = fig.add_gridspec(nrows, ncols + 1,
                          width_ratios=[1.0] * ncols + [0.05],
                          height_ratios=alturas,
                          left=0.05, right=0.95, top=0.955, bottom=0.01,
                          hspace=0.05, wspace=0.28)
    fig.suptitle("Stability Regions for Trojan Bodies by Spectral Type and Multiplicity",
                 fontsize=20, fontweight="bold", y=0.995)

    # Barra de color única y compartida
    cax = fig.add_subplot(gs[:, ncols])
    sm = ScalarMappable(norm=Normalize(0, 100), cmap=cmap)
    ticks_barra = np.linspace(0.0, 90.9, 10)
    cbar = fig.colorbar(sm, cax=cax, ticks=ticks_barra, extend="min")
    cbar.ax.set_yticklabels([f"{v:.1f}" for v in ticks_barra], fontsize=9)
    cbar.set_label("Relative Probability Density (%)", fontsize=12, fontweight="bold")

    tareas = [(r, c, tipo, pn, d_t[d_t["Num_Planetas"] == pn].copy())
              for r, (tipo, d_t, mults) in enumerate(filas)
              for c, pn in enumerate(mults)]

    resumen = []
    filas_sigma = []
    for r, c, tipo, pn, d_sub in tqdm(tareas, desc="Generando paneles", unit="panel"):
        ax = fig.add_subplot(gs[r, c])
        r_p = _dibujar_panel_matriz(
            ax, d_sub, f"Type {tipo} Stars - {pn}-Planet Systems", estilos,
            xlims, ylims, cmap=cmap, mostrar_ylabel=(c == 0),
            lineas_extra=lineas_extra, modo_peso=modo_peso,
            leyenda=_cfg_leyenda(tipo), etiqueta=f"matriz_{tipo}_{pn}pl_{modo_peso}",
            n_regiones=REGIONES_MULT.get((tipo, int(pn))))
        resumen += _filas_resumen(tipo, pn, r_p)
        filas_sigma += _filas_sigma({"Tipo": tipo, "Num_Planetas": pn}, r_p["boot"], diagnostico=r_p["diagnostico"])

    ruta_png = os.path.join(base_dir, f"Map_2D_Islands_Matriz_Tipo_Multiplicidad_{modo_peso}.png")
    ruta_pdf = os.path.join(base_dir, f"Map_2D_Islands_Matriz_Tipo_Multiplicidad_{modo_peso}.pdf")
    _guardar_figura(fig, ruta_png, ruta_pdf)
    _guardar_tabla_sigma(filas_sigma, os.path.join(base_dir, f"intervalos_sigma_matriz_{modo_peso}.csv"))
    return pd.DataFrame(resumen)


@_cerrar_figuras_al_salir
def plot_figuras_por_tipo(df: pd.DataFrame, base_dir: str,
                          cmap: str = "magma",
                          tipos=("F", "G", "K", "M"),
                          lineas_extra=None,
                          modo_peso=None):
    """
    Genera una figura por tipo espectral (Map_2D_Islands_Tipo_<X>_<modo>.png / .pdf).
    Los límites de ejes son comunes a todas las figuras para que sean comparables.
    El Sistema Solar NO forma parte de estas figuras (tiene la suya: analizar_kde_sistema_solar).
    Devuelve un DataFrame con a_min, a_max, m_min, m_max y sus σ por panel y región.
    """
    modo_peso = modo_peso or MODO_PESO_DEFECTO
    print(f"\nGenerando una figura por tipo espectral [pesos: {modo_peso}]...")
    df_f = _seleccionar_estrellas(df)
    estilos = _asignar_estilos_sistema(df_f)
    if len(df_f) < 3:
        print("No hay suficientes datos válidos para generar las figuras.")
        return pd.DataFrame()

    xlims, ylims = _limites_estrellas(df_f)

    resumen = []
    filas_sigma = []
    for tipo in tipos:
        d_t = df_f[df_f["Tipo_Estrella"] == tipo]
        if d_t.empty:
            continue
        mults = sorted(d_t["Num_Planetas"].unique())
        n_pan = len(mults)
        cfg = _cfg_leyenda(tipo)

        # Zoom: límites propios de este tipo espectral (si está en ZOOM_POR_TIPO)
        xlims_t, ylims_t = xlims, ylims
        if tipo in ZOOM_POR_TIPO:
            mx, my = ZOOM_POR_TIPO[tipo]
            xt = np.log10(d_t["Distancia_UA"])
            yt = np.log10(d_t["Masa_Tierra"])
            xlims_t = (max(xt.min() - mx, xlims[0]), min(xt.max() + mx, xlims[1]))
            ylims_t = (max(yt.min() - my, ylims[0]), min(yt.max() + my, ylims[1]))

        # Disposición: F en una fila; G, K, M en cuadrícula de 2 columnas
        if tipo == "F":
            nrows, ncols = 1, n_pan
        else:
            ncols = 2 if n_pan > 1 else 1
            nrows = math.ceil(n_pan / ncols)

        # Altura de cada fila según su leyenda más grande
        alturas = []
        for r in range(nrows):
            max_filas_leyenda = 0
            for pn in mults[r * ncols:(r + 1) * ncols]:
                n_ent = _n_entradas_leyenda(d_t[d_t["Num_Planetas"] == pn], lineas_extra)
                max_filas_leyenda = max(max_filas_leyenda, _filas_leyenda(n_ent, cfg))
            alturas.append(6.0 + _alto_leyenda(max_filas_leyenda, cfg) + 1.1)

        fig_h = sum(alturas) + 1.3
        fig = plt.figure(figsize=(ANCHO_PANEL_TIPO * ncols + 1.6, fig_h))
        gs = fig.add_gridspec(nrows, ncols + 1,
                              width_ratios=[1.0] * ncols + [0.05],
                              height_ratios=alturas,
                              left=0.06, right=0.94,
                              top=1 - 1.15 / fig_h, bottom=0.01,
                              hspace=0.05, wspace=0.38)
        fig.suptitle(f"Stability Regions for Trojan Bodies — Type {tipo} Stars",
                     fontsize=20, fontweight="bold", y=1 - 0.1 / fig_h, va="top")

        # Barra de color compartida por la figura
        cax = fig.add_subplot(gs[:, ncols])
        sm = ScalarMappable(norm=Normalize(0, 100), cmap=cmap)
        ticks_barra = np.linspace(0.0, 90.9, 10)
        cbar = fig.colorbar(sm, cax=cax, ticks=ticks_barra, extend="min")
        cbar.ax.set_yticklabels([f"{v:.1f}" for v in ticks_barra], fontsize=9)
        cbar.set_label("Relative Probability Density (%)", fontsize=12, fontweight="bold")

        for idx, pn in enumerate(tqdm(mults, desc=f"Paneles tipo {tipo}", unit="panel")):
            r, c = divmod(idx, ncols)
            ax = fig.add_subplot(gs[r, c])
            d_pn = d_t[d_t["Num_Planetas"] == pn].copy()
            r_p = _dibujar_panel_matriz(
                ax, d_pn,
                f"Type {tipo} Stars - {pn}-Planet Systems", estilos,
                xlims_t, ylims_t, cmap=cmap,
                mostrar_ylabel=True,
                lineas_extra=lineas_extra, modo_peso=modo_peso,
                leyenda=cfg, etiqueta=f"tipo_{tipo}_{pn}pl_{modo_peso}",
                n_regiones=REGIONES_MULT.get((tipo, int(pn))))
            resumen += _filas_resumen(tipo, pn, r_p)
            filas_sigma += _filas_sigma({"Tipo": tipo, "Num_Planetas": pn}, r_p["boot"], diagnostico=r_p["diagnostico"])

        ruta_png = os.path.join(base_dir, f"Map_2D_Islands_Tipo_{tipo}_{modo_peso}.png")
        ruta_pdf = os.path.join(base_dir, f"Map_2D_Islands_Tipo_{tipo}_{modo_peso}.pdf")
        _guardar_figura(fig, ruta_png, ruta_pdf)

    _guardar_tabla_sigma(filas_sigma, os.path.join(base_dir, f"intervalos_sigma_{modo_peso}.csv"))
    return pd.DataFrame(resumen)


@_cerrar_figuras_al_salir
def plot_tipos_espectrales_fila(df: pd.DataFrame, base_dir: str,
                                cmap: str = "magma",
                                tipos=("F", "G", "K", "M"),
                                modo_peso="fraccion",     # A_est / (A_est + A_inest + A_col_m2)
                                n_bootstrap=None,
                                tam_ticks=14,
                                tam_labels=14):
    """
    Una figura 1 x N con un panel por tipo espectral ("Spectral Type X"), sin el Sistema Solar.
      - Todos los paneles muestran eje X, eje Y y sus números (tamaño tam_ticks).
      - Cada panel lleva debajo su propia leyenda, con SOLO los sistemas de ese tipo
        de estrella (los sistemas quedan separados por tipo).
      - Pesos del KDE: modo_peso="fraccion" -> A_est / (A_est + A_inest + A_col_m2).
      - Nº de regiones por tipo: REGIONES_FILA (F 2, G 2, K 3, M 1).
    Devuelve un DataFrame con a_min, a_max, m_min, m_max y sus σ por tipo y región.
    """
    print(f"\nGenerando figura en fila por tipo espectral [pesos: {modo_peso}]...")
    df_f = _seleccionar_estrellas(df)
    estilos = _asignar_estilos_sistema(df_f)
    if len(df_f) < 3:
        print("No hay suficientes datos válidos para generar la figura.")
        return pd.DataFrame()

    xlims, ylims = _limites_estrellas(df_f)

    grupos = [(t, df_f[df_f["Tipo_Estrella"] == t]) for t in tipos]
    grupos = [(t, d) for t, d in grupos if not d.empty]
    if not grupos:
        print("Ningún tipo espectral con datos.")
        return pd.DataFrame()
    ncols = len(grupos)

    # Altura según la leyenda más larga
    alto_leyenda = 0.0
    for t, d_t in grupos:
        cfg = _cfg_leyenda(t)
        filas_t = _filas_leyenda(_n_entradas_leyenda(d_t), cfg)
        alto_leyenda = max(alto_leyenda, _alto_leyenda(filas_t, cfg))
    alto = 6.5 + alto_leyenda

    fig = plt.figure(figsize=(ANCHO_PANEL_FILA * ncols + 1.6, alto))
    gs = fig.add_gridspec(1, ncols + 1, width_ratios=[1.0] * ncols + [0.04],
                          left=0.05, right=0.96, top=0.93, bottom=0.01, wspace=0.35)

    cax = fig.add_subplot(gs[0, ncols])
    sm = ScalarMappable(norm=Normalize(0, 100), cmap=cmap)
    ticks_barra = np.linspace(0.0, 90.9, 10)
    cbar = fig.colorbar(sm, cax=cax, ticks=ticks_barra, extend="min")
    cbar.ax.set_yticklabels([f"{v:.1f}" for v in ticks_barra], fontsize=tam_ticks - 2)
    cbar.set_label("Relative Probability Density (%)", fontsize=tam_labels, fontweight="bold")

    resumen, filas_sigma = [], []
    for c, (tipo, d_t) in enumerate(tqdm(grupos, desc="Paneles por tipo", unit="panel")):
        ax = fig.add_subplot(gs[0, c])
        r_p = _dibujar_panel_matriz(
            ax, d_t.copy(), f"Spectral Type {tipo}", estilos, xlims, ylims,
            cmap=cmap, mostrar_ylabel=True, modo_peso=modo_peso, n_bootstrap=n_bootstrap,
            leyenda=_cfg_leyenda(tipo), etiqueta=f"fila_{tipo}_{modo_peso}",
            n_regiones=REGIONES_FILA.get(tipo))
        # Ejes siempre visibles, con números grandes
        ax.tick_params(axis="both", labelsize=tam_ticks, labelbottom=True, labelleft=True)
        ax.set_xlabel("log[Distance] (AU)", fontsize=tam_labels)
        ax.set_ylabel(r"log[Planetary Mass] ($M_\oplus$)", fontsize=tam_labels)
        ax.set_title(f"Spectral Type {tipo}", fontsize=16, fontweight="bold", pad=24)
        leg = ax.get_legend()
        if leg is not None:
            leg.set_title(f"Type {tipo} systems", prop={"size": 9, "weight": "bold"})
        resumen += _filas_resumen(tipo, "todos", r_p)
        filas_sigma += _filas_sigma({"Tipo": tipo, "Num_Planetas": "todos"}, r_p["boot"], diagnostico=r_p["diagnostico"])

    ruta = os.path.join(base_dir, f"Map_2D_Islands_Fila_Tipo_Espectral_{modo_peso}")
    _guardar_figura(fig, ruta + ".png", ruta + ".pdf")
    _guardar_tabla_sigma(filas_sigma,
                         os.path.join(base_dir, f"intervalos_sigma_fila_tipo_{modo_peso}.csv"))
    return pd.DataFrame(resumen)


@_cerrar_figuras_al_salir
def analizar_kde_sistema_solar(df=None, base_dir=None, cmap="magma", modo_peso=None,
                               n_bootstrap=None):
    """
    Figura única e independiente de las estrellas tipo G: KDE ponderado de los 8 planetas
    del Sistema Solar, con las líneas de cada región de máxima densidad (bootstrap para los
    errores) y la marca de MARCA_X_SISTEMA_SOLAR. Usa la caché del KDE y la leyenda LEYENDA_SOLAR.
    Guarda figura PNG/PDF, tabla por planeta (densidad relativa en su posición) y tabla σ.
    Con df=None usa los datos de SISTEMA_SOLAR["planetas"].
    """
    ss = SISTEMA_SOLAR
    modo = modo_peso or MODO_PESO_DEFECTO
    nombre = ss["nombre_sistema"]
    base_dir = base_dir or os.path.join(os.getcwd(), "graficos_sistema_solar")
    os.makedirs(base_dir, exist_ok=True)
    if df is None:
        df = construir_sistema_solar()

    d = _datos_fisicos(df[df["Sistema"] == nombre]).sort_values("Distancia_UA")
    if len(d) < 3:
        print("KDE del Sistema Solar omitido: se necesitan al menos 3 planetas con área estable.")
        return None
    w = _calcular_pesos(d, modo)
    if not _pesos_validos(w):
        print(f"KDE del Sistema Solar omitido con modo_peso=\"{modo}\": todos los pesos son nulos.")
        return None

    # Cada planeta como "sistema" propio: un punto y una entrada de leyenda por planeta
    nombres = [str(p).replace(nombre + " ", "") for p in d["Planeta"]]
    d_plot = d.copy()
    d_plot["Sistema"] = nombres
    estilos = _asignar_estilos_sistema(d_plot)
    cmap_pl = plt.get_cmap("tab10")
    for i, nm in enumerate(nombres):
        estilos[nm] = {"marker": "o", "color": cmap_pl(i)}

    x = np.log10(d["Distancia_UA"].to_numpy(dtype=float))
    y = np.log10(d["Masa_Tierra"].to_numpy(dtype=float))
    xlims = LIM_SISTEMA_SOLAR_X or (x.min() - 0.5, x.max() + 0.5)
    ylims = LIM_SISTEMA_SOLAR_Y or (y.min() - 0.5, y.max() + 0.5)

    fig, ax = plt.subplots(figsize=(11.0, 12.5))
    cfg = _KDE.get()
    n_bootstrap = cfg.replicas_solar if n_bootstrap is None else n_bootstrap
    contexto = _SALIDA.get()
    if contexto.carpeta_cache is None:
        contexto = replace(contexto, carpeta_cache=Path(base_dir) / "cache_kde")
    with _configurar(salida=contexto):
        r_p = calcular_kde_panel(d, xlims, ylims, modo_peso=modo, n_bootstrap=n_bootstrap,
                                 nivel_min_pico=cfg.nivel_min_pico_solar,
                                 etiqueta=f"SolarSystem_{modo}", unidad_bootstrap="planetas_solares")
    r_p = dibujar_panel_kde(
        ax, d_plot, r_p, f"Solar System (weights: {modo})", estilos, xlims, ylims,
        cmap=cmap, modo_peso=modo, leyenda=LEYENDA_SOLAR, dibujar_individuales=False)
    sm = ScalarMappable(norm=Normalize(0, 100), cmap=cmap)
    ticks_barra = np.linspace(0.0, 90.9, 10)
    cbar = fig.colorbar(sm, ax=ax, ticks=ticks_barra, extend="min", pad=0.02, fraction=0.046)
    cbar.ax.set_yticklabels([f"{v:.1f}" for v in ticks_barra], fontsize=9)
    cbar.set_label("Relative Probability Density (%)", fontsize=12, fontweight="bold")
    for xp, yp, nm in zip(x, y, nombres):
        ax.annotate(nm, (xp, yp), xytext=(6, 6), textcoords="offset points", color="white",
                    fontsize=12, fontweight="bold", zorder=11)
    if MARCA_X_SISTEMA_SOLAR is not None and xlims[0] < MARCA_X_SISTEMA_SOLAR < xlims[1]:
        xm = MARCA_X_SISTEMA_SOLAR
        ax.axvline(xm, color="cyan", ls=":", lw=1.8, zorder=7)
        ax.annotate(f"{10 ** xm:.0f} AU\n(log a={xm:.2f})", xy=(xm, ylims[1]),
                    xytext=(4, -6), textcoords="offset points", ha="left", va="top",
                    color="cyan", fontsize=10, fontweight="bold", zorder=8)

    ruta = os.path.join(base_dir, f"KDE_Sistema_Solar_{modo}")
    _guardar_figura(fig, ruta + ".png", ruta + ".pdf")

    # tabla por planeta
    tabla = pd.DataFrame({"Planeta": nombres, "a_UA": d["Distancia_UA"].values,
                          "Masa_Mtierra": d["Masa_Tierra"].values,
                          "Area_Estable_km2": d["Area_Estable_km2"].values,
                          "Area_Inestable_km2": d["Area_Inestable_km2" if "Area_Inestable_km2" in d else "Area_Inestable"].values,
                          "Area_Colision_m2_km2": d["Area_Colision_m2_km2" if "Area_Colision_m2_km2" in d else "Area_Colision_m2"].values,
                          "Peso_KDE": w})
    if r_p["malla"] is not None:
        X, Y, Z = r_p["malla"]
        interp = RegularGridInterpolator((X[:, 0], Y[0, :]), Z, bounds_error=False, fill_value=0.0)
        dens = interp(np.column_stack([x, y]))
        bordes = np.append(np.linspace(0.0, 90.9, 10), 100.0)
        idx = np.clip(np.searchsorted(bordes, dens, side="right") - 1, 0, len(bordes) - 2)
        tabla["Densidad_rel_%"] = dens
        tabla["Intervalo_barra_%"] = [f"{bordes[i]:.1f}-{bordes[i + 1]:.1f}" for i in idx]
    tabla.to_csv(ruta.replace("KDE_Sistema_Solar", "kde_sistema_solar_planetas") + ".csv",
                 index=False, encoding="utf-8-sig")

    resumen = pd.DataFrame(_filas_resumen("Solar", len(d), r_p))
    _guardar_csv(resumen, Path(base_dir) / f"limites_sistema_solar_{modo}.csv")
    _escribir_texto_regiones(resumen, Path(base_dir) / f"regiones_sistema_solar_{modo}.txt",
                            "Regiones del Sistema Solar")
    _guardar_tabla_sigma(_filas_sigma({"Muestra": nombre, "Pesos": modo}, r_p["boot"],
                                     diagnostico=r_p["diagnostico"]),
                         Path(base_dir) / f"kde_sistema_solar_intervalos_sigma_{modo}.csv")
    return tabla


def _texto_limite(variable, subindice, valor, error, unidad, marca=""):
    if error is None:
        return f"${variable}_{{{subindice}}}$ = {valor:.3f} {unidad}{marca}"
    texto_error = "<0.001" if 0 < error < 0.0005 else f"{error:.3f}"
    return f"${variable}_{{{subindice}}}$ = {valor:.3f} ± {texto_error} {unidad}{marca}"


def _txt_lim(nombre, a, dn, up, marca=""):
    return _texto_limite("a", nombre, a, (dn + up) / 2, "AU", marca)


def _txt_masa(nombre, m, dn=None, up=None, marca=""):
    error = None if dn is None or up is None else (dn + up) / 2
    return _texto_limite("m", nombre, m, error, r"$M_\oplus$", marca)


def _asignar_estilos_sistema(df):
    """Asigna marcador y línea a todos los sistemas, con un color común para los KDE."""
    sistemas = df["Sistema"] if "Sistema" in df else df["Planeta"].str.rsplit(" ", n=1).str[0]
    marcadores = ["o", "s", "^", "D", "v", "p", "*", "h", "H", "X", "d", "P", "<", ">"]
    combinaciones = itertools.cycle(itertools.product(marcadores, plt.cm.tab20.colors))
    estilos = {}
    for i, sistema in enumerate(sistemas.unique()):
        marcador, color = next(combinaciones)
        # Las combinaciones de trazo se amplían sin reciclar los primeros estilos.
        ls = "-" if i == 0 else (0, (2.0 + i // 8 * 0.4, 1 + i % 8 * 0.3, 1.0, 1.2))
        estilos[sistema] = {"marker": marcador, "color": color, "ls": ls}
    ss = SISTEMA_SOLAR
    if ss["activo"] and ss["nombre_sistema"] in estilos:
        estilos[ss["nombre_sistema"]].update(marker=ss["marcador"], color=ss["color"])
    return estilos


def _contorno_sistema(ax, df, xlims, ylims, modo, estilo, nombre):
    cfg = _KDE.get()
    if len(df) < 3:
        return False
    x, y = np.log10(df[["Distancia_UA", "Masa_Tierra"]].to_numpy(dtype=float)).T
    w = _calcular_pesos(df, modo)
    if np.count_nonzero(w) < 3 or np.ptp(x[w > 0]) == 0 or np.ptp(y[w > 0]) == 0:
        return False
    clave = _hash_cache("individual", x, y, w, tuple(xlims), tuple(ylims))

    def _calc():
        res = {"malla": None, "regiones": [], "boot": {}, "diagnostico": {}}
        X, Y = _malla(xlims, ylims, cfg.malla)
        try:
            Z, _ = _malla_nominal(x, y, w, X, Y, cfg.bw)
            res["malla"] = (X, Y, Z)
        except (np.linalg.LinAlgError, ValueError) as exc:
            LOG.debug("KDE individual no estimable para %s: %s", nombre, exc)
        return res

    malla = _cache_obtener(f"sistema {nombre}", clave, _calc)["malla"]
    if malla is None:
        return False
    ax.contour(*malla, levels=[cfg.nivel], colors=[COLOR_KDE_SISTEMA],
               linestyles=[estilo], alpha=0.62, linewidths=0.75, zorder=2.2)
    return True


def _filas_resumen(tipo, pn, r_p):
    """Incluye diagnósticos para los paneles válidos y los que carecen de regiones."""
    d = r_p["diagnostico"]
    comunes = {"Tipo": tipo, "Num_Planetas": pn, "N_regiones": len(r_p["regiones"]),
               "Estado_panel": d["estado"], "Unidad_remuestreo": d["unidad"],
               "N_planetas": d["n_planetas"], "N_sistemas": d["n_sistemas"],
               "N_replicas_intentadas": d["evaluadas"],
               "N_replicas_descartadas_panel": sum(d["descartes"].values()),
               "N_replicas_varianza_nula": d["descartes"].get("varianza_nula", 0),
               "N_replicas_pesos_nulos": d["descartes"].get("pesos_nulos", 0),
               "N_replicas_kde_no_estimable": d["descartes"].get("kde_no_estimable", 0),
               "N_replicas_sin_region_asignada": d["descartes"].get("sin_region_asignada", 0),
               "Piso_x_dex": d.get("piso_x_dex"), "Piso_y_dex": d.get("piso_y_dex")}
    if not r_p["regiones"]:
        return [{**comunes, "Region": None, "a_min_UA": None, "sigma_a_min": None,
                 "a_max_UA": None, "sigma_a_max": None, "m_min_Mt": None, "m_max_Mt": None}]
    return [
        {**comunes, "Region": r["region"], "N_replicas_validas": r["n_validas"],
         "N_replicas_no_recuperadas": d["evaluadas"] - r["n_validas"],
         "Tasa_recuperacion": r["recuperacion"], "Region_inestable": r["inestable"],
         "Solo_resolucion": r["solo_resolucion"], "Pico_densidad_%": r["pico"],
         "Nivel_contorno_%": r["nivel"],
         "a_min_UA": r["a_min"], "sigma_a_min": r["s_min"],
         "a_max_UA": r["a_max"], "sigma_a_max": r["s_max"],
         "a_min_menos": r["dn_min"], "a_min_mas": r["up_min"],
         "a_max_menos": r["dn_max"], "a_max_mas": r["up_max"],
         "m_min_Mt": r["m_min"], "sigma_m_min": r["sm_min"],
         "m_max_Mt": r["m_max"], "sigma_m_max": r["sm_max"],
         "m_min_menos": r["dnm_min"], "m_min_mas": r["upm_min"],
         "m_max_menos": r["dnm_max"], "m_max_mas": r["upm_max"],
         "m_pico_Mt": r["m_pico"], **{k: v for k, v in r.items() if k.endswith("_en_borde")}}
        for r in r_p["regiones"]]


def _escribir_texto_regiones(res, ruta, titulo):
    """Exporta los límites nominales y la recuperación de cada región."""
    cfg = _KDE.get()
    def fmt(v, e):
        error = "<0.001" if 0 < e < 0.0005 else f"{e:.3f}"
        return f"{v:.3f} ± {error}"

    lineas = [titulo, "=" * len(titulo),
              f"Error simétrico 1σ ({cfg.metodo_error}) con resolución de {cfg.piso_celdas:g} celdas en dex.",
              "† Recuperación baja o réplicas insuficientes. Los errores con solo resolución son instrumentales.",
              ""]
    for r in res.to_dict("records"):
        nombre = f"Tipo {r['Tipo']} | {r['Num_Planetas']} planetas"
        if pd.isna(r["Region"]):
            lineas.append(f"{nombre} | {r['Estado_panel']}")
            continue
        marca = " †" if r["Region_inestable"] else ""
        lineas.append(f"{nombre} | región {int(r['Region'])} de {int(r['N_regiones'])}{marca}")
        lineas.append(f"   Distancia: de {fmt(r['a_min_UA'], r['sigma_a_min'])} "
                      f"a {fmt(r['a_max_UA'], r['sigma_a_max'])} AU")
        lineas.append(f"   Masa: de {fmt(r['m_min_Mt'], r['sigma_m_min'])} "
                      f"a {fmt(r['m_max_Mt'], r['sigma_m_max'])} M_Tierra")
        n, total = r["N_replicas_validas"], r["N_replicas_intentadas"]
        tasa = f"{n / total:.1%}" if total else "sin remuestreo"
        lineas.append(f"   Pico {r['Pico_densidad_%']:.2f} % · nivel {r['Nivel_contorno_%']:.2f} % · "
                      f"recuperación {n}/{total} ({tasa}) · {r['Unidad_remuestreo']}")
        if r["Solo_resolucion"]:
            lineas.append("   Incertidumbre indicada solo por la resolución de la malla.")
        if any(v is True for k, v in r.items() if k.endswith("_en_borde")):
            lineas.append("   Algún límite coincide con el borde de la malla.")
        lineas.append("")
    Path(ruta).write_text("\n".join(lineas), encoding="utf-8")


def _guardar_figura(fig, ruta_png, ruta_pdf):
    """Usa la misma figura de alta resolución para ambas salidas."""
    fig.savefig(ruta_png, dpi=300, bbox_inches="tight")
    fig.savefig(ruta_pdf, format="pdf", bbox_inches="tight")
    _mostrar_o_cerrar(fig)


@_cerrar_figuras_al_salir
def _plot_islas(df, base_dir, grupos, categoria, cmap, modo_peso):
    d = _seleccionar_estrellas(df)
    if d.empty or not grupos:
        return pd.DataFrame()
    modo = modo_peso or MODO_PESO_DEFECTO
    xlims, ylims = _limites_estrellas(d)
    estilos = _asignar_estilos_sistema(d)
    ncols = min(2, len(grupos)) if categoria == "PorTipoEstrella" else len(grupos)
    nrows = math.ceil(len(grupos) / ncols)
    fig, axs = plt.subplots(nrows, ncols, figsize=(8.5 * ncols, 11.5 * nrows), squeeze=False)
    filas, sigmas = [], []
    for ax, (tipo, pn, sub, titulo, n_regiones) in zip(axs.flat, grupos):
        r = _dibujar_panel_matriz(ax, sub, titulo, estilos, xlims, ylims, cmap=cmap, modo_peso=modo,
                                 leyenda=_cfg_leyenda(tipo), n_regiones=n_regiones)
        filas += _filas_resumen(tipo, pn, r)
        sigmas += _filas_sigma({"Tipo": tipo, "Num_Planetas": pn}, r["boot"], diagnostico=r["diagnostico"])
    for ax in axs.flat[len(grupos):]:
        ax.set_visible(False)
    fig.colorbar(ScalarMappable(norm=Normalize(0, 100), cmap=cmap), ax=axs.ravel().tolist(),
                 fraction=0.025, label="Relative Probability Density (%)")
    fig.subplots_adjust(hspace=0.7, wspace=0.45)
    ruta = os.path.join(base_dir, f"Map_2D_Islands_Area_Estable_km2_{categoria}_{modo}")
    _guardar_figura(fig, ruta + ".png", ruta + ".pdf")
    _guardar_tabla_sigma(sigmas, os.path.join(base_dir, f"intervalos_sigma_{categoria}_{modo}.csv"))
    return pd.DataFrame(filas)


def plot_islands_por_tipo_estrella(df: pd.DataFrame, base_dir: str,
                                   tipos=("F", "G", "K", "M"), cmap="magma",
                                   color_rocoso="brown", color_neptuniano="purple", modo_peso=None):
    """Genera los paneles por tipo espectral en la cuadrícula histórica."""
    d = _seleccionar_estrellas(df)
    grupos = [(t, "todos", d[d["Tipo_Estrella"] == t], f"All systems — Type {t}", REGIONES_FILA.get(t))
              for t in tipos if t in set(d["Tipo_Estrella"])]
    return _plot_islas(d, base_dir, grupos, "PorTipoEstrella", cmap, modo_peso)


def plot_islands_zonas_estables2(df: pd.DataFrame, base_dir: str, cmap="magma", modo_peso=None):
    """Mantiene la llamada histórica para la figura global y por multiplicidad."""
    d = _seleccionar_estrellas(df)
    grupos = [("Todos", "todos", d, "Global View: All systems", None)]
    grupos.extend(("Todos", pn, sub, f"Systems with {pn} planets", None)
                  for pn, sub in d.groupby("Num_Planetas"))
    return _plot_islas(d, base_dir, grupos, "Horizontal", cmap, modo_peso)


def plot_sistemas_f_horizontal_gkm_cuadrados(df: pd.DataFrame, base_dir: str, cmap="magma",
                                             color_rocoso="brown", color_neptuniano="purple",
                                             modo_peso=None):
    """Mantiene la llamada histórica con los paneles por tipo y multiplicidad."""
    return plot_figuras_por_tipo(df, base_dir, cmap=cmap, modo_peso=modo_peso)


@_cerrar_figuras_al_salir
def analizar_sistema_solar(df: pd.DataFrame, base_dir: str, cmap="magma", modo_peso=None):
    """Compara cada planeta solar con el KDE y las islas en dos dimensiones del tipo G."""
    ss = SISTEMA_SOLAR
    modo = modo_peso or MODO_PESO_DEFECTO
    nombre, tipo = ss["nombre_sistema"], ss["tipo_estrella"]
    d = _datos_fisicos(df)
    d = d[d["Tipo_Estrella"].str.strip().str.upper() == tipo]
    d_ss = d[d["Sistema"] == nombre]
    d_ref = d[d["Sistema"] != nombre]
    if d_ss.empty or len(d_ref) < 3:
        LOG.warning("Comparación solar omitida por falta de planetas solares o de referencia")
        return None
    xlims, ylims = _limites_estrellas(d, margen_y=(0.4, 0.4))
    res = calcular_kde_panel(d_ref, xlims, ylims, modo_peso=modo, etiqueta=f"{tipo}_sin_SS",
                             n_regiones=REGIONES_FILA.get(tipo))
    if res["malla"] is None:
        return None
    X, Y, Z = res["malla"]
    comparar = d.copy()
    # El conjunto solar es un solo sistema en la comparación entre poblaciones.
    con = calcular_kde_panel(comparar, xlims, ylims, modo_peso=modo, etiqueta=f"{tipo}_con_SS",
                             n_regiones=REGIONES_FILA.get(tipo))
    filas = []
    for muestra, r in ((f"{tipo} sin {nombre}", res), (f"{tipo} con {nombre}", con)):
        filas += _filas_sigma({"Muestra": muestra, "Pesos": modo}, r["boot"], diagnostico=r["diagnostico"])
    _guardar_tabla_sigma(filas, os.path.join(base_dir, f"comparacion_G_con_sin_sistema_solar_{modo}.csv"))
    _guardar_csv(pd.DataFrame(_filas_resumen("G sin Solar", "todos", res)
                              + _filas_resumen("G con Solar", "todos", con)),
                 os.path.join(base_dir, f"limites_comparacion_solar_{modo}.csv"))

    coords = ["Distancia_UA", "Masa_Tierra"]
    ref, planetas = (np.log10(d_[coords].to_numpy(dtype=float)) for d_ in (d_ref, d_ss))
    interp = RegularGridInterpolator((X[:, 0], Y[0, :]), Z, bounds_error=False, fill_value=0.0)
    dens_ref, dens = interp(ref), interp(planetas)
    bordes = np.append(np.linspace(0.0, 90.9, 10), 100.0)
    idx = np.clip(np.searchsorted(bordes, dens, side="right") - 1, 0, len(bordes) - 2)
    nominales, ampliadas = [], []
    for r in res["regiones"]:
        k = r["region"]
        nominal = (r["lmin"], r["lmax"], math.log10(r["m_min"]), math.log10(r["m_max"]))
        nominales.append(nominal)
        iv = [_intervalo_sigma(vals, 3, c)
              for c, vals in (res["boot"][f"{b}_{k}"] for b in ("a_min", "a_max", "m_min", "m_max"))]
        if all(v is not None for v in iv):
            ampliadas.append(tuple(f(c, v[i % 2]) for i, (f, c, v) in
                                   enumerate(zip((min, max, min, max), nominal, iv))))

    def _en(x, y, cajas):
        return any(lo <= x <= hi and yl <= y <= yh for lo, hi, yl, yh in cajas)

    nombres = d_ss["Planeta"].str.removeprefix(nombre + " ").tolist()
    tabla = pd.DataFrame({
        "Planeta": nombres, "a_UA": d_ss["Distancia_UA"], "Masa_Mtierra": d_ss["Masa_Tierra"],
        "Densidad_rel_G_%": dens, "Intervalo_barra_%": [f"{bordes[i]:.1f}-{bordes[i+1]:.1f}" for i in idx],
        "Percentil_en_planetas_G_%": [(dens_ref <= z).mean() * 100 for z in dens],
        "N_regiones_G": len(nominales), "En_region_nominal": [_en(*p, nominales) for p in planetas],
        "En_region_3sigma": [_en(*p, ampliadas) for p in planetas] if ampliadas and
        len(ampliadas) == len(nominales) else None})
    _guardar_csv(tabla, os.path.join(base_dir, f"analisis_sistema_solar_planetas_{modo}.csv"))

    fig, ax = plt.subplots(figsize=(10.5, 9.5))
    ref_fig = d_ref.assign(Sistema=f"Type {tipo} planets (reference)")
    dibujar_panel_kde(ax, ref_fig, res, f"Solar System vs. Type {tipo} Stability Regions (weights: {modo})",
                     _asignar_estilos_sistema(ref_fig), xlims, ylims, cmap=cmap, modo_peso=modo,
                     leyenda={"fs": LEYENDA_COMPARACION_FS, "ncol": 2}, dibujar_individuales=False)
    solar = ax.scatter(*planetas.T, s=190, marker=ss["marcador"], color=ss["color"],
                       edgecolor="black", linewidth=0.9, zorder=10, label=nombre)
    anterior = ax.get_legend()
    ax.legend(handles=[solar, *anterior.legend_handles], loc="upper center",
              bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=LEYENDA_COMPARACION_FS, frameon=True)
    for (xp, yp), pl in zip(planetas, nombres):
        ax.annotate(pl, (xp, yp), xytext=(6, 6), textcoords="offset points",
                    color="white", fontsize=10, fontweight="bold", zorder=11)
    cbar = fig.colorbar(ScalarMappable(norm=Normalize(0, 100), cmap=cmap), ax=ax, pad=0.02,
                        ticks=np.linspace(0, 90.9, 10), extend="min")
    cbar.set_label(f"Relative Probability Density (%) — {tipo} systems without Solar System")
    ruta = os.path.join(base_dir, f"Solar_System_vs_G_Type_{modo}")
    _guardar_figura(fig, ruta + ".png", ruta + ".pdf")
    return tabla

# %% Ejecución
ETAPAS = ("fila", "tipo", "matriz", "islas", "solar", "comparar")
ETAPAS_DEFECTO = ("fila", "tipo", "solar")
SALIDA_CARPETA = "graficos_magma_con_sistemas_azules"


def preparar_sistema_solar() -> pd.DataFrame:
    """Prepara el catálogo solar incorporado para sus etapas independientes."""
    return construir_sistema_solar() if SISTEMA_SOLAR["activo"] else pd.DataFrame()


def _detectar_carpeta():
    for directorio in (Path.cwd(), *Path.cwd().parents):
        # El catálogo de referencia de 448 se conserva en Troyanos.
        for candidato in (directorio / "Troyanos", directorio):
            if all((candidato / f"Resultados_Estrellas_{t}").is_dir() for t in "FGKM"):
                return candidato
    raise ValueError("Indica el catálogo con --carpeta o activa --dialogos")


def _preparar_salida(carpeta, sobrescribir):
    out = Path(carpeta).expanduser().resolve()
    if out.exists() and not sobrescribir and any(p.name != "cache_kde" for p in out.iterdir()):
        raise FileExistsError(f"{out} ya tiene archivos. Usa otra ruta o --sobrescribir")
    out.mkdir(parents=True, exist_ok=True)
    return out


def _guardar_lectura(df, out):
    info = df.attrs["lectura"]
    filas = info["descartados"]
    _guardar_csv(df, out / "datos_extraidos.csv")
    _guardar_csv(pd.DataFrame(filas, columns=("Tipo_Estrella", "Sistema", "Planeta", "Archivo", "Motivo")),
                 out / "descartes_lectura.csv")
    lineas = ["Lectura del catálogo", f"Esperados: {info['esperado']}", f"Válidos: {len(df)}",
              f"Descartados: {len(filas)}"]
    for t, n in info["candidatos"].items():
        lineas.append(f"{t} · {info['validos'].get(t, 0)} de {n} candidatos")
    for motivo, n in Counter(f["Motivo"] for f in filas).most_common():
        lineas.append(f"{n} · {motivo}")
    (out / "informe_lectura.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def ejecutar(etapas=ETAPAS_DEFECTO, *, carpeta=None, carpeta_salida=None, configuracion=None,
             mostrar=False, dialogos=False, cache=True, recalcular=False,
             esperado=N_PLANETAS_ESPERADO, exigir_total=False, sobrescribir=False):
    """Ejecuta las etapas solicitadas y devuelve sus tablas para inspección."""
    etapas = (etapas,) if isinstance(etapas, str) else tuple(etapas)
    if set(etapas) - {*ETAPAS, "todo", "kde_solar"}:
        raise ValueError(f"Etapas desconocidas: {', '.join(sorted(set(etapas) - {*ETAPAS, 'todo', 'kde_solar'}))}")
    if "todo" in etapas:
        etapas = ETAPAS
    if "kde_solar" in etapas:
        if etapas != ("kde_solar",):
            raise ValueError("kde_solar se ejecuta como etapa independiente")
        return ejecutar_sistema_solar(carpeta_salida, configuracion=configuracion, mostrar=mostrar,
                                      cache=cache, recalcular=recalcular, sobrescribir=sobrescribir)
    if not mostrar:
        # Al importar el módulo, el entorno conserva su backend. La ejecución sin
        # pantalla selecciona Agg salvo si hay figuras del llamante abiertas.
        if not plt.get_fignums():
            plt.switch_backend("Agg")
    con_catalogo = bool(set(etapas) - {"solar"})
    df = None
    if con_catalogo:
        fuente = carpeta if carpeta is not None or dialogos else _detectar_carpeta()
        df, base = extraer_datos_personalizados(fuente, esperado=esperado)
        if not base:
            return {}
        base = Path(fuente) if fuente is not None else Path(base)
    else:
        base = Path(carpeta) if carpeta is not None else Path.cwd()
    out = _preparar_salida(carpeta_salida or (base / SALIDA_CARPETA), sobrescribir)
    if df is not None:
        _guardar_lectura(df, out)
        if df.empty:
            raise ValueError(f"No hay planetas válidos. Consulta el informe de lectura en {out}")
        if exigir_total and esperado is not None and len(df) != esperado:
            raise ValueError(f"Catálogo con {len(df)} planetas. Se esperaban {esperado}")
    if "solar" in etapas or "comparar" in etapas:
        df_ss = preparar_sistema_solar()
    resultado = {}
    salida = ConfiguracionSalida(out / "cache_kde", cache, recalcular, mostrar)
    with _configurar(configuracion, salida):
        for etapa in dict.fromkeys(etapas):
            if etapa == "solar":
                if not df_ss.empty:
                    resultado[etapa] = analizar_kde_sistema_solar(df_ss, out / "sistema_solar")
                continue
            if etapa == "comparar":
                if not df_ss.empty:
                    resultado[etapa] = analizar_sistema_solar(pd.concat([df, df_ss], ignore_index=True), out)
                continue
            funcion, archivo = {
                "fila": (plot_tipos_espectrales_fila, "fila"),
                "tipo": (plot_figuras_por_tipo, "tipo"),
                "matriz": (plot_matriz_tipo_multiplicidad, "matriz"),
                "islas": (plot_islands_por_tipo_estrella, "islas"),
            }[etapa]
            tabla = resultado[etapa] = funcion(df, out)
            if tabla.empty:
                continue
            prefijo = "limites_estabilidad" if etapa == "tipo" else f"limites_estabilidad_{archivo}"
            _guardar_csv(tabla, out / f"{prefijo}_{MODO_PESO_DEFECTO}.csv")
            _escribir_texto_regiones(tabla, out / f"regiones_distancia_masa_{archivo}.txt",
                                    f"Regiones de mayor densidad · {etapa}")
    LOG.info("Salidas guardadas en %s", out)
    return resultado


def ejecutar_sistema_solar(carpeta_salida=None, modos=("area", "fraccion", "neto"), *,
                            configuracion=None, mostrar=False, cache=True, recalcular=False,
                            sobrescribir=False):
    """Ejecuta el KDE solar para los modos de peso solicitados."""
    if not mostrar and not plt.get_fignums():
        plt.switch_backend("Agg")
    out = _preparar_salida(carpeta_salida or "graficos_sistema_solar", sobrescribir)
    with _configurar(configuracion, ConfiguracionSalida(out / "cache_kde", cache, recalcular, mostrar)):
        return {m: analizar_kde_sistema_solar(base_dir=out, modo_peso=m) for m in modos}


def main(argv=None):
    """Interfaz de línea de comandos."""
    p = argparse.ArgumentParser(description="Mapas 2D de estabilidad para planetas troyanos.")
    p.add_argument("etapas", nargs="*", metavar="ETAPA",
                   help="fila, tipo, matriz, islas, solar, comparar, todo o kde_solar")
    origen = p.add_mutually_exclusive_group()
    origen.add_argument("--carpeta", type=Path, help="Raíz del catálogo o carpeta de un tipo espectral")
    origen.add_argument("--dialogos", action="store_true", help="Selecciona los datos con Tkinter")
    p.add_argument("--salida", type=Path, help="Carpeta de salida")
    p.add_argument("--mostrar", action="store_true", help="Abre las figuras con el backend del entorno")
    p.add_argument("--sin-cache", action="store_true")
    p.add_argument("--recalcular", action="store_true")
    p.add_argument("--sobrescribir", action="store_true")
    p.add_argument("--esperados", type=int, default=N_PLANETAS_ESPERADO)
    p.add_argument("--exigir-total", action="store_true")
    p.add_argument("--bw", type=float, default=BW_FIJO)
    p.add_argument("--malla", type=int, default=ConfiguracionKDE.malla)
    p.add_argument("--replicas", type=int, default=ConfiguracionKDE.replicas)
    p.add_argument("--replicas-solar", type=int, default=ConfiguracionKDE.replicas_solar)
    p.add_argument("--error", choices=("basico", "percentil", "std"), default=ConfiguracionKDE.metodo_error)
    p.add_argument("--covarianza-variable", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        cfg = ConfiguracionKDE(bw=args.bw, malla=args.malla, replicas=args.replicas,
                               replicas_solar=args.replicas_solar, metodo_error=args.error,
                               covarianza_fija=not args.covarianza_variable)
        ejecutar(args.etapas or ETAPAS_DEFECTO, carpeta=args.carpeta, carpeta_salida=args.salida,
                 configuracion=cfg, dialogos=args.dialogos, mostrar=args.mostrar,
                 cache=not args.sin_cache, recalcular=args.recalcular, esperado=args.esperados,
                 exigir_total=args.exigir_total, sobrescribir=args.sobrescribir)
    except (OSError, ValueError) as exc:
        p.exit(2, f"{p.prog}: {exc}\n")
    return 0


if __name__ == "__main__" and "ipykernel" not in sys.modules:
    raise SystemExit(main())
