# coding: utf-8
''' 可转债打新提醒
@crontab: 30 09 * * * cd ${BASE_PATH} && python convertible_bonds_ipo.py 2>&1 | tee -a logs/convertible_bonds_ipo.log
'''

import json
import sys
import time
from dotenv import dotenv_values

import requests
from pyutils.notify_util import Feishu, Pushme


if __name__ == '__main__':
    args = dotenv_values()

    resp = requests.get('https://datacenter-web.eastmoney.com/api/data/v1/get?sortColumns=PUBLIC_START_DATE&sortTypes=-1&pageSize=50&pageNumber=1&reportName=RPT_BOND_CB_LIST&columns=ALL&quoteColumns=f2~01~CONVERT_STOCK_CODE~CONVERT_STOCK_PRICE,f235~10~SECURITY_CODE~TRANSFER_PRICE,f236~10~SECURITY_CODE~TRANSFER_VALUE,f2~10~SECURITY_CODE~CURRENT_BOND_PRICE,f237~10~SECURITY_CODE~TRANSFER_PREMIUM_RATIO,f239~10~SECURITY_CODE~RESALE_TRIG_PRICE,f240~10~SECURITY_CODE~REDEEM_TRIG_PRICE,f23~01~CONVERT_STOCK_CODE~PBV_RATIO&source=WEB&client=WEB')
    data = json.loads(resp.text)# ; print("data =", data)

    msg = ''
    for row in data['result']['data']:
        if row['VALUE_DATE'].split()[0] == time.strftime("%Y-%m-%d"):
            msg += "- " + " ".join((row['SECURITY_NAME_ABBR'], row['SECUCODE'], row['VALUE_DATE'].split()[0]))
            msg += "\n"

    if msg:
        card_msg = {'title': f"可转债打新({time.strftime('%Y-%m-%d')})", 'msg': msg}
        print(f'\n\n\n有可转债打新：{card_msg}\n\n\n')

        try:
            feishu = Feishu(args['FEISHU_WEBHOOK_TOKEN'])
            feishu.send_markdown(card_msg['title'], card_msg['msg'])
        finally:
            pushme = Pushme(args['PUSHME_PUSH_KEY'])
            pushme.send_markdown('[#打新!🎲📈]'+card_msg['title'], card_msg['msg'])

