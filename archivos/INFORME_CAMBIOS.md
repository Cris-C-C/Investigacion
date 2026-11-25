# Auditoría de los mapas de estabilidad

El catálogo histórico bajo **Troyanos** tiene **448 planetas válidos y 0 descartados**. El lector encontró 24 F, 124 G, 140 K y 160 M. Las multiplicidades coinciden con el inventario de carpetas de planeta de cada sistema. El catálogo homónimo de la raíz contiene 451 planetas y se puede seleccionar por separado. La detección automática prioriza Troyanos. El Sistema Solar aporta ocho planetas a su etapa propia.

## Inventario y orden de ejecución

Los índices de celda empiezan en 0 y corresponden a Final.ipynb.

| Celdas | Funciones, variables y dependencias |
| --- | --- |
| 0, 2 | Importaciones y configuración. NumPy, SciPy, pandas, Matplotlib, tqdm, Tkinter y pickle. Constantes de pesos, niveles, malla y semilla. REGIONES_FILA, REGIONES_MULT, LEYENDA_*, SISTEMA_SOLAR, _CACHE_VERSION y _CACHE_DIR. |
| 4, 6 | _mostrar_o_cerrar, _safe_log10, _calcular_pesos, _pesos_validos, _asignar_estilos_sistema. Usan configuración, paquetes numéricos y Matplotlib. |
| 7, 8 | _calcular_limites_criticos, _bootstrap_limites_criticos, _sigma_log, _umbral_region, _kde_cov_fija, _cobertura_gauss, _intervalo_sigma, _dibujar_bandas_sigma, _filas_sigma, _guardar_tabla_sigma, _con_sufijo. El código de umbral HDR y covarianza fija se compartía con celdas posteriores. |
| 10, 12 | _set_cache_dir, _hash_cache, _cache_obtener, _cfg_leyenda, _n_entradas_leyenda, _filas_leyenda, _alto_leyenda. Preparan la caché y dimensiones de leyenda. |
| 14, 16 | extraer_datos_personalizados, construir_sistema_solar, preparar_sistema_solar. Producen el catálogo y la tabla solar. |
| 18, 20, 22, 24 | _dibujar_panel_islas, plot_sistemas_f_horizontal_gkm_cuadrados, plot_islands_por_tipo_estrella, plot_islands_zonas_estables2. La etapa islas activaba esta ruta heredada. |
| 26, 28 | JUPITER_UA, JUPITER_MASA, NIVELES_REGIONES, ZOOM_POR_TIPO, _dibujar_isolineas_difuminadas, _limites_por_nivel, _regiones_por_umbral, _fusionar_islas, _nivel_isla, _regiones_por_picos, _error_asimetrico, _txt_lim, _limites_masa_region, _masa_region_nominal, _txt_masa, _region_principal, _centro_tramo, _dist_norm y _bootstrap_regiones. La celda 26 define nombres requeridos por la 28 y 30. |
| 30, 32 | calcular_kde_panel, dibujar_panel_kde, _dibujar_panel_matriz, _filas_resumen, _escribir_texto_regiones, plot_matriz_tipo_multiplicidad y plot_figuras_por_tipo. Usan pesos y caché, más las celdas 26 y 28. La figura por tipo aplica el zoom configurado para F. |
| 34, 36 | analizar_kde_sistema_solar, _malla_kde, _ajuste_regiones y analizar_sistema_solar. La etapa solar usa la celda 30. Comparar tenía un ajuste separado. |
| 38, 39 | plot_tipos_espectrales_fila, ejecutar, ejecutar_sistema_solar, ETAPAS, ETAPAS_DEFECTO y bloque de entrada. Invocan las funciones anteriores. La celda 39 tiene un error de sintaxis. |

El orden del cuaderno corregido es importaciones → configuración → utilidades → lectura → KDE y regiones → bootstrap → figuras → ejecución → verificación. Los ocho bloques compartidos son estructuralmente idénticos a los del script. Las dos celdas adicionales lanzan el flujo y comprueban sus tablas.

## Hallazgos y correcciones

| ID | Severidad | Ubicación original | Causa y comportamiento anterior | Corrección | Efecto |
| --- | --- | --- | --- | --- | --- |
| A01 | Crítica | 14 · extraer_datos_personalizados | Imputaba 0 o 1 si faltaban parámetros físicos. | Valida campos obligatorios y registra archivo, planeta y motivo. | Evita logaritmos no finitos e imputaciones. Las 448 filas históricas se conservan. |
| A02 | Crítica | 14 · patrones de README y resumen | Coincidencias voraces y sufijos de unidad sin validar. | Rótulos por línea, números con signo, coma, punto y exponentes. Valida unidades y ambigüedad. | La prueba de 1,25e6 m² da 1,25 km². |
| A03 | Crítica | 14 · cálculo de Num_Planetas | El conteo dependía de cuántas filas superaban la lectura. | Inventario previo de carpetas de planeta y total explícito de catálogo cuando es consistente. | Un sistema de cinco conserva su multiplicidad tras cuatro descartes de prueba. |
| A04 | Media | 14 · manejo de excepciones | Los errores se perdían entre mensajes de progreso. | Registro por logging, descartes_lectura.csv e informe_lectura.txt. | Se puede reconciliar cada descarte con el total. |
| A05 | Crítica | 4 · _calcular_pesos | Suplía con ceros las áreas secundarias ausentes. | Columnas canónicas en km², alias históricos y validación de faltantes y contradicciones. | Evita fracciones de 1 por un esquema incompleto. |
| A06 | Media | 14 · alta de filas | Sin validación de duplicados y total. | Identidades normalizadas y opción de tolerar o exigir el total. | El histórico da 448 y la copia de la raíz 451. |
| B07 | Media | 7, 18, 28, 30, 36 · bw_method | Factores 0,50, 0,55 y 0,60 según la ruta. | Una configuración con 0,55 por defecto y opción --bw. | Diferencia nominal en la fila inferior a 2e-12 puntos porcentuales. |
| B08 | Crítica | 2, 28, 30 · mallas | Nominal a 150² y bootstrap a 250². | Una malla para ambos, configurable con --malla. | Se conservan las celdas nominales. Las réplicas usan esa misma resolución. |
| B09 | Media | 7, 18, 20, 22, 24 · rutas heredadas | Lógica de percentiles y umbrales distinta de la de picos. | Se retira el cálculo duplicado. Se conservan los nombres públicos. | La etapa islas obtiene los mismos picos y sus masas. |
| B10 | Media | 4 · _pesos_validos | El rango de los pesos siempre era no negativo por definición. La comprobación admitía pesos negativos. | Pesos finitos, no negativos y, para el KDE 2D, al menos tres positivos. | Se admiten pesos constantes positivos. |
| B11 | Media | 18, 36, 38 · pesos y filtros | Ciertos caminos daban 1e-12 a pesos cero o excluían sus filas antes de remuestrear. | Contribución exactamente cero para un peso cero. | Se preservan los recuentos cuando los datos son válidos. |
| B12 | Baja | 4, 30 · _safe_log10 | El nombre no delimitaba el uso del desplazamiento. | log1p se reserva a area y neto. Distancia y masa usan log10 con validación. | Las coordenadas no se desplazan. |
| B13 | Crítica | 7, 26, 30 · _sigma_log, _error_asimetrico | Pocas réplicas o una celda producían error cero. | Media celda como mínimo, error simétrico, recuento válido y marca de baja recuperación. | En G con cinco planetas, dos errores de masa antes impresos como 0 pasan a 4,108 y 7,337 M_Tierra en la regresión. |
| B14 | Media | 28 · _bootstrap_regiones | Los continue omitían causas y se podían unir islas de una réplica al asignarlas. | Contadores por panel y emparejamiento uno a uno en dos ejes. | La recuperación se calcula sobre todos los intentos. El intervalo queda condicionado a recuperar la isla. |
| B15 | Media | 8 · _guardar_tabla_sigma | Exportaba el percentil 3σ aun con colas insuficientes. | Exige diez observaciones esperadas por cola y exporta el estado. | Con 5337 válidas hay 7,2 por cola. El mínimo es 7408 válidas. |
| B16 | Crítica | 28, 30 · _limites_masa_region, _masa_region_nominal | La ruta alternativa recalculaba el umbral de masa por separado. | Un contorno para ambas coordenadas. Una proyección de una sola celda recibe su anchura. | G separa las masas neptunianas y gigantes. En K con seis planetas se corrige una masa de anchura cero. |
| B17 | Crítica | 26 · _fusionar_islas | Cajas cercanas podían fusionar componentes desconectadas. | Componentes 2D separadas. Se eleva el nivel del pico secundario si se solapan cajas. | G conserva dos regiones. El margen gap se conserva para el modo por umbral. |
| C18 | Media | 0, 14, 16 · Tkinter | Tkinter y los diálogos formaban parte de la ruta de entrada. | Importación local en --dialogos y modo --carpeta o detección local. | El script y el kernel funcionan sin pantalla con Agg. |
| C19 | Media | 7, 28 · _kde_cov_fija | Repetía las exponenciales por planeta y réplica. | Precalcula las gaussianas unitarias y combina sus contribuciones en bloques de 32. | La desviación máxima del núcleo es inferior a 8e-14 puntos porcentuales. |
| C20 | Crítica | 10, 30, 36 · _hash_cache y archivos pickle | Claves incompletas, escritura directa y carga sin protección. | Hash de entradas, parámetros y versiones. Reemplazo atómico y lector de datos primitivos. | Reutiliza ajustes válidos y recupera archivos corruptos. La v6 invalida v4. |
| C21 | Media | 2, 10 · _CACHE_DIR | Estado mutable y parámetros en celdas separadas. | Configuración inmutable y ámbito temporal por ejecución. | Cada llamada puede usar su carpeta y restaura el estado anterior al terminar. |
| C22 | Media | 4, 30, 32, 34, 36, 38 · ciclo de figura | Una excepción durante el dibujo o el guardado podía dejar figuras abiertas. | Cierre protegido y salida PNG/PDF desde la misma figura. | Se comprobó el cierre con el renderizador sin pantalla. |
| C23 | Media | 30, 34, 38 · rutas y CSV | Sobrescritura implícita y codificación desigual. | Rutas multiplataforma, nombres controlados, CSV UTF-8 con BOM y --sobrescribir explícito. | Se preservan los resultados históricos y el original. |
| C24 | Media | 6 · _asignar_estilos_sistema | zip omitía sistemas al agotar 280 combinaciones. | Estilo de línea por sistema y marcador para todos. | Se verificaron 310 estilos. Los contornos individuales comparten color y se distinguen por trazo. |
| C25 | Media | 12, 30, 34, 38 · leyendas | La reserva de altura dependía de estimaciones de entradas y fuente. | Se mantiene la reserva por filas y se guarda usando los límites ajustados al contenido. | El renderizador verificó que las leyendas F y solar caben debajo de la etiqueta X. |
| D01 | Crítica | 39 · última línea | Carácter 4 fuera de lugar tras ejecutar(...). | Punto de entrada con argparse independiente de los argumentos del kernel. | La regresión del original ejecutó las celdas 0–38 y emuló el selector. |
| D02 | Crítica | 36 · analizar_sistema_solar, _ajuste_regiones | Comparaba solo distancia y remuestreaba planetas. | Comparación en log-distancia y log-masa con el mismo KDE y remuestreo por sistema. | La pertenencia 3σ queda vacía si falta soporte de cola. |
| D03 | Media | 26 · _regiones_por_picos | La ventana de X se copiaba a Y. El cupo se aplicaba antes de fusionar. | Ventana centrada por eje y cupo después de aceptar cada caja. | Los límites nominales de la fila coinciden con el original. |
| D04 | Media | 28, 34 · remuestreo y filtro solar | Cambiaba a planetas con menos de tres sistemas y descartaba pesos solares constantes. | Remuestreo por sistemas desde dos grupos. Un sistema se identifica como intrasistema. El solar remuestrea planetas explícitamente. | Se distinguen incertidumbre entre sistemas y sensibilidad a la composición de uno. |
| D05 | Media | 26, 28, 30 · rótulos y cotas | Más/menos asimétrico, masa a dos decimales y detección de bordes con margen fijo. | Valor ± error a tres decimales, indicación <0.001 para errores positivos submilésimos y bordes por eje. | Los CSV conservan precisión completa. |
| D06 | Media | 8 · _filas_sigma | Encabezados en UA incluían límites de masa. | Columna Unidad con UA o M_Tierra y estado del intervalo. | Las magnitudes quedan identificadas en la tabla larga. |
| D07 | Media | 38 y 30 · ejecutar y matriz | Pedía catálogo extrasolar para ejecutar solar. La matriz podía aceptar filas solares. | Entrada solar independiente y filtro solar en figuras F/G/K/M. | Los 448 y los 8 planetas tienen figuras separadas. |
| D08 | Baja | 28, 30 · valor opcional de réplicas | Cero seleccionaba accidentalmente 1000 réplicas. | Cero activa cálculo nominal y marca el piso de resolución. | Se pueden probar y dibujar mapas nominales sin bootstrap involuntario. |

## Criterios numéricos

- El KDE principal conserva **bw=0.55**, normalización 0–100 % y malla 150×150. Las rutas heredadas 0,50 y 0,60 quedan sustituidas por la configuración. La covarianza fija permite combinar linealmente las gaussianas ponderadas. Con --covarianza-variable, SciPy vuelve a ajustar la covarianza en cada réplica.
- Los rectángulos proyectan en ambos ejes las celdas de cada componente. Pueden compartir distancia si sus masas están separadas, como en F. En la fila G se obtienen 0,093–0,290 UA y 1,700–2,054 UA. El segundo pico mide 71,00 % con contorno 70,70 %. Un nivel de 80,80 % no contiene ese pico en la muestra histórica.
- El error básico usa el cuantil de las desviaciones absolutas respecto al nominal en dex a la cobertura solicitada y le suma media celda por eje. Se convierte la semianchura a unidades físicas mediante la mitad de la diferencia entre ambos extremos exponenciados. Con menos de cinco recuperaciones se informa solo el piso. --error percentil usa la semianchura de los percentiles 15,865–84,135 con piso. --error std usa la desviación estándar con el mismo mínimo.
- Se marca † con recuperación inferior a 68 % o menos de cinco réplicas válidas. Los CSV identifican estado, unidad, recuentos y causas. Los métodos básico y percentil omiten 3σ con menos de 7408 recuperaciones. La tabla ofrece también el 3σ por dispersión estándar bajo hipótesis gaussiana.
- La carga genérica mediante pickle.load puede ejecutar código de archivos no confiables. El lector de la caché v6 restringe la resolución de funciones y clases, valida versión y clave y recalcula ante fallos. La primera ejecución corregida crea su propia caché. --sobrescribir permite regenerar salidas desde esa caché.

## Regresión sobre los 448 planetas

Se ejecutaron las funciones originales y corregidas sobre Troyanos, con semilla 12345, **100 réplicas por panel** y caché desactivada. Las tres etapas usan los límites de sus figuras, incluido el zoom F. Se emularon los diálogos del original y se omitió la celda con D01. Para el original se promediaron las dos semianchuras y se midió el máximo de densidad dentro del rectángulo.

En **40 de 41** correspondencias coinciden los cuatro límites nominales. **E** indica cambios de malla bootstrap común, asignación uno a uno y error con resolución. **M** añade el ancho de la única celda de masa en la región K con multiplicidad seis. Se indican el pico y, entre paréntesis, el contorno corregido. Distancia en UA y masa en M_Tierra.

| Tipo | Multiplicidad | Región | a_min antes → después | a_max antes → después | m_min antes → después | m_max antes → después | Pico % antes → después (contorno %) | Causa |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F | todos | 1→1 | 0.068 ± 0.001 → 0.068 ± 0.011 | 0.106 ± 0.010 → 0.106 ± 0.017 | 93.574 ± 6.109 → 93.574 ± 13.703 | 151.730 ± 10.166 → 151.730 ± 37.027 | 63.51 → 63.51 (60.60) | E |
| F | todos | 2→2 | 0.077 ± 0.010 → 0.077 ± 0.012 | 0.145 ± 0.029 → 0.145 ± 0.032 | 6.881 ± 1.133 → 6.881 ± 1.679 | 13.536 ± 2.268 → 13.536 ± 3.303 | 100.00 → 100.00 (90.90) | E |
| G | todos | 1→1 | 0.093 ± 0.021 → 0.093 ± 0.021 | 0.290 ± 0.084 → 0.290 ± 0.084 | 6.881 ± 1.201 → 6.881 ± 1.679 | 24.177 ± 8.672 → 24.177 ± 8.337 | 100.00 → 100.00 (90.90) | E |
| G | todos | 2→2 | 1.700 ± 0.304 → 1.700 ± 1.323 | 2.054 ± 0.927 → 2.054 ± 1.010 | 223.359 ± 193.487 → 223.359 ± 204.892 | 298.505 ± 657.330 → 298.505 ± 569.537 | 71.00 → 71.00 (70.70) | E |
| K | todos | 1→1 | 0.064 ± 0.006 → 0.064 ± 0.006 | 0.128 ± 0.012 → 0.128 ± 0.012 | 712.520 ± 234.461 → 712.520 ± 319.823 | 2272.959 ± 694.229 → 2272.959 ± 783.794 | 100.00 → 100.00 (90.90) | E |
| K | todos | 2→2 | 0.082 ± 0.012 → 0.082 ± 0.018 | 0.164 ± 0.033 → 0.164 ± 0.037 | 5.671 ± 1.021 → 5.671 ± 1.956 | 14.910 ± 4.540 → 14.910 ± 5.142 | 85.08 → 85.08 (80.80) | E |
| K | todos | 3→3 | 0.748 ± 0.282 → 0.748 ± 0.316 | 2.331 ± 0.574 → 2.331 ± 0.853 | 103.072 ± 52.882 → 103.072 ± 46.265 | 484.023 ± 190.050 → 484.023 ± 269.642 | 55.93 → 55.93 (50.50) | E |
| M | todos | 1→1 | 0.046 ± 0.007 → 0.046 ± 0.007 | 0.106 ± 0.011 → 0.106 ± 0.017 | 2.376 ± 0.266 → 2.376 ± 0.346 | 6.881 ± 0.798 → 6.881 ± 1.001 | 100.00 → 100.00 (90.90) | E |
| F | 3 | 1→1 | 0.059 ± 0.002 → 0.059 ± 0.004 | 0.090 ± 0.006 → 0.090 ± 0.009 | 99.615 ± 7.580 → 99.615 ± 12.672 | 183.150 ± 11.311 → 183.150 ± 13.956 | 97.10 → 97.10 (90.90) | E |
| F | 3 | 2→2 | 0.070 ± 0.010 → 0.070 ± 0.010 | 0.116 ± 0.014 → 0.116 ± 0.017 | 6.429 ± 1.952 → 6.429 ± 2.406 | 13.764 ± 2.556 → 13.764 ± 3.892 | 100.00 → 100.00 (90.90) | E |
| F | 3 | 3→3 | 0.289 ± 0.047 → 0.289 ± 0.054 | 0.403 ± 0.058 → 0.403 ± 0.076 | 39.958 ± 23.183 → 39.958 ± 27.083 | 69.830 ± 40.769 → 69.830 ± 38.997 | 73.22 → 73.22 (70.70) | E |
| F | 4 | 1→1 | 0.043 ± 0.009 → 0.043 ± 0.015 | 0.048 ± 0.011 → 0.048 ± 0.022 | 4.284 ± 0.358 → 4.284 ± 0.765 | 5.248 ± 0.398 → 5.248 ± 0.668 | 42.78 → 42.78 (40.40) | E |
| F | 4 | 2→2 | 0.111 ± 0.021 → 0.111 ± 0.028 | 0.142 ± 0.023 → 0.142 ± 0.021 | 12.436 ± 2.511 → 12.436 ± 3.845 | 16.862 ± 2.823 → 16.862 ± 2.145 | 100.00 → 100.00 (90.90) | E |
| F | 5 | 1→1 | 0.148 ± 0.033 → 0.148 ± 0.047 | 0.198 ± 0.044 → 0.198 ± 0.047 | 6.111 ± 0.423 → 6.111 ± 1.091 | 6.764 ± 0.574 → 6.764 ± 1.208 | 83.01 → 83.01 (80.80) | E |
| F | 5 | 2→2 | 0.539 ± 0.226 → 0.539 ± 0.243 | 1.240 ± 0.321 → 1.240 ± 0.448 | 6.111 ± 0.365 → 6.111 ± 0.466 | 8.718 ± 0.743 → 8.718 ± 1.341 | 79.82 → 79.82 (70.70) | E |
| F | 5 | 3→3 | 1.094 ± 0.086 → 1.094 ± 0.068 | 1.730 ± 0.103 → 1.730 ± 0.108 | 21.733 ± 1.026 → 21.733 ± 0.552 | 29.469 ± 1.270 → 29.469 ± 2.245 | 100.00 → 100.00 (90.90) | E |
| G | 3 | 1→1 | 0.077 ± 0.015 → 0.077 ± 0.017 | 0.212 ± 0.047 → 0.212 ± 0.061 | 6.247 ± 1.444 → 6.247 ± 1.524 | 21.949 ± 4.823 → 21.949 ± 7.569 | 100.00 → 100.00 (90.90) | E |
| G | 3 | 2→2 | 1.810 ± 0.699 → 1.810 ± 0.641 | 4.114 ± 2.796 → 4.114 ± 1.479 | 184.093 ± 73.738 → 184.093 ± 82.632 | 484.023 ± 467.711 → 484.023 ± 269.642 | 75.07 → 75.07 (70.70) | E |
| G | 4 | 1→1 | 0.049 ± 0.013 → 0.049 ± 0.011 | 0.099 ± 0.031 → 0.099 ± 0.029 | 184.093 ± 32.459 → 184.093 ± 44.925 | 439.423 ± 48.500 → 439.423 ± 107.233 | 100.00 → 100.00 (90.90) | E |
| G | 4 | 2→2 | 0.128 ± 0.038 → 0.128 ± 0.045 | 0.329 ± 0.077 → 0.329 ± 0.095 | 7.579 ± 2.401 → 7.579 ± 2.613 | 21.949 ± 9.189 → 21.949 ± 9.852 | 90.63 → 90.63 (80.80) | E |
| G | 4 | 3→3 | 1.092 ± 0.189 → 1.092 ± 0.243 | 2.054 ± 0.347 → 2.054 ± 0.458 | 151.730 ± 93.024 → 151.730 ± 110.163 | 439.423 ± 202.856 → 439.423 ± 219.380 | 54.51 → 54.51 (50.50) | E |
| G | 5 | 1→1 | 0.082 ± 0.015 → 0.082 ± 0.018 | 0.175 ± 0.078 → 0.175 ± 0.086 | 5.148 ± 1.214 → 5.148 ± 0.749 | 10.129 ± 1.699 → 10.129 ± 1.474 | 100.00 → 100.00 (90.90) | E |
| G | 5 | 2→2 | 0.309 ± 0.006 → 0.309 ± 0.029 | 0.512 ± 0.010 → 0.512 ± 0.016 | 84.952 ± 0.000 → 84.952 ± 4.108 | 151.730 ± 0.000 → 151.730 ± 7.337 | 66.99 → 66.99 (60.60) | E |
| G | 5 | 3→3 | 0.849 ± 0.454 → 0.849 ± 0.540 | 2.188 ± 0.880 → 2.188 ± 1.232 | 18.090 ± 11.148 → 18.090 ± 12.130 | 52.391 ± 24.654 → 52.391 ± 41.401 | 45.26 → 45.26 (40.40) | E |
| G | 6 | 1→1 | 0.056 ± 0.001 → 0.056 ± 0.002 | 0.128 ± 0.002 → 0.128 ± 0.004 | 1700.760 ± 38.889 → 1700.760 ± 82.237 | 4925.546 ± 261.373 → 4925.546 ± 238.167 | 100.00 → 100.00 (90.90) | E |
| G | 6 | 2→2 | 1.320 ± 0.144 → 1.320 ± 0.209 | 3.862 ± 0.394 → 3.862 ± 0.612 | 63.566 ± 13.618 → 63.566 ± 42.622 | 271.000 ± 61.275 → 271.000 ± 181.711 | 87.20 → 87.20 (80.80) | E |
| K | 3 | 1→1 | 0.064 ± 0.012 → 0.064 ± 0.018 | 0.175 ± 0.046 → 0.175 ± 0.050 | 5.671 ± 2.300 → 5.671 ± 2.373 | 26.631 ± 11.652 → 26.631 ± 17.856 | 67.35 → 67.35 (60.60) | E |
| K | 3 | 2→2 | 0.068 ± 0.006 → 0.068 ± 0.006 | 0.136 ± 0.015 → 0.136 ± 0.022 | 1048.887 ± 29.660 → 1048.887 ± 50.717 | 3037.667 ± 84.018 → 3037.667 ± 146.881 | 100.00 → 100.00 (90.90) | E |
| K | 3 | 3→3 | 0.849 ± 0.287 → 0.849 ± 0.358 | 1.810 ± 1.078 → 1.810 ± 0.764 | 113.533 ± 101.242 → 113.533 ± 76.126 | 398.933 ± 622.410 → 398.933 ± 396.193 | 64.62 → 64.62 (60.60) | E |
| K | 4 | 1→1 | 0.060 ± 0.002 → 0.060 ± 0.002 | 0.120 ± 0.005 → 0.120 ± 0.011 | 398.933 ± 24.210 → 398.933 ± 19.290 | 1048.887 ± 57.653 → 1048.887 ± 50.717 | 100.00 → 100.00 (90.90) | E |
| K | 4 | 2→2 | 0.082 ± 0.016 → 0.082 ± 0.024 | 0.175 ± 0.042 → 0.175 ± 0.050 | 5.671 ± 0.952 → 5.671 ± 1.384 | 13.536 ± 2.891 → 13.536 ± 3.303 | 96.74 → 96.74 (90.90) | E |
| K | 4 | 3→3 | 1.092 ± 0.379 → 1.092 ± 0.461 | 2.331 ± 0.395 → 2.331 ± 0.369 | 223.359 ± 26.704 → 223.359 ± 53.007 | 439.423 ± 54.449 → 439.423 ± 107.233 | 63.84 → 63.84 (60.60) | E |
| K | 5 | 1→1 | 0.064 ± 0.000 → 0.064 ± 0.002 | 0.112 ± 0.000 → 0.112 ± 0.004 | 712.520 ± 20.962 → 712.520 ± 103.680 | 3685.580 ± 105.891 → 3685.580 ± 178.210 | 100.00 → 100.00 (90.90) | E |
| K | 6 | 1→1 | 0.072 ± 0.008 → 0.072 ± 0.007 | 0.154 ± 0.025 → 0.154 ± 0.024 | 4.674 ± 0.564 → 4.674 ± 1.141 | 9.195 ± 1.994 → 9.195 ± 2.244 | 100.00 → 100.00 (90.90) | E |
| K | 6 | 2→2 | 2.817 ± 0.232 → 2.817 ± 0.628 | 3.000 ± 0.365 → 3.000 ± 1.063 | 103.072 ± 7.846 → 98.208 ± 19.106 | 103.072 ± 11.101 → 108.176 ± 31.813 | 62.14 → 62.14 (60.60) | M |
| M | 3 | 1→1 | 0.036 ± 0.007 → 0.036 ± 0.008 | 0.087 ± 0.016 → 0.087 ± 0.019 | 2.157 ± 0.505 → 2.157 ± 0.744 | 6.881 ± 1.703 → 6.881 ± 2.305 | 100.00 → 100.00 (90.90) | E |
| M | 4 | 1→1 | 0.077 ± 0.007 → 0.077 ± 0.012 | 0.136 ± 0.018 → 0.136 ± 0.022 | 3.175 ± 0.432 → 3.175 ± 0.775 | 8.348 ± 1.635 → 8.348 ± 2.037 | 100.00 → 100.00 (90.90) | E |
| M | 5 | 1→1 | 0.077 ± 0.024 → 0.077 ± 0.022 | 0.145 ± 0.051 → 0.145 ± 0.051 | 2.617 ± 0.282 → 2.617 ± 0.381 | 3.175 ± 0.376 → 3.175 ± 0.462 | 100.00 → 100.00 (90.90) | E |
| M | 7 | 1→1 | 0.012 ± 0.012 → 0.012 ± 0.003 | 0.016 ± 0.015 → 0.016 ± 0.004 | 1.208 ± 0.286 → 1.208 ± 0.176 | 1.465 ± 0.310 → 1.465 ± 0.142 | 100.00 → 100.00 (90.90) | E |
| Solar | 8 | 1→1 | 0.384 ± 0.236 → 0.384 ± 0.235 | 1.691 ± 0.557 → 1.691 ± 0.684 | 0.066 ± 0.194 → 0.066 ± 0.130 | 4.681 ± 1.348 → 4.681 ± 9.264 | 18.65 → 18.65 (11.60) | E |
| Solar | 8 | 2→2 | 4.274 ± 1.738 → 4.274 ± 2.618 | 7.809 ± 3.027 → 7.809 ± 3.617 | 119.075 ± 58.575 → 119.075 ± 125.563 | 518.408 ± 219.351 → 518.408 ± 663.799 | 100.00 → 100.00 (90.90) | E |

## Rendimiento y equivalencia

Tiempo de pared en la misma máquina Windows, semilla y 100 réplicas, con un hilo BLAS. Las tres primeras filas incluyen PNG, PDF e intervalos. Las dos últimas aíslan el núcleo KDE con los mismos pesos y sorteos, sin cambiar ni la malla ni la covarianza. La etapa corregida incluye el coste adicional de dibujar los contornos individuales.

| Medición | Original (s) | Corregido (s) | Aceleración |
| --- | ---: | ---: | ---: |
| Figura en fila | 44.99 | 8.97 | 5.0× |
| Figuras por multiplicidad | 85.00 | 19.19 | 4.4× |
| Figura solar | 4.84 | 1.40 | 3.5× |
| Núcleo G, malla 150² | 1.344 | 0.109 | 12.4× |
| Núcleo G, malla 250² | 3.230 | 0.302 | 10.7× |

Las desviaciones máximas del núcleo fueron **7,11e-14** puntos porcentuales a 150² y **5,68e-14** a 250², por debajo de la tolerancia de **2e-12**. Las diferencias de los errores en la tabla se deben a las reglas estadísticas, de malla y de asignación.

## Sistema Solar y validación

Júpiter reproduce **96,72962 %** de densidad relativa. Los cuatro bordes nominales reproducen las referencias tras redondear a dos decimales. La tabla usa los valores finales con **5000 réplicas solares**.

| Región | Referencia a_min | Corregido a_min | Referencia a_max | Corregido a_max | Recuperación |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 0,38 ± 0,19 UA | 0,384 ± 0,214 UA | 1,69 ± 0,46 UA | 1,691 ± 0,856 UA | 3766/5000 |
| 2 | 4,27 ± 1,74 UA | 4,274 ± 1,102 UA | 7,81 ± 3,03 UA | 7,809 ± 2,389 UA | 4395/5000 |

Los errores difieren por la malla compartida, el emparejamiento uno a uno y la semianchura medida alrededor del nominal con piso de resolución. El remuestreo solar identifica explícitamente ocho planetas, con orden reproducible por distancia. El original les asignaba etiquetas de sistema individuales y las ordenaba por nombre para sortearlas. El panel registró 27 réplicas con KDE válido sin región asignada. Los rótulos lineales representan semianchuras y los extremos de los intervalos exportados se calculan en dex y se transforman a unidades físicas.

En la prueba sintética de verdad conocida, la población es una mezcla de dos gaussianas convolucionadas con el kernel poblacional. Una malla de referencia de 601² verifica independientemente las proyecciones analíticas del contorno de 90,9 %. Una muestra fija de cuadratura de 450 planetas recupera los ocho límites dentro del error reportado.

La cobertura se evaluó con 44 catálogos independientes de 180 planetas y 150 réplicas por catálogo. El intervalo simétrico reportado logró **72,7 %** medio, compatible con 68,3 % según el criterio por catálogo de la prueba. Las coberturas de a_min, a_max, m_min y m_max fueron 72,7 %, 61,4 %, 81,8 % y 63,6 % en la primera isla y 81,8 %, 75,0 %, 84,1 % y 61,4 % en la segunda. La semianchura percentil con piso obtuvo 57,4 % medio en la misma simulación. La medición se limita a la mezcla, ancho de banda y malla declarados.

| Verificación | Resultado |
| --- | --- |
| Pruebas automáticas | 13 aprobadas. Incluyen lector real y sintético, regresión nominal contra el original, cobertura, vectores KDE, archivos dañados, pesos nulos, menos de tres datos, varianza cero, NaN/inf, un único sistema y leyendas. |
| Invariantes | KDE finito con mínimo ≥0 y máximo 100. Límites crecientes y dentro de los ejes. Rectángulos sin solape en dos dimensiones. Errores positivos y recuperación acotada. Se validaron 84 registros de región en las seis tablas finales. |
| Ejecución completa | Las seis etapas se ejecutaron con el catálogo de 448, 1000 réplicas extrasolares por panel y 5000 solares. El script tardó 122,4 s y el kernel de Jupyter 124,9 s durante esta comprobación concurrente. Coincidieron byte por byte 16 CSV, 6 TXT y 9 PNG. También coincidió el contenido de los 9 PDF al normalizar su fecha de creación. |
| Reutilización de caché | La regeneración de fila, tipo y solar reutilizó 268 resultados de caché, incluidos los KDE de sistemas individuales. Los CSV, TXT y PNG conservaron sus hashes. La prueba independiente de kde_solar generó area y fraccion. En neto, los ocho pesos solares son cero y el ajuste se omite con un aviso. |

## Ejecución

Desde la raíz del proyecto, con Python 3.13 y las dependencias de archivos/requirements.txt.

    python archivos/mapas_estabilidad_robusto.py fila tipo solar --carpeta Troyanos --salida resultados_estabilidad --exigir-total
    python -m pytest -q -s archivos/tests_verificacion.py

La celda «Ejecutar con el catálogo local» permite editar origen, etapas y destino. Para regenerar en el mismo destino, pasa sobrescribir=True a ejecutar. El cuaderno se entrega sin salidas guardadas.
