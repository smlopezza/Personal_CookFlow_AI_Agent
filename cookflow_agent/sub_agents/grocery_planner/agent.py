import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
from google.genai import types
from .prompt import GROCERY_PLANNER_INSTRUCTIONS

# Load environment variables from .env
load_dotenv()

# Read the model name from .env
GROCERY_PLANNER_AGENT_MODEL = os.getenv("GROCERY_PLANNER_AGENT_MODEL", "gemini-2.5-flash-lite") 

retry_config=types.HttpRetryOptions(
    attempts=5,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504], # Retry on these HTTP errors
)


grocery_planner_agent = Agent(
    name="Grocery_Planner_Agent",
    model=Gemini(model=GROCERY_PLANNER_AGENT_MODEL, retry_options=retry_config),
    description="Creates categorized grocery lists from recipes.",
    instruction=GROCERY_PLANNER_INSTRUCTIONS,
    output_key="grocery_list",
)
