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
    RunDebugSessionResponse,
)


class DebugOrchestrator:

    def __init__(self):

        self.sessions = {}


    def create_session(
        self,
        request: CreateDebugSessionRequest
    ) -> CreateDebugSessionResponse:

        session = DebugSession(
            mode=request.mode,
            problem=request.problem,
            context=request.context,
        )

        self.sessions[session.session_id] = session

        return CreateDebugSessionResponse(
            session_id=session.session_id,
            status=session.stage,
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
            session_id=session.session_id,
            status=session.stage,
            patch_attempt=len(session.patch_attempts),
            max_patch_attempts=session.max_patch_attempts,
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