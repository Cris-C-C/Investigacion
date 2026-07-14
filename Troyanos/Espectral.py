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
from matplotlib.gridspec import GridSpec
import corner
import seaborn as sns
import itertools
from mpl_toolkits.mplot3d import Axes3D
warnings.filterwarnings('ignore')
def extraer_datos_de_carpetas(directorio_raiz):
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
                # 1. LEER RESUMEN (ZONAS Y ÁREAS)
                with open(ruta_resumen, 'r', encoding='utf-8') as f:
                    contenido_resumen = f.read()
                
                # Regex para ZONAS (Conteos Enteros)
                z_est_match = re.search(r'Total estables:\s*(\d+)', contenido_resumen)
                z_inest_match = re.search(r'Total inestables:\s*(\d+)', contenido_resumen)
                z_m1_match = re.search(r'Total colisi[oó]n m1:\s*(\d+)', contenido_resumen, re.IGNORECASE)
                z_m2_match = re.search(r'Total colisi[oó]n m2:\s*(\d+)', contenido_resumen, re.IGNORECASE)
                
                z_est = int(z_est_match.group(1)) if z_est_match else 0
                z_inest = int(z_inest_match.group(1)) if z_inest_match else 0
                z_m1 = int(z_m1_match.group(1)) if z_m1_match else 0
                z_m2 = int(z_m2_match.group(1)) if z_m2_match else 0
                
                # Regex para ÁREAS (Inmune a tildes)
                a_est_match = re.search(r'[AÁaá]rea estable:\s*([0-9.eE+-]+)', contenido_resumen)
                a_inest_match = re.search(r'[AÁaá]rea inestable:\s*([0-9.eE+-]+)', contenido_resumen)
                a_col_match = re.search(r'[AÁaá]rea.*colisi[oó]n.*m2:\s*([0-9.eE+-]+)', contenido_resumen, re.IGNORECASE)
                
                a_est = float(a_est_match.group(1)) if a_est_match else 0.0
                a_inest = float(a_inest_match.group(1)) if a_inest_match else 0.0
                a_col = float(a_col_match.group(1)) if a_col_match else 0.0
                
                # 2. LEER README (PARÁMETROS FÍSICOS)
                with open(ruta_readme, 'r', encoding='utf-8') as f:
                    contenido_readme = f.read()
                    
                dist_match = re.search(r'Semi-eje mayor.*:\s*([0-9.eE+-]+)', contenido_readme)
                masa_p_match = re.search(r'Masa del Planeta.*:\s*([0-9.eE+-]+)', contenido_readme)
                pnum_match = re.search(r'CANTIDAD DE PLANETAS.*:\s*(\d+)', contenido_readme)
                masa_e_match = re.search(r'Masa de.*estrella.*:\s*([0-9.eE+-]+)', contenido_readme, re.IGNORECASE)
                
                distancia = float(dist_match.group(1)) if dist_match else 0.0
                masa_planeta = float(masa_p_match.group(1)) if masa_p_match else 0.0
                pnum = int(pnum_match.group(1)) if pnum_match else 0
                masa_estel = float(masa_e_match.group(1)) if masa_e_match else 1.0
                
                datos_recopilados.append({
                    "Planeta": nombre_planeta,
                    "Distancia_UA": distancia,
                    "Masa_Tierra": masa_planeta,
                    "Masa_Estrella": masa_estel,
                    "Num_Planetas": pnum,
                    "Zonas Estables": z_est,             # <-- AQUÍ NACE LA COLUMNA
                    "Zonas Inestables": z_inest,
                    "Zonas Colisión m1": z_m1,
                    "Zonas Colisión m2": z_m2,
                    "Area_Estable_km2": a_est,
                    "Area_Inestable": a_inest,
                    "Area_Colision_m2": a_col
                })
            except Exception as e:
                print(f"❌ Error interno procesando {nombre_planeta}: {e}")
                
    df_resultados = pd.DataFrame(datos_recopilados)
    if not df_resultados.empty:
        df_resultados = df_resultados.sort_values(by="Planeta").reset_index(drop=True)
        print(f"✅ Lectura completada. Se extrajeron datos válidos de {len(df_resultados)} planetas.")
    return df_resultados