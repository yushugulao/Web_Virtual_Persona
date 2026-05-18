from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_windows_graphical_quick_deploy_entrypoints_are_present():
    required_paths = [
        "bootstrap.ps1",
        "install.ps1",
        "install.sh",
        "scripts/deploy/windows_local_gui_deploy.ps1",
        "scripts/deploy/windows_uninstall.ps1",
        "configs/deployment_dependencies.json",
        "configs/deployment_profiles/quick_gpu.json",
        "configs/deployment_profiles/standard_gpu.json",
    ]

    missing = [path for path in required_paths if not (ROOT / path).is_file()]

    assert missing == []


def test_bootstrap_and_readme_point_to_graphical_deployer():
    bootstrap = read_text("bootstrap.ps1")
    install = read_text("install.ps1")
    readme = read_text("README.md")
    installation = read_text("docs/installation.md")

    assert "WEB_VIRTUAL_PERSONA_BRANCH" in bootstrap
    assert "windows_local_gui_deploy.ps1" in install
    assert "Save-RemoteUtf8Script" in install
    assert "Get-PowerShellExecutable" in install
    assert "bootstrap.ps1 | iex" in readme
    assert "图形界面" in readme
    assert "图形化本地部署" in installation


def test_graphical_deployer_exposes_user_facing_configuration_and_success_flow():
    gui_script = read_text("scripts/deploy/windows_local_gui_deploy.ps1")

    expected_user_facing_text = [
        "Web虚拟分身 Windows 本地快速部署",
        "DeepSeek 密钥",
        "文档读取与 OCR",
        "PaddleOCR-VL",
        "部署完成，可以开始使用了",
        "卸载 Web虚拟分身.exe",
        "覆盖已有安装目录",
    ]

    for text in expected_user_facing_text:
        assert text in gui_script


def test_graphical_deployer_writes_runtime_configuration_and_uninstaller():
    gui_script = read_text("scripts/deploy/windows_local_gui_deploy.ps1")

    expected_configuration_keys = [
        "PERSONA_RAG_DEEPSEEK_API_KEY",
        "PERSONA_RAG_SMTP_HOST",
        "DOCUMENT_READER_ENABLE_PADDLEOCR_VL",
        "DOCUMENT_READER_ENABLE_MARKER_SURYA",
        "PERSONA_RAG_AUTH_ADMIN_PASSWORD",
        "VITE_API_BASE_URL",
    ]

    for key in expected_configuration_keys:
        assert key in gui_script

    assert "Write-UninstallerPackage" in gui_script
    assert "install_manifest.json" in gui_script
