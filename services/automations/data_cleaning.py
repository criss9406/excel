import io
import pandas as pd

def _get_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Resultado')
    return output.getvalue()

def procesar_copy_paste(c1: bytes, c2: bytes, name1: str, name2: str) -> dict:
    """Anexa c2 (diario) al final de c1 (maestro)."""
    df1 = pd.read_excel(io.BytesIO(c1))
    df2 = pd.read_excel(io.BytesIO(c2))
    df_combined = pd.concat([df1, df2], ignore_index=True)
    return {"excel_bytes": _get_bytes(df_combined)}

def procesar_limpieza(contenido: bytes, nombre: str) -> dict:
    """Limpia fechas sucias, numeros y remueve duplicados."""
    df = pd.read_csv(io.BytesIO(contenido)) if nombre.endswith('.csv') else pd.read_excel(io.BytesIO(contenido))
    
    # Remove obvious duplicates
    df = df.drop_duplicates()
    
    # Clean dirty dates if a date column exists (e.g., 'Fecha_Sucia')
    date_col = next((c for c in df.columns if 'fecha' in c.lower()), None)
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce').dt.strftime('%Y-%m-%d')
        df[date_col] = df[date_col].fillna('Fecha Inválida')
    
    # Clean dirty numbers (e.g., 'Monto')
    num_col = next((c for c in df.columns if 'monto' in c.lower()), None)
    if num_col:
        df[num_col] = df[num_col].astype(str).str.replace(',', '.').str.replace(r'[^\d.]', '', regex=True)
        df[num_col] = pd.to_numeric(df[num_col], errors='coerce').fillna(0)
        
    return {"excel_bytes": _get_bytes(df)}

def procesar_recurrente(contenido: bytes, nombre: str) -> dict:
    """Aplica transformaciones estandarizadas."""
    df = pd.read_excel(io.BytesIO(contenido))
    
    # Calculate derived columns typical in recurrent reports
    if 'Unidades' in df.columns and 'Precio_Unitario' in df.columns and 'Descuento_pct' in df.columns:
        df['Venta_Bruta'] = df['Unidades'] * df['Precio_Unitario']
        df['Descuento_Aplicado'] = df['Venta_Bruta'] * (df['Descuento_pct'] / 100)
        df['Venta_Neta'] = df['Venta_Bruta'] - df['Descuento_Aplicado']
        df['Clasificacion_Venta'] = df['Venta_Neta'].apply(lambda x: 'Alta' if x > 1000 else ('Media' if x > 500 else 'Baja'))
        
    return {"excel_bytes": _get_bytes(df)}
