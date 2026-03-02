import os
from dotenv import load_dotenv
from google.adk.agents import Agent
# from google.adk.tools import AgentTool
from google.adk.tools.agent_tool import AgentTool # for version google-adk==1.4.1
from google.adk.models.google_llm import Gemini
from google.genai import types
from .sub_agents.recipe_finder.agent import recipe_finder_agent
from .sub_agents.meal_prep_planner.agent import meal_prep_planner_agent
from .prompt import ROOT_AGENT_INSTRUCTIONS
from .observability import before_model_callback, after_model_callback  
from .data.recipe_filter import filter_recipes, relaxation_message, filter_live_recipes
from .data.error_handling import load_recipe_db_safe
import json

# Load environment variables from .env file
load_dotenv()

_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "recipes.json")
load_recipe_db_safe(_DB_PATH)  # startup check

# Read the model name from .env
ROOT_AGENT_MODEL = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")

CATEGORY_ORDER = ["produce", "protein", "dairy", "seafood", "pantry", "spice", "frozen", "bakery", "other"]
PANTRY_STAPLES = {"salt", "pepper", "oil", "water", "olive oil", "vegetable oil", "cooking oil"}

# ─────────────────────────────────────────────────────────────────────────────
# Tool 1: Fallback recipe DB (unchanged role — called when Recipe Finder empty)
# ─────────────────────────────────────────────────────────────────────────────

def recipe_db_fallback(
    allergens: list[str] = None,
    cuisines: list[str] = None,
    kid_friendly: bool = False,
    vegan: bool = False,
    vegetarian: bool = False,
    cooking_frequency: str = None,
    max_total_minutes: int = None,
    effort_levels: list[str] = None,
    count: int = 4,
) -> str:
    """
    Fallback tool: filter the curated recipe database when Recipe Finder
    returns no results. Call this when recipe_finder returns empty recipes.
    Returns JSON with 'recipes' list and 'relaxation_note'.

    Args:
        allergens:         Declared allergens (safety-critical, never relaxed)
        cuisines:          Preferred cuisines (soft constraint, may be relaxed)
        kid_friendly:      Prefer kid-friendly recipes
        vegan:             Only vegan recipes (hard constraint)
        vegetarian:        Only vegetarian/vegan recipes (hard constraint)
        cooking_frequency: "batch", "few_times", or "daily" (replaces batch_cook)
        max_total_minutes: Max total cook+prep time in minutes
        effort_levels:     Acceptable effort levels (e.g. ["easy", "medium"])
        count:             Number of recipes to return (3 for Mode A, 4 for Mode B)
    """
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
# Tool 2: process_recipes — Root Agent interception step (NEW)
# Fixes: allergens structured (gap 1), recipe_filter on every call (gap 2),
#        total_time_estimate structured (gap 3)
# ─────────────────────────────────────────────────────────────────────────────

def process_recipes(
      recipes_json: str,
      allergens: list[str] = None,
      vegan: bool = False,
      vegetarian: bool = False,
  ) -> str:
      """
      Root Agent interception step: apply hard constraint filters to Recipe Finder
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
              "relaxation_note": "Could not parse Recipe Finder output — calling fallback.",
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
# Tool 3: build_grocery_list — Python consolidation (NEW)
# Fixes: LLM arithmetic for grocery quantities (gap 5)
# ─────────────────────────────────────────────────────────────────────────────

def build_grocery_list(recipes_json: str, household_size: int = 4) -> str:
    """
    Build a consolidated grocery list from filtered recipes.
    Deduplicates ingredients across all recipes, scales quantities to household_size,
    and groups by store section. ALWAYS call this after meal_prep_planner.

    Args:
        recipes_json:  JSON string — either a list of recipe dicts, or
                       {"filtered_recipes": [...]} from process_recipes output
        household_size: Number of people to scale quantities for

    Returns JSON list of objects:
        [{"item": str, "quantity": float, "unit": str, "category": str}, ...]
    Sorted by store section then item name.
    Note: pantry staples (salt, pepper, oil, water) are excluded from the list.
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
# Root Agent
# ─────────────────────────────────────────────────────────────────────────────

retry_config=types.HttpRetryOptions(
    attempts=5,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504], # Retry on these HTTP errors
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
        process_recipes,      # interception step: allergen filter + total_time extraction
        build_grocery_list,   # Python grocery consolidation
        ]
    
)

