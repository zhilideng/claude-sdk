"""配置段模型集合（配置 schema 层）。

本包是配置 schema 层，与 ``app/core/config.py`` 的「加载机制」分离：
本包只声明有哪些配置段、字段、类型与默认值。所有配置段 class 统一收敛在
``settings`` 模块，便于集中维护。

组织约定：
- 配置段 class 统一放 ``settings`` 模块，不再按段拆分多文件；
- 敏感字段（密钥、令牌、连接串中的口令等）一律用 ``SecretStr``，且只经
  环境变量注入，不写入 yaml；
- 新增配置段后，需在 ``app/core/config.py`` 的 ``Settings`` 根配置里聚合
  对应字段，并在本 ``__init__`` 导出。

当前已导出：
- ``AppSettings`` —— 应用通用配置（名称、环境、host/port、debug、log_level）；
- ``LoggingSettings`` —— 日志配置（级别/序列化/目录/轮转/保留/压缩/diagnose/enqueue）；
- ``DBSettings`` —— 数据库配置（连接串/连接池/echo）；
- ``RedisSettings`` —— Redis 缓存配置（url/db/max_connections/decode_responses/encoding）；
- ``MilvusSettings`` —— Milvus 向量库配置（开关/地址/凭证/数据库/超时/批量大小）；
- ``CorsSettings`` —— 跨域配置（origins/methods/headers/credentials/expose_headers/max_age；dev/test 全放行、prod 收敛白名单）；
- ``LlmProviderConfig`` / ``LlmSettings`` —— LLM 网关配置（各 Provider 统一走 OpenAI 兼容端点；api_key 为 SecretStr 仅经环境变量注入）。
- ``LangSmithConfig`` —— LangSmith 追踪配置（挂 ``LlmSettings.langsmith``；enabled 默认 false 零上报，api_key 走 ``LANGCHAIN_API_KEY`` 环境变量）。
- ``SkillSettings`` —— skill 注册中心配置（扫描根目录、总开关、懒加载缓存）。
- ``ProjectSettings`` —— 本地项目导入配置（允许根目录、SDK 超时）。
- ``ClaudeAgentSettings`` —— Claude Agent SDK 配置（全能力开放 + SSE 流式输出）。

注：仅 HTTP 客户端参数仍写死（见 ``app/utils/http_client.py``），不进配置；
CORS 跨域策略已改配置驱动（见 ``CorsSettings`` 段）；LLM 网关参数亦配置驱动
（见 ``LlmSettings`` 段 + ``app/core/llm/``）。
"""
from app.core.settings.settings import (
    AppSettings,
    ClaudeAgentSettings,
    CorsSettings,
    DBSettings,
    LangSmithConfig,
    LlmProviderConfig,
    LlmSettings,
    LoggingSettings,
    McpClientSettings,
    McpRemoteServerSettings,
    McpServerSettings,
    McpSettings,
    MilvusSettings,
    ProjectSettings,
    RedisSettings,
    SkillSettings,
)

__all__ = [
    "AppSettings",
    "ClaudeAgentSettings",
    "LoggingSettings",
    "McpRemoteServerSettings",
    "McpClientSettings",
    "McpServerSettings",
    "McpSettings",
    "DBSettings",
    "RedisSettings",
    "MilvusSettings",
    "ProjectSettings",
    "CorsSettings",
    "LlmProviderConfig",
    "LlmSettings",
    "LangSmithConfig",
    "SkillSettings",
]
