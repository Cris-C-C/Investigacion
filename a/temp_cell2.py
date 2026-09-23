def _obtener_curva_convergencia(x, y, weights):
    xy_train = np.vstack([x, y]).T 
    bws = np.linspace(0.1, 1.5, 40)
    grid_params = {'bandwidth': bws}
    grid = GridSearchCV(KernelDensity(), grid_params, cv=3)
    try:
        grid.fit(xy_train, sample_weight=weights)
        return bws, grid.cv_results_['mean_test_score'], grid.best_estimator_.bandwidth
    except Exception:
        return bws, np.zeros_like(bws), 0.6

def plot_convergencia_bw(df: pd.DataFrame):
    metrica = "Area_Estable_km2"
    
    # Filtramos estrictamente valores > 0 para evitar errores matemáticos con el logaritmo
    mask_valid = (df[metrica] > 0) & (df["Distancia_UA"] > 0) & (df["Masa_Tierra"] > 0)
    df_valid = df[mask_valid].copy()
    
    df_filtrado = df_valid[df_valid['Num_Planetas'] >= 3]
    pnums = sorted(df_filtrado["Num_Planetas"].unique())
    num_paneles = len(pnums) + 1
    
    fig, axes = plt.subplots(1, num_paneles, figsize=(5 * num_paneles, 5.5), constrained_layout=True)
    fig.suptitle("KDE Bandwidth Optimization: Log-Likelihood Convergence", fontsize=18, fontweight="bold")
    
    if num_paneles == 1: 
        axes = [axes]
        
    def graficar_curva(ax, x_data, y_data, w_data, titulo, color):
        if len(x_data) <= 4:
            ax.set_title(titulo + f"\n(N={len(x_data)} - Insufficient Data)", fontsize=12)
            ax.axis('off')
            return
            
        print(f"Calculando {titulo}...")
        bws, puntajes, bw_optimo = _obtener_curva_convergencia(x_data, y_data, w_data)
        
        ax.plot(bws, puntajes, color=color, linewidth=2.5, label="Log-Likelihood")
        ax.scatter(bw_optimo, np.max(puntajes), color='red', s=80, zorder=5, edgecolor='black', label=f"Optimal Peak ({bw_optimo:.2f})")
        ax.axvline(x=bw_optimo, color='red', linestyle='--', alpha=0.6)
        
        ax.set_title(titulo + f" (N={len(x_data)})", fontsize=14, fontweight="bold")
        ax.set_xlabel("Bandwidth")
        if ax == axes[0]: ax.set_ylabel("Mean Log-Likelihood")
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.legend(loc='lower right', fontsize=10)

    # Usamos np.log10 directo ya que los ceros fueron filtrados por mask_valid
    x_glob = np.log10(df_valid["Distancia_UA"].values)
    y_glob = np.log10(df_valid["Masa_Tierra"].values)
    w_glob = np.log10(df_valid[metrica].values)
    graficar_curva(axes[0], x_glob, y_glob, w_glob, "Global View", "navy")
    
    colores = ["darkorange", "forestgreen", "purple", "crimson", "teal", "sienna"]
    for i, pnum in enumerate(pnums):
        df_sub = df_filtrado[df_filtrado["Num_Planetas"] == pnum]
        
        x_sub = np.log10(df_sub["Distancia_UA"].values)
        y_sub = np.log10(df_sub["Masa_Tierra"].values)
        w_sub = np.log10(df_sub[metrica].values)
        
        graficar_curva(axes[i+1], x_sub, y_sub, w_sub, f"{int(pnum)} Planets", colores[i % len(colores)])
        
    plt.show()