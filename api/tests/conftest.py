import os
import pytest
from dotenv import load_dotenv

@pytest.fixture(scope="session", autouse=True)
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(env_path)
    print(f"✅ Cargadas variables de entorno desde {env_path}")
