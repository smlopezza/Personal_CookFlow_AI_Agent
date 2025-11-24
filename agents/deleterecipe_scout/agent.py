import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
from google.adk.tools import google_search
from .prompt import RECIPE_SCOUT_AGENT_INSTRUCTIONS

# Load environment variables from .env
load_dotenv()

# Read the model name from .env
RECIPE_SCOUT_AGENT_MODEL = os.getenv("RECIPE_SCOUT_AGENT_MODEL", "gemini-2.5-flash-lite") 


recipe_scout_agent = Agent(
    name="Recipe_Scout_Agent",
    model=Gemini(model=RECIPE_SCOUT_AGENT_MODEL),
    description="Scouts for recipes based on given criteria.",
    instruction=RECIPE_SCOUT_AGENT_INSTRUCTIONS,
    tools=[google_search],
)
