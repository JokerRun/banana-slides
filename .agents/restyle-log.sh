#!/usr/bin/env bash
# 采集 banana-slides 后端关键日志：restyle/生成流程、prompt、项目操作、AI调用
#
# Usage:
#   ./restyle-log.sh          # 实时跟踪
#   ./restyle-log.sh -n 200   # 查看最近200行历史 + 跟踪
#   ./restyle-log.sh --no-prompt  # 隐藏长 prompt 内容

TAIL_LINES=""
SHOW_PROMPT=true

for arg in "$@"; do
  case "$arg" in
    -n) shift; TAIL_LINES="--tail=$1"; shift ;;
    --no-prompt) SHOW_PROMPT=false; shift ;;
  esac
done

# 关键模块过滤（grep -E 正则）
MODULES=(
  "services\.task_manager"          # restyle/生成/编辑 任务全流程
  "services\.ai_service"            # AI 调用入口
  "services\.ai_providers\.image"   # GenAI/OpenAI provider：prompt、response、图片提取
  "controllers\.restyle_controller" # restyle 项目创建
  "controllers\.project_controller" # 项目/大纲/描述 生成
  "controllers\.settings_controller" # 设置变更
  "controllers\.export_controller"  # 导出任务
)

PATTERN=$(IFS='|'; echo "${MODULES[*]}")

if $SHOW_PROMPT; then
  docker compose logs -f --no-log-prefix $TAIL_LINES backend 2>&1 \
    | grep --line-buffered -E "$PATTERN"
else
  # 过滤掉 📝 Prompt 行（通常很长）
  docker compose logs -f --no-log-prefix $TAIL_LINES backend 2>&1 \
    | grep --line-buffered -E "$PATTERN" \
    | grep --line-buffered -v "📝 Prompt"
fi
