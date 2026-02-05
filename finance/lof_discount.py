"""
@crontab: 30 12 * * 1-5 cd $reminder_home && $PYTHON -u -m finance.lof_discount 2>&1 | tee -a logs/lof_discount.log
"""
import sys
import requests

from dotenv import dotenv_values
from pyutils.notify_util import Feishu, Pushme
from pyutils.date_util import now


def main():
    headers = {
    'accept': 'application/json, text/javascript, */*; q=0.01',
    'accept-language': 'zh-CN,zh;q=0.9',
    'priority': 'u=1, i',
    'referer': 'https://www.jisilu.cn/data/lof/',
    'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'x-requested-with': 'XMLHttpRequest',
    }

    response = requests.get(
        'https://www.jisilu.cn/data/lof/index_lof_list/',  # ?___jsl=LST___t=1770261137994&only_owned=&rp=25
        headers=headers
    )
    lof_data = response.json()

    result = []
    for x in lof_data['rows']:
        lof_cell = x['cell']
        if lof_cell['discount_rt'] not in ('', '-') and float(lof_cell['discount_rt']) >= 5:
            apply_status = lof_cell.get('apply_status', '未知')
            if apply_status != '暂停申购':
                result.append(f'{lof_cell["fund_id"]} {lof_cell["fund_nm"]} 实时溢价={lof_cell["discount_rt"]}% 申购状态={apply_status}')
    return result


if __name__ == '__main__':
    ENV = dotenv_values()
    print(f'\n\n\n=============== {now()} ===============')


    result = main()
    if len(result) == 0:
        print('没有明显折价且可以申购的LOF基金')
        sys.exit(0)

    title, content = 'LOF折价', '\n\n'.join(['- ' + line for line in result])
    try:
        Feishu(ENV['FEISHU_WEBHOOK_TOKEN']).send_markdown(title, content)
    finally:
        cate, icon = '折价套利', '💰'
        Pushme(ENV['PUSHME_PUSH_KEY']).send_markdown(f'[#{cate}!{icon}]'+title, content)

