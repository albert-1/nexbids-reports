#!/usr/bin/env python3
"""
PS系统数据采集器 - 每小时自动采集所有广告主的投放数据
支持多维度查询和小时级数据采集
"""

import os
import json
import time
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import pandas as pd
from pathlib import Path
import sqlite3
import schedule
import threading

# 引入统一配置
from config import load_config, init_database, PROJECT_ROOT

# 配置日志
log_dir = PROJECT_ROOT / "logs"
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "ps_system_log.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class PSDataCollector:
    """PS系统数据采集器"""

    def __init__(self, config_path: Path = None):
        """初始化采集器"""
        self.config = load_config(config_path)
        self.data_dir = self.config["_data_dir"]
        self.log_dir = self.config["_log_dir"]

        # 数据库连接
        self.db_path = self.config["_db_path"]
        init_database(self.db_path)

        # 当前广告主列表
        self.advertisers = self.config.get("advertisers", [])
        self.last_collection_time = None
        self.use_mock = self.config.get("data_collection_method", "web_scraping") == "mock"

        # API 认证状态
        self._token = None
        self._token_expire_at = None

        logger.info(f"PS数据采集器初始化完成，数据目录: {self.data_dir}")

    def get_current_hour_range(self) -> tuple:
        """获取当前小时的时间范围（UTC时间）"""
        now = datetime.utcnow()
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)
        return hour_start, hour_end

    def _get_auth_token(self) -> str:
        """登录并获取 JWT Token"""
        import requests

        ps_url = self.config.get("ps_system_url", "https://dsp.nexbids.com")
        username = self.config.get("username", "")
        password = self.config.get("password", "")

        if not username or not password:
            raise ValueError("用户名或密码未配置")

        # 如果 token 还没过期，直接复用
        if self._token and self._token_expire_at and datetime.utcnow() < self._token_expire_at:
            return self._token

        login_url = f"{ps_url}/api/user/login"
        payload = {"email": username, "password": password}

        resp = requests.post(login_url, json=payload, timeout=30)
        resp.raise_for_status()

        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"登录失败: {result.get('message', '未知错误')}")

        token = result["data"]["token"]
        expire_seconds = result["data"].get("expire", 259200)

        self._token = token
        self._token_expire_at = datetime.utcnow() + timedelta(seconds=expire_seconds - 300)  # 提前5分钟刷新

        logger.info(f"登录成功，Token 有效期 {expire_seconds} 秒")
        return token

    def collect_data_for_advertiser(self, advertiser_id: str, advertiser_name: str) -> bool:
        """为指定广告主采集数据"""
        logger.info(f"开始为广告主采集数据: {advertiser_name} ({advertiser_id})")

        start_time = datetime.utcnow()
        hour_start, hour_end = self.get_current_hour_range()

        try:
            if self.use_mock:
                data = self.generate_mock_data(advertiser_id, advertiser_name, hour_start)
                logger.info(f"使用模拟数据模式: {advertiser_name}")
            else:
                data = self.fetch_real_data(advertiser_id, advertiser_name, hour_start)
                logger.info(f"使用真实采集模式: {advertiser_name}")

            # 保存到数据库
            success = self.save_hourly_data(data, advertiser_id, advertiser_name, hour_start, hour_end)

            # 更新广告主信息
            self.update_advertiser_info(advertiser_id, advertiser_name)

            # 记录采集日志
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            self.log_collection(advertiser_id, 'success', len(data), None, start_time, end_time, duration)

            logger.info(f"广告主数据采集完成: {advertiser_name}, 数据量: {len(data)}")
            return True

        except Exception as e:
            logger.error(f"广告主数据采集失败 {advertiser_name}: {e}")

            # 记录错误日志
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            self.log_collection(advertiser_id, 'failed', 0, str(e), start_time, end_time, duration)
            return False

    def fetch_real_data(self, advertiser_id: str, advertiser_name: str, hour_start: datetime) -> List[Dict[str, Any]]:
        """
        从真实PS系统 (dsp.nexbids.com) 获取数据
        系统返回的是当日累计数据，我们按当前小时存储为快照
        """
        import requests

        ps_url = self.config.get("ps_system_url", "https://dsp.nexbids.com")
        token = self._get_auth_token()

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        report_url = (
            f"{ps_url}/api/report/operation/list"
            f"?pageNo=1&pageSize=100"
            f"&advertiserId={advertiser_id}"
            f"&startDate={today_str}&endDate={today_str}"
            f"&viewType=2"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        resp = requests.get(report_url, headers=headers, timeout=60)
        resp.raise_for_status()

        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"报表接口返回错误: {result.get('message', '未知错误')}")

        rows = result.get("data", {}).get("rows", [])
        if not rows:
            logger.warning(f"广告主 {advertiser_name} 今日暂无数据")
            return []

        normalized = []
        for item in rows:
            # 映射真实系统字段到内部字段
            # API 字段: spend(str), impressions(int), clicks(int), installs(int),
            # activates(int), registers(int), amount(str), roi(number),
            # installRate(number), activateCVR(number), registerCVR(number),
            # ctr(number), cpi(str), cpa_a(str), cpa_r(str), cpc(str), ecpm(str)
            def _float(val):
                try:
                    return float(val) if val is not None else 0.0
                except (ValueError, TypeError):
                    return 0.0

            def _int(val):
                try:
                    return int(val) if val is not None else 0
                except (ValueError, TypeError):
                    return 0

            normalized.append({
                "advertiser_id": advertiser_id,
                "advertiser_name": advertiser_name,
                "campaign_id": str(item.get("campaignId", "")),
                "campaign_name": item.get("campaignName", "Unknown"),
                "adgroup_id": str(item.get("adGroupId", "")),
                "adgroup_name": item.get("adGroupName", "Unknown"),
                "creative_id": str(item.get("creativeId", "")),
                "creative_name": item.get("creativeName", "Unknown"),
                "goal": item.get("goal") if item.get("goal") else "CPL",
                "spend": _float(item.get("spend")),
                "impressions": _int(item.get("impressions")),
                "clicks": _int(item.get("clicks")),
                "ctr": _float(item.get("ctr")),
                "ecpm": _float(item.get("ecpm")),
                "installs": _int(item.get("installs")),
                "install_rate": _float(item.get("installRate")),
                "cpi": _float(item.get("cpi")),
                "activates": _int(item.get("activates")),
                "activate_cvr": _float(item.get("activateCVR")),
                "activate_cpa": _float(item.get("cpa_a")),
                "registers": _int(item.get("registers")),
                "register_cvr": _float(item.get("registerCVR")),
                "register_cpa": _float(item.get("cpa_r")),
                "amount": _float(item.get("amount")),
                "roi": _float(item.get("roi")),
                "cpc": _float(item.get("cpc")),
                "hour_start": hour_start
            })

        logger.info(f"从真实系统获取到 {len(normalized)} 条创意级数据")
        return normalized

    def generate_mock_data(self, advertiser_id: str, advertiser_name: str, hour_start: datetime) -> List[Dict[str, Any]]:
        """生成模拟数据（用于测试或fallback）"""
        import random

        campaigns = [
            {"id": f"{advertiser_id}_campaign_001", "name": f"{advertiser_name}-Campaign-A"},
            {"id": f"{advertiser_id}_campaign_002", "name": f"{advertiser_name}-Campaign-B"},
            {"id": f"{advertiser_id}_campaign_003", "name": f"{advertiser_name}-Campaign-C"}
        ]

        data = []
        for campaign in campaigns:
            for i in range(random.randint(2, 3)):
                adgroup_id = f"{campaign['id']}_adgroup_{i+1:03d}"
                adgroup_name = f"{campaign['name']}-AdGroup-{i+1}"

                for j in range(random.randint(1, 2)):
                    creative_id = f"{adgroup_id}_creative_{j+1:03d}"
                    creative_name = f"{adgroup_name}-Creative-{j+1}"

                    spend = round(random.uniform(10.0, 100.0), 4)
                    impressions = random.randint(1000, 10000)
                    clicks = random.randint(10, 200)
                    ctr = round(clicks / impressions * 100, 2) if impressions > 0 else 0
                    registers = random.randint(0, 20)
                    amount = round(random.uniform(50.0, 500.0), 2)
                    roi = round((amount - spend) / spend * 100, 2) if spend > 0 else 0

                    data.append({
                        "advertiser_id": advertiser_id,
                        "advertiser_name": advertiser_name,
                        "campaign_id": campaign["id"],
                        "campaign_name": campaign["name"],
                        "adgroup_id": adgroup_id,
                        "adgroup_name": adgroup_name,
                        "creative_id": creative_id,
                        "creative_name": creative_name,
                        "goal": "CPL",
                        "spend": spend,
                        "impressions": impressions,
                        "clicks": clicks,
                        "ctr": ctr,
                        "ecpm": round(spend / impressions * 1000, 4) if impressions > 0 else 0,
                        "installs": random.randint(0, 10),
                        "install_rate": 0,
                        "cpi": 0,
                        "activates": random.randint(0, 10),
                        "activate_cvr": 0,
                        "activate_cpa": 0,
                        "registers": registers,
                        "register_cvr": 0,
                        "register_cpa": round(spend / registers, 4) if registers > 0 else 0,
                        "amount": amount,
                        "roi": roi,
                        "cpc": round(spend / clicks, 4) if clicks > 0 else 0,
                        "hour_start": hour_start
                    })

        return data

    def save_hourly_data(self, data: List[Dict[str, Any]], advertiser_id: str,
                         advertiser_name: str, hour_start: datetime, hour_end: datetime) -> bool:
        """保存小时级数据到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            for item in data:
                cursor.execute('''
                    INSERT OR REPLACE INTO hourly_data
                    (advertiser_id, advertiser_name, campaign_id, campaign_name,
                     adgroup_id, adgroup_name, creative_id, creative_name,
                     goal, spend, impressions, clicks, ctr, ecpm,
                     installs, install_rate, cpi, activates, activate_cvr, activate_cpa,
                     registers, register_cvr, register_cpa, amount, roi, cpc,
                     hour_start, hour_end, collection_time, data_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    advertiser_id,
                    advertiser_name,
                    item.get('campaign_id'),
                    item.get('campaign_name'),
                    item.get('adgroup_id'),
                    item.get('adgroup_name'),
                    item.get('creative_id'),
                    item.get('creative_name'),
                    item.get('goal'),
                    item.get('spend', 0.0),
                    item.get('impressions', 0),
                    item.get('clicks', 0),
                    item.get('ctr', 0.0),
                    item.get('ecpm', 0.0),
                    item.get('installs', 0),
                    item.get('install_rate', 0.0),
                    item.get('cpi', 0.0),
                    item.get('activates', 0),
                    item.get('activate_cvr', 0.0),
                    item.get('activate_cpa', 0.0),
                    item.get('registers', 0),
                    item.get('register_cvr', 0.0),
                    item.get('register_cpa', 0.0),
                    item.get('amount', 0.0),
                    item.get('roi', 0.0),
                    item.get('cpc', 0.0),
                    hour_start,
                    hour_end,
                    datetime.utcnow(),
                    'mock' if self.use_mock else 'api'
                ))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            logger.error(f"保存小时级数据失败: {e}")
            return False

    def update_advertiser_info(self, advertiser_id: str, advertiser_name: str) -> None:
        """更新广告主信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO advertisers (advertiser_id, advertiser_name, last_collected)
                VALUES (?, ?, ?)
            ''', (advertiser_id, advertiser_name, datetime.utcnow()))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"更新广告主信息失败: {e}")

    def log_collection(self, advertiser_id: str, status: str, data_count: int,
                      error_message: Optional[str], start_time: datetime,
                      end_time: datetime, duration_seconds: float) -> None:
        """记录采集日志"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO collection_logs
                (advertiser_id, status, data_count, error_message, start_time, end_time, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (advertiser_id, status, data_count, error_message, start_time, end_time, duration_seconds))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"记录采集日志失败: {e}")

    def collect_all_advertisers(self) -> Dict[str, Any]:
        """采集所有广告主的数据"""
        logger.info("开始采集所有广告主数据")

        advertisers = self.config.get("advertisers", [])
        if not advertisers:
            advertisers = [
                {"id": "10001", "name": "zeydoo", "active": True}
            ]

        active_advertisers = [a for a in advertisers if a.get("active", True)]

        results = {
            "total_advertisers": len(active_advertisers),
            "success_count": 0,
            "failed_count": 0,
            "total_data_count": 0,
            "start_time": datetime.utcnow().isoformat(),
            "details": []
        }

        for advertiser in active_advertisers:
            success = self.collect_data_for_advertiser(advertiser["id"], advertiser["name"])

            detail = {
                "advertiser_id": advertiser["id"],
                "advertiser_name": advertiser["name"],
                "status": "success" if success else "failed",
                "collection_time": datetime.utcnow().isoformat()
            }
            results["details"].append(detail)

            if success:
                results["success_count"] += 1
            else:
                results["failed_count"] += 1

        results["end_time"] = datetime.utcnow().isoformat()
        results["duration_seconds"] = (datetime.fromisoformat(results["end_time"]) -
                                      datetime.fromisoformat(results["start_time"])).total_seconds()

        logger.info(f"所有广告主数据采集完成: {results['success_count']}成功, {results['failed_count']}失败")
        self.save_collection_summary(results)
        return results

    def save_collection_summary(self, results: Dict[str, Any]) -> None:
        """保存采集结果摘要"""
        try:
            summary_dir = self.data_dir / "summaries"
            summary_dir.mkdir(exist_ok=True)

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            summary_file = summary_dir / f"collection_summary_{timestamp}.json"

            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

            logger.info(f"采集结果摘要已保存: {summary_file}")

        except Exception as e:
            logger.error(f"保存采集结果摘要失败: {e}")

    def generate_hourly_report(self, hour_start: Optional[datetime] = None) -> pd.DataFrame:
        """生成小时级数据报告"""
        if hour_start is None:
            hour_start, _ = self.get_current_hour_range()

        try:
            conn = sqlite3.connect(self.db_path)

            query = '''
                SELECT
                    advertiser_name,
                    campaign_name,
                    adgroup_name,
                    creative_name,
                    SUM(spend) as total_spend,
                    SUM(impressions) as total_impressions,
                    SUM(clicks) as total_clicks,
                    CASE
                        WHEN SUM(impressions) > 0 THEN ROUND(SUM(clicks) * 100.0 / SUM(impressions), 2)
                        ELSE 0
                    END as overall_ctr,
                    SUM(registers) as total_registers,
                    SUM(activates) as total_activates,
                    SUM(installs) as total_installs,
                    SUM(amount) as total_amount,
                    CASE
                        WHEN SUM(spend) > 0 THEN ROUND((SUM(amount) - SUM(spend)) * 100.0 / SUM(spend), 2)
                        ELSE 0
                    END as overall_roi
                FROM hourly_data
                WHERE hour_start = ?
                GROUP BY advertiser_id, campaign_id, adgroup_id, creative_id
                ORDER BY advertiser_name, total_spend DESC
            '''

            df = pd.read_sql_query(query, conn, params=(hour_start,))
            conn.close()
            return df

        except Exception as e:
            logger.error(f"生成小时级报告失败: {e}")
            return pd.DataFrame()

    def generate_weekly_report(self, week_start: Optional[datetime] = None) -> Dict[str, Any]:
        """生成周报数据（上周六到本周五）"""
        if week_start is None:
            today = datetime.utcnow()
            days_since_friday = (today.weekday() - 4) % 7
            last_friday = today - timedelta(days=days_since_friday)
            week_start = last_friday - timedelta(days=6)

        week_end = week_start + timedelta(days=6)

        try:
            conn = sqlite3.connect(self.db_path)

            summary_query = '''
                SELECT
                    advertiser_name,
                    COUNT(DISTINCT campaign_id) as campaign_count,
                    COUNT(DISTINCT adgroup_id) as adgroup_count,
                    COUNT(DISTINCT creative_id) as creative_count,
                    SUM(spend) as total_spend,
                    SUM(impressions) as total_impressions,
                    SUM(clicks) as total_clicks,
                    SUM(registers) as total_registers,
                    SUM(activates) as total_activates,
                    SUM(installs) as total_installs,
                    SUM(amount) as total_amount,
                    ROUND(AVG(roi), 2) as avg_roi
                FROM hourly_data
                WHERE hour_start >= ? AND hour_start <= ?
                GROUP BY advertiser_id
                ORDER BY total_spend DESC
            '''

            daily_trend_query = '''
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
                WHERE hour_start >= ? AND hour_start <= ?
                GROUP BY DATE(hour_start)
                ORDER BY date
            '''

            summary_df = pd.read_sql_query(summary_query, conn, params=(week_start, week_end))
            daily_trend_df = pd.read_sql_query(daily_trend_query, conn, params=(week_start, week_end))

            conn.close()

            report = {
                "period": {
                    "week_start": week_start.isoformat(),
                    "week_end": week_end.isoformat(),
                    "generated_at": datetime.utcnow().isoformat()
                },
                "summary": summary_df.to_dict('records'),
                "daily_trends": daily_trend_df.to_dict('records'),
                "key_metrics": {
                    "total_spend": summary_df["total_spend"].sum(),
                    "total_registers": summary_df["total_registers"].sum(),
                    "total_activates": summary_df["total_activates"].sum(),
                    "total_installs": summary_df["total_installs"].sum(),
                    "avg_register_cpa": summary_df["total_spend"].sum() / summary_df["total_registers"].sum() if summary_df["total_registers"].sum() > 0 else 0,
                    "total_roi": ((summary_df["total_amount"].sum() - summary_df["total_spend"].sum()) / summary_df["total_spend"].sum() * 100) if summary_df["total_spend"].sum() > 0 else 0
                }
            }

            return report

        except Exception as e:
            logger.error(f"生成周报失败: {e}")
            return {}

    def start_scheduled_collection(self) -> None:
        """启动定时采集任务"""
        logger.info("启动定时采集任务")

        interval = self.config.get("collection_interval_hours", 1)
        schedule.every(interval).hours.at(":00").do(self.collect_all_advertisers)

        self.collect_all_advertisers()

        while True:
            schedule.run_pending()
            time.sleep(60)

    def cleanup_old_data(self, retention_days: int = None) -> None:
        """清理旧数据"""
        if retention_days is None:
            retention_days = self.config.get("data_retention_days", 30)

        try:
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('DELETE FROM hourly_data WHERE hour_start < ?', (cutoff_date,))
            hourly_deleted = cursor.rowcount

            cursor.execute('DELETE FROM collection_logs WHERE start_time < ?', (cutoff_date,))
            logs_deleted = cursor.rowcount

            conn.commit()
            conn.close()

            logger.info(f"数据清理完成: 删除{hourly_deleted}条小时数据, {logs_deleted}条日志记录")

        except Exception as e:
            logger.error(f"数据清理失败: {e}")


def main():
    """主函数"""
    collector = PSDataCollector()

    schedule.every().day.at("02:00").do(collector.cleanup_old_data)
    collector.start_scheduled_collection()


if __name__ == "__main__":
    main()
