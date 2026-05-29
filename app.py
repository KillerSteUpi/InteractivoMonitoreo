import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, MultiPoint
from shapely.ops import voronoi_diagram
import folium
from folium.plugins import HeatMap, MarkerCluster
from streamlit_folium import st_folium
import plotly.express as px
import requests
from datetime import datetime, timedelta
import urllib3
import json
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Tablero Territorial CDMX", layout="wide")
st.title("📍 Sistema de Inteligencia Territorial")
st.markdown("---")

# ==========================================
# 2. CARGA DE DATOS OPERATIVOS (SENSORES TERRITORIALES)
# ==========================================
@st.cache_data(ttl=300)
def cargar_datos():
    try:
        if not os.path.exists("mis_datos.json"): return pd.DataFrame(), gpd.GeoDataFrame()
        df = pd.read_json("mis_datos.json", orient="index")
        if df.empty: return pd.DataFrame(), gpd.GeoDataFrame()

        df['nombre_sitio'] = df.index.astype(str).str.replace("_", " ")
        if 'lat' not in df.columns: df['lat'] = None
        if 'lon' not in df.columns: df['lon'] = None
            
        df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
        df['lon'] = pd.to_numeric(df['lon'], errors='coerce')
        df = df.dropna(subset=['lat', 'lon'])
        
        df = df[(df['lat'] > 19.0) & (df['lat'] < 19.8) & (df['lon'] > -99.6) & (df['lon'] < -98.8)]
        
        if df.empty: return pd.DataFrame(), gpd.GeoDataFrame()

        geometria = [Point(xy) for xy in zip(df['lon'], df['lat'])]
        gdf = gpd.GeoDataFrame(df, geometry=geometria, crs="EPSG:4326")
        return df, gdf
    except Exception as e:
        return pd.DataFrame(), gpd.GeoDataFrame()

# ==========================================
# 3. CARGA DE CAPA DE COLONIAS OFICIALES
# ==========================================
@st.cache_data(ttl=3600)
def cargar_colonias():
    try:
        if not os.path.exists("georef-mexico-colonia.json"):
            return gpd.GeoDataFrame()
            
        with open("georef-mexico-colonia.json", encoding="utf-8") as f:
            datos_col = json.load(f)
            
        features = []
        for item in datos_col:
            feat = item.get("geo_shape")
            if not feat: continue
            
            nombre = item.get("col_name", [""])[0] if isinstance(item.get("col_name"), list) else item.get("col_name", "")
            alcaldia = item.get("mun_name", [""])[0] if isinstance(item.get("mun_name"), list) else item.get("mun_name", "")
            
            feat["properties"] = {
                "colonia": str(nombre).upper(),
                "alcaldia": str(alcaldia).upper()
            }
            features.append(feat)
            
        gdf_col = gpd.GeoDataFrame.from_features({"type": "FeatureCollection", "features": features})
        gdf_col = gdf_col.set_crs("EPSG:4326")
        return gdf_col
    except Exception as e:
        return gpd.GeoDataFrame()

df_datos, gdf_datos = cargar_datos()
gdf_colonias = cargar_colonias()

if not df_datos.empty:
    st.sidebar.header("⚙️ Panel de Control")
    
    # --- VISOR DE COLONIAS ---
    st.sidebar.markdown("### 🏘️ Visor de Colonias")
    if not gdf_colonias.empty:
        lista_todas_colonias = sorted([c for c in gdf_colonias['colonia'].dropna().unique() if str(c).strip() != ""])
        colonias_seleccionadas = st.sidebar.multiselect(
            "Selecciona la colonia para iluminar su límite:", 
            lista_todas_colonias,
            placeholder="Despliega o escribe una colonia..."
        )
    else:
        colonias_seleccionadas = []
        
    st.sidebar.markdown("---")
    
    # --- FILTRO OPERATIVO ---
    st.sidebar.markdown("### 🔍 Buscador de Sensores")
    texto_filtro = st.sidebar.text_input("Filtrar por nombre de sitio:", placeholder="Ej: ZARAGOZA, POZO...")
    lista_deleg = sorted(df_datos['delegacion'].dropna().unique())
    deleg_selec = st.sidebar.multiselect("Filtrar sensores por Demarcación:", lista_deleg)
    
    df_f = df_datos.copy()
    if texto_filtro:
        df_f = df_f[df_f['nombre_sitio'].str.contains(texto_filtro, case=False, na=False)]
    if deleg_selec:
        df_f = df_f[df_f['delegacion'].isin(deleg_selec)]

    st.sidebar.markdown("---")
    modo_vista = st.sidebar.radio(
        "Capa Operativa (Aplica a Sensores):",
        ["1. Clusters", "2. Radios", "3. Sectores", "4. Calor", "5. Voronoi"]
    )

    # ==========================================
    # 4. CONSTRUCCIÓN DEL MAPA TERRITORIAL
    # ==========================================
    if colonias_seleccionadas and not gdf_colonias.empty:
        gdf_col_filtradas = gdf_colonias[gdf_colonias['colonia'].isin(colonias_seleccionadas)]
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            c_lat = gdf_col_filtradas.geometry.centroid.y.mean()
            c_lon = gdf_col_filtradas.geometry.centroid.x.mean()
    elif not df_f.empty:
        c_lat, c_lon = df_f['lat'].mean(), df_f['lon'].mean()
    else:
        c_lat, c_lon = 19.4326, -99.1332
        
    mapa = folium.Map(location=[c_lat, c_lon], zoom_start=13 if colonias_seleccionadas else 11, tiles="cartodbpositron")
    
    try:
        folium.GeoJson("perimetro_cdmx.json", name="CDMX", style_function=lambda x: {'color': '#2C3E50', 'weight': 2, 'dashArray': '5, 5'}).add_to(mapa)
    except: pass

    if colonias_seleccionadas and not gdf_colonias.empty:
        folium.GeoJson(
            gdf_col_filtradas,
            name="Colonias Seleccionadas",
            style_function=lambda x: {'fillColor': '#F1C40F', 'color': '#E67E22', 'weight': 3, 'fillOpacity': 0.3},
            tooltip=folium.GeoJsonTooltip(fields=['colonia', 'alcaldia'], aliases=['Colonia:', 'Demarcación:'])
        ).add_to(mapa)

    if not df_f.empty:
        if modo_vista == "1. Clusters":
            cluster = MarkerCluster().add_to(mapa)
            for i, r in df_f.iterrows():
                folium.CircleMarker(
                    location=[r['lat'], r['lon']],
                    radius=7, color="#2C3E50", fill=True, fill_color="#922A27", fill_opacity=0.9,
                    tooltip=f"🏢 {r['nombre_sitio']}",
                    popup=folium.Popup(f"<b>🏢 {r['nombre_sitio']}</b>", max_width=300)
                ).add_to(cluster)
        elif modo_vista == "2. Radios":
            for i, r in df_f.iterrows():
                folium.Circle([r['lat'], r['lon']], radius=500, color="#0096FF", fill=True, tooltip=f"📍 {r['nombre_sitio']}", popup=folium.Popup(f"<b>📍 {r['nombre_sitio']}</b>", max_width=300)).add_to(mapa)
        elif modo_vista == "3. Sectores":
            if 'delegacion' in df_f.columns:
                gdf_f = gpd.GeoDataFrame(df_f, geometry=[Point(xy) for xy in zip(df_f['lon'], df_f['lat'])], crs="EPSG:4326")
                sectores = gdf_f.dissolve(by='delegacion')
                sectores['geometry'] = sectores.geometry.convex_hull
                sectores_validos = sectores[sectores.geometry.type.isin(['Polygon', 'MultiPolygon'])]
                if not sectores_validos.empty:
                    folium.GeoJson(sectores_validos, style_function=lambda x: {'fillColor': '#FF6400', 'color': '#FF6400', 'weight': 2, 'fillOpacity': 0.4}, tooltip=folium.GeoJsonTooltip(fields=['delegacion'], aliases=['Delegación:'])).add_to(mapa)
        elif modo_vista == "4. Calor":
            datos_calor = [[r['lat'], r['lon']] for i, r in df_f.iterrows()]
            HeatMap(datos_calor, radius=15, blur=10).add_to(mapa)
        elif modo_vista == "5. Voronoi":
            if len(df_f) > 3:
                try:
                    puntos = MultiPoint([(r.lon, r.lat) for i, r in df_f.iterrows()])
                    regiones_voronoi = voronoi_diagram(puntos)
                    gdf_voronoi = gpd.GeoDataFrame(geometry=[geom for geom in regiones_voronoi.geoms], crs="EPSG:4326")
                    folium.GeoJson(gdf_voronoi, style_function=lambda x: {'fillColor': '#28B463', 'color': '#196F3D', 'weight': 2, 'fillOpacity': 0.2}).add_to(mapa)
                    for i, r in df_f.iterrows():
                        folium.CircleMarker([r['lat'], r['lon']], radius=4, color='#E74C3C', fill=True, fill_opacity=1, tooltip=f"🏢 {r['nombre_sitio']}", popup=folium.Popup(f"<b>🏢 {r['nombre_sitio']}</b>", max_width=300)).add_to(mapa)
                except Exception as e:
                    st.error(f"⚠️ Error matemático al calcular polígonos de Voronoi: {e}")
            else:
                st.warning("Se requieren al menos 4 puntos en pantalla para calcular áreas de Voronoi.")

    st_folium(mapa, width=1200, height=550)

    # ==========================================
    # 5. MÉTRICAS EJECUTIVAS
    # ==========================================
    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("Sensores en pantalla", len(df_f))
    if 'max' in df_f.columns:
        c2.metric("Presión Promedio", round(pd.to_numeric(df_f['max'], errors='coerce').mean(), 3))
    c3.metric("Demarcaciones Filtradas", df_f['delegacion'].nunique())

    # ==========================================
    # 6. MONITOREO DINÁMICO (REAL SCADA API)
    # ==========================================
    st.markdown("---")
    st.header("🚨 Monitoreo Dinámico de Telemetría (SCADA Real)")

    def obtener_datos_scada_reales():
        """Consumo real de la API SCADA leyendo de st.secrets"""
        try:
            api_url = st.secrets["api_scada"]["url"]
            token = st.secrets["api_scada"]["token"]
            sitios_config = st.secrets["sitios"]
        except KeyError:
            st.error("⚠️ Faltan credenciales en la configuración de Streamlit Cloud (Secrets).")
            return []
            
        headers = {'nexustoken': token, 'Content-Type': 'application/json'}
        ahora = datetime.now()
        end_ts = int(ahora.timestamp() * 1000)
        start_ts = int((ahora - timedelta(days=3)).timestamp() * 1000)
        
        datos_recolectados = []
        
        for nombre_sitio, config in sitios_config.items():
            uid = config.get("uid")
            min_val = float(config.get("min", 0.0))
            max_val = float(config.get("max", 0.0))
            lat = float(config.get("lat", 0.0))
            lon = float(config.get("lon", 0.0))
            delegacion = config.get("delegacion", "N/A")
            
            url_consulta = f"{api_url}/{uid}/last-data"
            payload = {"uids": [uid], "startTs": start_ts, "endTs": end_ts, "dataSource": "RAW"}
            
            try:
                # Petición a la API SCADA
                respuesta = requests.post(url_consulta, headers=headers, json=payload, verify=False, timeout=15)
                
                if respuesta.status_code == 200:
                    data_json = respuesta.json()
                    es_flatline = False
                    historial_caidas = "Estable (Últimos 3 días)"
                    ultimo_registro = {}
                    
                    if isinstance(data_json, list) and len(data_json) > 0:
                        # Ordenamos cronológicamente
                        data_json = sorted(data_json, key=lambda x: x.get("timeStamp", 0))
                        datos_validos = [d for d in data_json if d.get("value") is not None and str(d.get("value")).strip().upper() != "N/A" and str(d.get("value")).strip() != ""]
                        
                        # --- Detección de Flatline ---
                        if len(datos_validos) > 1:
                            ts_actual = int(datetime.now().timestamp())
                            ts_limite = ts_actual - (8 * 3600)
                            datos_recientes = [d for d in datos_validos if d.get("timeStamp", 0) >= ts_limite]
                            if len(datos_recientes) >= 3:
                                valores_recientes = [d.get("value") for d in datos_recientes]
                                valor_actual = valores_recientes[-1]
                                if len(set(valores_recientes)) == 1 and valor_actual not in [0, 0.0]:
                                    es_flatline = True
                        
                        # --- Detección de Caídas ---
                        if len(datos_validos) == 0:
                            historial_caidas = "100% Tramas vacías (Últimos 3 días)"
                        else:
                            paquete_final = data_json[-1]
                            if paquete_final.get("value") is None or str(paquete_final.get("value")).strip() == "":
                                ts_ultimo_valido = datos_validos[-1].get("timeStamp")
                                ts_ultimo_paquete = paquete_final.get("timeStamp")
                                if ts_ultimo_valido and ts_ultimo_paquete:
                                    hueco_actual = ts_ultimo_paquete - ts_ultimo_valido
                                    if hueco_actual > (6 * 3600):
                                        caida_actual_str = datetime.fromtimestamp(ts_ultimo_valido).strftime('%d/%m/%Y %H:%M')
                                        horas_actuales = round(hueco_actual / 3600, 1)
                                        historial_caidas = f"Falla ACTUAL: Sin datos desde {caida_actual_str} ({horas_actuales}h)"
                        
                        ultimo_registro = datos_validos[-1] if datos_validos else data_json[-1]
                    else:
                        ultimo_registro = data_json if isinstance(data_json, dict) else {}
                    
                    epoch_ts = ultimo_registro.get("timeStamp")
                    valor_sensor = ultimo_registro.get("value")
                    fecha_conexion = datetime.fromtimestamp(epoch_ts) if epoch_ts is not None else None
                    
                    datos_recolectados.append({
                        "sensor": nombre_sitio,
                        "delegacion": delegacion,
                        "lat": lat,
                        "lon": lon,
                        "min_val": min_val,
                        "max_val": max_val,
                        "valor": valor_sensor,
                        "ultima_conexion": fecha_conexion,
                        "es_flatline": es_flatline,
                        "historial_caidas": historial_caidas
                    })
                else:
                    # Falló la API para este sensor
                    pass
            except Exception as e:
                # Falló la red
                pass
                
        return datos_recolectados

    def procesar_logica_scada(datos):
        df = pd.DataFrame(datos)
        if df.empty: return df
        
        df['ultima_conexion'] = pd.to_datetime(df['ultima_conexion'], errors='coerce')
        fecha_sin_senal = datetime.now() - timedelta(days=2)
        fecha_trancado = datetime.now() - timedelta(hours=24)
        
        def evaluar_estado(fila):
            v = fila.get('valor')
            fecha = fila.get('ultima_conexion')
            min_v = fila.get('min_val', 0)
            max_v = fila.get('max_val', 0)
            flatline = fila.get('es_flatline', False)
            
            if pd.isna(fecha) or fecha < fecha_sin_senal: return "Sin Señal"
            if fecha < fecha_trancado: return "Desactualizado"
            if flatline: return "Dato Trancado"
            if pd.isna(v) or v is None or str(v).strip() == "": return "DESCONEXION"
            if str(v).strip().upper() == "N/A": return "NO HAY DATO"
            
            try:
                val_num = float(v)
                if val_num == 0 or val_num == 0.0: return "SITIO EN 0"
                elif val_num > max_v: return "Alarma: Nivel Alto"
                elif val_num < min_v: return "Alarma: Nivel Bajo"
                else: return "Operación Normal"
            except ValueError:
                return "Error de Formato"

        df['estado'] = df.apply(evaluar_estado, axis=1)
        df['valor'] = df['valor'].fillna('')
        return df

    def generar_html_interactivo(df):
        total_puntos = len(df)
        colores_estados = {
            'Operación Normal': '#28a745', 'Sin Señal': '#dc3545', 'SITIO EN 0': '#ffc107', 
            'DESCONEXION': '#6c757d', 'NO HAY DATO': '#17a2b8', 'Alarma: Nivel Alto': '#fd7e14', 
            'Alarma: Nivel Bajo': '#6f42c1', 'Dato Trancado': '#e83e8c', 'Desactualizado': '#856404'
        }
        
        # 1. Gráfica Pastel
        conteo = df['estado'].value_counts().reset_index()
        conteo.columns = ['Estado', 'Cantidad']
        fig_pastel = px.pie(conteo, values='Cantidad', names='Estado', title=f'Diagnóstico General<br><sup style="color:gray; font-size:14px;">Total de puntos: {total_puntos}</sup>', color='Estado', color_discrete_map=colores_estados)
        html_pastel = fig_pastel.to_html(full_html=False, include_plotlyjs='cdn', div_id='grafica_plotly')

        # 2. Mapa Interactivo Plotly
        df_mapa = df[(df['lat'] != 0.0) & (df['lon'] != 0.0)].copy()
        if not df_mapa.empty:
            fig_mapa = px.scatter_mapbox(
                df_mapa, lat="lat", lon="lon", hover_name="sensor",
                hover_data={"estado": True, "delegacion": True, "valor": True, "lat": False, "lon": False},
                color="estado", color_discrete_map=colores_estados,
                zoom=10, center={"lat": 19.4326, "lon": -99.1332}, height=450,
                title="Ubicación de Infraestructura en Falla / Normal"
            )
            fig_mapa.update_layout(mapbox_style="carto-positron", title_x=0.5, margin=dict(t=60, b=10, l=10, r=10))
            html_mapa = fig_mapa.to_html(full_html=False, include_plotlyjs=False)
        else:
            html_mapa = "<div class='alert alert-warning text-center mt-4'>No hay coordenadas válidas para mostrar el mapa.</div>"

        # 3. Resumen Ejecutivo
        df['transmite'] = df['estado'].isin(['Operación Normal', 'SITIO EN 0', 'Alarma: Nivel Alto', 'Alarma: Nivel Bajo'])
        resumen = df.groupby('delegacion').agg(Total_Equipos=('sensor', 'count'), Transmitiendo=('transmite', 'sum')).reset_index()
        resumen['Sin_Transmision'] = resumen['Total_Equipos'] - resumen['Transmitiendo']
        resumen['Conectividad'] = (resumen['Transmitiendo'] / resumen['Total_Equipos'] * 100).round(1).astype(str) + '%'
        tabla_resumen_html = resumen.rename(columns={'delegacion': 'Alcaldía', 'Total_Equipos': 'Total de Sitios', 'Transmitiendo': 'En Línea', 'Sin_Transmision': 'Desconectados', 'Conectividad': 'Nivel de Conectividad'}).to_html(classes='table table-bordered table-striped text-center align-middle', index=False)

        # 4. Detalle
        df_vista = df.copy()
        df_vista['ultima_conexion'] = pd.to_datetime(df_vista['ultima_conexion']).dt.strftime('%Y-%m-%d %H:%M:%S').fillna('Sin registro')
        df_vista['rango'] = df_vista['min_val'].astype(str) + " a " + df_vista['max_val'].astype(str)
        df_vista['coordenadas'] = df_vista['lat'].astype(str) + ", " + df_vista['lon'].astype(str)
        
        columnas_ordenadas = ['sensor', 'delegacion', 'coordenadas', 'valor', 'rango', 'historial_caidas', 'ultima_conexion', 'estado']
        tabla_detalle_html = df_vista[columnas_ordenadas].to_html(classes='table table-striped table-hover table-bordered text-center align-middle', index=False, table_id="tabla_datos")

        html_final = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body {{ background-color: #f4f6f9; padding: 20px; }}
                .card {{ border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); padding: 20px; background: white; }}
                .estado-normal {{ color: #155724; background-color: #d4edda; font-weight: bold; }}
                .estado-sin-senal {{ color: #721c24; background-color: #f8d7da; font-weight: bold; }}
                .estado-trancado {{ color: #fff; background-color: #e83e8c; font-weight: bold; }}
                .estado-desconexion {{ color: #fff; background-color: #6c757d; font-weight: bold; }}
                .estado-cero {{ color: #856404; background-color: #fff3cd; font-weight: bold; }}
                .estado-alto {{ color: #fff; background-color: #fd7e14; font-weight: bold; }}
                .estado-bajo {{ color: #fff; background-color: #6f42c1; font-weight: bold; }}
                .fila-oculta {{ display: none; }}
                .header-resumen th {{ background-color: #0d6efd; color: white; }}
            </style>
        </head>
        <body>
            <div class="container-fluid">
                <div class="card mb-4">
                    <h2 class="text-center text-primary">Reporte de Transmisión SCADA</h2>
                    <p class="text-muted text-center mb-0">Generado el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                <div class="row mb-4">
                    <div class="col-lg-5"><div class="card">{html_pastel}</div></div>
                    <div class="col-lg-7"><div class="card">{html_mapa}</div></div>
                </div>
                <div class="card mb-4">
                    <h4 class="mb-3 text-secondary">📊 Resumen Ejecutivo</h4>
                    <div class="table-responsive header-resumen">{tabla_resumen_html}</div>
                </div>
                <div class="card">
                    <h4>Desglose Detallado</h4>
                    <div class="table-responsive">{tabla_detalle_html}</div>
                </div>
            </div>
            <script>
                document.querySelectorAll('#tabla_datos td').forEach(td => {{
                    if(td.textContent === 'Operación Normal') td.classList.add('estado-normal');
                    if(td.textContent === 'Sin Señal') td.classList.add('estado-sin-senal');
                    if(td.textContent === 'Dato Trancado') td.classList.add('estado-trancado');
                    if(td.textContent === 'SITIO EN 0') td.classList.add('estado-cero');
                    if(td.textContent === 'DESCONEXION') td.classList.add('estado-desconexion');
                    if(td.textContent === 'Alarma: Nivel Alto') td.classList.add('estado-alto');
                    if(td.textContent === 'Alarma: Nivel Bajo') td.classList.add('estado-bajo');
                }});
            </script>
        </body>
        </html>
        """
        return html_final

    col_btn, _ = st.columns([1, 3])
    with col_btn:
        actualizar = st.button("🔄 Consultar SCADA y Generar Reporte", use_container_width=True)

    if actualizar or 'df_scada' in st.session_state:
        if actualizar:
            with st.spinner("Conectando con servidores SCADA en tiempo real..."):
                datos_crudos = obtener_datos_scada_reales()
                if datos_crudos:
                    df_scada_procesado = procesar_logica_scada(datos_crudos)
                    st.session_state.df_scada = df_scada_procesado
                    st.session_state.html_generado = generar_html_interactivo(st.session_state.df_scada)
                    st.success("¡Análisis completado! Datos extraídos de la API.")
                else:
                    st.error("No se pudieron recuperar datos. Verifique la conexión de red o el archivo secrets.toml")

        if 'df_scada' in st.session_state and not st.session_state.df_scada.empty:
            df_scada = st.session_state.df_scada
            
            col_res_graf, col_res_tab = st.columns([1, 2])
            with col_res_graf:
                st.dataframe(df_scada['estado'].value_counts().reset_index(), hide_index=True, use_container_width=True)
            with col_res_tab:
                st.dataframe(df_scada[['sensor', 'estado', 'valor', 'historial_caidas']], hide_index=True, use_container_width=True)
            
            # --- BOTÓN DE DESCARGA HTML EN BARRA LATERAL ---
            if 'html_generado' in st.session_state:
                st.sidebar.markdown("---")
                st.sidebar.markdown("### 📥 Reportes y Descargas")
                st.sidebar.download_button(
                    label="📄 Descargar Reporte Completo (HTML)",
                    data=st.session_state.html_generado,
                    file_name=f"Reporte_SCADA_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                    mime="text/html"
                )

else:
    st.info("💡 Cargue registros operativos con coordenadas válidas para iniciar el tablero.")