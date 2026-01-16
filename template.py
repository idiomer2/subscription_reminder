""" TODO: 功能
"""

from dotenv import dotenv_values
from pyutils.notify_util import Feishu, Pushme



if __name__ == '__main__':
    cfg = dotenv_values()

    # TODO
    title, content = 'title', 'test...'

    try:
        Feishu(cfg['FEISHU_WEBHOOK_TOKEN']).send_markdown(title, content)
    finally:
        cate, icon = '', '😀'
        Pushme(cfg['PUSHME_PUSH_KEY']).send_markdown(f'[#{cate}!{icon}]'+title, content)

