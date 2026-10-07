"""Sandbox: static AST validation + execution in a separate, locked-down subprocess.

Layers of defence (defence in depth, no single layer is trusted alone):
  1. AST check rejects imports, dunder/underscore access, eval/exec/open, file/network
     style attributes, str.format tricks, etc. *before* anything runs.
  2. The code runs in a fresh subprocess with a 10 s timeout, a scrubbed
     environment (no API keys) and a whitelist of builtins (see sandbox_runner.py).
  3. Only `pd`, `np` and a private copy of `df` are visible to the code.
For a real production deployment also run the backend inside a container / jail.
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).with_name("sandbox_runner.py")
MARKER = "@@PCDA_RESULT@@"
TIMEOUT_SECONDS = 10
MAX_CODE_CHARS = 6000


class CodeRejected(Exception):
    """The generated code failed the static safety check."""


BANNED_NAMES = {
    "eval", "exec", "compile", "open", "__import__", "getattr", "setattr", "delattr",
    "hasattr", "globals", "locals", "vars", "dir", "input", "breakpoint", "exit", "quit",
    "help", "memoryview", "bytearray", "classmethod", "staticmethod", "property", "super",
    "type", "object", "os", "sys", "subprocess", "builtins", "importlib", "socket",
    "shutil", "pathlib", "ctypes", "pickle",
}

BANNED_ATTRS = {
    "eval", "query", "exec", "system", "popen", "open", "load", "loads", "loadtxt",
    "genfromtxt", "fromfile", "fromregex", "save", "savez", "savez_compressed", "savetxt",
    "tofile", "memmap", "ctypeslib", "testing", "io", "api", "options", "get_option",
    "set_option", "option_context", "reset_option", "describe_option", "format",
    "format_map", "style", "os", "sys", "subprocess", "importlib", "compat", "util", "lib",
    "core", "f2py", "distutils", "show_versions", "show_config", "test", "plot", "hist",
    "boxplot", "pickle",
}

# `to_*` helpers that are pure conversions (everything else, e.g. to_csv, is rejected)
ALLOWED_TO = {
    "to_datetime", "to_numeric", "to_period", "to_timestamp", "to_list", "to_dict",
    "to_numpy", "to_frame", "to_timedelta", "to_pydatetime", "to_series",
}

FORBIDDEN_NODES = (
    ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef, ast.AsyncFunctionDef,
    ast.AsyncFor, ast.AsyncWith, ast.Await, ast.Yield, ast.YieldFrom, ast.With,
)


def validate_code(code: str) -> None:
    """Raise CodeRejected if the code is not safe to run."""
    if not isinstance(code, str) or not code.strip():
        raise CodeRejected("No code was produced.")
    if len(code) > MAX_CODE_CHARS:
        raise CodeRejected("The code is too long.")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise CodeRejected(f"The code has a syntax error: {exc.msg}.")

    assigns_result = False
    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN_NODES):
            raise CodeRejected(f"{type(node).__name__} statements are not allowed (no imports, classes or file access).")
        if isinstance(node, ast.Name):
            if node.id in BANNED_NAMES or node.id.startswith("_"):
                raise CodeRejected(f"The name '{node.id}' is not allowed.")
            if node.id == "result" and isinstance(node.ctx, ast.Store):
                assigns_result = True
        elif isinstance(node, ast.Attribute):
            a = node.attr
            if a.startswith("_"):
                raise CodeRejected("Attributes starting with an underscore (e.g. dunder) are not allowed.")
            if a in BANNED_ATTRS or a.startswith("read_"):
                raise CodeRejected(f"The attribute '{a}' is not allowed.")
            if a.startswith("to_") and a not in ALLOWED_TO:
                raise CodeRejected(f"The attribute '{a}' is not allowed.")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "__" in node.value:
                raise CodeRejected("Strings containing '__' are not allowed.")
        elif isinstance(node, ast.arg) and node.arg.startswith("_"):
            raise CodeRejected("Argument names starting with underscore are not allowed.")
    if not assigns_result:
        raise CodeRejected("The code must assign the final value to a variable named `result`.")


def _safe_env() -> dict:
    keep = ("SYSTEMROOT", "SystemRoot", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "TMPDIR",
            "LANG", "LC_ALL", "HOME", "USERPROFILE", "VIRTUAL_ENV")
    return {k: os.environ[k] for k in keep if k in os.environ}  # no API keys leak in


def run_code(code: str, pickle_path: Path) -> dict:
    """Run validated code in a fresh subprocess. Returns the runner's JSON dict.

    {"ok": True, "result": {...}, "evidence": {...}} or {"ok": False, "error": "..."}
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(RUNNER), str(pickle_path)],
            input=code,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            env=_safe_env(),
            cwd=str(pickle_path.parent),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"The calculation took longer than {TIMEOUT_SECONDS} seconds.", "timeout": True}

    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith(MARKER):
            try:
                return json.loads(line[len(MARKER):])
            except json.JSONDecodeError:
                break
    tail = (proc.stderr or "").strip().splitlines()[-1:] or ["no output"]
    return {"ok": False, "error": f"The calculation did not finish ({tail[0][:200]})."}
