from fastapi import FastAPI, HTTPException

from models import DebugRequest, DebugResponse
from debugger import debug_code
##this handles HTTP API endpoints that will be connected to the frontend


app = FastAPI(
    title="Python Debugger Backend",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post("/debug", response_model=DebugResponse)
def debug(request: DebugRequest):

    try:
        explanation = debug_code(
            source_code=request.source_code,
            error_log=request.error_log,
            filename=request.filename,
        )

        return DebugResponse(
            explanation=explanation
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )