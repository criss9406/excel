import os
import pandas as pd
from io import BytesIO

bank_file = os.path.join(os.path.dirname(__file__), 'data', 'Cartola de cuenta Corriente - Abril 2026.xlsx')

with open(bank_file, "rb") as f:
    contents = f.read()

df = pd.read_excel(BytesIO(contents), engine="openpyxl")
if "Banco Santander" in str(df.columns[0]) or "DETALLE DE MOVIMIENTOS" in df.iloc[:, 0].astype(str).values:
    header_row_idx = df[df.iloc[:, 0].astype(str).str.strip().str.upper() == "FECHA"].index
    if not header_row_idx.empty:
        idx = header_row_idx[0]
        df = pd.read_excel(BytesIO(contents), header=idx + 1, engine="openpyxl")
        df.columns = df.columns.str.strip().str.upper()
        df = df.rename(columns=lambda x: x.replace("Ó", "O").replace("Í", "I").replace(" ", "_"))
        
        col_cargos = [c for c in df.columns if "CARGOS" in c]
        col_abonos = [c for c in df.columns if "ABONOS" in c]
        
        if col_cargos and col_abonos:
            df["cargos_num"] = pd.to_numeric(df[col_cargos[0]], errors="coerce")
            df["abonos_num"] = pd.to_numeric(df[col_abonos[0]], errors="coerce")
            
            df["monto"] = df["abonos_num"].fillna(df["cargos_num"])
            df["tipo"] = df.apply(lambda row: "Abono" if pd.notnull(row["abonos_num"]) else "Cargo", axis=1)
            
            df["fecha"] = df["FECHA"].astype(str).str.strip()
            df.loc[df["fecha"].str.len() <= 5, "fecha"] += "/2026"
            
            col_desc = [c for c in df.columns if "DESCRIPCION" in c or "DESCRIPCIN" in c]
            if col_desc:
                df = df.rename(columns={col_desc[0]: "descripcion"})
            else:
                df["descripcion"] = "Sin descripción"
                
            df = df.dropna(subset=["monto"])
            df = df[df["fecha"].str.contains(r"\d{2}/\d{2}", regex=True, na=False)]
            df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y", errors="coerce").dt.strftime("%Y-%m-%d")
            
            print(df[["fecha", "monto", "descripcion", "tipo"]].head(10))
