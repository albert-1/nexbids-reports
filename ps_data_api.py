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
import sys

# 引入统一配置
from config import load_config, PROJECT_ROOT

# 配置日志
log_dir = PROJECT_ROOT / "logs"
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "api_service.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
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

# 配置CORS（生产环境应限制为具体域名）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:8081", "http://127.0.0.1:8080", "http://127.0.0.1:8081"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 合法的分组表达式和指标（防SQL注入）
VALID_METRICS = {
    "spend", "impressions", "clicks", "ctr", "ecpm", "cpc",
    "installs", "install_rate", "cpi", "activates", "activate_cvr", "activate_cpa",
    "registers", "register_cvr", "register_cpa", "amount", "roi"
}
VALID_GROUP_BY = {"hour", "day", "week"}


def _add_column_if_not_exists(cursor, table, column, col_type):
    try:
        cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise


def init_database(db_path: Path):
    """初始化数据库（统一入口）"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

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
            goal TEXT,
            spend REAL DEFAULT 0.0,
            impressions INTEGER DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0.0,
            ecpm REAL DEFAULT 0.0,
            installs INTEGER DEFAULT 0,
            install_rate REAL DEFAULT 0.0,
            cpi REAL DEFAULT 0.0,
            activates INTEGER DEFAULT 0,
            activate_cvr REAL DEFAULT 0.0,
            activate_cpa REAL DEFAULT 0.0,
            registers INTEGER DEFAULT 0,
            register_cvr REAL DEFAULT 0.0,
            register_cpa REAL DEFAULT 0.0,
            amount REAL DEFAULT 0.0,
            roi REAL DEFAULT 0.0,
            cpc REAL DEFAULT 0.0,
            hour_start TIMESTAMP NOT NULL,
            hour_end TIMESTAMP NOT NULL,
            collection_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            data_source TEXT DEFAULT 'web',
            UNIQUE(advertiser_id, campaign_id, adgroup_id, creative_id, hour_start)
        )
    ''')

    _add_column_if_not_exists(cursor, 'hourly_data', 'goal', 'TEXT')
    _add_column_if_not_exists(cursor, 'hourly_data', 'ecpm', 'REAL DEFAULT 0.0')
    _add_column_if_not_exists(cursor, 'hourly_data', 'installs', 'INTEGER DEFAULT 0')
    _add_column_if_not_exists(cursor, 'hourly_data', 'install_rate', 'REAL DEFAULT 0.0')
    _add_column_if_not_exists(cursor, 'hourly_data', 'cpi', 'REAL DEFAULT 0.0')
    _add_column_if_not_exists(cursor, 'hourly_data', 'activates', 'INTEGER DEFAULT 0')
    _add_column_if_not_exists(cursor, 'hourly_data', 'activate_cvr', 'REAL DEFAULT 0.0')
    _add_column_if_not_exists(cursor, 'hourly_data', 'activate_cpa', 'REAL DEFAULT 0.0')
    _add_column_if_not_exists(cursor, 'hourly_data', 'register_cvr', 'REAL DEFAULT 0.0')
    _add_column_if_not_exists(cursor, 'hourly_data', 'cpc', 'REAL DEFAULT 0.0')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS advertisers (
            advertiser_id TEXT PRIMARY KEY,
            advertiser_name TEXT NOT NULL,
            last_collected TIMESTAMP,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS collection_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            advertiser_id TEXT,
            status TEXT NOT NULL,
            data_count INTEGER DEFAULT 0,
            error_message TEXT,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP NOT NULL,
            duration_seconds REAL
        )
    ''')

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

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hourly_advertiser_hour ON hourly_data(advertiser_id, hour_start)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hourly_collection_time ON hourly_data(collection_time)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hourly_campaign ON hourly_data(campaign_id, hour_start)')

    conn.commit()
    conn.close()
    logger.info("数据库初始化完成")


class DataManager:
    """数据管理器"""

    def __init__(self, db_path: Path = None):
        self.config = load_config()
        self.db_path = db_path or self.config["_db_path"]

        if not self.db_path.exists():
            init_database(self.db_path)

        logger.info("数据管理器初始化完成")

    def get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)


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
            "/api/historical-data",
            "/api/real-time-metrics",
            "/api/summary/today",
            "/api/hourly/today",
            "/api/weekly/current",
            "/api/collect-now",
            "/api/download-report"
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
        conn = data_manager.get_connection()
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
    adgroup_id: Optional[str] = Query(None, description="广告组ID"),
    creative_id: Optional[str] = Query(None, description="创意ID"),
    limit: int = Query(100, description="返回记录数", ge=1, le=1000)
):
    """获取小时级数据，支持按各维度ID筛选"""
    try:
        conn = data_manager.get_connection()

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

        if adgroup_id:
            conditions.append("adgroup_id = ?")
            params.append(adgroup_id)

        if creative_id:
            conditions.append("creative_id = ?")
            params.append(creative_id)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f'''
            SELECT
                advertiser_id,
                advertiser_name,
                campaign_id,
                campaign_name,
                adgroup_id,
                adgroup_name,
                creative_id,
                creative_name,
                goal,
                spend,
                impressions,
                clicks,
                ctr,
                ecpm,
                installs,
                install_rate,
                cpi,
                activates,
                activate_cvr,
                activate_cpa,
                registers,
                register_cvr,
                register_cpa,
                amount,
                roi,
                cpc,
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

        records = []
        for _, row in df.iterrows():
            records.append({
                "advertiser_id": row["advertiser_id"],
                "advertiser_name": row["advertiser_name"],
                "campaign_id": row["campaign_id"],
                "campaign_name": row["campaign_name"],
                "adgroup_id": row["adgroup_id"],
                "adgroup_name": row["adgroup_name"],
                "creative_id": row["creative_id"],
                "creative_name": row["creative_name"],
                "goal": row["goal"],
                "spend": float(row["spend"]),
                "impressions": int(row["impressions"]),
                "clicks": int(row["clicks"]),
                "ctr": float(row["ctr"]),
                "ecpm": float(row["ecpm"]),
                "installs": int(row["installs"]),
                "install_rate": float(row["install_rate"]),
                "cpi": float(row["cpi"]),
                "activates": int(row["activates"]),
                "activate_cvr": float(row["activate_cvr"]),
                "activate_cpa": float(row["activate_cpa"]),
                "registers": int(row["registers"]),
                "register_cvr": float(row["register_cvr"]),
                "register_cpa": float(row["register_cpa"]),
                "amount": float(row["amount"]),
                "roi": float(row["roi"]),
                "cpc": float(row["cpc"]),
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
                "campaign_id": campaign_id,
                "adgroup_id": adgroup_id,
                "creative_id": creative_id
            }
        }

    except Exception as e:
        logger.error(f"获取小时级数据失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")


@app.get("/api/hourly/today")
async def get_hourly_today():
    """获取今日小时级数据（前端兼容接口）"""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    try:
        conn = data_manager.get_connection()
        query = '''
            SELECT
                strftime('%H', hour_start) as hour,
                advertiser_id,
                advertiser_name,
                campaign_id,
                campaign_name,
                adgroup_id,
                adgroup_name,
                creative_id,
                creative_name,
                SUM(spend) as spend,
                SUM(impressions) as impressions,
                SUM(clicks) as clicks,
                CASE WHEN SUM(impressions) > 0 THEN ROUND(SUM(clicks) * 1.0 / SUM(impressions), 4) ELSE 0 END as ctr,
                SUM(registers) as registers,
                SUM(activates) as activates,
                SUM(installs) as installs,
                SUM(amount) as amount,
                CASE WHEN SUM(registers) > 0 THEN ROUND(SUM(spend) / SUM(registers), 2) ELSE 0 END as register_cpa,
                CASE WHEN SUM(spend) > 0 THEN ROUND(SUM(amount) * 100.0 / SUM(spend), 2) ELSE 0 END as roi
            FROM hourly_data
            WHERE hour_start >= ? AND hour_start < ?
            GROUP BY strftime('%H', hour_start), advertiser_id, campaign_id, adgroup_id, creative_id
            ORDER BY hour, advertiser_name
        '''
        df = pd.read_sql_query(query, conn, params=(today_start, today_end))
        conn.close()

        records = []
        for _, row in df.iterrows():
            records.append({
                "hour": int(row["hour"]),
                "advertiser_id": row["advertiser_id"],
                "advertiser_name": row["advertiser_name"],
                "campaign_id": row["campaign_id"],
                "campaign_name": row["campaign_name"],
                "adgroup_id": row["adgroup_id"],
                "adgroup_name": row["adgroup_name"],
                "creative_id": row["creative_id"],
                "creative_name": row["creative_name"],
                "spend": float(row["spend"]),
                "impressions": int(row["impressions"]),
                "clicks": int(row["clicks"]),
                "ctr": float(row["ctr"]),
                "registers": int(row["registers"]),
                "activates": int(row["activates"]),
                "installs": int(row["installs"]),
                "amount": float(row["amount"]),
                "register_cpa": float(row["register_cpa"]),
                "roi": float(row["roi"])
            })

        return records

    except Exception as e:
        logger.error(f"获取今日小时数据失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")


@app.get("/api/summary/today")
async def get_summary_today():
    """获取今日汇总数据（前端兼容接口）
    由于数据是每小时快照（当日累计），取最新小时的快照作为今日汇总
    """
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    try:
        conn = data_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            WITH latest_hour AS (
                SELECT MAX(hour_start) as max_hour
                FROM hourly_data
                WHERE hour_start >= ? AND hour_start < ?
            )
            SELECT
                SUM(spend),
                SUM(registers),
                SUM(activates),
                SUM(installs),
                SUM(clicks),
                SUM(impressions),
                SUM(amount)
            FROM hourly_data
            WHERE hour_start = (SELECT max_hour FROM latest_hour)
        ''', (today_start, today_end))

        row = cursor.fetchone()
        conn.close()

        total_spend = float(row[0] or 0)
        total_registers = int(row[1] or 0)
        total_activates = int(row[2] or 0)
        total_installs = int(row[3] or 0)
        total_clicks = int(row[4] or 0)
        total_impressions = int(row[5] or 0)
        total_amount = float(row[6] or 0)

        avg_cpc = round(total_spend / total_clicks, 4) if total_clicks > 0 else 0
        avg_ctr = round(total_clicks / total_impressions, 4) if total_impressions > 0 else 0
        avg_roi = round(total_amount / total_spend, 2) if total_spend > 0 else 0

        return {
            "total_spend": total_spend,
            "total_registers": total_registers,
            "total_activates": total_activates,
            "total_installs": total_installs,
            "total_clicks": total_clicks,
            "total_impressions": total_impressions,
            "total_amount": total_amount,
            "avg_cpc": avg_cpc,
            "avg_ctr": avg_ctr,
            "avg_roi": avg_roi
        }

    except Exception as e:
        logger.error(f"获取今日汇总失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")


@app.get("/api/daily-summary")
async def get_daily_summary(
    days: int = Query(7, description="天数", ge=1, le=30),
    advertiser_id: Optional[str] = Query(None, description="广告主ID")
):
    """获取每日汇总数据（取每天最新小时快照）"""
    try:
        conn = data_manager.get_connection()

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

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
                SUM(activates) as daily_activates,
                SUM(installs) as daily_installs,
                CASE
                    WHEN SUM(impressions) > 0 THEN ROUND(SUM(clicks) * 100.0 / SUM(impressions), 2)
                    ELSE 0
                END as daily_ctr,
                CASE
                    WHEN SUM(registers) > 0 THEN ROUND(SUM(spend) / SUM(registers), 4)
                    ELSE 0
                END as daily_register_cpa,
                SUM(amount) as daily_amount,
                CASE
                    WHEN SUM(spend) > 0 THEN ROUND(SUM(amount) / SUM(spend), 2)
                    ELSE 0
                END as daily_roi
            FROM hourly_data
            {where_clause}
            GROUP BY DATE(hour_start), advertiser_id
            ORDER BY date DESC, advertiser_name
        '''

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        daily_data = {}
        for _, row in df.iterrows():
            date_str = row["date"]
            if date_str not in daily_data:
                daily_data[date_str] = {
                    "date": date_str,
                    "advertisers": [],
                    "total_spend": 0,
                    "total_registers": 0,
                    "total_activates": 0,
                    "total_installs": 0,
                    "total_impressions": 0,
                    "total_clicks": 0
                }

            advertiser_data = {
                "name": row["advertiser_name"],
                "spend": float(row["daily_spend"]),
                "impressions": int(row["daily_impressions"]),
                "clicks": int(row["daily_clicks"]),
                "registers": int(row["daily_registers"]),
                "activates": int(row["daily_activates"]),
                "installs": int(row["daily_installs"]),
                "ctr": float(row["daily_ctr"]),
                "register_cpa": float(row["daily_register_cpa"]),
                "amount": float(row["daily_amount"]),
                "roi": float(row["daily_roi"])
            }

            daily_data[date_str]["advertisers"].append(advertiser_data)
            daily_data[date_str]["total_spend"] += advertiser_data["spend"]
            daily_data[date_str]["total_registers"] += advertiser_data["registers"]
            daily_data[date_str]["total_activates"] += advertiser_data["activates"]
            daily_data[date_str]["total_installs"] += advertiser_data["installs"]
            daily_data[date_str]["total_impressions"] += advertiser_data["impressions"]
            daily_data[date_str]["total_clicks"] += advertiser_data["clicks"]

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
        conn = data_manager.get_connection()

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
        reports_dir = data_manager.config["_data_dir"] / "weekly_reports"
        report_files = list(reports_dir.glob(f"weekly_report_{week_start}_*.json"))

        if not report_files:
            raise HTTPException(status_code=404, detail="周报不存在")

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


def _get_week_data(conn, week_start: datetime, week_end: datetime) -> List[Dict]:
    """获取指定周的数据（内部辅助函数）"""
    query = '''
        SELECT
            DATE(hour_start) as date,
            SUM(spend) as daily_spend,
            SUM(impressions) as daily_impressions,
            SUM(clicks) as daily_clicks,
            SUM(registers) as daily_registers,
            SUM(activates) as daily_activates,
            SUM(installs) as daily_installs,
            SUM(amount) as daily_amount
        FROM hourly_data
        WHERE hour_start >= ? AND hour_start < ?
        GROUP BY DATE(hour_start)
        ORDER BY date
    '''
    df = pd.read_sql_query(query, conn, params=(week_start, week_end))

    records = []
    for _, row in df.iterrows():
        records.append({
            "date": row["date"],
            "spend": float(row["daily_spend"]),
            "impressions": int(row["daily_impressions"]),
            "clicks": int(row["daily_clicks"]),
            "registers": int(row["daily_registers"]),
            "activates": int(row["daily_activates"]),
            "installs": int(row["daily_installs"]),
            "amount": float(row["daily_amount"])
        })
    return records


def _calc_week_summary(records: List[Dict]) -> Dict:
    """计算周汇总指标"""
    total_spend = sum(r["spend"] for r in records)
    total_impressions = sum(r["impressions"] for r in records)
    total_clicks = sum(r["clicks"] for r in records)
    total_registers = sum(r["registers"] for r in records)
    total_activates = sum(r["activates"] for r in records)
    total_installs = sum(r["installs"] for r in records)
    total_amount = sum(r["amount"] for r in records)

    return {
        "spend": total_spend,
        "impressions": total_impressions,
        "clicks": total_clicks,
        "ctr": round(total_clicks / total_impressions, 4) if total_impressions > 0 else 0,
        "registers": total_registers,
        "activates": total_activates,
        "installs": total_installs,
        "amount": total_amount,
        "roi": round(total_amount / total_spend, 2) if total_spend > 0 else 0
    }


@app.get("/api/weekly/current")
async def get_weekly_current(
    week_offset: int = Query(0, description="周偏移量，0=本周，1=上周，2=上上周", ge=0, le=12)
):
    """获取本周/指定周数据，并附带上周环比对比"""
    today = datetime.utcnow()
    days_since_monday = today.weekday()

    # 计算目标周
    current_week_start = today - timedelta(days=days_since_monday + week_offset * 7)
    current_week_start = current_week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    current_week_end = current_week_start + timedelta(days=7)

    # 计算上周
    last_week_start = current_week_start - timedelta(days=7)
    last_week_end = current_week_start

    try:
        conn = data_manager.get_connection()

        current_week_data = _get_week_data(conn, current_week_start, current_week_end)
        last_week_data = _get_week_data(conn, last_week_start, last_week_end)

        conn.close()

        current_summary = _calc_week_summary(current_week_data)
        last_summary = _calc_week_summary(last_week_data)

        # 计算环比变化
        def _pct_change(cur, prev):
            if prev == 0:
                return None if cur == 0 else 99999.99
            return round((cur - prev) / prev * 100, 2)

        comparison = {
            "spend_change": _pct_change(current_summary["spend"], last_summary["spend"]),
            "impressions_change": _pct_change(current_summary["impressions"], last_summary["impressions"]),
            "clicks_change": _pct_change(current_summary["clicks"], last_summary["clicks"]),
            "registers_change": _pct_change(current_summary["registers"], last_summary["registers"]),
            "amount_change": _pct_change(current_summary["amount"], last_summary["amount"]),
            "roi_change": _pct_change(current_summary["roi"], last_summary["roi"])
        }

        return {
            "week_offset": week_offset,
            "current_week": {
                "week_start": current_week_start.isoformat(),
                "week_end": current_week_end.isoformat(),
                "summary": current_summary,
                "daily_data": current_week_data
            },
            "last_week": {
                "week_start": last_week_start.isoformat(),
                "week_end": last_week_end.isoformat(),
                "summary": last_summary,
                "daily_data": last_week_data
            },
            "comparison": comparison
        }

    except Exception as e:
        logger.error(f"获取本周数据失败: {e}")
        raise HTTPException(status_code=500, detail="获取数据失败")


@app.get("/api/historical-data")
async def get_historical_data(
    metric: str = Query("spend", description="指标名称",
                       enum=["spend", "impressions", "clicks", "registers", "amount", "roi", "activates", "installs"]),
    group_by: str = Query("day", description="分组方式",
                         enum=["hour", "day", "week"]),
    days: int = Query(30, description="天数", ge=1, le=90)
):
    """获取历史数据趋势"""
    try:
        conn = data_manager.get_connection()

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        if group_by == "hour":
            group_expr = "DATE(hour_start) || ' ' || strftime('%H', hour_start) || ':00'"
            order_expr = "hour_start"
            query = f'''
                SELECT
                    {group_expr} as time_group,
                    SUM({metric}) as total_value
                FROM hourly_data
                WHERE hour_start >= ? AND hour_start <= ?
                GROUP BY strftime('%Y-%m-%d %H', hour_start)
                ORDER BY {order_expr}
            '''
            df = pd.read_sql_query(query, conn, params=(start_date, end_date))
        else:
            # day / week 取每天最新快照
            group_expr_map = {
                "day": ("DATE(h.hour_start)", "DATE(h.hour_start)"),
                "week": ("STRFTIME('%Y-W%W', h.hour_start)", "STRFTIME('%Y-W%W', h.hour_start)")
            }
            group_expr, order_expr = group_expr_map[group_by]
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
    """获取实时指标（取最新小时快照）"""
    try:
        conn = data_manager.get_connection()

        current_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        next_hour = current_hour + timedelta(hours=1)

        query = '''
            SELECT
                COUNT(DISTINCT advertiser_id) as active_advertisers,
                COUNT(DISTINCT campaign_id) as active_campaigns,
                SUM(spend) as current_hour_spend,
                SUM(registers) as current_hour_registers,
                SUM(activates) as current_hour_activates,
                SUM(installs) as current_hour_installs,
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
                    "spend": float(row[2] or 0),
                    "registers": int(row[3] or 0),
                    "activates": int(row[4] or 0),
                    "installs": int(row[5] or 0),
                    "impressions": int(row[6] or 0),
                    "clicks": int(row[7] or 0)
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
                    "activates": 0,
                    "installs": 0,
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
        output_dir = data_manager.config["_data_dir"] / "temp"
        output_dir.mkdir(exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{report_type}_report_{timestamp}.csv"
        filepath = output_dir / filename

        conn = data_manager.get_connection()

        if report_type == "hourly":
            query = '''
                SELECT
                    advertiser_id,
                    advertiser_name,
                    campaign_id,
                    campaign_name,
                    adgroup_id,
                    adgroup_name,
                    creative_id,
                    creative_name,
                    goal,
                    spend,
                    impressions,
                    clicks,
                    ctr,
                    ecpm,
                    installs,
                    install_rate,
                    cpi,
                    activates,
                    activate_cvr,
                    activate_cpa,
                    registers,
                    register_cvr,
                    register_cpa,
                    amount,
                    roi,
                    cpc,
                    hour_start,
                    hour_end
                FROM hourly_data
                ORDER BY hour_start DESC
            '''
        elif report_type == "daily":
            query = '''
                SELECT
                    DATE(hour_start) as date,
                    advertiser_id,
                    advertiser_name,
                    campaign_id,
                    campaign_name,
                    adgroup_id,
                    adgroup_name,
                    creative_id,
                    creative_name,
                    SUM(spend) as total_spend,
                    SUM(impressions) as total_impressions,
                    SUM(clicks) as total_clicks,
                    SUM(registers) as total_registers,
                    SUM(activates) as total_activates,
                    SUM(installs) as total_installs,
                    SUM(amount) as total_amount
                FROM hourly_data
                GROUP BY DATE(hour_start), creative_id
                ORDER BY date DESC, advertiser_name
            '''
        else:  # weekly
            query = '''
                SELECT
                    STRFTIME('%Y-W%W', hour_start) as week,
                    advertiser_id,
                    advertiser_name,
                    campaign_id,
                    campaign_name,
                    adgroup_id,
                    adgroup_name,
                    creative_id,
                    creative_name,
                    SUM(spend) as total_spend,
                    SUM(registers) as total_registers,
                    SUM(activates) as total_activates,
                    SUM(installs) as total_installs,
                    SUM(amount) as total_amount,
                    AVG(roi) as avg_roi
                FROM hourly_data
                GROUP BY STRFTIME('%Y-W%W', hour_start), creative_id
                ORDER BY week DESC, advertiser_name
            '''

        df = pd.read_sql_query(query, conn)
        conn.close()

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
        try:
            from weekly_report_generator import WeeklyReportGenerator
            generator = WeeklyReportGenerator()
            report = generator.generate_weekly_report()
            if report:
                logger.info(f"定时周报生成成功: {report.get('report_path', '')}")
        except Exception as e:
            logger.error(f"定时周报生成失败: {e}")

    schedule.every().friday.at("23:45").do(generate_report)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=schedule_weekly_report, daemon=True)
    scheduler_thread.start()

    config = data_manager.config
    port = config.get("api_port", 8090)

    logger.info(f"启动PS系统数据API服务，端口: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
