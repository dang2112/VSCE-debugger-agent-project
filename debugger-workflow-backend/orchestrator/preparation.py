"""Session preparation options shared by HTTP schemas and the SBFL adapter."""
from pydantic import BaseModel, ConfigDict, Field


class RunSBFLArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_root: str = Field(default="src", min_length=1)
    test_ids: list[str] = Field(default_factory=list, max_length=200)
    top_k: int = Field(default=10, ge=1, le=50)
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    test_timeout_seconds: float = Field(default=15, gt=0, le=120, allow_inf_nan=False)
    exclude_internet: bool = True


class PreparationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    sbfl: RunSBFLArguments = Field(default_factory=RunSBFLArguments)
    max_preload_files: int = Field(default=3, ge=0, le=10)
    max_file_requests: int = Field(default=20, ge=1, le=100)
    max_file_chars: int = Field(default=24000, ge=1000, le=100000)
    max_source_context_chars: int = Field(default=80000, ge=1000, le=300000)
