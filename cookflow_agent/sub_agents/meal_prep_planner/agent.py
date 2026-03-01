import os
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.genai import types
from .prompt import MEAL_PREP_PLANNER_INSTRUCTIONS
from ...observability import before_model_callback, after_model_callback  


# Load environment variables from .env
load_dotenv()

# Read the model name from .env
MEAL_PREP_PLANNER_MODEL = os.getenv("MEAL_PREP_PLANNER_MODEL", "gemini-2.5-flash") 

retry_config = types.HttpRetryOptions(
      attempts=5,
      exp_base=7,
      initial_delay=1,
      http_status_codes=[429, 500, 503, 504],
  )

meal_prep_planner_agent = Agent(
      name="Meal_Prep_Planner_Agent",
      model=Gemini(model=MEAL_PREP_PLANNER_MODEL, retry_options=retry_config),
      description="Generates the grocery list, batch cooking schedule, and weekly meal distribution from a set of recipes.",
      instruction=MEAL_PREP_PLANNER_INSTRUCTIONS,
      before_model_callback=before_model_callback,
      after_model_callback=after_model_callback,
      output_key="meal_prep_plan",
  )
