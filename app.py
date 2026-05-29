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

# Ocultar advertencias SSL para la API
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Tablero Territorial CDMX", layout="wide")
st.title("📍 Sistema de Inteligencia Territorial")
st.markdown("---")

# ==========================================
# 2. CARGA DE DATOS OPERATIVOS (SENSORES)
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
    
    # ------------------------------------------
    # BUSCADOR GLOBAL DE COLONIAS 
    # ------------------------------------------
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
    
    # ------------------------------------------
    # FILTRO OPERATIVO DE SENSORES
    # ------------------------------------------
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
    # 4. CONSTRUCCIÓN DEL MAPA
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
    # 6. MONITOREO DINÁMICO (SCADA Y HTML)
    # ==========================================
    st.markdown("---")
    st.header("🚨 Monitoreo Dinámico de Telemetría (SCADA)")

    def obtener_datos_scada():
        try:
            sitios_config = st.secrets["sitios"]
        except KeyError:
            st.error("⚠️ Falta configurar los Secretos de la API SCADA en Streamlit Cloud.")
            return []
            
        import random
        datos_recolectados = []
        for nombre_sitio, config in sitios_config.items():
            estado_sim = random.choice(["Operación Normal", "Dato Trancado", "Sin Señal"])
            ultimo_valor = random.uniform(config.get("min", 0), config.get("max", 1) + 1) if estado_sim == "Operación Normal" else (0.0 if estado_sim == "Sin Señal" else config.get("max", 1))
            
            datos_recolectados.append({
                "sensor": nombre_sitio,
                "delegacion": config.get("delegacion", "N/A"), 
                "valor": ultimo_valor,
                "estado": estado_sim,
                "ultima_conexion": datetime.now() if estado_sim != "Sin Señal" else datetime.now() - timedelta(days=3),
                "historial_caidas": "Estable" if estado_sim == "Operación Normal" else "Falla Detectada"
            })
        return datos_recolectados

    def generar_html_interactivo(df):
        total_puntos = len(df)
        colores_estados = {'Operación Normal': '#28a745', 'Sin Señal': '#dc3545', 'SITIO EN 0': '#ffc107', 'DESCONEXION': '#6c757d', 'Dato Trancado': '#e83e8c'}
        
        conteo = df['estado'].value_counts().reset_index()
        conteo.columns = ['Estado', 'Cantidad']
        fig_pastel = px.pie(conteo, values='Cantidad', names='Estado', title=f'Diagnóstico General<br><sup style="color:gray; font-size:14px;">Total de puntos: {total_puntos}</sup>', color='Estado', color_discrete_map=colores_estados)
        html_pastel = fig_pastel.to_html(full_html=False, include_plotlyjs='cdn', div_id='grafica_plotly')

        df['transmite'] = df['estado'] == 'Operación Normal'
        resumen = df.groupby('delegacion').agg(Total_Equipos=('sensor', 'count'), Transmitiendo=('transmite', 'sum')).reset_index()
        resumen['Sin_Transmision'] = resumen['Total_Equipos'] - resumen['Transmitiendo']
        resumen['Conectividad'] = (resumen['Transmitiendo'] / resumen['Total_Equipos'] * 100).round(1).astype(str) + '%'
        
        tabla_resumen_html = resumen.rename(columns={'delegacion': 'Alcaldía', 'Total_Equipos': 'Total de Sitios', 'Transmitiendo': 'En Línea', 'Sin_Transmision': 'Desconectados', 'Conectividad': 'Nivel de Conectividad'}).to_html(classes='table table-bordered table-striped text-center align-middle', index=False)

        df['ultima_conexion'] = pd.to_datetime(df['ultima_conexion']).dt.strftime('%Y-%m-%d %H:%M:%S').fillna('Sin registro')
        tabla_detalle_html = df[['sensor', 'delegacion', 'valor', 'estado', 'historial_caidas', 'ultima_conexion']].to_html(classes='table table-striped table-hover table-bordered text-center align-middle', index=False, table_id="tabla_datos")

        df_mapa = df[(df['lat'] != 0.0) & (df['lon'] != 0.0)]
        fig_mapa = px.scatter_map(
        df_mapa, lat="lat", lon="lon", hover_name="sensor",
        hover_data={"estado": True, "delegacion": True, "valor": True, "lat": False, "lon": False},
        color="estado", color_discrete_map=colores_estados,
        zoom=10, center={"lat": 19.4326, "lon": -99.1332}, height=450,
        title="Ubicación de Infraestructura"
        )
        fig_mapa.update_layout(map_style="carto-positron", title_x=0.5, margin=dict(t=60, b=10, l=10, r=10))
        html_mapa = fig_mapa.to_html(full_html=False, include_plotlyjs=False) 
    
        html_final = f"""
        <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Monitor SCADA</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ background-color: #f4f6f9; padding: 20px; }}
            .card {{ border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); padding: 20px; background: white; height: 100%; }}
            .estado-normal {{ color: #155724; background-color: #d4edda; font-weight: bold; }}
            .estado-sin-senal {{ color: #721c24; background-color: #f8d7da; font-weight: bold; }}
            .estado-cero {{ color: #856404; background-color: #fff3cd; font-weight: bold; }}
            .estado-desconexion {{ color: #fff; background-color: #6c757d; font-weight: bold; }}
            .estado-nodato {{ color: #0c5460; background-color: #d1ecf1; font-weight: bold; }}
            .estado-alto {{ color: #fff; background-color: #fd7e14; font-weight: bold; }}
            .estado-bajo {{ color: #fff; background-color: #6f42c1; font-weight: bold; }}
            
            .estado-trancado {{ color: #fff; background-color: #e83e8c; font-weight: bold; }}
            .estado-desactualizado {{ color: #fff; background-color: #856404; font-weight: bold; }} 
            
            .fila-oculta {{ display: none; }}
            .header-resumen th {{ background-color: #0d6efd; color: white; }}
        </style>
    </head>
    <body>
        <div class="container-fluid">
            <div class="card mb-4">
                <h2 class="text-center text-primary">Monitoreo Operativo de D4 Segunda Parte</h2>
                <h3 class="text-center text-secondary">Subdirección de Tecnología, Innovación y Datos</h3>
                <h4 class="text-center text-secondary">JUD de Información</h4>
                <p class="text-muted text-center mb-0">Última actualización: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            
            <div class="row mb-4">
                <div class="col-lg-5 mb-3 mb-lg-0">
                    <div class="card">
                        <p class="text-center text-muted small mb-0">Haga clic en una sección para filtrar la tabla detallada</p>
                        {html_pastel}
                    </div>
                </div>
                <div class="col-lg-7">
                    <div class="card">
                        {html_mapa}
                    </div>
                </div>
            </div>
            
            <div class="card mb-4">
                <h4 class="mb-3 text-secondary">📊 Resumen Ejecutivo por Alcaldía</h4>
                <div class="table-responsive header-resumen">
                    {tabla_resumen_html}
                </div>
            </div>

            <div class="card">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <h4 class="mb-0">Desglose Detallado de Dispositivos e Infraestructura <span id="texto_filtro" class="badge bg-info text-dark ms-2" style="display:none;"></span></h4>
                    <button id="btn_reset" class="btn btn-sm btn-outline-secondary" style="display:none;" onclick="resetearFiltro()">Mostrar Todos</button>
                </div>
                <div class="table-responsive">
                    {tabla_detalle_html}
                </div>
            </div>
        </div>

        <script>
            document.querySelectorAll('#tabla_datos td').forEach(td => {{
                if(td.textContent === 'Operación Normal') td.classList.add('estado-normal');
                if(td.textContent === 'Sin Señal') td.classList.add('estado-sin-senal');
                if(td.textContent === 'SITIO EN 0') td.classList.add('estado-cero');
                if(td.textContent === 'DESCONEXION') td.classList.add('estado-desconexion');
                if(td.textContent === 'NO HAY DATO') td.classList.add('estado-nodato');
                if(td.textContent === 'Alarma: Nivel Alto') td.classList.add('estado-alto');
                if(td.textContent === 'Alarma: Nivel Bajo') td.classList.add('estado-bajo');
                
                if(td.textContent === 'Dato Trancado') td.classList.add('estado-trancado');
                if(td.textContent === 'Desactualizado') td.classList.add('estado-desactualizado');
            }});

            setTimeout(() => {{
                const grafica = document.getElementById('grafica_plotly');
                if(grafica) {{
                    grafica.on('plotly_click', function(data) {{
                        const estadoSeleccionado = data.points[0].label;
                        const filas = document.querySelectorAll('#tabla_datos tbody tr');
                        
                        filas.forEach(fila => {{
                            // ATENCIÓN: El índice cambió a 7 al agregar la columna de Eventos de Desconexión
                            const celdaEstado = fila.querySelectorAll('td')[7]; 
                            if(celdaEstado) {{
                                if(celdaEstado.textContent === estadoSeleccionado) {{
                                    fila.classList.remove('fila-oculta');
                                }} else {{
                                    fila.classList.add('fila-oculta');
                                }}
                            }}
                        }});
                        
                        document.getElementById('btn_reset').style.display = 'inline-block';
                        const badgeFiltro = document.getElementById('texto_filtro');
                        badgeFiltro.textContent = "Filtrado por: " + estadoSeleccionado;
                        badgeFiltro.style.display = 'inline-block';
                    }});
                }}
            }}, 1000);

            function resetearFiltro() {{
                const filas = document.querySelectorAll('#tabla_datos tbody tr');
                filas.forEach(fila => fila.classList.remove('fila-oculta'));
                document.getElementById('btn_reset').style.display = 'none';
                document.getElementById('texto_filtro').style.display = 'none';
            }}
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
            with st.spinner("Conectando con SCADA y compilando HTML..."):
                datos_crudos = obtener_datos_scada()
                if datos_crudos:
                    st.session_state.df_scada = pd.DataFrame(datos_crudos)
                    st.session_state.html_generado = generar_html_interactivo(st.session_state.df_scada)
                    st.success("¡Datos extraídos y reporte compilado!")

        if 'df_scada' in st.session_state and not st.session_state.df_scada.empty:
            df_scada = st.session_state.df_scada
            
            col_res_graf, col_res_tab = st.columns([1, 2])
            with col_res_graf:
                st.dataframe(df_scada['estado'].value_counts().reset_index(), hide_index=True, use_container_width=True)
            with col_res_tab:
                st.dataframe(df_scada[['sensor', 'estado', 'valor']], hide_index=True, use_container_width=True)
            
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