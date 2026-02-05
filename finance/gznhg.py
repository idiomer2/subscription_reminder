#! /usr/bin/env python
# systemctl restart gznhg.service && journalctl -u gznhg.service -f -a
import requests
import time
import datetime
import json

from dotenv import dotenv_values
from pyutils.notify_util import Feishu, Pushme, Bark
from pyutils.date_util import now, now_time


# ================= 配置区域 =================
# 1. 飞书 Webhook 地址 (请替换为你自己的)
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/714dbf4e-4233-4075-b811-030c5f3f3f8b"

# 2. 触发提醒的最低阈值 (例如 2.0 代表年化 2%)
BASE_THRESHOLD = 1.8

# 3. 监控的品种代码 (腾讯接口格式)
# 沪市: sh204001(GC001), sh204002(GC002)...
# 深市: sz131810(R-001), sz131811(R-002)...
CODES = [
    "sh204001", "sh204002", "sh204003", "sh204004", "sh204007", # 沪市 GC
    "sz131810", "sz131811", "sz131800", "sz131809", "sz131801", # 深市 R
]
# ===========================================

class RepoMonitor:
    def __init__(self):
        self.last_alert_rate = 0.0  # 记录当天已提醒过的最高利率
        self.current_date = now_time().date()

    def send_feishu_msg(self, title, content):
        """发送飞书通知"""
        headers = {"Content-Type": "application/json"}
        data = {
            "msg_type": "text",
            "content": {
                "text": f"{title}\n\n{content}"
            }
        }
        try:
            # 设置超时时间，防止卡死
            r = requests.post(FEISHU_WEBHOOK, headers=headers, data=json.dumps(data), timeout=5)
            if r.status_code == 200:
                print(f"[系统] 飞书通知发送成功: {title}")
            else:
                print(f"[错误] 飞书发送失败: {r.text}")
        except Exception as e:
            print(f"[错误] 网络请求异常: {e}")

    def get_realtime_rates(self):
        """获取实时行情 (使用腾讯 qt.gtimg.cn 接口)"""
        url = f"http://qt.gtimg.cn/q={','.join(CODES)}"
        
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                return {}
            
            # 腾讯接口通常是 GBK 编码，需强制解码
            text_content = resp.content.decode('gbk')
            
            # 解析数据
            data = {}
            lines = text_content.strip().split(";")
            
            for line in lines:
                line = line.strip()
                if not line: continue
                
                # 格式: v_sh204001="1~GC001~204001~2.050~..."
                if "=" not in line: continue
                
                parts = line.split('=')
                # 提取代码: v_sh204001 -> sh204001
                code_key = parts[0].split('_')[-1] 
                
                # 提取内容: "1~GC001~..." -> 去掉引号
                content_str = parts[1].replace('"', '')
                values = content_str.split('~')
                
                # 腾讯数据结构:
                # [1]=名字(GC001), [2]=代码, [3]=当前价格(即利率), [4]=昨收, [5]=开盘
                if len(values) > 10:
                    name = values[1]
                    try:
                        rate = float(values[3]) # 当前成交价即为年化利率
                        
                        # 过滤掉为0的无效数据（停牌或集合竞价前可能为0）
                        if rate > 0:
                            data[code_key] = {"name": name, "rate": rate}
                    except ValueError:
                        continue
            return data
        except Exception as e:
            print(f"[警告] 获取行情失败: {e}")
            return {}

    def is_trading_time(self):
        """判断是否在交易时间 (周一到周五 9:30-15:30)"""
        now = now_time()
        
        # 周六(5) 周日(6) 排除
        if now.weekday() > 4:
            return False

        current_time = now.time()
        start_time = datetime.time(9, 30)
        end_time = datetime.time(15, 30) 
        
        return start_time <= current_time <= end_time

    def run(self):
        print(f"Start Monitoring (Tencent Source)... 基础阈值: {BASE_THRESHOLD}%")
        
        while "09:30" <= now_time().strftime('%H:%M') < "15:30":
            # 1. 跨天重置逻辑
            if now_time().date() != self.current_date:
                self.current_date = now_time().date()
                self.last_alert_rate = 0.0
                print(f"[系统] 日期变更，重置报警水位")

            # 2. 判断交易时间
            if not self.is_trading_time():
                print(f"\r[休息] 非交易时间 - {datetime.datetime.now().strftime('%H:%M:%S')}", end="")
                time.sleep(60) 
                continue

            # 3. 获取数据
            rates_map = self.get_realtime_rates()
            
            # 4. 寻找最高利率
            max_rate = 0.0
            max_code = ""
            max_name = ""
            
            for code, info in rates_map.items():
                if info['rate'] > max_rate:
                    max_rate = info['rate']
                    max_code = code
                    max_name = info['name']

            current_time_str = now_time().strftime("%H:%M:%S")
            

            # 5. 触发报警逻辑
            # A: 超过基础阈值
            # B: 超过当天已报警过的最高值 (只有更高才报)
            if max_rate >= BASE_THRESHOLD and max_rate > self.last_alert_rate:
                # 打印当前状态 (\r + end=""覆盖同一行，保持控制台清爽)
                status_msg = f"[监控] {current_time_str} 最高: {max_name} {max_rate}% (阈值:{BASE_THRESHOLD}%, 水位:{self.last_alert_rate}%)"
                print(status_msg)
                print() # 换行，避免覆盖掉监控日志
                
                rise_val = round(max_rate - self.last_alert_rate, 2)
                rise_txt = f"+{rise_val}%" if self.last_alert_rate > 0 else "首次触发"
                
                msg = (f"🚀 国债逆回购收益飙升!\n"
                       f"品种: {max_name} ({max_code})\n"
                       f"当前利率: {max_rate}%\n"
                       f"趋势: 较上次 {rise_txt}\n"
                       f"时间: {current_time_str}")
                title = '💰 逆回购捡漏提醒'
                #self.send_feishu_msg(title, msg)
                try:
                    Feishu(ENV['FEISHU_WEBHOOK_TOKEN']).send_markdown(title, msg)
                finally:
                    cate, icon = '', '💰'
                    Pushme(ENV['PUSHME_PUSH_KEY']).send_markdown(f'[#{cate}!{icon}]'+title, msg)
                    Bark(ENV['BARK_TOKEN']).send(msg, title)

                # 更新水位线
                self.last_alert_rate = max_rate
            
            # 6. 休眠频率 (秒)
            time.sleep(60)

if __name__ == "__main__":
    ENVS = dotenv_values()
    print(f'\n\n\n=============== {now()} ===============')

    monitor = RepoMonitor()
    monitor.run()

