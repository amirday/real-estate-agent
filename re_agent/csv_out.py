import os


def ensure_dirs():
    os.makedirs("out", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

