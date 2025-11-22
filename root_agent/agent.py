import os
from google.adk.agents import Agent
from google.adk.tools import google_search

root_agent_instructions = """You are a useful assistant that helps users find recipes. 
You can use google search to find information and answer questions."""

root_agent = Agent(
    name="Root_agent",
    model='gemini-2.5-flash',
    description=root_agent_instructions,
    instruction=root_agent_instructions,
    tools=[google_search],
)

