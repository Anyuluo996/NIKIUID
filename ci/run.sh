#!/usr/bin/env bash
# NIKIUID 本地容器 CI 运行器
#
# 用法(Git Bash / pwsh 里 `bash ci/run.sh` 均可):
#   bash ci/run.sh            # 全量:lint + test + smoke
#   bash ci/run.sh --lint     # 仅 ruff 检查(最快)
#   bash ci/run.sh --test     # 仅单元测试
#   bash ci/run.sh --smoke    # 仅全模块导入检查(含路由/SV 注册副作用)
#   bash ci/run.sh --build    # 只构建/刷新镜像
#
# 环境变量:
#   CI_IMAGE   镜像 tag(默认 nikiuid-ci:latest)
#   CI_PROXY   构建期代理(默认 http://host.docker.internal:17890,
#              无代理环境置空: CI_PROXY= bash ci/run.sh)
#
# 代码注入方式:docker cp 打包进一次性容器,不用 bind mount ——
# Windows 上 Docker Desktop 未对盘符授权文件共享时,-v 会静默卡死,
# cp 方式不依赖文件共享设置。每次运行互不影响,容器用完即删。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${CI_IMAGE:-nikiuid-ci:latest}"
PROXY="${CI_PROXY:-http://host.docker.internal:17890}"
CONTAINER_DIR=/opt/gsuid_core/gsuid_core/plugins/NIKIUID
CONTAINER_NAME="nikiuid-ci-$$"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

build_image() {
  local args=(docker build -t "$IMAGE" "$REPO_ROOT/ci")
  if [[ -n "$PROXY" ]]; then
    args+=(
      --build-arg "http_proxy=$PROXY"
      --build-arg "https_proxy=$PROXY"
      --build-arg "HTTP_PROXY=$PROXY"
      --build-arg "HTTPS_PROXY=$PROXY"
    )
  fi
  echo "==> 构建镜像 $IMAGE"
  "${args[@]}"
}

# 起一个常驻容器,把插件源码复制进去(排除本地缓存与 .git)
start_container() {
  docker run -d --name "$CONTAINER_NAME" "$IMAGE" sleep 1800 >/dev/null
  tar -C "$REPO_ROOT" \
    --exclude=.git \
    --exclude=__pycache__ \
    --exclude=.pytest_cache \
    --exclude=.ruff_cache \
    --exclude=.venv \
    -cf - . | docker cp - "$CONTAINER_NAME:$CONTAINER_DIR"
}

exec_in_container() {
  docker exec -e PYTEST_ADDOPTS="-p no:cacheprovider" "$CONTAINER_NAME" "$@"
}

tier_lint() {
  echo "==> [lint] ruff check"
  exec_in_container ruff check --no-cache .
}

tier_test() {
  echo "==> [test] pytest NIKIUID/tests"
  exec_in_container python -m pytest NIKIUID/tests -q
}

tier_smoke() {
  echo "==> [smoke] 全模块导入检查(路由/SV 注册副作用)"
  # 不用 stdin heredoc:docker exec 不带 -i 时 stdin 不会进容器,
  # python 会静默空跑造成假阳性,检查逻辑放仓库内脚本里
  exec_in_container python ci/smoke_imports.py
}

case "${1:-}" in
--build)
  build_image
  ;;
--lint | --test | --smoke)
  start_container
  "tier_${1#--}"
  ;;
"" | --all)
  build_image
  start_container
  tier_lint
  tier_test
  tier_smoke
  echo "==> 全部通过"
  ;;
*)
  echo "未知参数: $1(见文件头部用法)" >&2
  exit 2
  ;;
esac
