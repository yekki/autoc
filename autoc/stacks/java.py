"""Java / Kotlin 技术栈适配器"""
import os, re
from autoc.stacks import StackAdapter, ProjectContext

class JavaAdapter(StackAdapter):
    @staticmethod
    def detect(workspace_dir: str) -> str | None:
        for name in ("pom.xml", "build.gradle", "build.gradle.kts"):
            p = os.path.join(workspace_dir, name)
            if os.path.isfile(p): return p
        return None

    @staticmethod
    def priority() -> int:
        return 70

    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        basename = os.path.basename(manifest_path) if manifest_path else ""
        is_gradle = "gradle" in basename
        lang = "Kotlin" if basename.endswith(".kts") else "Java"
        ctx = ProjectContext(
            language=lang, manifest_file=basename,
            install_command="./gradlew dependencies" if is_gradle else "mvn install -DskipTests",
            build_command="./gradlew build" if is_gradle else "mvn package -DskipTests",
            test_command="./gradlew test" if is_gradle else "mvn test",
        )
        if not manifest_path: return ctx
        try:
            with open(manifest_path, encoding="utf-8") as f:
                content = f.read()
            if is_gradle:
                deps = re.findall(r"['\"](.+?:.+?:.+?)['\"]", content)
                ctx.dependencies = [d.split(":")[1] for d in deps[:20]]
                if "spring-boot" in content.lower():
                    ctx.framework = "Spring Boot"
                    ctx.project_type = "web_backend"
                    ctx.default_port = 8080
                    ctx.start_command = "./gradlew bootRun"
                elif "ktor" in content.lower():
                    ctx.framework = "Ktor"
                    ctx.project_type = "web_backend"
                    ctx.default_port = 8080
            else:
                deps = re.findall(r"<artifactId>(.+?)</artifactId>", content)
                ctx.dependencies = deps[:20]
                if "spring-boot" in content:
                    ctx.framework = "Spring Boot"
                    ctx.project_type = "web_backend"
                    ctx.default_port = 8080
                    ctx.start_command = "mvn spring-boot:run"
        except OSError:
            pass
        return ctx

    @staticmethod
    def hidden_dirs() -> set[str]:
        return {"target", ".gradle", ".m2", "build", "out"}

    @staticmethod
    def noread_files() -> set[str]:
        return set()

    @staticmethod
    def noread_extensions() -> set[str]:
        return {".class", ".jar"}

    @staticmethod
    def config_files() -> set[str]:
        return {"pom.xml", "build.gradle", "build.gradle.kts"}

    @staticmethod
    def coding_guidelines() -> str:
        return ("## Java/Kotlin 编码规范\n"
                "- Maven: pom.xml 管理依赖; Gradle: build.gradle\n"
                "- 遵循 Java 命名规范，使用 Lombok 减少样板代码\n")

    @staticmethod
    def testing_guidelines() -> str:
        return ("## Java/Kotlin 测试要求\n"
                "- 测试文件放在 src/test/java/ 目录\n"
                "- 使用 JUnit 5 (@Test 注解)\n")

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        return {"complex": [], "medium": ["Spring Boot", "Ktor", "Micronaut", "Quarkus"]}
