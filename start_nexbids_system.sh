#!/bin/bash
# NexBids数据监控系统启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "   NexBids数据监控系统启动脚本"
echo "========================================="
echo ""

# 检查Python环境
echo "[1/4] 检查Python环境..."
python3 --version || { echo "错误: 未找到 python3"; exit 1; }
pip --version || { echo "错误: 未找到 pip"; exit 1; }

# 检查依赖
echo "[2/4] 检查依赖..."
if ! python3 -c "import schedule" 2>/dev/null; then
    echo "安装 schedule 模块..."
    pip install schedule
fi

if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "安装 fastapi 和 uvicorn..."
    pip install fastapi uvicorn
fi

if ! python3 -c "import pandas" 2>/dev/null; then
    echo "安装 pandas..."
    pip install pandas
fi

# 创建必要目录
mkdir -p "$SCRIPT_DIR/data"
mkdir -p "$SCRIPT_DIR/logs"

# 启动API服务
echo "[3/4] 启动API服务..."

# 检查是否已有API服务在运行
if pgrep -f "ps_data_api.py" > /dev/null; then
    echo "API服务已在运行，停止现有服务..."
    pkill -f "ps_data_api.py" || true
    sleep 2
fi

echo "启动新的API服务..."
nohup python3 "$SCRIPT_DIR/ps_data_api.py" > "$SCRIPT_DIR/logs/api_service.log" 2>&1 &
API_PID=$!
echo "API服务已启动 (PID: $API_PID)"

# 等待API服务启动
echo "等待API服务启动..."
sleep 5

# 检查API服务状态
API_PORT=${NEXBIDS_API_PORT:-8090}
if curl -s "http://localhost:${API_PORT}/api/health" > /dev/null 2>&1; then
    echo "✓ API服务启动成功 (端口: ${API_PORT})"
else
    echo "✗ API服务启动失败，请检查日志"
    tail -20 "$SCRIPT_DIR/logs/api_service.log"
    exit 1
fi

# 启动Web服务器
echo "[4/4] 启动Web服务器..."

# 检查是否已有Web服务在运行
if pgrep -f "nexbids_web/server.py" > /dev/null; then
    echo "Web服务已在运行，停止现有服务..."
    pkill -f "nexbids_web/server.py" || true
    sleep 2
fi

echo "启动Web服务器..."
nohup python3 "$SCRIPT_DIR/nexbids_web/server.py" --port 8081 > "$SCRIPT_DIR/logs/web_service.log" 2>&1 &
WEB_PID=$!
echo "Web服务器已启动 (PID: $WEB_PID)"

# 等待Web服务器启动
echo "等待Web服务器启动..."
sleep 3

# 检查Web服务器状态
if curl -s "http://localhost:8081" > /dev/null 2>&1; then
    echo "✓ Web服务器启动成功 (端口: 8081)"
else
    echo "✗ Web服务器启动失败，请检查日志"
    tail -20 "$SCRIPT_DIR/logs/web_service.log"
    exit 1
fi

echo ""
echo "========================================="
echo "       系统启动完成！"
echo "========================================="
echo ""
echo "访问地址:"
echo "  1. Web界面: http://localhost:8081"
echo "  2. API服务: http://localhost:${API_PORT}"
echo "  3. API健康检查: http://localhost:${API_PORT}/api/health"
echo ""
echo "日志文件:"
echo "  1. API服务日志: $SCRIPT_DIR/logs/api_service.log"
echo "  2. Web服务日志: $SCRIPT_DIR/logs/web_service.log"
echo "  3. 采集日志:     $SCRIPT_DIR/logs/ps_system_log.log"
echo ""
echo "停止服务:"
echo "  ./stop_nexbids_system.sh"
echo ""
echo "========================================="
