#!/usr/bin/env python3
"""回填4月1号以后的历史数据"""
import sys
sys.path.insert(0, '/Users/adam/.qoderwork/workspace/mo89651o2lc5ox3e/outputs/nexbids_repo_fixed')

from ps_data_collector import PSDataCollector

collector = PSDataCollector()
result = collector.backfill_daily_data("2026-04-01", "2026-04-20")
print(f"回填完成: 成功 {result['success']} 条, 失败 {result['failed']} 条")
print(f"日期: {result['dates']}")
