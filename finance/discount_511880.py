"""
脚本逻辑：
0. 判断今天(Asia/Shanghai)是否是交易日和交易时间。若是则执行下面步骤，否则直接结束
1. 获取最新净值和日期
2. 计算历史净值增长的中位数做为1天的预估增长值
3. 基于预估增长值和交易日，计算下次的预估净值和日期（基金周一到周四更新1天收益，周五更新3天收益，节假日前一天更新包含节假日的收益）
4. 每隔30秒
    - 获取最新场内价格和时间
    - 计算当前价格相对下次预估净值的折价
    - 若折价大于万分之0.5（可配置），print告警；否则打印普通信息

日志查看：
grep -E '最新净值:|下次预估净值:' logs/discount_511880.log
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

from pyutils.date_util import stamp2time, stamp2str, now
from pyutils.notify_util import Feishu, Pushme


# 配置参数
CONFIG = {
    'WARNING_DISCOUNT': 0.5 / 10000,  # 万分之0.5的折价
    'CHECK_INTERVAL': 30,  # 检查间隔30秒
    'TRADING_HOURS': {
        'morning_start': dt_time(9, 30),
        'morning_end': dt_time(11, 30),
        'afternoon_start': dt_time(13, 0),
        'afternoon_end': dt_time(15, 0),
    }
}


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


def fetch_fund_history(code: str) -> Dict[str, Any]:
    """
    获取基金历史净值数据
    """
    try:
        # 构建URL，增加时间戳防止缓存
        timestamp = int(time.time() * 1000)
        url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js?t={timestamp}_{time.time()}"

        # 设置请求头，模拟浏览器
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': f'https://fund.eastmoney.com/{code}.html',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # 从JavaScript中提取数据
        js_content = response.text

        # 提取基金名称
        name_match = re.search(r'fS_name\s*=\s*[\'"]([^\'"]+)[\'"]', js_content)
        name = name_match.group(1) if name_match else code

        # 提取净值趋势数据
        # 寻找 Data_netWorthTrend 赋值语句
        pattern = r'Data_netWorthTrend\s*=\s*(\[.*?\]);'
        match = re.search(pattern, js_content, re.DOTALL)

        if match:
            try:
                # 解析JSON数据
                data_str = match.group(1)
                # 处理可能的JavaScript格式（如日期对象）
                data_str = re.sub(r'new Date\((\d{4}),(\d{1,2}),(\d{1,2})\)',
                                 r'"\1-\2-\3"', data_str)

                history_data = json.loads(data_str)

                # 获取最近20条数据并反转顺序（与JavaScript代码一致）
                recent_data = history_data[-20:][::-1]

                return {
                    'name': name,
                    'history': recent_data
                }
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print(f"解析基金{code}历史数据时出错: {e}")
                return {'name': code, 'history': []}
        else:
            return {'name': code, 'history': []}

    except requests.RequestException as e:
        print(f"获取基金{code}历史数据时网络错误: {e}")
        return {'name': code, 'history': []}
    except Exception as e:
        print(f"获取基金{code}历史数据时发生未知错误: {e}")
        return {'name': code, 'history': []}


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


def calculate_median_growth(history: List[Dict[str, Any]]) -> float:
    """
    计算中位数增长率
    """
    if len(history) < 2:
        return 0.0

    diffs = []
    limit = min(len(history), 11)

    for i in range(limit - 1):
        # 注意：原JavaScript代码中 history[i].y 对应Python中的历史数据项
        # 假设历史数据格式为 [{'y': 1.23, ...}, ...]
        if 'y' in history[i] and 'y' in history[i + 1]:
            curr = history[i]['y']
            prev = history[i + 1]['y']
            diffs.append(abs(curr - prev))

    if not diffs:
        return 0.0

    diffs.sort()
    mid = len(diffs) // 2

    if len(diffs) % 2 != 0:
        return diffs[mid]
    else:
        return round((diffs[mid - 1] + diffs[mid]) / 2, 7)


class FundMonitor:
    def __init__(self, fund_code: str):
        self.fund_code = fund_code
        self.fund_name = ""
        self.latest_nav = 0.0  # 最新净值
        self.latest_nav_date = None  # 最新净值日期
        self.estimated_growth = 0.0  # 预估增长率
        self.next_estimated_nav = 0.0  # 下次预估净值
        self.next_estimated_date = None  # 下次预估日期

    def is_trading_day(self, date_obj: datetime) -> Tuple[bool, str]:
        """
        判断指定日期是否为交易日
        """
        year = date_obj.year
        holiday_data = get_holiday_data(year)
        return is_a_share_trading_day(date_obj, holiday_data)

    def is_trading_time(self, now_time: datetime) -> bool:
        """
        判断当前时间是否为交易时间
        """
        time_only = now_time.time()
        trading_hours = CONFIG['TRADING_HOURS']

        # 上午交易时间
        morning_trading = (trading_hours['morning_start'] <= time_only <= trading_hours['morning_end'])
        # 下午交易时间
        afternoon_trading = (trading_hours['afternoon_start'] <= time_only <= trading_hours['afternoon_end'])

        return morning_trading or afternoon_trading

    def get_next_trading_date(self, start_date: datetime) -> datetime:
        """
        获取下一个交易日
        """
        current_date = start_date
        while True:
            current_date += timedelta(days=1)
            is_trading, _ = self.is_trading_day(current_date)
            if is_trading:
                return current_date

    def calculate_next_update_earndays(self, current_date: datetime) -> int:
        """
        计算下次净值更新的天数
        规则：
        - 周一到周四：更新1天收益，下个交易日
        - 周五：更新3天收益（周六、周日、下周一）
        - 节假日前一天：更新包含假期的所有天数收益
        """
        next_date = current_date  # 下次净值更新时间，也就是今日
        days = 1
        while not self.is_trading_day(next_date + timedelta(1))[0]:
            days += 1
            next_date = next_date + timedelta(1)
        return days

    def fetch_latest_nav(self) -> bool:
        """
        获取最新净值数据
        """
        try:
            history_data = fetch_fund_history(self.fund_code)
            if not history_data['history']:
                print(f"基金{self.fund_code}没有历史数据")
                return False

            self.fund_name = history_data['name']

            # 获取最新净值数据
            latest_item = history_data['history'][0]
            self.latest_nav = latest_item.get('y', 0.0)
            nav_timestamp = latest_item.get('x', 0)

            # 转换时间戳为日期
            if nav_timestamp:
                self.latest_nav_date = stamp2time(nav_timestamp, 'ms').date()
            else:
                # 如果没有时间戳，使用当前日期
                self.latest_nav_date = datetime.now(ZoneInfo('Asia/Shanghai')).date()

            print(f"基金: {self.fund_name}")
            print(f"最新净值: {self.latest_nav:.4f} (日期: {self.latest_nav_date})")

            # 计算历史增长率中位数
            self.estimated_growth = calculate_median_growth(history_data['history'])
            print(f"预估日增长率(中位数): {self.estimated_growth:.6f}")

            return True

        except Exception as e:
            print(f"获取最新净值失败: {e}")
            return False

    def calculate_next_estimation(self) -> bool:
        """
        计算下次预估净值和日期
        """
        if not self.latest_nav_date:
            print("没有最新净值日期，无法计算预估")
            return False

        # 将日期转换为datetime对象以便计算
        latest_date = datetime.combine(
            self.latest_nav_date,
            dt_time.min
        ).replace(tzinfo=ZoneInfo('Asia/Shanghai'))

        # 计算下次净值更新的日期和收益天数
        self.next_estimated_date = self.get_next_trading_date(latest_date)
        next_update_earndays = self.calculate_next_update_earndays(self.next_estimated_date)

        # 计算下次预估净值
        self.next_estimated_nav = self.latest_nav + (self.estimated_growth * next_update_earndays)

        print(f"下次预估日期: {self.next_estimated_date.strftime('%Y-%m-%d')}")
        print(f"下次预估净值: {self.next_estimated_nav:.4f}")
        print(f"预估收益天数: {next_update_earndays}天")

        return True

    def monitor_price(self):
        """
        监控基金价格
        """
        print(f"\n开始监控基金 {self.fund_name} ({self.fund_code})...")
        print(f"警告阈值: 折价 > {CONFIG['WARNING_DISCOUNT']*10000:.1f} 万分之一")
        print("-" * 50)

        try:
            last_alert_discount = 0
            while True:
                # 获取当前时间
                now = datetime.now(ZoneInfo('Asia/Shanghai'))
                if now.strftime('%H:%M:%S') > '15:00:00':
                    break

                # 检查是否在交易时间内
                if not self.is_trading_time(now):
                    # 非交易时间，等待到下一个交易时段开始
                    print(f"非交易时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

                    # 计算等待时间（到下一个交易时段开始）
                    wait_seconds = self.calculate_wait_seconds(now)
                    time.sleep(wait_seconds)
                    continue

                # 获取实时价格
                price_data = fetch_realtime_price(self.fund_code)
                current_price = price_data.get('price', 0.0)

                if current_price == 0.0:
                    print(f"{now.strftime('%H:%M:%S')} - 获取价格失败")
                    time.sleep(CONFIG['CHECK_INTERVAL'])
                    continue

                # 计算折价率
                if self.next_estimated_nav > 0:
                    discount = (self.next_estimated_nav - current_price) / self.next_estimated_nav

                    # 格式化输出
                    time_str = now.strftime('%H:%M:%S')
                    latest_nav_str = f"{self.latest_nav:.4f}"
                    nav_str = f"{self.next_estimated_nav:.4f}"
                    price_str = f"{current_price:.4f}"
                    discount_str = f"{discount*10000:.2f}"

                    # 判断是否告警
                    if discount >= CONFIG['WARNING_DISCOUNT'] and discount > last_alert_discount:
                        last_alert_discount = discount
                        # 红色警告（在支持ANSI颜色的终端显示）
                        print(f"\033[91m{time_str} - 警告! 价格: {price_str}, 预估净值: {nav_str}(<-{latest_nav_str}), ✔ 折价: {discount_str}‱\033[0m")
                        title, content = '银华折价', f'- 昨晚最新净值: {latest_nav_str} ({self.latest_nav_date})\n\n- 今晚预估净值: {nav_str} ({self.next_estimated_date})\n\n- 实时价格: {price_str} ({time_str})\n\n-场内折价: {discount_str}‱  '
                        try:
                            Feishu(cfg['FEISHU_WEBHOOK_TOKEN']).send_markdown(title, content)
                        finally:
                            cate, icon = '套利', '😀'
                            Pushme(cfg['PUSHME_PUSH_KEY']).send_markdown(f'[#{cate}!{icon}]'+title, content)
                    else:
                        # 普通信息
                        print(f"{time_str} - 价格: {price_str}, 预估净值: {nav_str}(<-{latest_nav_str}), 折价: {discount_str}‱")

                # 等待下次检查
                time.sleep(CONFIG['CHECK_INTERVAL'])

        except KeyboardInterrupt:
            print("\n监控已停止")
        except Exception as e:
            print(f"监控过程中发生错误: {e}")

    def calculate_wait_seconds(self, now: datetime) -> float:
        """
        计算到下一个交易时段开始的等待秒数
        """
        current_time = now.time()
        trading_hours = CONFIG['TRADING_HOURS']

        # 如果当前时间在上午交易时段结束到下午开始之间
        if trading_hours['morning_end'] < current_time < trading_hours['afternoon_start']:
            # 等待到下午开盘
            target_time = datetime.combine(now.date(), trading_hours['afternoon_start'])
            target_datetime = target_time.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            return max(0.0, (target_datetime - now).total_seconds())

        # 如果当前时间在下午交易时段结束之后
        elif current_time > trading_hours['afternoon_end']:
            # 等待到明天上午开盘
            tomorrow = now.date() + timedelta(days=1)
            target_time = datetime.combine(tomorrow, trading_hours['morning_start'])
            target_datetime = target_time.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            return max(0.0, (target_datetime - now).total_seconds())

        # 其他情况（如交易时段前），等待到上午开盘
        else:
            target_time = datetime.combine(now.date(), trading_hours['morning_start'])
            target_datetime = target_time.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            return max(0.0, (target_datetime - now).total_seconds())

    def run(self):
        """
        主运行函数
        """
        print("=" * 50)
        print("基金折价监控系统")
        print("=" * 50)

        # 0. 检查今天是否是交易日和交易时间
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        today = now.date()

        # 检查是否是交易日
        is_trading_day, reason = self.is_trading_day(now)

        if not is_trading_day:
            print(f"今天({today})不是交易日: {reason}")
            print("程序结束")
            return

        # 检查是否是交易时间
        if not self.is_trading_time(now):
            print(f"当前时间不在交易时间内: {now.strftime('%H:%M:%S')}")
            # 可以等待到交易时间，或者直接结束
            wait_seconds = self.calculate_wait_seconds(now)
            print(f"等待到交易时间开始... ({wait_seconds:.0f}秒)")
            time.sleep(wait_seconds)

        print(f"今天是交易日，当前时间在交易时间内")
        print("-" * 50)

        # 1. 获取最新净值和日期
        print("步骤1: 获取最新净值和日期")
        if not self.fetch_latest_nav():
            print("获取最新净值失败，程序结束")
            return

        print("-" * 50)

        # 2. 计算历史净值增长的中位数
        print("步骤2: 计算历史增长率中位数")
        # 已在fetch_latest_nav中完成

        print("-" * 50)

        # 3. 计算下次预估净值和日期
        print("步骤3: 计算下次预估净值和日期")
        if not self.calculate_next_estimation():
            print("计算预估失败，程序结束")
            return

        print("-" * 50)

        # 4. 开始监控
        print("步骤4: 开始监控价格")
        self.monitor_price()

if __name__ == "__main__":
    cfg = dotenv_values()
    print(f'\n\n\n\n\n=============== START: {now()} ===============')

    # 配置基金代码
    FUND_CODE = "511880"  # 示例基金代码，可替换为其他基金

    # 创建监控器并运行
    monitor = FundMonitor(FUND_CODE)
    monitor.run()

