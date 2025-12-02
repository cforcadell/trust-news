#!/usr/bin/env python3
import sys
from eth_account import Account

def get_private_key(keystore_path, password):
    with open(keystore_path) as f:
        keyfile_json = f.read()
    acct = Account.from_key(Account.decrypt(keyfile_json, password))
    return acct.key.hex()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Uso: {sys.argv[0]} <ruta_keyfile> <password>")
        sys.exit(1)

    path = sys.argv[1]
    pwd = sys.argv[2]

    try:
        private_key = get_private_key(path, pwd)
        print("Private key:", private_key)
    except Exception as e:
        print("Error:", e)
