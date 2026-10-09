from pydantic import BaseModel
##this defines the formats for receiving the request from frontend and sending the frontend the response

class DebugRequest(BaseModel):
    source_code: str
    error_log: str | None = None
    filename: str | None = None


class DebugResponse(BaseModel):
    explanation: str