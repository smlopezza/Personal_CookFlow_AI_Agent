import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
from .prompt import MEAL_PREP_PLANNER_INSTRUCTIONS
from ...observability import before_model_callback, after_model_callback

load_dotenv()

MEAL_PREP_PLANNER_MODEL = os.getenv("MEAL_PREP_PLANNER_MODEL", "gemini-2.5-flash")

meal_prep_planner_agent = Agent(
    name="Meal_Prep_Planner_Agent",
    model=Gemini(model=MEAL_PREP_PLANNER_MODEL),
    description=(
        "Generates a consolidated grocery list, a cooking schedule, and a weekly meal plan "
        "from a set of approved recipes. Adapts output based on cooking_frequency: "
        "daily (per-night guide, 5 recipes), few times a week (two sessions), or batch (single session)."
    ),
    instruction=MEAL_PREP_PLANNER_INSTRUCTIONS,
    before_model_callback=before_model_callback,
    after_model_callback=after_model_callback,
    output_key="meal_plan",
)
