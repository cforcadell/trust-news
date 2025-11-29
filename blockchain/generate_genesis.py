import json

# CONFIGURACIÓN
chain_id = 1214
period = 1
epoch = 30000
gas_limit = "0x8000000"
difficulty = "0x1"

# Lista de validadores (pueden tener 0x y mayúsculas)
validators = [
    "0xED47E71846D68f17Aa2156252ee00949a7a1FDFF"
]

# Función para generar extraData
def generate_extra_data(validators):
    # 32 bytes ceros
    extra_data = "00" * 32
    # Añadir cada validador (20 bytes cada uno)
    for v in validators:
        clean_v = v.lower().replace("0x", "")
        if len(clean_v) != 40:
            raise ValueError(f"Dirección inválida: {v}")
        extra_data += clean_v
    # Relleno de 65 bytes al final
    extra_data += "00" * 65
    return "0x" + extra_data

# Crear genesis
genesis = {
    "config": {
        "chainId": chain_id,
        "homesteadBlock": 0,
        "eip150Block": 0,
        "eip155Block": 0,
        "eip158Block": 0,
        "byzantiumBlock": 0,
        "constantinopleBlock": 0,
        "petersburgBlock": 0,
        "istanbulBlock": 0,
        "clique": {
            "period": period,
            "epoch": epoch
        }
    },
    "nonce": "0x0",
    "timestamp": "0x0",
    "extraData": generate_extra_data(validators),
    "gasLimit": gas_limit,
    "difficulty": difficulty,
    "mixHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "coinbase": "0x0000000000000000000000000000000000000000",
    "alloc": {},
    "number": "0x0",
    "gasUsed": "0x0",
    "parentHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
    "baseFeePerGas": None
}

# Asignar saldo inicial a todos los validadores automáticamente
initial_balance = "0x3635C9ADC5DEA00000"  # 100 ETH en wei
for v in validators:
    clean_v = v.lower().replace("0x", "")
    genesis["alloc"][clean_v] = {"balance": initial_balance}

# Guardar en genesis.json
with open("genesis.json", "w") as f:
    json.dump(genesis, f, indent=2)

print("genesis.json generado correctamente con los validadores y saldo inicial:")
for v in validators:
    print("-", v)
