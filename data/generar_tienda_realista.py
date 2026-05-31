import pandas as pd
import os

folder = os.path.dirname(os.path.abspath(__file__))

data_tienda = [
    # Coinciden exactamente con el banco (para prueba de "Coinciden")
    {'fecha': '2026-04-01', 'monto': 35000, 'medio_pago': 'Transferencia', 'referencia': 'Arriendo Cabaña'},
    {'fecha': '2026-04-01', 'monto': 26070, 'medio_pago': 'MercadoPago', 'referencia': 'Venta Panel Solar'},
    {'fecha': '2026-04-01', 'monto': 15500, 'medio_pago': 'MercadoPago', 'referencia': 'Venta Insumos'},
    {'fecha': '2026-04-06', 'monto': 380000, 'medio_pago': 'Transferencia', 'referencia': 'Sueldo Administrador'},
    {'fecha': '2026-04-06', 'monto': 19640, 'medio_pago': 'Tarjeta Débito', 'referencia': 'Insumos Oficina'},
    
    # Coincide monto pero difiere fecha levemente (simular desfase, quedarán en "Solo Banco" y "Solo Tienda")
    {'fecha': '2026-04-02', 'monto': 7000, 'medio_pago': 'MercadoPago', 'referencia': 'Venta Insumos (Desfase)'},
    {'fecha': '2026-04-07', 'monto': 145607, 'medio_pago': 'Crédito', 'referencia': 'Pago TDC (Desfase)'},
    
    # Exclusivos de la tienda (no están en el banco)
    {'fecha': '2026-04-02', 'monto': 45000, 'medio_pago': 'Efectivo', 'referencia': 'Venta Mostrador #001'},
    {'fecha': '2026-04-03', 'monto': 12500, 'medio_pago': 'Efectivo', 'referencia': 'Venta Mostrador #002'},
    {'fecha': '2026-04-05', 'monto': 8990, 'medio_pago': 'Transbank', 'referencia': 'Venta Web #5092'},
    {'fecha': '2026-04-08', 'monto': 150000, 'medio_pago': 'Transferencia', 'referencia': 'Abono Proyecto A'},
    {'fecha': '2026-04-10', 'monto': 22000, 'medio_pago': 'Efectivo', 'referencia': 'Caja Chica'}
]

pd.DataFrame(data_tienda).to_excel(os.path.join(folder, 'ejemplo_tienda.xlsx'), index=False)
print("Archivo ejemplo_tienda.xlsx generado con formato profesional pyme.")
