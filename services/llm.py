"""LLM 服务"""
import time
from astrbot import logger
from astrbot.core.provider.entities import ProviderType
from ..constants import LOG_PREFIX

# 全局断路器：记录 LLM 最近失败时间，5分钟内不回退到模板
_llm_failure_time = 0.0
_LLM_CIRCUIT_BREAKER_TTL = 300  # 5分钟


class LLMService:
    def __init__(self, context):
        self.context = context
        self._provider_id = None
        self._fallback_template = ""

    def set_fallback_template(self, template: str):
        """设置 LLM 失败时的 fallback 模板文案"""
        self._fallback_template = template

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
        return await self.generate_llm_message(
            prompt=prompt,
            system_prompt=self._get_persona_prompt() if use_persona else None,
            temperature=0.7,
        )

    async def generate_llm_message(
        self, prompt: str, system_prompt: str | None = None, temperature: float = 0.7
    ) -> str:
        global _llm_failure_time
        # 兼容旧接口参数；当前 AstrBot llm_generate 接口未暴露 temperature
        if not self.context:
            return self._fallback_template if self._fallback_template else ""
        provider_id = self._get_provider_id()
        if not provider_id:
            logger.error(f"{LOG_PREFIX} 未配置默认LLM Provider")
            return self._fallback_template if self._fallback_template else ""
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id, prompt=prompt,
                system_prompt=system_prompt if system_prompt else None,
            )
            _llm_failure_time = 0.0  # 成功，重置断路器
            return resp.completion_text.strip()
        except Exception as e:
            logger.error(f"{LOG_PREFIX} LLM 生成失败: {e}")
            _llm_failure_time = time.time()
            # 有 fallback 模板时回退
            if self._fallback_template:
                logger.warning(f"{LOG_PREFIX} LLM 失败，使用 fallback 模板")
                return self._fallback_template
            return ""
