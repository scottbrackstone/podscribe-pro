from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/app")
def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
