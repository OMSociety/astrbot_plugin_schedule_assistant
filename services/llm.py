"""LLM 服务 - 封装 AstrBot LLM 接口，支持人设和对话历史"""

import time

from astrbot.api import logger
from astrbot.core.provider.entities import ProviderType

from ..constants import LOG_PREFIX

# 全局断路器：记录 LLM 最近失败时间，5分钟内不回退到模板
_llm_failure_time = 0.0
_LLM_CIRCUIT_BREAKER_TTL = 300  # 5分钟


class LLMService:
    """LLM 服务，封装 AstrBot 的 llm_generate 接口"""

    def __init__(self, context, config: dict = None):
        self.context = context
        self.config = config or {}
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
            provider = self.context.provider_manager.get_using_provider(
                ProviderType.CHAT_COMPLETION
            )
            if provider:
                self._provider_id = provider.meta().id
                return self._provider_id
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 获取默认模型失败: {e}")
        return None

    def _normalize_umo(self, umo: str | None) -> str | None:
        """将纯 QQ 号转换为合法的 MessageSession 格式。

        persona_manager.get_default_persona_v3 内部会调用
        MessageSession.from_str() 验证格式，纯数字 QQ 号会
        导致 ValueError 从而回退到默认人格。
        """
        if not umo or ":" in umo:
            return umo
        # 获取主平台 ID
        platform = "aiocqhttp"
        try:
            for p in self.context.platform_manager.platform_insts:
                pid = p.meta().id
                if pid:
                    platform = str(pid)
                    break
        except Exception:
            pass
        normalized = f"{platform}:FriendMessage:{umo}"
        logger.debug(f"{LOG_PREFIX} 规范化 umo: {umo} → {normalized}")
        return normalized

    def _get_persona_prompt(self, umo: str = None) -> str:
        """获取人设 prompt，按优先级：配置指定 > 当前会话 > 全局默认"""
        umo = self._normalize_umo(umo)
        try:
            # 1. 从插件配置中读取指定的人格ID
            persona_id = self.config.get("persona_id", "")
            if persona_id:
                logger.debug(f"{LOG_PREFIX} 使用插件配置的人格: {persona_id}")
                persona = self.context.persona_manager.get_persona(persona_id)
                if persona:
                    if isinstance(persona, dict):
                        return persona.get("prompt", "")
                    return getattr(persona, "prompt", "") if hasattr(persona, "prompt") else ""
                else:
                    logger.warning(f"{LOG_PREFIX} 配置的人格 '{persona_id}' 不存在，回退到会话人格")
            
            # 2. 尝试获取当前会话的人格（如果提供了umo）
            if umo:
                logger.debug(f"{LOG_PREFIX} 尝试获取会话 {umo} 的当前人格")
                persona = self.context.persona_manager.get_default_persona_v3(umo=umo)
                if persona:
                    if isinstance(persona, dict):
                        return persona.get("prompt", "")
                    return getattr(persona, "prompt", "") if hasattr(persona, "prompt") else ""
            
            # 3. 回退到全局默认人格
            logger.debug(f"{LOG_PREFIX} 使用全局默认人格")
            persona = self.context.persona_manager.get_default_persona_v3()
            if isinstance(persona, dict):
                return persona.get("prompt", "")
            return getattr(persona, "prompt", "") if hasattr(persona, "prompt") else ""
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 获取人格失败: {e}")
            return ""

    async def generate(
        self, prompt: str, use_persona: bool = True, history: str = "", umo: str = None
    ) -> str:
        """生成 LLM 回复

        Args:
            prompt: 用户输入的 prompt
            use_persona: 是否使用人设 prompt
            history: 近期对话历史，会拼接到 system_prompt 末尾
            umo: 统一会话标识，用于获取当前会话的人格

        Returns:
            LLM 生成的文本
        """
        system_prompt = self._get_persona_prompt(umo=umo) if use_persona else ""
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
                chat_provider_id=provider_id,
                prompt=prompt,
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
