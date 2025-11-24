import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
from .prompt import MEAL_DISTRIBUTION_INSTRUCTIONS

# Load environment variables from .env
load_dotenv()

# Read the model name from .env
MEAL_DISTRIBUTION_MODEL = os.getenv("MEAL_DISTRIBUTION_MODEL", "gemini-2.5-flash-lite") 


meal_distribution_agent = Agent(
    name="Meal_Distribution_Agent",
    model=Gemini(model=MEAL_DISTRIBUTION_MODEL),
    description="Plan and distribute meals throughout the week based on user preferences and dietary restrictions.",
    instruction=MEAL_DISTRIBUTION_INSTRUCTIONS,
)
