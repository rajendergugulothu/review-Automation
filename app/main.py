import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import review, feedback, admin


def _allowed_origins() -> list[str]:
    origins = {
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    }

    frontend_base_url = os.getenv("FRONTEND_BASE_URL", "").strip().rstrip("/")
    if frontend_base_url:
        origins.add(frontend_base_url)

    extra_origins = os.getenv("CORS_ALLOW_ORIGINS", "")
    for origin in extra_origins.split(","):
        cleaned = origin.strip().rstrip("/")
        if cleaned:
            origins.add(cleaned)

    return sorted(origins)


app = FastAPI(title="Urban Review System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review.router)
app.include_router(feedback.router)
app.include_router(admin.router)
