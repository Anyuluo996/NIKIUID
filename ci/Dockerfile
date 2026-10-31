# NIKIUID 本地容器 CI 镜像
#
# 分层设计(依赖缓存):
#   base   -> python + git(改动少,几乎不重建)
#   core   -> 固定 commit 的 gsuid_core + 全量运行依赖(上游更新才重建)
#   tools  -> 插件开发工具链(ruff/pytest/pycryptodome,跟随插件 pyproject)
#
# 构建示例(需要代理访问 GitHub/PyPI 时):
#   docker build -t nikiuid-ci ci/ \
#     --build-arg http_proxy=http://host.docker.internal:17890 \
#     --build-arg https_proxy=http://host.docker.internal:17890
#
# 插件代码不进镜像:运行时把仓库根挂载到 /opt/gsuid_core/gsuid_core/plugins/NIKIUID
# (与真实部署布局一致,conftest.py 的 sys.path 推导依赖这个层级)。

FROM python:3.12-slim

ARG DEBIAN_FRONTEND=noninteractive
ARG GSCORE_REPO=https://github.com/Genshin-bots/gsuid_core.git
# 与本机开发环境锁同版本:上游升级后改这里并重建镜像
ARG GSCORE_REF=f0fea6f9

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# gsuid_core 固定版本 + 运行依赖(慢层,靠 GSCORE_REF 不变来缓存)
# 必须 editable 安装:若装成 site-packages 里的常规包,sys.path 扫描时
# 常规包优先于 checkout 的 namespace 包,gsuid_core.plugins.NIKIUID
# (插件挂载在 checkout 下)将永远解析不到 —— 本地开发同理,venv 里
# 不装 gsuid_core 本体、直接跑 checkout
RUN git clone --quiet "$GSCORE_REPO" /opt/gsuid_core \
    && git -C /opt/gsuid_core checkout --quiet "$GSCORE_REF"

RUN pip install --no-cache-dir -e /opt/gsuid_core

# 插件开发/测试工具链(版本与 pyproject dev extras 对齐)
# pytakumi 为渲染层可选依赖(linux 有轮子则装,没有不影响 lint/test/smoke)
RUN pip install --no-cache-dir \
        "ruff>=0.15" \
        "pytest>=8.3" \
        "pytest-asyncio>=0.24" \
        "pycryptodome>=3.20" \
    && pip install --no-cache-dir pytakumi \
    || echo "[ci] pytakumi 不可用,跳过(渲染功能不在 CI 范围)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 插件挂载点(目录先建好,权限属 root,容器内只读挂载即可)
RUN mkdir -p /opt/gsuid_core/gsuid_core/plugins/NIKIUID

WORKDIR /opt/gsuid_core/gsuid_core/plugins/NIKIUID
