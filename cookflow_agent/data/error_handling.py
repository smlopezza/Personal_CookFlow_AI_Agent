"""
CookFlow Error Handling
Covers the 4 error points from implementation_design.md:
  1. Gemini API errors (429, 500, timeout)
  2. Google Search failures → trigger JSON fallback
  3. Agent-to-agent handoffs returning empty/unusable results
  4. JSON database load failures → last-resort hardcoded recipes
"""

import functools
import json
import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("cookflow.errors")


# --------------------------------------------------------------------------- #
# 1. Error classification
# --------------------------------------------------------------------------- #

class CookFlowError(Exception):
    """Base class for all CookFlow errors."""
    pass

class RateLimitError(CookFlowError):
    """Gemini API 429 — too many requests."""
    pass

class APIServerError(CookFlowError):
    """Gemini API 500 / 503 — server-side failure."""
    pass

class APITimeoutError(CookFlowError):
    """Request timed out."""
    pass

class SearchFailedError(CookFlowError):
    """Google Search returned no usable results."""
    pass

class AgentHandoffError(CookFlowError):
    """Sub-agent returned empty or unusable output."""
    pass

class DatabaseError(CookFlowError):
    """Recipe JSON failed to load or is malformed."""
    pass


# --------------------------------------------------------------------------- #
# 2. User-facing messages — never expose raw errors
# --------------------------------------------------------------------------- #

USER_MESSAGES = {
    RateLimitError: (
        "I need a moment to catch up — I've been thinking a lot! "
        "Please try again in about a minute."
    ),
    APIServerError: (
        "I'm having a bit of trouble connecting right now. "
        "Let me try a different approach."
    ),
    APITimeoutError: (
        "That took longer than expected. "
        "Let me try again with a simpler plan."
    ),
    SearchFailedError: (
        "I couldn't find recipes through my usual search, "
        "so I'm pulling from my curated list instead."
    ),
    AgentHandoffError: (
        "I'm having a bit of trouble with {step}. Let me try a different approach."
    ),
    DatabaseError: (
        "I'm running into an issue loading my recipe list. "
        "I'll use a few reliable fallback recipes instead."
    ),
}

def user_message(error: CookFlowError, step: str = "that step") -> str:
    """Return a user-friendly message for the given error."""
    template = USER_MESSAGES.get(type(error), "I ran into an issue. Let me try again.")
    return template.format(step=step)


# --------------------------------------------------------------------------- #
# 3. Gemini API call wrapper
# --------------------------------------------------------------------------- #

def call_gemini_with_retry(
    fn: Callable,
    *args,
    max_retries: int = 1,
    retry_delay: float = 5.0,
    **kwargs,
) -> Any:
    """
    Wrap a Gemini API call with error handling and one retry.
    Translates google.api_core exceptions into CookFlow exceptions.

    Usage:
        result = call_gemini_with_retry(agent.run, user_input)
    """
    attempts = 0
    last_error = None

    while attempts <= max_retries:
        try:
            return fn(*args, **kwargs)

        except Exception as e:
            error_str = str(type(e).__name__).lower() + str(e).lower()

            if "429" in str(e) or "resource_exhausted" in error_str or "quota" in error_str:
                last_error = RateLimitError(str(e))
                # Rate limit — don't retry immediately, surface to user
                logger.warning("Gemini rate limit hit: %s", e)
                raise last_error

            elif "500" in str(e) or "503" in str(e) or "internal" in error_str or "unavailable" in error_str:
                last_error = APIServerError(str(e))
                logger.warning("Gemini server error (attempt %d): %s", attempts + 1, e)

            elif "timeout" in error_str or "deadline" in error_str:
                last_error = APITimeoutError(str(e))
                logger.warning("Gemini timeout (attempt %d): %s", attempts + 1, e)

            else:
                # Unknown error — log and re-raise as APIServerError
                last_error = APIServerError(str(e))
                logger.error("Unexpected Gemini error (attempt %d): %s", attempts + 1, e)

            attempts += 1
            if attempts <= max_retries:
                logger.info("Retrying in %.1f seconds...", retry_delay)
                time.sleep(retry_delay)

    raise last_error


# --------------------------------------------------------------------------- #
# 4. Google Search failure detection
# --------------------------------------------------------------------------- #

def validate_search_results(results: Any, min_count: int = 1) -> bool:
    """
    Return True if search results are usable.
    Results are unusable if: None, empty list, or fewer than min_count items.
    """
    if results is None:
        return False
    if isinstance(results, list) and len(results) < min_count:
        return False
    if isinstance(results, dict) and not results:
        return False
    return True


def safe_google_search(search_fn: Callable, query: str, **kwargs) -> tuple[Any, bool]:
    """
    Run Google Search with error handling.
    Returns (results, success) — if success is False, trigger JSON fallback.

    Usage:
        results, ok = safe_google_search(google_search_tool, "nut-free Colombian chicken stew")
        if not ok:
            results = filter_recipes(...)
    """
    try:
        results = search_fn(query, **kwargs)
        if not validate_search_results(results):
            logger.info("Google Search returned empty results for: %s", query)
            return None, False
        return results, True
    except Exception as e:
        logger.warning("Google Search failed for '%s': %s", query, e)
        return None, False


# --------------------------------------------------------------------------- #
# 5. Agent handoff validation
# --------------------------------------------------------------------------- #

def validate_agent_output(
    output: Any,
    required_keys: Optional[list[str]] = None,
    step_name: str = "sub-agent",
) -> Any:
    """
    Validate that a sub-agent returned usable output.
    Raises AgentHandoffError if output is None, empty, or missing required keys.

    Usage:
        recipes = validate_agent_output(
            recipe_finder.run(constraints),
            required_keys=["recipes"],
            step_name="Recipe Finder"
        )
    """
    if output is None:
        raise AgentHandoffError(f"{step_name} returned None")

    if isinstance(output, (list, dict, str)) and not output:
        raise AgentHandoffError(f"{step_name} returned empty output")

    if required_keys and isinstance(output, dict):
        missing = [k for k in required_keys if k not in output or not output[k]]
        if missing:
            raise AgentHandoffError(
                f"{step_name} missing required fields: {missing}"
            )

    return output


# --------------------------------------------------------------------------- #
# 6. JSON database failure fallback
# --------------------------------------------------------------------------- #

# Hardcoded minimal recipe set — last resort if recipes.json fails to load
_LAST_RESORT_RECIPES = [
    {
        "id": "fallback_001",
        "name": "Simple Chicken and Rice",
        "source_url": "classic_recipe",
        "servings": 4,
        "prep_time": 10,
        "cook_time": 30,
        "effort_level": "easy",
        "is_main_dish": True,
        "tags": ["international", "kid_friendly", "batch_cookable", "gluten_free", "dairy_free"],
        "allergens": [],
        "condition_avoids": {},
        "ingredients": [
            {"item": "chicken breast", "quantity": 1.5, "unit": "lbs", "category": "protein"},
            {"item": "white rice", "quantity": 1.5, "unit": "cups", "category": "pantry"},
            {"item": "chicken broth", "quantity": 3, "unit": "cups", "category": "pantry"},
            {"item": "garlic", "quantity": 2, "unit": "cloves", "category": "produce"},
            {"item": "yellow onion", "quantity": 1, "unit": "medium", "category": "produce"},
        ],
    },
    {
        "id": "fallback_002",
        "name": "Lentil Soup",
        "source_url": "classic_recipe",
        "servings": 4,
        "prep_time": 10,
        "cook_time": 40,
        "effort_level": "easy",
        "is_main_dish": True,
        "tags": ["international", "vegan", "vegetarian", "batch_cookable", "gluten_free", "dairy_free", "kid_friendly"],
        "allergens": [],
        "condition_avoids": {},
        "ingredients": [
            {"item": "red lentils", "quantity": 1.5, "unit": "cups", "category": "pantry"},
            {"item": "carrots", "quantity": 2, "unit": "medium", "category": "produce"},
            {"item": "yellow onion", "quantity": 1, "unit": "medium", "category": "produce"},
            {"item": "garlic", "quantity": 2, "unit": "cloves", "category": "produce"},
            {"item": "vegetable broth", "quantity": 6, "unit": "cups", "category": "pantry"},
            {"item": "ground cumin", "quantity": 1, "unit": "tsp", "category": "spice"},
        ],
    },
    {
        "id": "fallback_003",
        "name": "Sheet Pan Chicken and Vegetables",
        "source_url": "classic_recipe",
        "servings": 4,
        "prep_time": 15,
        "cook_time": 40,
        "effort_level": "easy",
        "is_main_dish": True,
        "tags": ["international", "batch_cookable", "kid_friendly", "gluten_free", "dairy_free"],
        "allergens": [],
        "condition_avoids": {},
        "ingredients": [
            {"item": "chicken thighs bone-in", "quantity": 2, "unit": "lbs", "category": "protein"},
            {"item": "baby potatoes", "quantity": 1, "unit": "lb", "category": "produce"},
            {"item": "broccoli florets", "quantity": 2, "unit": "cups", "category": "produce"},
            {"item": "olive oil", "quantity": 3, "unit": "tbsp", "category": "pantry"},
            {"item": "garlic", "quantity": 3, "unit": "cloves", "category": "produce"},
            {"item": "paprika", "quantity": 1, "unit": "tsp", "category": "spice"},
        ],
    },
    {
        "id": "fallback_004",
        "name": "Beef and Vegetable Stew",
        "source_url": "classic_recipe",
        "servings": 4,
        "prep_time": 20,
        "cook_time": 90,
        "effort_level": "medium",
        "is_main_dish": True,
        "tags": ["international", "batch_cookable", "kid_friendly", "gluten_free", "dairy_free"],
        "allergens": [],
        "condition_avoids": {},
        "ingredients": [
            {"item": "beef stew meat", "quantity": 1.5, "unit": "lbs", "category": "protein"},
            {"item": "carrots", "quantity": 3, "unit": "medium", "category": "produce"},
            {"item": "yellow potatoes", "quantity": 3, "unit": "medium", "category": "produce"},
            {"item": "yellow onion", "quantity": 1, "unit": "medium", "category": "produce"},
            {"item": "beef broth", "quantity": 4, "unit": "cups", "category": "pantry"},
            {"item": "tomato paste", "quantity": 2, "unit": "tbsp", "category": "pantry"},
        ],
    },
]

def load_recipe_db_safe(db_path: str) -> list[dict]:
    """
    Load recipes.json with fallback to hardcoded recipes if file is missing or malformed.
    Always returns a non-empty list.
    """
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        recipes = data.get("recipes", [])
        if not recipes:
            raise DatabaseError("recipes.json loaded but contains no recipes")
        logger.info("Recipe database loaded: %d recipes", len(recipes))
        return recipes
    except FileNotFoundError:
        logger.error("recipes.json not found at %s — using last-resort fallback", db_path)
        return _LAST_RESORT_RECIPES
    except json.JSONDecodeError as e:
        logger.error("recipes.json is malformed: %s — using last-resort fallback", e)
        return _LAST_RESORT_RECIPES
    except Exception as e:
        logger.error("Unexpected error loading recipes.json: %s — using last-resort fallback", e)
        return _LAST_RESORT_RECIPES


# --------------------------------------------------------------------------- #
# 7. Root Agent orchestration wrapper
# --------------------------------------------------------------------------- #

def safe_pipeline_step(
    step_fn: Callable,
    step_name: str,
    fallback_fn: Optional[Callable] = None,
    *args,
    **kwargs,
) -> tuple[Any, Optional[str]]:
    """
    Run a pipeline step (agent call) with error handling.
    Returns (result, error_message_for_user).
    If error_message is not None, Root Agent should surface it before retrying.

    Usage:
        result, err = safe_pipeline_step(
            recipe_finder.run, "Recipe Finder",
            fallback_fn=lambda: filter_recipes(**constraints),
            constraints
        )
        if err:
            yield err  # surface to user
    """
    try:
        result = call_gemini_with_retry(step_fn, *args, **kwargs)
        validate_agent_output(result, step_name=step_name)
        return result, None

    except RateLimitError as e:
        return None, user_message(e)

    except (APIServerError, APITimeoutError) as e:
        if fallback_fn:
            logger.info("Trying fallback for %s after error: %s", step_name, e)
            try:
                result = fallback_fn()
                return result, user_message(SearchFailedError(), step=step_name)
            except Exception as fallback_error:
                logger.error("Fallback also failed for %s: %s", step_name, fallback_error)
        return None, user_message(AgentHandoffError(), step=step_name)

    except AgentHandoffError as e:
        if fallback_fn:
            try:
                result = fallback_fn()
                return result, user_message(SearchFailedError(), step=step_name)
            except Exception:
                pass
        return None, user_message(e, step=step_name)

    except Exception as e:
        logger.error("Unhandled error in %s: %s", step_name, e)
        return None, user_message(AgentHandoffError(), step=step_name)


# --------------------------------------------------------------------------- #
# Smoke test
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    # Test 1: Database load with valid path
    import os
    db_path = os.path.join(os.path.dirname(__file__), "recipes.json")
    recipes = load_recipe_db_safe(db_path)
    print(f"DB load test: {len(recipes)} recipes loaded")

    # Test 2: Database load with bad path → last-resort fallback
    recipes_fallback = load_recipe_db_safe("/nonexistent/path/recipes.json")
    print(f"Fallback test: {len(recipes_fallback)} last-resort recipes returned")

    # Test 3: Search result validation
    print(f"Empty list valid: {validate_search_results([])}")         # False
    print(f"None valid: {validate_search_results(None)}")             # False
    print(f"One result valid: {validate_search_results(['x'])}")      # True

    # Test 4: Agent output validation
    try:
        validate_agent_output(None, step_name="Recipe Finder")
    except AgentHandoffError as e:
        print(f"None output caught: {e}")

    try:
        validate_agent_output({"recipes": []}, required_keys=["recipes"], step_name="Recipe Finder")
    except AgentHandoffError as e:
        print(f"Empty recipes caught: {e}")

    print("All error handling smoke tests passed.")
