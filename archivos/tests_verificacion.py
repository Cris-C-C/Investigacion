"""Pruebas del lector, la densidad, las figuras y el remuestreo reproducible.

Ejecutar desde este directorio con python -m pytest -q -s tests_verificacion.py.
El contraste histórico usa el código original de Final.ipynb si está disponible.
"""
import ast
import json
import math
import pickle
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest
from matplotlib import pyplot as plt
from scipy.interpolate import RegularGridInterpolator
from scipy.stats import norm, multivariate_normal

import mapas_estabilidad_robusto as mapas


def _tabla(puntos, sistemas=None):
    n = len(puntos)
    return pd.DataFrame({
        "Sistema": [str(i) for i in range(n)] if sistemas is None else sistemas,
        "Distancia_UA": 10 ** puntos[:, 0], "Masa_Tierra": 10 ** puntos[:, 1],
        "Area_Estable_km2": np.ones(n), "Area_Inestable_km2": 2.0,
        "Area_Colision_m2_km2": 1.0,
    })


def _planeta(raiz, nombre, readme=True, area_inestable=True, masa="1,5e+1"):
    carpeta = raiz / "Resultados_Estrellas_F" / "S" / nombre
    carpeta.mkdir(parents=True)
    if readme:
        (carpeta / "README.txt").write_text(
            f"Masa del planeta: {masa} M_Tierra\n"
            "Masa estelar: 1,1 Masas Solares\n"
            "Semi eje mayor (AU): 2,5e-1\n", encoding="utf-8-sig")
    (carpeta / "resumen.txt").write_text(
        "Área estable: 1,25e6 m²\n"
        + ("Área inestable (km^2): 2\n" if area_inestable else "")
        + "Área colisión m2: 0 km²\nTotal estables: 100\n",
        encoding="utf-8")
    return carpeta


def test_lectura_multiplicidad_y_descartes(tmp_path):
    _planeta(tmp_path, "S_b")
    _planeta(tmp_path, "S_c", readme=False)
    _planeta(tmp_path, "S_d", area_inestable=False)
    _planeta(tmp_path, "S_e", masa="0")
    _planeta(tmp_path, "S_f", masa="1e999")
    (tmp_path / "Resultados_Estrellas_F" / "S" / "graficos").mkdir()
    d, _ = mapas.extraer_datos_personalizados(tmp_path, esperado=1)
    assert d["Num_Planetas"].tolist() == [5]
    assert d["Distancia_UA"].tolist() == [0.25]
    assert d["Masa_Tierra"].tolist() == [15.]
    assert d["Masa_Estrella"].tolist() == [1.1]
    assert d["Area_Estable_km2"].tolist() == [1.25]
    assert len(d.attrs["lectura"]["descartados"]) == 4
    faltantes = [r["Motivo"] for r in d.attrs["lectura"]["descartados"]]
    assert any("README" in motivo for motivo in faltantes)
    assert any("Area_Inestable" in motivo for motivo in faltantes)
    assert mapas._numero("1.234,52") == 1234.52
    assert mapas._numero("-1,234.52e-1") == -123.452
    with pytest.raises(ValueError, match="ambiguo"):
        mapas._numero("12,34.56")


def test_unidades_y_multiplicidad_explicita(tmp_path):
    b = _planeta(tmp_path, "S_b")
    c = _planeta(tmp_path, "S_c")
    with (b / "README.txt").open("a", encoding="utf-8") as f:
        f.write("Número de planetas: 7\n")
    d, _ = mapas.extraer_datos_personalizados(tmp_path)
    assert d["Num_Planetas"].tolist() == [7, 7]
    with (c / "README.txt").open("a", encoding="utf-8") as f:
        f.write("Total planetas: 6\n")
    with pytest.raises(ValueError, match="Multiplicidades contradictorias"):
        mapas.extraer_datos_personalizados(tmp_path)
    campos = list(mapas._campos("Masa planetaria (kg): 10"))
    with pytest.raises(ValueError, match="unidad no reconocida"):
        mapas._leer_campo(campos, "masa planetaria", "masa", {"masas terrestres": 1.0})


def test_pesos_validos_y_columnas_historicas():
    d = mapas.construir_sistema_solar()
    canonicas = [nombre for nombre, _ in mapas.AREAS]
    historicas = d.drop(columns=canonicas[1:])
    np.testing.assert_array_equal(mapas._calcular_pesos(d), mapas._calcular_pesos(historicas))
    np.testing.assert_allclose(mapas._calcular_pesos(d), d[canonicas[0]] / d[canonicas].sum(axis=1))
    with pytest.raises(ValueError, match="Faltan columnas"):
        mapas._calcular_pesos(historicas.drop(columns="Area_Inestable"))
    with pytest.raises(ValueError, match="contradictorias"):
        mapas._calcular_pesos(d.assign(Area_Inestable=0))
    assert mapas._pesos_validos([1, 1, 1])
    assert not mapas._pesos_validos([-1, 1, 1])
    assert not mapas._pesos_validos([0, 0, 0])


def test_catalogo_y_regiones_g():
    raiz = Path(__file__).resolve().parent.parent / "Troyanos"
    if not raiz.is_dir():
        pytest.skip("El catálogo local de referencia está en Troyanos")
    d, _ = mapas.extraer_datos_personalizados(raiz, esperado=448)
    assert d.attrs["lectura"]["descartados"] == []
    assert d.groupby("Tipo_Estrella").size().to_dict() == {"F": 24, "G": 124, "K": 140, "M": 160}
    assert not d.duplicated(["Sistema", "Planeta"]).any()
    assert (d.groupby("Sistema")["Planeta"].transform("size") == d["Num_Planetas"]).all()
    x, y = mapas._limites_estrellas(d)
    g = mapas.calcular_kde_panel(d[d.Tipo_Estrella == "G"], x, y, n_bootstrap=40, n_regiones=2)
    _invariantes(g, x, y)
    a, b = g["regiones"]
    assert a["a_max"] < b["a_min"]
    assert a["nivel"] == pytest.approx(90.9)
    assert b["nivel"] == pytest.approx(70.7)
    assert b["pico"] == pytest.approx(71.0, abs=0.1)
    assert a["m_max"] < b["m_min"]


def test_paneles_no_estimables_y_un_sistema():
    p = np.array([[-0.4, 0], [-0.15, .5], [0.1, .12], [0.02, -0.22]])
    d = _tabla(p, ["S"] * len(p))
    kwargs = {"xlims": (-1, 1), "ylims": (-1, 1), "n_bootstrap": 30}
    with mapas._configurar(mapas.ConfiguracionKDE(malla=61)):
        r = mapas.calcular_kde_panel(d, **kwargs)
        _invariantes(r, kwargs["xlims"], kwargs["ylims"])
        assert r["diagnostico"]["unidad"] == "planetas_intrasistema"
        assert r["diagnostico"]["evaluadas"] == 30
        estados = [
            (d.iloc[:2], "menos_de_tres_planetas"),
            (d.assign(Masa_Tierra=1), "varianza_nula"),
            (d.assign(Area_Estable_km2=0), "menos_de_tres_pesos_positivos"),
            (d.assign(Distancia_UA=[np.inf, np.nan, 1, 2]), "menos_de_tres_planetas"),
        ]
        for tabla, estado in estados:
            r = mapas.calcular_kde_panel(tabla, **kwargs)
            assert r["malla"] is None
            assert r["diagnostico"]["estado"] == estado
        with pytest.raises(ValueError, match="áreas deben ser finitas"):
            mapas.calcular_kde_panel(d.assign(Area_Estable_km2=np.nan), **kwargs)


def test_cache_corrupcion_version_y_regeneracion(tmp_path, monkeypatch):
    cfg = mapas.ConfiguracionKDE(malla=51)
    cfg_salida = mapas.ConfiguracionSalida(tmp_path)
    d = _tabla(np.random.default_rng(17).normal(size=(12, 2)) * 0.23)

    def obtener():
        return mapas.calcular_kde_panel(d, (-1, 1), (-1, 1), n_bootstrap=18, n_regiones=1)

    with mapas._configurar(cfg, cfg_salida):
        r = obtener()
        archivo, = tmp_path.glob("*.pkl")
        with monkeypatch.context() as parches:
            parches.setattr(mapas, "_malla_nominal", lambda *a: pytest.fail("KDE se recalculó"))
            assert obtener()["regiones"] == r["regiones"]
        archivo.write_bytes(b"truncada")
        assert obtener()["regiones"] == r["regiones"]
        with archivo.open("wb") as f:
            pickle.dump(("v4", "clave antigua", None, {}), f)
        assert obtener()["regiones"] == r["regiones"]
    with mapas._configurar(replace(cfg, bw=0.65), cfg_salida):
        assert obtener()["regiones"] != r["regiones"]
    assert len(list(tmp_path.glob("*.pkl"))) == 2


def test_covarianza_fija_equivalente_al_bucle_y_a_scipy():
    rng = np.random.default_rng(203)
    xy = rng.normal(size=(23, 2)) * [0.4, 0.8]
    x, y = xy.T
    w = rng.uniform(size=len(x))
    X, Y = mapas._malla((-2, 2), (-3, 3), 65)
    Z_scipy, cov = mapas._malla_nominal(x, y, w, X, Y, bw=0.55)
    k = mapas._nucleos_fijos(x, y, cov, X, Y)
    np.testing.assert_allclose(mapas._normalizar_densidad((w @ k).reshape(X.shape)),
                               Z_scipy, atol=2e-12, rtol=0)
    inv = np.linalg.inv(cov)
    for p in rng.poisson(1, (12, len(x))) * w:
        antigua = np.zeros_like(X)
        for xi, yi, wi in zip(x, y, p):
            dx, dy = X - xi, Y - yi
            antigua += wi * np.exp(-0.5 * (inv[0, 0] * dx * dx
                                           + 2 * inv[0, 1] * dx * dy + inv[1, 1] * dy * dy))
        np.testing.assert_allclose(mapas._normalizar_densidad((p @ k).reshape(X.shape)),
                                   mapas._normalizar_densidad(antigua), atol=2e-12, rtol=0)


def _invariantes(r, xlims, ylims):
    _, _, Z = r["malla"]
    assert np.isfinite(Z).all() and 0 <= Z.min() and Z.max() == 100
    cajas = []
    for isla in r["regiones"]:
        caja = (isla["lmin"], isla["lmax"], math.log10(isla["m_min"]), math.log10(isla["m_max"]))
        lo, hi, ylo, yhi = caja
        assert xlims[0] - 1e-12 <= lo < hi <= xlims[1] + 1e-12
        assert ylims[0] - 1e-12 <= ylo < yhi <= ylims[1] + 1e-12
        assert min(isla["s_min"], isla["s_max"], isla["sm_min"], isla["sm_max"]) > 0
        assert 0 <= isla["n_validas"] <= r["diagnostico"]["evaluadas"]
        assert all(not mapas._cajas_solapadas(caja, otra) for otra in cajas)
        cajas.append(caja)


def test_solar_y_colas():
    d = mapas.construir_sistema_solar().sort_values("Distancia_UA")
    x = d["Distancia_UA"].to_numpy()
    y = np.log10(d["Masa_Tierra"].to_numpy())
    limx, limy = mapas.LIM_SISTEMA_SOLAR_X, (y.min() - 0.5, y.max() + 0.5)
    r = mapas.calcular_kde_panel(d, limx, limy, n_bootstrap=160,
                                 nivel_min_pico=10, unidad_bootstrap="planetas_solares")
    assert len(r["regiones"]) == 2
    X, Y, Z = r["malla"]
    interp = RegularGridInterpolator((X[:, 0], Y[0, :]), Z)
    j = float(interp((np.log10(x[4]), y[4])))
    assert j == pytest.approx(96.7296200203, abs=0.01)
    limites = [[q["a_min"], q["a_max"]] for q in r["regiones"]]
    np.testing.assert_allclose(limites, [[0.38, 1.69], [4.27, 7.81]], atol=0.03)
    _invariantes(r, limx, limy)
    assert mapas._intervalo_sigma(np.ones(5337), 3, metodo="percentil") is None
    assert mapas._intervalo_sigma(np.ones(8000), 3, metodo="percentil") is not None
    assert mapas._intervalo_sigma(np.ones(200), 3, metodo="std", piso=0.1) == pytest.approx((0.7, 1.3))


def test_estilos_leyendas_y_cierre(tmp_path, monkeypatch):
    estilos = mapas._asignar_estilos_sistema(pd.DataFrame({"Sistema": [str(i) for i in range(310)]}))
    assert len(estilos) == len({s["ls"] for s in estilos.values()}) == 310
    raiz = Path(__file__).resolve().parent.parent / "Troyanos"
    if not raiz.is_dir():
        pytest.skip("Para esta figura se usa la lista real de sistemas F")
    d, _ = mapas.extraer_datos_personalizados(raiz / "Resultados_Estrellas_F")
    comprobadas = []

    def verificar(fig, *rutas):
        fig.canvas.draw()
        motor = fig.canvas.get_renderer()
        for ax in fig.axes:
            leyenda = ax.get_legend()
            if leyenda is None:
                continue
            caja = leyenda.get_window_extent(motor)
            assert caja.y1 < ax.xaxis.label.get_window_extent(motor).y0
            area = fig.get_tightbbox(motor).transformed(fig.dpi_scale_trans)
            assert area.x0 <= caja.x0 <= caja.x1 <= area.x1 + 1e-8
            assert area.y0 <= caja.y0 + 1e-8 <= caja.y1 <= area.y1 + 1e-8
            comprobadas.append(leyenda)
        mapas._mostrar_o_cerrar(fig)

    monkeypatch.setattr(mapas, "_guardar_figura", verificar)
    with mapas._configurar(mapas.ConfiguracionKDE(replicas=0, replicas_solar=0, malla=75),
                            mapas.ConfiguracionSalida(cache=False)):
        mapas.plot_tipos_espectrales_fila(d, tmp_path, tipos=("F",))
        mapas.analizar_kde_sistema_solar(base_dir=tmp_path)
    assert len(comprobadas) == 2
    assert not plt.get_fignums()


def test_codigo_notebook_identico_y_sin_salidas():
    raiz = Path(mapas.__file__).parent
    nb = json.loads((raiz / "Final_corregido.ipynb").read_text(encoding="utf-8"))
    bloques = ["".join(c["source"]) for c in nb["cells"] if c.get("id", "").startswith("codigo-")]
    fuente = Path(mapas.__file__).read_text(encoding="utf-8")
    assert ast.dump(ast.parse("\n\n".join(bloques))) == ast.dump(ast.parse(fuente))
    assert all(c["outputs"] == [] and c["execution_count"] is None
               for c in nb["cells"] if c["cell_type"] == "code")


def test_regresion_nominal_con_codigo_original():
    ruta = Path(mapas.__file__).with_name("Final.ipynb")
    raiz = ruta.parent.parent / "Troyanos"
    if not ruta.is_file() or not raiz.is_dir():
        pytest.skip("La regresión requiere Final.ipynb y el catálogo local")
    celdas = json.loads(ruta.read_text(encoding="utf-8"))["cells"]
    original = {}
    for c in celdas[:-1]:
        if c["cell_type"] == "code":
            codigo = "\n".join(l for l in "".join(c["source"]).splitlines()
                               if not l.startswith(("import tkinter", "from tkinter")))
            exec(compile(codigo, str(ruta), "exec"), original)
    original.update(USAR_CACHE_KDE=False, tqdm=lambda valores, **kw: valores)
    d, _ = mapas.extraer_datos_personalizados(raiz)
    limites = mapas._limites_estrellas(d)
    for tipo, n in mapas.REGIONES_FILA.items():
        datos = d[d.Tipo_Estrella == tipo]
        antes = original["calcular_kde_panel"](datos, *limites, n_bootstrap=1, n_regiones=n)
        despues = mapas.calcular_kde_panel(datos, *limites, n_bootstrap=1, n_regiones=n)
        np.testing.assert_allclose(antes["malla"][2], despues["malla"][2], atol=2e-12, rtol=0)
        ca = _centros(antes)
        cd = _centros(despues)
        np.testing.assert_allclose(ca, cd, atol=1e-10, rtol=0)


MEDIAS = np.array([[-1.15, -0.65], [1.15, 0.65]])
DESVIACIONES = np.array([0.18, 0.15])
EXTENSIONES = ((-1.85, 1.85), (-1.32, 1.32))
CFG_MEZCLA = mapas.ConfiguracionKDE(bw=0.16, malla=101, niveles_por_altura=False,
                                    piso_celdas=0.5)


def _mezcla(rng, n):
    grupos = rng.integers(0, 2, size=n)
    return rng.normal(size=(n, 2)) * DESVIACIONES + MEDIAS[grupos]


def _verdad():
    # La densidad de población convolucionada se conoce exactamente. El nivel es 90.9 %
    # de cada pico. La evaluación en malla fina hace despreciable el error de la referencia.
    X, Y = mapas._malla(*EXTENSIONES, 601)
    coords = np.stack([X, Y], axis=-1)
    local = np.diag(DESVIACIONES ** 2)
    semidif = (MEDIAS[1] - MEDIAS[0]) / 2
    cov = local + CFG_MEZCLA.bw ** 2 * (local + np.outer(semidif, semidif))
    densidad = sum(multivariate_normal.pdf(coords, mu, cov) for mu in MEDIAS) / 2
    with mapas._configurar(CFG_MEZCLA):
        islas = mapas._regiones_por_picos(mapas._normalizar_densidad(densidad), X, Y, n_max=2)
    assert len(islas) == 2
    # Validación independiente por las proyecciones analíticas de ambas elipses.
    dx, dy = np.sqrt(-2 * math.log(0.909) * np.diag(cov))
    analitico = np.array([[x - dx, x + dx, y - dy, y + dy] for x, y in MEDIAS])
    limites = np.array([r.limites for r in islas])
    np.testing.assert_allclose(limites, analitico, atol=0.009, rtol=0)
    return 10 ** analitico


def _centros(r):
    return np.array([[isla[k] for k in ("a_min", "a_max", "m_min", "m_max")] for isla in r["regiones"]])


def _centros_y_errores(r):
    errores = [[isla[k] for k in ("s_min", "s_max", "sm_min", "sm_max")] for isla in r["regiones"]]
    return _centros(r), np.array(errores)


def test_dos_islas_con_respuesta_conocida():
    verdad = _verdad()
    q = norm.ppf((np.arange(15) + 0.5) / 15)
    reticula = np.column_stack([e.ravel() for e in np.meshgrid(q, q)])
    puntos = np.concatenate([reticula * DESVIACIONES / q.std() + mu for mu in MEDIAS])
    with mapas._configurar(CFG_MEZCLA):
        r = mapas.calcular_kde_panel(_tabla(puntos), *EXTENSIONES,
                                     n_bootstrap=220, n_regiones=2)
    assert len(r["regiones"]) == 2
    _invariantes(r, *EXTENSIONES)
    centros, errores = _centros_y_errores(r)
    assert np.all(abs(centros - verdad) <= errores), (centros, errores, verdad)


def test_cobertura_sintetica():
    verdad = _verdad()
    rng = np.random.default_rng(81031)
    aciertos = np.zeros((2, 4))
    n_catalogos = 44
    for i in range(n_catalogos):
        cfg = replace(CFG_MEZCLA, semilla=mapas.SEMILLA_BOOTSTRAP + i)
        with mapas._configurar(cfg):
            r = mapas.calcular_kde_panel(_tabla(_mezcla(rng, 180)), *EXTENSIONES,
                                         n_bootstrap=150, n_regiones=2)
        if len(r["regiones"]) == 2:
            centros, errores = _centros_y_errores(r)
            aciertos += abs(centros - verdad) <= errores
    tasas = aciertos / n_catalogos
    print("Cobertura 1σ por isla y límite [a_min, a_max, m_min, m_max]:", tasas.tolist())
    print(f"Cobertura media: {tasas.mean():.4f} sobre {n_catalogos} catálogos")
    # El catálogo es la unidad independiente; los ocho bordes de cada uno son correlacionados.
    sem_error_max = 0.5 / math.sqrt(n_catalogos)
    assert abs(tasas.mean() - (norm.cdf(1) - norm.cdf(-1))) <= 1.96 * sem_error_max
