import os


def get_openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "")
