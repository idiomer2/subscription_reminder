""" 下班前查看天气是否下雨
@crontab: 50 17 * * * cd ${BASE_PATH} && python -m life.rain_offwork 2>&1 | tee -a logs/rain_offwork.log
"""

import sys
import time
from datetime import datetime

import requests
from dotenv import dotenv_values
from pyutils.notify_util import Feishu, Pushme


def get_huangpu_weather():
    """
    获取广州黄埔区天气并判断降雨情况
    接口来源: Open-Meteo (无需API Key, 免费稳定)
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 正在获取天气数据...")

    # 广州市黄埔区的大致经纬度
    latitude = 23.114
    longitude = 113.461

    # 构建请求 URL
    # current=weather_code,rain: 获取当前天气代码和降雨量(mm)
    # timezone=Asia/Shanghai: 设定时区
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "weather_code,rain",
        "timezone": "Asia/Shanghai"
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json(); print(data)

        # 解析数据
        current = data.get("current", {})
        weather_code = current.get("weather_code")
        rain_mm = current.get("rain", 0.0) # 当前小时降雨量

        # 判断并输出结果
        return analyze_rain(weather_code, rain_mm)

    except requests.exceptions.RequestException as e:
        print(f"网络请求出错: {e}")
    except Exception as e:
        print(f"程序发生未知错误: {e}")

def analyze_rain(code, rain_mm):
    """
    根据 WMO Weather Code 解析降雨程度
    参考: https://open-meteo.com/en/docs
    """
    # WMO 代码映射表
    rain_codes = {
        0: "晴朗/多云", 1: "晴朗/多云", 2: "晴朗/多云", 3: "晴朗/多云",
        45: "有雾", 48: "有雾",

        51: "轻微毛毛雨", 53: "中度毛毛雨", 55: "密集毛毛雨",

        61: "小雨", 63: "中雨", 65: "大雨",

        80: "轻微阵雨", 81: "中度阵雨", 82: "暴雨/剧烈阵雨",

        95: "雷雨", 96: "雷雨伴有冰雹", 99: "大雷雨伴有冰雹"
    }

    status = rain_codes.get(code, "未知天气")

    # 逻辑判断
    is_raining = False

    # 如果代码属于降雨序列 (50-99之间通常是降水) 或 降雨量 > 0
    if (50 <= code <= 99) or (rain_mm > 0):
        is_raining = True

    results = []
    print("-" * 30)
    results.append(f"📍 地点: 广州市黄埔区\n")
    if is_raining:
        results.append(f"- 🌧️ 状态: 【正在下雨】")
        results.append(f"- 💧 程度: {status}")
        results.append(f"- 📊 降雨量: {rain_mm} mm")
    else:
        results.append(f"☁️ 状态: 没有下雨")
        results.append(f"🌤️ 天气: {status}")
    print('\n'.join(results))
    print("-" * 30)
    return is_raining, '\n'.join(results)


if __name__ == '__main__':
    cfg = dotenv_values()

    result = get_huangpu_weather()
    if result is None:  # 接口调用失败
        title, content = '下雨提醒', '天气接口调用失败'
    else:
        title, content, is_raining = '下雨提醒', result[-1], result[0]
        if not is_raining:
            sys.exit(0)

    try:
        Feishu(cfg['FEISHU_WEBHOOK_TOKEN']).send_markdown(title, content)
    finally:
        cate, icon = '', '😀'
        Pushme(cfg['PUSHME_PUSH_KEY']).send_markdown(f'[#{cate}!{icon}]'+title, content)

