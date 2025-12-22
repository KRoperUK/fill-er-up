import importlib.util
import os


def _load_module_from_path(path: str):
    spec = importlib.util.spec_from_file_location("stateless_api_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Load the Flask app from the hyphenated filename
_MODULE_PATH = os.path.join(os.path.dirname(__file__), "stateless-api.py")
_mod = _load_module_from_path(_MODULE_PATH)

# Gunicorn entrypoint: `api.wsgi:app`
app = _mod.create_app()
