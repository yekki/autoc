"""模型配置管理器

管理 AI 模型凭证的存储、验证和激活。
数据持久化到 config/models.json。
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from openai import OpenAI

from .client import PROVIDERS, PRESETS, LLMConfig

logger = logging.getLogger("autoc.model_config")

CONFIG_FILENAME = "config/models.json"


VALID_AGENTS = ("coder", "critique", "helper", "planner")


def _default_config() -> dict:
    return {
        "version": 2,
        "active": {
            "coder": {"provider": "", "model": ""},
            "critique": {"provider": "", "model": ""},
            "helper": {"provider": "", "model": ""},
            "planner": {"provider": "", "model": ""},
        },
        "credentials": {},
        "advanced": {
            "temperature": 0.7,
            "max_tokens": 32768,
            "timeout": 120,
            "max_rounds": 3,
        },
        "general_settings": {
            "use_cn_mirror": False,
            "enable_critique": False,
        },
    }


class ModelConfigManager:
    """管理 config/models.json 的加载、保存和凭证回显"""

    def __init__(self, project_root: str | Path | None = None):
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent.parent
        self.project_root = Path(project_root)
        self.config_path = self.project_root / CONFIG_FILENAME
        self._data: dict | None = None

    @property
    def data(self) -> dict:
        if self._data is None:
            self._data = self._load()
        return self._data

    def _load(self) -> dict:
        if not self.config_path.exists():
            return _default_config()
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            cfg = _default_config()
            _SPECIAL_SECTIONS = {"active", "credentials", "advanced"}
            for k, v in raw.items():
                if k not in _SPECIAL_SECTIONS and v is not None:
                    cfg[k] = v
            if "active" in raw and isinstance(raw["active"], dict):
                for k, v in raw["active"].items():
                    cfg["active"][k] = v
            if "credentials" in raw and isinstance(raw["credentials"], dict):
                cfg["credentials"] = raw["credentials"]
            if "advanced" in raw and isinstance(raw["advanced"], dict):
                cfg["advanced"].update(raw["advanced"])
            return cfg
        except Exception as e:
            logger.warning(f"加载 config/models.json 失败: {e}，使用默认配置")
            return _default_config()

    def save(self):
        """持久化到文件，并设置仅所有者可读写的权限（保护 API Key）"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            import os as _os
            _os.chmod(self.config_path, 0o600)
            logger.info(f"模型配置已保存: {self.config_path}")
        except Exception as e:
            logger.error(f"保存 config/models.json 失败: {e}")
            raise

    def reload(self):
        """重新从文件加载"""
        self._data = self._load()

    # ==================== Active Config ====================

    def get_active(self) -> dict:
        """获取当前激活配置 {coder: {provider, model}, critique: ..., helper: ...}"""
        return self.data["active"]

    def set_active(self, agent: str, provider: str, model: str):
        """设置某个 agent 的激活模型"""
        if agent not in VALID_AGENTS:
            raise ValueError(f"未知 agent: {agent}")
        self.data["active"][agent] = {"provider": provider, "model": model}

    def has_active_config(self) -> bool:
        """是否有任何 agent 配置了模型"""
        for agent_cfg in self.data["active"].values():
            if agent_cfg.get("provider") and agent_cfg.get("model"):
                return True
        return False

    # ==================== Credentials ====================

    def get_credential(self, provider: str) -> dict:
        """获取某个服务商的凭证 {api_key, base_url?, verified_models, last_verified}"""
        return self.data["credentials"].get(provider, {})

    def save_credential(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str = "",
    ):
        """保存验证通过的凭证"""
        cred = self.data["credentials"].get(provider, {})
        cred["api_key"] = api_key
        if base_url:
            cred["base_url"] = base_url
        verified = set(cred.get("verified_models", []))
        verified.add(model)
        cred["verified_models"] = sorted(verified)
        cred["last_verified"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.data["credentials"][provider] = cred

    def save_credential_key_only(
        self,
        provider: str,
        api_key: str,
        base_url: str = "",
    ):
        """仅保存 API Key（无需绑定模型，用于预存凭证）"""
        cred = self.data["credentials"].get(provider, {})
        cred["api_key"] = api_key
        if base_url:
            cred["base_url"] = base_url
        cred.setdefault("verified_models", [])
        self.data["credentials"][provider] = cred

    def get_api_key_for_provider(self, provider: str) -> str:
        """获取某个服务商的 API Key（先查凭证，再查环境变量）"""
        cred = self.get_credential(provider)
        if cred.get("api_key"):
            return cred["api_key"]
        prov_info = PROVIDERS.get(provider, {})
        env_key = prov_info.get("env_key", "")
        if env_key:
            return os.environ.get(env_key, "")
        return os.environ.get("AUTOC_API_KEY", "")

    def is_model_verified(self, provider: str, model: str) -> bool:
        """某个 provider+model 组合是否曾验证通过"""
        cred = self.get_credential(provider)
        return model in cred.get("verified_models", [])

    # ==================== Advanced ====================

    def get_advanced(self) -> dict:
        return self.data["advanced"]

    def set_advanced(self, **kwargs):
        for k, v in kwargs.items():
            if k in self.data["advanced"]:
                self.data["advanced"][k] = v

    # ==================== General Settings ====================

    def get_general_settings(self) -> dict:
        defaults = {"use_cn_mirror": False, "enable_critique": False}
        gs = self.data.get("general_settings", {})
        return {**defaults, **gs}

    def set_general_settings(self, **kwargs):
        defaults = {"use_cn_mirror": False, "enable_critique": False}
        gs = self.data.setdefault("general_settings", defaults)
        for k, v in kwargs.items():
            if k in defaults:
                gs[k] = v

    # ==================== LLMConfig 构建 ====================

    def build_llm_config_for_agent(self, agent: str) -> LLMConfig | None:
        """为指定 agent 构建 LLMConfig，如果未配置返回 None"""
        active = self.data["active"].get(agent, {})
        provider_id = active.get("provider", "")
        model_id = active.get("model", "")
        if not provider_id or not model_id:
            return None

        prov = PROVIDERS.get(provider_id, {})
        cred = self.get_credential(provider_id)
        api_key = cred.get("api_key", "")
        if not api_key:
            api_key = self.get_api_key_for_provider(provider_id)

        base_url = cred.get("base_url", "") or prov.get("base_url", "")
        adv = self.data["advanced"]

        return LLMConfig(
            preset=provider_id if provider_id in PRESETS else "",
            base_url=base_url,
            api_key=api_key,
            model=model_id,
            temperature=adv.get("temperature", 0.7),
            max_tokens=adv.get("max_tokens", 32768),
            timeout=adv.get("timeout", 120),
            extra_params=prov.get("extra_params", {}),
        )

    # ==================== 全量导出 (for API) ====================

    def to_api_response(self) -> dict:
        """供 Web API 返回的完整配置（脱敏 API Key）"""
        result = {
            "active": self.data["active"],
            "credentials": {},
            "advanced": self.data["advanced"],
            "general_settings": self.get_general_settings(),
        }
        for provider_id, cred in self.data["credentials"].items():
            result["credentials"][provider_id] = {
                "has_key": bool(cred.get("api_key")),
                "api_key_preview": _mask_key(cred.get("api_key", "")),
                "base_url": cred.get("base_url", ""),
                "verified_models": cred.get("verified_models", []),
                "last_verified": cred.get("last_verified", ""),
            }
        return result


def _mask_key(key: str) -> str:
    """API Key 脱敏显示: sk-abc...xyz"""
    if not key or len(key) < 8:
        return "***" if key else ""
    return f"{key[:6]}...{key[-4:]}"


def test_model_connection(
    provider: str,
    model: str,
    api_key: str,
    base_url: str = "",
) -> dict[str, Any]:
    """
    测试模型连接是否可用。

    Returns:
        {"success": True} 或 {"success": False, "error": "..."}
    """
    prov = PROVIDERS.get(provider)
    if not prov:
        return {"success": False, "error": f"未知服务提供商: {provider}"}

    actual_url = base_url or (prov["base_url"] if prov else "")
    if not actual_url:
        return {"success": False, "error": "Base URL 不能为空"}
    if not api_key:
        return {"success": False, "error": "API Key 不能为空"}

    headers = (prov or {}).get("default_headers", {})
    extra = (prov or {}).get("extra_params", {})

    try:
        client = OpenAI(
            api_key=api_key,
            base_url=actual_url,
            timeout=15,
            **({"default_headers": headers} if headers else {}),
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi, respond with OK"}],
            "max_tokens": 10,
        }
        if extra:
            kwargs["extra_body"] = extra

        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        return {"success": True, "response": content.strip()[:50]}
    except Exception as e:
        err_msg = str(e)
        if len(err_msg) > 200:
            err_msg = err_msg[:200] + "..."
        return {"success": False, "error": err_msg}
