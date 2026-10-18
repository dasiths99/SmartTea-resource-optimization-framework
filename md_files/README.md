# SmartTea-LK Component 04: Resource Optimization Framework

AI-based tea plantation resource optimization and intervention planning. The system recommends **what to do next, how much, and when** for fertilizer, irrigation, fungicide and pH correction on each tea block. It uses a three-tier pipeline: XGBoost prediction → NSGA-II optimization → forecast-aware Action-Window scheduling.

| Where | What |
|---|---|
| [`data/`](data/README.md) | All datasets: raw downloads → real data pack → hybrid dataset → **model-ready** tables. Start with `md_files/data/README.md` |
| [`data/DATA_DICTIONARY.md`](data/DATA_DICTIONARY.md) | Every column of every table |
| `src/data/` | Data pipeline and the `load_task()` loader |
| `src/models`, `src/optimizer`, `src/scheduler`, `src/api` | Python ML service (Tiers 1–3, FastAPI) |
| `backend/`, `frontend/` | Spring Boot + MongoDB, React + Tailwind |
| `docs/` | Project context and the research report |

## Quick start
```powershell
py -3.14 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
python -c "from src.data.load import load_task; X, y, meta = load_task('yield'); print(X.shape)"
```

Data note: weather, forecasts and soil are real. Management, crop response and runoff are simulated (see `md_files/data/README.md`).
