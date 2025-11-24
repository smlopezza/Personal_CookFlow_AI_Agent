import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
# from google.adk.tools import google_search
from .prompt import GROCERY_PLANNER_INSTRUCTIONS

# Load environment variables from .env
load_dotenv()

# Read the model name from .env
GROCERY_PLANNER_AGENT_MODEL = os.getenv("GROCERY_PLANNER_AGENT_MODEL", "gemini-2.5-flash-lite") 


grocery_planner_agent = Agent(
    name="Grocery_Planner_Agent",
    model=Gemini(model=GROCERY_PLANNER_AGENT_MODEL),
    description="Creates categorized grocery lists from recipes.",
    instruction=GROCERY_PLANNER_INSTRUCTIONS,
    # tools=[google_search],
)
