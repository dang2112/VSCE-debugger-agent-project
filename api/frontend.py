#take HTTP request from VSCE frontend
#deserialize the request
#call orchestrator
#serialize the response
#send HTTP response back to VSCE frontend
#this file is the FastAPI routes

from fastapi import APIRouter, HTTPException

from api.schemas import (
    CreateDebugSessionRequest,
    CreateDebugSessionResponse,
    DebugResultResponse,
    DebugSessionStatusResponse,
    RunDebugSessionResponse,
)

from orchestrator.service import DebugOrchestrator


router = APIRouter(
    prefix="/debug",
    tags=["debug"]
)


orchestrator = DebugOrchestrator()


@router.post(
    "/sessions",
    response_model=CreateDebugSessionResponse
)
def create_debug_session(
    request: CreateDebugSessionRequest
):

    return orchestrator.create_session(request)


@router.get(
    "/sessions/{session_id}",
    response_model=DebugSessionStatusResponse
)
def get_debug_session(
    session_id: str
):

    session = orchestrator.get_session(
        session_id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Debug session not found"
        )

    return session


@router.post(
    "/sessions/{session_id}/run",
    response_model=RunDebugSessionResponse
)
def run_debug_session(
    session_id: str
):

    try:

        return orchestrator.run_session(
            session_id
        )

    except KeyError:

        raise HTTPException(
            status_code=404,
            detail="Debug session not found"
        )


@router.get(
    "/sessions/{session_id}/result",
    response_model=DebugResultResponse
)
def get_debug_result(
    session_id: str
):

    try:

        return orchestrator.get_result(
            session_id
        )

    except KeyError:

        raise HTTPException(
            status_code=404,
            detail="Debug session not found"
        )