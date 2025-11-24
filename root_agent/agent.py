import os
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools import AgentTool
from google.adk.models.google_llm import Gemini
from agents.user_preferences.agent import user_preferences_agent
from agents.recipe_finder.agent import recipe_finder_agent
from agents.grocery_planner.agent import grocery_planner_agent
from agents.batch_cooking.agent import batch_cooking_agent
from agents.meal_distribution.agent import meal_distribution_agent
from root_agent.prompt import ROOT_AGENT_INSTRUCTIONS

# Load environment variables from .env file
load_dotenv()

# Read the model name from .env
ROOT_AGENT_MODEL = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")

root_agent = Agent(
    name="Root_agent",
    model=Gemini(model=ROOT_AGENT_MODEL),
    description="A root agent that coordinates sub-agents to assist users in meal planning.",
    instruction=ROOT_AGENT_INSTRUCTIONS,
    tools=[
        AgentTool(user_preferences_agent),
        AgentTool(recipe_finder_agent),
        AgentTool(grocery_planner_agent),
        AgentTool(batch_cooking_agent),
        AgentTool(meal_distribution_agent)
        ]
    
)

