import os

from strands.models.bedrock import BedrockModel


def load_model() -> BedrockModel:
    """Get the Bedrock model client using IAM credentials from the runtime environment."""
    return BedrockModel(model_id=os.getenv("ENTRY_AGENT_MODEL_ID", "amazon.nova-micro-v1:0"))
