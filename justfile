set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

serve:
    python3 -m http.server 8000

update:
    python3 scripts/update_models.py

serve-updated:
    just update
    python3 -m http.server 8000
