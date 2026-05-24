import os
from urllib.parse import quote_plus


def build_mongo_uri_from_env(default_host: str = "mongodb", default_port: str = "27017") -> str:
    explicit_uri = os.getenv("MONGO_URI")
    if explicit_uri:
        return explicit_uri

    user = os.getenv("MONGO_APP_USER")
    password = os.getenv("MONGO_APP_PWD")
    db_name = os.getenv("MONGO_DBNAME") or os.getenv("MONGO_APP_DATABASE") or "newsdb"
    host = os.getenv("MONGO_APP_HOST", default_host)
    port = os.getenv("MONGO_APP_PORT", default_port)
    auth_source = os.getenv("MONGO_APP_AUTHSOURCE", db_name)

    if user and password:
        escaped_user = quote_plus(user)
        escaped_password = quote_plus(password)
        escaped_auth_source = quote_plus(auth_source)
        return f"mongodb://{escaped_user}:{escaped_password}@{host}:{port}/{db_name}?authSource={escaped_auth_source}"

    return f"mongodb://{host}:{port}"
