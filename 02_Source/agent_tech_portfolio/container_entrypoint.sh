#!/bin/sh
set -eu

# 命名卷挂载后会遮住镜像中的示例数据，首次启动时补齐缺失文件。
if [ -d /app/default_data ] && [ -d /app/data ]; then
  for file in /app/default_data/*; do
    [ -f "$file" ] || continue
    target="/app/data/$(basename "$file")"
    [ -e "$target" ] || cp "$file" "$target"
  done
fi

exec "$@"
