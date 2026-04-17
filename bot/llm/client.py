"""
LLM provider abstraction.

Switch providers via .env:
  LLM_PROVIDER=groq          → uses Groq API (free tier, OpenAI-compatible)
  LLM_PROVIDER=anthropic     → uses Anthropic Claude API
  LLM_PROVIDER=ollama        → uses local Ollama (OpenAI-compatible)

Change LLM_API_KEY and LLM_MODEL accordingly.
"""
from dataclasses import dataclass


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

# Default models per provider
DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-haiku-4-5-20251001",
    "ollama": "llama3",
}


@dataclass
class LLMClient:
    """Thin wrapper around LLM providers. Call complete() to get a text response."""

    provider: str  # "groq", "anthropic", "ollama"
    api_key: str
    model: str

    async def complete(self, system: str, user: str) -> str:
        """Send a system + user prompt, return the model's text response."""
        if self.provider == "anthropic":
            return await self._complete_anthropic(system, user)
        return await self._complete_openai_compat(system, user)

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

    async def _complete_openai_compat(self, system: str, user: str) -> str:
        import openai
        base_urls = {
            "groq": GROQ_BASE_URL,
            "ollama": OLLAMA_BASE_URL,
        }
        client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=base_urls.get(self.provider),
        )
        response = await client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content


def build_llm_client(provider: str, api_key: str, model: str = "") -> LLMClient:
    resolved_model = model or DEFAULT_MODELS.get(provider, "")
    if not resolved_model:
        raise ValueError(f"No default model for provider '{provider}'. Set LLM_MODEL in .env")
    return LLMClient(provider=provider, api_key=api_key, model=resolved_model)
