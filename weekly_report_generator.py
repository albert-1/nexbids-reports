#!/usr/bin/env python3
"""
周报生成器
根据数据库中的小时级数据生成周报
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

from config import load_config, PROJECT_ROOT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WeeklyReportGenerator:
    """周报生成器"""

    def __init__(self):
        self.config = load_config()
        self.data_dir = self.config["_data_dir"]
        self.db_path = self.config["_db_path"]

    def generate_weekly_report(self, week_start: Optional[datetime] = None) -> Dict[str, Any]:
        """
        生成周报并保存到文件
        默认生成上周六到本周五的数据
        """
        import sqlite3
        import pandas as pd

        if week_start is None:
            today = datetime.utcnow()
            days_since_friday = (today.weekday() - 4) % 7
            last_friday = today - timedelta(days=days_since_friday)
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
                    "week_start": week_start.strftime("%Y-%m-%d"),
                    "week_end": week_end.strftime("%Y-%m-%d"),
                    "generated_at": datetime.utcnow().isoformat()
                },
                "summary": summary_df.to_dict('records') if not summary_df.empty else [],
                "daily_trends": daily_trend_df.to_dict('records') if not daily_trend_df.empty else [],
                "key_metrics": {
                    "total_spend": float(summary_df["total_spend"].sum()) if not summary_df.empty else 0,
                    "total_registers": int(summary_df["total_registers"].sum()) if not summary_df.empty else 0,
                    "avg_register_cpa": (
                        float(summary_df["total_spend"].sum() / summary_df["total_registers"].sum())
                        if not summary_df.empty and summary_df["total_registers"].sum() > 0 else 0
                    ),
                    "total_roi": (
                        float((summary_df["total_amount"].sum() - summary_df["total_spend"].sum())
                              / summary_df["total_spend"].sum() * 100)
                        if not summary_df.empty and summary_df["total_spend"].sum() > 0 else 0
                    )
                }
            }

            # 保存报告文件
            reports_dir = self.data_dir / "weekly_reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            week_start_str = week_start.strftime("%Y%m%d")
            week_end_str = week_end.strftime("%Y%m%d")

            report_path = reports_dir / f"weekly_report_{week_start_str}_{week_end_str}.json"
            simplified_path = reports_dir / f"simplified_weekly_report_{week_start_str}_{week_end_str}.json"

            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            # 简化版报告（只包含关键指标）
            simplified_report = {
                "period": report["period"],
                "key_metrics": report["key_metrics"],
                "summary_count": len(report["summary"])
            }
            with open(simplified_path, 'w', encoding='utf-8') as f:
                json.dump(simplified_report, f, indent=2, ensure_ascii=False)

            # 更新数据库索引
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO weekly_reports
                (week_start, week_end, report_path, simplified_path)
                VALUES (?, ?, ?, ?)
            ''', (week_start, week_end, str(report_path), str(simplified_path)))
            conn.commit()
            conn.close()

            logger.info(f"周报生成成功: {report_path}")

            report["report_path"] = str(report_path)
            report["simplified_path"] = str(simplified_path)
            return report

        except Exception as e:
            logger.error(f"生成周报失败: {e}")
            return {}


if __name__ == "__main__":
    generator = WeeklyReportGenerator()
    result = generator.generate_weekly_report()
    print(json.dumps(result, indent=2, ensure_ascii=False))
