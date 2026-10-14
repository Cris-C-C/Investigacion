import os
os.environ.setdefault("PHOEBE_ENABLE_ONLINE_PASSBANDS", "FALSE")   # evita la consulta de red al importar
 
import sys
import glob
import shutil
import argparse
import tempfile
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
 
 
# ---------------------------------------------------------------- lectura del bundle
def find_bundle(arg=None):
    if arg:
        return arg
    cands = [p for p in glob.glob("**/*.bundle", recursive=True) if "copia_lectura" not in p]
    if not cands:
        sys.exit("No encontré ningún .bundle desde esta carpeta hacia abajo. Pásame la ruta como argumento.")
    cands.sort(key=os.path.getmtime, reverse=True)
    return cands[0]
 
 
def load_chain(path):
    import phoebe
    tmp = os.path.join(tempfile.mkdtemp(), "copia_lectura.bundle")
    shutil.copy(path, tmp)                       # copia: no se lee el archivo mientras otro proceso lo guarda
    b = phoebe.load(tmp)
 
    names = [s for s in b.solutions if s.startswith("emcee_sol_")]
    names.sort(key=lambda s: int(s.split("_")[-1]))
    if not names:
        names = list(b.solutions)
    chain = lnp = sol = None
    for s in reversed(names):                    # la más reciente que tenga 'samples'
        try:
            chain = np.array(b.get_value("samples", solution=s))
            lnp = np.array(b.get_value("lnprobabilities", solution=s))
            sol = s
            break
        except Exception:
            continue
    if chain is None:
        sys.exit(f"Ninguna solución del bundle tiene 'samples'. Soluciones: {list(b.solutions)}")
    twigs = list(b.get_value("fitted_twigs", solution=sol))
    return chain, lnp, twigs, sol, b
 
 
def orient(chain, lnp):
    """Deja chain como (iteraciones, walkers, parámetros) y lnp como (iteraciones, walkers)."""
    if chain.ndim != 3:
        sys.exit(f"'samples' tiene forma inesperada {chain.shape}")
    if chain.shape[0] < chain.shape[1]:          # (walkers, iteraciones, parámetros)
        chain = np.swapaxes(chain, 0, 1)
        if lnp.shape == chain.shape[:2][::-1]:
            lnp = lnp.T
    if lnp.shape != chain.shape[:2] and lnp.T.shape == chain.shape[:2]:
        lnp = lnp.T
    if lnp.shape != chain.shape[:2]:
        print(f"AVISO: forma de lnprob {lnp.shape} no calza con samples {chain.shape}")
    return chain, lnp
 
 
# ---------------------------------------------------------------- diagnósticos
def _acf(x):
    n = len(x)
    nfft = 2 ** int(np.ceil(np.log2(2 * n)))
    f = np.fft.fft(x - x.mean(), n=nfft)
    acf = np.fft.ifft(f * np.conjugate(f))[:n].real
    return acf / acf[0]
 
 
def tau_integrado(chain, c=5):
    """Tiempo de autocorrelación integrado (mismo método que emcee: promedio sobre walkers, ventana automática)."""
    try:
        import emcee
        return emcee.autocorr.integrated_time(chain, c=c, tol=0, quiet=True)
    except Exception:
        pass
    n, w, d = chain.shape
    out = []
    for j in range(d):
        f = np.mean([_acf(chain[:, i, j]) for i in range(w)], axis=0)
        taus = 2 * np.cumsum(f) - 1
        ok = np.arange(len(taus)) < c * taus
        win = np.argmin(ok) if (~ok).any() else len(taus) - 1
        out.append(taus[win])
    return np.array(out)
 
 
def rhat(chain):
    """Gelman-Rubin sobre la segunda mitad (orientativo: los walkers de emcee no son cadenas independientes)."""
    c = chain[chain.shape[0] // 2:]
    n = c.shape[0]
    W = c.var(axis=0, ddof=1).mean(axis=0)
    B = n * c.mean(axis=0).var(axis=0, ddof=1)
    return np.sqrt(((n - 1) / n * W + B / n) / W)
 
 
def auto_burnin(lnp, ventana=20, tol=2.0):
    """Primera iteración desde la que la mediana de lnprob queda a menos de 'tol' de su meseta final."""
    m = np.nanmedian(lnp, axis=1)
    plateau = np.median(m[-max(len(m) // 4, ventana):])
    for i in range(0, len(m) - ventana):
        if np.mean(m[i:i + ventana]) >= plateau - tol:
            return i
    return len(m) // 2
 
 
# ---------------------------------------------------------------- análisis y figuras
def analizar(chain, lnp, twigs, burnin=None, out_png="trazas_parciales.png",
             hist_png="hist_posburnin.png", paso=100):
    n, w, d = chain.shape
    lnp = np.where(np.isfinite(lnp), lnp, np.nan)
    nombres = [t.split("@")[0] for t in twigs]
    print(f"\nCadena: {n} iteraciones x {w} walkers x {d} parámetros")
 
    # --- lnprob: ¿sigue subiendo? ---
    meds = [float(np.nanmedian(lnp[i:i + paso])) for i in range(0, n, paso)]
    print(f"\nMediana de lnprob cada {paso} iteraciones:")
    print("  " + "  ".join(f"{m:.1f}" for m in meds))
 
    auto = auto_burnin(lnp)
    if burnin is None:
        burnin = auto
        print(f"\nBurn-in automático: {burnin} iteraciones (lnprob en su meseta a ±2)")
    else:
        print(f"\nBurn-in indicado: {burnin} iteraciones (el automático daría {auto})")
    post = chain[burnin:]
    npost = post.shape[0]
    if npost < 50:
        print("AVISO: quedan muy pocas iteraciones después del burn-in.")
 
    # --- diagnóstico DESPUÉS del burn-in ---
    tau_all = tau_integrado(chain)
    tau_post = tau_integrado(post)
    R_post = rhat(post)
    print(f"\nDiagnóstico sin el burn-in ({npost} iteraciones x {w} walkers):")
    print(f"{'parámetro':16s} {'tau(todo)':>10s} {'tau(post)':>10s} {'N/tau':>7s} {'R-hat':>7s}")
    for j, nom in enumerate(nombres):
        print(f"{nom:16s} {tau_all[j]:10.1f} {tau_post[j]:10.1f} {npost / tau_post[j]:7.1f} {R_post[j]:7.3f}")
    print(f"  -> el criterio de emcee pide N/tau > 50; con lo que llevas, el parámetro más lento tiene "
          f"N/tau = {npost / np.max(tau_post):.1f}")
    print(f"  -> iteraciones post-burn-in necesarias para N/tau = 50 en el más lento: ~{int(50 * np.max(tau_post))}")
 
    # --- resumen del posterior (post-burn-in) ---
    flat = post.reshape(-1, d)
    print("\nPosterior provisional (mediana, -1sigma, +1sigma) sin el burn-in:")
    for j, nom in enumerate(nombres):
        lo, med, hi = np.percentile(flat[:, j], [16, 50, 84])
        print(f"  {nom:16s} {med:12.6g}   -{med - lo:.3g}   +{hi - med:.3g}")
 
    # --- deriva dentro de la parte post-burn-in: mitad inicial vs mitad final ---
    h = npost // 2
    print("\nDeriva post-burn-in (mediana 2ª mitad - 1ª mitad, en sigma):")
    for j, nom in enumerate(nombres):
        a, b2 = np.median(post[:h, :, j]), np.median(post[h:, :, j])
        s = np.std(post[h:, :, j]) or np.nan
        print(f"  {nom:16s} {(b2 - a) / s:+.2f}")
 
    # --- figura 1: trazas ---
    fig, axes = plt.subplots(d + 1, 1, figsize=(9, 1.8 * (d + 1) + 1), sharex=True)
    axes[0].plot(lnp, alpha=0.25, lw=0.6)
    axes[0].plot(np.nanmedian(lnp, axis=1), color="k", lw=1.2)
    axes[0].set_ylabel("lnprob")
    for j in range(d):
        ax = axes[j + 1]
        ax.plot(chain[:, :, j], alpha=0.25, lw=0.6)
        ax.plot(np.median(chain[:, :, j], axis=1), color="k", lw=1.2)
        ax.set_ylabel(nombres[j], fontsize=7)
    for ax in axes:
        ax.axvline(burnin, color="r", ls="--", lw=0.8)
    axes[-1].set_xlabel("iteración (línea roja = fin del burn-in)")
    fig.suptitle("Trazas parciales (negro = mediana de los walkers)", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
 
    # --- figura 2: histogramas post-burn-in ---
    ncol = 4
    nrow = int(np.ceil(d / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3 * ncol, 2.4 * nrow))
    axes = np.atleast_1d(axes).ravel()
    for j in range(d):
        axes[j].hist(flat[:, j], bins=40, color="tab:blue", alpha=0.8)
        axes[j].set_title(nombres[j], fontsize=8)
        axes[j].tick_params(labelsize=7)
    for k in range(d, len(axes)):
        axes[k].axis("off")
    fig.suptitle(f"Distribuciones sin el burn-in (iteraciones {burnin}-{n})", fontsize=9)
    fig.tight_layout()
    fig.savefig(hist_png, dpi=150)
    plt.close(fig)
    print(f"\nFiguras guardadas en: {os.path.abspath(out_png)}  y  {os.path.abspath(hist_png)}")
    return burnin
 
 
def _fase(t, t0, P):
    return ((np.asarray(t) - t0) / P + 0.5) % 1.0 - 0.5          # [-0.5, 0.5): el eclipse primario queda en el centro
 
 
def _modelo_en_tiempos(bm, ds, model, t_obs):
    """Flujo del modelo evaluado en los tiempos observados (en el mismo orden que los datos)."""
    tm = np.array(bm.get_value("times", dataset=ds, model=model, context="model"))
    fm = np.array(bm.get_value("fluxes", dataset=ds, model=model, context="model"))
    idx = np.argsort(t_obs)
    out = np.empty(len(t_obs))
    if len(tm) == len(t_obs) and np.allclose(tm, np.asarray(t_obs)[idx]):
        out[idx] = fm
    else:                                                        # por si el modelo trae otra malla de tiempos
        out = np.interp(t_obs, tm, fm)
    return out
 
 
def _run(bm, compute, model):
    try:
        bm.run_compute(compute=compute, model=model, overwrite=True, progressbar=False)
    except Exception:
        bm.run_compute(compute=compute, model=model, overwrite=True)
 
 
def curva_de_luz(b, chain, twigs, burnin, nmodels=30, compute="optim_compute",
                 out_png="curva_luz_emcee.png", seed=0):
    """Datos con barras de error + modelo con los parámetros medianos + banda de 'nmodels' muestras del posterior.
    Todo se calcula en una COPIA del bundle (no toca el original)."""
    d = chain.shape[2]
    flat = chain[burnin:].reshape(-1, d)
    med = np.median(flat, axis=0)
    bm = b.copy()
 
    try:
        dsets = list(bm.filter(kind="lc", context="dataset").datasets)
    except Exception:
        dsets = ["lc01", "lc02"]
    obs = {}
    for ds in dsets:
        obs[ds] = tuple(np.array(bm.get_value(q, dataset=ds, context="dataset"), dtype=float)
                        for q in ("times", "fluxes", "sigmas"))
 
    def fijar(vals):
        for tw, v in zip(twigs, vals):
            bm.set_value(tw, float(v))
 
    # --- modelo mediano ---
    fijar(med)
    _run(bm, compute, "mc_med")
    p_med = dict(zip([t.split("@")[0] for t in twigs], med))
    t0, P = p_med["t0_supconj"], p_med["period"]
    mod_med = {ds: _modelo_en_tiempos(bm, ds, "mc_med", obs[ds][0]) for ds in dsets}
 
    # --- modelos del posterior ---
    rng = np.random.default_rng(seed)
    sel = flat[rng.choice(len(flat), size=min(nmodels, len(flat)), replace=False)] if nmodels > 0 else []
    draws = {ds: [] for ds in dsets}
    malos = 0
    for k, vals in enumerate(sel):
        try:
            fijar(vals)
            _run(bm, compute, "mc_tmp")
            for ds in dsets:
                draws[ds].append(_modelo_en_tiempos(bm, ds, "mc_tmp", obs[ds][0]))
        except Exception:
            malos += 1                                           # p. ej. combinación fuera de rango físico
        if (k + 1) % 10 == 0:
            print(f"  curva de luz: {k + 1}/{len(sel)} modelos")
    if malos:
        print(f"  {malos} de {len(sel)} muestras no se pudieron calcular y se omitieron")
 
    # --- chi2 del modelo mediano ---
    print("\nAjuste del modelo con los parámetros medianos del posterior:")
    chi_tot, n_tot = 0.0, 0
    for ds in dsets:
        t, f, s = obs[ds]
        chi2 = float(np.sum(((f - mod_med[ds]) / s) ** 2))
        chi_tot += chi2
        n_tot += len(t)
        print(f"  {ds}: chi2 = {chi2:.1f}   chi2/N = {chi2 / len(t):.2f}   (N = {len(t)})")
    print(f"  total: chi2 = {chi_tot:.1f}   chi2/(N-{d}) = {chi_tot / max(n_tot - d, 1):.2f}")
 
    # --- figura ---
    nd = len(dsets)
    fig, axes = plt.subplots(2, nd, figsize=(5.8 * nd, 6.5), sharex="col",
                             gridspec_kw={"height_ratios": [3, 1]}, squeeze=False)
    colores = ["tab:red", "tab:blue", "tab:green", "tab:orange"]
    for c, ds in enumerate(dsets):
        t, f, s = obs[ds]
        ph = _fase(t, t0, P)
        o = np.argsort(ph)
        try:
            etiqueta = str(bm.get_value("passband", dataset=ds, context="dataset"))
        except Exception:
            etiqueta = ds
        col = colores[c % len(colores)]
        ax, axr = axes[0, c], axes[1, c]
 
        M = np.array(draws[ds])                                  # (modelos, puntos)
        if len(M):
            for m in M:
                ax.plot(ph[o], m[o], color="0.5", alpha=0.12, lw=0.7, zorder=1)
            lo, hi = np.percentile(M, [16, 84], axis=0)
            ax.fill_between(ph[o], lo[o], hi[o], color=col, alpha=0.30, lw=0, zorder=2, label="posterior 16-84 %")
            axr.fill_between(ph[o], (lo - mod_med[ds])[o], (hi - mod_med[ds])[o], color=col, alpha=0.30, lw=0)
        ax.errorbar(ph, f, yerr=s, fmt="o", ms=3, color="k", ecolor="0.35", elinewidth=0.8,
                    capsize=0, alpha=0.9, zorder=3, label="datos \u00b11\u03c3")
        ax.plot(ph[o], mod_med[ds][o], color=col, lw=1.6, zorder=4, label="modelo (mediana)")
        ax.set_title(f"{etiqueta}  ({ds})", fontsize=10)
        ax.set_ylabel("flujo")
        ax.legend(fontsize=7, loc="lower right")
 
        axr.errorbar(ph, f - mod_med[ds], yerr=s, fmt="o", ms=3, color="k", ecolor="0.35",
                     elinewidth=0.8, capsize=0, alpha=0.9)
        axr.axhline(0, color=col, lw=1.2)
        axr.set_xlabel("fase")
        axr.set_ylabel("residuo")
    fig.suptitle(f"Curva de luz con el ajuste de emcee (burn-in {burnin}; {len(sel)} muestras; compute = {compute})",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    print(f"Curva de luz guardada en: {os.path.abspath(out_png)}")
 
 
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", nargs="?", default=None)
    ap.add_argument("--burnin", type=int, default=None)
    ap.add_argument("--nmodels", type=int, default=30, help="modelos del posterior en la curva de luz (0 = omitir)")
    ap.add_argument("--compute", default="optim_compute", help="backend de cálculo para la curva de luz")
    args = ap.parse_args()
 
    path = find_bundle(args.bundle)
    print("Bundle:", os.path.abspath(path))
    chain, lnp, twigs, sol, b = load_chain(path)
    print("Solución:", sol)
    chain, lnp = orient(chain, lnp)
    burnin = analizar(chain, lnp, twigs, burnin=args.burnin)
    if args.nmodels > 0:
        print(f"\nCalculando la curva de luz (~{2 * (args.nmodels + 1)} s con 2 s por modelo)...")
        try:
            curva_de_luz(b, chain, twigs, burnin, nmodels=args.nmodels, compute=args.compute)
        except Exception as e:
            print(f"No pude generar la curva de luz: {type(e).__name__}: {e}")