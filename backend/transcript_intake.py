from dataclasses import dataclass
import re
from typing import Protocol


YOUTUBE_VIDEO_ID_PATTERN = re.compile(
    r"(?:v=|youtu\.be/|shorts/|embed/)([a-zA-Z0-9_-]{11})"
)
YOUTUBE_HOST_PATTERN = re.compile(r"(?:youtube\.com|youtu\.be)", re.IGNORECASE)


class YouTubeTranscriptAdapter(Protocol):
    def fetch(self, video_id: str) -> str:
        pass


class TranscriptIntakeError(ValueError):
    pass


class TranscriptFetchError(RuntimeError):
    pass


class TranscriptDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranscriptResult:
    transcript: str
    source_type: str
    video_id: str | None = None


class YouTubeTranscriptApiAdapter:
    def fetch(self, video_id: str) -> str:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as exc:
            raise TranscriptDependencyError(
                "youtube-transcript-api is not installed in this Python environment"
            ) from exc

        try:
            fetched = _fetch_youtube_transcript(YouTubeTranscriptApi, video_id)
        except TranscriptDependencyError:
            raise
        except Exception as exc:
            raise TranscriptFetchError(
                "Could not fetch YouTube transcript. This video may not have a public transcript, or YouTube may have blocked the request."
            ) from exc

        return " ".join(_entry_text(entry) for entry in fetched)


@dataclass
class TranscriptIntake:
    youtube_adapter: YouTubeTranscriptAdapter

    def resolve(self, source: str) -> TranscriptResult:
        text = source.strip()
        if not text:
            raise TranscriptIntakeError("Transcript or URL is required")

        video_id = extract_youtube_video_id(text)
        if video_id:
            return TranscriptResult(
                transcript=self.youtube_adapter.fetch(video_id),
                source_type="youtube",
                video_id=video_id,
            )

        if YOUTUBE_HOST_PATTERN.search(text):
            raise TranscriptIntakeError(
                "Could not find a valid YouTube video ID in that URL"
            )

        return TranscriptResult(transcript=text, source_type="text")


def extract_youtube_video_id(text: str) -> str | None:
    match = YOUTUBE_VIDEO_ID_PATTERN.search(text)
    if not match:
        return None
    return match.group(1)


def _fetch_youtube_transcript(api_class: type, video_id: str) -> object:
    if hasattr(api_class, "get_transcript"):
        return api_class.get_transcript(video_id)
    client = api_class()
    if hasattr(client, "fetch"):
        return client.fetch(video_id)
    raise TranscriptDependencyError(
        "Installed youtube-transcript-api version does not expose a supported transcript fetch interface"
    )


def _entry_text(entry: object) -> str:
    if isinstance(entry, dict):
        return str(entry.get("text", ""))
    return str(getattr(entry, "text", ""))
