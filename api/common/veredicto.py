from enum import IntEnum
from dataclasses import dataclass

class Validacion(IntEnum):
    UNKNOWN = 0  # Desconocido
    TRUE = 1     # Verdadero
    FALSE = 2    # Falso
    
from dataclasses import dataclass

@dataclass
class Veredicto:
    texto: str
    estado: Validacion = Validacion.UNKNOWN # Valor por defecto


            
