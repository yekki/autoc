"""Orchestrator — 多 Agent 编排器（薄编排层）

核心链路: Planning 函数生成计划 → Coder Agent 迭代实现 → (可选) Critique Agent 评审。
实际逻辑委托给三个子模块:
- lifecycle.py: 项目生命周期（工作区/Checkpoint/初始化/收尾/预览/经验）
- scheduler.py: 任务调度（Planning 阶段/Dev-Test 迭代/操作入口）
- gates.py: 安全检查（Token 预算/回滚推断）
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from rich.console import Console

from autoc.core.llm import LLMClient, LLMConfig
from autoc.core.llm.registry import LLMRegistry
from autoc.core.event import EventLog
from autoc.core.security import SecurityAnalyzer, ConfirmationPolicy
from autoc.core.skill import SkillRegistry
from autoc.core.infra.user_profile import UserProfileManager
from autoc.core.conversation import ConversationStore
from autoc.core.llm.condenser import create_condenser
from autoc.core.project.memory import SharedMemory, TaskStatus
from autoc.core.project.models import ProjectStatus
from autoc.tools.sandbox import DEFAULT_SANDBOX_IMAGE
from autoc.core.analysis.experience import ExperienceStore
from autoc.core.project.progress import ProgressTracker
from autoc.core.project import ProjectManager
from autoc.core.analysis.complexity import assess_complexity
from autoc.core.project.state import StateManager
from autoc.core.infra.presenter import ConsolePresenter
from autoc.core.analysis.refiner import RequirementRefiner
from autoc.core.infra.profile import ProfileManager
from autoc.agents.planner import PlanningAgent
from autoc.agents.code_act_agent import CodeActAgent
from autoc.agents.critique import CritiqueAgent
from autoc.tools.file_ops import FileOps
from autoc.tools.shell import ShellExecutor
from autoc.tools.sandbox import DockerSandbox
from autoc.tools.git_ops import GitOps
from autoc.tools.code_quality import CodeQualityTools
from autoc.core.runtime.preview import PreviewManager
from autoc.core.runtime.venv_manager import VenvManager
from autoc.core.llm.router import ModelRouter
from . import lifecycle, scheduler

console = Console()
logger = logging.getLogger("autoc.orchestrator")

@dataclass
class OrchestratorConfig:
    """Orchestrator 配置对象"""
    llm_config: LLMConfig = field(default_factory=LLMConfig)
    workspace_dir: str = "./workspace"
    max_rounds: int = 3
    auto_fix: bool = True
    agent_configs: dict = field(default_factory=dict)
    on_event: Callable | None = None
    enable_checkpoint: bool = False
    checkpoint_dir: str = ".autoc_state"
    context_limit: int = 60000
    enable_git: bool = True
    sandbox_image: str = DEFAULT_SANDBOX_IMAGE
    enable_experience: bool = True
    experience_dir: str = ".autoc_experience"
    enable_code_quality: bool = True
    enable_parallel: bool = False
    max_parallel_tasks: int = 3
    enable_progress_tracking: bool = True
    single_task_mode: bool = False
    session_registry: Any = None
    session_id: str = ""
    refiner_config: dict = field(default_factory=dict)
    token_budget: int = 0
    preview_config: dict = field(default_factory=dict)
    use_project_venv: bool = False
    global_venv_path: str = ""
    sandbox_mode: str = "project"
    enable_critique: bool = False
    enable_plan_approval: bool = False  # S-002: Planning 确认门，True 时等待用户审批后再开发


class Orchestrator:
    """多 Agent 编排器 — 初始化 + 生命周期 + 阶段调度

    支持上下文管理器协议，自动清理沙箱资源:
        with Orchestrator(...) as orc:
            orc.run("需求描述")
    """

    def __init__(self, config: OrchestratorConfig | None = None, **kwargs):
        """初始化编排器

        Args:
            config: OrchestratorConfig 配置对象
            **kwargs: 直接传递给 OrchestratorConfig 的参数
        """
        if config is None:
            config = OrchestratorConfig(**kwargs)
        self._config = config

        self.workspace_dir = os.path.abspath(config.workspace_dir)
        self.max_rounds = config.max_rounds
        self.auto_fix = config.auto_fix
        self.on_event = config.on_event or (lambda e: None)
        self.enable_checkpoint = config.enable_checkpoint
        self.checkpoint_dir = config.checkpoint_dir
        self.context_limit = config.context_limit
        self.enable_parallel = config.enable_parallel
        self.max_parallel_tasks = config.max_parallel_tasks
        self.single_task_mode = config.single_task_mode
        self.session_registry = config.session_registry
        self.session_id = config.session_id
        self._token_budget = config.token_budget
        self.presenter = ConsolePresenter()
        self._state_manager: StateManager | None = None
        self._agent_configs = config.agent_configs

        self._init_core_tools(config.workspace_dir, config.use_project_venv,
                              config.global_venv_path, config.enable_progress_tracking)
        # 沙箱延迟初始化：存储配置，规划完成后再创建容器
        self._sandbox_config = {
            "workspace_dir": config.workspace_dir,
            "sandbox_image": config.sandbox_image,
            "sandbox_mode": config.sandbox_mode,
        }
        self.sandbox = None
        self._init_peripheral(config.workspace_dir, config.enable_git, config.enable_code_quality,
                              config.enable_experience, config.experience_dir,
                              config.preview_config or None, config.agent_configs)
        self._init_llm(config.llm_config, config.agent_configs, config.refiner_config or None)
        self._init_agents(config.agent_configs)

    # ---------- 初始化：核心工具 ----------

    def _init_core_tools(self, workspace_dir, use_project_venv, global_venv_path,
                         enable_progress_tracking):
        self.venv_manager = VenvManager(
            workspace_dir,
            use_project_venv=use_project_venv,
            global_venv_path=global_venv_path,
        )
        self._venv_ready = False
        self.memory = SharedMemory()
        self.file_ops = FileOps(workspace_dir)
        self.shell = ShellExecutor(workspace_dir, venv_manager=self.venv_manager)
        self.progress_tracker = ProgressTracker(workspace_dir) if enable_progress_tracking else None
        self.project_manager = ProjectManager(workspace_dir)

        # EventLog — Append-Only JSONL 统一事件日志
        event_log_dir = os.path.join(workspace_dir, ".autoc-events")
        self.event_log = EventLog(event_log_dir, session_id=self.session_id)

        # Security Analyzer — 零 LLM 开销的工具安全评估
        self.security_analyzer = SecurityAnalyzer(
            policy=ConfirmationPolicy.SANDBOX,
        )

        # Skill Registry — 可复用知识注入
        self.skill_registry = SkillRegistry()
        self.skill_registry.load_builtin()
        self.skill_registry.load_project(workspace_dir)

        # User Profile — ToM 用户画像
        self.user_profile = UserProfileManager()

        # Conversation Store — 对话增量持久化
        conv_store_dir = os.path.join(workspace_dir, ".autoc-conversations")
        self.conversation_store = ConversationStore(
            conv_store_dir, session_id=self.session_id,
        )

    # ---------- 初始化：Docker 沙箱（延迟到规划后） ----------

    def init_sandbox_after_planning(self):
        """规划完成后初始化沙箱。先确定最终镜像（含 RuntimeBuilder 优化），再创建容器。"""
        if self.sandbox and self.sandbox.is_available:
            return
        cfg = self._sandbox_config
        image = cfg["sandbox_image"]

        # RuntimeBuilder: 先确定最终镜像，避免先建容器再换镜像导致镜像不匹配
        try:
            from autoc.core.runtime.builder import RuntimeBuilder
            use_cn = os.environ.get("AUTOC_USE_CN_MIRROR") == "1"
            builder = RuntimeBuilder(base_image=image, use_cn_mirror=use_cn)
            built_image = builder.build_if_needed(cfg["workspace_dir"])
            if built_image and built_image != image:
                logger.info(f"RuntimeBuilder 构建优化镜像: {built_image}")
                image = built_image
        except Exception as e:
            logger.debug(f"RuntimeBuilder 跳过: {e}")

        self._init_sandbox(cfg["workspace_dir"], image, cfg["sandbox_mode"])

    def _init_sandbox(self, workspace_dir, sandbox_image, sandbox_mode):
        project_name = os.path.basename(workspace_dir)
        self.sandbox = DockerSandbox(
            workspace_dir, image=sandbox_image,
            sandbox_mode=sandbox_mode, project_name=project_name,
        )

        def _sandbox_progress(step: str, message: str, percent: int):
            self._emit("sandbox_preparing", step=step, message=message, progress=percent)

        self._ensure_sandbox_ready(_sandbox_progress)
        self._emit("sandbox_ready", message="沙箱环境已就绪")
        self.shell.sandbox = self.sandbox
        logger.info("Agent 命令执行已切换到 Docker 沙箱模式")

        # 自动执行项目初始化脚本（.autoc/setup.sh）
        try:
            setup_output = self.sandbox.run_setup_script()
            if setup_output:
                logger.info(f"项目初始化脚本已执行 ({len(setup_output)} chars)")
        except Exception as e:
            logger.warning(f"项目初始化脚本执行失败: {e}")

    # ---------- 初始化：外围组件 ----------

    def _init_peripheral(self, workspace_dir, enable_git, enable_code_quality,
                         enable_experience, experience_dir,
                         preview_config, agent_configs):
        self._preview_config = preview_config or {}
        self.preview_manager = PreviewManager(workspace_dir, on_event=self.on_event) \
            if self._preview_config.get("enabled", True) else None
        self._preview_info: dict | None = None

        self.git_ops = None
        if enable_git:
            try:
                self.git_ops = GitOps(workspace_dir, auto_init=True)
            except Exception as e:
                logger.warning(f"Git 初始化失败: {e}")

        self.code_quality = CodeQualityTools(workspace_dir) if enable_code_quality else None
        self.experience = ExperienceStore(experience_dir) if enable_experience else None
        self.profile_manager = ProfileManager()

        self.code_index = None

    # ---------- 初始化：LLM 客户端 ----------

    def _init_llm(self, llm_config, agent_configs, refiner_config):
        routing_config = agent_configs.get("_routing", {})
        self._model_router = ModelRouter(
            provider=llm_config.preset or "glm",
            config=routing_config,
        )

        self.llm_registry = LLMRegistry()

        self.llm_default = LLMClient(llm_config)

        # 四类模型: Planner AI（规划）/ Coder AI（实现）/ Critique AI（评审）/ 辅助 AI（需求优化等）
        coder_cfg = agent_configs.get("coder", {})
        critique_cfg = agent_configs.get("critique", {})
        helper_cfg = agent_configs.get("helper", {})
        planner_cfg = agent_configs.get("planner", {})

        self.llm_coder = self._get_llm_for_agent(llm_config, coder_cfg, agent_name="coder")
        self.llm_critique = self._get_llm_for_agent(llm_config, critique_cfg, agent_name="critique")
        self.llm_helper = self._get_llm_for_agent(llm_config, helper_cfg, agent_name="helper")

        # Planner: 未配置时 fallback 到 llm_coder
        if planner_cfg.get("model") or planner_cfg.get("preset"):
            self.llm_planner = self._get_llm_for_agent(llm_config, planner_cfg, agent_name="planner")
        else:
            self.llm_planner = self.llm_coder

        self.llm_registry.register("coder", self.llm_coder)
        self.llm_registry.register("critique", self.llm_critique)
        self.llm_registry.register("helper", self.llm_helper)
        self.llm_registry.register("planner", self.llm_planner)

        completion_log_dir = os.path.join(self.workspace_dir, ".autoc-logs", "completions")
        for llm in (self.llm_coder, self.llm_critique, self.llm_helper, self.llm_planner):
            llm.enable_completion_logging(completion_log_dir)

        refiner_config = refiner_config or {}
        refiner_mode = refiner_config.get("mode", "auto")
        self.refiner = RequirementRefiner(
            llm_client=self.llm_helper, mode=refiner_mode,
            quality_threshold_high=refiner_config.get("quality_threshold_high", 0.7),
            quality_threshold_low=refiner_config.get("quality_threshold_low", 0.4),
        ) if refiner_mode != "off" else None

    # ---------- 初始化：Agent 实例 ----------

    def _init_agents(self, agent_configs):
        common_kwargs = dict(
            on_event=self.on_event, context_limit=self.context_limit,
            git_ops=self.git_ops, code_quality=self.code_quality,
            progress_tracker=self.progress_tracker,
        )
        impl_cfg = (agent_configs.get("coder", {})
                     or agent_configs.get("main", {})
                     or agent_configs.get("developer", {}))

        # PlanningAgent: 只读工具，独立 LLM
        planner_cfg = agent_configs.get("planner", {})
        self.planner_agent = PlanningAgent(
            name=planner_cfg.get("name", "Planning Agent"),
            role_description=planner_cfg.get("description", "项目规划师"),
            llm_client=self.llm_planner, memory=self.memory,
            file_ops=self.file_ops, shell=self.shell,
            max_iterations=planner_cfg.get("max_iterations", 10), color="blue",
            **common_kwargs,
        )

        # CodeActAgent: 全量工具
        self.code_act_agent = CodeActAgent(
            name=impl_cfg.get("name", "Coder Agent"),
            role_description=impl_cfg.get("description", "全栈实现者"),
            llm_client=self.llm_coder, memory=self.memory,
            file_ops=self.file_ops, shell=self.shell,
            max_iterations=impl_cfg.get("max_iterations", 50), color="green",
            **common_kwargs,
        )

        self.code_act_agent._helper_llm = self.llm_helper

        # Critique Agent: 可选，由 enable_critique 配置控制
        self.critique = None
        if self._config.enable_critique:
            critique_cfg = agent_configs.get("critique", {})
            self.critique = CritiqueAgent(
                name=critique_cfg.get("name", "Critique Agent"),
                role_description=critique_cfg.get("description", "代码评审专家"),
                llm_client=self.llm_critique, memory=self.memory,
                file_ops=self.file_ops, shell=self.shell,
                max_iterations=critique_cfg.get("max_iterations", 8), color="magenta",
                **common_kwargs,
            )

        # Condenser — 注入所有 Agent（planner 用 NoOp 避免压缩只读探索上下文）
        condenser_cfg = agent_configs.get("_condenser", {})
        condenser_strategy = condenser_cfg.get("strategy", "sliding_window")
        self.code_act_agent.condenser = create_condenser(condenser_strategy)
        self.planner_agent.condenser = create_condenser("noop")
        if self.critique:
            self.critique.condenser = create_condenser(condenser_strategy)

        # 注入共享基础设施
        agents = [self.planner_agent, self.code_act_agent]
        if self.critique:
            agents.append(self.critique)
        for agent in agents:
            if hasattr(agent, '_registry'):
                agent._registry.set_security_analyzer(self.security_analyzer)
            agent._skill_registry = self.skill_registry
            agent._conversation_store = self.conversation_store
            agent._event_log = self.event_log
            agent._user_profile = self.user_profile

        self.developer = self.code_act_agent

    # ==================== 上下文管理器 ====================

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def cleanup(self):
        """Session 结束时清理：断开沙箱引用（不销毁容器）"""
        if self.preview_manager:
            try:
                self.preview_manager.stop()
            except Exception:
                pass
        if self.sandbox:
            try:
                self.sandbox.detach()
            except Exception:
                pass

    def destroy_sandbox(self):
        """显式销毁容器（新需求或用户手动清理时调用）"""
        if self.sandbox:
            self.sandbox.destroy()

    # ==================== 沙箱自动恢复 ====================

    def _ensure_sandbox_ready(self, on_progress):
        """确保沙箱就绪，失败时重试一次（不销毁容器，容器仅随项目删除时清理）"""
        try:
            self.sandbox.ensure_ready(on_progress=on_progress)
        except RuntimeError:
            logger.warning("沙箱初始化失败，重试一次")
            self.sandbox._available = None
            self.sandbox.ensure_ready(on_progress=on_progress)

    # ==================== 辅助方法 ====================

    def _get_llm_for_agent(self, base_config: LLMConfig, agent_config: dict,
                           agent_name: str = "", complexity: str = "") -> LLMClient:
        agent_model = agent_config.get("model", "")
        agent_preset = agent_config.get("preset", "")

        # 智能模型路由: 如果 agent_config 未显式指定 model，尝试路由
        if not agent_model and agent_name and complexity and self._model_router.is_enabled:
            routed_model = self._model_router.route(agent_name, complexity)
            if routed_model:
                agent_model = routed_model

        if not agent_model and not agent_preset:
            return LLMClient(base_config)
        override_config = LLMConfig(
            preset=agent_preset or base_config.preset,
            base_url=agent_config.get("base_url", "") or base_config.base_url,
            api_key=agent_config.get("api_key", "") or base_config.api_key,
            model=agent_model or base_config.model,
            temperature=base_config.temperature,
            max_tokens=base_config.max_tokens,
            timeout=agent_config.get("timeout", 0) or base_config.timeout,
            extra_params=base_config.extra_params,
            max_retries=base_config.max_retries,
            retry_base_delay=base_config.retry_base_delay,
        )
        return LLMClient(override_config)

    def _get_helper_batch_size(self) -> int:
        return self._agent_configs.get("helper", {}).get("batch_size", 5)

    def _emit(self, event_type: str, **data):
        self.on_event({"type": event_type, "agent": "system", "data": data})
        self.event_log.append(event_type, agent="system", data=data)

    def _wait_for_plan_approval(self, timeout: float = 600.0) -> bool:
        """S-002: 暂停执行，等待用户在 Web 界面确认 Planning 输出。

        超时（默认 10 分钟）自动视为批准，避免永久阻塞。
        Returns True（批准继续）/ False（用户拒绝，终止开发）。
        """
        if not self.session_id:
            return True
        from autoc.core.orchestrator.gates import (
            register_approval_gate, get_approval_result, cleanup_approval_gate,
        )
        evt = register_approval_gate(self.session_id)
        self._emit(
            "plan_approval_required",
            plan_md=self.memory.plan_md,
            session_id=self.session_id,
            timeout_seconds=int(timeout),
        )
        logger.info("[S-002] 等待用户审批计划 session=%s timeout=%.0fs", self.session_id, timeout)
        fired = evt.wait(timeout=timeout)
        if not fired:
            logger.warning("[S-002] 审批超时 %.0fs，自动批准继续", timeout)
            cleanup_approval_gate(self.session_id)
            return True
        result = get_approval_result(self.session_id)
        cleanup_approval_gate(self.session_id)
        if result and not result.get("approved"):
            feedback = result.get("feedback", "用户拒绝计划")
            logger.info("[S-002] 用户拒绝计划: %s", feedback)
            return False
        return True

    def _finish_session(self, success: bool):
        if self.session_registry and self.session_id:
            self.session_registry.update(
                self.session_id, status="completed" if success else "failed",
                ended_at=time.time(), workspace_dir=self.file_ops.workspace_dir,
            )

    @property
    def total_tokens(self) -> int:
        return self.llm_registry.total_tokens

    @staticmethod
    def assess_complexity(requirement: str) -> str:
        return assess_complexity(requirement)

    def _get_enabled_features(self) -> list[str]:
        features = ["Docker沙箱"]
        if self.refiner:
            features.append("需求优化")
        if self.git_ops:
            features.append("Git")
        if self.experience:
            features.append("经验学习")
        if self.code_quality:
            features.append("代码质量")
        if self.enable_parallel:
            features.append("并行执行")
        if self.progress_tracker:
            features.append("进度追踪")
        if self.single_task_mode:
            features.append("单任务模式")
        features.append("技术栈Profile")
        features.append("安全评估")
        features.append("停滞检测")
        features.append("Skill注入")
        features.append("用户画像")
        features.append("对话持久化")
        features.append("Condenser压缩")
        return features

    # ==================== 主流程 ====================

    def run(self, requirement: str, resume: bool = False, clean: bool = False,
            incremental: bool = False, max_iterations: int | None = None) -> dict:
        """运行全自动开发流程"""
        start_time = time.time()

        if self.session_registry and self.session_id:
            self.session_registry.register(
                session_id=self.session_id, requirement=requirement,
                workspace_dir=self.file_ops.workspace_dir,
            )

        lifecycle.check_workspace(self, clean=clean)

        if resume and lifecycle.load_checkpoint(self):
            console.print("[green]📂 从上次中断处继续...[/green]")
            return lifecycle.run_from_checkpoint(self, start_time)

        requirement = scheduler.refine_requirement(self, requirement)
        self.memory.set_requirement(requirement)
        self.presenter.print_header(requirement, self._get_enabled_features())

        if self.git_ops:
            self.git_ops.ensure_init()

        lifecycle.ensure_project_metadata(self, requirement)
        skip_planning = lifecycle.try_restore_existing_tasks(self, incremental)

        if skip_planning:
            plan_md = self.memory.plan_md
        else:
            plan_md = scheduler.run_planning_phase(self, requirement, incremental)
            if plan_md is None:
                self._finish_session(False)
                return {"success": False, "summary": "需求分析失败", "files": []}

            # S-002: Planning 确认门（由 API 层 require_plan_approval 参数启用）
            if getattr(self._config, "enable_plan_approval", False):
                approved = self._wait_for_plan_approval()
                if not approved:
                    self._emit("execution_failed",
                               failure_reason="用户拒绝计划，开发已取消",
                               phase="plan_approval", recovery_suggestions=[])
                    self._finish_session(False)
                    return {"success": False, "summary": "用户拒绝计划，开发已取消", "files": []}

        self.init_sandbox_after_planning()

        try:
            scheduler.run_dev_and_test(self, plan_md, max_iterations=max_iterations)
        except (SystemExit, KeyboardInterrupt):
            logger.warning("迭代循环被用户终止")
        except Exception as e:
            logger.exception("迭代循环异常: %s", e)

        elapsed = time.time() - start_time
        try:
            result = lifecycle.finalize(self, elapsed, requirement)
            # 首次运行（非 redefine/add_feature 路径）：成功时打 tag + 记录需求
            if result.get("success") and not hasattr(self, '_requirement_type'):
                from autoc.core.project.models import RequirementType
                ver = self.project_manager.get_version()
                if self.git_ops:
                    self.git_ops.tag(f"v{ver}", f"AutoC: v{ver} 主需求完成")
                self.project_manager.record_requirement(
                    req_id=f"req-{ver}", title=requirement[:200],
                    description=requirement, req_type=RequirementType.PRIMARY,
                    version=ver,
                )
            return result
        except Exception as e:
            logger.exception("收尾阶段异常: %s", e)
            try:
                self.project_manager.update_status(ProjectStatus.INCOMPLETE, force=True)
            except Exception:
                pass
            self._finish_session(False)
            return {
                "success": False,
                "summary": f"收尾异常: {e}",
                "files": list(self.memory.files.keys()),
                "tasks_completed": len(self.memory.get_tasks_by_status(TaskStatus.COMPLETED)),
                "tasks_total": len(self.memory.tasks),
            }

    def quick_fix_bugs(self, bug_ids=None, bug_titles=None, bugs_data=None) -> dict:
        return scheduler.execute_quick_fix(self, bug_ids, bug_titles, bugs_data)

    def resume(self) -> dict:
        """从上次中断处恢复执行（跳过 PM，只处理未完成的任务）"""
        from autoc.core.orchestrator.scheduler_ops import execute_resume
        return execute_resume(self)

    def redefine_project(self, new_description: str) -> dict:
        """主需求变更：归档当前迭代 → 清空 → major bump → 全量重来"""
        from autoc.core.orchestrator.scheduler_ops import execute_redefine_project
        return execute_redefine_project(self, new_description)

    def add_feature(self, new_description: str) -> dict:
        """次级需求：保留已有代码 → 增量规划 → append 新任务 → minor bump"""
        from autoc.core.orchestrator.scheduler_ops import execute_add_feature
        return execute_add_feature(self, new_description)

