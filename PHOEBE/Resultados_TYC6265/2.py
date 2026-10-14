import os
import shutil
import tempfile
import numpy as np
import matplotlib.pyplot as plt
import phoebe
 
try:                                                  # fuerza gráficos en línea en Jupyter
    from IPython import get_ipython
    get_ipython().run_line_magic("matplotlib", "inline")
except Exception:
    pass
 
BUNDLE   = "TYC6265_emcee.bundle"    # ruta al bundle de la corrida
COMPUTE  = "optim_compute"           # backend del muestreo; prueba 'final_compute' para la física completa
BURNIN   = 300                       # iteraciones a descartar (por la traza de lnprob: ~250)
THIN     = 5                         # 1 = usar todas las muestras; sube si la figura corner va lenta
NSAMPLES = 20                        # modelos del posterior para la curva de luz (≈ 2 s cada uno)
DATASETS = ["lc01", "lc02"]
MODEL    = "emcee_sol_model"
 
tmp = os.path.join(tempfile.mkdtemp(), "copia_lectura.bundle")
shutil.copy(BUNDLE, tmp)                              # copia: no se lee el original mientras otro proceso lo guarda
b = phoebe.load(tmp)
 
emcee_sols = sorted([s for s in b.solutions if s.startswith("emcee_sol_")],
                    key=lambda s: int(s.split("_")[-1]))
SOL = emcee_sols[-1] if emcee_sols else list(b.solutions)[-1]   # la más reciente (contiene la cadena acumulada)
print("Solución usada:", SOL, "| soluciones disponibles:", list(b.solutions))
 
# burn-in y thinning se guardan como parámetros de la solución y los usan los gráficos y sample_from
b.set_value("burnin", solution=SOL, value=BURNIN)
b.set_value("thin", solution=SOL, value=THIN)
print("burnin =", b.get_value("burnin", solution=SOL), "| thin =", b.get_value("thin", solution=SOL))
 
 
# %% 1. Gráficos de la solución: lnprobability, corner, trace
_ = b.plot(solution=SOL, style="lnprobability", save="emcee_lnprobability.png", show=True)
_ = b.plot(solution=SOL, style="corner", save="emcee_corner.png", show=True)
_ = b.plot(solution=SOL, style="trace", save="emcee_trace.png", show=True)
 
 
# %% 2. Modelos muestreados del posterior (cada modelo ≈ 2 s)
b.run_compute(compute=COMPUTE, sample_from=SOL, sample_num=NSAMPLES, model=MODEL, overwrite=True)
 
 
# %% 3. Curva de luz con los modelos del posterior y residuos, por filtro
for ds in DATASETS:
    _ = b.plot(dataset=ds, x="phases",
               marker={"dataset": "."},
               model=MODEL, save=f"emcee_{ds}_curva.png", show=True)
    _ = b.plot(dataset=ds, x="phases", y="residuals",
               z={"dataset": 0, "model": 1},
               model=MODEL, save=f"emcee_{ds}_residuos.png", show=True)
 