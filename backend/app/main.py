from fastapi import FastAPI

app = FastAPI(
    title="KnowledgeOps AI",
    description="Enterprise knowledge and intelligent operations API",
    version="0.1.0",
)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
