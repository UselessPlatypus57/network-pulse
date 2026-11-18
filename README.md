# Network Pulse

A small network health & outage monitor for simulated cellular sites.

> Work in progress — see the git log for the build history.

## Backend (dev)

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate      # Windows (use `source .venv/bin/activate` on macOS/Linux)
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://localhost:8000/docs.
