import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
from .prompt import BATCH_COOKING_INSTRUCTIONS

# Load environment variables from .env
load_dotenv()

# Read the model name from .env
BATCH_COOKING_MODEL = os.getenv("BATCH_COOKING_MODEL", "gemini-2.5-flash-lite") 


batch_cooking_agent = Agent(
    name="Batch_Cooking_Agent",
    model=Gemini(model=BATCH_COOKING_MODEL),
    description="Plan to prepare meals in batches to save time and effort while ensuring variety and nutritional balance.",
    instruction=BATCH_COOKING_INSTRUCTIONS,
    output_key="batch_cooking_plan", 
)
