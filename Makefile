.PHONY: install test api worker frontend demo
install:
	uv venv --python python3.11 .venv
	uv pip install --python .venv/bin/python -r requirements.lock
	cd frontend && npm ci

test:
	.venv/bin/python -m pytest -q
	cd frontend && npm run build

api:
	PYTHONPATH=backend .venv/bin/python -m uvicorn finagent.api:app --host 127.0.0.1 --port 8000

worker:
	PYTHONPATH=backend .venv/bin/python -m finagent.worker

frontend:
	cd frontend && npm run dev -- --host 127.0.0.1

demo:
	.venv/bin/python scripts/e2e_demo.py
