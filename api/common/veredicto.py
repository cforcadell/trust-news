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

    def __post_init__(self):
        # Convertir a mayúsculas una sola vez
        
        texto_upper = self.texto.upper()

        if "TRUE" in texto_upper:
            # Si contiene "TRUE", el estado es Verdadero
            self.estado = Validacion.TRUE
        elif "FALSE" in texto_upper:
            # Si contiene "FALSE" (y no "TRUE"), el estado es Falso
            self.estado = Validacion.FALSE
        else:
            # Si no contiene ninguno de los dos, el estado es Desconocido (UNKNOWN)
            self.estado = Validacion.UNKNOWN
            
