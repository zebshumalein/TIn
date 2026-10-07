"""Runs inside the isolated subprocess. Reads code from stdin, a pickled DataFrame path from argv.
Prints exactly one marker line with a JSON payload. Never imported by the API process."""
import datetime
import io
import json
import math
import sys

MARKER = "@@PCDA_RESULT@@"
MAX_RESULT_ROWS = 100
MAX_EVIDENCE_ROWS = 20

SAFE_BUILTINS = {}


def _build_builtins():
    import builtins
    names = (
        "abs all any bool dict divmod enumerate filter float int isinstance len list map max min "
        "pow range reversed round set slice sorted str sum tuple zip "
        "Exception ValueError KeyError TypeError IndexError ZeroDivisionError ArithmeticError"
    ).split()
    d = {n: getattr(builtins, n) for n in names}
    d["print"] = lambda *a, **k: None  # swallow prints
    return d


def main():
    real_out = sys.stdout
    payload = {"ok": False, "error": "Unknown error."}
    try:
        import numpy as np
        import pandas as pd

        try:  # best-effort memory cap on POSIX
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
        except Exception:
            pass

        def clean(v):
            if v is None or v is pd.NaT:
                return None
            if isinstance(v, (bool, np.bool_)):
                return bool(v)
            if isinstance(v, (int, np.integer)):
                return int(v)
            if isinstance(v, (float, np.floating)):
                f = float(v)
                return None if (math.isnan(f) or math.isinf(f)) else f
            if isinstance(v, (pd.Timestamp, datetime.datetime, datetime.date)):
                return v.isoformat()
            if isinstance(v, str):
                return v
            return str(v)

        def table(columns, rows, total, limit):
            return {"kind": "table", "columns": [str(c) for c in columns],
                    "rows": [[clean(c) for c in r] for r in rows[:limit]], "total_rows": int(total)}

        def normalize(x):
            if isinstance(x, pd.DataFrame):
                df2 = x
                if not isinstance(df2.index, pd.RangeIndex):
                    try:
                        df2 = df2.reset_index()
                    except Exception:
                        pass
                return table(df2.columns, df2.values.tolist(), len(df2), MAX_RESULT_ROWS)
            if isinstance(x, pd.Series):
                rows = [[k, v] for k, v in x.items()]
                return table([x.index.name or "index", x.name if x.name is not None else "value"],
                             rows, len(rows), MAX_RESULT_ROWS)
            if isinstance(x, np.ndarray):
                x = x.tolist()
            if isinstance(x, (list, tuple, set)):
                rows = [[v] for v in list(x)]
                return table(["value"], rows, len(rows), MAX_RESULT_ROWS)
            if isinstance(x, dict):
                rows = [[k, v] for k, v in x.items()]
                return table(["key", "value"], rows, len(rows), MAX_RESULT_ROWS)
            return {"kind": "scalar", "value": clean(x)}

        code = sys.stdin.read()
        df = pd.read_pickle(sys.argv[1])
        g = {"__builtins__": _build_builtins(), "pd": pd, "np": np, "df": df.copy()}
        compiled = compile(code, "<analysis>", "exec")

        sys.stdout = io.StringIO()
        try:
            exec(compiled, g)
        finally:
            sys.stdout = real_out

        if "result" not in g:
            raise ValueError("The code did not set `result`.")
        result = normalize(g["result"])

        ev = g.get("evidence_df")
        evidence = {"columns": [], "rows": [], "total_rows": 0}
        if isinstance(ev, pd.Series):
            ev = ev.to_frame()
        if isinstance(ev, pd.DataFrame):
            evidence = table(ev.columns, ev.values.tolist(), len(ev), MAX_EVIDENCE_ROWS)
            evidence.pop("kind", None)

        payload = {"ok": True, "result": result, "evidence": evidence}
    except BaseException as exc:  # noqa: BLE001 - report everything back
        sys.stdout = real_out
        payload = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}

    real_out.write("\n" + MARKER + json.dumps(payload) + "\n")
    real_out.flush()


if __name__ == "__main__":
    main()
