#placeholder orchestrator service
from uuid import uuid4
from agents.direct_debugger import debug_direct
from orchestrator.state import (
    DebugMode,
    DebugSession,
    DebugStage,
)

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

        if session.mode == DebugMode.DIRECT:

            session.stage = DebugStage.ROOT_CAUSE_ANALYSIS

            explanation = debug_direct(
                problem=session.problem,
                context=session.context,
            )

            session.final_explanation = explanation
            session.stage = DebugStage.COMPLETED

        # Placeholder only.
        # Actual pipeline comes later.
        elif session.mode == DebugMode.AGENT:
            session.stage = DebugStage.COLLECTING_EVIDENCE

        return RunDebugSessionResponse(
            session_id=session.session_id,
            status=session.stage,
        )


    def get_result(
        self,
        session_id: str
    ) -> DebugResultResponse:

        if session_id not in self.sessions:
            raise KeyError(session_id)

        session = self.sessions[session_id]

        final_patch = None
        verification_status = None

        if session.patch_attempts:
            last_attempt = session.patch_attempts[-1]

            final_patch = last_attempt.patch.diff

            if last_attempt.verification is not None:
                verification_status = (
                    last_attempt.verification.overall_status
                )

        return DebugResultResponse(
            session_id=session.session_id,
            status=session.stage,
            explanation=session.final_explanation,
            patch=final_patch,
            verification_status=verification_status,
        )