"""
llm_router.py
=============
Multi-provider LLM router with automatic failover and rate limit tracking.

Provider priority order (all free tiers):
  1. Groq        — llama-3.3-70b-versatile / llama-3.1-8b-instant
  2. Google       — gemini-1.5-flash / gemini-1.5-flash-8b
  3. OpenRouter   — free models (mistral-7b, llama-3-8b via openai SDK)
  4. Ollama       — local fallback (llama3.2 if installed)

When a provider hits a rate limit (429) or token limit, it is
marked as exhausted for a cooldown window and the next provider
is tried automatically. Recovers automatically after cooldown.

Setup — add to .env:
  GROQ_API_KEY=gsk_...
  GEMINI_API_KEY=AIza...
  OPENROUTER_API_KEY=sk-or-...   (free at openrouter.ai)
  OLLAMA_BASE_URL=http://localhost:11434  (optional local)
"""

import os
import time
import logging
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("llm_router")

# ── Provider cooldown tracking ─────────────────────────────────────────────
# When a provider hits rate limit, it's skipped for COOLDOWN_SECONDS
COOLDOWN_SECONDS = 60   # 1 minute cooldown after rate limit hit

_exhausted: dict[str, float] = {}   # provider_name → timestamp when exhausted

def _is_exhausted(name: str) -> bool:
    if name not in _exhausted:
        return False
    if time.time() - _exhausted[name] > COOLDOWN_SECONDS:
        del _exhausted[name]   # cooldown expired, provider recovered
        logger.info(f"[LLM Router] {name} cooldown expired — back in rotation")
        return False
    return True

def _mark_exhausted(name: str):
    _exhausted[name] = time.time()
    logger.warning(f"[LLM Router] {name} marked exhausted — cooling down {COOLDOWN_SECONDS}s")

def _is_rate_limit_error(error: Exception) -> bool:
    msg = str(error).lower()
    return any(k in msg for k in [
        "rate limit", "rate_limit", "429", "too many requests",
        "quota", "resource exhausted", "tokens per", "requests per"
    ])

# ══════════════════════════════════════════════════════════════
# PROVIDER 1: GROQ
# ══════════════════════════════════════════════════════════════
class GroqProvider:
    NAME = "groq"
    MODELS = {
        "smart": "llama-3.3-70b-versatile",
        "fast":  "llama-3.1-8b-instant",
    }
    # Free tier limits (per minute):
    # llama-3.3-70b: 6,000 TPM, 30 RPM
    # llama-3.1-8b:  30,000 TPM, 30 RPM

    def __init__(self):
        from groq import Groq, RateLimitError
        self._RateLimitError = RateLimitError
        key = os.getenv("GROQ_API_KEY")
        self.available = bool(key)
        if self.available:
            self.client = Groq(api_key=key)
            logger.info("[LLM Router] Groq provider initialised")

    def call(self, system: str, user: str, history: list,
             max_tokens: int, mode: str) -> str:
        model = self.MODELS.get(mode, self.MODELS["smart"])
        msgs  = self._build_messages(system, user, history)
        resp  = self.client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            temperature=0.1, messages=msgs
        )
        return resp.choices[0].message.content.strip()

    def _build_messages(self, system, user, history):
        msgs = [{"role": "system", "content": system}]
        if history:
            msgs.extend(history[-16:])
        msgs.append({"role": "user", "content": user})
        return msgs

    def is_rate_limit(self, e):
        return isinstance(e, self._RateLimitError) or _is_rate_limit_error(e)


# ══════════════════════════════════════════════════════════════
# PROVIDER 2: GOOGLE GEMINI
# ══════════════════════════════════════════════════════════════
class GeminiProvider:
    NAME = "gemini"
    MODELS = {
        "smart": "gemini-1.5-flash",        # free: 15 RPM, 1M TPD
        "fast":  "gemini-1.5-flash-8b",     # free: 15 RPM, 1M TPD
    }

    def __init__(self):
        key = os.getenv("GEMINI_API_KEY")
        self.available = bool(key)
        if self.available:
            try:
                import google.generativeai as genai
                genai.configure(api_key=key)
                self._genai = genai
                logger.info("[LLM Router] Gemini provider initialised")
            except ImportError:
                self.available = False
                logger.warning("[LLM Router] google-generativeai not installed — run: pip install google-generativeai")

    def call(self, system: str, user: str, history: list,
             max_tokens: int, mode: str) -> str:
        model_name = self.MODELS.get(mode, self.MODELS["smart"])
        model = self._genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system,
            generation_config={"max_output_tokens": max_tokens, "temperature": 0.1}
        )
        # Build Gemini-format history
        chat_history = []
        for msg in (history or [])[-16:]:
            role = "user" if msg["role"] == "user" else "model"
            chat_history.append({"role": role, "parts": [msg["content"]]})

        chat = model.start_chat(history=chat_history)
        resp = chat.send_message(user)
        return resp.text.strip()

    def is_rate_limit(self, e):
        return _is_rate_limit_error(e)


# ══════════════════════════════════════════════════════════════
# PROVIDER 3: OPENROUTER (free models via OpenAI SDK)
# ══════════════════════════════════════════════════════════════
class OpenRouterProvider:
    NAME = "openrouter"
    MODELS = {
        # Free models on openrouter.ai (no cost, generous limits)
        "smart": "meta-llama/llama-3.3-70b-instruct:free",
        "fast":  "meta-llama/llama-3.1-8b-instruct:free",
    }

    def __init__(self):
        key = os.getenv("OPENROUTER_API_KEY")
        self.available = bool(key)
        if self.available:
            try:
                from openai import OpenAI
                self.client = OpenAI(
                    api_key=key,
                    base_url="https://openrouter.ai/api/v1",
                    default_headers={
                        "HTTP-Referer": "https://tata-steel-chatbot.local",
                        "X-Title": "Tata Steel Ops Chatbot"
                    }
                )
                logger.info("[LLM Router] OpenRouter provider initialised")
            except ImportError:
                self.available = False
                logger.warning("[LLM Router] openai package not installed")

    def call(self, system: str, user: str, history: list,
             max_tokens: int, mode: str) -> str:
        model = self.MODELS.get(mode, self.MODELS["smart"])
        msgs  = [{"role": "system", "content": system}]
        if history:
            msgs.extend(history[-16:])
        msgs.append({"role": "user", "content": user})

        resp = self.client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            temperature=0.1, messages=msgs
        )
        return resp.choices[0].message.content.strip()

    def is_rate_limit(self, e):
        return _is_rate_limit_error(e)


# ══════════════════════════════════════════════════════════════
# PROVIDER 4: OLLAMA (local, completely free, no limits)
# ══════════════════════════════════════════════════════════════
class OllamaProvider:
    NAME = "ollama"
    MODELS = {
        "smart": "llama3.2",    # install with: ollama pull llama3.2
        "fast":  "llama3.2",
    }

    def __init__(self):
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.base_url = base_url
        # Check if Ollama is running
        try:
            import urllib.request
            urllib.request.urlopen(f"{base_url}/api/tags", timeout=2)
            from openai import OpenAI
            self.client = OpenAI(
                api_key="ollama",
                base_url=f"{base_url}/v1"
            )
            self.available = True
            logger.info(f"[LLM Router] Ollama provider initialised at {base_url}")
        except Exception:
            self.available = False
            logger.info("[LLM Router] Ollama not running — skipping local provider")

    def call(self, system: str, user: str, history: list,
             max_tokens: int, mode: str) -> str:
        model = self.MODELS.get(mode, self.MODELS["smart"])
        msgs  = [{"role": "system", "content": system}]
        if history:
            msgs.extend(history[-16:])
        msgs.append({"role": "user", "content": user})

        resp = self.client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            temperature=0.1, messages=msgs
        )
        return resp.choices[0].message.content.strip()

    def is_rate_limit(self, e):
        return False   # local — never rate limited


# ══════════════════════════════════════════════════════════════
# ROUTER — tries providers in priority order
# ══════════════════════════════════════════════════════════════
class LLMRouter:
    """
    Tries each provider in priority order.
    On rate limit → marks provider exhausted, tries next.
    On cooldown expiry → provider automatically re-enters rotation.
    """

    def __init__(self):
        # Priority order: fastest/best first, local last
        self.providers = [
            GroqProvider(),
            GeminiProvider(),
            OpenRouterProvider(),
            OllamaProvider(),
        ]
        # Filter to only providers that have API keys configured
        self.available = [p for p in self.providers if p.available]

        if not self.available:
            raise RuntimeError(
                "No LLM providers configured. "
                "Add at least one of: GROQ_API_KEY, GEMINI_API_KEY, "
                "OPENROUTER_API_KEY to your .env file, or run Ollama locally."
            )

        names = [p.NAME for p in self.available]
        logger.info(f"[LLM Router] Active providers: {names}")

    def call(self, system: str, user: str,
             max_tokens: int = 800,
             mode: str = "smart",
             history: list = None) -> str:
        """
        Call LLM with automatic provider rotation.
        mode: "smart" (70B, reasoning tasks) or "fast" (8B, classification)
        """
        history = history or []
        errors  = []

        for provider in self.available:
            if _is_exhausted(provider.NAME):
                logger.info(f"[LLM Router] Skipping {provider.NAME} — in cooldown")
                continue

            try:
                logger.info(f"[LLM Router] Trying {provider.NAME} ({mode})")
                result = provider.call(system, user, history, max_tokens, mode)
                logger.info(f"[LLM Router] ✓ {provider.NAME} succeeded")
                return result

            except Exception as e:
                if provider.is_rate_limit(e):
                    _mark_exhausted(provider.NAME)
                    errors.append(f"{provider.NAME}: rate limited")
                    logger.warning(f"[LLM Router] {provider.NAME} rate limited — trying next")
                    continue
                else:
                    # Non-rate-limit error (bad request, auth etc) — log and try next
                    errors.append(f"{provider.NAME}: {str(e)[:80]}")
                    logger.error(f"[LLM Router] {provider.NAME} error: {e}")
                    continue

        # All providers failed
        raise RuntimeError(
            f"All LLM providers failed or are rate limited. "
            f"Errors: {' | '.join(errors)}. "
            f"Providers will recover in {COOLDOWN_SECONDS}s."
        )

    def status(self) -> dict:
        """Return current status of all providers for the /health endpoint."""
        result = {}
        for p in self.providers:
            if not p.available:
                result[p.NAME] = "not_configured"
            elif _is_exhausted(p.NAME):
                remaining = COOLDOWN_SECONDS - (time.time() - _exhausted[p.NAME])
                result[p.NAME] = f"cooling_down ({int(remaining)}s remaining)"
            else:
                result[p.NAME] = "active"
        return result


# ── Singleton instance ─────────────────────────────────────────────────────
router = LLMRouter()
