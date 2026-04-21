"""LLM 服务"""
from astrbot import logger
from astrbot.core.provider.entities import ProviderType
from ..constants import LOG_PREFIX


class LLMService:
    def __init__(self, context):
        self.context = context
        self._provider_id = None

    def _get_provider_id(self):
        if self._provider_id:
            return self._provider_id
        try:
            provider = self.context.provider_manager.get_using_provider(ProviderType.CHAT_COMPLETION)
            if provider:
                self._provider_id = provider.meta().id
                return self._provider_id
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 获取默认模型失败: {e}")
        return None

    def _get_persona_prompt(self) -> str:
        try:
            persona = self.context.persona_manager.get_default_persona_v3()
            if isinstance(persona, dict):
                return persona.get("prompt", "")
            return getattr(persona, "prompt", "") if hasattr(persona, "prompt") else ""
        except Exception:
            return ""

    async def generate(self, prompt: str, use_persona: bool = True) -> str:
        provider_id = self._get_provider_id()
        if not provider_id:
            logger.error(f"{LOG_PREFIX} 未配置默认LLM Provider")
            return ""
        system_prompt = self._get_persona_prompt() if use_persona else ""
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id, prompt=prompt,
                system_prompt=system_prompt if system_prompt else None,
            )
            return resp.completion_text.strip()
        except Exception as e:
            logger.error(f"{LOG_PREFIX} LLM 生成失败: {e}")
            return ""
