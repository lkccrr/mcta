"""全局配置：路径、密钥、默认输出格式。全部可用环境变量覆盖。"""
import os
from pathlib import Path


def _resolve_workroot() -> Path:
    """工作根目录：MT_SEEK_HOME 优先，否则用当前目录。

    导出包直接落在这个根目录下（<包名>/），不再套 exports/ 中间层；
    状态库放隐藏的 .mt.seek/，缓存统一放 ~/.cache/mcta/seek/
    （可用 XDG_CACHE_HOME 覆盖根），不污染工作目录。
    """
    env = os.environ.get("MT_SEEK_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd()


def _resolve_cache_dir() -> Path:
    """mt.seek 缓存根目录：XDG_CACHE_HOME/mcta/seek，默认 ~/.cache/mcta/seek。"""
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".cache"
    return (base / "mcta" / "seek").resolve()


WORKROOT = _resolve_workroot()
# 导出包根 = 工作根：每个任务直接生成 <包名>/，内部仍用 EXPORT_ROOT 这个名字
# 复用扫描逻辑（curate/ml 扫 */manifest.csv）。
EXPORT_ROOT = WORKROOT
STATE_DIR = WORKROOT / ".mt.seek"           # 隐藏的内部状态（SQLite 事件库）
STRUCT_CACHE = _resolve_cache_dir()         # 统一缓存（MP 结构、检索、SQS 中间文件）
DB_PATH = STATE_DIR / "mt.seek.db"          # 事件与任务状态（SQLite）；打包时复制进包


def set_home(path) -> Path:
    """运行时切换工作根目录（供 --home 使用）。"""
    global WORKROOT, EXPORT_ROOT, STATE_DIR, DB_PATH, MP_API_KEY
    WORKROOT = Path(path).expanduser().resolve()
    EXPORT_ROOT = WORKROOT
    STATE_DIR = WORKROOT / ".mt.seek"
    # 缓存目录是用户级、跨 --home 复用，set_home 不应改变它。
    DB_PATH = STATE_DIR / "mt.seek.db"
    # MP_API_KEY 在模块导入时解析；切换根目录后必须重读该目录的 mt.seek.conf，
    # 否则 --home 指定的配置永远不会生效。
    MP_API_KEY = os.environ.get("MP_API_KEY", "") or _read_conf_file("MP_API_KEY")
    return WORKROOT

# --- Materials Project ---
CONFIG_FILE = Path.home() / ".config" / "mcta" / "config"


def _read_conf_file(name: str) -> str:
    """从配置文件读一项（KEY=VALUE 行，# 开头为注释）。

    环境变量在 cron、systemd、`ssh 主机 "命令"` 这类非交互场景下不会生效
    （.bashrc 对非交互 shell 直接 return），所以必须有文件兜底。
    """
    paths = []
    override = os.environ.get("MT_SEEK_CONFIG")
    if override:
        paths.append(Path(override).expanduser())
    paths.append(CONFIG_FILE)
    paths.append(WORKROOT / "mt.seek.conf")
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
                    "model": "gpt-4o-mini"},
    "deepseek":    {"base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat"},
    "qwen":        {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model": "qwen-plus"},
    "glm":         {"base_url": "https://open.bigmodel.cn/api/paas/v4",
                    "model": "glm-4-plus"},
    "kimi":        {"base_url": "https://api.moonshot.cn/v1",
                    "model": "moonshot-v1-32k"},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1",
                    "model": "Qwen/Qwen2.5-72B-Instruct"},
    "gemini":      {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "model": "gemini-2.5-flash"},
    "openrouter":  {"base_url": "https://openrouter.ai/api/v1",
                    "model": "openai/gpt-4o-mini"},
    "ollama":      {"base_url": "http://localhost:11434/v1",
                    "model": "qwen3:8b"},
    "vllm":        {"base_url": "http://localhost:8000/v1",
                    "model": "local-model"},
}
LLM_LOCAL_PROVIDERS = {"ollama", "vllm"}   # 本地服务，密钥可随便填
DEFAULT_LLM_PROVIDER = "openai"


def _resolve_llm(provider: str = None) -> dict:
    """按 provider 预设补全 base_url / model / api_key，显式环境变量优先。"""
    name = (provider or os.environ.get("MT_SEEK_PROVIDER") or
            DEFAULT_LLM_PROVIDER).strip().lower()
    if name not in LLM_PROVIDERS:
        name = DEFAULT_LLM_PROVIDER
    preset = LLM_PROVIDERS[name]
    # 所有引擎统一读 MT_SEEK_API_KEY，不设各引擎单独的密钥变量
    key = os.environ.get("MT_SEEK_API_KEY", "")
    if not key and name in LLM_LOCAL_PROVIDERS:
        key = "local"
    return {
        "provider": name,
        "base_url": os.environ.get("MT_SEEK_BASE_URL") or preset["base_url"],
        "model": os.environ.get("MT_SEEK_MODEL") or preset["model"],
        "api_key": key,
    }


_LLM = _resolve_llm()
LLM_PROVIDER = _LLM["provider"]
LLM_API_KEY = _LLM["api_key"]
LLM_BASE_URL = _LLM["base_url"]
LLM_MODEL = _LLM["model"]


def set_llm_provider(provider: str) -> dict:
    """运行时切换 LLM 引擎（供 --provs 使用），返回生效的配置。"""
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
MAX_LLM_TURNS = int(os.environ.get("MT_SEEK_MAX_TURNS", "30"))
MAX_CANDIDATES = int(os.environ.get("MT_SEEK_MAX_CAND", "20"))

# 判断是否需要标注磁性的元素（3d/4d 后过渡金属 + 稀土）
MAGNETIC_ELEMENTS = {
    "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Mo", "W", "Re",
    "Ru", "Rh", "Ir", "Pd", "Pt", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd",
    "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
}


def ensure_dirs() -> None:
    # 状态库留在 .mt.seek/；缓存统一放用户级 ~/.cache/mcta/seek/。
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STRUCT_CACHE.mkdir(parents=True, exist_ok=True)


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

