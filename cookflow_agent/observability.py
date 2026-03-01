import logging
import json
import time
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

# Cloud Run ships stdout logs to Cloud Logging automatically.
# Use JSON format so log entries are structured and queryable.
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s"  # raw JSON — Cloud Logging parses it
)
logger = logging.getLogger("cookflow")

def log(agent: str, event: str, payload: dict):
    logger.info(json.dumps({"agent": agent, "event": event, **payload}))


def before_model_callback(callback_context: CallbackContext, llm_request: LlmRequest):
    """Log when an agent calls the model. Attaches a start timestamp."""
    callback_context.state["_call_start"] = time.time()
    log(
        agent=callback_context.agent_name,
        event="model_call_start",
        payload={"invocation_id": callback_context.invocation_id}
    )
    return None  # None = don't intercept, let the call proceed


def after_model_callback(callback_context: CallbackContext, llm_response: LlmResponse):
    """Log agent response with latency. Extract key signals for monitoring."""
    elapsed = round(time.time() - callback_context.state.get("_call_start", time.time()), 2)
    agent = callback_context.agent_name
    text = llm_response.content.parts[0].text if llm_response.content and llm_response.content.parts else ""

    payload = {
        "invocation_id": callback_context.invocation_id,
        "latency_seconds": elapsed,
        "response_length": len(text) if isinstance(text, str) else 0,
    }

    # Recipe Finder signals — count recipes returned
    if agent == "Recipe_Finder_Agent":
        recipe_count = text.count('"id": "recipe_')
        time_flag = "over your" in text.lower() or "over the" in text.lower()
        payload["recipe_count"] = recipe_count
        payload["time_overage_flagged"] = time_flag

    # Batch Cooking signals — detect reheat-only recipes
    if agent == "Batch_Cooking_Agent":
        reheat_only = "reheat" in text.lower() and "phase 1" not in text.lower()
        payload["possible_reheat_only_recipe"] = reheat_only

    log(agent=agent, event="model_call_complete", payload=payload)
    return None  # None = don't modify the response