from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from pathlib import Path

import streamlit as st
import yaml

from dashboard.config import PROJECT_ROOT

DEFAULT_ITERATIONS = 390_000


def hash_password(password: str, *, salt: str | None = None, iterations: int = DEFAULT_ITERATIONS) -> str:
    if salt is None:
        salt = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${iterations}${salt}${encoded}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        scheme, iter_text, salt, expected = encoded_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    actual = hash_password(password, salt=salt, iterations=int(iter_text)).split("$", 3)[3]
    return hmac.compare_digest(actual, expected)


def _load_users(users_file: str | Path) -> dict:
    path = Path(users_file)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get("users", {})


def require_login(settings: dict) -> bool:
    auth_settings = settings.get("auth", {})
    if not auth_settings.get("enabled", False):
        with st.sidebar:
            st.warning("Authentication is disabled. Enable it before multi-user deployment.")
        return True
    users = _load_users(auth_settings.get("users_file", "dashboard/config/users.yaml"))
    if not users:
        st.error("Authentication is enabled, but no users.yaml file was found.")
        st.code("cp dashboard/config/users.example.yaml dashboard/config/users.yaml\npython scripts/hash_password.py")
        st.stop()
    if st.session_state.get("authenticated"):
        return True
    st.title("PCORIExplorer login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        user = users.get(username)
        if user and verify_password(password, user.get("password_hash", "")):
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            st.session_state["role"] = user.get("role", "viewer")
            st.rerun()
        st.error("Invalid username or password.")
    st.stop()
