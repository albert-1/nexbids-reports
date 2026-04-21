#!/bin/bash
# NexBids数据监控系统停止脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================="
echo "   NexBids数据监控系统停止脚本"
echo "========================================="
echo ""

# 停止Web服务器
echo "[1/2] 停止Web服务器..."
if pgrep -f "nexbids_web/server.py" > /dev/null; then
    echo "找到Web服务器进程，正在停止..."
    pkill -f "nexbids_web/server.py"
    sleep 2

    if pgrep -f "nexbids_web/server.py" > /dev/null; then
        echo "强制停止Web服务器..."
        pkill -9 -f "nexbids_web/server.py"
    fi

    echo "✓ Web服务器已停止"
else
    echo "Web服务器未运行"
fi

# 停止API服务
echo "[2/2] 停止API服务..."
if pgrep -f "ps_data_api.py" > /dev/null; then
    echo "找到API服务进程，正在停止..."
    pkill -f "ps_data_api.py"
    sleep 2

    if pgrep -f "ps_data_api.py" > /dev/null; then
        echo "强制停止API服务..."
        pkill -9 -f "ps_data_api.py"
    fi

    echo "✓ API服务已停止"
else
    echo "API服务未运行"
fi

echo ""
echo "========================================="
echo "       系统已完全停止"
echo "========================================="
echo ""
echo "如果要重新启动系统，运行:"
echo "  ./start_nexbids_system.sh"
echo ""
echo "清理日志文件:"
echo "  rm -f $SCRIPT_DIR/logs/*.log"
echo ""
echo "========================================="
