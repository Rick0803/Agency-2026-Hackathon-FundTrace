# agent/llm_client.py
# Unified LLM client supporting both Anthropic API and AWS Bedrock

import json
import os
from typing import Optional

# Import config helper for Streamlit Cloud compatibility
try:
    from config import get_env
except ImportError:
    # Fallback if config.py is not available
    def get_env(key: str, default: str = "") -> str:
        return os.getenv(key, default)


def get_llm_client():
    """
    Returns the appropriate LLM client based on environment configuration.
    Falls back to None if credentials are missing (graceful degradation).
    """
    use_bedrock = get_env("USE_BEDROCK", "").lower() == "true"
    
    if use_bedrock:
        try:
            import boto3
            return BedrockClient()
        except Exception as e:
            print(f"Bedrock client initialization failed: {e}")
            return None
    else:
        try:
            import anthropic
            api_key = get_env("ANTHROPIC_API_KEY")
            if not api_key:
                return None
            return AnthropicClient(api_key)
        except Exception as e:
            print(f"Anthropic client initialization failed: {e}")
            return None


class BedrockClient:
    """AWS Bedrock client wrapper matching Anthropic API interface."""
    
    def __init__(self):
        import boto3
        self.client = boto3.client(
            service_name="bedrock-runtime",
            region_name=get_env("AWS_DEFAULT_REGION", "us-west-2"),
        )
        self.model_id = get_env("BEDROCK_MODEL", "anthropic.claude-opus-4-5-20251101-v1:0")
    
    def create_message(
        self,
        system: str,
        messages: list,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """
        Call Bedrock with Anthropic Messages API format.
        Returns the text content from the response.
        """
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(request_body),
        )
        
        response_body = json.loads(response["body"].read())
        
        # Extract text from content blocks
        content = response_body.get("content", [])
        if isinstance(content, list) and len(content) > 0:
            return content[0].get("text", "")
        return ""


class AnthropicClient:
    """Anthropic API client wrapper."""
    
    def __init__(self, api_key: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model_id = get_env("CLAUDE_MODEL", "claude-sonnet-4-6")
    
    def create_message(
        self,
        system: str,
        messages: list,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """
        Call Anthropic API with Messages API format.
        Returns the text content from the response.
        """
        response = self.client.messages.create(
            model=self.model_id,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        
        # Extract text from content blocks
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> Optional[str]:
    """
    Convenience function for simple LLM calls.
    Returns None if LLM is unavailable (graceful degradation).
    """
    client = get_llm_client()
    if client is None:
        return None
    
    try:
        return client.create_message(
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=max_tokens,
        )
    except Exception as e:
        print(f"LLM call failed: {e}")
        return None
