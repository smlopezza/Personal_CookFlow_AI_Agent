import os
import json
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool  # for google-adk==1.4.1
from google.adk.models.google_llm import Gemini
from google.genai import types
from .sub_agents.recipe_finder.agent import recipe_finder_agent
from .sub_agents.meal_prep_planner.agent import meal_prep_planner_agent
from .prompt import ROOT_AGENT_INSTRUCTIONS
from .observability import before_model_callback, after_model_callback
from .data.recipe_filter import filter_recipes, relaxation_message, filter_live_recipes
from .data.error_handling import load_recipe_db_safe
from .data.family_context import load_family_context, save_family_context, delete_family_context

# Load environment variables from .env file
load_dotenv()

_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "recipes.json")
load_recipe_db_safe(_DB_PATH)  # startup check

ROOT_AGENT_MODEL = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")

CATEGORY_ORDER = ["produce", "protein", "dairy", "seafood", "pantry", "spice", "frozen", "bakery", "other"]
PANTRY_STAPLES = {"salt", "pepper", "oil", "water", "olive oil", "vegetable oil", "cooking oil"}


# ─────────────────────────────────────────────────────────────────────────────
# Tool 1: recipe_db_fallback
# ─────────────────────────────────────────────────────────────────────────────

def recipe_db_fallback(
    allergens: list[str] = [],
    cuisines: list[str] = [],
    kid_friendly: bool = False,
    vegan: bool = False,
    vegetarian: bool = False,
    cooking_frequency: str = "",
    max_total_minutes: int = 0,
    effort_levels: list[str] = [],
    count: int = 4,
) -> str:
    """
    Fallback tool: filter the curated recipe database when recipe_finder
    returns no results. Call this when recipe_finder returns empty recipes.
    Returns JSON with 'recipes' list and 'relaxation_note'.

    Args:
        allergens: Declared allergens (safety-critical, never relaxed)
        cuisines: Preferred cuisines (soft constraint, may be relaxed)
        kid_friendly: Prefer kid-friendly recipes
        vegan: Only vegan recipes (hard constraint)
        vegetarian: Only vegetarian/vegan recipes (hard constraint)
        cooking_frequency: "batch", "few_times", or "daily"
        max_total_minutes: Max total cook+prep time in minutes
        effort_levels: Acceptable effort levels (e.g. ["easy", "medium"])
        count: Number of recipes to return (3 for Mode A, 4 for Mode B)
    """
    max_total_minutes = max_total_minutes or None
    batch_cook = (cooking_frequency == "batch")
    recipes, relaxed = filter_recipes(
        count=count,
        allergens=allergens,
        cuisines=cuisines,
        kid_friendly=kid_friendly,
        vegan=vegan,
        vegetarian=vegetarian,
        batch_cook=batch_cook,
        max_total_minutes=max_total_minutes,
        effort_levels=effort_levels,
    )
    note = relaxation_message(relaxed, {"cuisines": cuisines or []})
    return json.dumps({"recipes": recipes, "relaxation_note": note})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2: process_recipes — allergen filter + total_time extraction
# ALWAYS call this after recipe_finder and BEFORE meal_prep_planner
# ─────────────────────────────────────────────────────────────────────────────

def process_recipes(
    recipes_json: str,
    allergens: list[str] = [],
    vegan: bool = False,
    vegetarian: bool = False,
) -> str:
    """
    Root Agent interception step: apply hard constraint filters to recipe_finder
    output and extract total_time_estimate as a structured integer.

    ALWAYS call this after recipe_finder returns and BEFORE calling meal_prep_planner.
    """
    allergens = allergens or []

    try:
        data = json.loads(recipes_json)
        if isinstance(data, list):
            recipes = data
            total_time_estimate = sum(r.get("total_time_minutes", 0) for r in recipes)
        else:
            recipes = data.get("recipes", [])
            total_time_estimate = data.get("total_time_estimate", 0)
            if not total_time_estimate and recipes:
                total_time_estimate = sum(r.get("total_time_minutes", 0) for r in recipes)
    except (json.JSONDecodeError, TypeError, AttributeError):
        return json.dumps({
            "filtered_recipes": [],
            "total_time_estimate": 0,
            "relaxation_note": "Could not parse recipe_finder output — calling fallback.",
        })

    filtered, notes = filter_live_recipes(
        recipes,
        allergens=allergens,
        vegan=vegan,
        vegetarian=vegetarian,
    )

    return json.dumps({
        "filtered_recipes": filtered,
        "total_time_estimate": int(total_time_estimate or 0),
        "relaxation_note": notes[0] if notes else "",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Tool 3: build_grocery_list — Python consolidation
# ─────────────────────────────────────────────────────────────────────────────

def build_grocery_list(recipes_json: str, household_size: int = 4) -> str:
    """
    Build a consolidated grocery list from filtered recipes.
    Deduplicates ingredients across all recipes, scales quantities to household_size,
    and groups by store section. ALWAYS call this after meal_prep_planner.

    Args:
        recipes_json: JSON string — list of recipe dicts or {"filtered_recipes": [...]}
        household_size: Number of people to scale quantities for

    Returns JSON list:
        [{"item": str, "quantity": float, "unit": str, "category": str}, ...]
        Sorted by store section then item name.
        Pantry staples (salt, pepper, oil, water) are excluded.
    """
    try:
        data = json.loads(recipes_json)
        if isinstance(data, list):
            recipes = data
        else:
            recipes = data.get("filtered_recipes", data.get("recipes", []))
    except (json.JSONDecodeError, TypeError):
        return json.dumps([])

    consolidated: dict[tuple, dict] = {}

    for recipe in recipes:
        servings = max(recipe.get("servings", 4), 1)
        scale = household_size / servings

        for ing in recipe.get("ingredients", []):
            item_name = (ing.get("item") or "").strip()
            if not item_name or item_name.lower() in PANTRY_STAPLES:
                continue

            unit = (ing.get("unit") or "").strip()
            qty = float(ing.get("quantity") or 0)
            category = ing.get("category", "other")
            if category not in CATEGORY_ORDER:
                category = "other"

            key = (item_name.lower(), unit.lower())
            if key in consolidated:
                consolidated[key]["quantity"] = round(consolidated[key]["quantity"] + qty * scale, 1)
            else:
                consolidated[key] = {
                    "item": item_name,
                    "quantity": round(qty * scale, 1),
                    "unit": unit,
                    "category": category,
                }

    grocery_list = sorted(
        consolidated.values(),
        key=lambda x: (CATEGORY_ORDER.index(x["category"]), x["item"]),
    )

    return json.dumps(grocery_list)


# ─────────────────────────────────────────────────────────────────────────────
# Tool 4: load_user_profile — load FamilyContext from Firestore
# ─────────────────────────────────────────────────────────────────────────────

def load_user_profile(user_id: str) -> str:
    """
    Load the user's saved family profile from Firestore.

    Call this at the START of every session, immediately after getting the user's name.
    - exists=true: returning user — surface profile for confirmation.
    - exists=false: first session — ask for consent before collecting anything.

    Args:
        user_id: The name or identifier the user provided.

    Returns JSON:
        {"exists": true, "profile": {...}}   — returning user
        {"exists": false}                    — first session
    """
    profile = load_family_context(user_id)
    if profile is None:
        return json.dumps({"exists": False})
    return json.dumps({"exists": True, "profile": profile})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 5: save_user_profile — persist FamilyContext to Firestore
# ─────────────────────────────────────────────────────────────────────────────

def save_user_profile(user_id: str, profile_json: str) -> str:
    """
    Save the user's family profile to Firestore.

    ONLY call this after the user has explicitly said YES to data storage.
    Never call this if the user said NO or hasn't been asked yet.

    Args:
        user_id: The name or identifier the user provided.
        profile_json: JSON string with FamilyContext fields:
            {
                "household_size": 4,
                "allergens": ["nuts"],
                "condition_avoids": {},
                "cultural_preferences": ["Colombian", "Canadian"],
                "cooking_frequency": "once a week",
                "cooking_day": "Sunday",
                "grocery_day": ""
            }

    Returns JSON:
        {"success": true} or {"success": false}
    """
    try:
        profile = json.loads(profile_json)
        success = save_family_context(user_id, profile)
        return json.dumps({"success": success})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 6: delete_user_profile — remove FamilyContext from Firestore
# ─────────────────────────────────────────────────────────────────────────────

def delete_user_profile(user_id: str) -> str:
    """
    Delete the user's saved profile from Firestore.
    Call this if the user withdraws consent mid-session.

    Returns JSON:
        {"success": true} or {"success": false}
    """
    try:
        success = delete_family_context(user_id)
        return json.dumps({"success": success})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Root Agent
# ─────────────────────────────────────────────────────────────────────────────

retry_config = types.HttpRetryOptions(
    attempts=5,
    exp_base=7,
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504],
)

root_agent = Agent(
    name="Root_agent",
    model=Gemini(model=ROOT_AGENT_MODEL, retry_options=retry_config),
    description="A root agent that coordinates sub-agents to assist users in meal planning.",
    instruction=ROOT_AGENT_INSTRUCTIONS,
    before_model_callback=before_model_callback,
    after_model_callback=after_model_callback,
    tools=[
        AgentTool(recipe_finder_agent),
        AgentTool(meal_prep_planner_agent),
        recipe_db_fallback,
        process_recipes,
        build_grocery_list,
        load_user_profile,
        save_user_profile,
        delete_user_profile,
    ],
)
