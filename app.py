# app.py — compatibility shim
# Nano Banana Studio has been renamed to nbs.py
# This file exists so that "python app.py" still works.
import runpy, os
runpy.run_path(os.path.join(os.path.dirname(__file__), "nbs.py"), run_name="__main__")
