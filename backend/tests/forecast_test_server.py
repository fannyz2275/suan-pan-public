"""Local-only synthetic HTTP harness: never uses Supabase, user data, or AI APIs.

PYTHONPATH=backend .venv/bin/uvicorn tests.forecast_test_server:app --port 8099
"""
from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.engine.forecast_service import ForecastUpdate, load_forecast
from tests.forecast_fixture import FixtureDB, UID, TODAY

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5173', 'http://localhost:5173'], allow_methods=['*'], allow_headers=['*'])
db = FixtureDB()


@app.post('/reset')
def reset(tables: dict | None = Body(default=None)):
    global db
    db = FixtureDB()
    if tables is not None:
        db.tables.update(tables)
    return {'ok':True}


@app.get('/fixture')
def fixture():
    return db.tables


@app.get('/engine/forecast')
def forecast(months: int = 12):
    return load_forecast(db, UID, months=months, today=TODAY)


@app.patch('/engine/forecast')
def update(body: ForecastUpdate, months: int = 12):
    return load_forecast(db, UID, months=months, update=body, today=TODAY)
