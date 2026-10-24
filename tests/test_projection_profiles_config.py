from __future__ import annotations

from pathlib import Path

from system_core.core.mask_engine import include_file, match_dir_rule
from system_core.core.projection_engine import ProjectionProfile, get_projection_profile


ROOT = Path(__file__).resolve().parents[1]


def _profile(profile_id: str) -> ProjectionProfile:
    # Loaded as the program loads it: `extends` resolved.
    return get_projection_profile(profile_id, ROOT / "config" / "projection_profiles.json")


def test_python_projection_includes_dev_git_files() -> None:
    profile = _profile("audion_python_project_projection")
    included = [
        ".gitmodules",
        ".git-blame-ignore-revs",
        "CODEOWNERS",
        "Makefile",
        "CMakeLists.txt",
        "Cargo.lock",
        "go.mod",
        "src/main.rs",
        "src/App.vue",
        "package/yarn.lock",
        ".vscode/tasks.json",
    ]

    for rel_path in included:
        assert include_file(rel_path, 100, profile) == (True, "ok")


def test_python_projection_excludes_local_and_build_noise() -> None:
    profile = _profile("audion_python_project_projection")
    excluded = [
        "config/apps.local.json",
        "web/app.min.js",
        "web/app.js.map",
        "native/module.obj",
        "target/classes/App.class",
    ]

    for rel_path in excluded:
        assert include_file(rel_path, 100, profile)[0] is False

    for rel_path in ["dist/app.js", ".next/server/page.js", "target/debug/app"]:
        assert any(match_dir_rule(rel_path, rules) for rules in (profile.exclude_dir_contents, profile.hide_dirs, profile.output_dirs))


def test_a_rule_with_a_leading_slash_names_a_folder_at_the_root_only() -> None:
    assert match_dir_rule("App", ["/App"])
    assert match_dir_rule("App/runtimes/win", ["/App"])
    assert not match_dir_rule("system_core/app", ["/App"])
    assert match_dir_rule("system_core/app", ["app"])


def test_the_project_profile_keeps_the_built_window_and_the_lab_out_as_folders() -> None:
    profile = _profile("audion_python_project_projection")
    # The built window is a guess of the profile (`app/` of Next.js is sources): Audion projects keep it out by .gitignore.
    assert match_dir_rule("App", profile.output_dirs) and not match_dir_rule("App", profile.exclude_dir_contents)
    assert match_dir_rule("examples/lab", profile.exclude_dir_contents)
    assert not match_dir_rule("examples/demo_full_project/system_core/app", profile.output_dirs)
    for path in ("Source/MainWindow.axaml", "Source/AudionHubManager.csproj", "Source/Assets/Fonts/a.ttf", "Source/app.manifest"):
        assert include_file(path, 100, profile)[0], path
    for path in ("App/AudionHubManager.deps.json", "config/window_settings.json", "licenses/COMPONENTS.json"):
        assert not include_file(path, 100, profile)[0], path


def test_the_project_profile_takes_the_sources_of_every_kind() -> None:
    profile = _profile("audion_python_project_projection")
    for rel_path in (
        "src/app.py", "web/src/App.tsx", "web/vite.config.ts", "api/main.go", "crates/core/src/lib.rs", "App/Models/User.cs",
        "Program.fs", "app/src/main/java/Main.java", "build.gradle.kts", "ios/App/ContentView.swift", "lib/main.dart",
        "pubspec.yaml", "config/routes.rb", "public/index.php", "lib/app.ex", "infra/main.tf", "flake.nix", "k8s/deploy.yaml",
        "Dockerfile.prod", "docs/index.mdx", "paper/main.tex", ".github/workflows/ci.yml", ".forgejo/workflows/build.yml",
        ".devcontainer/devcontainer.json", "Assets/Scripts/Player.cs", "Assets/Player.prefab.meta", "project.godot",
        "scripts/build.ps1", "schema.graphql", "api.proto", "uv.lock", ".env.example", "notebook.ipynb",
    ):
        assert include_file(rel_path, 1000, profile)[0], rel_path
    # Pictures and fonts of the sources pass up to a megabyte; bigger ones are media.
    assert include_file("web/public/logo.png", 50_000, profile)[0]
    assert not include_file("web/public/poster.png", 3_000_000, profile)[0]


def test_the_project_profile_leaves_out_secrets_builds_media_and_data() -> None:
    profile = _profile("audion_python_project_projection")
    for rel_path in (
        ".env", "deploy/id_ed25519", "certs/server.key", "keys/store.jks", "infra/terraform.tfstate", "prod.tfvars",
        "gcp/service-account-prod.json", "credentials.json", "app.csproj.user", "Thumbs.db", "dist.zip", "release.tar.gz",
        "bin.exe", "lib/native.so.1", "pkg.egg-info/PKG-INFO", "cmake-build-debug/app", "video/intro.mp4", "art/cover.psd",
        "data/train.parquet", "models/llama.gguf", "models/net.pt", "db/app.sqlite3", "logs/run.log", "notes.txt~",
        "web/bundle.min.js", "App/AudionHubManager.deps.json", "config/window_settings.json", "licenses/COMPONENTS.json",
    ):
        assert not include_file(rel_path, 1000, profile)[0], rel_path
    for folder in ("web/node_modules", "rust/target", "py/.venv", "py/__pycache__", "ios/DerivedData", "app/.dart_tool",
                   "infra/.terraform", "web/.next", "Game/Intermediate", "godot/.godot", ".idea", "obj", ".ssh", ".aws"):
        assert match_dir_rule(folder, profile.hide_dirs), folder
    for rel_path in ("deploy/credentials", ".ssh/known_hosts", "keys/id_ed25519.pub", "id_rsa-backup", "release.bundle"):
        assert not include_file(rel_path, 100, profile)[0], rel_path


def test_the_project_profile_holds_what_four_real_projects_showed() -> None:
    # KeePassXC (C++, Qt, CMake, WiX), Build Orchestrator (keys in text files), Media Tools, Audion Design.
    profile = _profile("audion_python_project_projection")
    for rel_path in ("src/gui/MainWindow.ui", "src/gui/styles/styles.qrc", "src/gui/styles/dark/darkstyle.qss", "qml/Main.qml",
                     "src/config-keepassx.h.in", "cmake/VersionInfo.in", "share/windows/KPXC_ExitDlg.wxs", "setup.iss",
                     "share/linux/org.keepassxc.KeePassXC.desktop", "share/macosx/keepassxc.entitlements", ".tx/config",
                     "po/ru.po", "templates/page.j2", "docs/arch.puml", "docs/flow.drawio"):
        assert include_file(rel_path, 1000, profile)[0], rel_path
    for rel_path in ("config/keys/api_key_openai.txt", "config/github/api_key_github.txt", "config/api_key_gemini.txt",
                     "config/github_token.dpapi", "config/gui_key_cache.json", "config/github_token.txt", "token.json",
                     "tests/data/NewDatabase.kdbx", "config/rclone/rclone.conf", "wg0.conf", "config/awg0.conf",
                     "config/s3_credentials.txt", "secrets.toml", "config/token_cache.json"):
        assert not include_file(rel_path, 100, profile)[0], rel_path
    # A program about keys keeps its code: only the text files of keys stay out.
    assert include_file("src/keys/FileKey.cpp", 1000, profile)[0] and include_file("core/api_keys.py", 1000, profile)[0]
    for folder in ("cmake-build-release", "build-tools/msys64", "vcpkg_installed"):
        assert match_dir_rule(folder, profile.hide_dirs) or match_dir_rule(folder, profile.exclude_dir_contents), folder
    assert profile.respect_gitignore


def test_a_folder_rule_may_be_a_mask() -> None:
    assert match_dir_rule("cmake-build-debug/CMakeFiles", ["cmake-build-*"])
    assert match_dir_rule("sub/cmake-build-x", ["cmake-build-*"])
    assert match_dir_rule("build-ui", ["/build-*"]) and not match_dir_rule("src/build-ui", ["/build-*"])
    assert not match_dir_rule("cmake", ["cmake-build-*"])


def test_the_strict_profile_extends_the_project_profile() -> None:
    project, strict = _profile("audion_python_project_projection"), _profile("audion_python_project_projection_strict")
    assert strict.include_globs == project.include_globs and strict.exclude_globs == project.exclude_globs
    assert strict.hide_dirs == project.hide_dirs and strict.compare_mode == "strict_blake3"
    assert strict.title != project.title
