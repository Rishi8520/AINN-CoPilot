from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router, runner

app = FastAPI(
    title="TelcoMind Digital Twin",
    description="Continuous 7-gNB hexagonal digital twin driven by real Simu5G/OMNeT++ subprocess runs.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def on_startup():
    runner.start()


@app.on_event("shutdown")
def on_shutdown():
    runner.stop()
