#!/usr/bin/env python3
"""
PS系统数据采集器 - 每小时自动采集所有广告主的投放数据
支持多维度查询和小时级数据采集
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import pandas as pd
from pathlib import Path
import sqlite3
import schedule
import threading
import sys

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/workspace/ps_system_log.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class PSDataCollector:
    """PS系统数据采集器"""
    
    def __init__(self, config_path: str = "/home/workspace/ps_system_config.json"):
        """初始化采集器"""
        self.config_path = config_path
        self.config = self.load_config()
        self.data_dir = Path("/home/workspace/ps_system_data")
        self.data_dir.mkdir(exist_ok=True)
        
        # 数据库连接
        self.db_path = self.data_dir / "ps_data.db"
        self.init_database()
        
        # 当前广告主列表
        self.advertisers = []
        self.last_collection_time = None
        
        logger.info(f"PS数据采集器初始化完成，数据目录: {self.data_dir}")
    
    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 验证必要配置
            required_keys = ['ps_system_url', 'username', 'password']
            for key in required_keys:
                if key not in config:
                    raise ValueError(f"配置文件中缺少必要键: {key}")
            
            logger.info(f"配置文件加载成功: {self.config_path}")
            return config
            
        except FileNotFoundError:
            logger.error(f"配置文件不存在: {self.config_path}")
            # 创建默认配置
            default_config = {
                "ps_system_url": "https://dsp.nexbids.com",
                "username": "admin@qq.com",
                "password": "a123456",
                "data_retention_days": 30,
                "collection_interval_hours": 1,
                "advertiser_switch_delay": 2,
                "max_retries": 3,
                "timezone": "UTC",
                "web_port": 8080,
                "debug_mode": False
            }
            self.save_config(default_config)
            return default_config
            
        except json.JSONDecodeError as e:
            logger.error(f"配置文件JSON解析错误: {e}")
            raise
    
    def save_config(self, config: Dict[str, Any]) -> None:
        """保存配置文件"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logger.info(f"配置文件已保存: {self.config_path}")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
    
    def init_database(self) -> None:
        """初始化数据库"""
        try:
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
            
            # 创建采集日志表
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
            
            # 创建索引以提高查询性能
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_hourly_advertiser_hour ON hourly_data(advertiser_id, hour_start)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_hourly_collection_time ON hourly_data(collection_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_hourly_campaign ON hourly_data(campaign_id, hour_start)')
            
            conn.commit()
            conn.close()
            logger.info("数据库初始化完成")
            
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise
    
    def get_current_hour_range(self) -> tuple:
        """获取当前小时的时间范围（UTC时间）"""
        now = datetime.utcnow()
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)
        return hour_start, hour_end
    
    def collect_data_for_advertiser(self, advertiser_id: str, advertiser_name: str) -> bool:
        """为指定广告主采集数据"""
        logger.info(f"开始为广告主采集数据: {advertiser_name} ({advertiser_id})")
        
        start_time = datetime.utcnow()
        hour_start, hour_end = self.get_current_hour_range()
        
        try:
            # 这里应该使用浏览器自动化来获取实际数据
            # 由于这是示例，我们使用模拟数据
            mock_data = self.generate_mock_data(advertiser_id, advertiser_name, hour_start)
            
            # 保存到数据库
            success = self.save_hourly_data(mock_data, advertiser_id, advertiser_name, hour_start, hour_end)
            
            # 更新广告主信息
            self.update_advertiser_info(advertiser_id, advertiser_name)
            
            # 记录采集日志
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            self.log_collection(advertiser_id, 'success', len(mock_data), None, start_time, end_time, duration)
            
            logger.info(f"广告主数据采集完成: {advertiser_name}, 数据量: {len(mock_data)}")
            return True
            
        except Exception as e:
            logger.error(f"广告主数据采集失败 {advertiser_name}: {e}")
            
            # 记录错误日志
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            self.log_collection(advertiser_id, 'failed', 0, str(e), start_time, end_time, duration)
            return False
    
    def generate_mock_data(self, advertiser_id: str, advertiser_name: str, hour_start: datetime) -> List[Dict[str, Any]]:
        """生成模拟数据（实际应用中应该从PS系统获取）"""
        import random
        
        # 模拟不同的campaign
        campaigns = [
            {"id": f"{advertiser_id}_campaign_001", "name": f"{advertiser_name}-Campaign-A"},
            {"id": f"{advertiser_id}_campaign_002", "name": f"{advertiser_name}-Campaign-B"},
            {"id": f"{advertiser_id}_campaign_003", "name": f"{advertiser_name}-Campaign-C"}
        ]
        
        data = []
        for campaign in campaigns:
            # 每个campaign有2-3个adgroup
            for i in range(random.randint(2, 3)):
                adgroup_id = f"{campaign['id']}_adgroup_{i+1:03d}"
                adgroup_name = f"{campaign['name']}-AdGroup-{i+1}"
                
                # 每个adgroup有1-2个creative
                for j in range(random.randint(1, 2)):
                    creative_id = f"{adgroup_id}_creative_{j+1:03d}"
                    creative_name = f"{adgroup_name}-Creative-{j+1}"
                    
                    # 生成随机数据
                    spend = round(random.uniform(10.0, 100.0), 4)
                    impressions = random.randint(1000, 10000)
                    clicks = random.randint(10, 200)
                    ctr = round(clicks / impressions * 100, 2) if impressions > 0 else 0
                    registers = random.randint(0, 20)  # 注册数
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
                        "spend": spend,
                        "impressions": impressions,
                        "clicks": clicks,
                        "ctr": ctr,
                        "registers": registers,
                        "register_cpa": round(spend / registers, 4) if registers > 0 else 0,
                        "amount": amount,
                        "roi": roi,
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
                     spend, impressions, clicks, ctr, registers, register_cpa, 
                     amount, roi, hour_start, hour_end, collection_time, data_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    advertiser_id,
                    advertiser_name,
                    item.get('campaign_id'),
                    item.get('campaign_name'),
                    item.get('adgroup_id'),
                    item.get('adgroup_name'),
                    item.get('creative_id'),
                    item.get('creative_name'),
                    item.get('spend', 0.0),
                    item.get('impressions', 0),
                    item.get('clicks', 0),
                    item.get('ctr', 0.0),
                    item.get('registers', 0),
                    item.get('register_cpa', 0.0),
                    item.get('amount', 0.0),
                    item.get('roi', 0.0),
                    hour_start,
                    hour_end,
                    datetime.utcnow(),
                    'mock'  # 实际应用中应该是 'web'
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
        
        # 获取广告主列表（这里应该从PS系统获取）
        # 暂时使用模拟数据
        advertisers = [
            {"id": "10001", "name": "zeydoo"},
            {"id": "10002", "name": "Zeydoo"}
        ]
        
        results = {
            "total_advertisers": len(advertisers),
            "success_count": 0,
            "failed_count": 0,
            "total_data_count": 0,
            "start_time": datetime.utcnow().isoformat(),
            "details": []
        }
        
        for advertiser in advertisers:
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
        
        # 保存采集结果
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
                    CASE 
                        WHEN SUM(registers) > 0 THEN ROUND(SUM(spend) / SUM(registers), 4)
                        ELSE 0
                    END as overall_register_cpa,
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
            # 计算上周六的时间
            today = datetime.utcnow()
            # 找到本周五
            days_since_friday = (today.weekday() - 4) % 7
            last_friday = today - timedelta(days=days_since_friday)
            # 上周六 = 上周五 - 6天
            week_start = last_friday - timedelta(days=6)
        
        week_end = week_start + timedelta(days=6)
        
        try:
            conn = sqlite3.connect(self.db_path)
            
            # 汇总数据
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
                    SUM(amount) as total_amount,
                    ROUND(AVG(roi), 2) as avg_roi
                FROM hourly_data
                WHERE hour_start >= ? AND hour_start <= ?
                GROUP BY advertiser_id
                ORDER BY total_spend DESC
            '''
            
            # 每日趋势
            daily_trend_query = '''
                SELECT 
                    DATE(hour_start) as date,
                    SUM(spend) as daily_spend,
                    SUM(impressions) as daily_impressions,
                    SUM(clicks) as daily_clicks,
                    SUM(registers) as daily_registers
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
        
        # 每小时整点执行
        schedule.every().hour.at(":00").do(self.collect_all_advertisers)
        
        # 立即执行一次
        self.collect_all_advertisers()
        
        # 运行调度器
        while True:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次
    
    def cleanup_old_data(self, retention_days: int = 30) -> None:
        """清理旧数据"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 删除旧的hourly_data
            cursor.execute('DELETE FROM hourly_data WHERE hour_start < ?', (cutoff_date,))
            hourly_deleted = cursor.rowcount
            
            # 删除旧的collection_logs
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
    
    # 启动清理任务（每天执行一次）
    schedule.every().day.at("02:00").do(collector.cleanup_old_data)
    
    # 启动定时采集
    collector.start_scheduled_collection()

if __name__ == "__main__":
    main()