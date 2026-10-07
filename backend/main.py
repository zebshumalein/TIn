"""Proof-Carrying Data Analyst - FastAPI backend. Run: uvicorn main:app --host 0.0.0.0 --port 8000"""
import io
import hmac
import json
import logging
import math
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")

import llm  # noqa: E402  (after load_dotenv)
import sample_data  # noqa: E402
from sandbox import CodeRejected, run_code, validate_code  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pcda")

MAX_BYTES = 10 * 1024 * 1024
MAX_TOTAL_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_JOINED_ROWS = 1_000_000
MAX_FILES = 5
ALLOWED_EXT = {".csv", ".xlsx", ".xls"}
MAX_SESSIONS = 100
SESSION_TTL = 2 * 60 * 60
PENDING_UPLOAD_TTL = 15 * 60
SESSION_DIR = BASE / ".sessions"
SESSION_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Proof-Carrying Data Analyst")
access_token = os.getenv("APP_ACCESS_TOKEN", "").strip()
if os.getenv("APP_ENV", "development").lower() == "production" and len(access_token) < 24:
    raise RuntimeError("APP_ACCESS_TOKEN must contain at least 24 characters in production.")

_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def require_access_token(request: Request, call_next):
    configured_token = os.getenv("APP_ACCESS_TOKEN", "").strip()
    if configured_token and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        authorization = request.headers.get("authorization", "")
        supplied_token = authorization.removeprefix("Bearer ").strip()
        if not authorization.startswith("Bearer ") or not hmac.compare_digest(
            supplied_token.encode("utf-8"), configured_token.encode("utf-8")
        ):
            return JSONResponse(status_code=401, content={"detail": "A valid app access token is required."})
    return await call_next(request)

# ---------------------------------------------------------------- sessions
_sessions: dict[str, dict] = {}
_pending_uploads: dict[str, dict] = {}
_lock = threading.Lock()


def _drop(sid: str) -> None:
    _sessions.pop(sid, None)
    try:
        (SESSION_DIR / f"{sid}.pkl").unlink(missing_ok=True)
    except OSError:
        pass


def register(df: pd.DataFrame, filename: str, source_names: list[str] | None = None) -> dict:
    df.columns = _unique_names(df.columns)
    sid = uuid.uuid4().hex
    df.to_pickle(SESSION_DIR / f"{sid}.pkl")  # copy used by the sandbox subprocess
    now = time.time()
    with _lock:
        for k in [k for k, v in _sessions.items() if now - v["ts"] > SESSION_TTL]:
            _drop(k)
        for upload_id in [
            key for key, value in _pending_uploads.items()
            if now - value["ts"] > PENDING_UPLOAD_TTL
        ]:
            _pending_uploads.pop(upload_id, None)
        while len(_sessions) >= MAX_SESSIONS:
            _drop(min(_sessions, key=lambda k: _sessions[k]["ts"]))
        _sessions[sid] = {"df": df, "filename": filename, "ts": now}
    response = {
        "session_id": sid,
        "filename": filename,
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "column_names": [str(c) for c in df.columns],
        "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
        "preview": json.loads(df.head(5).to_json(orient="records", date_format="iso")),
    }
    if source_names:
        response["source_names"] = source_names
    return response


def _unique_names(cols) -> list[str]:
    seen, out = {}, []
    for i, c in enumerate(cols):
        name = str(c).strip() or f"column_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def get_session(sid: str) -> dict:
    with _lock:
        s = _sessions.get(sid)
        if s:
            s["ts"] = time.time()
    if not s:
        raise HTTPException(404, "Your session expired. Please upload your file again.")
    return s


# ---------------------------------------------------------------- upload / sample
def read_table(raw: bytes, ext: str) -> pd.DataFrame:
    if ext == ".csv":
        try:
            return pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(io.BytesIO(raw), encoding="latin-1")
    return pd.read_excel(io.BytesIO(raw))


async def _read_upload(file: UploadFile) -> tuple[str, pd.DataFrame, int]:
    name = Path(file.filename or "data").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "That file type isn't supported. Please use .csv, .xlsx or .xls.")
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "That file is larger than 10 MB. Please try a smaller file.")
    if not raw:
        raise HTTPException(400, "That file is empty.")
    try:
        df = read_table(raw, ext)
    except (ValueError, OSError, ImportError) as exc:
        log.info("Parse failure: %s", type(exc).__name__)
        raise HTTPException(400, "I couldn't read that file. Please check that it is a valid spreadsheet or CSV.")
    if df.empty or df.shape[1] == 0:
        raise HTTPException(400, "That file has no data rows.")
    df.columns = _unique_names(df.columns)
    return name, df, len(raw)


@app.post("/api/upload")
async def upload(files: list[UploadFile] | None = File(default=None), file: UploadFile | None = File(default=None)):
    selected_files = files or ([file] if file else [])
    if not selected_files:
        raise HTTPException(400, "Select at least one CSV or Excel file.")
    if len(selected_files) > MAX_FILES:
        raise HTTPException(400, f"You can combine up to {MAX_FILES} files at a time.")

    loaded = []
    total_bytes = 0
    for uploaded_file in selected_files:
        name, df, size = await _read_upload(uploaded_file)
        total_bytes += size
        if total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, "The selected files exceed the combined 20 MB upload limit.")
        loaded.append({"name": name, "df": df})

    if len(loaded) == 1:
        return register(loaded[0]["df"], loaded[0]["name"])

    upload_id = uuid.uuid4().hex
    now = time.time()
    with _lock:
        for expired_id in [
            key for key, value in _pending_uploads.items()
            if now - value["ts"] > PENDING_UPLOAD_TTL
        ]:
            _pending_uploads.pop(expired_id, None)
        if len(_pending_uploads) >= 20:
            oldest_id = min(_pending_uploads, key=lambda key: _pending_uploads[key]["ts"])
            _pending_uploads.pop(oldest_id)
        _pending_uploads[upload_id] = {"files": loaded, "ts": now}

    return {
        "needs_join": True,
        "upload_id": upload_id,
        "files": [
            {
                "filename": entry["name"],
                "rows": int(len(entry["df"])),
                "column_names": [str(column) for column in entry["df"].columns],
                "preview": json.loads(entry["df"].head(5).to_json(orient="records", date_format="iso")),
            }
            for entry in loaded
        ],
    }


class JoinSpec(BaseModel):
    left_on: str
    right_on: str


class JoinRequest(BaseModel):
    upload_id: str
    joins: list[JoinSpec]
    how: Literal["left", "inner", "outer"] = "left"


@app.post("/api/join")
def join_files(body: JoinRequest):
    with _lock:
        pending = _pending_uploads.get(body.upload_id)
    if not pending or time.time() - pending["ts"] > PENDING_UPLOAD_TTL:
        raise HTTPException(404, "The uploaded files expired. Please upload them again.")

    files = pending["files"]
    if len(body.joins) != len(files) - 1:
        raise HTTPException(400, "Choose one pair of matching columns for each additional file.")

    merged = files[0]["df"].copy()
    for file_index, (entry, spec) in enumerate(zip(files[1:], body.joins), start=1):
        right = entry["df"]
        if spec.left_on not in merged.columns or spec.right_on not in right.columns:
            raise HTTPException(400, f"Choose valid join columns for {entry['name']}.")
        left_counts = merged[spec.left_on].value_counts(dropna=False)
        right_counts = right[spec.right_on].value_counts(dropna=False)
        common_keys = left_counts.index.intersection(right_counts.index)
        matched_rows = sum(
            int(left_counts.loc[key]) * int(right_counts.loc[key])
            for key in common_keys
        )
        unmatched_left = int(left_counts.sum()) - sum(int(left_counts.loc[key]) for key in common_keys)
        unmatched_right = int(right_counts.sum()) - sum(int(right_counts.loc[key]) for key in common_keys)
        projected_rows = matched_rows
        if body.how in {"left", "outer"}:
            projected_rows += unmatched_left
        if body.how == "outer":
            projected_rows += unmatched_right
        if projected_rows > MAX_JOINED_ROWS:
            raise HTTPException(
                413,
                f"Joining {entry['name']} would exceed the {MAX_JOINED_ROWS:,}-row result limit.",
            )
        try:
            merged = merged.merge(
                right,
                how=body.how,
                left_on=spec.left_on,
                right_on=spec.right_on,
                suffixes=("", f"_file{file_index + 1}"),
                sort=False,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, f"Could not join {entry['name']}: {exc}") from exc
        merged.columns = _unique_names(merged.columns)

    with _lock:
        if _pending_uploads.get(body.upload_id) is not pending:
            raise HTTPException(404, "The uploaded files expired or have already been joined.")
        _pending_uploads.pop(body.upload_id)

    filenames = [entry["name"] for entry in files]
    return register(merged, f"Joined {len(files)} files", filenames)


@app.get("/api/sample")
def sample():
    return register(sample_data.load_sample(), "sample_sales.csv")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def frontend():
    return FileResponse(BASE.parent / "index.html")


@app.get("/app.js", include_in_schema=False)
def frontend_app():
    return FileResponse(BASE.parent / "app.js")


@app.get("/styles.css", include_in_schema=False)
def frontend_styles():
    return FileResponse(BASE.parent / "styles.css")


@app.get("/soft-aurora.js", include_in_schema=False)
def frontend_aurora():
    return FileResponse(BASE.parent / "soft-aurora.js")


# ---------------------------------------------------------------- formatting / comparison
def _indian(n: int) -> str:
    s, neg = str(abs(n)), n < 0
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if neg else "") + s


def fmt(v) -> str:
    if v is None:
        return "no value"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, int):
        return _indian(v)
    if isinstance(v, float):
        if abs(v) < 1:
            return f"{v:.4g}"
        r = round(v, 2)
        if r == int(r):
            return _indian(int(r))
        whole = int(abs(r))
        return ("-" if r < 0 else "") + _indian(whole) + f"{abs(r) - whole:.2f}"[1:]
    return str(v)


def display(norm: dict, label: str = "") -> str:
    if norm["kind"] == "scalar":
        return fmt(norm["value"])
    rows, cols = norm["rows"], norm["columns"]
    if len(cols) == 2 and rows:
        text = "; ".join(f"{fmt(r[0])}: {fmt(r[1])}" for r in rows[:3])
        return text + (" …" if norm["total_rows"] > 3 else "")
    return f"{norm['total_rows']} rows (see the table)"


def same(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


def fallback_suggestions(df: pd.DataFrame) -> list[str]:
    nums = [c for c, t in df.dtypes.items() if pd.api.types.is_numeric_dtype(t)]
    cats = [c for c in df.columns if c not in nums]
    if nums and cats:
        return [f"What is the total {nums[0]} by {cats[0]}?", f"What is the average {nums[0]}?"]
    if nums:
        return [f"What is the total {nums[0]}?", f"What is the highest {nums[0]}?"]
    return ["How many rows are there?", f"How many different values does {df.columns[0]} have?"]


def cannot(reason: str, df: pd.DataFrame, suggestions: list[str] | None = None) -> dict:
    sugg = list(suggestions or [])
    for s in fallback_suggestions(df):
        if len(sugg) >= 2:
            break
        if s not in sugg:
            sugg.append(s)
    return {"status": "cannot_prove", "answer": None, "answer_text": "", "code": "", "evidence": [],
            "evidence_total_rows": 0, "runs": [], "reason": reason, "suggestions": sugg[:2]}


# ---------------------------------------------------------------- /api/ask
class AskBody(BaseModel):
    session_id: str
    question: str
    double_check: bool = True


@app.post("/api/ask")
def ask(body: AskBody):
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Please type a question first.")
    if len(question) > 1000:
        raise HTTPException(400, "That question is too long. Please keep it under 1000 characters.")
    sess = get_session(body.session_id)
    df: pd.DataFrame = sess["df"]
    pkl = SESSION_DIR / f"{body.session_id}.pkl"
    if not pkl.exists():
        df.to_pickle(pkl)

    try:
        return analyse(df, pkl, question, body.double_check)
    except llm.LLMError as exc:
        raise HTTPException(exc.status, exc.user_message)


def analyse(df: pd.DataFrame, pkl: Path, question: str, double_check: bool) -> dict:
    feedback, last_error, suggestions = None, "", []
    for attempt in range(2):
        plan = llm.plan(df, question, feedback)
        if not plan["can_answer"]:
            return cannot(plan["reason"] or "Your data can't answer this question.", df, plan["suggestions"])
        suggestions = plan["suggestions"]
        code = plan["code"]
        try:
            validate_code(code)
        except CodeRejected as exc:
            feedback, last_error = f"Code rejected: {exc}", str(exc)
            log.info("Rejected code on attempt %s: %s", attempt + 1, exc)
            continue

        jobs = 2 if double_check else 1
        with ThreadPoolExecutor(max_workers=2) as pool:  # separate fresh subprocess per run
            runs = list(pool.map(lambda _: run_code(code, pkl), range(jobs)))

        failed = next((r for r in runs if not r.get("ok")), None)
        if failed:
            feedback, last_error = f"Runtime error: {failed.get('error')}", failed.get("error", "")
            if failed.get("timeout"):
                break
            continue

        norm = [r["result"] for r in runs]
        second_code = None
        if double_check and os.getenv("INDEPENDENT_SECOND_RUN", "false").lower() == "true":
            try:
                p2 = llm.plan(df, question, independent=True)
                if p2["can_answer"]:
                    validate_code(p2["code"])
                    r3 = run_code(p2["code"], pkl)
                    if r3.get("ok"):
                        norm[1], second_code = r3["result"], p2["code"]
                    else:
                        return cannot("The independent check could not be completed.", df, suggestions)
            except (CodeRejected, llm.LLMError):
                return cannot("The independent check could not be completed.", df, suggestions)

        if double_check and not same(norm[0], norm[1]):
            return cannot("The two runs did not match", df, suggestions)

        label = plan["label"] or "Answer"
        answer = norm[0]
        answer_text = f"{label}: {display(answer)}"
        ev = runs[0]["evidence"]
        evidence = [dict(zip(ev["columns"], row)) for row in ev["rows"]]
        resp = {
            "status": "verified" if double_check else "answered",
            "answer": answer,
            "answer_text": answer_text,
            "code": code,
            "evidence": evidence,
            "evidence_columns": ev["columns"],
            "evidence_total_rows": ev["total_rows"],
            "runs": [{"run": i + 1, "result": n, "display": display(n)} for i, n in enumerate(norm)],
            "reason": "",
        }
        if second_code:
            resp["code_second"] = second_code
        return resp

    return cannot(f"I couldn't run a reliable calculation for this question ({last_error}).", df, suggestions)
