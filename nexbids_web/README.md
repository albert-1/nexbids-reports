# NexBids数据监控系统

专业的广告投放数据监控和分析系统，支持实时数据采集、可视化分析和自动化报告生成。

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    Web界面 (8081端口)                    │
│               http://localhost:8081                      │
└──────────────────────────┬──────────────────────────────┘
                           │ API代理
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  数据API服务 (8090端口)                  │
│              http://localhost:8090/api                   │
└──────────────────────────┬──────────────────────────────┘
                           │ 数据访问
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    SQLite数据库                          │
│              /home/workspace/ps_system_data              │
└──────────────────────────┬──────────────────────────────┘
                           │ 定时采集
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   PS系统数据采集器                       │
│               定时采集投放平台数据                       │
└─────────────────────────────────────────────────────────┘
```

## 功能特性

### 核心功能
- **实时数据监控**: 每小时自动采集投放数据
- **多维度分析**: 广告主、活动、广告组、创意等多维度分析
- **可视化报表**: 丰富的图表展示和数据趋势分析
- **自动化报告**: 每日、每周自动化报告生成

### 数据采集
- **采集频率**: 每小时自动采集（UTC整点）
- **数据范围**: 支持多广告主轮流采集
- **指标维度**: 花费、展示、点击、转化、ROI等10+指标
- **数据存储**: SQLite数据库，30天数据保留

### Web界面
- **响应式设计**: 支持PC和移动设备访问
- **实时刷新**: 支持自动刷新和手动刷新
- **数据筛选**: 支持时间范围、广告主等多维度筛选
- **数据导出**: 支持CSV、Excel格式导出

## 快速开始

### 环境要求
- Python 3.8+
- Git
- 网络连接（用于访问投放平台）

### 安装步骤

1. **克隆仓库**
   ```bash
   git clone https://github.com/albert-1/nexbids-reports.git
   cd nexbids-reports
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **配置系统**
   编辑 `ps_system_config.json` 文件：
   ```json
   {
     "ps_system_url": "https://dsp.nexbids.com",
     "username": "您的账号",
     "password": "您的密码",
     "data_collection_method": "web_scraping"
   }
   ```

4. **启动系统**
   ```bash
   # 启动API服务（后台运行）
   python ps_data_api.py &
   
   # 启动Web界面（后台运行）
   cd nexbids_web
   python server.py --port 8081 &
   ```

5. **访问系统**
   - Web界面: http://localhost:8081
   - API服务: http://localhost:8090/api/health

### 使用启动脚本
```bash
# 一键启动
./start_nexbids_system.sh

# 一键停止
./stop_nexbids_system.sh
```

## 系统配置

### 配置文件说明
`ps_system_config.json` 包含所有系统配置：

```json
{
  "ps_system_url": "投放平台URL",
  "username": "登录账号",
  "password": "登录密码",
  "data_retention_days": 30,
  "collection_interval_hours": 1,
  "advertiser_switch_delay": 2,
  "max_retries": 3,
  "timezone": "UTC",
  "web_port": 8090,
  "debug_mode": false,
  "advertisers": [
    {"id": "10001", "name": "广告主A", "active": true},
    {"id": "10002", "name": "广告主B", "active": true}
  ],
  "metrics": ["spend", "impressions", "clicks", "registers", "roi"],
  "report_config": {
    "hourly_metrics": ["spend", "impressions", "clicks", "registers"],
    "weekly_metrics": ["total_spend", "total_registers", "avg_register_cpa"]
  }
}
```

### 定时任务
系统内置以下定时任务：
- **每小时**: 数据自动采集（UTC整点）
- **每日**: 数据汇总和清理
- **每周**: 周报生成（上周六至本周五）

## API接口

### 健康检查
```
GET /api/health
```
返回系统健康状态。

### 广告主列表
```
GET /api/advertisers
```
返回所有配置的广告主信息。

### 小时级数据
```
GET /api/hourly-data
```
查询小时级投放数据。

### 每日汇总
```
GET /api/daily-summary
```
获取每日数据汇总。

### 周报数据
```
GET /api/weekly-reports
```
查询周报数据。

### 实时采集
```
POST /api/collect-now
```
立即触发数据采集。

## 数据模型

### 小时数据表 (hourly_data)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| advertiser_id | TEXT | 广告主ID |
| advertiser_name | TEXT | 广告主名称 |
| campaign_id | TEXT | 活动ID |
| campaign_name | TEXT | 活动名称 |
| adgroup_id | TEXT | 广告组ID |
| adgroup_name | TEXT | 广告组名称 |
| creative_id | TEXT | 创意ID |
| creative_name | TEXT | 创意名称 |
| spend | REAL | 花费（元） |
| impressions | INTEGER | 展示量 |
| clicks | INTEGER | 点击量 |
| ctr | REAL | 点击率（%） |
| registers | INTEGER | 转化数 |
| register_cpa | REAL | 转化成本（元） |
| amount | REAL | 收入金额（元） |
| roi | REAL | 投资回报率（%） |
| hour_start | TEXT | 小时开始时间 |
| hour_end | TEXT | 小时结束时间 |
| created_at | TEXT | 创建时间 |

## 部署指南

### 生产环境部署

1. **服务器配置**
   ```bash
   # 安装系统依赖
   sudo apt update
   sudo apt install python3-pip git nginx
   
   # 创建系统用户
   sudo useradd -m -s /bin/bash nexbids
   sudo su - nexbids
   ```

2. **应用部署**
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

3. **配置Nginx**
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

4. **配置系统服务**
   ```bash
   # 创建systemd服务
   sudo nano /etc/systemd/system/nexbids.service
   
   # 服务配置内容
   [Unit]
   Description=NexBids Data Monitoring System
   After=network.target
   
   [Service]
   User=nexbids
   WorkingDirectory=/home/nexbids/nexbids-reports
   Environment="PATH=/home/nexbids/nexbids-reports/venv/bin"
   ExecStart=/home/nexbids/nexbids-reports/venv/bin/python /home/nexbids/nexbids-reports/start_nexbids_system.sh
   Restart=always
   RestartSec=10
   
   [Install]
   WantedBy=multi-user.target
   ```

5. **启动服务**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable nexbids
   sudo systemctl start nexbids
   ```

## 故障排除

### 常见问题

1. **API服务无法启动**
   ```
   错误: ModuleNotFoundError: No module named 'schedule'
   ```
   **解决方案**: 运行 `pip install schedule fastapi uvicorn`

2. **网页无法访问**
   ```
   错误: 404 Not Found
   ```
   **解决方案**: 
   - 检查端口是否被占用
   - 检查防火墙设置
   - 确认服务已正确启动

3. **数据采集失败**
   ```
   错误: 登录失败或网络连接问题
   ```
   **解决方案**:
   - 检查账号密码是否正确
   - 检查网络连接
   - 查看采集日志

### 日志文件
- API服务日志: `api_service.log`
- Web服务日志: `web_service.log`
- 数据采集日志: `ps_system_log.log`

## 开发指南

### 项目结构
```
nexbids-reports/
├── ps_data_api.py          # API服务主程序
├── ps_data_collector.py    # 数据采集器
├── ps_system_config.json   # 配置文件
├── requirements.txt        # Python依赖
├── start_nexbids_system.sh # 启动脚本
├── stop_nexbids_system.sh  # 停止脚本
└── nexbids_web/           # Web界面
    ├── index.html         # 主页面
    ├── server.py          # Web服务器
    └── README.md          # 本文档
```

### 扩展开发

1. **添加新的数据指标**
   - 修改 `ps_data_collector.py` 中的采集逻辑
   - 更新数据库schema
   - 更新API接口返回数据

2. **添加新的图表类型**
   - 编辑 `nexbids_web/index.html` 中的JavaScript代码
   - 添加新的Chart.js配置

3. **集成其他数据源**
   - 创建新的数据采集模块
   - 更新数据整合逻辑

## 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 联系方式

如有问题或建议，请通过以下方式联系：
- 项目仓库: https://github.com/albert-1/nexbids-reports
- 报告问题: https://github.com/albert-1/nexbids-reports/issues

---

**重要提示**: 请妥善保管配置文件和登录凭证，不要将敏感信息提交到版本控制系统。