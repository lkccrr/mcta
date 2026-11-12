"""LLM 薄封装：任意 OpenAI 兼容端点。

引擎由 config.LLM_PROVIDERS 预设（openai / deepseek / qwen / glm / kimi /
siliconflow / gemini / openrouter / ollama / vllm），用 --provs 或
MT_SEEKER_PROVIDER 切换；MT_SEEKER_BASE_URL / _MODEL 可单独覆盖。
未配置密钥时返回 None，回落到规则流水线。
"""
from mcta.seeker import config

# 最近一次 get_client 失败的真实原因（'no_key' / 'no_package' / 异常文本），
# 供 CLI 给出准确提示 —— "没装 openai" 与 "没配密钥" 是两回事。
LAST_ERROR = ""


def get_client(provider: str = None):
    """provider 给定时先切换引擎，再按生效配置建客户端；无密钥返回 None。"""
    global LAST_ERROR
    LAST_ERROR = ""
    if provider:
        config.set_llm_provider(provider)
    if not config.LLM_API_KEY:
        LAST_ERROR = "no_key"
        return None
    try:
        from openai import OpenAI
    except ImportError:
        LAST_ERROR = "no_package"
        return None
    try:
        return OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    except Exception as e:  # noqa: BLE001
        LAST_ERROR = f"{type(e).__name__}: {e}"
        return None


def describe() -> dict:
    """当前生效的引擎配置（不含密钥），用于报错提示与自检输出。"""
    return {"provider": config.LLM_PROVIDER,
            "base_url": config.LLM_BASE_URL,
            "model": config.LLM_MODEL,
            "has_key": bool(config.LLM_API_KEY),
            "last_error": LAST_ERROR}
