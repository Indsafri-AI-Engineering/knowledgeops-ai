import os
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from backend.app.core.environment import load_environment

if os.getenv("APP_ENV", "").lower() != "test":
    load_environment()

from backend.app.api.v1.router import router as api_v1_router
from backend.app.core.observability import request_metrics

app = FastAPI(
    title="KnowledgeOps AI",
    description="Enterprise knowledge and intelligent operations API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
            
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def attach_request_id(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    request_id = uuid4()
    request.state.request_id = request_id
    started_at = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = str(request_id)
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", "<unmatched>")
        request_metrics.record(
            request.method,
            route_path,
            status_code,
            perf_counter() - started_at,
        )


app.include_router(api_v1_router)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
