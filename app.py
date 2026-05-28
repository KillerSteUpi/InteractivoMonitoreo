import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import requests
from datetime import datetime, timedelta
import plotly.express as px
import urllib3
import time
import os
import json

# Ocultar advertencias de certificados SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. CONFIGURACIÓN DEL DASHBOARD
# ==========================================
st.set_page_config(page_title="Tablero Territorial y SCADA CDMX", layout="wide")

# ==========================================
# 2. FUNCIONES DEL MAPA TERRITORIAL (Original)
# ==========================================
@st.cache_data(ttl=300)
def cargar_datos_territoriales():
    if not os.path.exists("mis_datos.json"): 
        return pd.DataFrame(), gpd.GeoDataFrame()
    df = pd.read_json("mis_datos.json", orient="index")
    if df.empty: return pd.DataFrame(), gpd.GeoDataFrame()

    df['nombre_sitio'] = df.index.astype(str).str.replace("_", " ")
    df['lat'] = pd.to_numeric(df.get('lat'), errors='coerce')
    df['lon'] = pd.to_numeric(df.get('lon'), errors='coerce')
    df = df.dropna(subset=['lat', 'lon'])
    
    gdf = gpd.GeoDataFrame(df, geometry=[Point(xy) for xy in zip(df.lon, df.lat)], crs="EPSG:4326")
    return df, gdf

df_datos, gdf_datos = cargar_datos_territoriales()

# ==========================================
# 3. MOTOR DE EXTRACCIÓN SCADA (Protegido)
# ==========================================
def obtener_datos_api_seguro():
    """Consume la API leyendo los parámetros desde st.secrets"""
    datos_recolectados = []
    
    # Recuperación segura de credenciales
    api_url = st.secrets["api_scada"]["url"]
    token = st.secrets["api_scada"]["token"]
    sitios_config = st.secrets["sitios"]
    
    headers = {'nexustoken': token, 'Content-Type': 'application/json'}
    ahora = datetime.now()
    end_ts = int(ahora.timestamp() * 1000)
    start_ts = int((ahora - timedelta(days=3)).timestamp() * 1000)

    # Iteramos sobre los sitios definidos en secrets.toml
    for nombre_sitio, config in sitios_config.items():
        uid = config["uid"]
        url_consulta = f"{api_url}/{uid}/last-data" 
        payload = {
            "uids": [uid],
            "startTs": start_ts,
            "endTs": end_ts,
            "dataSource": "RAW"
        }
        
        # Simulamos la extracción para mantener el entorno de prueba responsivo
        # (Reemplace este bloque con su lógica original `requests.post` si desea conexión real en este script)
        import random
        estado_sim = random.choice(["Normal", "Flatline", "Vacio"])
        ultimo_valor = random.uniform(config["min"], config["max"] + 1) if estado_sim == "Normal" else (config["max"] if estado_sim == "Flatline" else None)
        
        datos_recolectados.append({
            "sensor": nombre_sitio,
            "delegacion": config["delegacion"], 
            "lat": config["lat"],                
            "lon": config["lon"],                
            "valor": ultimo_valor,
            "ultima_conexion": datetime.now() if estado_sim != "Vacio" else datetime.now() - timedelta(days=3),
            "es_flatline": estado_sim == "Flatline",
            "historial_caidas": "Estable" if estado_sim == "Normal" else "Falla Detectada",
            "min_val": config["min"], 
            "max_val": config["max"]
        })

    # Datos inyectados de prueba para completar la visualización
    if len(datos_recolectados) < 3:
        datos_recolectados.extend([
            {"sensor": "PRUEBA_C5", "delegacion": "Venustiano Carranza", "lat": 19.4276, "lon": -99.1132, "valor": 1.5, "ultima_conexion": datetime.now(), "es_flatline": False, "historial_caidas": "Estable", "min_val": 0.5, "max_val": 2.5},
            {"sensor": "PRUEBA_CAIDO", "delegacion": "Tlalpan", "lat": 19.2878, "lon": -99.1713, "valor": None, "ultima_conexion": datetime.now() - timedelta(days=5), "es_flatline": False, "historial_caidas": "Caída prolongada", "min_val": 0.5, "max_val": 2.5}
        ])

    return datos_recolectados

def procesar_datos_scada(datos):
    """Evalúa los estados operativos según ventanas de tiempo"""
    df = pd.DataFrame(datos)
    df['ultima_conexion'] = pd.to_datetime(df['ultima_conexion'], errors='coerce')
    
    fecha_sin_senal = datetime.now() - timedelta(days=2)   
    fecha_trancado = datetime.now() - timedelta(hours=24)  
    
    def evaluar_estado(fila):
        v = fila['valor']
        fecha = fila['ultima_conexion']
        flatline = fila.get('es_flatline', False) 
        
        if pd.isna(fecha) or fecha < fecha_sin_senal: return "Sin Señal"
        if fecha < fecha_trancado: return "Desactualizado" 
        if flatline == True: return "Dato Trancado"
        if pd.isna(v) or v is None or str(v).strip() == "": return "DESCONEXION"
        
        try:
            val_num = float(v)
            if val_num == 0.0: return "SITIO EN 0"
            elif val_num > fila['max_val']: return "Alarma: Nivel Alto"
            elif val_num < fila['min_val']: return "Alarma: Nivel Bajo"
            else: return "Operación Normal"
        except:
            return "Error de Formato"

    df['estado'] = df.apply(evaluar_estado, axis=1)
    df['valor'] = df['valor'].fillna('') 
    return df

# ==========================================
# 4. GENERADOR DE REPORTE HTML (En memoria)
# ==========================================
def generar_html_en_memoria(df):
    """Construye el string HTML exacto de su reporte para descargarlo"""
    # ... (Aquí va exactamente el mismo código de su función generar_reporte_html) ...
    # Solo cambiamos la parte final para que haga 'return html_final' en lugar de 'with open...'
    html_final = "<h1>Reporte de Monitoreo SCADA</h1><p>Archivo generado dinámicamente.</p>" # Simplificado para el ejemplo
    return html_final

# ==========================================
# INTERFAZ DE USUARIO (UI)
# ==========================================
st.title("📍 Sistema de Inteligencia Territorial y SCADA")
st.markdown("---")

# --- BARRA LATERAL ---
st.sidebar.markdown("### ⚙️ Panel de Control")
busqueda_sitio = st.sidebar.text_input("Filtrar por nombre de sitio:", placeholder="EJ: ZARAGOZA, POZO...")
demarcacion_sel = st.sidebar.selectbox("Filtrar por Demarcación:", ["Todas"] + list(df_datos['delegacion'].unique()) if not df_datos.empty else [])

# --- MAPA PRINCIPAL TERRITORIAL ---
if not df_datos.empty:
    m = folium.Map(location=[19.4326, -99.1332], zoom_start=10, tiles="CartoDB positron")
    marker_cluster = MarkerCluster().add_to(m)
    for idx, row in df_datos.iterrows():
        folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color="blue", fill=True, popup=row['nombre_sitio']).add_to(marker_cluster)
    st_folium(m, width="100%", height=400, returned_objects=[])

# --- SECCIÓN DE MONITOREO DINÁMICO ---
st.markdown("---")
st.header("🚨 Monitoreo Dinámico de Telemetría (No Sebalogs)")

col_btn, col_espacio = st.columns([1, 3])
with col_btn:
    actualizar = st.button("🔄 Consultar SCADA", use_container_width=True)

if actualizar or 'df_scada' in st.session_state:
    if actualizar:
        with st.spinner("Conectando con el servidor SCADA y calculando MTTR..."):
            datos_crudos = obtener_datos_api_seguro()
            st.session_state.df_scada = procesar_datos_scada(datos_crudos)
            st.success("¡Estados operativos actualizados!")

    df_scada = st.session_state.df_scada
    
    # 1. Gráfica y Resumen Ejecutivo
    col_pie, col_res = st.columns([1, 2])
    
    with col_pie:
        conteo = df_scada['estado'].value_counts().reset_index()
        conteo.columns = ['Estado', 'Cantidad']
        fig = px.pie(conteo, values='Cantidad', names='Estado', hole=0.4, title="Diagnóstico de Red")
        st.plotly_chart(fig, use_container_width=True)
        
    with col_res:
        st.markdown("##### Resumen por Alcaldía")
        resumen = df_scada.groupby('delegacion').size().reset_index(name='Total Equipos')
        st.dataframe(resumen, use_container_width=True, hide_index=True)

    # 2. Desglose detallado
    st.markdown("##### Desglose Detallado de Dispositivos")
    st.dataframe(df_scada[['sensor', 'delegacion', 'valor', 'estado', 'historial_caidas']], use_container_width=True, hide_index=True)

    # 3. Exportación Documental
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📥 Generación de Reportes")
    
    html_descargable = generar_html_en_memoria(df_scada)
    fecha_formato = datetime.now().strftime("%Y-%m-%d_%H-%M")
    
    st.sidebar.download_button(
        label="📄 Descargar Reporte Completo (HTML)",
        data=html_descargable,
        file_name=f"Reporte_SCADA_{fecha_formato}.html",
        mime="text/html"
    )