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
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Annotated, Optional

from .agent_runner import create_session, run_agent_turn, build_form_prompt
from cookflow_agent.data.family_context import (
    load_family_context,
    save_family_context,
    delete_family_context,
)

app = FastAPI(title="CookFlow")


def render_markdown(text: str) -> str:
    """Convert agent markdown output to HTML. Links open in a new tab."""
    # Convert bare URLs to markdown links so the renderer picks them up
    text = re.sub(r'(?<!\()(?<!")(https?://[^\s|<>"]+)', r'[\1](\1)', text)
    html = md.markdown(text, extensions=["tables", "nl2br"])
    # Make all links open in a new tab
    html = re.sub(r'<a href=', '<a target="_blank" rel="noopener noreferrer" href=', html)
    return html
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

CUISINE_OPTIONS = ["Colombian", "Canadian", "Mexican", "Italian", "Chinese", "Indian", "Any"]
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
# POST /plan — Submit preferences → run agent → recipe options
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/plan", response_class=HTMLResponse)
async def plan(
    request: Request,
    response: Response,
    household_size: Annotated[int, Form()],
    allergens: Annotated[str, Form()] = "",
    cuisines: Annotated[list[str], Form()] = [],
    cooking_frequency: Annotated[str, Form()] = "batch",
    max_total_minutes: Annotated[int, Form()] = 240,
    mode: Annotated[str, Form()] = "weekly",
    available_ingredients: Annotated[str, Form()] = "",
    kid_friendly: Annotated[bool, Form()] = False,
    remember: Annotated[bool, Form()] = False,
    user_id: Annotated[Optional[str], Cookie()] = None,
):
    """Process form, call agent, return recipe options for user to select."""

    # Resolve user_id — create one if new user
    if not user_id:
        user_id = str(uuid.uuid4())

    # Parse allergens (comma-separated string → list)
    allergen_list = [a.strip() for a in allergens.split(",") if a.strip()]

    form_data = {
        "mode": mode,
        "household_size": household_size,
        "allergens": allergen_list,
        "cuisines": cuisines if cuisines else [],
        "cooking_frequency": cooking_frequency,
        "max_total_minutes": max_total_minutes,
        "available_ingredients": available_ingredients,
        "kid_friendly": kid_friendly,
    }

    # Save to Firestore if user consented
    if remember:
        save_family_context(user_id, {
            "household_size": household_size,
            "allergens": allergen_list,
            "condition_avoids": {},
            "cultural_preferences": cuisines if cuisines else [],
            "cooking_frequency": cooking_frequency,
            "cooking_day": "",
            "grocery_day": "",
            "kid_friendly": kid_friendly,
        })

    # Create ADK session and get recipe options from agent
    session_id = str(uuid.uuid4())
    await create_session(session_id)

    prompt = build_form_prompt(form_data)
    agent_response = await run_agent_turn(session_id, prompt)

    # Set user_id cookie (30 days)
    html_response = templates.TemplateResponse("recipes.html", {
        "request": request,
        "agent_response": render_markdown(agent_response),
        "session_id": session_id,
        "mode": mode,
    })
    html_response.set_cookie("user_id", user_id, max_age=30 * 24 * 3600)
    return html_response


# ─────────────────────────────────────────────────────────────────────────────
# POST /confirm — User selects recipe → agent completes pipeline
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/confirm", response_class=HTMLResponse)
async def confirm(
    request: Request,
    session_id: Annotated[str, Form()],
    selection: Annotated[str, Form()],
):
    """Send user's recipe selection to agent, return full meal plan."""
    agent_response = await run_agent_turn(session_id, selection)

    return templates.TemplateResponse("results.html", {
        "request": request,
        "plan": render_markdown(agent_response),
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /swap — User requests recipe swap → repopulate recipes page
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/swap", response_class=HTMLResponse)
async def swap(
    request: Request,
    session_id: Annotated[str, Form()],
    swap_request: Annotated[str, Form()],
    mode: Annotated[str, Form()] = "weekly",
):
    """Send swap request to agent, return updated recipe options on the same page."""
    agent_response = await run_agent_turn(session_id, swap_request)

    return templates.TemplateResponse("recipes.html", {
        "request": request,
        "agent_response": render_markdown(agent_response),
        "session_id": session_id,
        "mode": mode,
    })


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
