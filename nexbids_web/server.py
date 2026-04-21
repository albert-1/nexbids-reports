#!/usr/bin/env python3
"""
NexBids数据监控系统 - Web服务器
提供网页界面展示投放数据监控和报告
"""

import os
import json
import logging
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
import socket
import threading
import time
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "web_service.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class NexBidsRequestHandler(SimpleHTTPRequestHandler):
    """自定义请求处理器"""

    def __init__(self, *args, **kwargs):
        self.api_url = "http://localhost:8090"
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """处理GET请求"""
        try:
            # 处理API代理请求
            if self.path.startswith('/api/'):
                self.proxy_to_api()
                return

            # 处理静态文件
            return super().do_GET()

        except Exception as e:
            logger.error(f"处理请求 {self.path} 时出错: {e}")
            self.send_error(500, f"服务器内部错误: {str(e)}")

    def do_OPTIONS(self):
        """处理预检请求（CORS）"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def proxy_to_api(self):
        """代理请求到后端API"""
        try:
            import urllib.request
            import urllib.error

            # 构建API URL
            api_path = self.path
            api_url = f"{self.api_url}{api_path}"

            logger.info(f"代理请求到: {api_url}")

            # 添加查询参数
            if '?' in self.path:
                api_url = f"{self.api_url}{self.path}"

            # 发送请求到API
            req = urllib.request.Request(api_url)
            req.add_header('User-Agent', 'NexBids-Web-Server/1.0')

            # 添加请求头
            for header, value in self.headers.items():
                if header.lower() not in ['host', 'connection']:
                    req.add_header(header, value)

            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    # 读取响应
                    data = response.read()

                    # 设置响应头
                    self.send_response(response.status)

                    # 复制API响应头
                    for header, value in response.headers.items():
                        if header.lower() not in ['connection', 'transfer-encoding']:
                            self.send_header(header, value)

                    # 添加CORS头
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()

                    # 发送响应体
                    self.wfile.write(data)

            except urllib.error.HTTPError as e:
                # 传递API的错误响应
                self.send_response(e.code)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(e.read())

            except socket.timeout:
                self.send_error(504, "API请求超时")
            except urllib.error.URLError as e:
                self.send_error(502, f"无法连接到API: {e.reason}")

        except Exception as e:
            logger.error(f"代理请求失败: {e}")
            self.send_error(500, f"代理请求失败: {str(e)}")

    def log_message(self, format, *args):
        """自定义日志格式"""
        logger.info(f"{self.address_string()} - {format % args}")

    def send_error(self, code, message=None):
        """发送错误响应"""
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        error_response = {
            "error": True,
            "code": code,
            "message": message or self.responses[code][0],
            "timestamp": datetime.now().isoformat()
        }

        self.wfile.write(json.dumps(error_response, ensure_ascii=False).encode('utf-8'))


def check_api_health():
    """检查API服务健康状态"""
    try:
        import urllib.request
        import urllib.error

        api_url = "http://localhost:8090/api/health"
        req = urllib.request.Request(api_url)

        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                return data.get('status') == 'healthy'
        return False

    except Exception as e:
        logger.warning(f"API健康检查失败: {e}")
        return False


def start_web_server(port=8081, web_root=None):
    """启动Web服务器"""
    # 切换到网页目录
    if web_root is None:
        web_root = PROJECT_ROOT / "nexbids_web"
    os.chdir(web_root)

    # 检查API服务
    if not check_api_health():
        logger.warning("API服务不可用，网页可能无法获取实时数据")

    server_address = ('', port)
    httpd = HTTPServer(server_address, NexBidsRequestHandler)

    logger.info(f"=== NexBids数据监控系统 ===")
    logger.info(f"服务器启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"监听地址: http://localhost:{port}")
    logger.info(f"API服务地址: http://localhost:8090")
    logger.info(f"按 Ctrl+C 停止服务器")
    logger.info("=" * 40)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭服务器...")
    finally:
        httpd.server_close()
        logger.info("服务器已关闭")


class BackgroundMonitor(threading.Thread):
    """后台监控线程"""

    def __init__(self):
        super().__init__(daemon=True)
        self.running = True

    def run(self):
        """监控循环"""
        while self.running:
            try:
                # 每30秒检查一次API健康状态
                time.sleep(30)

                if check_api_health():
                    logger.debug("API服务状态正常")
                else:
                    logger.warning("API服务可能已断开")

            except Exception as e:
                logger.error(f"监控循环出错: {e}")

    def stop(self):
        """停止监控"""
        self.running = False


if __name__ == '__main__':
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='NexBids数据监控系统Web服务器')
    parser.add_argument('--port', type=int, default=8081, help='服务器端口 (默认: 8081)')
    parser.add_argument('--api-url', type=str, default='http://localhost:8090',
                       help='API服务地址 (默认: http://localhost:8090)')
    parser.add_argument('--web-root', type=str, default=None,
                       help='Web根目录 (默认: 本文件所在目录)')

    args = parser.parse_args()

    # 设置API URL
    NexBidsRequestHandler.api_url = args.api_url

    # 启动后台监控
    monitor = BackgroundMonitor()
    monitor.start()

    try:
        start_web_server(args.port, web_root=args.web_root)
    except Exception as e:
        logger.error(f"服务器启动失败: {e}")
        sys.exit(1)
    finally:
        monitor.stop()
