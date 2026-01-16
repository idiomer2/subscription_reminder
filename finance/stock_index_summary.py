""" 指数播报
@crontab: 45 14 * * 1-5 cd ${BASE_PATH} && python -m finance.stock_index_summary.py 2>&1 | tee -a logs/stock_index_summary.log
"""

import time
import sys
import json
import base64
from dotenv import dotenv_values

import requests
import easyquotation

from pyutils.notify_util import Feishu, Pushme


def add_color(txt):
    if '-' in txt:
        return "<font color='green'> %s </font>" % txt
    else: 
        return "<font color='red'> %s </font>" % txt

def get_holidays():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'}
    try:
        resp = requests.get('https://timor.tech/api/holiday/year', headers=headers)
        holiday_json = resp.json()
        if holiday_json.get('code', -1)==0 and 'holiday' in holiday_json:
            holiday_dates = [month_day for month_day,info in holiday_json['holiday'].items() if info['holiday']]
            print('holiday_dates = %s' % holiday_dates)
            return holiday_dates
    except Exception as e:
        print(e)
        return []

def today_is_holiday():
    today, holidays = time.strftime('%m-%d'), get_holidays()
    if today in holidays:
        print(f'今天{today}在工作日假期内{holidays}')
        return True
    return False

def new_my_decode(data):
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    key = b'bieyanjiulexixishuibatoufameill1'[:32]  # 密钥需要是32字节
    iv = b'nengnongchulainbl1'[:16]  # 向量通常是16字节
    encrypted_data = base64.b64decode(data)     # 解码 Base64 数据
    cipher = AES.new(key, AES.MODE_CBC, iv)     # 创建 AES 解密器
    try:
        decrypted = unpad(cipher.decrypt(encrypted_data), AES.block_size)     # 解密数据并去掉填充
    except:
        decrypted = cipher.decrypt(encrypted_data)
        decrypted = decrypted[decrypted.find(b'{'):decrypted.rfind(b'}')]
    return decrypted.decode('utf-8')

def get_kjtl_data():
    url = "https://api.jiucaishuo.com/v2/kjtl/kjtlconnect"
    payload = {
        "gu_code": '000001.SH',  # 000300.SH
        "type": "h5",
        "version": "2.4.5",
        "act_time": 1697623588394,
    }
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'}
    r = requests.post(url, headers=headers, json=payload)
    data_json = r.json()
    data_json = json.loads(new_my_decode(data_json))
    return data_json

if __name__ == '__main__' and not today_is_holiday():
    args = dotenv_values()

    quotation = easyquotation.use('qq')
    data = quotation.stocks(['sh000300', 'sh000905', 'sh000922', 'sh000919', 'sz399986', 'sz399975', 'sh512480', 'sh515790'], prefix=True)
    print(data) # main_columns = ['code', 'name', 'now', 'close', '涨跌(%)', 'open', 'high', 'low', 'datetime']

    msg = ''
    for info in data.values():
        code = str(info['code']) if str(info['code'])[:2] not in ('sh', 'sz') else str(info['code'])[2:]
        name = str(info['name'])
        chgPct = str(info['涨跌(%)'])
        more_link = f'[详情](https://quote.eastmoney.com/zs{code}.html)'
        msg += '%s  %s  %s\n' % (name, add_color(chgPct+'%'), more_link)
    
    try:
        data_json = get_kjtl_data()
        x_dates = data_json.get('data', data_json)['xAxis']['categories']
        y_kjtl = data_json.get('data', data_json)['series'][0]['data']
        msg += '\n昨日恐惧贪婪指数：%.2f' % y_kjtl[-1]
    except Exception as e:
        print(e)


    card_msg = {
        "title": "收盘前播报(%s)" % time.strftime('%Y-%m-%d %H:%M'), 
        "markdown_content": msg,
        "actions": [   # (可选)
            {
                "tag": "button",
                "text": {"content": "更多指数", "tag": "plain_text"},
                "type": "primary",
                "url": "https://quote.eastmoney.com/center/hszs.html"
            },
            {
                "tag": "button",
                "text": {"content": "市场估值", "tag": "plain_text"},
                "type": "default",
                "url": "https://legulegu.com/stockdata/hs300-pb"
            }
        ]
    }

    try:
        Feishu(args['FEISHU_WEBHOOK_TOKEN']).send_markdown_interactive(**card_msg)
    finally:
        Pushme(args['PUSHME_PUSH_KEY']).send_markdown('[#指数播报!指]'+card_msg['title'], card_msg['markdown_content'].replace('\n', '\n\n'))

