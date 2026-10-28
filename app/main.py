"""lectura-api: reading fluency microservice of Colegio Smart."""
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.routers import assessments, catalog, reports  # noqa: E402
from app.security import CsrfMiddleware  # noqa: E402
from app.settings import settings  # noqa: E402
from app.worker import Worker  # noqa: E402

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker = Worker(settings.worker_poll_seconds) if settings.worker_enabled else None
    if worker:
        worker.start()
    yield
    if worker:
        worker.stop()


app = FastAPI(title="lectura-api", version="0.1.0", lifespan=lifespan)
app.add_middleware(CsrfMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_allowed_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["Content-Type", "X-XSRF-TOKEN", "traceparent"])
for module in (catalog, assessments, reports):
    app.include_router(module.router)


@app.get("/actuator/health")
def health():
    return {"status": "UP"}
