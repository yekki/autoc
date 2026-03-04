"""预置测试用例 — 3 种复杂度的 ProjectPlan，用于 Mock PM 模式

每个用例包含:
- requirement: 需求描述（与真实 PM 模式的输入一致）
- plan: ProjectPlan 对象（跳过 PM 直接注入）
- complexity: 复杂度标签（simple / medium / complex）
"""

from autoc.core.project.models import ProjectPlan, Task


def get_test_case(name: str) -> dict:
    """获取预置测试用例

    Returns:
        {"requirement": str, "plan": ProjectPlan, "complexity": str}
        对于 mini_memos，额外返回 "features": [{"requirement", "plan"}]
    """
    cases = {
        "hello": _case_hello(),
        "calculator": _case_calculator(),
        "calculator_extend": _case_calculator_extend(),
        "flask_todo": _case_flask_todo(),
        "flask_config": _case_flask_config(),
        "mini_memos": _case_mini_memos(),
        "task_board": _case_task_board(),
    }
    if name not in cases:
        available = ", ".join(cases.keys())
        raise ValueError(f"未知测试用例: {name}，可用: {available}")
    return cases[name]


def list_test_cases() -> list[str]:
    return ["hello", "calculator", "calculator_extend", "flask_todo",
            "flask_config", "mini_memos", "task_board"]


# ── hello: 最简单的 Python 脚本 ──────────────────────────────────

def _case_hello() -> dict:
    return {
        "requirement": "创建一个 Python hello world 脚本，输出 Hello, World!",
        "complexity": "simple",
        "plan": ProjectPlan(
            project_name="hello-world",
            description="一个简单的 Python Hello World 脚本",
            tech_stack=["Python"],
            tasks=[
                Task(
                    id="task-1",
                    title="创建 Hello World 主脚本",
                    description=(
                        "创建 main.py，包含一个 main() 函数，"
                        "运行时输出 'Hello, World!' 到标准输出。"
                    ),
                    files=["main.py"],
                    verification_steps=[
                        "python -m py_compile main.py",
                        "python main.py",
                        "test -f main.py",
                    ],
                    acceptance_criteria=[
                        "main.py 存在且语法正确",
                        "运行 python main.py 输出包含 Hello",
                    ],
                ),
            ],
            data_models="",
            api_design="",
        ),
    }


# ── calculator: 多任务 + 依赖关系 ────────────────────────────────

def _case_calculator() -> dict:
    return {
        "requirement": "创建一个命令行计算器，支持加减乘除四则运算",
        "complexity": "medium",
        "plan": ProjectPlan(
            project_name="cli-calculator",
            description="命令行计算器，支持 +、-、*、/ 四则运算",
            tech_stack=["Python"],
            tasks=[
                Task(
                    id="task-1",
                    title="创建计算引擎模块",
                    description=(
                        "创建 calculator.py，实现 Calculator 类，"
                        "包含 add/subtract/multiply/divide 四个方法，"
                        "每个方法接收两个 float 参数并返回 float。"
                        "除法需检查除数为零的情况，抛出 ValueError。"
                    ),
                    files=["calculator.py"],
                    verification_steps=[
                        "python -m py_compile calculator.py",
                        "python -c \"from calculator import Calculator; c = Calculator(); print(c.add(1, 2))\"",
                    ],
                    acceptance_criteria=[
                        "Calculator 类存在且可导入",
                        "四则运算方法返回正确结果",
                    ],
                ),
                Task(
                    id="task-2",
                    title="创建命令行入口",
                    description=(
                        "创建 main.py，解析命令行输入 (格式: num1 op num2)，"
                        "调用 Calculator 对应方法并输出结果。"
                        "支持的操作符: +, -, *, /"
                    ),
                    files=["main.py"],
                    dependencies=["task-1"],
                    verification_steps=[
                        "python -m py_compile main.py",
                        "echo '3 + 4' | python main.py",
                        "test -f main.py",
                    ],
                    acceptance_criteria=[
                        "main.py 存在且可运行",
                        "输入 '3 + 4' 输出 7",
                    ],
                ),
            ],
            data_models="class Calculator:\n    def add(a: float, b: float) -> float\n    def subtract(a: float, b: float) -> float\n    def multiply(a: float, b: float) -> float\n    def divide(a: float, b: float) -> float",
            api_design="",
        ),
    }


# ── calculator_extend: 增量修改（验证 edit_file）────────────────────

def _case_calculator_extend() -> dict:
    return {
        "requirement": (
            "在已有的 Calculator 类（calculator.py）基础上增加以下功能：\n"
            "1. 添加 history 属性，记录每次运算的历史（列表，每项包含操作和结果）\n"
            "2. 添加 last_result 属性，返回最近一次运算结果\n"
            "3. 添加 clear_history() 方法清空历史\n"
            "4. 更新 main.py 支持输入 'history' 查看历史记录\n\n"
            "注意：calculator.py 和 main.py 已存在，请在已有代码基础上修改，不要重写。"
        ),
        "complexity": "medium",
        "plan": ProjectPlan(
            project_name="cli-calculator-extend",
            description="在已有计算器基础上增加历史记录功能",
            tech_stack=["Python"],
            tasks=[
                Task(
                    id="task-1",
                    title="为 Calculator 类增加历史记录",
                    description=(
                        "修改 calculator.py，给 Calculator 类添加 __init__ 方法"
                        "初始化 self.history = [] 和 self.last_result = None。"
                        "在每个运算方法中记录 {'op': 'add', 'args': (a, b), 'result': r}。"
                        "添加 clear_history() 方法。"
                    ),
                    files=["calculator.py"],
                    verification_steps=[
                        "python -m py_compile calculator.py",
                        'python -c "from calculator import Calculator; c = Calculator(); c.add(1,2); assert len(c.history) == 1"',
                    ],
                    acceptance_criteria=[
                        "Calculator 有 history 属性",
                        "运算后 history 记录正确",
                    ],
                ),
                Task(
                    id="task-2",
                    title="更新命令行入口支持查看历史",
                    description=(
                        "修改 main.py，支持输入 'history' 打印历史记录，"
                        "支持输入 'clear' 清空历史，支持 'quit' 退出。"
                    ),
                    files=["main.py"],
                    dependencies=["task-1"],
                    verification_steps=[
                        "python -m py_compile main.py",
                    ],
                    acceptance_criteria=[
                        "main.py 支持 history 命令",
                    ],
                ),
            ],
            data_models="class Calculator:\n    history: list[dict]\n    last_result: float | None\n    def clear_history(self) -> None",
            api_design="",
        ),
    }


# ── flask_todo: 复杂 Web 项目 ────────────────────────────────────

def _case_flask_todo() -> dict:
    return {
        "requirement": "创建一个 Flask Todo 应用，带 SQLite 存储，支持增删改查",
        "complexity": "complex",
        "plan": ProjectPlan(
            project_name="flask-todo",
            description="Flask Todo 应用，使用 SQLite 存储，提供 REST API",
            tech_stack=["Python", "Flask", "SQLite"],
            tasks=[
                Task(
                    id="task-1",
                    title="创建数据库模型和初始化",
                    description=(
                        "创建 models.py，定义 Todo 数据模型（id, title, done, created_at）。\n"
                        "创建 database.py，实现 SQLite 初始化和 CRUD 操作:\n"
                        "- init_db(): 创建 todos 表\n"
                        "- get_all_todos(): 返回所有 todo\n"
                        "- create_todo(title): 创建新 todo\n"
                        "- update_todo(id, done): 更新完成状态\n"
                        "- delete_todo(id): 删除 todo"
                    ),
                    files=["models.py", "database.py"],
                    verification_steps=[
                        "python -m py_compile models.py",
                        "python -m py_compile database.py",
                        "python -c \"from database import init_db; init_db(); print('DB init OK')\"",
                    ],
                    acceptance_criteria=[
                        "models.py 和 database.py 语法正确",
                        "init_db() 可成功创建数据库",
                    ],
                ),
                Task(
                    id="task-2",
                    title="创建 Flask 应用和 API 路由",
                    description=(
                        "创建 app.py，实现 Flask 应用:\n"
                        "- GET /api/todos → 返回所有 todo (JSON)\n"
                        "- POST /api/todos → 创建新 todo (JSON body: {title})\n"
                        "- PUT /api/todos/<id> → 更新 todo (JSON body: {done})\n"
                        "- DELETE /api/todos/<id> → 删除 todo\n"
                        "- GET / → 返回简单的 HTML 页面"
                    ),
                    files=["app.py"],
                    dependencies=["task-1"],
                    verification_steps=[
                        "python -m py_compile app.py",
                        "python -c \"from app import app; print(app.name)\"",
                        "test -f app.py",
                    ],
                    acceptance_criteria=[
                        "app.py 语法正确且可导入",
                        "Flask app 对象可正常创建",
                    ],
                ),
                Task(
                    id="task-3",
                    title="创建依赖文件和启动脚本",
                    description=(
                        "创建 requirements.txt，包含 flask 依赖。\n"
                        "创建 README.md，说明项目用途和启动方式。"
                    ),
                    files=["requirements.txt", "README.md"],
                    dependencies=["task-2"],
                    verification_steps=[
                        "test -f requirements.txt",
                        "test -f README.md",
                        "grep -q flask requirements.txt",
                    ],
                    acceptance_criteria=[
                        "requirements.txt 包含 flask",
                        "README.md 存在",
                    ],
                ),
            ],
            data_models=(
                "class Todo:\n"
                "    id: int  # 主键，自增\n"
                "    title: str  # 标题\n"
                "    done: bool = False  # 完成状态\n"
                "    created_at: str  # ISO 时间戳\n"
                "\n"
                "CREATE TABLE todos (\n"
                "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
                "    title TEXT NOT NULL,\n"
                "    done BOOLEAN DEFAULT 0,\n"
                "    created_at TEXT DEFAULT CURRENT_TIMESTAMP\n"
                ");"
            ),
            api_design=(
                "GET    /api/todos       → [{id, title, done, created_at}]\n"
                "POST   /api/todos       ← {title}  → {id, title, done, created_at}\n"
                "PUT    /api/todos/<id>   ← {done}   → {id, title, done, created_at}\n"
                "DELETE /api/todos/<id>   →  204 No Content\n"
                "GET    /                 → HTML 页面"
            ),
        ),
    }


# ── flask_config: 验证 Context7 + ask_helper 知识获取路径 ────────────
# 该用例要求 Agent 正确配置 Flask（CORS / 环境变量 / 日志），
# 需要查阅 Flask 文档（Context7 场景）并理解项目约定（ask_helper 场景）。

def _case_flask_config() -> dict:
    return {
        "requirement": (
            "创建一个 Flask API 项目：\n"
            "1. 使用 Flask 的 app factory 模式（create_app 函数）\n"
            "2. 从环境变量 FLASK_SECRET_KEY 读取密钥\n"
            "3. 配置 CORS 允许 http://localhost:3000\n"
            "4. 配置 JSON 日志格式输出到 stdout\n"
            "5. 提供 GET /health 健康检查端点返回 {\"status\": \"ok\"}"
        ),
        "complexity": "medium",
        "knowledge_hints": {
            "context7_queries": [
                "Flask app factory pattern create_app",
                "flask-cors CORS configuration",
                "Python logging JSON formatter",
            ],
            "ask_helper_questions": [
                "项目是否有统一的日志格式要求？",
                "CORS 允许的前端地址是固定的还是可配置的？",
            ],
        },
        "plan": ProjectPlan(
            project_name="flask-config-demo",
            description="Flask API 项目，演示 app factory + CORS + 环境变量 + JSON 日志",
            tech_stack=["Python", "Flask", "flask-cors"],
            tasks=[
                Task(
                    id="task-1",
                    title="创建 Flask App Factory",
                    description=(
                        "创建 app.py，实现 create_app() 工厂函数：\n"
                        "- 从 os.environ 读取 FLASK_SECRET_KEY，无则用默认值\n"
                        "- 配置 flask-cors，允许 http://localhost:3000\n"
                        "- 注册 /health 蓝图或直接路由\n"
                        "- 配置 JSON 格式的日志输出"
                    ),
                    files=["app.py"],
                    verification_steps=[
                        "python -m py_compile app.py",
                        "python -c \"from app import create_app; app = create_app(); print(app.name)\"",
                    ],
                    acceptance_criteria=[
                        "create_app() 工厂函数存在且可调用",
                        "Flask app 对象正常创建",
                    ],
                ),
                Task(
                    id="task-2",
                    title="创建健康检查端点和启动脚本",
                    description=(
                        "在 app.py 中添加 GET /health 端点，返回 JSON {\"status\": \"ok\"}。\n"
                        "创建 run.py 入口脚本，调用 create_app() 并启动。\n"
                        "创建 requirements.txt，包含 flask 和 flask-cors。"
                    ),
                    files=["run.py", "requirements.txt"],
                    dependencies=["task-1"],
                    verification_steps=[
                        "test -f run.py",
                        "test -f requirements.txt",
                        "grep -q flask requirements.txt",
                        "grep -q flask-cors requirements.txt",
                    ],
                    acceptance_criteria=[
                        "run.py 存在且语法正确",
                        "requirements.txt 包含 flask 和 flask-cors",
                    ],
                ),
            ],
            data_models="",
            api_design="GET /health → {\"status\": \"ok\"}",
        ),
    }


# ── mini_memos: 多阶段生命周期测试（主需求 + 2 个追加功能） ──

def _case_mini_memos() -> dict:
    """Mini Memos — 用于测试 primary → add_feature × 2 → fix 完整生命周期"""
    primary_plan = ProjectPlan(
        project_name="mini-memos",
        description="轻量备忘录应用，支持创建、列表、删除备忘",
        tech_stack=["Python"],
        tasks=[
            Task(
                id="task-1",
                title="创建备忘录数据模型",
                description=(
                    "创建 memo.py，定义 Memo 数据类（id, title, content, created_at）。\n"
                    "实现 MemoStore 类，使用内存字典存储，提供:\n"
                    "- add(title, content) -> Memo\n"
                    "- get(id) -> Memo | None\n"
                    "- list_all() -> list[Memo]\n"
                    "- delete(id) -> bool"
                ),
                files=["memo.py"],
                verification_steps=[
                    "python -m py_compile memo.py",
                    "python -c \"from memo import MemoStore; s = MemoStore(); m = s.add('test', 'hello'); print(m.title)\"",
                ],
                acceptance_criteria=[
                    "MemoStore 可导入并正常工作",
                    "CRUD 操作返回正确结果",
                ],
            ),
            Task(
                id="task-2",
                title="创建命令行界面",
                description=(
                    "创建 cli.py，实现命令行交互:\n"
                    "- add <title> <content>: 添加备忘\n"
                    "- list: 列出所有备忘\n"
                    "- delete <id>: 删除备忘\n"
                    "- help: 显示帮助\n"
                    "使用 argparse 或简单的 input() 循环。"
                ),
                files=["cli.py"],
                dependencies=["task-1"],
                verification_steps=[
                    "python -m py_compile cli.py",
                    "echo 'help' | python cli.py",
                    "test -f cli.py",
                ],
                acceptance_criteria=[
                    "cli.py 可运行",
                    "help 命令输出帮助信息",
                ],
            ),
            Task(
                id="task-3",
                title="创建项目配置文件",
                description=(
                    "创建 requirements.txt（无外部依赖，写入 # no dependencies）。\n"
                    "创建 README.md，说明 Mini Memos 的用途和命令。"
                ),
                files=["requirements.txt", "README.md"],
                dependencies=["task-2"],
                verification_steps=[
                    "test -f requirements.txt",
                    "test -f README.md",
                ],
                acceptance_criteria=[
                    "requirements.txt 存在",
                    "README.md 存在",
                ],
            ),
        ],
        data_models=(
            "class Memo:\n"
            "    id: str\n"
            "    title: str\n"
            "    content: str\n"
            "    created_at: str\n"
        ),
        api_design="",
    )

    feature_1_plan = ProjectPlan(
        project_name="mini-memos",
        description="追加标签分类功能",
        tech_stack=["Python"],
        tasks=[
            Task(
                id="task-4",
                title="为 Memo 添加标签支持",
                description=(
                    "修改 memo.py:\n"
                    "- Memo 类新增 tags: list[str] 字段\n"
                    "- MemoStore.add() 接受可选 tags 参数\n"
                    "- 新增 MemoStore.find_by_tag(tag) -> list[Memo]\n"
                    "创建 tags.py，实现 TagManager:\n"
                    "- get_all_tags() -> list[str]\n"
                    "- get_tag_counts() -> dict[str, int]"
                ),
                files=["memo.py", "tags.py"],
                verification_steps=[
                    "python -m py_compile memo.py",
                    "python -m py_compile tags.py",
                    "python -c \"from memo import MemoStore; s = MemoStore(); s.add('test', 'hi', tags=['work']); print(s.find_by_tag('work'))\"",
                ],
                acceptance_criteria=[
                    "Memo 支持 tags 字段",
                    "find_by_tag 可按标签过滤",
                ],
            ),
            Task(
                id="task-5",
                title="CLI 支持标签操作",
                description=(
                    "修改 cli.py，新增命令:\n"
                    "- add <title> <content> --tags tag1,tag2: 带标签添加\n"
                    "- tags: 列出所有标签及计数\n"
                    "- find <tag>: 按标签查找备忘"
                ),
                files=["cli.py"],
                dependencies=["task-4"],
                verification_steps=[
                    "python -m py_compile cli.py",
                    "echo 'tags' | python cli.py",
                ],
                acceptance_criteria=[
                    "tags 命令可用",
                    "find 命令可按标签查找",
                ],
            ),
        ],
        data_models="",
        api_design="",
    )

    feature_2_plan = ProjectPlan(
        project_name="mini-memos",
        description="追加搜索功能",
        tech_stack=["Python"],
        tasks=[
            Task(
                id="task-6",
                title="实现全文搜索",
                description=(
                    "创建 search.py，实现 MemoSearch:\n"
                    "- search(store, query) -> list[Memo]: 在 title + content 中搜索\n"
                    "- 支持大小写不敏感匹配\n"
                    "- 结果按相关度排序（title 匹配优先于 content）"
                ),
                files=["search.py"],
                verification_steps=[
                    "python -m py_compile search.py",
                    "python -c \"from search import MemoSearch; from memo import MemoStore; s = MemoStore(); s.add('hello', 'world'); print(MemoSearch.search(s, 'hello'))\"",
                ],
                acceptance_criteria=[
                    "MemoSearch.search() 可正常搜索",
                    "大小写不敏感",
                ],
            ),
            Task(
                id="task-7",
                title="CLI 支持搜索命令",
                description=(
                    "修改 cli.py，新增命令:\n"
                    "- search <query>: 全文搜索备忘\n"
                    "显示匹配结果列表（ID、标题、匹配片段）"
                ),
                files=["cli.py"],
                dependencies=["task-6"],
                verification_steps=[
                    "python -m py_compile cli.py",
                    "echo 'search test' | python cli.py",
                ],
                acceptance_criteria=[
                    "search 命令可用",
                    "显示搜索结果",
                ],
            ),
        ],
        data_models="",
        api_design="",
    )

    feature_3_plan = ProjectPlan(
        project_name="mini-memos",
        description="追加收藏置顶功能",
        tech_stack=["Python"],
        tasks=[
            Task(
                id="task-8",
                title="实现收藏与置顶逻辑",
                description=(
                    "修改 memo.py:\n"
                    "- Memo 类新增 pinned: bool 字段（默认 False）\n"
                    "- MemoStore 新增 toggle_pin(id) -> Memo | None: 切换置顶状态\n"
                    "- MemoStore.list_all() 修改为置顶项优先排列\n"
                    "创建 favorites.py，实现 FavoriteManager:\n"
                    "- add_favorite(memo_id) -> bool\n"
                    "- remove_favorite(memo_id) -> bool\n"
                    "- list_favorites(store) -> list[Memo]\n"
                    "- is_favorite(memo_id) -> bool"
                ),
                files=["memo.py", "favorites.py"],
                verification_steps=[
                    "python -m py_compile memo.py",
                    "python -m py_compile favorites.py",
                    "python -c \"from memo import MemoStore; s = MemoStore(); m = s.add('test', 'hi'); print(s.toggle_pin(m.id))\"",
                ],
                acceptance_criteria=[
                    "Memo 支持 pinned 字段",
                    "toggle_pin 可切换置顶状态",
                    "list_all 置顶项优先",
                ],
            ),
            Task(
                id="task-9",
                title="CLI 支持收藏和置顶命令",
                description=(
                    "修改 cli.py，新增命令:\n"
                    "- pin <id>: 切换备忘置顶状态\n"
                    "- fav <id>: 切换收藏状态\n"
                    "- favorites: 列出所有收藏的备忘\n"
                    "- list 命令中用 ★ 标记置顶项和 ♥ 标记收藏项"
                ),
                files=["cli.py"],
                dependencies=["task-8"],
                verification_steps=[
                    "python -m py_compile cli.py",
                    "echo 'favorites' | python cli.py",
                ],
                acceptance_criteria=[
                    "pin 命令可用",
                    "favorites 命令可列出收藏",
                ],
            ),
        ],
        data_models="",
        api_design="",
    )

    return {  # noqa: E501
        "requirement": "创建 Mini Memos 轻量备忘录应用，支持创建、列表、删除备忘",
        "complexity": "medium",
        "plan": primary_plan,
        "features": [
            {
                "requirement": "为 Mini Memos 添加标签分类功能，支持按标签过滤和管理",
                "plan": feature_1_plan,
            },
            {
                "requirement": "为 Mini Memos 添加全文搜索功能，支持在标题和内容中搜索",
                "plan": feature_2_plan,
            },
            {
                "requirement": "为 Mini Memos 添加收藏置顶功能，支持置顶排序和收藏管理",
                "plan": feature_3_plan,
            },
        ],
    }


# ── task_board: 压力测试（钻石 DAG + 大量共享文件 + 深回归级联） ──

def _case_task_board() -> dict:
    """Task Board — 压力测试: 5 任务钻石 DAG + 3 个追加功能 + 14 个总任务

    压力点:
    - 钻石依赖: task-1 → task-2/task-3 → task-4
    - models.py 被 5 个任务触碰（task-1/2/6/8/11）
    - routes.py 被 4 个任务触碰（task-4/7/10/12）
    - app.py 被 3 个任务触碰（task-4/7/12）
    - Feature 3 触发 8+ 任务回归级联
    """
    primary_plan = ProjectPlan(
        project_name="task-board",
        description="任务管理 REST API，支持项目/任务 CRUD、用户认证、数据验证",
        tech_stack=["Python", "Flask", "SQLite"],
        tasks=[
            Task(
                id="task-1",
                title="数据模型与数据库层",
                description=(
                    "创建 models.py，定义数据模型:\n"
                    "- Project 类（id, name, description, created_at）\n"
                    "- TaskItem 类（id, title, status, project_id, assignee, priority, created_at）\n"
                    "- User 类（id, username, email, role）\n"
                    "创建 database.py，实现 DatabaseManager:\n"
                    "- init_db(): 创建所有表\n"
                    "- get_connection(): 返回 SQLite 连接\n"
                    "- execute_query(sql, params): 通用查询执行"
                ),
                files=["models.py", "database.py"],
                verification_steps=[
                    "python -m py_compile models.py",
                    "python -m py_compile database.py",
                    "python -c \"from database import init_db; init_db(); print('DB OK')\"",
                ],
                acceptance_criteria=[
                    "三个数据模型定义正确",
                    "数据库初始化可执行",
                ],
            ),
            Task(
                id="task-2",
                title="用户认证模块",
                description=(
                    "创建 auth.py，实现 AuthManager 类:\n"
                    "- register(username, email, password) -> User\n"
                    "- login(username, password) -> str（token）\n"
                    "- verify_token(token) -> User | None\n"
                    "- hash_password(password) -> str\n"
                    "修改 models.py，User 类新增 password_hash 字段"
                ),
                files=["auth.py", "models.py"],
                dependencies=["task-1"],
                verification_steps=[
                    "python -m py_compile auth.py",
                    "python -m py_compile models.py",
                    "python -c \"from auth import AuthManager; print('Auth OK')\"",
                ],
                acceptance_criteria=[
                    "AuthManager 可导入",
                    "密码哈希和 token 机制可用",
                ],
            ),
            Task(
                id="task-3",
                title="数据验证器",
                description=(
                    "创建 validators.py，实现:\n"
                    "- validate_project(data) -> tuple[bool, list[str]]\n"
                    "- validate_task(data) -> tuple[bool, list[str]]\n"
                    "- validate_user(data) -> tuple[bool, list[str]]\n"
                    "- sanitize_input(text) -> str\n"
                    "每个验证器检查必填字段、字段长度、格式合法性"
                ),
                files=["validators.py"],
                dependencies=["task-1"],
                verification_steps=[
                    "python -m py_compile validators.py",
                    "python -c \"from validators import validate_project; print(validate_project({'name': 'test'}))\"",
                ],
                acceptance_criteria=[
                    "三个验证器函数可用",
                    "验证返回 (bool, errors) 元组",
                ],
            ),
            Task(
                id="task-4",
                title="REST API 路由",
                description=(
                    "创建 app.py，Flask 应用:\n"
                    "- GET/POST /api/projects\n"
                    "- GET/PUT/DELETE /api/projects/<id>\n"
                    "- GET/POST /api/tasks\n"
                    "- GET/PUT/DELETE /api/tasks/<id>\n"
                    "- POST /api/auth/register\n"
                    "- POST /api/auth/login\n"
                    "创建 routes.py，路由蓝图注册"
                ),
                files=["routes.py", "app.py"],
                dependencies=["task-2", "task-3"],
                verification_steps=[
                    "python -m py_compile app.py",
                    "python -m py_compile routes.py",
                    "python -c \"from app import app; print(app.name)\"",
                ],
                acceptance_criteria=[
                    "Flask app 可创建",
                    "所有 API 路由已注册",
                ],
            ),
            Task(
                id="task-5",
                title="项目配置与文档",
                description=(
                    "创建 config.py，集中管理配置:\n"
                    "- DATABASE_PATH, SECRET_KEY, DEBUG 等\n"
                    "- load_config() -> dict\n"
                    "创建 requirements.txt 和 README.md"
                ),
                files=["config.py", "requirements.txt", "README.md"],
                dependencies=["task-4"],
                verification_steps=[
                    "python -m py_compile config.py",
                    "test -f requirements.txt",
                    "test -f README.md",
                ],
                acceptance_criteria=[
                    "配置模块可用",
                    "项目文件齐全",
                ],
            ),
        ],
        data_models=(
            "class Project:\n"
            "    id: int\n    name: str\n    description: str\n    created_at: str\n\n"
            "class TaskItem:\n"
            "    id: int\n    title: str\n    status: str\n"
            "    project_id: int\n    assignee: str\n    priority: int\n\n"
            "class User:\n"
            "    id: int\n    username: str\n    email: str\n    role: str\n"
        ),
        api_design=(
            "GET    /api/projects       → [{id, name, description}]\n"
            "POST   /api/projects       ← {name, description}  → {id, ...}\n"
            "GET    /api/projects/<id>   → {id, name, description, tasks}\n"
            "PUT    /api/projects/<id>   ← {name, description}\n"
            "DELETE /api/projects/<id>   → 204\n"
            "GET    /api/tasks           → [{id, title, status, assignee}]\n"
            "POST   /api/tasks           ← {title, project_id, priority}\n"
            "PUT    /api/tasks/<id>      ← {status, assignee}\n"
            "DELETE /api/tasks/<id>      → 204\n"
            "POST   /api/auth/register   ← {username, email, password}\n"
            "POST   /api/auth/login      ← {username, password}  → {token}\n"
        ),
    )

    feature_1_plan = ProjectPlan(
        project_name="task-board",
        description="追加团队与任务分配功能",
        tech_stack=["Python", "Flask"],
        tasks=[
            Task(
                id="task-6",
                title="团队模型与分配逻辑",
                description=(
                    "创建 team.py，实现 TeamManager:\n"
                    "- create_team(name, members) -> Team\n"
                    "- add_member(team_id, user_id) -> bool\n"
                    "- remove_member(team_id, user_id) -> bool\n"
                    "- get_team_members(team_id) -> list[User]\n"
                    "修改 models.py，新增 Team 类（id, name, created_at）\n"
                    "和 TeamMember 关联类（team_id, user_id, role）"
                ),
                files=["team.py", "models.py"],
                verification_steps=[
                    "python -m py_compile team.py",
                    "python -m py_compile models.py",
                    "python -c \"from team import TeamManager; print('Team OK')\"",
                ],
                acceptance_criteria=[
                    "Team 模型存在",
                    "TeamManager CRUD 可用",
                ],
            ),
            Task(
                id="task-7",
                title="分配 API 路由",
                description=(
                    "修改 routes.py，新增团队路由蓝图:\n"
                    "- GET/POST /api/teams\n"
                    "- POST /api/teams/<id>/members\n"
                    "- DELETE /api/teams/<id>/members/<user_id>\n"
                    "- POST /api/tasks/<id>/assign\n"
                    "修改 app.py 注册新蓝图"
                ),
                files=["routes.py", "app.py"],
                dependencies=["task-6"],
                verification_steps=[
                    "python -m py_compile routes.py",
                    "python -m py_compile app.py",
                ],
                acceptance_criteria=[
                    "团队路由已注册",
                    "分配 API 可用",
                ],
            ),
        ],
        data_models="",
        api_design="",
    )

    feature_2_plan = ProjectPlan(
        project_name="task-board",
        description="追加数据分析与仪表盘功能",
        tech_stack=["Python"],
        tasks=[
            Task(
                id="task-8",
                title="分析引擎",
                description=(
                    "创建 analytics.py，实现 AnalyticsEngine:\n"
                    "- task_completion_rate(project_id) -> float\n"
                    "- avg_task_duration(project_id) -> float\n"
                    "- team_workload(team_id) -> dict\n"
                    "- overdue_tasks() -> list[TaskItem]\n"
                    "修改 models.py，TaskItem 新增 due_date, completed_at 字段"
                ),
                files=["analytics.py", "models.py"],
                verification_steps=[
                    "python -m py_compile analytics.py",
                    "python -m py_compile models.py",
                    "python -c \"from analytics import AnalyticsEngine; print('Analytics OK')\"",
                ],
                acceptance_criteria=[
                    "分析引擎可导入",
                    "统计函数返回正确类型",
                ],
            ),
            Task(
                id="task-9",
                title="仪表盘数据聚合",
                description=(
                    "创建 dashboard.py，实现 DashboardService:\n"
                    "- get_overview() -> dict（项目数/任务数/完成率）\n"
                    "- get_project_stats(project_id) -> dict\n"
                    "- get_recent_activity(limit) -> list[dict]"
                ),
                files=["dashboard.py"],
                dependencies=["task-8"],
                verification_steps=[
                    "python -m py_compile dashboard.py",
                    "python -c \"from dashboard import DashboardService; print('Dashboard OK')\"",
                ],
                acceptance_criteria=[
                    "仪表盘服务可用",
                    "概览数据聚合正确",
                ],
            ),
            Task(
                id="task-10",
                title="分析 API 与数据导出",
                description=(
                    "创建 export.py，实现数据导出:\n"
                    "- export_csv(project_id) -> str\n"
                    "- export_json(project_id) -> dict\n"
                    "修改 routes.py，新增分析路由:\n"
                    "- GET /api/dashboard\n"
                    "- GET /api/projects/<id>/stats\n"
                    "- GET /api/projects/<id>/export?format=csv|json"
                ),
                files=["export.py", "routes.py"],
                dependencies=["task-8", "task-9"],
                verification_steps=[
                    "python -m py_compile export.py",
                    "python -m py_compile routes.py",
                ],
                acceptance_criteria=[
                    "导出功能可用",
                    "分析路由已注册",
                ],
            ),
        ],
        data_models="",
        api_design="",
    )

    feature_3_plan = ProjectPlan(
        project_name="task-board",
        description="追加通知与 Webhook 功能",
        tech_stack=["Python"],
        tasks=[
            Task(
                id="task-11",
                title="通知系统",
                description=(
                    "创建 notify.py，实现 NotificationManager:\n"
                    "- send(user_id, message, type) -> bool\n"
                    "- get_unread(user_id) -> list[Notification]\n"
                    "- mark_read(notification_id) -> bool\n"
                    "修改 models.py，新增 Notification 类（id, user_id, message, type, read, created_at）\n"
                    "修改 config.py，新增 NOTIFICATION_ENABLED, WEBHOOK_SECRET 配置项"
                ),
                files=["notify.py", "models.py", "config.py"],
                verification_steps=[
                    "python -m py_compile notify.py",
                    "python -m py_compile models.py",
                    "python -m py_compile config.py",
                    "python -c \"from notify import NotificationManager; print('Notify OK')\"",
                ],
                acceptance_criteria=[
                    "通知管理器可用",
                    "Notification 模型存在",
                ],
            ),
            Task(
                id="task-12",
                title="Webhook 与通知路由",
                description=(
                    "创建 webhook.py，实现 WebhookManager:\n"
                    "- register_hook(url, events) -> Webhook\n"
                    "- trigger(event, payload) -> list[bool]\n"
                    "- list_hooks() -> list[Webhook]\n"
                    "修改 routes.py，新增路由:\n"
                    "- GET/POST /api/notifications\n"
                    "- PUT /api/notifications/<id>/read\n"
                    "- GET/POST /api/webhooks\n"
                    "- DELETE /api/webhooks/<id>\n"
                    "修改 app.py 注册通知蓝图"
                ),
                files=["webhook.py", "routes.py", "app.py"],
                dependencies=["task-11"],
                verification_steps=[
                    "python -m py_compile webhook.py",
                    "python -m py_compile routes.py",
                    "python -m py_compile app.py",
                ],
                acceptance_criteria=[
                    "Webhook 管理器可用",
                    "通知和 Webhook 路由已注册",
                ],
            ),
        ],
        data_models="",
        api_design="",
    )

    return {
        "requirement": "创建 Task Board 任务管理 REST API，支持项目管理、任务 CRUD、用户认证和数据验证",
        "complexity": "complex",
        "plan": primary_plan,
        "features": [
            {
                "requirement": "为 Task Board 添加团队管理与任务分配功能",
                "plan": feature_1_plan,
            },
            {
                "requirement": "为 Task Board 添加数据分析仪表盘与导出功能",
                "plan": feature_2_plan,
            },
            {
                "requirement": "为 Task Board 添加通知系统与 Webhook 集成",
                "plan": feature_3_plan,
            },
        ],
    }
