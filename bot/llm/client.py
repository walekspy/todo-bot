"""
LLM provider abstraction.

Switch providers via .env:
  LLM_PROVIDER=groq          → uses Groq API (free tier, OpenAI-compatible)
  LLM_PROVIDER=anthropic     → uses Anthropic Claude API
  LLM_PROVIDER=ollama        → uses local Ollama (OpenAI-compatible)
  LLM_PROVIDER=hermes        → uses Hermes Agent API Server (local, OpenAI-compatible)

Change LLM_API_KEY and LLM_MODEL accordingly.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
HERMES_BASE_URL = "http://127.0.0.1:8642/v1"

# Default models per provider
DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-haiku-4-5-20251001",
    "ollama": "llama3",
    "hermes": "hermes-agent",
}


@dataclass
class LLMClient:
    """Thin wrapper around LLM providers. Call complete() to get a text response."""

    provider: str  # "groq", "anthropic", "ollama", "hermes"
    api_key: str
    model: str
    fallback_key: str = ""  # optional fallback API key (e.g. groq)

    async def complete(self, system: str, user: str) -> str:
        """Send a system + user prompt, return the model's text response."""
        if self.provider == "anthropic":
            return await self._complete_anthropic(system, user)
        if self.provider == "hermes":
            try:
                return await self._complete_hermes(system, user)
            except Exception as e:
                logging.getLogger(__name__).warning("Hermes API down (%s), falling back to groq", e)
                return await self._complete_openai_compat(system, user, fallback=True)
        return await self._complete_openai_compat(system, user)

    async def _complete_hermes(self, system: str, user: str) -> str:
        import openai
        client = openai.AsyncOpenAI(api_key=self.api_key, base_url=HERMES_BASE_URL)
        response = await client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content

    async def _complete_anthropic(self, system: str, user: str) -> str:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    async def _complete_openai_compat(self, system: str, user: str, fallback: bool = False) -> str:
        import openai
        if fallback:
            client = openai.AsyncOpenAI(api_key=self.fallback_key or self.api_key, base_url=GROQ_BASE_URL)
            model = "llama-3.3-70b-versatile"
        else:
            base_urls = {
                "groq": GROQ_BASE_URL,
                "ollama": OLLAMA_BASE_URL,
            }
            client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=base_urls.get(self.provider),
            )
            model = self.model
        response = await client.chat.completions.create(
            model=model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content


def build_llm_client(provider: str, api_key: str, model: str = "", fallback_key: str = "") -> LLMClient:
    resolved_model = model or DEFAULT_MODELS.get(provider, "")
    if not resolved_model:
        raise ValueError(f"No default model for provider '{provider}'. Set LLM_MODEL in .env")
    return LLMClient(provider=provider, api_key=api_key, model=resolved_model, fallback_key=fallback_key)
