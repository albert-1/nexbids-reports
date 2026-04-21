#!/bin/bash
# NexBids数据监控系统启动脚本

set -e

echo "========================================="
echo "   NexBids数据监控系统启动脚本"
echo "========================================="
echo ""

# 检查Python环境
echo "[1/4] 检查Python环境..."
python3 --version
pip --version

# 检查依赖
echo "[2/4] 检查依赖..."
if ! python3 -c "import schedule" 2>/dev/null; then
    echo "安装schedule模块..."
    pip install schedule
fi

if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "安装fastapi模块..."
    pip install fastapi uvicorn
fi

# 启动API服务
echo "[3/4] 启动API服务..."
cd /home/workspace

# 检查是否已有API服务在运行
if ps aux | grep -v grep | grep -q "ps_data_api.py"; then
    echo "API服务已在运行，停止现有服务..."
    pkill -f "ps_data_api.py" || true
    sleep 2
fi

echo "启动新的API服务..."
nohup python3 ps_data_api.py > api_service.log 2>&1 &
API_PID=$!
echo "API服务已启动 (PID: $API_PID)"

# 等待API服务启动
echo "等待API服务启动..."
sleep 5

# 检查API服务状态
if curl -s http://localhost:8090/api/health > /dev/null 2>&1; then
    echo "✓ API服务启动成功"
else
    echo "✗ API服务启动失败，请检查日志"
    tail -20 api_service.log
    exit 1
fi

# 启动Web服务器
echo "[4/4] 启动Web服务器..."
cd /home/workspace/nexbids_web

# 检查是否已有Web服务在运行
if ps aux | grep -v grep | grep -q "server.py"; then
    echo "Web服务已在运行，停止现有服务..."
    pkill -f "server.py" || true
    sleep 2
fi

echo "启动Web服务器..."
nohup python3 server.py > web_service.log 2>&1 &
WEB_PID=$!
echo "Web服务器已启动 (PID: $WEB_PID)"

# 等待Web服务器启动
echo "等待Web服务器启动..."
sleep 3

# 检查Web服务器状态
if curl -s http://localhost:8080 > /dev/null 2>&1; then
    echo "✓ Web服务器启动成功"
else
    echo "✗ Web服务器启动失败，请检查日志"
    tail -20 web_service.log
    exit 1
fi

echo ""
echo "========================================="
echo "       系统启动完成！"
echo "========================================="
echo ""
echo "访问地址:"
echo "  1. Web界面: http://localhost:8080"
echo "  2. API服务: http://localhost:8090"
echo "  3. API健康检查: http://localhost:8090/api/health"
echo ""
echo "日志文件:"
echo "  1. API服务日志: /home/workspace/api_service.log"
echo "  2. Web服务日志: /home/workspace/nexbids_web/web_service.log"
echo ""
echo "停止服务:"
echo "  ./stop_nexbids_system.sh"
echo ""
echo "========================================="

# 显示实时日志（可选）
echo "显示最近日志（按Ctrl+C返回）..."
echo "-----------------------------------------"
tail -f /home/workspace/api_service.log /home/workspace/nexbids_web/web_service.log 2>/dev/null | head -50