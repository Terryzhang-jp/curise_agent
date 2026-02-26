import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import settings
from routes.auth import router as auth_router
from routes.settings import router as settings_router
from routes.excel import router as excel_router
from routes.orders import router as orders_router
from routes.chat import router as chat_router
from routes.tool_settings import router as tool_settings_router
from routes.users import router as users_router
from routes.data import router as data_router
from routes.line_webhook import router as line_router
from database import engine
from models import Base

app = FastAPI(
    title="Cruise Procurement Agent API",
    version="2.0.0",
    docs_url="/docs" if settings.DEBUG else None,
)

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_debug_origins = [
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS if not settings.DEBUG else _debug_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(excel_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(tool_settings_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(data_router, prefix="/api")
app.include_router(line_router, prefix="/api")

UPLOAD_DIR = settings.UPLOAD_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}
