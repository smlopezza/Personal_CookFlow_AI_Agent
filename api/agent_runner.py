"""
ADK agent runner for FastAPI integration.
Manages sessions and runs the CookFlow root agent.

"""

import os
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Import root agent from existing cookflow_agent package
from cookflow_agent.agent import root_agent

APP_NAME = "cookflow"
USER_ID = "web_user"  # single-user for now; replace with session cookie later

session_service = InMemorySessionService()
runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)


async def create_session(session_id: str) -> None:
    """Create a new ADK session."""
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
    )


async def run_agent_turn(session_id: str, message: str) -> str:
    """
    Send a message to the agent and return the final text response.
    Reuses an existing session so conversation state is preserved between turns.
    """
    content = types.Content(
        role="user",
        parts=[types.Part(text=message)],
    )

    response_text = ""
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response():
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text

    return response_text


def build_form_prompt(data: dict) -> str:
    """
    Convert form data into a structured agent message.
    The [FORM_SUBMISSION] prefix tells the agent to skip Phase 0 and Phase 2.
    """
    mode = data.get("mode", "weekly")
    allergens = ", ".join(data.get("allergens", [])) or "none"
    cuisines = ", ".join(data.get("cuisines", [])) or "any"
    household_size = data.get("household_size", 4)
    cooking_frequency = data.get("cooking_frequency", "batch cook once a week")
    max_minutes = data.get("max_total_minutes", 240)
    ingredients = data.get("available_ingredients", "")

    if mode == "ingredient":
        return (
            f"[FORM_SUBMISSION] Mode: ingredient-first. "
            f"Available ingredients: {ingredients}. "
            f"Household: {household_size} people. "
            f"Allergens: {allergens}. "
            f"Cuisines: {cuisines}. "
            f"Max cooking time: {max_minutes} minutes."
        )
    else:
        return (
            f"[FORM_SUBMISSION] Mode: weekly plan. "
            f"Household: {household_size} people. "
            f"Allergens: {allergens}. "
            f"Cuisines: {cuisines}. "
            f"Cooking frequency: {cooking_frequency}. "
            f"Max cooking time: {max_minutes} minutes."
        )
