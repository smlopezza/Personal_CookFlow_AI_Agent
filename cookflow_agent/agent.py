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
from .data.recipe_filter import filter_recipes, relaxation_message
from .data.error_handling import load_recipe_db_safe
import json

# Load environment variables from .env file
load_dotenv()

_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "recipes.json")
load_recipe_db_safe(_DB_PATH)  # startup check

# Read the model name from .env
ROOT_AGENT_MODEL = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")

def recipe_db_fallback(
      allergens: list[str] = None,
      cuisines: list[str] = None,
      kid_friendly: bool = False,
      vegan: bool = False,
      vegetarian: bool = False,
      batch_cook: bool = False,
      max_total_minutes: int = None,
      effort_levels: list[str] = None,
      count: int = 4,
  ) -> str:
      """
      Fallback tool: filter the curated recipe database when Recipe Finder
      returns no results. Call this when recipe_finder returns empty recipes.
      Returns JSON with 'recipes' list and 'relaxation_note'.
      """
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
        ]
    
)

