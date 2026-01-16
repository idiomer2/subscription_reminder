""" TODO: 功能
@crontab: 30 09 * * * cd ${BASE_PATH} && python -m folder.xxx 2>&1 | tee -a logs/xxx.log
"""

from dotenv import dotenv_values
from pyutils.notify_util import Feishu, Pushme
from pyutils.date_util import now



if __name__ == '__main__':
    cfg = dotenv_values()
    print(f'\n\n\n=============== {now()} ===============')

    # TODO
    title, content = 'title', 'test...'

    try:
        Feishu(cfg['FEISHU_WEBHOOK_TOKEN']).send_markdown(title, content)
    finally:
        cate, icon = '', '😀'
        Pushme(cfg['PUSHME_PUSH_KEY']).send_markdown(f'[#{cate}!{icon}]'+title, content)

