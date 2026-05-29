from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router

# Initialize the core application with clean OpenAPI documentation tags
app = FastAPI(
    title="Telco Mind - Async Simu5G Microservice Engine Backend",
    description="Production-grade 3GPP/O-RAN digital twin simulation workspace controller.",
    version="2.0.0"
)

# Enable Cross-Origin Resource Sharing (CORS) so Member 3's frontend or agent can reach it
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bind our API routes directly onto the core lifecycle engine
app.include_router(router)

@app.get("/", tags=["Health Check"])
async def root_health_check():
    """
    Immediate service health heartbeat path.
    """
    return {
        "status": "ONLINE",
        "service": "Telco Mind Simulation Backend",
        "standardization_alignment": "3GPP TS 38.300 / O-RAN WG1"
    }
