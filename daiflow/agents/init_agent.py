"""Init agent: project knowledge generation (non-chattable).

Init agents are orchestrated by project_service.run_init() which handles
layer sequencing and Cody client creation directly. This config exists
to complete the registry but build_prompt/on_complete are handled
by the project_service layer orchestration.
"""

from daiflow.agents import AgentConfig, register_agent


class InitAgent(AgentConfig):
    agent_type = "init"
    chattable = False

    async def build_prompt(self, ctx):
        # Init prompts are built by project_service with knowledge-type-specific templates
        raise NotImplementedError("Init agent prompts are built by project_service")


register_agent(InitAgent())
