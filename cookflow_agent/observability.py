import json
import time

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types as genai_types


_FAILURE_THRESHOLD = 2
_ERROR_MESSAGE = (
    "I'm running into an issue right now. Please try again in a minute."
)


def log(agent: str, event: str, payload: dict):
    print(json.dumps({"agent": agent, "event": event, **payload}), flush=True)


def before_model_callback(callback_context: CallbackContext, llm_request: LlmRequest):
    """
    Log model call start. Circuit-breaker: if LLM has returned empty responses
    (not function calls) twice this invocation, short-circuit and return a
    user-friendly error instead of making another failing call.
    """
    failure_count = callback_context.state.get("_llm_failure_count", 0)
    if failure_count >= _FAILURE_THRESHOLD:
        log(
            agent=callback_context.agent_name,
            event="circuit_breaker_triggered",
            payload={
                "invocation_id": callback_context.invocation_id,
                "failure_count": failure_count,
            },
        )
        return LlmResponse(
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part(text=_ERROR_MESSAGE)],
            )
        )

    callback_context.state["_call_start"] = time.time()
    log(
        agent=callback_context.agent_name,
        event="model_call_start",
        payload={"invocation_id": callback_context.invocation_id},
    )
    return None


def after_model_callback(callback_context: CallbackContext, llm_response: LlmResponse):
    """
    Log agent response with latency. Track genuinely empty responses for
    circuit-breaker. Function calls are NOT counted as failures.
    """
    elapsed = round(time.time() - callback_context.state.get("_call_start", time.time()), 2)
    agent = callback_context.agent_name

    text = ""
    has_function_call = False

    if llm_response.content and llm_response.content.parts:
        for part in llm_response.content.parts:
            if hasattr(part, "text") and part.text:
                text += part.text
            if hasattr(part, "function_call") and part.function_call:
                has_function_call = True

    # Circuit-breaker: reset on text response or function call, increment only
    # on truly empty responses (no text, no function call — genuine LLM failure).
    if text or has_function_call:
        callback_context.state["_llm_failure_count"] = 0
    else:
        failure_count = callback_context.state.get("_llm_failure_count", 0) + 1
        callback_context.state["_llm_failure_count"] = failure_count
        log(
            agent=agent,
            event="empty_response",
            payload={
                "invocation_id": callback_context.invocation_id,
                "failure_count": failure_count,
            },
        )

    payload = {
        "invocation_id": callback_context.invocation_id,
        "latency_seconds": elapsed,
        "response_length": len(text),
        "has_function_call": has_function_call,
    }

    # Recipe Finder signals
    if agent == "Recipe_Finder_Agent":
        recipe_count = text.count('"id": "recipe_')
        time_flag = "over your" in text.lower() or "over the" in text.lower()
        payload["recipe_count"] = recipe_count
        payload["time_overage_flagged"] = time_flag

    # Meal Prep Planner signals
    if agent == "Meal_Prep_Planner_Agent":
        reheat_only = "reheat" in text.lower() and "phase 1" not in text.lower()
        payload["possible_reheat_only_recipe"] = reheat_only

    log(agent=agent, event="model_call_complete", payload=payload)
    return None
