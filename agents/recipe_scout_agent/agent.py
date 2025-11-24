import os
from google.adk.models.google_llm import Gemini
from google.adk.agents import Agent
# from google.adk.tools import google_search
from google.genai import types
from . import prompt



retry_config = types.HttpRetryOptions(
    attempts=5,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504],  # Retry on these HTTP errors
)

recipe_scout_agent = Agent(
    name="Recipe_Scout_Agent",
    model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
    description="An agent that finds and suggests recipes based on user preferences and constraints.",
    instruction=prompt.RECIPE_SCOUT_AGENT_INSTRUCTIONS,
    # tools=[google_search]
)
