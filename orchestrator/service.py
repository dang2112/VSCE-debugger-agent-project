#placeholder orchestrator service
from uuid import uuid4

from api.schemas import (
    CreateDebugSessionRequest,
    CreateDebugSessionResponse,
    DebugResultResponse,
    DebugSessionStatusResponse,
    DebugStage,
    RunDebugSessionResponse,
)


class DebugOrchestrator:

    def __init__(self):

        self.sessions = {}


    def create_session(
        self,
        request: CreateDebugSessionRequest
    ) -> CreateDebugSessionResponse:

        session_id = str(uuid4())

        self.sessions[session_id] = {
            "request": request,
            "status": DebugStage.CREATED,
            "patch_attempt": 0,
            "result": None,
        }

        return CreateDebugSessionResponse(
            session_id=session_id,
            status=DebugStage.CREATED,
        )


    def get_session(
        self,
        session_id: str
    ) -> DebugSessionStatusResponse | None:

        session = self.sessions.get(
            session_id
        )

        if session is None:
            return None

        return DebugSessionStatusResponse(
            session_id=session_id,
            status=session["status"],
            patch_attempt=session["patch_attempt"],
            max_patch_attempts=3,
        )


    def run_session(
        self,
        session_id: str
    ) -> RunDebugSessionResponse:

        if session_id not in self.sessions:
            raise KeyError(session_id)

        session = self.sessions[session_id]

        # Placeholder only.
        # Actual pipeline comes later.
        session["status"] = (
            DebugStage.COLLECTING_EVIDENCE
        )

        return RunDebugSessionResponse(
            session_id=session_id,
            status=session["status"],
        )


    def get_result(
        self,
        session_id: str
    ) -> DebugResultResponse:

        if session_id not in self.sessions:
            raise KeyError(session_id)

        session = self.sessions[session_id]

        return DebugResultResponse(
            session_id=session_id,
            status=session["status"],
            explanation=None,
            patch=None,
            verification_status=None,
        )