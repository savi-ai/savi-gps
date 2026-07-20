"""LLM client abstraction"""
from typing import Optional, List, Dict, Any
from abc import ABC, abstractmethod
from app.core.config import settings
from app.core.logger import logger
import os


class LLMClient(ABC):
    """Abstract base class for LLM clients"""
    
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        """Generate text from prompt"""
        pass
    
    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Chat completion"""
        pass


class OpenAIClient(LLMClient):
    """OpenAI LLM client"""
    
    def __init__(self):
        try:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            self.model = "gpt-4"
        except ImportError:
            raise ImportError("openai package not installed. Install with: pip install openai")
    
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages, **kwargs)
    
    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        response = await self.client.chat.completions.create(
            model=kwargs.get("model", self.model),
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 4000)
        )
        return response.choices[0].message.content


class BedrockClient(LLMClient):
    """AWS Bedrock LLM client"""
    
    def __init__(self):
        try:
            import boto3
            self.bedrock_runtime = boto3.client(
                'bedrock-runtime',
                region_name=settings.AWS_REGION
            )
            self.model_id = settings.BEDROCK_MODEL_ID
        except ImportError:
            raise ImportError("boto3 package not installed. Install with: pip install boto3")
    
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "user", "content": f"{system_prompt}\n\n{prompt}"})
        else:
            messages.append({"role": "user", "content": prompt})
        return await self.chat(messages, **kwargs)
    
    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        import json
        import asyncio
        
        # Convert messages to Bedrock format
        prompt = "\n".join([msg["content"] for msg in messages])
        
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": kwargs.get("max_tokens", 4000),
            "messages": [
                {"role": "user", "content": prompt}
            ]
        })
        
        response = self.bedrock_runtime.invoke_model(
            modelId=self.model_id,
            body=body
        )
        
        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']


class ClaudeClient(LLMClient):
    """Anthropic Claude LLM client"""
    
    def __init__(self):
        try:
            from anthropic import AsyncAnthropic
            if not settings.ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY not set")
            self.client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            self.model = settings.ANTHROPIC_MODEL
        except ImportError:
            raise ImportError("anthropic package not installed. Install with: pip install anthropic")
    
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        """Generate text from prompt using Claude"""
        messages = [{"role": "user", "content": prompt}]
        
        response = await self.client.messages.create(
            model=kwargs.get("model", self.model),
            max_tokens=kwargs.get("max_tokens", 8192),
            system=system_prompt if system_prompt else None,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7)
        )
        
        # Claude returns a list of text blocks
        response_text = response.content[0].text
        response_text = response_text.replace("```json", "").replace("```", "")
        return response_text
    
    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Chat completion using Claude"""
        # Convert messages to Claude format
        # Claude uses "user" and "assistant" roles, and supports system messages
        claude_messages = []
        system_message = None
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                system_message = content
            elif role in ["user", "assistant"]:
                claude_messages.append({"role": role, "content": content})
            else:
                # Convert other roles to "user"
                claude_messages.append({"role": "user", "content": content})
        
        response = await self.client.messages.create(
            model=kwargs.get("model", self.model),
            max_tokens=kwargs.get("max_tokens", 8192),
            system=system_message,
            messages=claude_messages,
            temperature=kwargs.get("temperature", 0.7)
        )
        
        response_text = response.content[0].text
        response_text = response_text.replace("```json", "").replace("```", "")
        return response_text


class OllamaClient(LLMClient):
    """Ollama LLM client (for local development)"""
    
    def __init__(self, model: str = "llama3.1"):
        self.model = model
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        # Try to use langchain if available, otherwise use direct HTTP calls
        try:
            from langchain_community.llms import Ollama
            self.llm = Ollama(model=model, base_url=self.base_url)
            self.use_langchain = True
        except ImportError:
            self.use_langchain = False
            logger.warning("langchain-community not available, using direct HTTP calls to Ollama")
    
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        if self.use_langchain:
            return await self._generate_with_langchain(prompt, system_prompt, **kwargs)
        else:
            return await self._generate_with_http(prompt, system_prompt, **kwargs)
    
    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        if self.use_langchain:
            return await self._chat_with_langchain(messages, **kwargs)
        else:
            return await self._chat_with_http(messages, **kwargs)
    
    async def _generate_with_langchain(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        """Generate using langchain (if available)"""
        # Try new import path first, fallback to old path
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError:
            try:
                from langchain.schema import HumanMessage, SystemMessage
            except ImportError:
                # If both fail, use a simple string-based approach
                full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
                response = await self.llm.ainvoke(full_prompt)
                return str(response)
        
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))
        
        response = await self.llm.ainvoke(messages)
        print(f"Response: {str(response)}")
        return str(response)
    
    async def _chat_with_langchain(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Chat using langchain (if available)"""
        # Try new import path first, fallback to old path
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError:
            try:
                from langchain.schema import HumanMessage, SystemMessage
            except ImportError:
                # If both fail, use a simple string-based approach
                prompt = "\n".join([f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in messages])
                response = await self.llm.ainvoke(prompt)
                return str(response)
        
        langchain_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                langchain_messages.append(SystemMessage(content=content))
            else:
                langchain_messages.append(HumanMessage(content=content))
        
        response = await self.llm.ainvoke(langchain_messages)
        return str(response)
    
    async def _generate_with_http(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        """Generate using direct HTTP calls to Ollama"""
        import aiohttp
        import json
        
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"Response: {data.get('response', '')}")
                    return data.get("response", "")
                else:
                    raise Exception(f"Ollama API error: {response.status}")
    
    async def _chat_with_http(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Chat using direct HTTP calls to Ollama"""
        import aiohttp
        import json
        
        # Convert messages to Ollama format
        ollama_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            ollama_messages.append({"role": role, "content": content})
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": ollama_messages,
                    "stream": False
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("message", {}).get("content", "")
                else:
                    raise Exception(f"Ollama API error: {response.status}")


def get_llm_client() -> LLMClient:
    """Factory function to get appropriate LLM client"""
    provider = settings.LLM_PROVIDER.lower()
    
    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set")
        return OpenAIClient()
    elif provider == "claude" or provider == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set")
        return ClaudeClient()
    elif provider == "bedrock":
        return BedrockClient()
    elif provider == "ollama":
        return OllamaClient()
    else:
        # Default to Ollama for development
        return OllamaClient()

