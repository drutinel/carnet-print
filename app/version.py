"""Versión del programa: la escribe el build en `_build_version.py`; en desarrollo es «dev»."""
try:
    from ._build_version import VERSION
except ImportError:
    VERSION = "dev"
