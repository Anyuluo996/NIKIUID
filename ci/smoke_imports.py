"""CI smoke 层:逐个导入插件全部子模块。

覆盖单元测试不经过的导入副作用:
- 外层/内层 __init__ 的 Plugins() 注册、gss 钩子挂载
- niki_login 的 FastAPI 路由注册(gsuid_core.web_app)
- 各命令模块的 SV 监听注册

在 CI 容器内由 ci/run.sh 以 `python ci/smoke_imports.py` 执行,
cwd 为插件挂载目录(gsuid_core/gsuid_core/plugins/NIKIUID)。
"""

import sys
import importlib

MODULES = [
    "gsuid_core.plugins.NIKIUID",
    "gsuid_core.plugins.NIKIUID.NIKIUID.__full__",
    "gsuid_core.plugins.NIKIUID.NIKIUID.niki_card",
    "gsuid_core.plugins.NIKIUID.NIKIUID.niki_calendar",
    "gsuid_core.plugins.NIKIUID.NIKIUID.niki_config",
    "gsuid_core.plugins.NIKIUID.NIKIUID.niki_help",
    "gsuid_core.plugins.NIKIUID.NIKIUID.niki_login",
    "gsuid_core.plugins.NIKIUID.NIKIUID.niki_refresh",
    "gsuid_core.plugins.NIKIUID.NIKIUID.niki_stamina",
]


def main() -> int:
    failed: list[tuple[str, str]] = []
    for mod in MODULES:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001 - 逐模块收集,最后统一退出
            failed.append((mod, repr(exc)))
            print(f"FAIL {mod}: {exc!r}", file=sys.stderr)
        else:
            print("ok", mod)

    if failed:
        print(f"smoke: {len(failed)}/{len(MODULES)} modules FAILED", file=sys.stderr)
        return 1
    print(f"smoke: {len(MODULES)} modules imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
