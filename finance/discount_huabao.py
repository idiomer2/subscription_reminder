"""
@crontab: 30 09 * * 1-5 cd $reminder_home && $PYTHON -u -m finance.discount_huabao 2>&1 | tee -a logs/discount_huabao.log
"""
import json
import re
import time
import math
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from functools import lru_cache

import requests
from dotenv import dotenv_values

from pyutils.date_util import stamp2time, stamp2str, now, now_time
from pyutils.notify_util import Feishu, Pushme, Bark


@lru_cache(maxsize=100)
def get_holiday_data(year):
    """
    获取指定年份的节假日数据
    使用 timor.tech 免费API
    """
    url = f"https://timor.tech/api/holiday/year/{year}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('code') == 0:
            return data.get('holiday', {})
    except Exception as e:
        print(f"获取 {year} 年节假日数据失败: {e}")
        # 如果获取失败，返回空字典，后续逻辑会降级为仅判断周末
        return {}
    return {}


def is_a_share_trading_day(target_date, holiday_data):
    """
    判断某一天是否为A股交易日
    逻辑：
    1. 周六周日 -> 休市
    2. 法定节假日(周一至周五) -> 休市
    3. 调休上班的周末 -> A股依然休市
    """
    date_str = target_date.strftime('%Y-%m-%d')
    short_date_str = target_date.strftime('%m-%d') # API 的键通常是 MM-DD
    # 1. 判断是否为周末 (0=周一, 6=周日)
    weekday = target_date.weekday()
    is_weekend = weekday >= 5
    # 2. 判断是否为法定节假日
    # API 返回格式示例: "10-01": {"holiday": true, "name": "国庆节", ...}
    is_legal_holiday = False
    holiday_info = holiday_data.get(short_date_str)
    if holiday_info:
        # 如果 API 标记 holiday 为 True，则是法定节假日
        if holiday_info['holiday'] is True:
            is_legal_holiday = True
    # A股交易日规则：非周末 且 非法定节假日
    # 注意：A股有个特点，即使是“调休上班”的周六日，股市也是不开的。
    # 所以只要是周末，或者只要是法定假日，都不开市。
    if is_weekend:
        return False, "休市 (周末)"
    if is_legal_holiday:
        name = holiday_info.get('name', '节假日')
        return False, f"休市 ({name})"
    return True, "交易日"


def is_trade_date(date_obj: datetime) -> bool:
    """ 判断指定日期是否为交易日 """
    year = date_obj.year
    holiday_data = get_holiday_data(year)
    return is_a_share_trading_day(date_obj, holiday_data)


def fetch_realtime_price(code: str) -> Dict[str, float]:
    """
    获取基金实时价格
    """
    try:
        # 构造symbol，需要根据基金类型确定前缀
        # 这里假设是上海市场的基金，实际情况可能需要调整
        symbol = f"sh{code}"
        url = f"https://qt.gtimg.cn/q={symbol}&t={time.time()}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://quote.eastmoney.com/',
            'Accept': '*/*',
        }
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        # 响应格式示例: v_sh000001="1~平安银行~000001~13.45~13.40~..."
        content = response.text
        # 解析数据
        if '=' in content:
            data_str = content.split('=')[1].strip('";')
            parts = data_str.split('~')
            if len(parts) >= 33:
                price = float(parts[3]) if parts[3] else 0.0
                pct = float(parts[32]) if parts[32] else 0.0
                return {'price': price, 'pct': pct}
        return {'price': 0.0, 'pct': 0.0}
    except requests.RequestException as e:
        print(f"获取基金{code}实时价格时网络错误: {e}")
        return {'price': 0.0, 'pct': 0.0}
    except (ValueError, IndexError) as e:
        print(f"解析基金{code}实时价格时出错: {e}")
        return {'price': 0.0, 'pct': 0.0}
    except Exception as e:
        print(f"获取基金{code}实时价格时发生未知错误: {e}")
        return {'price': 0.0, 'pct': 0.0}


class HuaBaoMonitor:
    def __init__(self, fund_code='511990', low_price=99.993):
        self.fund_code = fund_code
        self.low_price = low_price
    
    def run(self):
        if not is_trade_date(now_time()):
            print(f"今天({now_time().strftime('%Y-%m-%d')})不是交易日")
            return

        tonight_nav_estimated = 100.0029
        alerted_price = float('inf')
        while '09:30' <= now_time().strftime('%H:%M') < '15:00':
            price_rt = fetch_realtime_price(self.fund_code)['price']
            discount = tonight_nav_estimated - price_rt
            if price_rt < self.low_price and price_rt < alerted_price:
                alerted_price = price_rt

                title, content = '华宝折价511990', '\n\n'.join(['折价套利：', f'- 今晚净值预估: {tonight_nav_estimated}', f'- 场内实时价格: {price_rt}', f'- 折价: 万分之{discount*100:.2f}'])
                print(); print(content.replace('\n', ' ')); print()
                try:
                    Feishu(ENV['FEISHU_WEBHOOK_TOKEN']).send_markdown(title, content)
                finally:
                    cate, icon = '折价套利', '💰'
                    Pushme(ENV['PUSHME_PUSH_KEY']).send_markdown(f'[#{cate}!{icon}]'+title, content)
            else:
                content = '\n\n'.join([f'- 今晚净值预估: {tonight_nav_estimated}', f'- 场内实时价格: {price_rt}', f'- 折价: 万分之{discount*100:.2f}'])
                print(content.replace('\n', ' '))
            time.sleep(60)


if __name__ == '__main__':
    ENV = dotenv_values()
    print(f'\n\n\n=============== {now()} ===============')

    monitor = HuaBaoMonitor('511990', low_price=99.993)
    monitor.run()


