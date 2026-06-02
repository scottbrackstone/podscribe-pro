import os
import base64
import hashlib
import hmac
import html
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from pydantic import BaseModel

from ai_generation import (
    AIGeneration,
    AIGenerationError,
    InvalidGenerationRequest,
    OpenRouterAdapter,
)
from transcript_intake import (
    TranscriptDependencyError,
    TranscriptFetchError,
    TranscriptIntake,
    TranscriptIntakeError,
    YouTubeTranscriptApiAdapter,
)

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
APP_PASSWORD = os.getenv("APP_PASSWORD")
SESSION_SECRET = os.getenv("SESSION_SECRET")
SESSION_COOKIE = "podscribe_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
PUBLIC_PATHS = {"/", "/health", "/login", "/logout"}
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
ai_generation = AIGeneration(OpenRouterAdapter(api_key=OPENROUTER_API_KEY))
transcript_intake = TranscriptIntake(YouTubeTranscriptApiAdapter())

app = FastAPI(title="PodScribe Pro", description="AI-powered podcast summarizer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def auth_is_configured() -> bool:
    return bool(APP_PASSWORD and SESSION_SECRET)


def encode_base64_url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def decode_base64_url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_session_payload(payload: str) -> str:
    if not SESSION_SECRET:
        return ""

    signature = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return encode_base64_url(signature)


def create_session_token() -> str:
    now = int(time.time())
    payload = encode_base64_url(
        json.dumps(
            {"iat": now, "exp": now + SESSION_TTL_SECONDS},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return f"{payload}.{sign_session_payload(payload)}"


def is_valid_session_token(token: str | None) -> bool:
    if not token or not auth_is_configured():
        return False

    try:
        payload, signature = token.split(".", 1)
        expected_signature = sign_session_payload(payload)
        if not hmac.compare_digest(signature, expected_signature):
            return False

        session = json.loads(decode_base64_url(payload))
        return int(session.get("exp", 0)) >= int(time.time())
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


def is_authenticated(request: Request) -> bool:
    return is_valid_session_token(request.cookies.get(SESSION_COOKIE))


def safe_next_path(next_path: str | None) -> str:
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return "/app"
    return next_path


def wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def render_login_page(
    *,
    next_path: str = "/app",
    error_message: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    safe_next = html.escape(safe_next_path(next_path), quote=True)
    safe_error = html.escape(error_message, quote=True)
    auth_configured = auth_is_configured()
    config_warning = ""
    disabled = ""

    if not auth_configured:
        config_warning = (
            "<p class=\"error\">APP_PASSWORD and SESSION_SECRET must be configured "
            "before this app can be used.</p>"
        )
        disabled = " disabled"

    error_html = f"<p class=\"error\">{safe_error}</p>" if safe_error else ""
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PodScribe Pro Login</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            min-height: 100vh;
            margin: 0;
            display: grid;
            place-items: center;
            padding: 24px;
            font-family: Arial, sans-serif;
            background: #f3f4f6;
            color: #172033;
        }}
        main {{
            width: min(100%, 380px);
            padding: 28px;
            border: 1px solid #d7dce3;
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 16px 40px rgba(23, 32, 51, 0.10);
        }}
        h1 {{
            margin: 0 0 8px;
            font-size: 1.6rem;
            line-height: 1.2;
        }}
        p {{
            margin: 0 0 20px;
            color: #596274;
            line-height: 1.5;
        }}
        label {{
            display: block;
            margin-bottom: 8px;
            font-size: 0.9rem;
            font-weight: 700;
        }}
        input {{
            width: 100%;
            min-height: 46px;
            padding: 10px 12px;
            border: 1px solid #b8c0cc;
            border-radius: 6px;
            font: inherit;
        }}
        button {{
            width: 100%;
            min-height: 46px;
            margin-top: 16px;
            border: 0;
            border-radius: 6px;
            background: #1f6feb;
            color: #ffffff;
            font: inherit;
            font-weight: 700;
            cursor: pointer;
        }}
        button:disabled {{
            background: #9aa4b2;
            cursor: not-allowed;
        }}
        .error {{
            margin: 0 0 16px;
            color: #b42318;
            font-weight: 700;
        }}
    </style>
</head>
<body>
    <main>
        <h1>PodScribe Pro</h1>
        <p>Enter the private app password to continue.</p>
        {config_warning}
        {error_html}
        <form method="post" action="/login">
            <input type="hidden" name="next" value="{safe_next}">
            <label for="password">Password</label>
            <input id="password" name="password" type="password" autocomplete="current-password" autofocus{disabled}>
            <button type="submit"{disabled}>Unlock</button>
        </form>
    </main>
</body>
</html>"""
    return HTMLResponse(body, status_code=status_code)


@app.middleware("http")
async def require_private_session(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or is_authenticated(request):
        return await call_next(request)

    if request.method == "GET" and wants_html(request):
        return RedirectResponse(url=f"/login?next={quote(path)}", status_code=303)

    return JSONResponse({"detail": "Authentication required"}, status_code=401)


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/app")
def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/login")
def login_page(next: str = "/app"):
    status_code = 200 if auth_is_configured() else 503
    return render_login_page(next_path=next, status_code=status_code)


@app.post("/login")
async def login(request: Request):
    body = (await request.body()).decode("utf-8")
    form = parse_qs(body)
    password = form.get("password", [""])[0]
    next_path = safe_next_path(form.get("next", ["/app"])[0])

    if not auth_is_configured():
        return render_login_page(next_path=next_path, status_code=503)

    if not hmac.compare_digest(password, APP_PASSWORD or ""):
        return render_login_page(
            next_path=next_path,
            error_message="Incorrect password.",
            status_code=401,
        )

    response = RedirectResponse(url=next_path, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


class SummarizeRequest(BaseModel):
    transcript: str
    style: str = "concise"


class TranscriptRequest(BaseModel):
    source: str | None = None
    url: str | None = None


@app.get("/")
def read_root():
    return {"message": "Hello, PodScribe! The API is working."}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/transcript")
def get_transcript(request: TranscriptRequest):
    source = request.source or request.url
    if source is None:
        raise HTTPException(status_code=400, detail="Transcript or URL is required")

    try:
        result = transcript_intake.resolve(source)
    except TranscriptIntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TranscriptDependencyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except TranscriptFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "transcript": result.transcript,
        "source_type": result.source_type,
        "video_id": result.video_id,
    }


@app.post("/summarize")
def summarize(request: SummarizeRequest):
    try:
        result = ai_generation.summarize(request.transcript, request.style)
    except AIGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "summary": result.summary,
        "word_count": result.word_count,
        "style": result.style,
    }


class ClipWiseRequest(BaseModel):
    transcript: str
    platform: str = "all"
    approach: str = "curious_student"
    tone: str | None = None


@app.post("/clipwise")
def clipwise(request: ClipWiseRequest):
    try:
        return ai_generation.clipwise(
            request.transcript,
            platform=request.platform,
            approach=request.approach,
            tone=request.tone,
        )
    except InvalidGenerationRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True, proxy_headers=True)
