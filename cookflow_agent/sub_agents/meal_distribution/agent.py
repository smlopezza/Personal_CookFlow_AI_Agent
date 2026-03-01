import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
from .prompt import MEAL_DISTRIBUTION_INSTRUCTIONS
from ...observability import before_model_callback, after_model_callback 


# Load environment variables from .env
load_dotenv()

# Read the model name from .env
MEAL_DISTRIBUTION_MODEL = os.getenv("MEAL_DISTRIBUTION_MODEL", "gemini-2.5-flash-lite") 


meal_distribution_agent = Agent(
    name="Meal_Distribution_Agent",
    model=Gemini(model=MEAL_DISTRIBUTION_MODEL),
    description="Plan and distribute meals throughout the week based on user preferences and dietary restrictions.",
    instruction=MEAL_DISTRIBUTION_INSTRUCTIONS,
    before_model_callback=before_model_callback,   
    after_model_callback=after_model_callback,
    output_key="meal_distribution", 
)
