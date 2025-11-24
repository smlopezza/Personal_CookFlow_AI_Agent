import os
from dotenv import load_dotenv
from google.adk.agents import Agent
from agents.recipe_finder.agent import recipe_finder_agent
from agents.grocery_planner.agent import grocery_planner_agent
from root_agent import prompt

# Load environment variables from .env file
load_dotenv()

# Read the model name from .env
ROOT_AGENT_MODEL = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")

root_agent = Agent(
    name="Root_agent",
    model=ROOT_AGENT_MODEL,
    description="A root agent that coordinates sub-agents to assist users in meal planning.",
    instruction=prompt.ROOT_AGENT_INSTRUCTIONS,
    sub_agents=[recipe_finder_agent, grocery_planner_agent],
    
)

