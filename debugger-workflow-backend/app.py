from fastapi import FastAPI
from api.frontend import router as debug_router
#the app enters here

app = FastAPI(
    title="Debugger Workflow Backend",
    version="0.3.0",
)


app.include_router( #expose these routes
    debug_router
)


@app.get("/health")
def health():

    return {
        "status": "ok",
        "version": "0.3.0"
    }