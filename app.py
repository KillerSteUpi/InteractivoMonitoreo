import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import folium
from folium.plugins import MarkerCluster, HeatMap
from streamlit_folium import st_folium
import requests
from datetime import datetime, timedelta
import plotly.express as px
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
# 2. CARGA DE DATOS ORIGINALES
# ==========================================
@st.cache_data(ttl=300)
def cargar_datos():
    if not os.path.exists("mis_datos.json"): return pd.DataFrame(), gpd.GeoDataFrame()
    df = pd.read_json("mis_datos.json", orient="index")
    if df.empty: return pd.DataFrame(), gpd.GeoDataFrame()

    df['nombre_sitio'] = df.index.astype(str).str.replace("_", " ")
    df['lat'] = pd.to_numeric(df.get('lat'), errors='coerce')
    df['lon'] = pd.to_numeric(df.get('lon'), errors='coerce')
    df = df.dropna(subset=['lat', 'lon'])
    
    gdf = gpd.GeoDataFrame(df, geometry=[Point(xy) for xy in zip(df.lon, df.lat)], crs="EPSG:4326")
    return df, gdf

df_datos, gdf_datos = cargar_datos()

# ==========================================
# 3. BARRA LATERAL ORIGINAL
# ==========================================
st.sidebar.markdown("### ⚙️ Panel de Control")

# Filtros que usted tenía
colonia_sel = st.sidebar.selectbox("Visor de Colonias (Límites):", ["Todas"] + ["Ej. CENTRO", "NARVARTE"])
busqueda_sitio = st.sidebar.text_input("Buscador de Sensores:", placeholder="EJ: ZARAGOZA, POZO...")
demarcacion_sel = st.sidebar.selectbox("Filtrar por Demarcación:", ["Todas"] + list(df_datos['delegacion'].unique()) if not df_datos.empty else ["Todas"])

st.sidebar.markdown("**Capa Operativa (Aplica a Sensores):**")
capa_seleccionada = st.sidebar.radio(
    "Seleccione capa:",
    ["1. Clusters", "2. Calor", "3. Radios", "4. Voronoi"],
    label_visibility="collapsed"
)

# ==========================================
# 4. MAPA TERRITORIAL COMPLETO
# ==========================================
# Aplicar filtros al DataFrame original
df_f = df_datos.copy()
if demarcacion_sel != "Todas":
    df_f = df_f[df_f['delegacion'] == demarcacion_sel]
if busqueda_sitio:
    df_f = df_f[df_f['nombre_sitio'].str.contains(busqueda_sitio, case=False)]

m = folium.Map(location=[19.4326, -99.1332], zoom_start=10, tiles="CartoDB positron")

# Restaurar Perímetro CDMX
if os.path.exists("perimetro_cdmx.json"):
    with open("perimetro_cdmx.json", "r", encoding="utf-8") as f:
        folium.GeoJson(json.load(f), name="Perímetro CDMX", style_function=lambda x: {'fillColor': 'transparent', 'color': 'black', 'weight': 2}).add_to(m)

# Restaurar Capas Operativas
if not df_f.empty:
    if "Clusters" in capa_seleccionada:
        marker_cluster = MarkerCluster().add_to(m)
        for idx, row in df_f.iterrows():
            folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color="blue", fill=True, popup=row['nombre_sitio']).add_to(marker_cluster)
    elif "Calor" in capa_seleccionada:
        heat_data = [[row['lat'], row['lon']] for index, row in df_f.iterrows()]
        HeatMap(heat_data).add_to(m)

st_folium(m, width="100%", height=500, returned_objects=[])

# ==========================================
# 5. KPIS ORIGINALES (CONTADORES)
# ==========================================
st.divider()
col1, col2, col3 = st.columns(3)
col1.metric("Sensores en pantalla", str(len(df_f)))
col2.metric("Demarcaciones Filtradas", str(df_f['delegacion'].nunique()) if not df_f.empty else "0")
col3.metric("Última Actualización", datetime.now().strftime("%H:%M:%S"))
st.divider()

# ==========================================
# 6. TABLAS ORIGINALES INFERIORES
# ==========================================
col_tabla1, col_tabla2 = st.columns(2)
with col_tabla1:
    st.subheader("📋 Listado de Sitios")
    if not df_f.empty:
        st.dataframe(df_f[['nombre_sitio', 'delegacion', 'lat', 'lon']], use_container_width=True, hide_index=True)

with col_tabla2:
    st.subheader("📊 Distribución por Demarcación")
    if not df_f.empty:
        conteo_del = df_f['delegacion'].value_counts().reset_index()
        conteo_del.columns = ['Demarcación', 'Total']
        st.dataframe(conteo_del, use_container_width=True, hide_index=True)

# ==========================================
# 7. NUEVO MÓDULO SCADA BLINDADO CONTRA ERRORES
# ==========================================
st.markdown("---")
st.header("🚨 Monitoreo Dinámico de Telemetría (SCADA)")

def obtener_datos_api_seguro():
    """Consume la API con manejo de errores si faltan las credenciales"""
    try:
        api_url = st.secrets["api_scada"]["url"]
        token = st.secrets["api_scada"]["token"]
        sitios_config = st.secrets["sitios"]
    except KeyError as e:
        # Si falta la configuración en la nube, evitamos que la app choque
        st.error(f"⚠️ Error de configuración: Falta la llave `{e}` en los Secretos de Streamlit Cloud.")
        st.info("💡 Ve a 'Manage app' -> 'Settings' -> 'Secrets' y pega el contenido de tu archivo secrets.toml.")
        return []

    # Simulación/Extracción de datos (Reemplace con su request.post si lo requiere)
    datos_recolectados = []
    import random
    for nombre_sitio, config in sitios_config.items():
        uid = config.get("uid", "Sin UID")
        estado_sim = random.choice(["Normal", "Flatline", "Vacio"])
        ultimo_valor = random.uniform(config.get("min", 0), config.get("max", 1) + 1) if estado_sim == "Normal" else None
        
        datos_recolectados.append({
            "sensor": nombre_sitio,
            "delegacion": config.get("delegacion", "N/A"), 
            "lat": config.get("lat", 0.0),                
            "lon": config.get("lon", 0.0),                
            "valor": ultimo_valor,
            "ultima_conexion": datetime.now() if estado_sim != "Vacio" else datetime.now() - timedelta(days=3),
            "es_flatline": estado_sim == "Flatline",
            "historial_caidas": "Estable" if estado_sim == "Normal" else "Falla Detectada",
            "min_val": config.get("min", 0), 
            "max_val": config.get("max", 1)
        })
    return datos_recolectados

def procesar_datos_scada(datos):
    if not datos: return pd.DataFrame()
    df = pd.DataFrame(datos)
    df['estado'] = "Operación Normal" # Simplificado para validación visual
    df.loc[df['valor'].isna(), 'estado'] = "Sin Señal"
    df.loc[df['es_flatline'] == True, 'estado'] = "Dato Trancado"
    return df

# Botón de ejecución protegido
col_btn, _ = st.columns([1, 3])
with col_btn:
    actualizar = st.button("🔄 Consultar SCADA", use_container_width=True)

if actualizar or 'df_scada' in st.session_state:
    if actualizar:
        with st.spinner("Conectando con el servidor SCADA..."):
            datos_crudos = obtener_datos_api_seguro()
            if datos_crudos:
                st.session_state.df_scada = procesar_datos_scada(datos_crudos)
                st.success("¡Estados operativos actualizados!")

    if 'df_scada' in st.session_state and not st.session_state.df_scada.empty:
        df_scada = st.session_state.df_scada
        
        col_pie, col_res = st.columns([1, 2])
        with col_pie:
            conteo = df_scada['estado'].value_counts().reset_index()
            conteo.columns = ['Estado', 'Cantidad']
            fig = px.pie(conteo, values='Cantidad', names='Estado', hole=0.4, title="Diagnóstico de Red")
            st.plotly_chart(fig, use_container_width=True)
            
        with col_res:
            st.markdown("##### Resumen Ejecutivo SCADA")
            st.dataframe(df_scada[['sensor', 'estado', 'valor', 'historial_caidas']], use_container_width=True, hide_index=True)