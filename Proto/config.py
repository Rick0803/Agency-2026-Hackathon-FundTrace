# config.py
# Unified configuration loader for local .env and Streamlit Cloud secrets

import os
from pathlib import Path


def get_env(key: str, default: str = "") -> str:
    """
    Get environment variable from either:
    1. Streamlit secrets (when deployed to Streamlit Cloud)
    2. OS environment variables (when running locally with .env)
    
    Args:
        key: Environment variable name
        default: Default value if not found
        
    Returns:
        Environment variable value or default
    """
    # Try Streamlit secrets first (for cloud deployment)
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and key in st.secrets:
            return str(st.secrets[key])
    except (ImportError, FileNotFoundError, KeyError):
        pass
    
    # Fall back to OS environment variables (for local development)
    return os.getenv(key, default)


def load_env_file():
    """
    Load .env file for local development.
    This is called automatically when the module is imported.
    """
    env_file = Path(__file__).parent / '.env'
    
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and not os.getenv(key):
                        os.environ[key] = value


# Auto-load .env file when module is imported
load_env_file()


# Export commonly used config values
DB_CONNECTION_STRING = get_env("DB_CONNECTION_STRING")
USE_BEDROCK = get_env("USE_BEDROCK", "true").lower() == "true"
AWS_DEFAULT_REGION = get_env("AWS_DEFAULT_REGION", "us-west-2")
AWS_ACCESS_KEY_ID = get_env("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = get_env("AWS_SECRET_ACCESS_KEY")
AWS_SESSION_TOKEN = get_env("AWS_SESSION_TOKEN")
BEDROCK_MODEL = get_env("BEDROCK_MODEL", "anthropic.claude-opus-4-5-20251101-v1:0")
ANTHROPIC_API_KEY = get_env("ANTHROPIC_API_KEY")
CLAUDE_MODEL = get_env("CLAUDE_MODEL", "claude-sonnet-4-6")
BQ_DATA_PROJECT = get_env("BQ_DATA_PROJECT")
BQ_TEAM_PROJECT = get_env("BQ_TEAM_PROJECT")
