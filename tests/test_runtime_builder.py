"""Runtime Builder 测试"""

import os
import pytest
from autoc.core.runtime.builder import RuntimeBuilder, DependencyInfo


class TestDependencyScan:
    def test_scan_empty_dir(self, tmp_path):
        builder = RuntimeBuilder()
        deps = builder.scan_dependencies(str(tmp_path))
        assert deps == []

    def test_scan_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==3.0\nrequests\n")
        builder = RuntimeBuilder()
        deps = builder.scan_dependencies(str(tmp_path))
        assert len(deps) == 1
        assert deps[0].dep_type == "pip"
        assert deps[0].file_path == "requirements.txt"

    def test_scan_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name":"test","dependencies":{}}')
        builder = RuntimeBuilder()
        deps = builder.scan_dependencies(str(tmp_path))
        assert len(deps) == 1
        assert deps[0].dep_type == "npm"

    def test_scan_multiple(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\n")
        (tmp_path / "package.json").write_text('{}')
        builder = RuntimeBuilder()
        deps = builder.scan_dependencies(str(tmp_path))
        assert len(deps) == 2

    def test_scan_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/app\ngo 1.21\n")
        builder = RuntimeBuilder()
        deps = builder.scan_dependencies(str(tmp_path))
        assert deps[0].dep_type == "go"


class TestImageTag:
    def test_empty_deps(self):
        builder = RuntimeBuilder()
        assert builder.compute_image_tag([]) == ""

    def test_deterministic(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==3.0\n")
        builder = RuntimeBuilder()
        deps = builder.scan_dependencies(str(tmp_path))
        tag1 = builder.compute_image_tag(deps)
        tag2 = builder.compute_image_tag(deps)
        assert tag1 == tag2
        assert tag1.startswith("autoc-custom:")

    def test_different_content_different_tag(self, tmp_path):
        builder = RuntimeBuilder()
        dep1 = [DependencyInfo("requirements.txt", "pip", "aaa", "pip install")]
        dep2 = [DependencyInfo("requirements.txt", "pip", "bbb", "pip install")]
        assert builder.compute_image_tag(dep1) != builder.compute_image_tag(dep2)


class TestDockerfile:
    def test_basic_pip(self):
        builder = RuntimeBuilder(base_image="python:3.12-slim")
        deps = [DependencyInfo("requirements.txt", "pip", "abc", "pip install --no-cache-dir -r requirements.txt")]
        df = builder.generate_dockerfile(deps)
        assert "FROM python:3.12-slim" in df
        assert "COPY requirements.txt" in df
        assert "pip install" in df

    def test_cn_mirror(self):
        builder = RuntimeBuilder(use_cn_mirror=True)
        deps = [DependencyInfo("requirements.txt", "pip", "abc", "pip install -r requirements.txt")]
        df = builder.generate_dockerfile(deps)
        assert "tuna.tsinghua" in df

    def test_npm_cn_mirror(self):
        builder = RuntimeBuilder(use_cn_mirror=True)
        deps = [DependencyInfo("package.json", "npm", "abc", "npm install --production")]
        df = builder.generate_dockerfile(deps)
        assert "npmmirror" in df

    def test_multi_deps(self):
        builder = RuntimeBuilder()
        deps = [
            DependencyInfo("requirements.txt", "pip", "a", "pip install -r requirements.txt"),
            DependencyInfo("package.json", "npm", "b", "npm install --production"),
        ]
        df = builder.generate_dockerfile(deps)
        assert "COPY requirements.txt" in df
        assert "COPY package.json" in df
        assert "pip install" in df
        assert "npm install" in df


class TestBuildIfNeeded:
    def test_no_deps_returns_base(self, tmp_path):
        builder = RuntimeBuilder(base_image="python:3.12-slim")
        result = builder.build_if_needed(str(tmp_path))
        assert result == "python:3.12-slim"
