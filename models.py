from pydantic import BaseModel
##this defines the formats for receiving the request from frontend and sending the frontend the response

class SourceFile(BaseModel):
    path: str
    content: str


class DebugProblem(BaseModel):
    error_log: str | None = None


class DebugContext(BaseModel):
    files: list[SourceFile] = Field(default_factory=list)


class DebugRequest(BaseModel):
    problem: DebugProblem
    context: DebugContext


class DebugResponse(BaseModel):
    explanation: str