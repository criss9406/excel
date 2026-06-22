import io
from datetime import datetime
import pandas as pd

def _get_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Resultado')
    return output.getvalue()

def procesar_cobranzas(contenido: bytes, nombre: str) -> dict:
    """Calcula mora y clasifica facturas pendientes."""
    df = pd.read_excel(io.BytesIO(contenido))
    
    col_emision = next((c for c in df.columns if 'emis' in c.lower() or 'fecha' in c.lower()), None)
    if col_emision:
        df[col_emision] = pd.to_datetime(df[col_emision])
        # Simulate current date for calculating delays based on standard invoice terms (e.g. 30 days)
        today = datetime.now()
        df['Dias_Transcurridos'] = (today - df[col_emision]).dt.days
        df['Dias_Mora'] = df['Dias_Transcurridos'] - 30
        df['Dias_Mora'] = df['Dias_Mora'].apply(lambda x: x if x > 0 else 0)
        
        def estado_accion(mora):
            if mora == 0: return 'Al día'
            elif mora < 15: return 'Recordatorio Amistoso 1'
            elif mora < 30: return 'Recordatorio Urgente 2'
            else: return 'Pasar a Cobranza Externa'
            
        df['Accion_Sugerida'] = df['Dias_Mora'].apply(estado_accion)
        
    return {"excel_bytes": _get_bytes(df)}

def procesar_carga_erp(contenido: bytes, nombre: str) -> dict:
    """Valida datos listos para RPA ERP y genera log de carga."""
    df = pd.read_excel(io.BytesIO(contenido))
    
    log_data = []
    for idx, row in df.iterrows():
        # Example business rules
        precio = pd.to_numeric(row.get('Precio_Base', 0), errors='coerce')
        stock = pd.to_numeric(row.get('Stock_Inicial', 0), errors='coerce')
        
        status = "OK"
        motivo = ""
        
        if pd.isna(precio) or precio <= 0:
            status = "RECHAZADO"
            motivo += "Precio invalido. "
        if pd.isna(stock) or stock < 0:
            status = "RECHAZADO"
            motivo += "Stock negativo o invalido. "
            
        row_dict = row.to_dict()
        row_dict['RPA_Status'] = status
        row_dict['RPA_Motivo'] = motivo
        log_data.append(row_dict)
        
    df_log = pd.DataFrame(log_data)
    return {"excel_bytes": _get_bytes(df_log)}

def procesar_rrhh(c_bruto: bytes, c_plantilla: bytes, n_bruto: str, n_plantilla: str) -> dict:
    """Pivotea marcas de entrada/salida y resume horas totales."""
    df_bruto = pd.read_csv(io.BytesIO(c_bruto))
    df_plantilla = pd.read_excel(io.BytesIO(c_plantilla))
    
    # Aseguramos que existan las columnas de hora
    if 'Hora_Entrada' in df_bruto.columns and 'Hora_Salida' in df_bruto.columns:
        # Convert strings to timedelta to calculate differences
        df_bruto['Entrada'] = pd.to_timedelta(df_bruto['Hora_Entrada'] + ':00')
        df_bruto['Salida'] = pd.to_timedelta(df_bruto['Hora_Salida'] + ':00')
        df_bruto['Horas_Trabajadas'] = (df_bruto['Salida'] - df_bruto['Entrada']).dt.total_seconds() / 3600.0
        
        # Agrupar por empleado
        resumen = df_bruto.groupby('ID_Empleado').agg(
            Dias_Trabajados=('Fecha', 'count'),
            Horas_Totales=('Horas_Trabajadas', 'sum')
        ).reset_index()
        
        # Calculamos extras (asumimos 8h / dia -> mes = ~160h. Aca simplemente es Horas_Totales - (Dias * 8))
        resumen['Horas_Extras'] = resumen['Horas_Totales'] - (resumen['Dias_Trabajados'] * 8)
        resumen['Horas_Extras'] = resumen['Horas_Extras'].apply(lambda x: round(x, 1) if x > 0 else 0)
        
        # Merge with plantilla
        df_final = pd.merge(df_plantilla[['ID_Empleado']], resumen, on='ID_Empleado', how='right')
        df_final['Bonos'] = df_final['Horas_Extras'].apply(lambda x: x * 5000) # Ej: $5000 por hora extra
        
    else:
        df_final = df_plantilla # fallback
        
    return {"excel_bytes": _get_bytes(df_final)}
