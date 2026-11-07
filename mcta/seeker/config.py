"""全局配置：路径、密钥、默认输出格式。全部可用环境变量覆盖。"""
import os
from pathlib import Path


def _resolve_workroot() -> Path:
    """工作根目录：MT_SEEKER_HOME 优先，否则用当前目录。

    默认取当前目录而不是包所在目录 —— 安装成命令行工具后，包位于
    site-packages，绝不能把 exports/cache 写进那里。
    """
    env = os.environ.get("MT_SEEKER_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd()


WORKROOT = _resolve_workroot()
EXPORT_ROOT = WORKROOT / "exports"          # 每次任务一个子目录，可直接 scp 到服务器
STRUCT_CACHE = WORKROOT / "cache"           # MP 结构原始缓存（json）
DB_PATH = WORKROOT / "mt.seeker.db"          # 事件与任务状态（SQLite）


def set_home(path) -> Path:
    """运行时切换工作根目录（供 --home 使用）。"""
    global WORKROOT, EXPORT_ROOT, STRUCT_CACHE, DB_PATH
    WORKROOT = Path(path).expanduser().resolve()
    EXPORT_ROOT = WORKROOT / "exports"
    STRUCT_CACHE = WORKROOT / "cache"
    DB_PATH = WORKROOT / "mt.seeker.db"
    return WORKROOT

# --- Materials Project ---
CONFIG_FILE = Path.home() / ".config" / "mcta" / "config"


def _read_conf_file(name: str) -> str:
    """从配置文件读一项（KEY=VALUE 行，# 开头为注释）。

    环境变量在 cron、systemd、`ssh 主机 "命令"` 这类非交互场景下不会生效
    （.bashrc 对非交互 shell 直接 return），所以必须有文件兜底。
    """
    paths = []
    override = os.environ.get("MT_SEEKER_CONFIG")
    if override:
        paths.append(Path(override).expanduser())
    paths.append(CONFIG_FILE)
    paths.append(WORKROOT / "mt.seeker.conf")
    for p in paths:
        try:
            if not p.is_file():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line[0] in "#;" or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip("'\"")
        except OSError:
            continue
    return ""


MP_API_KEY = os.environ.get("MP_API_KEY", "") or _read_conf_file("MP_API_KEY")

# --- LLM（可选，仅自然语言模式需要）---
# 所有引擎统一走 OpenAI 兼容协议（/chat/completions），要求模型支持 function calling。
LLM_PROVIDERS = {
    "openai":      {"base_url": "https://api.openai.com/v1",
                    "model": "gpt-4o-mini", "key_env": "OPENAI_API_KEY"},
    "deepseek":    {"base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat", "key_env": "DEEPSEEK_API_KEY"},
    "qwen":        {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model": "qwen-plus", "key_env": "DASHSCOPE_API_KEY"},
    "glm":         {"base_url": "https://open.bigmodel.cn/api/paas/v4",
                    "model": "glm-4-plus", "key_env": "ZHIPU_API_KEY"},
    "kimi":        {"base_url": "https://api.moonshot.cn/v1",
                    "model": "moonshot-v1-32k", "key_env": "MOONSHOT_API_KEY"},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1",
                    "model": "Qwen/Qwen2.5-72B-Instruct", "key_env": "SILICONFLOW_API_KEY"},
    "gemini":      {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "model": "gemini-2.5-flash", "key_env": "GEMINI_API_KEY"},
    "openrouter":  {"base_url": "https://openrouter.ai/api/v1",
                    "model": "openai/gpt-4o-mini", "key_env": "OPENROUTER_API_KEY"},
    "ollama":      {"base_url": "http://localhost:11434/v1",
                    "model": "qwen3:8b", "key_env": ""},
    "vllm":        {"base_url": "http://localhost:8000/v1",
                    "model": "local-model", "key_env": ""},
}
LLM_LOCAL_PROVIDERS = {"ollama", "vllm"}   # 本地服务，密钥可随便填
DEFAULT_LLM_PROVIDER = "openai"


def _resolve_llm(provider: str = None) -> dict:
    """按 provider 预设补全 base_url / model / api_key，显式环境变量优先。"""
    name = (provider or os.environ.get("MT_SEEKER_PROVIDER") or
            DEFAULT_LLM_PROVIDER).strip().lower()
    if name not in LLM_PROVIDERS:
        name = DEFAULT_LLM_PROVIDER
    preset = LLM_PROVIDERS[name]
    key = os.environ.get("MT_SEEKER_API_KEY", "")
    if not key and preset["key_env"]:
        key = os.environ.get(preset["key_env"], "")
    if not key and name in LLM_LOCAL_PROVIDERS:
        key = "local"
    return {
        "provider": name,
        "base_url": os.environ.get("MT_SEEKER_BASE_URL") or preset["base_url"],
        "model": os.environ.get("MT_SEEKER_MODEL") or preset["model"],
        "api_key": key,
    }


_LLM = _resolve_llm()
LLM_PROVIDER = _LLM["provider"]
LLM_API_KEY = _LLM["api_key"]
LLM_BASE_URL = _LLM["base_url"]
LLM_MODEL = _LLM["model"]


def set_llm_provider(provider: str) -> dict:
    """运行时切换 LLM 引擎（供 --provider 使用），返回生效的配置。"""
    global LLM_PROVIDER, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
    cfg = _resolve_llm(provider)
    LLM_PROVIDER = cfg["provider"]
    LLM_API_KEY = cfg["api_key"]
    LLM_BASE_URL = cfg["base_url"]
    LLM_MODEL = cfg["model"]
    return cfg

# --- 输出 ---
DEFAULT_FORMATS = ("cif", "poscar", "json")   # 结构文件格式
STRUCT_FORMATS = ("cif", "poscar", "vasp", "json", "xyz")   # 允许的格式（vasp 同 poscar）
MAX_LLM_TURNS = int(os.environ.get("MT_SEEKER_MAX_TURNS", "30"))
MAX_CANDIDATES = int(os.environ.get("MT_SEEKER_MAX_CAND", "20"))

# 判断是否需要标注磁性的元素（3d/4d 后过渡金属 + 稀土）
MAGNETIC_ELEMENTS = {
    "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Mo", "W", "Re",
    "Ru", "Rh", "Ir", "Pd", "Pt", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd",
    "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
}


def ensure_dirs() -> None:
    for p in (EXPORT_ROOT, STRUCT_CACHE):
        p.mkdir(parents=True, exist_ok=True)


def export_dir_for(name: str) -> Path:
    ensure_dirs()
    return EXPORT_ROOT / name


# --- 赝势路径（mt.sh/po.sh 用）---
# 优先级：PBE_PATH > LDA_PATH > GGA_PATH
# 每个路径都先查环境变量，再从 CONFIG_FILE (~/.config/mcta/config) 里兜底
_PSP_KEYS = ("PBE_PATH", "LDA_PATH", "GGA_PATH")


def get_pseudopotential_path() -> Path | None:
    """按 PBE_PATH > LDA_PATH > GGA_PATH 优先级返回赝势目录。

    环境变量优先，其次从 CONFIG_FILE (~/.config/mcta/config) 读，
    都没有或路径不存在时返回 None。
    """
    for key in _PSP_KEYS:
        val = os.environ.get(key) or _read_conf_file(key)
        if val:
            p = Path(val).expanduser()
            if p.is_dir():
                return p
    return None


# mt.sh 脚本里用 pot_path，这里提供一个可用的路径（如果有）
pot_path = str(get_pseudopotential_path()) if get_pseudopotential_path() else ""
