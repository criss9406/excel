import pandas as pd
import os

folder = os.path.dirname(os.path.abspath(__file__))

data_banco = [
    {'fecha': '2026-04-01', 'monto': 150000, 'descripcion': 'Depósito en Efectivo', 'tipo': 'Abono'},
    {'fecha': '2026-04-02', 'monto': 25000, 'descripcion': 'Transferencia Recibida', 'tipo': 'Abono'},
    {'fecha': '2026-04-03', 'monto': -5000, 'descripcion': 'Comisión Mensual', 'tipo': 'Cargo'},
    {'fecha': '2026-04-05', 'monto': 34000, 'descripcion': 'Pago Transbank', 'tipo': 'Abono'},
    {'fecha': '2026-04-06', 'monto': 12000, 'descripcion': 'Transferencia Desconocida', 'tipo': 'Abono'}
]

data_tienda = [
    {'fecha': '2026-04-01', 'monto': 150000, 'medio_pago': 'Efectivo', 'referencia': 'Caja 1'},
    {'fecha': '2026-04-02', 'monto': 25000, 'medio_pago': 'Transferencia', 'referencia': 'Pedido #1024'},
    {'fecha': '2026-04-05', 'monto': 34000, 'medio_pago': 'Tarjeta Debito', 'referencia': 'Cierre Transbank'},
    {'fecha': '2026-04-07', 'monto': 45000, 'medio_pago': 'Webpay', 'referencia': 'Pedido #1025'}
]

pd.DataFrame(data_banco).to_excel(os.path.join(folder, 'ejemplo_banco_formateado.xlsx'), index=False)
pd.DataFrame(data_tienda).to_excel(os.path.join(folder, 'ejemplo_tienda.xlsx'), index=False)

print('Archivos creados.')
