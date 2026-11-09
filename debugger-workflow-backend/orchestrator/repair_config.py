"""Repair policy; execution commands and interpreter are never model-controlled."""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from orchestrator.actions import ReadFileArguments


class RepairConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    max_attempts: int = Field(default=3, ge=1, le=5)
    test_targets: list[str] = Field(default_factory=lambda: ['tests'], min_length=1, max_length=100)
    regression_tests: list[str] = Field(default_factory=list, max_length=100)
    run_full_suite: bool = True
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    max_snapshot_files: int = Field(default=3000, ge=1, le=10000)
    max_snapshot_bytes: int = Field(default=50000000, ge=1000, le=200000000)

    @field_validator('test_targets', 'regression_tests')
    @classmethod
    def selectors_are_relative(cls, values):
        for value in values:
            path = value.split('::', 1)[0]
            if path != '.':
                ReadFileArguments(path=path)
        return values
