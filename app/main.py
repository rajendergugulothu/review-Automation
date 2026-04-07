from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import review, feedback, admin

app = FastAPI(title="Urban Review System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review.router)
app.include_router(feedback.router)
app.include_router(admin.router)
