import os
from dotenv import load_dotenv
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
from .prompt import USER_PREFERENCES_INSTRUCTIONS

# Load environment variables from .env
load_dotenv()

# Read the model name from .env
USER_PREFERENCES_MODEL = os.getenv("USER_PREFERENCES_MODEL", "gemini-2.5-flash-lite") 


user_preferences_agent = Agent(
    name="User_Preferences_Agent",
    model=Gemini(model=USER_PREFERENCES_MODEL),
    description="Ask the user about their dietary preferences, restrictions, and favorite cuisines to tailor meal plans accordingly.",
    instruction=USER_PREFERENCES_INSTRUCTIONS,
)
