# Verifi — Proof-Carrying Data Analyst

Upload one or more CSV/Excel files, select how their columns relate, and ask a
question. Verifi shows the generated pandas code, evidence rows, and repeat-run
check.

## Native development

Requirements: Python 3.10+ and [Ollama](https://ollama.com/).

```sh
OLLAMA_LOAD_TIMEOUT=15m ollama serve
ollama pull qwen2.5:7b
```

In another terminal:

```sh
cd backend
cp .env.example .env
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

From the project root, start the development frontend proxy:

```sh
python dev_server.py
```

Open <http://localhost:5500>. In Codespaces, forward port 5500. The FastAPI
backend also serves the frontend at port 8000. Set `QWEN_MODEL` in
`backend/.env` to a model installed in Ollama. Qwen 2.5 7B needs several GB of
available RAM; a machine with 16 GB RAM is recommended. Its first load can take
several minutes, so Ollama is configured with a 15-minute model-load timeout.
Smaller installed models such as `qwen2.5:0.5b` use less memory but are less
capable.

In VS Code, the **Run Full Project** task starts Ollama and the backend/frontend
together. Open the Command Palette and choose **Tasks: Run Task**.

## Single-host Docker deployment

Docker Compose builds one production web/API service and a private Ollama service.
It downloads the configured model on first start. Qwen 2.5 7B is a 4.7 GB
download and needs substantial host memory. Its first model load may take several
minutes; Compose allows up to 15 minutes for Ollama to load it.

```sh
cp .env.docker.example .env
```

Set `APP_ACCESS_TOKEN` in `.env` to a unique random value of at least 24
characters (for example, generate one with `openssl rand -hex 32`). Then run:

```sh
docker compose up --build -d
docker compose logs -f
```

Open <http://localhost:8000>. Enter the access token into the app when prompted.
To use a smaller Ollama model, set `QWEN_MODEL` in `.env`; Compose downloads it
automatically. Keep Ollama's port private. Do not commit `.env`.

This configuration is for one host and one API worker. Uploaded sessions are
temporary, held in process memory and local scratch files, and expire after two
hours. A restart loses active sessions. Before exposing the service to the
internet, put it behind TLS and configure rate limits, backups, and monitoring.
Before adding replicas, move sessions to shared storage. The sandbox is defense
in depth, not an isolation boundary; do not run untrusted code on a host
containing sensitive resources.

## Multiple-file joins

Select up to five CSV/Excel files (10 MB each, 20 MB total). Choose the matching
columns between the first file and each additional file, then select:

- **Left:** keep all rows from the first file (default)
- **Inner:** keep only rows with a match
- **Outer:** keep unmatched rows from either side

Each additional file joins directly to the first file; this is a star-shaped
join, not a chain where one added file joins through another. Duplicate
non-key column names receive file suffixes. Joins that would produce more than
1,000,000 rows are rejected before constructing the result. The resulting
table is the dataset used for analysis.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/upload` | Upload one `file` or repeated `files`; multiple files return join metadata |
| `POST /api/join` | Join staged files using selected keys and a left/inner/outer strategy |
| `GET /api/sample` | Load the 300-row sample sales dataset |
| `POST /api/ask` | Analyze a question for the active dataset |
| `GET /api/health` | Web/API liveness check (does not prove the model can answer) |

With `APP_ACCESS_TOKEN` set, include `Authorization: Bearer <token>` on API
requests other than the health check. The frontend sends the token entered in
its access-token field. CORS is disabled by default; configure
`CORS_ORIGINS` only if a separate trusted frontend origin is needed.