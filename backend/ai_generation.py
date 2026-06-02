from dataclasses import dataclass
from typing import Protocol

import requests


SUMMARY_PROMPTS = {
    "concise": """Always respond in English only.

You are an expert podcast summariser. Write a concise summary of this podcast transcript in 3-5 sentences of plain prose.
Focus only on the most important point or argument. No bullet points, no headings, no fluff.
Write it so someone can understand the whole episode in 30 seconds.

Transcript:
{transcript}""",
    "detailed": """Always respond in English only.

You are an expert podcast summariser. Write a detailed summary of this podcast transcript in clear prose paragraphs.
Cover every major topic, argument, and insight discussed. Use headings for each major section.
Write it so someone who never listens to the episode still gets the full picture.

Transcript:
{transcript}""",
    "takeaways": """Always respond in English only.

You are an expert podcast analyst. Extract the most valuable actionable insights and key lessons from this transcript.
Format as a numbered list. Each item should be a specific, useful takeaway - not just a topic mention.
Focus on what the listener should remember, do, or think differently about after this episode.

Transcript:
{transcript}""",
}

WRITER_PROFILE = """The writer is learning to code and is studying a postgraduate certificate in Information Technology online.
They are heavily interested in new tech, AI updates, coding tools, apps, web apps, and trying to build toward a business.
They are shy about posting, do not claim to know everything, and do not want to sound like an expert, guru, or influencer.
They want help finding their voice, sharing honest reactions, and starting conversations with people learning software development and people already in the field."""

APPROACH_PROFILES = {
    "quiet_learner": "Quiet learner: soft, honest, low-pressure, a little vulnerable, and comfortable saying what they are still figuring out.",
    "curious_student": "Curious student: frames the post around a question, a new idea, or something they are trying to understand.",
    "builder_reflection": "Builder reflection: connects the idea to building apps, web apps, AI tools, side projects, or learning by making things.",
    "conversation_starter": "Conversation starter: more outward-facing, invites other learners and developers to share their experience.",
    "braver_opinion": "Braver opinion: shares a real take with confidence, but still avoids sounding like an expert or pretending certainty.",
}

LEGACY_TONE_TO_APPROACH = {
    "casual": "quiet_learner",
    "balanced": "curious_student",
    "pro": "builder_reflection",
}

VALID_PLATFORMS = ("x", "threads", "instagram")

PLATFORM_INSTRUCTIONS = {
    "x": """Write one X post.
Max 280 characters.
No hashtags.
One clear idea from the transcript.
Use first person if it feels natural.
End with a short question only if it fits the approach.""",
    "threads": """Write one Threads post.
Max 500 characters.
Personal but not polished.
Use 1-2 short paragraphs if useful.
One clear thought, then a conversation hook.
Avoid hashtags unless one feels genuinely natural.""",
    "instagram": """Write one Instagram caption.
Use a strong but honest first line.
Use 3-5 short sentences.
Do not sound like a brand.
End with a question that could start a real conversation.
Add 4-6 relevant hashtags at the bottom.""",
}

INSTAGRAM_IMAGE_IDEA_PROMPT = """Always respond in English only.

Suggest one practical Instagram visual idea to accompany this caption.

Writer profile:
{writer_profile}

Posting approach:
{approach_profile}

Rules:
- Return only the image idea.
- Say whether it should be a single image or carousel.
- Make it realistic for someone learning coding and building apps.
- Avoid generic stock-photo ideas.
- Avoid anything that makes the writer look like an expert, guru, or influencer.
- If useful, include simple overlay text.

Caption:
{post}

Transcript context:
{transcript}"""


class TextGenerationAdapter(Protocol):
    def complete(self, prompt: str) -> str:
        pass


class AIGenerationError(RuntimeError):
    pass


class InvalidGenerationRequest(ValueError):
    pass


@dataclass(frozen=True)
class SummaryResult:
    summary: str
    word_count: int
    style: str


@dataclass
class OpenRouterAdapter:
    api_key: str | None
    model: str = "deepseek/deepseek-v4-flash"
    endpoint: str = "https://openrouter.ai/api/v1/chat/completions"
    timeout_seconds: int = 60

    def complete(self, prompt: str) -> str:
        if not self.api_key:
            raise AIGenerationError("OPENROUTER_API_KEY is not configured")

        try:
            response = requests.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            return payload["choices"][0]["message"]["content"]
        except requests.RequestException as exc:
            raise AIGenerationError("OpenRouter request failed") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIGenerationError("OpenRouter response was not understood") from exc


@dataclass
class AIGeneration:
    adapter: TextGenerationAdapter

    def summarize(self, transcript: str, style: str = "concise") -> SummaryResult:
        selected_style = style if style in SUMMARY_PROMPTS else "concise"
        prompt = SUMMARY_PROMPTS[selected_style].format(transcript=transcript)
        return SummaryResult(
            summary=self.adapter.complete(prompt),
            word_count=len(transcript.split()),
            style=selected_style,
        )

    def clipwise(
        self,
        transcript: str,
        platform: str = "all",
        approach: str = "curious_student",
        tone: str | None = None,
    ) -> dict[str, dict[str, str]]:
        selected_approach = normalize_approach(approach, tone)

        if platform == "all":
            platforms = VALID_PLATFORMS
        elif platform in VALID_PLATFORMS:
            platforms = (platform,)
        else:
            raise InvalidGenerationRequest(f"Unsupported ClipWise platform: {platform}")

        return {
            platform_key: self._generate_clip(
                transcript,
                platform_key,
                selected_approach,
            )
            for platform_key in platforms
        }

    def _generate_clip(
        self,
        transcript: str,
        platform: str,
        approach: str,
    ) -> dict[str, str]:
        post = self.adapter.complete(build_clip_prompt(transcript, platform, approach))
        result = {"post": post}

        if platform == "instagram":
            result["image_idea"] = self.adapter.complete(
                INSTAGRAM_IMAGE_IDEA_PROMPT.format(
                    writer_profile=WRITER_PROFILE,
                    approach_profile=APPROACH_PROFILES[approach],
                    post=post,
                    transcript=transcript,
                )
            )

        return result


def normalize_approach(approach: str, tone: str | None = None) -> str:
    if approach in APPROACH_PROFILES:
        return approach
    if tone in LEGACY_TONE_TO_APPROACH:
        return LEGACY_TONE_TO_APPROACH[tone]
    return "curious_student"


def build_clip_prompt(transcript: str, platform: str, approach: str) -> str:
    return f"""Always respond in English only.

You are helping the writer turn a podcast or video transcript into a social media post.

Writer profile:
{WRITER_PROFILE}

Posting approach:
{APPROACH_PROFILES[approach]}

Platform instructions:
{PLATFORM_INSTRUCTIONS[platform]}

Hard rules:
- Return only the post text.
- Do not make the writer sound like an expert, guru, founder influencer, or thought leader.
- Do not overstate certainty.
- Do not use hype language.
- Do not say "as someone who" more than once.
- Pull one specific idea from the transcript instead of summarising everything.
- Make the post useful for finding like-minded learners, software developers, AI builders, or tech-curious people.

Transcript:
{transcript}"""
