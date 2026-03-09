"""
CookFlow FastAPI app.

Directory structure:
  api/
    main.py              ← this file
    agent_runner.py
    templates/
      index.html
      chat.html
      recipes.html
      results.html
  cookflow_agent/        ← existing package (sibling to api/)

Run locally:
  uvicorn api.main:app --reload

Deploy: see Dockerfile
"""

import uuid
import json
import os
import re
import markdown as md

from fastapi import FastAPI, Request, Form, Cookie, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from typing import Annotated, Optional

from .agent_runner import create_session, run_agent_turn, stream_agent_turn, build_form_prompt
from cookflow_agent.data.family_context import (
    load_family_context,
    save_family_context,
    delete_family_context,
)

app = FastAPI(title="CookFlow")

# Pending prompts for streaming: session_id → message
# Populated by /plan and /confirm, consumed by /stream/* SSE endpoints
_pending: dict[str, str] = {}


def render_markdown(text: str) -> str:
    """Convert agent markdown output to HTML. Links open in a new tab."""
    # Convert bare URLs to markdown links so the renderer picks them up
    text = re.sub(r'(?<!\()(?<!")(https?://[^\s|<>"]+)', r'[\1](\1)', text)
    html = md.markdown(text, extensions=["tables", "nl2br"])
    # Make all links open in a new tab
    html = re.sub(r'<a href=', '<a target="_blank" rel="noopener noreferrer" href=', html)
    return html


templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

CUISINE_OPTIONS = [
    "Any",
    "Colombian", "Mexican", "Peruvian", "Brazilian", "Caribbean",
    "Canadian", "USA",
    "Italian", "French", "Greek", "Spanish",
    "Indian", "Chinese", "Japanese", "Thai", "Vietnamese", "Korean",
    "Middle Eastern", "Ethiopian",
]
FREQUENCY_OPTIONS = [
    ("batch", "Batch cook once a week"),
    ("few_times", "A few times a week"),
    ("daily", "Daily"),
]


# ─────────────────────────────────────────────────────────────────────────────
# GET / — Preferences form
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user_id: Annotated[Optional[str], Cookie()] = None):
    """Show preferences form. Pre-fill from Firestore if returning user."""
    profile = None
    if user_id:
        profile = load_family_context(user_id)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "profile": profile,
        "cuisine_options": CUISINE_OPTIONS,
        "frequency_options": FREQUENCY_OPTIONS,
        "returning_user": profile is not None,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /plan — Submit preferences → return loading page → stream recipes via SSE
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/plan", response_class=HTMLResponse)
async def plan(
    request: Request,
    response: Response,
    household_size: Annotated[int, Form()],
    allergens: Annotated[str, Form()] = "",
    cuisines: Annotated[list[str], Form()] = [],
    cuisine_other: Annotated[str, Form()] = "",
    cooking_frequency: Annotated[str, Form()] = "batch",
    max_total_minutes: Annotated[int, Form()] = 240,
    mode: Annotated[str, Form()] = "weekly",
    available_ingredients: Annotated[str, Form()] = "",
    kid_friendly: Annotated[bool, Form()] = False,
    additional_notes: Annotated[str, Form()] = "",
    remember: Annotated[bool, Form()] = False,
    user_id: Annotated[Optional[str], Cookie()] = None,
):
    """
    Process form and return recipes page in loading state.
    The page connects to /stream/plan via SSE to receive the agent response.
    """
    if not user_id:
        user_id = str(uuid.uuid4())

    allergen_list = [a.strip() for a in allergens.split(",") if a.strip()]

    cuisine_list = [c for c in cuisines if c != "Other"]
    if cuisine_other.strip():
        cuisine_list.append(cuisine_other.strip())

    form_data = {
        "mode": mode,
        "household_size": household_size,
        "allergens": allergen_list,
        "cuisines": cuisine_list if cuisine_list else [],
        "cooking_frequency": cooking_frequency,
        "max_total_minutes": max_total_minutes,
        "available_ingredients": available_ingredients,
        "kid_friendly": kid_friendly,
        "additional_notes": additional_notes.strip(),
    }

    if remember:
        save_family_context(user_id, {
            "household_size": household_size,
            "allergens": allergen_list,
            "condition_avoids": {},
            "cultural_preferences": cuisine_list if cuisine_list else [],
            "cooking_frequency": cooking_frequency,
            "cooking_day": "",
            "grocery_day": "",
            "kid_friendly": kid_friendly,
        })

    session_id = str(uuid.uuid4())
    await create_session(session_id)

    prompt = build_form_prompt(form_data)
    _pending[session_id] = prompt  # consumed by /stream/plan

    html_response = templates.TemplateResponse("recipes.html", {
        "request": request,
        "session_id": session_id,
        "mode": mode,
        "loading": True,
        "stream_url": f"/stream/plan?session_id={session_id}",
    })
    html_response.set_cookie("user_id", user_id, max_age=30 * 24 * 3600)
    return html_response


@app.get("/stream/plan")
async def stream_plan(session_id: str):
    """
    SSE endpoint: stream recipe finder output for a pending /plan session.
    The browser connects here via EventSource after receiving the loading page.
    """
    prompt = _pending.pop(session_id, None)
    if not prompt:
        return Response("Session not found", status_code=404)

    async def generate():
        try:
            async for chunk in stream_agent_turn(session_id, prompt):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps('[ERROR] ' + str(e))}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /confirm — User selects recipes → return loading page → stream full plan
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/confirm", response_class=HTMLResponse)
async def confirm(
    request: Request,
    session_id: Annotated[str, Form()],
    selection: Annotated[str, Form()],
):
    """
    Store user selection and return results page in loading state.
    The page connects to /stream/confirm via SSE to receive the full plan.
    """
    _pending[session_id] = selection  # consumed by /stream/confirm

    return templates.TemplateResponse("results.html", {
        "request": request,
        "session_id": session_id,
        "loading": True,
        "stream_url": f"/stream/confirm?session_id={session_id}",
    })


@app.get("/stream/confirm")
async def stream_confirm(session_id: str):
    """
    SSE endpoint: stream full meal plan output for a pending /confirm session.
    """
    selection = _pending.pop(session_id, None)
    if not selection:
        return Response("Session not found", status_code=404)

    async def generate():
        try:
            async for chunk in stream_agent_turn(session_id, selection):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps('[ERROR] ' + str(e))}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /swap — User requests recipe swap → stream updated options
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/swap", response_class=HTMLResponse)
async def swap(
    request: Request,
    session_id: Annotated[str, Form()],
    swap_request: Annotated[str, Form()],
    mode: Annotated[str, Form()] = "weekly",
):
    """Store swap request and return recipes page in loading state."""
    _pending[session_id] = swap_request

    return templates.TemplateResponse("recipes.html", {
        "request": request,
        "session_id": session_id,
        "mode": mode,
        "loading": True,
        "stream_url": f"/stream/swap?session_id={session_id}",
    })


@app.get("/stream/swap")
async def stream_swap(session_id: str):
    """SSE endpoint: stream updated recipe options after a swap request."""
    swap_request = _pending.pop(session_id, None)
    if not swap_request:
        return Response("Session not found", status_code=404)

    async def generate():
        try:
            async for chunk in stream_agent_turn(session_id, swap_request):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps('[ERROR] ' + str(e))}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /chat — Start a fresh chat session
# POST /chat — Send a message, return updated chat page
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Open a fresh chat session — agent handles Phase 0 (name, consent, family setup)."""
    session_id = str(uuid.uuid4())
    await create_session(session_id)

    return templates.TemplateResponse("chat.html", {
        "request": request,
        "session_id": session_id,
        "history": [],
        "history_json": "[]",
    })


@app.post("/chat", response_class=HTMLResponse)
async def chat_message(
    request: Request,
    session_id: Annotated[str, Form()],
    message: Annotated[str, Form()],
    history: Annotated[str, Form()] = "[]",
):
    """Process a chat message and return updated chat page with conversation history."""
    history_list = json.loads(history)
    history_list.append({"role": "user", "text": message})

    agent_response = await run_agent_turn(session_id, message)
    history_list.append({"role": "agent", "html": render_markdown(agent_response)})

    return templates.TemplateResponse("chat.html", {
        "request": request,
        "session_id": session_id,
        "history": history_list,
        "history_json": json.dumps(history_list),
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /forget — User withdraws consent, delete Firestore profile
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/forget")
async def forget(
    response: Response,
    user_id: Annotated[Optional[str], Cookie()] = None,
):
    """Delete saved profile from Firestore and clear cookie."""
    if user_id:
        delete_family_context(user_id)
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("user_id")
    return response
