"""Shared bounded Python subprocess execution for local tool adapters."""
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable


class PythonProcessRunner:
    def __init__(self, python_executable: str):
        self.python = python_executable

    @staticmethod
    def _stop_process(process) -> None:
        if os.name == "nt":
            import psutil
            try:
                descendants = psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                descendants = []
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            # A Windows venv launcher can exit before its Python child releases
            # the working directory. Wait for descendants before temp cleanup.
            _, alive = psutil.wait_procs(descendants, timeout=5)
            for child in alive:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            psutil.wait_procs(alive, timeout=5)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait()

    def _execute(self, args: list[str], workspace: Path, env: dict, log: Path, timeout: float,
                 is_cancelled: Callable[[], bool] | None = None) -> int:
        if timeout <= 0:
            raise TimeoutError("Tool exceeded its wall-clock timeout")
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                [self.python, *args], cwd=workspace, env=env, stdout=output,
                stderr=subprocess.STDOUT, shell=False,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            deadline = time.monotonic() + timeout
            try:
                while True:
                    if is_cancelled and is_cancelled():
                        raise RuntimeError("Tool session cancelled")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Tool exceeded its wall-clock timeout")
                    try:
                        return process.wait(timeout=min(0.25, remaining))
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                self._stop_process(process)
                raise

