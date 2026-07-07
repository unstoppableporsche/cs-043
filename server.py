import json
import hashlib
import hmac
import importlib.util
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


DB_PATH = Path("imdb_movies.db")
STATIC_DIR = Path("static")
MAX_ROWS = 100
DEFAULT_MODEL = "gpt-4.1-mini"
SESSION_DAYS = 1


def load_local_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value


load_local_env()

app = FastAPI(title="IMDb Chat With Your Data")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


SCHEMA_DESCRIPTION = """
Tables:

movies(
  tconst TEXT primary key,
  primary_title TEXT,
  original_title TEXT,
  start_year INTEGER,
  runtime_minutes INTEGER,
  genres TEXT comma-separated,
  average_rating REAL,
  num_votes INTEGER
)

movie_genres(
  tconst TEXT references movies.tconst,
  genre TEXT
)
"""

SQL_SYSTEM_PROMPT = (
    "Generate one SQLite SELECT query for the user's question. "
    "Use only the provided schema. Return JSON with keys sql and confidence. "
    "Never use INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA, or multiple statements.\n"
    f"{SCHEMA_DESCRIPTION}"
)


SAMPLE_QUESTIONS = [
    "What are the top 10 highest rated movies with at least 100000 votes?",
    "Which genres have the highest average rating?",
    "Show the number of movies released each year since 2010.",
    "What are the most common genres?",
    "Which decade has the highest average movie rating?",
    "Show top action movies after 2015.",
    "What are the longest movies with at least 50000 votes?",
    "How many movies are in the database?",
    "Which year had the most highly rated movies?",
    "Show average runtime by genre.",
]

SENSITIVE_PROMPT_PATTERNS = [
    ("Social Security number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("Social Security number", re.compile(r"\bssn\b|\bsocial security\b", re.IGNORECASE)),
    ("OpenAI/API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("credit card number", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("phone number", re.compile(r"\b(?:\+?1[ -.]?)?\(?\d{3}\)?[ -.]\d{3}[ -.]\d{4}\b")),
]

API_DOCS = [
    {
        "method": "GET",
        "path": "/",
        "purpose": "Serves the frontend web app.",
        "request": "No request body.",
        "response": "HTML page.",
    },
    {
        "method": "GET",
        "path": "/api/status",
        "purpose": "Shows whether the app is using OpenAI or demo-rule fallback mode.",
        "request": "No request body.",
        "response": "database, llm_enabled, model, fallback.",
    },
    {
        "method": "GET",
        "path": "/api/schema",
        "purpose": "Returns the SQLite tables and columns so the UI can show the data model.",
        "request": "No request body.",
        "response": "schema text plus table column metadata.",
    },
    {
        "method": "GET",
        "path": "/api/table-preview",
        "purpose": "Returns row counts and preview rows for the SQL tables.",
        "request": "Optional table name and row limit query parameters.",
        "response": "Preview rows for movies and movie_genres, or one selected table.",
    },
    {
        "method": "GET",
        "path": "/api/sample-questions",
        "purpose": "Returns the prepared demo questions.",
        "request": "No request body.",
        "response": "List of natural-language questions.",
    },
    {
        "method": "POST",
        "path": "/api/register",
        "purpose": "Creates a local demo user with a unique username and hashed password.",
        "request": '{ "username": "demo_user", "password": "password123" }',
        "response": "Created user id and username.",
    },
    {
        "method": "POST",
        "path": "/api/login",
        "purpose": "Logs a user in, stores a session cookie, and records the login event.",
        "request": '{ "username": "demo_user", "password": "password123" }',
        "response": "Logged-in username and session expiration.",
    },
    {
        "method": "GET",
        "path": "/api/login-events",
        "purpose": "Returns recent successful logins for the audit table.",
        "request": "No request body.",
        "response": "Recent login event rows.",
    },
    {
        "method": "GET",
        "path": "/api/chat-audit",
        "purpose": "Returns recent question-to-SQL audit rows for chat memory.",
        "request": "No request body.",
        "response": "Recent chat audit rows for the logged-in user.",
    },
    {
        "method": "POST",
        "path": "/api/ask",
        "purpose": "Converts a user question into SQL, runs it safely, and returns an answer.",
        "request": '{ "question": "Which genres have the highest average rating?" }',
        "response": "answer, generated SQL, result rows, confidence, source.",
    },
]


class QuestionRequest(BaseModel):
    question: str


class LoginRequest(BaseModel):
    username: str
    password: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(dt: datetime | None = None) -> str:
    return (dt or utc_now()).isoformat()


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_credentials(username: str, password: str) -> str:
    normalized = normalize_username(username)
    if not re.fullmatch(r"[a-z0-9_.-]{3,32}", normalized):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-32 characters and use only letters, numbers, dots, dashes, or underscores.",
        )
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    return normalized


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt, expected = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hash_password(password, salt).split("$", 2)[2]
    return hmac.compare_digest(candidate, expected)


def ensure_auth_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS login_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            logged_in_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS chat_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            question TEXT NOT NULL,
            generated_sql TEXT,
            answer TEXT,
            source TEXT,
            confidence REAL,
            row_count INTEGER,
            success INTEGER NOT NULL,
            error_message TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_login_events_user ON login_events(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
        CREATE INDEX IF NOT EXISTS idx_chat_audit_user ON chat_audit(user_id);
        """
    )
    conn.commit()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    expires_at = utc_now() + timedelta(days=SESSION_DAYS)
    conn.execute(
        """
        INSERT INTO sessions (user_id, token_hash, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, token_hash(token), utc_iso(), utc_iso(expires_at)),
    )
    conn.commit()
    return token, utc_iso(expires_at)


def get_current_user(session_token: str | None = Cookie(default=None)) -> dict[str, Any]:
    if not session_token:
        raise HTTPException(status_code=401, detail="Please log in first.")

    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT u.user_id, u.username, u.created_at, s.expires_at
            FROM sessions s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash(session_token),),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Session is invalid. Please log in again.")

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at <= utc_now():
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(session_token),))
            conn.commit()
            raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

        return dict(row)
    finally:
        conn.close()


def fallback_unavailable_error(reason: str | None = None) -> HTTPException:
    message = (
        "AI mode could not answer this question, and it does not match one of the supported demo queries. "
        "Try one of the suggested IMDb movie questions."
    )
    if reason:
        message = f"{message} Last failure: {reason}"

    return HTTPException(
        status_code=422,
        detail={
            "message": message,
            "suggestions": SAMPLE_QUESTIONS[:5],
        },
    )


def detect_sensitive_prompt(text: str) -> str | None:
    for label, pattern in SENSITIVE_PROMPT_PATTERNS:
        if pattern.search(text):
            return label
    return None


def validate_question_safety(question: str) -> None:
    if not question.strip():
        raise HTTPException(status_code=422, detail="Question cannot be empty.")

    sensitive_type = detect_sensitive_prompt(question)
    if sensitive_type:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Security check blocked this prompt because it appears to contain a {sensitive_type}. "
                "Do not enter personal secrets, credentials, or private identifiers. Ask only about the IMDb movie dataset."
            ),
        )


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=400,
            detail="Database not found. Run `python seed_db.py` first.",
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_auth_schema(conn)
    return conn


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def generate_fallback_sql(question: str) -> tuple[str, float]:
    q = normalize(question)

    if "how many" in q or "count" in q:
        return "SELECT COUNT(*) AS movie_count FROM movies;", 0.98

    if "top" in q and ("rated" in q or "rating" in q):
        votes = 100000 if "100000" in q or "100 000" in q else 50000
        return f"""
            SELECT primary_title, start_year, genres, average_rating, num_votes
            FROM movies
            WHERE num_votes >= {votes}
            ORDER BY average_rating DESC, num_votes DESC
            LIMIT 10;
        """, 0.94

    if "genre" in q and ("highest average rating" in q or "average rating" in q):
        return """
            SELECT g.genre, ROUND(AVG(m.average_rating), 2) AS avg_rating, COUNT(*) AS movie_count
            FROM movie_genres g
            JOIN movies m ON m.tconst = g.tconst
            GROUP BY g.genre
            HAVING COUNT(*) >= 1
            ORDER BY avg_rating DESC, movie_count DESC
            LIMIT 10;
        """, 0.92

    if "released each year" in q or ("movies" in q and "year" in q and "since" in q):
        year_match = re.search(r"(20\d{2}|19\d{2})", q)
        start_year = year_match.group(1) if year_match else "2010"
        return f"""
            SELECT start_year, COUNT(*) AS movie_count
            FROM movies
            WHERE start_year >= {start_year}
            GROUP BY start_year
            ORDER BY start_year;
        """, 0.91

    if "common genres" in q or "popular genres" in q:
        return """
            SELECT genre, COUNT(*) AS movie_count
            FROM movie_genres
            GROUP BY genre
            ORDER BY movie_count DESC
            LIMIT 10;
        """, 0.95

    if "decade" in q:
        return """
            SELECT (start_year / 10) * 10 AS decade,
                   ROUND(AVG(average_rating), 2) AS avg_rating,
                   COUNT(*) AS movie_count
            FROM movies
            GROUP BY decade
            HAVING COUNT(*) >= 1
            ORDER BY avg_rating DESC
            LIMIT 10;
        """, 0.9

    if "action" in q:
        year_match = re.search(r"(20\d{2}|19\d{2})", q)
        start_year = year_match.group(1) if year_match else "2015"
        return f"""
            SELECT m.primary_title, m.start_year, m.average_rating, m.num_votes
            FROM movies m
            JOIN movie_genres g ON g.tconst = m.tconst
            WHERE g.genre = 'Action' AND m.start_year > {start_year}
            ORDER BY m.average_rating DESC, m.num_votes DESC
            LIMIT 10;
        """, 0.89

    if "longest" in q or "runtime" in q and "movie" in q:
        return """
            SELECT primary_title, start_year, runtime_minutes, average_rating, num_votes
            FROM movies
            WHERE runtime_minutes IS NOT NULL AND num_votes >= 50000
            ORDER BY runtime_minutes DESC
            LIMIT 10;
        """, 0.9

    if "highly rated" in q and "year" in q:
        return """
            SELECT start_year, COUNT(*) AS highly_rated_movies
            FROM movies
            WHERE average_rating >= 8.0 AND num_votes >= 10000
            GROUP BY start_year
            ORDER BY highly_rated_movies DESC, start_year DESC
            LIMIT 10;
        """, 0.88

    if "average runtime by genre" in q or ("runtime" in q and "genre" in q):
        return """
            SELECT g.genre, ROUND(AVG(m.runtime_minutes), 1) AS avg_runtime_minutes, COUNT(*) AS movie_count
            FROM movie_genres g
            JOIN movies m ON m.tconst = g.tconst
            WHERE m.runtime_minutes IS NOT NULL
            GROUP BY g.genre
            HAVING COUNT(*) >= 1
            ORDER BY avg_runtime_minutes DESC
            LIMIT 10;
        """, 0.9

    raise fallback_unavailable_error()


def generate_openai_sql(question: str) -> tuple[str, float] | None:
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            temperature=0,
            messages=[
                {"role": "system", "content": SQL_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        )
        content = response.choices[0].message.content or ""
        return parse_sql_json(content)
    except Exception:
        return None


def parse_sql_json(content: str) -> tuple[str, float]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    parsed = json.loads(cleaned)
    return parsed["sql"], float(parsed.get("confidence", 0.75))


def configured_litellm_models() -> list[str]:
    raw_models = os.getenv("LITELLM_MODELS", "").strip()
    if raw_models:
        return [model.strip() for model in raw_models.split(",") if model.strip()]

    if os.getenv("OPENAI_API_KEY"):
        return [f"openai/{os.getenv('OPENAI_MODEL', DEFAULT_MODEL)}"]

    return []


def litellm_available() -> bool:
    return importlib.util.find_spec("litellm") is not None


def generate_litellm_sql(question: str) -> tuple[str, float, str] | None:
    load_local_env()
    models = configured_litellm_models()
    if not models:
        return None

    try:
        from litellm import completion
    except Exception:
        return None

    for model in models:
        try:
            response = completion(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": SQL_SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
            )
            content = response.choices[0].message.content or ""
            sql, confidence = parse_sql_json(content)
            return sql, confidence, f"litellm:{model}"
        except Exception:
            continue

    return None


def validate_sql(sql: str) -> str:
    cleaned = sql.strip().rstrip(";")
    lowered = cleaned.lower()
    forbidden = ["insert ", "update ", "delete ", "drop ", "alter ", "pragma ", "attach ", "detach "]
    if not lowered.startswith("select") or any(word in lowered for word in forbidden):
        raise HTTPException(status_code=400, detail="Only safe SELECT queries are allowed.")
    if ";" in cleaned:
        raise HTTPException(status_code=400, detail="Only one SQL statement is allowed.")
    if " limit " not in lowered:
        cleaned = f"{cleaned} LIMIT {MAX_ROWS}"
    return cleaned + ";"


def run_query(sql: str) -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = conn.execute(sql).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as exc:
        raise HTTPException(status_code=400, detail=f"SQL error: {exc}") from exc
    finally:
        conn.close()


def summarize(question: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No matching rows were found."
    if len(rows) == 1 and len(rows[0]) == 1:
        key, value = next(iter(rows[0].items()))
        return f"{key.replace('_', ' ').title()}: {value}."
    first = rows[0]
    if "primary_title" in first:
        details = []
        if "start_year" in first:
            details.append(str(first["start_year"]))
        if "average_rating" in first:
            details.append(f"rating {first['average_rating']}")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"Top result: {first['primary_title']}{suffix}. Showing {len(rows)} rows."
    label_key = next(iter(first.keys()))
    value_keys = [key for key in first.keys() if key != label_key]
    if value_keys:
        value_key = value_keys[0]
        return f"Top result: {first[label_key]} with {first[value_key]} {value_key.replace('_', ' ')}. Showing {len(rows)} rows."
    return f"Found {len(rows)} result rows for: {question}"


def execute_sql_candidate(question: str, sql: str, confidence: float, source: str) -> dict[str, Any]:
    safe_sql = validate_sql(sql)
    rows = run_query(safe_sql)
    return {
        "question": question,
        "answer": summarize(question, rows),
        "sql": safe_sql,
        "rows": rows,
        "confidence": confidence,
        "source": source,
    }


def record_chat_audit(
    user: dict[str, Any],
    question: str,
    success: bool,
    generated_sql: str | None = None,
    answer: str | None = None,
    source: str | None = None,
    confidence: float | None = None,
    row_count: int | None = None,
    error_message: str | None = None,
) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO chat_audit (
                user_id, username, question, generated_sql, answer, source,
                confidence, row_count, success, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["user_id"],
                user["username"],
                question,
                generated_sql,
                answer,
                source,
                confidence,
                row_count,
                1 if success else 0,
                error_message,
                utc_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def answer_with_graceful_fallback(question: str) -> dict[str, Any]:
    last_failure = None
    router_result = generate_litellm_sql(question)

    if router_result:
        sql, confidence, source = router_result
        try:
            return execute_sql_candidate(question, sql, confidence, source)
        except HTTPException as exc:
            last_failure = str(exc.detail)

    llm_result = generate_openai_sql(question)

    if llm_result:
        sql, confidence = llm_result
        try:
            return execute_sql_candidate(question, sql, confidence, "openai")
        except HTTPException as exc:
            last_failure = str(exc.detail)

    try:
        sql, confidence = generate_fallback_sql(question)
        result = execute_sql_candidate(question, sql, confidence, "demo-rule")
        if last_failure:
            result["fallback_reason"] = last_failure
        return result
    except HTTPException as exc:
        if isinstance(exc.detail, dict):
            raise exc
        raise fallback_unavailable_error(last_failure or str(exc.detail)) from exc


@app.get("/")
def index():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/schema")
def schema():
    conn = connect()
    try:
        tables = {}
        for table in ["movies", "movie_genres"]:
            columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
            tables[table] = [dict(column) for column in columns]
        return {"schema": SCHEMA_DESCRIPTION, "tables": tables}
    finally:
        conn.close()


@app.get("/api/table-preview")
def table_preview(
    table: str | None = Query(default=None, pattern="^(movies|movie_genres)$"),
    limit: int = Query(default=8, ge=1, le=25),
):
    conn = connect()
    try:
        tables = [table] if table else ["movies", "movie_genres"]
        previews = {}
        for table_name in tables:
            count = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()["count"]
            rows = conn.execute(f"SELECT * FROM {table_name} LIMIT ?", (limit,)).fetchall()
            previews[table_name] = {
                "count": count,
                "rows": [dict(row) for row in rows],
            }
        return {"tables": previews}
    finally:
        conn.close()


@app.get("/api/docs")
def api_docs():
    return {"endpoints": API_DOCS}


@app.get("/api/sample-questions")
def sample_questions():
    return {"questions": SAMPLE_QUESTIONS}


@app.post("/api/register")
def register(request: LoginRequest):
    username = validate_credentials(request.username, request.password)
    conn = connect()
    try:
        try:
            cursor = conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (username, hash_password(request.password), utc_iso()),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="That username is already taken.") from exc

        return {"user_id": cursor.lastrowid, "username": username}
    finally:
        conn.close()


@app.post("/api/login")
def login(request: LoginRequest, response: Response):
    username = normalize_username(request.username)
    conn = connect()
    try:
        user = conn.execute(
            "SELECT user_id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not user or not verify_password(request.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password.")

        conn.execute(
            """
            INSERT INTO login_events (user_id, username, logged_in_at)
            VALUES (?, ?, ?)
            """,
            (user["user_id"], user["username"], utc_iso()),
        )
        token, expires_at = create_session(conn, user["user_id"])
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=SESSION_DAYS * 24 * 60 * 60,
        )
        return {"username": user["username"], "expires_at": expires_at}
    finally:
        conn.close()


@app.post("/api/logout")
def logout(response: Response, session_token: str | None = Cookie(default=None)):
    if session_token:
        conn = connect()
        try:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(session_token),))
            conn.commit()
        finally:
            conn.close()
    response.delete_cookie("session_token")
    return {"ok": True}


@app.get("/api/me")
def me(user: dict[str, Any] = Depends(get_current_user)):
    return {"user_id": user["user_id"], "username": user["username"]}


@app.get("/api/login-events")
def login_events(limit: int = Query(default=20, ge=1, le=100)):
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT event_id, user_id, username, logged_in_at
            FROM login_events
            ORDER BY event_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return {"events": [dict(row) for row in rows]}
    finally:
        conn.close()


@app.get("/api/chat-audit")
def chat_audit(user: dict[str, Any] = Depends(get_current_user), limit: int = Query(default=20, ge=1, le=100)):
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT audit_id, username, question, generated_sql, answer, source,
                   confidence, row_count, success, error_message, created_at
            FROM chat_audit
            WHERE user_id = ?
            ORDER BY audit_id DESC
            LIMIT ?
            """,
            (user["user_id"], limit),
        ).fetchall()
        return {"events": [dict(row) for row in rows]}
    finally:
        conn.close()


@app.get("/api/status")
def status():
    load_local_env()
    env_path = Path(".env")
    env_key_in_file = False
    if env_path.exists():
        env_key_in_file = any(
            line.strip().startswith("OPENAI_API_KEY=")
            for line in env_path.read_text(encoding="utf-8").splitlines()
        )
    configured_models = configured_litellm_models()
    return {
        "database": DB_PATH.name,
        "llm_enabled": bool(configured_models or os.getenv("OPENAI_API_KEY")),
        "model": os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        "model_router": "litellm",
        "configured_models": configured_models,
        "litellm_installed": litellm_available(),
        "fallback": "demo-rule",
        "cwd": str(Path.cwd()),
        "env_file_exists": env_path.exists(),
        "env_key_in_file": env_key_in_file,
    }


@app.post("/api/ask")
def ask(request: QuestionRequest, user: dict[str, Any] = Depends(get_current_user)):
    try:
        validate_question_safety(request.question)
        result = answer_with_graceful_fallback(request.question)
        record_chat_audit(
            user=user,
            question=request.question,
            success=True,
            generated_sql=result.get("sql"),
            answer=result.get("answer"),
            source=result.get("source"),
            confidence=result.get("confidence"),
            row_count=len(result.get("rows", [])),
        )
        return result
    except HTTPException as exc:
        record_chat_audit(
            user=user,
            question=request.question,
            success=False,
            error_message=json.dumps(exc.detail) if isinstance(exc.detail, (dict, list)) else str(exc.detail),
        )
        raise exc


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=False)
