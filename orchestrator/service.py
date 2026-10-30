#placeholder orchestrator service
from tools.memorysystem import MemoryEntry, MemoryEntryType, MemoryStore
from agents.direct_debugger import debug_direct, review_debug_analysis
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
    CancelDebugSessionResponse,
)


class DebugOrchestrator:

    def __init__(self, memory_store: MemoryStore | None = None):

        self.sessions = {}
        self.memory = memory_store if memory_store is not None else MemoryStore()

    def _load_session(self, session_id: str) -> DebugSession:
        if session_id not in self.sessions:
            try:
                self.sessions[session_id] = self.memory.load(session_id).session
            except FileNotFoundError:
                raise KeyError(session_id) from None
        return self.sessions[session_id]


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
        self.memory.save(session)

        return CreateDebugSessionResponse(
            session_id=session.session_id,
            status=session.stage,
        )


    def get_session(
        self,
        session_id: str
    ) -> DebugSessionStatusResponse | None:

        try:
            session = self._load_session(session_id)
        except KeyError:
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

        session = self._load_session(session_id)

        # Durable state determines where to resume, even after a failed save.
        session = self.memory.load(session_id).session
        self.sessions[session_id] = session

        if session.stage in (
            DebugStage.COMPLETED,
            DebugStage.CANCELLED,
        ):

            return RunDebugSessionResponse(
                session_id=session.session_id,
                status=session.stage,
            )

        if session.mode in (DebugMode.DIRECT, DebugMode.TWO_THINKING_TIMES):
            try:
                self._run_analysis(session)
            except Exception as exc:
                session.stage = DebugStage.FAILED
                session.debug_error = str(exc)
                session.final_explanation = None
                self.memory.save(session)
                raise

        # Placeholder only.
        # Actual pipeline comes later.
        elif session.mode == DebugMode.AGENT:
            session.stage = DebugStage.COLLECTING_EVIDENCE
            self.memory.save(session)

        return RunDebugSessionResponse(
            session_id=session.session_id,
            status=session.stage,
        )

    def _run_analysis(self, session: DebugSession) -> None:
        """Each persisted step result is a checkpoint; retry only missing steps."""
        session_id = session.session_id
        persisted = self.memory.load(session_id)
        initial = next((entry for entry in reversed(persisted.entries)
                        if entry.step == DebugStage.ROOT_CAUSE_ANALYSIS.value
                        and entry.type in (MemoryEntryType.HYPOTHESIS,
                                           MemoryEntryType.OBSERVATION)), None)
        session.debug_error = None

        if initial is None:
            session.stage = DebugStage.ROOT_CAUSE_ANALYSIS
            self.memory.save(session)
            explanation = debug_direct(
                problem=session.problem,
                context=session.context,
                memory_context=self.memory.prompt_context(session_id),
            )
            initial = MemoryEntry(
                type=MemoryEntryType.HYPOTHESIS,
                step=DebugStage.ROOT_CAUSE_ANALYSIS.value,
                summary="Initial debugging analysis completed.",
                result=explanation,
            )
            # Persist output before moving on, including for DIRECT mode.
            self.memory.save(session, initial)

        final = initial
        if session.mode == DebugMode.TWO_THINKING_TIMES:
            session.stage = DebugStage.REVIEWING_ANALYSIS
            self.memory.save(session)
            # Reload the checkpoint rather than using an in-memory LLM answer.
            persisted = self.memory.load(session_id)
            initial_index = max(index for index, entry in enumerate(persisted.entries)
                                if entry.step == DebugStage.ROOT_CAUSE_ANALYSIS.value
                                and entry.type in (MemoryEntryType.HYPOTHESIS,
                                                   MemoryEntryType.OBSERVATION))
            final = next((entry for entry in reversed(persisted.entries[initial_index + 1:])
                          if entry.step == DebugStage.REVIEWING_ANALYSIS.value
                          and entry.type in (MemoryEntryType.REFLECTION,
                                             MemoryEntryType.OBSERVATION)), None)
            if final is None:
                explanation = review_debug_analysis(
                    problem=persisted.session.problem,
                    context=persisted.session.context,
                    previous_entry=persisted.entries[initial_index],
                )
                final = MemoryEntry(
                    type=MemoryEntryType.REFLECTION,
                    step=DebugStage.REVIEWING_ANALYSIS.value,
                    summary="Confidence review completed.",
                    result=explanation,
                )
                self.memory.save(session, final)

        session.final_explanation = final.result
        session.stage = DebugStage.COMPLETED
        self.memory.save(session)


    def get_result(
        self,
        session_id: str
    ) -> DebugResultResponse:

        session = self._load_session(session_id)

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
            error=session.debug_error,
        )

    def cancel_session(
        self,
        session_id: str
    ) -> CancelDebugSessionResponse:

        session = self._load_session(session_id)


        if session.stage in (
            DebugStage.COMPLETED,
            DebugStage.FAILED,
            DebugStage.CANCELLED,
        ):
            return CancelDebugSessionResponse(
                session_id=session.session_id,
                status=session.stage,
            )


        session.stage = DebugStage.CANCELLED
        self.memory.save(session)

        return CancelDebugSessionResponse(
            session_id=session.session_id,
            status=session.stage,
        )
