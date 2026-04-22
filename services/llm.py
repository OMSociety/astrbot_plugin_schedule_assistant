"""LLM 服务 - 封装 AstrBot LLM 接口，支持人设和对话历史"""
import time
from astrbot import logger
from astrbot.core.provider.entities import ProviderType
from ..constants import LOG_PREFIX

# 全局断路器：记录 LLM 最近失败时间，5分钟内不回退到模板
_llm_failure_time = 0.0
_LLM_CIRCUIT_BREAKER_TTL = 300  # 5分钟


class LLMService:
    """LLM 服务，封装 AstrBot 的 llm_generate 接口"""

    def __init__(self, context):
        self.context = context
        self._provider_id = None
        self._fallback_template = ""

    def set_fallback_template(self, template: str):
        """设置 LLM 失败时的 fallback 模板文案"""
        self._fallback_template = template

    def _get_provider_id(self):
        """获取默认 Provider ID"""
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
        """获取默认人设 prompt"""
        try:
            persona = self.context.persona_manager.get_default_persona_v3()
            if isinstance(persona, dict):
                return persona.get("prompt", "")
            return getattr(persona, "prompt", "") if hasattr(persona, "prompt") else ""
        except Exception:
            return ""

    async def generate(self, prompt: str, use_persona: bool = True, history: str = "") -> str:
        """生成 LLM 回复

        Args:
            prompt: 用户输入的 prompt
            use_persona: 是否使用人设 prompt
            history: 近期对话历史，会拼接到 system_prompt 末尾

        Returns:
            LLM 生成的文本
        """
        system_prompt = self._get_persona_prompt() if use_persona else ""
        # 追加对话历史，让 AI 有上下文
        if history:
            history_section = "\n\n【近期对话】\n" + history
            system_prompt = (system_prompt or "") + history_section
        return await self.generate_llm_message(
            prompt=prompt,
            system_prompt=system_prompt if system_prompt else None,
        )

    async def generate_llm_message(
        self, prompt: str, system_prompt: str = None, temperature: float = 0.7
    ) -> str:
        """直接调用 LLM 接口

        Args:
            prompt: 用户输入
            system_prompt: 系统提示词
            temperature: 温度参数（当前 AstrBot 未公开此参数）

        Returns:
            LLM 生成的文本
        """
        global _llm_failure_time
        if not self.context:
            return self._fallback_template if self._fallback_template else ""
        provider_id = self._get_provider_id()
        if not provider_id:
            logger.error(f"{LOG_PREFIX} 未配置默认LLM Provider")
            return self._fallback_template if self._fallback_template else ""
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id, prompt=prompt,
                system_prompt=system_prompt,
            )
            _llm_failure_time = 0.0  # 成功，重置断路器
            return resp.completion_text.strip()
        except Exception as e:
            logger.error(f"{LOG_PREFIX} LLM 生成失败: {e}")
            _llm_failure_time = time.time()
            if self._fallback_template:
                logger.warning(f"{LOG_PREFIX} LLM 失败，使用 fallback 模板")
                return self._fallback_template
            return ""
