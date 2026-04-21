# NexBids数据监控系统

专业的广告投放数据监控和分析系统，支持实时数据采集、可视化分析和自动化报告生成。

## 系统概览

NexBids数据监控系统是一个完整的投放数据监控解决方案，具备以下特点：

- **实时监控**: 每小时自动采集投放数据
- **多维度分析**: 广告主、活动、广告组、创意等多维度分析
- **可视化报表**: 丰富的图表展示和数据趋势分析
- **自动化报告**: 每日、每周自动化报告生成

## 快速开始

### 系统要求
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
   编辑 `ps_system_config.json` 文件，填入你的账号信息：
   ```json
   {
     "ps_system_url": "https://dsp.nexbids.com",
     "username": "你的账号",
     "password": "你的密码"
   }
   ```

   **安全提示**: 你也可以通过环境变量设置敏感信息，避免将密码写入文件：
   ```bash
   export NEXBIDS_USERNAME="your_username"
   export NEXBIDS_PASSWORD="your_password"
   ```

4. **启动系统**
   ```bash
   # 一键启动
   ./start_nexbids_system.sh
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

## 项目结构

```
nexbids_repo/
├── config.py                    # 统一配置管理模块
├── ps_data_api.py              # API服务主程序 (端口: 8090)
├── ps_data_collector.py        # 数据采集器
├── weekly_report_generator.py  # 周报生成器
├── ps_system_config.json       # 配置文件（示例，可用环境变量覆盖）
├── requirements.txt            # Python依赖
├── start_nexbids_system.sh     # 启动脚本
├── stop_nexbids_system.sh      # 停止脚本
├── validate_system.py          # 系统验证脚本
├── README.md                   # 本文档
├── DEPLOYMENT_GUIDE.md         # 部署指南
├── data/                       # 数据目录（自动创建）
│   └── ps_data.db             # SQLite数据库
├── logs/                       # 日志目录（自动创建）
│   ├── api_service.log
│   ├── web_service.log
│   └── ps_system_log.log
└── nexbids_web/               # Web界面 (端口: 8081)
    ├── index.html             # 主页面
    ├── server.py              # Web服务器
    └── README.md              # Web界面文档
```

## 核心功能

### 数据采集
- **频率**: 每小时自动采集（UTC整点）
- **范围**: 支持多广告主轮流采集（从配置读取）
- **指标**: 花费、展示、点击、转化、ROI等10+指标
- **存储**: SQLite数据库，默认30天数据保留
- **模式**: 支持 `mock`（模拟数据）和 `web_scraping`（真实采集）两种模式

### Web界面
- **响应式**: 支持PC和移动设备
- **实时**: 支持自动刷新和手动刷新
- **筛选**: 时间范围、广告主等多维度筛选
- **导出**: 支持CSV格式导出

### API接口
```
GET    /api/health              # 健康检查
GET    /api/advertisers         # 广告主列表
GET    /api/hourly-data         # 小时级数据
GET    /api/hourly/today        # 今日小时数据（前端专用）
GET    /api/daily-summary       # 每日汇总
GET    /api/summary/today       # 今日汇总（前端专用）
GET    /api/weekly-reports      # 周报列表
GET    /api/weekly/current      # 本周数据（前端专用）
GET    /api/weekly-reports/{id} # 指定周报详情
GET    /api/historical-data     # 历史数据趋势
GET    /api/real-time-metrics   # 实时指标
GET    /api/download-report     # 下载报告
POST   /api/collect-now         # 立即采集
```

## 系统架构

```
┌─────────────────────────────────────────┐
│            Web界面 (8081端口)           │
│        http://localhost:8081            │
└───────────────────┬─────────────────────┘
                    │ API代理
                    ▼
┌─────────────────────────────────────────┐
│        数据API服务 (8090端口)           │
│        http://localhost:8090/api        │
└───────────────────┬─────────────────────┘
                    │ 数据访问
                    ▼
┌─────────────────────────────────────────┐
│            SQLite数据库                 │
│          ./data/ps_data.db              │
└───────────────────┬─────────────────────┘
                    │ 定时采集
                    ▼
┌─────────────────────────────────────────┐
│          PS系统数据采集器               │
│      定时采集投放平台数据               │
└─────────────────────────────────────────┘
```

## 环境变量配置

以下环境变量可覆盖配置文件中的对应项：

| 环境变量 | 说明 |
|---------|------|
| `NEXBIDS_PS_URL` | 投放平台URL |
| `NEXBIDS_USERNAME` | 登录账号 |
| `NEXBIDS_PASSWORD` | 登录密码 |
| `NEXBIDS_WEB_PORT` | Web服务端口（默认8081） |
| `NEXBIDS_API_PORT` | API服务端口（默认8090） |
| `NEXBIDS_DATA_DIR` | 数据目录路径 |
| `NEXBIDS_LOG_DIR` | 日志目录路径 |

## 生产环境建议

1. **使用虚拟环境**: 隔离Python依赖
2. **配置防火墙**: 限制访问端口
3. **设置反向代理**: 使用Nginx或Apache
4. **配置SSL证书**: 启用HTTPS加密
5. **设置监控告警**: 监控系统健康状态
6. **环境变量管理密码**: 切勿将真实密码提交到版本控制

## 系统验证

运行验证脚本确保系统正常运行：
```bash
python validate_system.py
```

预期输出：
```
🎉 所有测试通过！系统功能完整。
```

## 安全提示

1. **保护配置文件**: 不要提交包含敏感信息的配置文件
2. **使用环境变量**: 将密码等敏感信息存储在环境变量中
3. **限制访问权限**: 只开放必要的端口
4. **定期更新**: 及时更新系统和依赖包

## 支持与贡献

### 问题报告
如遇问题，请通过以下方式报告：
1. 在GitHub仓库创建Issue
2. 提供详细的错误信息和复现步骤
3. 附上相关日志文件

### 功能建议
欢迎提出功能建议和优化方案。

## 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 更新日志

### v1.1 (2026-04-21)
- 修复硬编码路径问题，支持任意目录部署
- 添加统一配置管理模块（config.py）
- 修复前端API调用不匹配问题
- 统一端口配置（Web: 8081, API: 8090）
- 修复SQL注入隐患
- 添加环境变量覆盖敏感配置支持
- 完善前端各页面内容
- 添加周报生成器模块
- 优化启动/停止脚本

### v1.0 (2026-04-21)
- API服务完整实现
- Web界面响应式设计
- 数据采集自动化
- 系统验证脚本
- 完整文档

---

**系统状态**: 已验证，功能完整
**最后验证**: 2026-04-21
**版本**: v1.1
