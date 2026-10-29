"""El Learning Record Store: armar las sentencias xAPI y mandarlas a Learning Locker.

Learning Locker es software de terceros (gris en el C4): se instala y se consume. Lo que se
escribe aquí es el servicio que arma la sentencia y la cola que la reenvía, y **ninguna función
de la app depende de que el LRS esté encendido** (RF-19, RF-33).
"""
