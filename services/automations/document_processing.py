import io
import zipfile
import pandas as pd
import pdfplumber

def _get_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Resultado')
    return output.getvalue()

def procesar_pdf(contenido: bytes, nombre: str) -> dict:
    """Extrae tablas de un PDF usando pdfplumber y las convierte a un Excel."""
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        all_tables = []
        for page in pdf.pages:
            table = page.extract_table()
            if table:
                all_tables.extend(table)
                
    if not all_tables:
        raise ValueError("No se encontraron tablas estructuradas en el PDF.")
        
    # Asume que la primera fila extraida es el encabezado
    header = all_tables[0]
    data = all_tables[1:]
    
    df = pd.DataFrame(data, columns=header)
    return {"excel_bytes": _get_bytes(df)}

def procesar_generacion(contenido: bytes, nombre: str) -> dict:
    """Lee un Excel y genera multiples TXT agrupados en un ZIP emulando generacion de contratos/facturas."""
    df = pd.read_excel(io.BytesIO(contenido))
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for idx, row in df.iterrows():
            cliente = row.get("Nombre_Cliente", f"Cliente_{idx}")
            rut = row.get("RUT", "S/N")
            servicio = row.get("Servicio", "N/A")
            tarifa = row.get("Tarifa", 0)
            
            # Plantilla del documento
            doc_text = f"CONTRATO DE PRESTACION DE SERVICIOS\n\n"
            doc_text += f"Cliente: {cliente}\n"
            doc_text += f"RUT: {rut}\n\n"
            doc_text += f"Por el presente documento, se acuerda el servicio de {servicio}.\n"
            doc_text += f"Tarifa acordada: ${tarifa}\n\n"
            doc_text += "Firma: _________________\n"
            
            filename = f"contrato_{str(cliente).replace(' ', '_')}.txt"
            zip_file.writestr(filename, doc_text)
            
    return {"zip_bytes": zip_buffer.getvalue()}
