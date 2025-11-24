import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
# from google.adk.tools import google_search

# from google.genai import types
from .prompt import RECIPE_SCOUT_AGENT_INSTRUCTIONS


# Load environment variables from .env
load_dotenv()

# Read the model name from .env
RECIPE_SCOUT_AGENT_MODEL = os.getenv("RECIPE_SCOUT_AGENT_MODEL", "gemini-2.5-flash-lite") 

# retry_config = types.HttpRetryOptions(
#     attempts=5,  # Maximum retry attempts
#     exp_base=7,  # Delay multiplier
#     initial_delay=1,
#     http_status_codes=[429, 500, 503, 504],  # Retry on these HTTP errors
# )

recipe_scout_agent = Agent(
    name="Recipe_Scout_Agent",
    model=Gemini(model=RECIPE_SCOUT_AGENT_MODEL),#, retry_options=retry_config),
    description="An agent that finds and suggests recipes based on user preferences and constraints.",
    instruction=RECIPE_SCOUT_AGENT_INSTRUCTIONS,
    # tools=[google_search],
)
