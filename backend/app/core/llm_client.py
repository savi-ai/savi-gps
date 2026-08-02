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
    """AWS Bedrock Runtime client using the Converse API (roles + retries)."""

    def __init__(self, model_id: Optional[str] = None):
        try:
            import boto3
        except ImportError as e:
            raise ImportError("boto3 package not installed. Install with: pip install boto3") from e

        self.model_id = model_id or settings.BEDROCK_MODEL_ID
        if not self.model_id:
            raise ValueError("BEDROCK_MODEL_ID is required when LLM_PROVIDER=bedrock")

        region = (
            settings.BEDROCK_AWS_REGION
            or settings.AWS_REGION
            or "us-east-1"
        )
        access_key = settings.AWS_ACCESS_KEY_ID or settings.BEDROCK_AWS_ACCESS_KEY_ID
        secret_key = settings.AWS_SECRET_ACCESS_KEY or settings.BEDROCK_AWS_SECRET_ACCESS_KEY

        client_kwargs: Dict[str, Any] = {"service_name": "bedrock-runtime", "region_name": region}
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key
        # else: default credential chain (env profile, IRSA, instance role)

        self.region = region
        self.bedrock_runtime = boto3.client(**client_kwargs)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(messages, **kwargs)

    def _split_messages(
        self, messages: List[Dict[str, str]]
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        system_parts: List[str] = []
        converse_messages: List[Dict[str, Any]] = []
        for msg in messages:
            role = (msg.get("role") or "user").lower()
            content = msg.get("content") or ""
            if role == "system":
                system_parts.append(content)
                continue
            if role not in ("user", "assistant"):
                role = "user"
            converse_messages.append(
                {"role": role, "content": [{"text": content}]}
            )
        if not converse_messages:
            converse_messages = [{"role": "user", "content": [{"text": ""}]}]
        # Converse requires alternating roles starting with user
        if converse_messages[0]["role"] != "user":
            converse_messages.insert(0, {"role": "user", "content": [{"text": "(context)"}]})
        system = "\n\n".join(system_parts) if system_parts else None
        return system, converse_messages

    def _invoke_converse(
        self,
        system: Optional[str],
        converse_messages: List[Dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        kwargs: Dict[str, Any] = {
            "modelId": self.model_id,
            "messages": converse_messages,
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            kwargs["system"] = [{"text": system}]

        response = self.bedrock_runtime.converse(**kwargs)
        parts = response.get("output", {}).get("message", {}).get("content") or []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
        if not texts:
            raise RuntimeError("Bedrock Converse returned empty content")
        return "".join(texts)

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        import asyncio

        from app.core.llm_retry import with_llm_retries

        system, converse_messages = self._split_messages(messages)
        max_tokens = int(kwargs.get("max_tokens", 8192))
        temperature = float(kwargs.get("temperature", 0.3))

        async def _once() -> str:
            return await asyncio.to_thread(
                self._invoke_converse,
                system,
                converse_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        text = await with_llm_retries(_once, label="bedrock")
        return text.replace("```json", "").replace("```", "")


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
        from app.core.llm_retry import with_llm_retries

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
                claude_messages.append({"role": "user", "content": content})

        async def _once() -> str:
            response = await self.client.messages.create(
                model=kwargs.get("model", self.model),
                max_tokens=kwargs.get("max_tokens", 8192),
                system=system_message,
                messages=claude_messages,
                temperature=kwargs.get("temperature", 0.7),
            )
            response_text = response.content[0].text
            return response_text.replace("```json", "").replace("```", "")

        return await with_llm_retries(_once, label="claude")


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


def get_llm_client(provider: Optional[str] = None, model_id: Optional[str] = None) -> LLMClient:
    """Factory function to get appropriate LLM client."""
    resolved = (provider or settings.LLM_PROVIDER or "claude").lower()

    if resolved == "openai":
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set")
        return OpenAIClient()
    if resolved in {"claude", "anthropic"}:
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set")
        return ClaudeClient()
    if resolved == "bedrock":
        return BedrockClient(model_id=model_id)
    if resolved == "ollama":
        return OllamaClient(model=model_id or "llama3.1")
    logger.warning("Unknown LLM_PROVIDER=%s; falling back to Ollama", resolved)
    return OllamaClient()
