"""
=============================================================================
  Análisis de Estabilidad Orbital de Exoplanetas Troyanos — v2.0 (Refactorizado)
=============================================================================

Cambios respecto a la versión original:
  1. Todas las columnas se referencian por sus nombres canónicos del DataFrame
     (e.g. "Zonas Estables", nunca "Total estables").
  2. Transformaciones logarítmicas blindadas con np.log10(x + 1) y/o escala
     symlog para evitar -inf / división por cero.
  3. Filtros y copias de DataFrames sobre el original pasado a cada función
     (evita UnboundLocalError).
  4. KDE 2D solo para "Zonas Estables"; paleta cambiada a 'inferno'.
  5. Eliminada toda función de "Relaciones Dinámicas Adimensionales",
     "Esfera de Hill" y "Ratio de Estabilidad".
  6. Gráfico 3D rediseñado:
       - X = mu2 = Masa_Planeta / (Masa_Estrella + Masa_Planeta)  [en kg]
       - Y = Distancia a la estrella (UA, escala log)
       - Z = Conteo de Zonas Estables
       - Ángulo de cámara que expone la relación distancia-mu2.
"""

import os
import re
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy.stats import gaussian_kde
import tkinter as tk
from tkinter import filedialog
import warnings
import itertools
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (activa proyección 3D)

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES FÍSICAS
# ═══════════════════════════════════════════════════════════════════════════════
MASA_TIERRA_KG = 5.972e24   # kg
MASA_SOL_KG    = 1.989e30   # kg


# ═══════════════════════════════════════════════════════════════════════════════
# 1. EXTRACCIÓN DE DATOS
# ═══════════════════════════════════════════════════════════════════════════════
def extraer_datos_de_carpetas(directorio_raiz: str) -> pd.DataFrame:
    """
    Escanea la carpeta, extrae parámetros físicos del README y métricas del resumen,
    incluyendo conteos de zonas y áreas, blindado contra faltas de ortografía (tildes).
    """
    datos_recopilados = []
    print(f"\n🔍 Escaneando directorio: {directorio_raiz}...")

    for root, dirs, files in os.walk(directorio_raiz):
        resumen_file = None
        readme_file = None

        for file in files:
            if file.endswith(" resumen.txt") or file.endswith("_resumen.txt"):
                resumen_file = file
            elif file.startswith("README") and file.endswith(".txt"):
                readme_file = file

        if resumen_file and readme_file:
            nombre_planeta = os.path.basename(root).replace("_", " ")
            ruta_resumen = os.path.join(root, resumen_file)
            ruta_readme = os.path.join(root, readme_file)

            try:
                # ── 1. LEER RESUMEN (ZONAS Y ÁREAS) ──────────────────────
                with open(ruta_resumen, "r", encoding="utf-8") as f:
                    contenido_resumen = f.read()

                # Regex para ZONAS (Conteos Enteros)
                z_est_match   = re.search(r"Total estables:\s*(\d+)", contenido_resumen)
                z_inest_match = re.search(r"Total inestables:\s*(\d+)", contenido_resumen)
                z_m1_match    = re.search(r"Total colisi[oó]n m1:\s*(\d+)",
                                          contenido_resumen, re.IGNORECASE)
                z_m2_match    = re.search(r"Total colisi[oó]n m2:\s*(\d+)",
                                          contenido_resumen, re.IGNORECASE)

                z_est   = int(z_est_match.group(1))   if z_est_match   else 0
                z_inest = int(z_inest_match.group(1)) if z_inest_match else 0
                z_m1    = int(z_m1_match.group(1))    if z_m1_match    else 0
                z_m2    = int(z_m2_match.group(1))    if z_m2_match    else 0

                # Regex para ÁREAS (Inmune a tildes)
                a_est_match  = re.search(
                    r"[AÁaá]rea estable:\s*([0-9.eE+-]+)", contenido_resumen)
                a_inest_match = re.search(
                    r"[AÁaá]rea inestable:\s*([0-9.eE+-]+)", contenido_resumen)
                a_col_match  = re.search(
                    r"[AÁaá]rea.*colisi[oó]n.*m2:\s*([0-9.eE+-]+)",
                    contenido_resumen, re.IGNORECASE)

                a_est   = float(a_est_match.group(1))   if a_est_match   else 0.0
                a_inest = float(a_inest_match.group(1)) if a_inest_match else 0.0
                a_col   = float(a_col_match.group(1))   if a_col_match   else 0.0

                # ── 2. LEER README (PARÁMETROS FÍSICOS) ───────────────────
                with open(ruta_readme, "r", encoding="utf-8") as f:
                    contenido_readme = f.read()

                dist_match   = re.search(
                    r"Semi-eje mayor.*:\s*([0-9.eE+-]+)", contenido_readme)
                masa_p_match = re.search(
                    r"Masa del Planeta.*:\s*([0-9.eE+-]+)", contenido_readme)
                pnum_match   = re.search(
                    r"CANTIDAD DE PLANETAS.*:\s*(\d+)", contenido_readme)
                masa_e_match = re.search(
                    r"Masa de.*estrella.*:\s*([0-9.eE+-]+)",
                    contenido_readme, re.IGNORECASE)

                distancia     = float(dist_match.group(1))   if dist_match   else 0.0
                masa_planeta  = float(masa_p_match.group(1)) if masa_p_match else 0.0
                pnum          = int(pnum_match.group(1))     if pnum_match   else 0
                masa_estel    = float(masa_e_match.group(1)) if masa_e_match else 1.0

                datos_recopilados.append({
                    "Planeta":           nombre_planeta,
                    "Distancia_UA":      distancia,
                    "Masa_Tierra":       masa_planeta,
                    "Masa_Estrella":     masa_estel,
                    "Num_Planetas":      pnum,
                    "Zonas Estables":    z_est,
                    "Zonas Inestables":  z_inest,
                    "Zonas Colisión m1": z_m1,
                    "Zonas Colisión m2": z_m2,
                    "Area_Estable_km2":  a_est,
                    "Area_Inestable":    a_inest,
                    "Area_Colision_m2":  a_col,
                })
            except Exception as e:
                print(f"❌ Error interno procesando {nombre_planeta}: {e}")

    df_resultados = pd.DataFrame(datos_recopilados)
    if not df_resultados.empty:
        df_resultados = df_resultados.sort_values(by="Planeta").reset_index(drop=True)
        print(f"✅ Lectura completada. Se extrajeron datos válidos de "
              f"{len(df_resultados)} planetas.")
    return df_resultados


# ═══════════════════════════════════════════════════════════════════════════════
# UTILIDADES INTERNAS
# ═══════════════════════════════════════════════════════════════════════════════
def _safe_log10(x):
    """log10 blindado: retorna log10(x + 1) para evitar log(0) = -inf."""
    return np.log10(np.asarray(x, dtype=float) + 1.0)


def _asignar_estilos_sistema(df: pd.DataFrame) -> dict:
    """
    Genera combinaciones únicas de marcador/color para cada sistema estelar.
    Trabaja sobre la columna 'Sistema' (la crea si no existe).
    Devuelve un dict  {nombre_sistema: {'marker': ..., 'color': ...}}.
    """
    if "Sistema" not in df.columns:
        df = df.copy()
        df["Sistema"] = df["Planeta"].apply(lambda x: str(x).rsplit(" ", 1)[0])

    sistemas_unicos = df["Sistema"].unique()
    marcadores_base = ["o", "s", "^", "D", "v", "p", "*", "h",
                       "H", "X", "d", "P", "<", ">"]
    colores_base = plt.cm.tab20.colors
    combinaciones = itertools.product(marcadores_base, colores_base)

    estilos = {}
    for sist, (marker, color) in zip(sistemas_unicos, combinaciones):
        estilos[sist] = {"marker": marker, "color": color}

    return estilos


# ═══════════════════════════════════════════════════════════════════════════════
# 2. COMPARACIÓN POR MULTIPLICIDAD  (Paneles Verticales)
# ═══════════════════════════════════════════════════════════════════════════════
def graficar_comparacion_multiplicidad(df: pd.DataFrame, base_dir: str):
    """
    Genera paneles verticales dinámicos graficando el CONTEO de Zonas Estables
    vs Distancia a la estrella (UA), segregado por número de planetas.

    Usa escala 'symlog' en Y para manejar valores cero sin colapsar.
    """
    # ── Trabajo sobre copia ──
    df = df.copy()
    if "Sistema" not in df.columns:
        df["Sistema"] = df["Planeta"].apply(lambda x: str(x).rsplit(" ", 1)[0])

    a_total    = df["Distancia_UA"].values
    areas      = df["Zonas Estables"].values        # ← nombre canónico del DataFrame
    pnum_total = df["Num_Planetas"].values

    estilos_sistema = _asignar_estilos_sistema(df)

    # Paleta fija por multiplicidad
    estilos_pnum = {
        1: {"marker": "o", "color": "gray",    "label": "1 planeta"},
        2: {"marker": "s", "color": "#4363d8",  "label": "2 planetas"},
        3: {"marker": "^", "color": "#e6194b",  "label": "3 planetas"},
        4: {"marker": "D", "color": "#3cb44b",  "label": "4 planetas"},
        5: {"marker": "v", "color": "#f58231",  "label": "5 planetas"},
        6: {"marker": "p", "color": "#911eb4",  "label": "6 planetas"},
        7: {"marker": "*", "color": "#f032e6",  "label": "7 planetas"},
        8: {"marker": "h", "color": "#bcbd22",  "label": "8 planetas"},
    }

    pnums_unicos = sorted(df["Num_Planetas"].unique())
    num_paneles  = len(pnums_unicos) + 1

    fig, axes = plt.subplots(num_paneles, 1, figsize=(14, 6 * num_paneles))
    fig.suptitle("Comparación de Zonas Estables por Multiplicidad",
                 fontsize=22, fontweight="bold", y=0.98)

    if num_paneles == 1:
        axes = [axes]

    # Límites globales seguros
    xlims = ((a_total.min() * 0.5, a_total.max() * 2.0)
             if len(a_total) > 0 else (0.1, 100))
    y_max = areas.max() if (len(areas) > 0 and areas.max() > 0) else 10000
    ylims = (0.5, y_max * 2.0)

    # ── PANEL 0: General ─────────────────────────────────────────────────
    ax_all = axes[0]
    ax_all.set_title("Todos los sistemas (Clasificados por Multiplicidad)",
                     fontsize=16, fontweight="bold")

    for p_num in pnums_unicos:
        mask = pnum_total == p_num
        props = estilos_pnum.get(
            p_num, {"marker": "X", "color": "black", "label": f"{p_num} planetas"})
        ax_all.scatter(a_total[mask], areas[mask],
                       marker=props["marker"], color=props["color"],
                       s=100, alpha=0.8, edgecolor="black",
                       label=props["label"], zorder=3)

    ax_all.legend(loc="upper left", bbox_to_anchor=(1.02, 1),
                  frameon=True, shadow=True, title="Simbología")

    # ── PANELES 1…N: Filtro por multiplicidad ────────────────────────────
    for i, p_num in enumerate(pnums_unicos):
        ax = axes[i + 1]
        df_sub = df[df["Num_Planetas"] == p_num].copy()

        ax.set_title(f"Sistemas con {p_num} planetas",
                     fontsize=16, fontweight="bold")

        # KDE de densidad sobre la Distancia (X) — blindado
        a_sub = df_sub["Distancia_UA"].values
        a_sub_pos = a_sub[a_sub > 0]
        if len(a_sub_pos) >= 2:
            log_a = np.log10(a_sub_pos)
            try:
                kde = gaussian_kde(log_a)
                x_eval = np.linspace(log_a.min(), log_a.max(), 1000)
                y_eval = kde(x_eval)
                idx_max = np.argmax(y_eval)
                a_pico = 10 ** x_eval[idx_max]
                umbral = y_eval.max() * 0.5
                indices_rango = np.where(y_eval > umbral)[0]

                if len(indices_rango) > 0:
                    a_min_rango = 10 ** x_eval[indices_rango[0]]
                    a_max_rango = 10 ** x_eval[indices_rango[-1]]
                    texto = (f"Concentración: {a_min_rango:.2f} – "
                             f"{a_max_rango:.2f} UA")
                    ax.axvspan(a_min_rango, a_max_rango,
                               color="gray", alpha=0.15, label=texto, zorder=0)
                    ax.axvline(a_pico, color="red", linestyle=":",
                               linewidth=1.5,
                               label=f"Pico: {a_pico:.2f} UA", zorder=1)
            except np.linalg.LinAlgError:
                pass

        # Puntos de dispersión por sistema
        sistemas_en_panel = df_sub["Sistema"].unique()
        for sist in sistemas_en_panel:
            df_sist = df_sub[df_sub["Sistema"] == sist]
            props = estilos_sistema[sist]
            ax.scatter(df_sist["Distancia_UA"], df_sist["Zonas Estables"],
                       marker=props["marker"], color=props["color"],
                       s=110, alpha=0.85, edgecolor="black",
                       label=sist, zorder=3)

        ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1),
                  frameon=True, shadow=True,
                  title="Nombre del Sistema", ncol=2, fontsize=9)

    # ── ESTÉTICA DE EJES ─────────────────────────────────────────────────
    for ax in axes:
        ax.set_xscale("log")
        # symlog evita colapso cuando existen valores = 0
        ax.set_yscale("symlog", linthresh=1)
        ax.set_xlim(xlims)
        ax.set_ylim(ylims)
        ax.xaxis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f"{x:g}"))
        ax.yaxis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f"{x:g}"))
        ax.grid(True, which="both", ls="--", alpha=0.3, zorder=0)
        ax.set_xlabel("log[a] (UA)", fontsize=12, fontweight="bold")
        ax.set_ylabel("Zonas Estables (Conteo)",
                       fontsize=12, fontweight="bold")

    plt.tight_layout(rect=[0, 0.03, 0.85, 0.98])

    ruta_png = os.path.join(base_dir, "Zonas_Estables_Multiplicidad_Vertical.png")
    ruta_pdf = os.path.join(base_dir, "Zonas_Estables_Multiplicidad_Vertical.pdf")
    plt.savefig(ruta_png, dpi=300, bbox_inches="tight")
    plt.savefig(ruta_pdf, format="pdf", bbox_inches="tight")
    plt.show()
    plt.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. MAPA DE CONTORNO 2D (KDE) — SOLO "ZONAS ESTABLES"
# ═══════════════════════════════════════════════════════════════════════════════
def plot_islands_zonas_estables(df: pd.DataFrame, base_dir: str):
    """
    Genera mapas de contornos de densidad 2D (KDE) verticales
    ÚNICAMENTE para la métrica 'Zonas Estables'.

    Paleta de alto contraste térmico: 'inferno'.
    Logs blindados con _safe_log10.
    """
    metrica = "Zonas Estables"
    print(f"\nGenerando mapa de contornos 2D para: {metrica}...")

    # ── Trabajo sobre copia ──
    df = df.copy()
    if "Sistema" not in df.columns:
        df["Sistema"] = df["Planeta"].apply(lambda x: str(x).rsplit(" ", 1)[0])

    estilos_sistema = _asignar_estilos_sistema(df)

    # Filtrar datos con valores > 0 para el KDE
    df_f = df[df[metrica] > 0].copy()

    if df_f.empty or len(df_f) < 3:
        print(f"⚠️ No hay suficientes datos válidos (>0) para generar el mapa "
              f"de {metrica}.")
        return

    # Paneles
    pnums_unicos = sorted(df_f["Num_Planetas"].unique())
    num_paneles  = len(pnums_unicos) + 1

    fig, axes = plt.subplots(num_paneles, 1, figsize=(18, 10 * num_paneles))
    fig.suptitle(f"Mapas de Contorno 2D: Islas de {metrica} por Multiplicidad",
                 fontsize=24, fontweight="bold", y=0.98)

    if num_paneles == 1:
        axes = [axes]

    # Límites globales (log blindado: Distancia y Masa siempre > 0 en datos válidos)
    dist_pos = df_f["Distancia_UA"][df_f["Distancia_UA"] > 0]
    masa_pos = df_f["Masa_Tierra"][df_f["Masa_Tierra"] > 0]

    if dist_pos.empty or masa_pos.empty:
        print("⚠️ No hay datos positivos suficientes de Distancia/Masa para el KDE.")
        return

    x_all = np.log10(dist_pos)
    y_all = np.log10(masa_pos)
    xlims = (x_all.min() - 0.4, x_all.max() + 0.4)
    ylims = (y_all.min() - 0.4, y_all.max() + 0.4)

    # ── FUNCIÓN INTERNA: dibujar un panel ────────────────────────────────
    def dibujar_panel(ax, df_subset, titulo, es_general=False):
        if df_subset.empty:
            ax.set_title(titulo + " (Sin datos)",
                         fontsize=18, fontweight="bold", pad=15)
            ax.axis("off")
            return

        # Filtrar filas con Distancia > 0 y Masa > 0
        mask_valid = (df_subset["Distancia_UA"] > 0) & (df_subset["Masa_Tierra"] > 0)
        df_valid = df_subset[mask_valid].copy()

        if df_valid.empty:
            ax.set_title(titulo + " (Sin datos válidos)",
                         fontsize=18, fontweight="bold", pad=15)
            ax.axis("off")
            return

        x = np.log10(df_valid["Distancia_UA"].values)
        y = np.log10(df_valid["Masa_Tierra"].values)

        # Peso KDE blindado con log10(val + 1)
        weights = _safe_log10(df_valid[metrica].values)

        # ── A. MAPA DE CONTORNOS (KDE 2D) ────────────────────────────
        if len(df_valid) > 3 and x.var() > 0 and y.var() > 0:
            try:
                xy = np.vstack([x, y])
                kde = gaussian_kde(xy, weights=weights, bw_method=0.45)

                X, Y = np.mgrid[xlims[0]:xlims[1]:150j,
                                ylims[0]:ylims[1]:150j]
                positions = np.vstack([X.ravel(), Y.ravel()])
                Z = np.reshape(kde(positions).T, X.shape)

                contour = ax.contourf(X, Y, Z, levels=25,
                                      cmap="inferno", alpha=0.85)
                cbar = fig.colorbar(contour, ax=ax, pad=0.02, aspect=30)
                cbar.set_label(f"Densidad de {metrica} (log)", fontsize=12)
            except np.linalg.LinAlgError:
                pass

        # ── B. PUNTOS DE DISPERSIÓN ──────────────────────────────────
        for sist in df_valid["Sistema"].unique():
            df_sist = df_valid[df_valid["Sistema"] == sist]
            props = estilos_sistema.get(
                sist, {"marker": "o", "color": "white"})
            label = sist if not es_general else None
            ax.scatter(np.log10(df_sist["Distancia_UA"]),
                       np.log10(df_sist["Masa_Tierra"]),
                       marker=props["marker"], color=props["color"],
                       s=90, edgecolor="white", linewidth=1.0,
                       label=label, zorder=5)

        # ── C. LÍNEAS FÍSICAS ────────────────────────────────────────
        ax.axhline(y=np.log10(10), color="cyan", linestyle="--",
                   linewidth=2, label="Límite Rocoso / Neptuniano", zorder=4)
        ax.axhline(y=np.log10(50), color="magenta", linestyle="--",
                   linewidth=2, label="Límite Neptuniano / Gigante", zorder=4)

        # ── D. ESTÉTICA ──────────────────────────────────────────────
        ax.set_title(titulo, fontsize=18, fontweight="bold", pad=15)
        ax.set_xlim(xlims)
        ax.set_ylim(ylims)
        ax.set_xlabel("log[Distancia] (UA)", fontsize=14)
        ax.set_ylabel(r"log[Masa Planetaria] ($M_\oplus$)", fontsize=14)
        ax.grid(True, which="both", ls="--", color="white", alpha=0.3, zorder=0)

        # ── E. LEYENDAS ─────────────────────────────────────────────
        if not es_general:
            ax.legend(loc="upper left", bbox_to_anchor=(1.22, 1),
                      frameon=True, shadow=True,
                      title="Sistemas", ncol=2, fontsize=10)
        else:
            handles, labels = ax.get_legend_handles_labels()
            line_handles = [h for h, l in zip(handles, labels) if "Límite" in l]
            line_labels  = [l for l in labels if "Límite" in l]
            if line_handles:
                ax.legend(line_handles, line_labels, loc="upper left",
                          bbox_to_anchor=(1.22, 1),
                          frameon=True, shadow=True, fontsize=10)

    # ── EJECUCIÓN DE LOS PANELES ─────────────────────────────────────────
    dibujar_panel(axes[0], df_f,
                  f"Visión Global: Todos los sistemas ({metrica})",
                  es_general=True)

    for i, pnum in enumerate(pnums_unicos):
        df_sub = df_f[df_f["Num_Planetas"] == pnum].copy()
        dibujar_panel(axes[i + 1], df_sub,
                      f"Sistemas con {pnum} planetas ({metrica})",
                      es_general=False)

    plt.tight_layout(rect=[0, 0.03, 0.82, 0.98])

    nombre_base = metrica.replace(" ", "_")
    ruta_png = os.path.join(base_dir, f"Mapa_Islas_2D_{nombre_base}_Vertical.png")
    ruta_pdf = os.path.join(base_dir, f"Mapa_Islas_2D_{nombre_base}_Vertical.pdf")
    plt.savefig(ruta_png, dpi=300, bbox_inches="tight")
    plt.savefig(ruta_pdf, format="pdf", bbox_inches="tight")
    plt.show()
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. GRÁFICO 3D — mu2 vs Distancia vs Zonas Estables
# ═══════════════════════════════════════════════════════════════════════════════
def plot_3d_zonas_estables_mu2(df: pd.DataFrame, base_dir: str):
    """
    Dispersión tridimensional:
      · Eje X — mu2 = Masa_Planeta / (Masa_Estrella + Masa_Planeta)  [adim.]
      · Eje Y — Distancia a la estrella (UA) con escala logarítmica
      · Eje Z — Conteo de Zonas Estables (puro, sin transformación)
    Puntos coloreados por multiplicidad planetaria.
    """
    print("\nGenerando gráfico 3D de Zonas Estables vs Distancia y mu2...")

    col_zonas = "Zonas Estables"
    if col_zonas not in df.columns:
        print(f"Error: No se encontró la columna '{col_zonas}'.")
        return

    # ── Trabajo sobre copia, filtro > 0 ──
    df_f = df[df[col_zonas] > 0].copy()
    if df_f.empty:
        print("No hay datos válidos (>0) para graficar en 3D.")
        return

    # ── Cálculo de mu2  (masa reducida del secundario) ───────────────────
    m_star_kg  = df_f["Masa_Estrella"].values * MASA_SOL_KG
    m_planet_kg = df_f["Masa_Tierra"].values * MASA_TIERRA_KG
    mu2 = m_planet_kg / (m_star_kg + m_planet_kg)
    df_f["mu2"] = mu2

    # ── Ejes ─────────────────────────────────────────────────────────────
    x_vals = df_f["mu2"].values                           # mu2 (lineal)
    y_vals = df_f["Distancia_UA"].values                  # UA  (se graficará log)
    z_vals = df_f[col_zonas].values                       # conteo puro

    # ── Figura 3D ────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 10))
    ax  = fig.add_subplot(111, projection="3d")

    pnums  = sorted(df_f["Num_Planetas"].unique())
    colores = plt.cm.plasma(np.linspace(0.1, 0.9, len(pnums)))

    for i, p_num in enumerate(pnums):
        mask = df_f["Num_Planetas"] == p_num
        ax.scatter(x_vals[mask], y_vals[mask], z_vals[mask],
                   s=70, color=colores[i], edgecolor="black", alpha=0.85,
                   label=f"{p_num} planetas")

    # ── Estética ─────────────────────────────────────────────────────────
    ax.set_title(
        r"Relación 3D: Zonas Estables, Distancia y Masa Reducida ($\mu_2$)",
        fontsize=18, fontweight="bold", pad=20)

    ax.set_xlabel(r"$\mu_2$ (Masa Reducida del Secundario)",
                  fontsize=12, labelpad=12)
    ax.set_ylabel("Distancia a la estrella (UA)",
                  fontsize=12, labelpad=15)
    ax.set_zlabel("Zonas Estables (Conteo)",
                  fontsize=12, labelpad=10)

    # Formato estricto para mu2 (evitar colapso de decimales)
    ax.xaxis.set_major_formatter(ticker.FormatStrFormatter("%.2e"))
    # Eje Y logarítmico (mplot3d no soporta set_yscale('log') nativamente)
    ax.set_yscale("log")

    # Ángulo de cámara que expone relación distancia-mu2
    ax.view_init(elev=25, azim=135)

    ax.legend(title="Multiplicidad", loc="upper left",
              bbox_to_anchor=(1.05, 0.9))

    plt.tight_layout()

    ruta_png = os.path.join(base_dir, "Grafico_3D_Zonas_Estables_mu2.png")
    ruta_pdf = os.path.join(base_dir, "Grafico_3D_Zonas_Estables_mu2.pdf")
    plt.savefig(ruta_png, dpi=300, bbox_inches="tight")
    plt.savefig(ruta_pdf, format="pdf", bbox_inches="tight")
    plt.show()
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. BLOQUE MAIN
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":

    # ── Selección de carpeta con tkinter ──────────────────────────────────
    print("Esperando selección de carpeta en la ventana emergente...")
    root_tk = tk.Tk()
    root_tk.withdraw()
    directorio_raiz = filedialog.askdirectory(
        title="Selecciona la carpeta raíz de resultados")
    root_tk.destroy()

    if not directorio_raiz:
        print("❌ No se seleccionó ningún directorio. Saliendo.")
    else:
        # ── Extracción ────────────────────────────────────────────────
        df = extraer_datos_de_carpetas(directorio_raiz)

        if df.empty:
            print("❌ No se encontraron datos válidos en el directorio.")
        else:
            # Carpeta de salida para los gráficos
            base_dir = directorio_raiz

            # ── 1. Paneles verticales de multiplicidad ────────────────
            print("\nGenerando gráficos de Zonas Estables por multiplicidad...")
            graficar_comparacion_multiplicidad(df, base_dir)

            # ── 2. Mapas KDE 2D (solo Zonas Estables) ─────────────────
            print("\nGenerando mapa KDE 2D de islas de estabilidad...")
            plot_islands_zonas_estables(df, base_dir)

            # ── 3. Gráfico 3D (mu2 vs Distancia vs Zonas Estables) ───
            print("\nGenerando gráfico 3D con mu2 del secundario...")
            plot_3d_zonas_estables_mu2(df, base_dir)

            print("\n✅ Pipeline completo. Gráficos exportados en:")
            print(f"   {base_dir}")
