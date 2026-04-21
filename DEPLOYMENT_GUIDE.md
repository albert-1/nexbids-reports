# NexBids数据监控系统 - 部署指南

本文档提供将NexBids数据监控系统部署到生产环境的详细步骤。

## 系统架构

已完成的系统包含以下核心组件：

### 1. API服务 (`ps_data_api.py`)
- **端口**: 8090
- **功能**: 提供数据查询接口
- **端点**:
  - `/api/health` - 健康检查
  - `/api/advertisers` - 广告主列表
  - `/api/hourly-data` - 小时级数据
  - `/api/daily-summary` - 每日汇总
  - `/api/weekly-reports` - 周报数据

### 2. Web界面 (`nexbids_web/`)
- **端口**: 8081
- **功能**: 可视化数据监控界面
- **技术栈**: HTML5, CSS3, JavaScript, Chart.js, Bootstrap

### 3. 数据采集器 (`ps_data_collector.py`)
- **功能**: 每小时自动采集投放数据
- **配置**: 支持多广告主轮流采集（从配置文件读取）

### 4. 周报生成器 (`weekly_report_generator.py`)
- **功能**: 根据数据库生成周报JSON文件

### 5. 配置管理 (`config.py`)
- **功能**: 统一加载配置，支持环境变量覆盖敏感信息

## 文件结构

```
nexbids_repo/
├── config.py                    # 统一配置管理
├── ps_data_api.py              # API服务主程序
├── ps_data_collector.py        # 数据采集器
├── weekly_report_generator.py  # 周报生成器
├── ps_system_config.json       # 配置文件
├── requirements.txt            # Python依赖
├── start_nexbids_system.sh     # 启动脚本
├── stop_nexbids_system.sh      # 停止脚本
├── validate_system.py          # 系统验证脚本
├── README.md                   # 系统文档
├── DEPLOYMENT_GUIDE.md         # 本文档
├── data/                       # 数据目录（运行时创建）
├── logs/                       # 日志目录（运行时创建）
└── nexbids_web/               # Web界面
    ├── index.html             # 主页面
    ├── server.py              # Web服务器
    └── README.md              # Web界面文档
```

## 已验证的功能

- **API服务**: 正常运行，所有端点可访问
- **Web界面**: 可访问，界面美观响应式
- **数据采集**: 配置正确，支持多广告主
- **数据质量**: 字段完整，格式正确
- **系统集成**: API与Web界面无缝集成

## 部署步骤

### 1. 环境准备

```bash
# 安装系统依赖（以Ubuntu/Debian为例）
sudo apt update
sudo apt install python3-pip git nginx

# 创建系统用户
sudo useradd -m -s /bin/bash nexbids
sudo su - nexbids
```

### 2. 应用部署

```bash
# 克隆代码
git clone https://github.com/albert-1/nexbids-reports.git
cd nexbids-reports

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置系统

编辑 `ps_system_config.json`：

```json
{
  "ps_system_url": "https://dsp.nexbids.com",
  "username": "admin@qq.com",
  "password": "a123456",
  "data_collection_method": "web_scraping",
  "collection_interval_hours": 1,
  "web_port": 8081,
  "api_port": 8090
}
```

**推荐**: 使用环境变量管理密码（更安全）：

```bash
export NEXBIDS_USERNAME="admin@qq.com"
export NEXBIDS_PASSWORD="a123456"
export NEXBIDS_WEB_PORT=8081
export NEXBIDS_API_PORT=8090
```

### 4. 配置Nginx

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 5. 配置系统服务

创建systemd服务文件 `/etc/systemd/system/nexbids-api.service`：

```ini
[Unit]
Description=NexBids Data API Service
After=network.target

[Service]
User=nexbids
WorkingDirectory=/home/nexbids/nexbids-reports
Environment="PATH=/home/nexbids/nexbids-reports/venv/bin"
Environment="NEXBIDS_USERNAME=admin@qq.com"
Environment="NEXBIDS_PASSWORD=a123456"
ExecStart=/home/nexbids/nexbids-reports/venv/bin/python /home/nexbids/nexbids-reports/ps_data_api.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

创建systemd服务文件 `/etc/systemd/system/nexbids-web.service`：

```ini
[Unit]
Description=NexBids Web Server
After=network.target nexbids-api.service

[Service]
User=nexbids
WorkingDirectory=/home/nexbids/nexbids-reports
Environment="PATH=/home/nexbids/nexbids-reports/venv/bin"
ExecStart=/home/nexbids/nexbids-reports/venv/bin/python /home/nexbids/nexbids-reports/nexbids_web/server.py --port 8081
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable nexbids-api nexbids-web
sudo systemctl start nexbids-api nexbids-web
```

## 系统启动（开发环境）

### 快速启动

```bash
# 启动API服务
python ps_data_api.py &

# 启动Web界面
cd nexbids_web
python server.py --port 8081 &

# 访问系统
# Web界面: http://localhost:8081
# API服务: http://localhost:8090/api/health
```

### 使用启动脚本

```bash
# 一键启动
./start_nexbids_system.sh

# 一键停止
./stop_nexbids_system.sh
```

## 环境配置

### Python环境

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 配置文件

确保 `ps_system_config.json` 包含正确的配置：

```json
{
  "ps_system_url": "https://dsp.nexbids.com",
  "username": "admin@qq.com",
  "password": "a123456",
  "data_collection_method": "web_scraping",
  "collection_interval_hours": 1,
  "web_port": 8081,
  "api_port": 8090
}
```

## 验证系统

运行验证脚本确保所有功能正常：

```bash
python validate_system.py
```

预期输出：

```
🎉 所有测试通过！系统功能完整。
```

## 故障排除

### 常见问题

1. **端口冲突**
   ```
   错误: Address already in use
   ```
   **解决方案**: 修改配置文件或环境变量中的端口号

2. **依赖安装失败**
   ```
   错误: ModuleNotFoundError
   ```
   **解决方案**: 检查Python版本，使用虚拟环境

3. **API服务无法启动**
   ```
   错误: 404 Not Found
   ```
   **解决方案**: 检查API脚本是否正在运行

4. **路径错误**
   ```
   错误: FileNotFoundError: config.py
   ```
   **解决方案**: 确保从项目根目录运行脚本，不要移动单个文件

### 日志文件

- `logs/api_service.log` - API服务日志
- `logs/web_service.log` - Web服务日志
- `logs/ps_system_log.log` - 数据采集日志

## 后续步骤

1. **自动化部署**: 设置GitHub Actions自动部署
2. **监控告警**: 添加系统健康监控
3. **扩展功能**: 添加更多数据源和分析功能
4. **性能优化**: 优化数据查询和界面响应

## 联系方式

如需技术支持或功能扩展，请联系系统开发者。

---

**系统状态**: 已验证，功能完整
**部署状态**: 等待推送到GitHub
**最后验证**: 2026-04-21
