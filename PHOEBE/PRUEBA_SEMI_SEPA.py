import os
import time
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import phoebe
from phoebe import u

# =====================================================================
# CONFIGURACIÓN
# =====================================================================
BASE_DIR = os.getcwd()
OUT_DIR = os.path.join(BASE_DIR, "Resultados_TYC6265_Fase1")
os.makedirs(OUT_DIR, exist_ok=True)

_CARPETAS = [
    "C:/Users/darkm/Desktop/archivos_Investigación/PHOEBE",
    BASE_DIR,
]

def find_file(nombre):
    for c in _CARPETAS:
        p = os.path.join(c, nombre)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"No encuentro {nombre} en: {_CARPETAS}")

FILE_R = "TYC_6265_2079_flujo_r.txt"
FILE_I = "TYC_6265_2079_flujo_i.txt"

# Desactivamos EBAI porque suele fallar al estimar sistemas en contacto/semi-separados
USE_EBAI = False 
DISTORTION = "sphere"

PHASES_MESH = [0.0, 0.25, 0.5, 0.75]
MESH_COLOR  = "royalblue"
MESH_EDGE   = "black"

# Parámetros a optimizar (sin requivratio, ya que la secundaria está fijada a su lóbulo)
FIT_PARAMETERS = [
    "t0_supconj@binary",
    "period@binary",
    "incl@binary",
    "teff@primary",
    "teffratio@binary",
    "requivsumfrac@binary",
]

# =====================================================================
# CONSTRUCCIÓN DEL MODELO
# =====================================================================
def load(path):
    d = np.genfromtxt(path, delimiter=None, skip_header=1, encoding="latin1")
    return d[:, 0], d[:, 1], d[:, 2]

def build_bundle():
    print("1. Cargando datos fotométricos...")
    t_r, f_r, e_r = load(find_file(FILE_R))
    t_i, f_i, e_i = load(find_file(FILE_I))

    b = phoebe.default_binary()
    b.add_dataset("lc", times=t_r, fluxes=f_r, sigmas=e_r, passband="SDSS:r", dataset="lc01")
    b.add_dataset("lc", times=t_i, fluxes=f_i, sigmas=e_i, passband="SDSS:i", dataset="lc02")

    # Valores iniciales
    b["period@binary"] = 3.6788 * u.day
    b["t0_supconj@binary"] = t_r[0] * u.day
    b["incl@binary"] = 70.0 * u.deg
    b["q@binary"] = 0.5
    b["teff@primary"] = 25700 * u.K
    b["teff@secondary"] = 20000 * u.K
    b["ecc@binary"] = 0.0

    b.set_value_all("atm", "ck2004")
    b.set_value_all("ld_mode", "interp")
    b.set_value_all("ld_mode_bol", "manual")
    b.set_value_all("gravb_bol", 1.0)
    b.set_value_all("irrad_frac_refl_bol", 1.0)
    b.set_value_all("pblum_mode", "dataset-scaled")
    b.set_value_all("irrad_method", "horvat")

    print("2. Aplicando topología semi-separada (Algol)...")
    # ANCLAJE CORRECTO: La estrella secundaria llena su lóbulo de Roche
    b.add_constraint('requiv@secondary', 'requiv_max@secondary', solve_for='requiv@secondary')
    
    # La fracción de radios controla ahora únicamente el tamaño de la primaria
    b.flip_constraint("requivsumfrac", solve_for="requiv@primary")
    b.flip_constraint("teffratio", solve_for="teff@secondary")

    # Valor inicial conservador
    b["requivsumfrac@binary"] = 0.45

    b.add_compute("phoebe", compute="optim_compute", irrad_method="none", distortion_method=DISTORTION)
    b.add_compute("phoebe", compute="final_compute", irrad_method="horvat", distortion_method="roche")
    return b

def optimize(b):
    print("3. Iniciando optimización Nelder-Mead (Esto puede tardar unos minutos)...")
    # maxiter=150 evita bucles infinitos. Si no converge, al menos se detiene y te da un resultado.
    b.add_solver("optimizer.nelder_mead", solver="opt_nm", compute="optim_compute",
                 fit_parameters=FIT_PARAMETERS, maxiter=150)
    b.run_solver("opt_nm", solution="opt_nm_sol", lc_datasets=["lc01", "lc02"])
    b.adopt_solution("opt_nm_sol")
    print("-> Optimización finalizada.")

# =====================================================================
# RESULTADOS Y GRÁFICAS
# =====================================================================
def dibujar_mesh(b):
    print("4. Generando gráficos de las estrellas (Mesh)...")
    P = b.get_value("period@binary", context="component")
    t0 = b.get_value("t0_supconj@binary", context="component")
    bm = b.copy()
    for ds in ["lc01", "lc02"]:
        try: bm.disable_dataset(ds)
        except Exception: pass

    times_mesh = [t0 + ph * P for ph in PHASES_MESH]
    try: bm.add_dataset("mesh", compute_times=times_mesh, dataset="mesh01", columns=["teffs", "loggs"])
    except Exception: bm.add_dataset("mesh", times=times_mesh, dataset="mesh01", columns=["teffs", "loggs"])
    
    bm.run_compute(compute="final_compute", model="mesh_model", overwrite=True)

    estilo = dict(fc=MESH_COLOR, ec=MESH_EDGE, show=False)
    for ph, t in zip(PHASES_MESH, times_mesh):
        bm.plot(model="mesh_model", dataset="mesh01", time=t, **estilo, save=os.path.join(OUT_DIR, f"mesh_fase{ph}.png"))

def fase1_verificar(b):
    print("5. Calculando curvas finales y residuos...")
    b.run_compute(compute="final_compute", model="check_final", overwrite=True)

    b.plot(dataset=["lc01", "lc02"], model="check_final", x="phases", show=False, legend=True,
           save=os.path.join(OUT_DIR, "ajuste_final.png"))
    b.plot(model="check_final", kind="lc", x="phases", y="residuals", show=False, legend=True, marker="o",
           save=os.path.join(OUT_DIR, "residuos_final.png"))

    P, t0 = b.get_value("period@binary"), b.get_value("t0_supconj@binary")
    incl, q = b.get_value("incl@binary"), b.get_value("q@binary")
    sma = b.get_value("sma@binary@component")
    R1, R2 = b.get_value("requiv@primary@component"), b.get_value("requiv@secondary@component")
    RL1, RL2 = b.get_value("requiv_max@primary@component"), b.get_value("requiv_max@secondary@component")
    T1, T2 = b.get_value("teff@primary@component"), b.get_value("teff@secondary@component")

    texto = f"""Resultados de Optimización (Fase 1 - SEMI-SEPARADO)
-----------------------------------
Periodo            : {P:.6f} d
t0_supconj         : {t0:.5f}
Inclinación        : {incl:.2f} deg
q (fijo)           : {q:.3f}
Teff1 / Teff2      : {T1:.0f} K / {T2:.0f} K
R1/a               : {R1/sma:.4f}
R2/a (Secundaria)  : {R2/sma:.4f} <-- Llenando el lóbulo
Llenado del lóbulo : R1/RL1 = {R1/RL1:.3f} , R2/RL2 = {R2/RL2:.3f} (1.0 = contacto)
"""
    print(f"\n{texto}")
    with open(os.path.join(OUT_DIR, "resultados.txt"), "w", encoding="utf-8") as f:
        f.write(texto)

    dibujar_mesh(b)
    bundle_path = os.path.join(OUT_DIR, "TYC6265_semiseparado.bundle")
    b.save(bundle_path)
    print(f"\n¡Proceso exitoso! Bundle guardado en: {bundle_path}")

if __name__ == "__main__":
    print("=" * 60)
    print("INICIANDO ANÁLISIS DE SISTEMA SEMI-SEPARADO")
    print("=" * 60)
    
    b = build_bundle()
    optimize(b)
    fase1_verificar(b)