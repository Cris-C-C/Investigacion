import os
import warnings
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import minimize
import phoebe
from phoebe import u

# Silenciar avisos numéricos repetitivos
warnings.filterwarnings("ignore", message="invalid value encountered in subtract")
warnings.filterwarnings("ignore", message="divide by zero encountered")
phoebe.logger(clevel="ERROR")  # Evita inundar la consola con arrays gigantes

# =====================================================================
# 1. ÚNICOS PARÁMETROS CONOCIDOS A PRIORI
# =====================================================================
PERIODO_FIJO = 3.6788        # Periodo orbital conocido [días]
TEFF1_FIJA   = 25700.0       # Temperatura efectiva de la primaria FIJA [K]
M1_REF_MSUN  = 11.0          # Masa típica de una B1V (25700 K) -> mantiene logg > 3.7

# Factor de llenado de la secundaria: 0.995 = llena el lóbulo de Roche (semi-separada)
# sin tocar la singularidad matemática exacta de L1 que rompe el mallador C++ de PHOEBE.
ROCHE_FILL_SEC = 0.995

# =====================================================================
# CONFIGURACIÓN DE ARCHIVOS
# =====================================================================
BASE_DIR = os.getcwd()
OUT_DIR = os.path.join(BASE_DIR, "Resultados_TYC6265_Fase1")
os.makedirs(OUT_DIR, exist_ok=True)

_CARPETAS = [
    "C:/Users/darkm/Desktop/archivos_Investigación/PHOEBE",
    "C:/Users/darkm/Desktop/archivos_Investigación/Investigacion/PHOEBE",
    BASE_DIR,
]

def find_file(nombre):
    for c in _CARPETAS:
        p = os.path.join(c, nombre)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"No encuentro '{nombre}' en: {_CARPETAS}")

FILE_R = "TYC_6265_2079_flujo_r.txt"
FILE_I = "TYC_6265_2079_flujo_i.txt"

N_COMPUTE_PHASES = 101
MAXITER_SPHERE   = 90
MAXITER_ROCHE    = 100

PHASES_MESH = [0.0, 0.25, 0.5, 0.75]
MESH_COLOR  = "royalblue"
MESH_EDGE   = "black"

# =====================================================================
# 2. ESTIMACIÓN ANALÍTICA DESDE LA CURVA DE LUZ
# =====================================================================
def load(path):
    try:
        d = np.genfromtxt(path, delimiter=None, skip_header=1, encoding="utf-8")
    except Exception:
        d = np.genfromtxt(path, delimiter=None, skip_header=1, encoding="latin1")

    if d.ndim != 2 or d.shape[1] < 3:
        raise ValueError(f"El archivo {path} no tiene al menos 3 columnas (tiempo, flujo, error).")

    t, f, e = d[:, 0], d[:, 1], d[:, 2]
    malos = ~(np.isfinite(t) & np.isfinite(f) & np.isfinite(e) & (e > 0) & (f > 0))
    if malos.any():
        print(f"   AVISO {os.path.basename(path)}: {int(malos.sum())} filas inválidas descartadas.")
        t, f, e = t[~malos], f[~malos], e[~malos]

    idx = np.argsort(t)
    return t[idx], f[idx], e[idx]

def eggleton_rl(q):
    """Radio equivalente fraccional del lóbulo de Roche R_L(q)/a según Eggleton (1983)."""
    q = max(1e-4, float(q))
    q13 = q ** (1.0 / 3.0)
    q23 = q13 * q13
    return (0.49 * q23) / (0.6 * q23 + np.log(1.0 + q13))

def analizar_morfologia_curva(t, f, P):
    """Extrae t0, T2/T1, (R1+R2)/a e inclinación directamente de la curva observada."""
    t_ref = float(np.median(t))
    fase_raw = ((t - t_ref) / P) % 1.0

    nbins = 50
    edges = np.linspace(0.0, 1.0, nbins + 1)
    centros = 0.5 * (edges[:-1] + edges[1:])
    f_bin = np.full(nbins, np.nan)
    for i in range(nbins):
        m = (fase_raw >= edges[i]) & (fase_raw < edges[i + 1])
        if np.any(m):
            f_bin[i] = np.median(f[m])

    valid = np.isfinite(f_bin)
    f_bin = np.interp(centros, centros[valid], f_bin[valid])

    phi_min1 = centros[np.argmin(f_bin)]
    dfase = ((fase_raw - phi_min1 + 0.5) % 1.0) - 0.5
    pts_min = np.abs(dfase) < 0.025
    if np.sum(pts_min) >= 3:
        pesos = (np.max(f[pts_min]) - f[pts_min]) + 1e-6
        delta_phi = np.sum(dfase[pts_min] * pesos) / np.sum(pesos)
        phi_min1 = (phi_min1 + delta_phi) % 1.0

    t0_est = t_ref + phi_min1 * P

    fase = ((t - t0_est) / P) % 1.0
    m_quad = (np.abs(fase - 0.25) < 0.06) | (np.abs(fase - 0.75) < 0.06)
    f_max = np.percentile(f[m_quad], 75) if np.any(m_quad) else np.percentile(f, 90)

    m_pri = (fase < 0.03) | (fase > 0.97)
    m_sec = np.abs(fase - 0.50) < 0.03
    f_min1 = np.percentile(f[m_pri], 15) if np.any(m_pri) else np.min(f)
    f_min2 = np.percentile(f[m_sec], 15) if np.any(m_sec) else np.median(f)

    d1 = np.clip((f_max - f_min1) / f_max, 0.02, 0.95)
    d2 = np.clip((f_max - f_min2) / f_max, 0.01, d1 * 0.98)

    if f_min2 < f_min1:
        t0_est += 0.5 * P
        d1, d2 = d2, d1

    teffratio_est = float(np.clip((d2 / d1) ** 0.28, 0.42, 0.92))

    umbral_eclipse = f_max - 0.15 * (f_max - f_min1)
    m_ancho = ((fase < 0.20) | (fase > 0.80)) & (f < umbral_eclipse)
    if np.any(m_ancho):
        fases_ec = np.where(fase[m_ancho] > 0.5, fase[m_ancho] - 1.0, fase[m_ancho])
        semi_ancho = np.clip(np.percentile(np.abs(fases_ec), 90), 0.05, 0.18)
    else:
        semi_ancho = 0.11
    rsum_est = float(np.clip(np.sin(2.0 * np.pi * semi_ancho), 0.38, 0.62))
    incl_est = float(np.clip(65.0 + 22.0 * np.sqrt(d1), 65.0, 86.0))

    print("\n   [Diagnóstico fotométrico automático de la curva de luz]")
    print(f"   -> t0_supconj detectado  : {t0_est:.5f} d")
    print(f"   -> Profundidad Ecl. Prim.: {d1*100:.1f}% | Ecl. Sec.: {d2*100:.1f}%")
    print(f"   -> T2/T1 estimado        : {teffratio_est:.3f} (T2 ~ {teffratio_est*TEFF1_FIJA:.0f} K)")
    print(f"   -> (R1+R2)/a estimado    : {rsum_est:.3f}")
    print(f"   -> Inclinación estimada  : {incl_est:.1f} deg")

    return {
        "t0": t0_est,
        "teffratio": teffratio_est,
        "rsum": rsum_est,
        "incl": incl_est,
    }

# =====================================================================
# 3. GESTIÓN FÍSICA AUTOCONSISTENTE DEL SISTEMA SEMI-SEPARADO
# =====================================================================
def set_estado_semiseparado(b, incl, q, teffratio, r1_over_a):
    """
    Aplica (incl, q, teffratio, R1/a) imponiendo la condición semi-separada:
      - T1 queda fija en TEFF1_FIJA (25700 K)
      - T2 = teffratio * TEFF1_FIJA
      - R2/a = ROCHE_FILL_SEC * R_L2(q) (llena el lóbulo al 99.5% sin colapsar en L1)
      - R1/a queda acotado a <= 0.85 * R_L1(q) para no desbordar nunca la primaria
    """
    q = float(np.clip(q, 0.12, 0.95))
    incl = float(np.clip(incl, 50.0, 89.8))
    teffratio = float(np.clip(teffratio, 0.30, 0.99))

    m_tot = M1_REF_MSUN * (1.0 + q)
    sma = 4.208278 * (m_tot * (PERIODO_FIJO ** 2)) ** (1.0 / 3.0)

    rl2_a = eggleton_rl(q)               # Lóbulo secundario R_L2 / a
    rl1_a = eggleton_rl(1.0 / q)         # Lóbulo primario   R_L1 / a

    r2_a = ROCHE_FILL_SEC * rl2_a
    r1_a = float(np.clip(r1_over_a, 0.06, 0.85 * rl1_a))

    b["incl@binary@component"]      = incl * u.deg
    b["q@binary@component"]         = q
    b["sma@binary@component"]       = sma * u.solRad
    b["teff@primary@component"]     = TEFF1_FIJA * u.K
    b["teff@secondary@component"]   = (TEFF1_FIJA * teffratio) * u.K
    b["requiv@primary@component"]   = (r1_a * sma) * u.solRad
    b["requiv@secondary@component"] = (r2_a * sma) * u.solRad

def chi2_red(b, compute, tag="eval_mod", n_params=4):
    """Evalúa chi2/dof de forma 100% segura."""
    try:
        b.run_compute(compute=compute, model=tag, overwrite=True)
    except Exception:
        return np.inf

    chi2, n = 0.0, 0
    for ds in ["lc01", "lc02"]:
        f = np.asarray(b.get_value("fluxes", dataset=ds, context="dataset"), float)
        s = np.asarray(b.get_value("sigmas", dataset=ds, context="dataset"), float)
        m = np.asarray(b.get_value("fluxes", dataset=ds, model=tag, context="model"), float)
        if len(m) != len(f):
            t_obs = np.asarray(b.get_value("times", dataset=ds, context="dataset"), float)
            t_mod = np.asarray(b.get_value("times", dataset=ds, model=tag, context="model"), float)
            m = np.interp(t_obs, t_mod, m)
        if not np.all(np.isfinite(m)) or np.all(m == 0):
            return np.inf
        k = np.sum(m * f) / np.sum(m * m)
        chi2 += float(np.sum(((f - k * m) / s) ** 2))
        n += len(f)

    return chi2 / max(1, n - n_params)

def build_bundle():
    print("1. Cargando datos fotométricos y analizando morfología...")
    t_r, f_r, e_r = load(find_file(FILE_R))
    t_i, f_i, e_i = load(find_file(FILE_I))

    est = analizar_morfologia_curva(t_r, f_r, PERIODO_FIJO)

    b = phoebe.default_binary()
    b.add_dataset("lc", times=t_r, fluxes=f_r, sigmas=e_r, passband="SDSS:r", dataset="lc01")
    b.add_dataset("lc", times=t_i, fluxes=f_i, sigmas=e_i, passband="SDSS:i", dataset="lc02")

    fases_computo = np.linspace(0.0, 1.0, N_COMPUTE_PHASES)
    for ds in ["lc01", "lc02"]:
        try:
            b.set_value("compute_phases", dataset=ds, value=fases_computo)
        except Exception:
            pass

    b["period@binary"]     = PERIODO_FIJO * u.day
    b["t0_supconj@binary"] = est["t0"] * u.day
    b["ecc@binary"]        = 0.0

    # SOLUCIÓN AL CRASH DE CK2004 (Teff > 26000 K con logg < 3.50):
    # Fijar atm='blackbody' y ld_mode='manual' (con ley logarítmica para estrellas B)
    # evita que cualquier vértice deformado de la malla dispare ValueError en ldint.
    b.set_value_all("atm", "blackbody")
    b.set_value_all("ld_mode", "manual")
    b.set_value_all("ld_func", "logarithmic")
    b.set_value_all("ld_coeffs", [0.42, 0.25])
    b.set_value_all("ld_mode_bol", "manual")
    b.set_value_all("ld_func_bol", "logarithmic")
    b.set_value_all("ld_coeffs_bol", [0.50, 0.25])

    b.set_value_all("gravb_bol", 1.0)
    b.set_value_all("irrad_frac_refl_bol", 1.0)
    b.set_value_all("pblum_mode", "dataset-scaled")

    b.add_compute("phoebe", compute="optim_compute", irrad_method="none",
                  distortion_method="sphere", ntriangles=800)
    b.add_compute("phoebe", compute="optim_roche", irrad_method="none",
                  distortion_method="roche", ntriangles=1200)
    b.add_compute("phoebe", compute="final_compute", irrad_method="horvat",
                  distortion_method="roche", ntriangles=2000)

    # 2. Barrido en rejilla (q-search) sobre geometría de Roche real
    print("\n2. Buscando la mejor semilla inicial en rejilla de Roche (q-search)...")
    q_grid = [0.22, 0.30, 0.40, 0.50, 0.62, 0.75]
    incl_offsets = [-3.5, 0.0, +3.5]

    mejor_chi2 = np.inf
    mejor_semilla = None

    for q_try in q_grid:
        r2a_try = ROCHE_FILL_SEC * eggleton_rl(q_try)
        r1a_try = float(np.clip(est["rsum"] - r2a_try, 0.12, 0.30))
        for d_inc in incl_offsets:
            inc_try = float(np.clip(est["incl"] + d_inc, 58.0, 88.0))
            set_estado_semiseparado(b, inc_try, q_try, est["teffratio"], r1a_try)
            c = chi2_red(b, "optim_roche", "grid_chk", n_params=4)
            if c < mejor_chi2:
                mejor_chi2 = c
                mejor_semilla = (inc_try, q_try, est["teffratio"], r1a_try)

    inc0, q0, tr0, r1a0 = mejor_semilla
    set_estado_semiseparado(b, inc0, q0, tr0, r1a0)
    print(f"   [Mejor Semilla Inicial]: incl={inc0:.2f} deg, q={q0:.3f}, "
          f"T2/T1={tr0:.3f} (T2={tr0*TEFF1_FIJA:.0f} K), R1/a={r1a0:.3f} -> chi2/dof={mejor_chi2:.2f}")

    return b, [inc0, q0, tr0, r1a0]

# =====================================================================
# 4. OPTIMIZACIÓN DIRECTA CON CONTROL ESTRICTO DEL LÓBULO DE ROCHE
# =====================================================================
def optimize(b, semilla):
    """
    Optimiza en dos etapas acoplando R2 = 0.995 * R_L2(q) en cada evaluación.
    De esta manera q varía libremente manteniendo la geometría semi-separada
    sin que el mallador C++ colapse jamás en L1.
    """
    inc0, q0, tr0, r1a0 = semilla

    # --- ETAPA 1: Esferas rápidas (ajusta incl, teffratio, R1/a con q=q0) ---
    print(f"\n3a. Etapa 1 - Ajuste rápido en esferas ({MAXITER_SPHERE} max evals)...")
    it1 = [0]
    best1 = [np.inf]

    def obj_stage1(x):
        inc, tr, r1a = x
        if not (50.0 <= inc <= 89.8 and 0.32 <= tr <= 0.98 and 0.07 <= r1a <= 0.36):
            return 1e9
        set_estado_semiseparado(b, inc, q0, tr, r1a)
        c = chi2_red(b, "optim_compute", "mod_s1", n_params=3)
        it1[0] += 1
        if c < best1[0]:
            best1[0] = c
            print(f"      [Etapa 1 - eval {it1[0]:3d}] Nuevo mejor chi2/dof = {c:.3f} "
                  f"(incl={inc:.2f}°, T2={tr*TEFF1_FIJA:.0f} K, R1/a={r1a:.4f})")
        return c if np.isfinite(c) else 1e9

    x0_s1 = np.array([inc0, tr0, r1a0], dtype=float)
    simplex_s1 = np.vstack([
        x0_s1,
        x0_s1 + np.array([2.0, 0.0, 0.0]),
        x0_s1 + np.array([0.0, 0.04, 0.0]),
        x0_s1 + np.array([0.0, 0.0, 0.02]),
    ])
    res1 = minimize(obj_stage1, x0_s1, method="Nelder-Mead",
                    options={"maxfev": MAXITER_SPHERE, "initial_simplex": simplex_s1,
                             "xatol": 1e-3, "fatol": 1e-3})
    inc1, tr1, r1a1 = res1.x

    # --- ETAPA 2: Geometría de Roche real (libera q junto con incl, T2/T1 y R1/a) ---
    print(f"\n3b. Etapa 2 - Refinamiento en Geometría de Roche con q libre ({MAXITER_ROCHE} max evals)...")
    it2 = [0]
    best2 = [np.inf]

    def obj_stage2(x):
        inc, q, tr, r1a = x
        rl1_max = 0.85 * eggleton_rl(1.0 / max(0.15, q))
        if not (50.0 <= inc <= 89.8 and 0.15 <= q <= 0.92 and 0.32 <= tr <= 0.98 and 0.07 <= r1a <= rl1_max):
            return 1e9
        set_estado_semiseparado(b, inc, q, tr, r1a)
        c = chi2_red(b, "optim_roche", "mod_s2", n_params=4)
        it2[0] += 1
        if c < best2[0]:
            best2[0] = c
            print(f"      [Etapa 2 - eval {it2[0]:3d}] Nuevo mejor chi2/dof = {c:.3f} "
                  f"(incl={inc:.2f}°, q={q:.4f}, T2={tr*TEFF1_FIJA:.0f} K, R1/a={r1a:.4f})")
        return c if np.isfinite(c) else 1e9

    x0_s2 = np.array([inc1, q0, tr1, r1a1], dtype=float)
    simplex_s2 = np.vstack([
        x0_s2,
        x0_s2 + np.array([1.5, 0.0, 0.0, 0.0]),
        x0_s2 + np.array([0.0, 0.06, 0.0, 0.0]),
        x0_s2 + np.array([0.0, 0.0, 0.03, 0.0]),
        x0_s2 + np.array([0.0, 0.0, 0.0, 0.015]),
    ])
    res2 = minimize(obj_stage2, x0_s2, method="Nelder-Mead",
                    options={"maxfev": MAXITER_ROCHE, "initial_simplex": simplex_s2,
                             "xatol": 1e-3, "fatol": 1e-3})

    inc_f, q_f, tr_f, r1a_f = res2.x
    set_estado_semiseparado(b, inc_f, q_f, tr_f, r1a_f)
    print(f"-> Optimización finalizada con éxito (chi2/dof final en Roche = {best2[0]:.3f}).")

# =====================================================================
# 5. RESULTADOS, GRÁFICAS Y DICCIONARIO DE PARÁMETROS ÓPTIMOS
# =====================================================================
def dibujar_mesh(b):
    print("4. Generando gráficos de las estrellas (Mesh)...")
    P = b.get_value("period@binary", context="component")
    t0 = b.get_value("t0_supconj@binary", context="component")
    bm = b.copy()
    for ds in ["lc01", "lc02"]:
        try:
            bm.disable_dataset(ds)
        except Exception:
            pass

    times_mesh = [t0 + ph * P for ph in PHASES_MESH]
    try:
        bm.add_dataset("mesh", compute_times=times_mesh, dataset="mesh01", columns=["teffs", "loggs"])
    except Exception:
        bm.add_dataset("mesh", times=times_mesh, dataset="mesh01", columns=["teffs", "loggs"])

    try:
        bm.run_compute(compute="final_compute", model="mesh_model", overwrite=True)
        estilo = dict(fc=MESH_COLOR, ec=MESH_EDGE, show=False)
        for ph, t in zip(PHASES_MESH, times_mesh):
            plt.figure(figsize=(6, 6))
            bm.plot(model="mesh_model", dataset="mesh01", time=t, **estilo,
                    save=os.path.join(OUT_DIR, f"mesh_fase{ph}.png"))
            plt.close("all")
    except Exception as e:
        print(f"   (!) No se pudo generar el gráfico de malla: {e}")

def fase1_verificar(b):
    print("5. Calculando curvas finales en todos los tiempos observados...")
    for ds in ["lc01", "lc02"]:
        try:
            b.set_value("compute_phases", dataset=ds, value=[])
        except Exception:
            pass

    try:
        b.run_compute(compute="final_compute", model="check_final", overwrite=True)
        modelo_final = "check_final"
    except Exception:
        b.run_compute(compute="optim_roche", model="check_final_roche", overwrite=True)
        modelo_final = "check_final_roche"

    chi2_fin = chi2_red(b, "optim_roche", "check_chi2_fin", n_params=4)

    plt.figure(figsize=(8, 5))
    b.plot(dataset=["lc01", "lc02"], model=modelo_final, x="phases", show=False, legend=True,
           save=os.path.join(OUT_DIR, "ajuste_final.png"))
    plt.close("all")

    plt.figure(figsize=(8, 4))
    b.plot(model=modelo_final, kind="lc", x="phases", y="residuals", show=False, legend=True, marker=".",
           save=os.path.join(OUT_DIR, "residuos_final.png"))
    plt.close("all")

    g = lambda tw: b.get_value(tw, context="component")
    P, t0 = g("period@binary"), g("t0_supconj@binary")
    incl, q = g("incl@binary"), g("q@binary")
    sma = g("sma@binary")
    R1, R2 = g("requiv@primary"), g("requiv@secondary")
    RL1, RL2 = g("requiv_max@primary"), g("requiv_max@secondary")
    T1, T2 = g("teff@primary"), g("teff@secondary")
    tratio = T2 / T1
    M1, M2 = g("mass@primary"), g("mass@secondary")

    texto = f"""===================================================================
ESTIMACIÓN ÓPTIMA DE PARÁMETROS (TYC 6265-2079-1 - SEMI-SEPARADO)
===================================================================
Parámetros de entrada fijos:
  Periodo orbital (P)        = {P:.6f} d
  Teff primaria (T1)         = {T1:.0f} K

Parámetros óptimos estimados de la curva de luz (chi2/dof = {chi2_fin:.3f}):
  t0_supconj                 = {t0:.6f} d
  Inclinación (incl)         = {incl:.3f} deg
  Razón de masas (q = M2/M1) = {q:.4f}
  Teff secundaria (T2)       = {T2:.0f} K   (T2/T1 = {tratio:.4f})
  Radio relativo R1/a        = {R1/sma:.4f}  (R1 = {R1:.2f} Rsun)
  Radio relativo R2/a        = {R2/sma:.4f}  (R2 = {R2:.2f} Rsun, llena L2 al {ROCHE_FILL_SEC*100:.1f}%)
  Suma fraccional (R1+R2)/a  = {(R1+R2)/sma:.4f}
  Factor de llenado          = R1/RL1 = {R1/RL1:.3f} , R2/RL2 = {R2/RL2:.3f}
  Escala orbital de ref.     = a = {sma:.2f} Rsun (M1={M1:.2f} Msun, M2={M2:.2f} Msun)

Bloque listo para copiar como semillas iniciales:
-------------------------------------------------------------------
PARAMS_INICIALES = {{
    "period": {P:.6f},
    "t0_supconj": {t0:.6f},
    "incl": {incl:.3f},
    "q": {q:.4f},
    "teff1": {T1:.1f},
    "teff2": {T2:.1f},
    "teffratio": {tratio:.4f},
    "r1_over_a": {R1/sma:.4f},
    "r2_over_a": {R2/sma:.4f},
    "requivsumfrac": {(R1+R2)/sma:.4f},
    "requiv1_rsun": {R1:.3f},
    "requiv2_rsun": {R2:.3f},
    "sma_rsun": {sma:.3f},
}}
"""
    print(f"\n{texto}")
    with open(os.path.join(OUT_DIR, "resultados.txt"), "w", encoding="utf-8") as f:
        f.write(texto)

    dibujar_mesh(b)
    bundle_path = os.path.join(OUT_DIR, "TYC6265_semiseparado.bundle")
    b.save(bundle_path)
    print(f"¡Proceso exitoso! Resultados y figuras guardados en: {OUT_DIR}")

if __name__ == "__main__":
    print("=" * 65)
    print("ESTIMADOR AUTOMÁTICO DE PARÁMETROS INICIALES (P y Teff1 fijos)")
    print("=" * 65)

    b, semilla = build_bundle()
    optimize(b, semilla)
    fase1_verificar(b)