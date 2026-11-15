"""
AI Text Generation module with multi-provider fallback (Gemini, Groq, OpenRouter).
Supports configurable models, vision inspection, and brand/tone alignment.
"""

import os
import base64
import requests
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from src.utils import logger, retry_with_backoff


def build_system_prompt(config: Dict[str, Any]) -> str:
    """
    Builds the system instruction prompt based on configuration.
    """
    brand = config.get("brand", {})
    name = brand.get("name", "My Brand")
    niche = brand.get("niche", "Technology and Lifestyle")
    audience = brand.get("target_audience", "General audience")
    language = brand.get("language", "mixed")
    tone = brand.get("tone", "engaging, informative")
    custom_prompt = brand.get("custom_system_prompt", "")

    lang_desc = {
        "bn": "Pure, natural Bengali (Bangla)",
        "en": "Clear, professional English",
        "mixed": "Bengali blended with natural English tech terms (Bangla-English / bilingual style as popular in Bangladesh tech communities)",
    }.get(language, language)

    prompt = (
        f"You are the official social media manager and content creator for '{name}'.\n"
        f"Page Niche: {niche}\n"
        f"Target Audience: {audience}\n"
        f"Tone of Voice: {tone}\n"
        f"Language requirement: {lang_desc}\n\n"
    )

    if custom_prompt:
        prompt += f"Brand Voice Guidelines:\n{custom_prompt}\n\n"

    prompt += (
        "Output ONLY the final post caption text ready to be published on Facebook. "
        "Do not include intro notes, meta labels (e.g. 'Hook:', 'Caption:'), "
        "or markdown wrapping like ```."
    )
    return prompt


def build_user_prompt(
    topic: str,
    config: Dict[str, Any],
    recent_captions: Optional[List[str]] = None,
    image_context: Optional[str] = None,
) -> str:
    """
    Builds the user prompt requesting a social media caption on the topic.
    """
    brand = config.get("brand", {})
    emoji = brand.get("emoji", True)
    hashtags_cfg = brand.get("hashtags", {})
    hashtags_enabled = hashtags_cfg.get("enabled", True)
    hashtag_count = hashtags_cfg.get("count", 5)
    max_length = brand.get("max_caption_length", 600)

    prompt_parts = [
        f"Write an engaging Facebook post for the topic: '{topic}'.",
        f"Target character length: Around {max_length} characters (concise, high readability).",
        "Include an irresistible hook in the first sentence to stop users from scrolling.",
        "Provide genuine value or practical insights in the body.",
        "End with an engaging call-to-action (e.g., question, invitation to share thoughts).",
    ]

    if emoji:
        prompt_parts.append("Use relevant, tastefully placed emojis to enhance readability.")
    else:
        prompt_parts.append("Do NOT use any emojis.")

    if hashtags_enabled:
        prompt_parts.append(f"At the very end of the post, append exactly {hashtag_count} relevant hashtags.")
    else:
        prompt_parts.append("Do NOT include any hashtags.")

    if image_context:
        prompt_parts.append(f"Context from the attached photo: {image_context}. Ensure your caption matches and enhances what is shown.")

    if recent_captions:
        short_snippets = [c.replace("\n", " ")[:80] for c in recent_captions[:5]]
        prompt_parts.append(
            "CRITICAL: Do NOT reuse the same hooks or opening phrasing from our recent posts:\n"
            + "\n".join(f"- {s}..." for s in short_snippets)
        )

    return "\n".join(prompt_parts)


def call_gemini(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
    image_path: Optional[Path] = None,
    timeout: int = 30,
) -> str:
    """
    Direct REST call to Google Gemini generateContent API.
    Supports multimodal input (vision) when image_path is provided.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    parts = []

    # If vision image is provided, encode to base64
    if image_path and image_path.exists():
        try:
            image_bytes = image_path.read_bytes()
            mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
            parts.append({
                "inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(image_bytes).decode("utf-8"),
                }
            })
        except Exception as e:
            logger.warning(f"Could not attach image to Gemini vision request: {e}")

    # Add the text prompt
    combined_prompt = f"{system_prompt}\n\nTask:\n{user_prompt}"
    parts.append({"text": combined_prompt})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1024,
        },
    }

    headers = {"Content-Type": "application/json"}
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API returned status {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        candidate = data["candidates"][0]
        text = candidate["content"]["parts"][0]["text"].strip()
        return text
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response structure: {data}") from e


def call_groq(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
    timeout: int = 30,
) -> str:
    """
    Direct REST call to Groq OpenAI-compatible chat completions API.
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 1024,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Groq API returned status {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Groq response structure: {data}") from e


def call_openrouter(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
    timeout: int = 30,
) -> str:
    """
    Direct REST call to OpenRouter chat completions API.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com",
        "X-Title": "AutoPoster",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 1024,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter API returned status {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected OpenRouter response structure: {data}") from e


def generate_caption(
    topic: str,
    config: Dict[str, Any],
    recent_captions: Optional[List[str]] = None,
    image_path: Optional[Path] = None,
) -> Tuple[str, str]:
    """
    Generates a social media caption using the configured providers in order of preference.
    Falls back gracefully if a provider returns an error, rate limit, or is missing a key.

    Returns:
        (caption_text, provider_name_used)
    """
    ai_cfg = config.get("ai", {})
    providers: List[str] = ai_cfg.get("text_providers", ["gemini", "groq", "openrouter"])
    models: Dict[str, str] = ai_cfg.get("models", {})
    vision_enabled = ai_cfg.get("vision_enabled_for_drive", True)

    system_prompt = build_system_prompt(config)
    user_prompt = build_user_prompt(topic, config, recent_captions=recent_captions)

    errors = []

    for provider in providers:
        provider = provider.lower().strip()
        logger.info(f"Attempting caption generation with provider: '{provider}'")

        try:
            if provider == "gemini":
                key = os.getenv("GEMINI_API_KEY", "").strip()
                if not key:
                    logger.warning("GEMINI_API_KEY not configured. Skipping Gemini.")
                    continue
                model = models.get("gemini", "gemini-1.5-flash")
                # Vision check: only pass image if vision is enabled and file exists
                v_img = image_path if (vision_enabled and image_path and image_path.exists()) else None
                text = call_gemini(system_prompt, user_prompt, model, key, image_path=v_img)
                logger.info(f"Caption generated successfully via Gemini ({model}).")
                return text, "gemini"

            elif provider == "groq":
                key = os.getenv("GROQ_API_KEY", "").strip()
                if not key:
                    logger.warning("GROQ_API_KEY not configured. Skipping Groq.")
                    continue
                model = models.get("groq", "llama-3.3-70b-versatile")
                text = call_groq(system_prompt, user_prompt, model, key)
                logger.info(f"Caption generated successfully via Groq ({model}).")
                return text, "groq"

            elif provider == "openrouter":
                key = os.getenv("OPENROUTER_API_KEY", "").strip()
                if not key:
                    logger.warning("OPENROUTER_API_KEY not configured. Skipping OpenRouter.")
                    continue
                model = models.get("openrouter", "meta-llama/llama-3.3-70b-instruct")
                text = call_openrouter(system_prompt, user_prompt, model, key)
                logger.info(f"Caption generated successfully via OpenRouter ({model}).")
                return text, "openrouter"

            else:
                logger.warning(f"Unknown text provider '{provider}' in configuration.")

        except Exception as e:
            msg = f"Provider '{provider}' failed: {e}"
            logger.warning(msg)
            errors.append(msg)

    error_summary = "; ".join(errors) if errors else "No providers with valid API keys found."
    raise RuntimeError(
        f"All AI text generation providers failed. Summary: {error_summary}. "
        "Please check your .env API keys or config.json."
    )


def test_text_providers(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Tests each configured AI provider with a tiny prompt.
    Used by CLI flag `--test-ai`.
    """
    ai_cfg = config.get("ai", {})
    providers: List[str] = ai_cfg.get("text_providers", ["gemini", "groq", "openrouter"])
    models: Dict[str, str] = ai_cfg.get("models", {})

    test_system = "You are a test helper."
    test_user = "Reply with exactly the word: SUCCESS"
    results = []

    for provider in providers:
        provider = provider.lower().strip()
        res = {"provider": provider, "status": "UNKNOWN", "model": "", "message": ""}
        try:
            if provider == "gemini":
                key = os.getenv("GEMINI_API_KEY", "").strip()
                model = models.get("gemini", "gemini-1.5-flash")
                res["model"] = model
                if not key:
                    res["status"] = "SKIPPED"
                    res["message"] = "GEMINI_API_KEY is missing in .env"
                else:
                    ans = call_gemini(test_system, test_user, model, key, timeout=10)
                    res["status"] = "PASSED"
                    res["message"] = f"OK: '{ans[:30]}'"

            elif provider == "groq":
                key = os.getenv("GROQ_API_KEY", "").strip()
                model = models.get("groq", "llama-3.3-70b-versatile")
                res["model"] = model
                if not key:
                    res["status"] = "SKIPPED"
                    res["message"] = "GROQ_API_KEY is missing in .env"
                else:
                    ans = call_groq(test_system, test_user, model, key, timeout=10)
                    res["status"] = "PASSED"
                    res["message"] = f"OK: '{ans[:30]}'"

            elif provider == "openrouter":
                key = os.getenv("OPENROUTER_API_KEY", "").strip()
                model = models.get("openrouter", "meta-llama/llama-3.3-70b-instruct")
                res["model"] = model
                if not key:
                    res["status"] = "SKIPPED"
                    res["message"] = "OPENROUTER_API_KEY is missing in .env"
                else:
                    ans = call_openrouter(test_system, test_user, model, key, timeout=10)
                    res["status"] = "PASSED"
                    res["message"] = f"OK: '{ans[:30]}'"

        except Exception as e:
            res["status"] = "FAILED"
            res["message"] = str(e)

        results.append(res)

    return results
