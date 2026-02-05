""" TODO: 功能
@crontab: 30 09 * * 1-5 cd $reminder_home && python -m folder.xxx 2>&1 | tee -a logs/xxx.log
"""

from dotenv import dotenv_values
from pyutils.notify_util import Feishu, Pushme, Bark
from pyutils.date_util import now, now_time



if __name__ == '__main__':
    ENV = dotenv_values()
    print(f'\n\n\n=============== {now()} ===============')

    # TODO
    title, content = 'title', 'test...'

    try:
        Feishu(ENV['FEISHU_WEBHOOK_TOKEN']).send_markdown(title, content)
    finally:
        cate, icon = '', '😀'
        Pushme(ENV['PUSHME_PUSH_KEY']).send_markdown(f'[#{cate}!{icon}]'+title, content)
        Bark(ENV['BARK_TOKEN']).send(content, title)

