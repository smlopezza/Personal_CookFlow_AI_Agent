import re
import json
import os
from urllib.parse import urlparse
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import google_search
from google.genai import types as genai_types
from .prompt import RECIPE_FINDER_AGENT_INSTRUCTIONS
from ...observability import before_model_callback as _base_before_model_callback
from ...observability import after_model_callback as _base_after_model_callback

load_dotenv()

RECIPE_FINDER_MODEL = os.getenv("RECIPE_FINDER_MODEL", "gemini-2.5-flash")

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".avif"}
_SESSION_URLS_KEY = "_search_urls"


def _is_page_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return not any(path.endswith(ext) for ext in _IMAGE_EXTENSIONS)


def _harvest_urls_from_request(llm_request: LlmRequest) -> list[str]:
    """
    Scan function_response parts in the request history for google_search results
    and return any page URLs found. Checks all common ADK response shapes.
    """
    urls = []
    try:
        for content in (llm_request.contents or []):
            for part in (content.parts or []):
                fn_resp = getattr(part, "function_response", None)
                if fn_resp is None:
                    continue
                if getattr(fn_resp, "name", "") != "google_search":
                    continue
                payload = getattr(fn_resp, "response", None)
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        continue
                # Normalise: ADK may return a list, or a dict with various keys
                if isinstance(payload, list):
                    items = payload
                elif isinstance(payload, dict):
                    items = (
                        payload.get("result")
                        or payload.get("results")
                        or payload.get("organic")
                        or payload.get("items")
                        or []
                    )
                    # Some ADK versions nest under a top-level key
                    if not items:
                        for v in payload.values():
                            if isinstance(v, list) and v:
                                items = v
                                break
                else:
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url") or item.get("link") or item.get("uri") or ""
                    if url and _is_page_url(url):
                        urls.append(url)
    except Exception:
        pass
    return urls


def _harvest_urls_from_response(llm_response: LlmResponse) -> list[str]:
    """
    Extract URLs from grounding_metadata on the LlmResponse, which ADK populates
    when google_search grounding is used.
    """
    urls = []
    try:
        grounding = getattr(llm_response, "grounding_metadata", None)
        if not grounding:
            return urls
        for chunk in (getattr(grounding, "grounding_chunks", None) or []):
            web = getattr(chunk, "web", None)
            if web:
                uri = getattr(web, "uri", None)
                if uri and _is_page_url(uri):
                    urls.append(uri)
    except Exception:
        pass
    return urls


def _strip_unverified_urls(text: str, valid_urls: set) -> str:
    """
    Parse the first JSON array in text. Set source_url to null for any URL that
    was not in the verified search results. Returns the (possibly modified) text.
    """
    try:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return text
        recipes = json.loads(match.group(0))
        modified = False
        for recipe in recipes:
            url = recipe.get("source_url")
            if url and url not in valid_urls:
                recipe["source_url"] = None
                modified = True
        if not modified:
            return text
        cleaned = json.dumps(recipes, indent=2)
        return text[: match.start()] + cleaned + text[match.end():]
    except Exception:
        return text


# ── Callbacks ────────────────────────────────────────────────────────────────

def before_model_callback(callback_context: CallbackContext, llm_request: LlmRequest):
    """Harvest any google_search URLs already in the request history, then run base callback."""
    urls = _harvest_urls_from_request(llm_request)
    if urls:
        existing: list = callback_context.state.get(_SESSION_URLS_KEY, [])
        callback_context.state[_SESSION_URLS_KEY] = existing + urls

    return _base_before_model_callback(callback_context, llm_request)


def after_model_callback(callback_context: CallbackContext, llm_response: LlmResponse):
    """
    1. Harvest grounding URLs from this response into session state.
    2. Apply URL safety net: strip any source_url that isn't in verified search results.
    3. Run base observability callback.
    """
    result = _base_after_model_callback(callback_context, llm_response)

    # Harvest grounding URLs from this response
    new_urls = _harvest_urls_from_response(llm_response)
    if new_urls:
        existing: list = callback_context.state.get(_SESSION_URLS_KEY, [])
        callback_context.state[_SESSION_URLS_KEY] = existing + new_urls

    # Safety net: strip unverified URLs from any JSON array in the response text
    valid_urls: set = set(callback_context.state.get(_SESSION_URLS_KEY, []))
    if valid_urls and llm_response.content and llm_response.content.parts:
        changed = False
        new_parts = []
        for part in llm_response.content.parts:
            if hasattr(part, "text") and part.text:
                cleaned = _strip_unverified_urls(part.text, valid_urls)
                if cleaned != part.text:
                    changed = True
                    new_parts.append(genai_types.Part(text=cleaned))
                else:
                    new_parts.append(part)
            else:
                new_parts.append(part)
        if changed:
            llm_response.content = genai_types.Content(
                role=llm_response.content.role,
                parts=new_parts,
            )

    return result


# ── Agent ─────────────────────────────────────────────────────────────────────

recipe_finder_agent = Agent(
    name="recipe_finder",
    model=Gemini(model=RECIPE_FINDER_MODEL),
    description="Search for recipes based on user constraints and return structured results with real URLs.",
    instruction=RECIPE_FINDER_AGENT_INSTRUCTIONS,
    before_model_callback=before_model_callback,
    after_model_callback=after_model_callback,
    tools=[google_search],
    output_key="recipes",
)
