"""Locating and configuring the DPTechDraw binary.

The CLI features this server depends on are NOT in any stable QET release.
They exist only on the source-mirror head (PRs #489, #490, #493, listed under
"Unreleased" in ChangeLog.MD). A locally built binary is required.

See qet-ai/docs-ai/03-cli-and-io.md for the full CLI reference.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Defaults matching the local build. Override with environment variables.
# qet-ai lives inside the DPTechDraw source tree: <repo>/qet-ai/qet_mcp/config.py
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = REPO_ROOT / "build" / "DPTechDraw.exe"
DEFAULT_QT_BIN = Path(r"C:\Qt\6.10.1\mingw_64\bin")


class QetNotFoundError(RuntimeError):
    """The DPTechDraw binary could not be located."""


@dataclass(frozen=True)
class QetConfig:
    """Resolved paths and environment for invoking DPTechDraw.exe."""

    exe: Path
    qt_bin: Path | None = None
    offscreen: bool = True
    timeout: float = 120.0
    extra_env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "QetConfig":
        """Build a config from QET_EXE / QET_QT_BIN / QET_OFFSCREEN / QET_TIMEOUT."""
        raw_exe = os.environ.get("QET_EXE")
        if raw_exe:
            exe = Path(raw_exe)
        elif DEFAULT_EXE.is_file():
            exe = DEFAULT_EXE
        else:
            found = shutil.which("DPTechDraw") or shutil.which("DPTechDraw.exe")
            if not found:
                raise QetNotFoundError(
                    "Could not find DPTechDraw.exe. Set QET_EXE to its full path. "
                    f"Looked at {DEFAULT_EXE} and on PATH."
                )
            exe = Path(found)

        if not exe.is_file():
            raise QetNotFoundError(f"QET_EXE points at a missing file: {exe}")

        raw_qt = os.environ.get("QET_QT_BIN")
        if raw_qt:
            qt_bin: Path | None = Path(raw_qt)
        elif DEFAULT_QT_BIN.is_dir():
            qt_bin = DEFAULT_QT_BIN
        else:
            qt_bin = None

        return cls(
            exe=exe,
            qt_bin=qt_bin,
            offscreen=os.environ.get("QET_OFFSCREEN", "1") not in ("0", "false", "no"),
            timeout=float(os.environ.get("QET_TIMEOUT", "120")),
        )

    def build_env(self) -> dict[str, str]:
        """Environment for the subprocess.

        Qt DLLs must be reachable on Windows, and a headless host needs the
        offscreen platform plugin because the CLI path still constructs a full
        QApplication (sources/main.cpp:125).
        """
        env = dict(os.environ)
        if self.qt_bin is not None:
            env["PATH"] = str(self.qt_bin) + os.pathsep + env.get("PATH", "")
        if self.offscreen:
            env.setdefault("QT_QPA_PLATFORM", "offscreen")
        # QET sets this itself (main.cpp:93) to make output diffable; harmless
        # to reassert, and it makes our intent explicit.
        env.setdefault("QT_HASH_SEED", "0")
        env.update(self.extra_env)
        return env
