set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

serve:
    python3 scripts/serve.py

update:
    python3 scripts/update_models.py

serve-updated:
    just update
    python3 scripts/serve.py

test:
    python3 -m unittest tests/test_update_models.py -v

cicd-check:
    uvx zizmor --gh-token $(gh auth token) --persona=auditor .github/workflows/pages.yml
