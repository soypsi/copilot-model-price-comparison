set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

serve:
    python3 scripts/serve.py

update:
    python3 scripts/update_models.py

serve-updated:
    just update
    python3 scripts/serve.py
