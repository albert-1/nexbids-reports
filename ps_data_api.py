#!/usr/bin/env python3
"""
PS系统数据API服务
为网页前端提供数据接口
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import uvicorn
from pydantic import BaseModel
import pandas as pd
import schedule
import threading
import time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 数据模型
class TimeRange(BaseModel):
    """时间范围"""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

class FilterParams(BaseModel):
    """过滤参数"""
    advertiser_ids: Optional[List[str]] = None
    campaign_ids: Optional[List[str]] = None
    adgroup_ids: Optional[List[str]] = None
    creative_ids: Optional[List[str]] = None
    time_range: Optional[TimeRange] = None

# 创建FastAPI应用
app = FastAPI(title="PS系统数据API", description="为网页前端提供数据接口", version="1.0.0")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境中应该限制为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DataManager:
    """数据管理器"""
    
    def __init__(self, db_path: str = "/home/workspace/ps_system_data/ps_data.db"):
        self.db_path = Path(db_path)
        self.config_path = Path("/home/workspace/ps_system_config.json")
        self.config = self.load_config()
        
        # 确保数据库存在
        if not self.db_path.exists():
            self.init_database()
        
        logger.info("数据管理器初始化完成")
    
    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error("配置文件不存在")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"配置文件JSON解析错误: {e}")
            return {}
    
    def init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建小时级数据表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS hourly_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                advertiser_id TEXT NOT NULL,
                advertiser_name TEXT NOT NULL,
                campaign_id TEXT,
                campaign_name TEXT,
                adgroup_id TEXT,
                adgroup_name TEXT,
                creative_id TEXT,
                creative_name TEXT,
                spend REAL DEFAULT 0.0,
                impressions INTEGER DEFAULT 0,
                clicks INTEGER DEFAULT 0,
                ctr REAL DEFAULT 0.0,
                registers INTEGER DEFAULT 0,
                register_cpa REAL DEFAULT 0.0,
                amount REAL DEFAULT 0.0,
                roi REAL DEFAULT 0.0,
                hour_start TIMESTAMP NOT NULL,
                hour_end TIMESTAMP NOT NULL,
                collection_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                data_source TEXT DEFAULT 'web',
                UNIQUE(advertiser_id, campaign_id, adgroup_id, creative_id, hour_start)
            )
        ''')
        
        # 创建广告主信息表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS advertisers (
                advertiser_id TEXT PRIMARY KEY,
                advertiser_name TEXT NOT NULL,
                last_collected TIMESTAMP,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建周报索引表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weekly_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TIMESTAMP NOT NULL,
                week_end TIMESTAMP NOT NULL,
                report_path TEXT NOT NULL,
                simplified_path TEXT NOT NULL,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(week_start, week_end)
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("数据库初始化完成")

# 全局数据管理器实例
data_manager = DataManager()

@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "PS系统数据API",
        "version": "1.0.0",
        "endpoints": [
            "/api/health",
            "/api/advertisers",
            "/api/hourly-data",
            "/api/daily-summary",
            "/api/weekly-reports",
            "/api/historical-data"
        ]
    }

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/api/advertisers")
async def get_advertisers():
    """获取广告主列表"""
    try:
        conn = sqlite3.connect(data_manager.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT advertiser_id, advertiser_name, status, last_collected
            FROM advertisers
            ORDER BY advertiser_name
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        advertisers = []
        for row in rows:
            advertisers.append({
                "id": row[0],
                "name": row[1],
                "status": row[2],
                "last_collected": row[3]
            })
        
        return {
            "count": len(advertisers),
            "advertisers": advertisers
        }
        
    except Exception as e:
        logger.error(f"获取广告主列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")

@app.get("/api/hourly-data")
async def get_hourly_data(
    start_time: Optional[str] = Query(None, description="开始时间 (YYYY-MM-DD HH:MM:SS)"),
    end_time: Optional[str] = Query(None, description="结束时间 (YYYY-MM-DD HH:MM:SS)"),
    advertiser_id: Optional[str] = Query(None, description="广告主ID"),
    campaign_id: Optional[str] = Query(None, description="活动ID"),
    limit: int = Query(100, description="返回记录数", ge=1, le=1000)
):
    """获取小时级数据"""
    try:
        conn = sqlite3.connect(data_manager.db_path)
        
        # 构建查询条件
        conditions = []
        params = []
        
        if start_time:
            conditions.append("hour_start >= ?")
            params.append(start_time)
        
        if end_time:
            conditions.append("hour_end <= ?")
            params.append(end_time)
        
        if advertiser_id:
            conditions.append("advertiser_id = ?")
            params.append(advertiser_id)
        
        if campaign_id:
            conditions.append("campaign_id = ?")
            params.append(campaign_id)
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = f'''
            SELECT 
                advertiser_name,
                campaign_name,
                adgroup_name,
                creative_name,
                spend,
                impressions,
                clicks,
                ctr,
                registers,
                register_cpa,
                amount,
                roi,
                hour_start,
                hour_end
            FROM hourly_data
            {where_clause}
            ORDER BY hour_start DESC, advertiser_name
            LIMIT ?
        '''
        
        params.append(limit)
        
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        # 转换数据类型
        records = []
        for _, row in df.iterrows():
            records.append({
                "advertiser_name": row["advertiser_name"],
                "campaign_name": row["campaign_name"],
                "adgroup_name": row["adgroup_name"],
                "creative_name": row["creative_name"],
                "spend": float(row["spend"]),
                "impressions": int(row["impressions"]),
                "clicks": int(row["clicks"]),
                "ctr": float(row["ctr"]),
                "registers": int(row["registers"]),
                "register_cpa": float(row["register_cpa"]),
                "amount": float(row["amount"]),
                "roi": float(row["roi"]),
                "hour_start": row["hour_start"],
                "hour_end": row["hour_end"]
            })
        
        return {
            "count": len(records),
            "data": records,
            "query_params": {
                "start_time": start_time,
                "end_time": end_time,
                "advertiser_id": advertiser_id,
                "campaign_id": campaign_id
            }
        }
        
    except Exception as e:
        logger.error(f"获取小时级数据失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")

@app.get("/api/daily-summary")
async def get_daily_summary(
    days: int = Query(7, description="天数", ge=1, le=30),
    advertiser_id: Optional[str] = Query(None, description="广告主ID")
):
    """获取每日汇总数据"""
    try:
        conn = sqlite3.connect(data_manager.db_path)
        
        # 计算开始时间
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # 构建查询条件
        conditions = ["hour_start >= ?", "hour_start <= ?"]
        params = [start_date, end_date]
        
        if advertiser_id:
            conditions.append("advertiser_id = ?")
            params.append(advertiser_id)
        
        where_clause = "WHERE " + " AND ".join(conditions)
        
        query = f'''
            SELECT 
                DATE(hour_start) as date,
                advertiser_name,
                SUM(spend) as daily_spend,
                SUM(impressions) as daily_impressions,
                SUM(clicks) as daily_clicks,
                SUM(registers) as daily_registers,
                CASE 
                    WHEN SUM(impressions) > 0 THEN ROUND(SUM(clicks) * 100.0 / SUM(impressions), 2)
                    ELSE 0
                END as daily_ctr,
                CASE 
                    WHEN SUM(registers) > 0 THEN ROUND(SUM(spend) / SUM(registers), 4)
                    ELSE 0
                END as daily_cpa,
                SUM(amount) as daily_amount,
                CASE 
                    WHEN SUM(spend) > 0 THEN ROUND((SUM(amount) - SUM(spend)) * 100.0 / SUM(spend), 2)
                    ELSE 0
                END as daily_roi
            FROM hourly_data
            {where_clause}
            GROUP BY DATE(hour_start), advertiser_id
            ORDER BY date DESC, advertiser_name
        '''
        
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        # 按日期分组
        daily_data = {}
        for _, row in df.iterrows():
            date_str = row["date"]
            if date_str not in daily_data:
                daily_data[date_str] = {
                    "date": date_str,
                    "advertisers": [],
                    "total_spend": 0,
                    "total_registers": 0,
                    "total_impressions": 0,
                    "total_clicks": 0
                }
            
            advertiser_data = {
                "name": row["advertiser_name"],
                "spend": float(row["daily_spend"]),
                "impressions": int(row["daily_impressions"]),
                "clicks": int(row["daily_clicks"]),
                "registers": int(row["daily_registers"]),
                "ctr": float(row["daily_ctr"]),
                "cpa": float(row["daily_cpa"]),
                "amount": float(row["daily_amount"]),
                "roi": float(row["daily_roi"])
            }
            
            daily_data[date_str]["advertisers"].append(advertiser_data)
            daily_data[date_str]["total_spend"] += advertiser_data["spend"]
            daily_data[date_str]["total_registers"] += advertiser_data["registers"]
            daily_data[date_str]["total_impressions"] += advertiser_data["impressions"]
            daily_data[date_str]["total_clicks"] += advertiser_data["clicks"]
        
        # 转换为列表并按日期排序
        result = sorted(daily_data.values(), key=lambda x: x["date"], reverse=True)
        
        return {
            "days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "count": len(result),
            "data": result
        }
        
    except Exception as e:
        logger.error(f"获取每日汇总数据失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")

@app.get("/api/weekly-reports")
async def get_weekly_reports(
    weeks_back: int = Query(4, description="周数", ge=1, le=12)
):
    """获取周报列表"""
    try:
        conn = sqlite3.connect(data_manager.db_path)
        
        # 查询周报索引
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, week_start, week_end, report_path, simplified_path, generated_at
            FROM weekly_reports
            ORDER BY week_start DESC
            LIMIT ?
        ''', (weeks_back,))
        
        rows = cursor.fetchall()
        conn.close()
        
        reports = []
        for row in rows:
            reports.append({
                "id": row[0],
                "week_start": row[1],
                "week_end": row[2],
                "report_path": row[3],
                "simplified_path": row[4],
                "generated_at": row[5]
            })
        
        return {
            "count": len(reports),
            "weeks_back": weeks_back,
            "reports": reports
        }
        
    except Exception as e:
        logger.error(f"获取周报列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")

@app.get("/api/weekly-reports/{week_start}")
async def get_weekly_report_detail(week_start: str):
    """获取指定周报详情"""
    try:
        # 查找周报文件
        reports_dir = Path("/home/workspace/ps_system_data/weekly_reports")
        report_files = list(reports_dir.glob(f"weekly_report_{week_start}_*.json"))
        
        if not report_files:
            raise HTTPException(status_code=404, detail="周报不存在")
        
        # 读取简化版报告
        simplified_files = list(reports_dir.glob(f"simplified_weekly_report_{week_start}_*.json"))
        if simplified_files:
            with open(simplified_files[0], 'r', encoding='utf-8') as f:
                report_data = json.load(f)
        else:
            with open(report_files[0], 'r', encoding='utf-8') as f:
                report_data = json.load(f)
        
        return report_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取周报详情失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")

@app.get("/api/historical-data")
async def get_historical_data(
    metric: str = Query("spend", description="指标名称", 
                       enum=["spend", "impressions", "clicks", "registers", "amount", "roi"]),
    group_by: str = Query("day", description="分组方式", 
                         enum=["hour", "day", "week"]),
    days: int = Query(30, description="天数", ge=1, le=90)
):
    """获取历史数据趋势"""
    try:
        conn = sqlite3.connect(data_manager.db_path)
        
        # 计算开始时间
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # 根据分组方式构建查询
        if group_by == "hour":
            group_expr = "DATE(hour_start) || ' ' || HOUR(hour_start) || ':00'"
            order_expr = "hour_start"
        elif group_by == "day":
            group_expr = "DATE(hour_start)"
            order_expr = "date"
        elif group_by == "week":
            group_expr = "STRFTIME('%Y-W%W', hour_start)"
            order_expr = "week"
        
        query = f'''
            SELECT 
                {group_expr} as time_group,
                SUM({metric}) as total_value
            FROM hourly_data
            WHERE hour_start >= ? AND hour_start <= ?
            GROUP BY {group_expr}
            ORDER BY {order_expr}
        '''
        
        df = pd.read_sql_query(query, conn, params=(start_date, end_date))
        conn.close()
        
        # 转换为前端需要的格式
        labels = df["time_group"].tolist()
        data = df["total_value"].tolist()
        
        return {
            "metric": metric,
            "group_by": group_by,
            "days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "labels": labels,
            "data": data
        }
        
    except Exception as e:
        logger.error(f"获取历史数据趋势失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")

@app.get("/api/real-time-metrics")
async def get_real_time_metrics():
    """获取实时指标"""
    try:
        conn = sqlite3.connect(data_manager.db_path)
        
        # 获取当前小时的数据
        current_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        next_hour = current_hour + timedelta(hours=1)
        
        query = '''
            SELECT 
                COUNT(DISTINCT advertiser_id) as active_advertisers,
                COUNT(DISTINCT campaign_id) as active_campaigns,
                SUM(spend) as current_hour_spend,
                SUM(registers) as current_hour_registers,
                SUM(impressions) as current_hour_impressions,
                SUM(clicks) as current_hour_clicks
            FROM hourly_data
            WHERE hour_start >= ? AND hour_start < ?
        '''
        
        cursor = conn.cursor()
        cursor.execute(query, (current_hour, next_hour))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "current_hour": current_hour.isoformat(),
                "metrics": {
                    "active_advertisers": row[0],
                    "active_campaigns": row[1],
                    "spend": float(row[2]),
                    "registers": int(row[3]),
                    "impressions": int(row[4]),
                    "clicks": int(row[5])
                }
            }
        else:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "current_hour": current_hour.isoformat(),
                "metrics": {
                    "active_advertisers": 0,
                    "active_campaigns": 0,
                    "spend": 0.0,
                    "registers": 0,
                    "impressions": 0,
                    "clicks": 0
                },
                "note": "当前小时暂无数据"
            }
        
    except Exception as e:
        logger.error(f"获取实时指标失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")

@app.post("/api/collect-now")
async def collect_now(background_tasks: BackgroundTasks):
    """立即触发数据采集"""
    try:
        from ps_data_collector import PSDataCollector
        
        collector = PSDataCollector()
        
        # 在后台执行采集任务
        background_tasks.add_task(collector.collect_all_advertisers)
        
        return {
            "status": "started",
            "message": "数据采集任务已启动",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"触发数据采集失败: {e}")
        raise HTTPException(status_code=500, detail="启动采集任务失败")

@app.get("/api/download-report")
async def download_report(
    report_type: str = Query("hourly", description="报告类型", 
                           enum=["hourly", "daily", "weekly"]),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期")
):
    """下载报告"""
    try:
        # 根据报告类型生成文件
        output_dir = Path("/home/workspace/ps_system_data/temp")
        output_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{report_type}_report_{timestamp}.csv"
        filepath = output_dir / filename
        
        # 生成报告数据
        import csv
        conn = sqlite3.connect(data_manager.db_path)
        
        if report_type == "hourly":
            query = '''
                SELECT 
                    advertiser_name,
                    campaign_name,
                    adgroup_name,
                    creative_name,
                    spend,
                    impressions,
                    clicks,
                    ctr,
                    registers,
                    register_cpa,
                    amount,
                    roi,
                    hour_start,
                    hour_end
                FROM hourly_data
                ORDER BY hour_start DESC
            '''
        elif report_type == "daily":
            query = '''
                SELECT 
                    DATE(hour_start) as date,
                    advertiser_name,
                    SUM(spend) as total_spend,
                    SUM(impressions) as total_impressions,
                    SUM(clicks) as total_clicks,
                    SUM(registers) as total_registers,
                    SUM(amount) as total_amount
                FROM hourly_data
                GROUP BY DATE(hour_start), advertiser_id
                ORDER BY date DESC, advertiser_name
            '''
        else:  # weekly
            query = '''
                SELECT 
                    STRFTIME('%Y-W%W', hour_start) as week,
                    advertiser_name,
                    SUM(spend) as total_spend,
                    SUM(registers) as total_registers,
                    SUM(amount) as total_amount,
                    AVG(roi) as avg_roi
                FROM hourly_data
                GROUP BY STRFTIME('%Y-W%W', hour_start), advertiser_id
                ORDER BY week DESC, advertiser_name
            '''
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # 保存为CSV
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        return FileResponse(
            path=filepath,
            filename=filename,
            media_type='text/csv'
        )
        
    except Exception as e:
        logger.error(f"生成下载报告失败: {e}")
        raise HTTPException(status_code=500, detail="生成报告失败")

def schedule_weekly_report():
    """调度周报生成任务"""
    def generate_report():
        from weekly_report_generator import WeeklyReportGenerator
        generator = WeeklyReportGenerator()
        report = generator.generate_weekly_report()
        if report:
            logger.info(f"定时周报生成成功: {report.get('report_path', '')}")
    
    # 每周五23:45生成周报
    schedule.every().friday.at("23:45").do(generate_report)
    
    # 立即运行一次（如果当前时间是周五23:45之后）
    now = datetime.utcnow()
    if now.weekday() == 4 and now.hour >= 23 and now.minute >= 45:
        generate_report()
    
    # 运行调度器
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    # 启动定时任务调度器（在后台线程中）
    scheduler_thread = threading.Thread(target=schedule_weekly_report, daemon=True)
    scheduler_thread.start()
    
    # 启动API服务
    config = data_manager.config
    port = config.get("web_port", 8080)
    
    logger.info(f"启动PS系统数据API服务，端口: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)