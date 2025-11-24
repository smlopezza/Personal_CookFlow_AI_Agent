import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
# from google.adk.tools import google_search
from .prompt import RECIPE_FINDER_AGENT_INSTRUCTIONS

# Load environment variables from .env
load_dotenv()

# Model override via .env
RECIPE_FINDER_AGENT_MODEL = os.getenv("RECIPE_FINDER_AGENT_MODEL", "gemini-2.5-flash-lite")


recipe_finder_agent = Agent(
    name="Recipe_Finder_Agent",
    model=Gemini(model=RECIPE_FINDER_AGENT_MODEL),
    description="Finds recipes based on user constraints.",
    instruction=RECIPE_FINDER_AGENT_INSTRUCTIONS,
    # tools=[google_search],
)
