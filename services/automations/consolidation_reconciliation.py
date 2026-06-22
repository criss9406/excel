import io
import pandas as pd

def _get_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Resultado')
    return output.getvalue()

def procesar_consolidacion(conts: list[bytes], nombres: list[str]) -> dict:
    """Apila multiples archivos con exactamente la misma estructura y agrega Origen."""
    dfs = []
    for c, n in zip(conts, nombres):
        df = pd.read_excel(io.BytesIO(c)) if n.endswith(('.xls', '.xlsx')) else pd.read_csv(io.BytesIO(c))
        df['Origen'] = n
        dfs.append(df)
    
    df_final = pd.concat(dfs, ignore_index=True)
    return {"excel_bytes": _get_bytes(df_final)}

def procesar_reconciliacion(c1: bytes, c2: bytes, name1: str, name2: str) -> dict:
    """Cruza Cartola Bancaria con Libro Mayor basandose en el monto (Abono vs Debe) y busca diferencias."""
    df_banco = pd.read_excel(io.BytesIO(c1))
    df_mayor = pd.read_excel(io.BytesIO(c2))
    
    # Simple reconciliation logic based on exact Amounts
    # We create a 'matched' column
    df_banco['Matched'] = False
    df_mayor['Matched'] = False
    
    abonos_banco = df_banco[df_banco['Abono'] > 0]
    debes_mayor = df_mayor[df_mayor['Debe'] > 0]
    
    # Match by Amount
    for idx_b, row_b in abonos_banco.iterrows():
        monto_b = round(float(row_b['Abono']), 2)
        # Find match in mayor
        matches = df_mayor[(~df_mayor['Matched']) & (df_mayor['Debe'] > 0)]
        match_idx = None
        for idx_m, row_m in matches.iterrows():
            monto_m = round(float(row_m['Debe']), 2)
            if abs(monto_b - monto_m) <= 0.05:  # Tolerance of 5 cents
                match_idx = idx_m
                break
        
        if match_idx is not None:
            df_banco.at[idx_b, 'Matched'] = True
            df_mayor.at[match_idx, 'Matched'] = True
            
    # Highlight missing
    df_banco['Estado_Conciliacion'] = df_banco['Matched'].apply(lambda x: 'Conciliado' if x else 'No Conciliado / Diferencia')
    df_mayor['Estado_Conciliacion'] = df_mayor['Matched'].apply(lambda x: 'Conciliado' if x else 'Falta en Banco')
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_banco.drop(columns=['Matched']).to_excel(writer, index=False, sheet_name='Análisis Cartola')
        df_mayor.drop(columns=['Matched']).to_excel(writer, index=False, sheet_name='Análisis Mayor')
    
    return {"excel_bytes": output.getvalue()}
