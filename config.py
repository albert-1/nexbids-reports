#!/usr/bin/env python3
"""
NexBids 统一配置管理模块
解决硬编码路径问题，支持环境变量覆盖敏感配置
"""

import json
import os
import logging
import sqlite3
from pathlib import Path
from typing import Dict, Any

# 项目根目录（本文件所在目录）
PROJECT_ROOT = Path(__file__).parent.resolve()

# 默认数据/日志目录（放在项目内部，也可通过环境变量覆盖）
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"

# 配置文件路径
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "ps_system_config.json"

# 环境变量映射：环境变量名 -> 配置键名
ENV_OVERRIDES = {
    "NEXBIDS_PS_URL": "ps_system_url",
    "NEXBIDS_USERNAME": "username",
    "NEXBIDS_PASSWORD": "password",
    "NEXBIDS_WEB_PORT": "web_port",
    "NEXBIDS_API_PORT": "api_port",
    "NEXBIDS_DATA_DIR": "data_dir",
    "NEXBIDS_LOG_DIR": "log_dir",
}

logger = logging.getLogger(__name__)


def load_config(config_path: Path = None) -> Dict[str, Any]:
    """
    加载配置文件，支持环境变量覆盖敏感字段
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    config = {}

    # 1. 尝试读取 JSON 配置文件
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"配置文件加载成功: {config_path}")
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 解析错误: {e}")
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
    else:
        logger.warning(f"配置文件不存在，将使用默认配置: {config_path}")

    # 2. 环境变量覆盖（优先级最高）
    for env_key, config_key in ENV_OVERRIDES.items():
        env_val = os.environ.get(env_key)
        if env_val is not None:
            # 端口等数字类型转换
            if config_key in ("web_port", "api_port", "data_retention_days",
                              "collection_interval_hours", "max_retries"):
                try:
                    config[config_key] = int(env_val)
                except ValueError:
                    config[config_key] = env_val
            else:
                config[config_key] = env_val
            logger.info(f"配置项 '{config_key}' 已通过环境变量 '{env_key}' 覆盖")

    # 3. 填充默认值
    defaults = {
        "ps_system_url": "https://dsp.nexbids.com",
        "data_retention_days": 30,
        "collection_interval_hours": 1,
        "advertiser_switch_delay": 2,
        "max_retries": 3,
        "timezone": "UTC",
        "web_port": 8081,
        "api_port": 8090,
        "debug_mode": False,
        "data_collection_method": "web_scraping",
        "advertisers": [],
        "metrics": ["spend", "impressions", "clicks", "ctr", "ecpm", "cpc", "installs", "install_rate", "cpi", "activates", "activate_cvr", "activate_cpa", "registers", "register_cvr", "register_cpa", "amount", "roi"],
        "report_config": {
            "hourly_metrics": ["spend", "impressions", "clicks", "registers"],
            "weekly_metrics": ["total_spend", "total_registers", "avg_register_cpa", "total_roi"],
            "chart_types": {
                "hourly_trend": "line",
                "spend_vs_registers": "scatter",
                "performance_comparison": "bar"
            }
        }
    }
    for key, val in defaults.items():
        if key not in config:
            config[key] = val

    # 4. 处理数据/日志目录
    data_dir = config.get("data_dir")
    if data_dir:
        config["_data_dir"] = Path(data_dir).resolve()
    else:
        config["_data_dir"] = DEFAULT_DATA_DIR

    log_dir = config.get("log_dir")
    if log_dir:
        config["_log_dir"] = Path(log_dir).resolve()
    else:
        config["_log_dir"] = DEFAULT_LOG_DIR

    config["_data_dir"].mkdir(parents=True, exist_ok=True)
    config["_log_dir"].mkdir(parents=True, exist_ok=True)

    # 5. 派生路径
    config["_db_path"] = config["_data_dir"] / "ps_data.db"
    config["_config_path"] = Path(config_path).resolve()

    return config


def _add_column_if_not_exists(cursor, table, column, col_type):
    """安全添加列（忽略已存在错误）"""
    try:
        cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise


def init_database(db_path: Path):
    """初始化数据库（统一入口）"""
    conn = sqlite3.connect(db_path)
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

    # 迁移：为旧表添加新列
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

    # 创建索引以提高查询性能
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hourly_advertiser_hour ON hourly_data(advertiser_id, hour_start)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hourly_collection_time ON hourly_data(collection_time)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hourly_campaign ON hourly_data(campaign_id, hour_start)')

    conn.commit()
    conn.close()
    logger.info("数据库初始化完成")


def save_config(config: Dict[str, Any], config_path: Path = None) -> None:
    """保存配置文件（排除内部派生字段）"""
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    # 排除内部字段
    save_keys = {k for k in config.keys() if not k.startswith("_")}
    save_data = {k: config[k] for k in save_keys}

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        logger.info(f"配置文件已保存: {config_path}")
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
