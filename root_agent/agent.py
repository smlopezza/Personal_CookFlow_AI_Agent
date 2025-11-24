import os
from google.adk.agents import Agent
from agents.recipe_scout_agent.agent import recipe_scout_agent
from root_agent import prompt




root_agent = Agent(
    name="Root_agent",
    model='gemini-2.5-flash',
    description="A root agent that coordinates sub-agents to assist users in meal planning.",
    instruction=prompt.ROOT_AGENT_INSTRUCTIONS,
    sub_agents=[recipe_scout_agent],
    
)

