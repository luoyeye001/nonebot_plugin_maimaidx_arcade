import re
import time
from typing import Tuple

from nonebot import get_driver, on_fullmatch, on_message, on_regex, on_startswith
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER
from nonebot.params import RegexGroup
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from .data import (
    arcade,
    batch_subscribe_region,
    download_arcade_info,
    fuzzy_match_arcade,
    get_group_region,
    image_to_base64,
    log_removed_arcades,
    set_group_region,
    subscribe,
    text_to_image,
    update_alias,
    update_person,
    updata_arcade,
)

__plugin_meta__ = PluginMetadata(
    name='maimaiDX排卡',
    description='maimai DX 机厅排卡管理插件',
    usage='发送「帮助maimaiDX排卡」查看指令列表',
)

_driver = get_driver()

_HELP_TEXT = """排卡指令如下：
添加机厅 <店名> <地址> <机台数量> 添加机厅信息
删除机厅 <店名> 删除机厅信息
修改机厅 <店名> 数量 <数量> ... 修改机厅信息
添加机厅别名 <店名> <别名>
订阅机厅 <店名> 订阅机厅，简化后续指令
订阅地区 <地区> 按地区批量订阅（如：浙江省宁波市）
取消订阅地区 <地区> 按地区批量取消订阅
查看订阅 查看群组订阅机厅的信息
取消订阅机厅 <店名> 取消群组机厅订阅
查找机厅,查询机厅,机厅查找,机厅查询 <关键词> 查询对应机厅信息
<店名/别名>人数设置,设定,=,增加,加,+,减少,减,-<人数> 操作排卡人数
<店名/别名>有多少人,有几人,有几卡,几人,几卡 查看排卡人数
机厅几人 查看已订阅机厅排卡人数
设置地区 <地区> 设置群所在地区（如：浙江省杭州市）"""


# =================== 启动加载 ===================

@_driver.on_startup
async def _():
    from nonebot.log import logger
    logger.info('正在获取maimai所有机厅信息')
    await arcade.getArcade()
    logger.info('maimai机厅数据获取完成')


# =================== 帮助 ===================

arcade_help = on_fullmatch(('帮助maimaiDX排卡', '帮助maimaidx排卡'), priority=5, block=True)


@arcade_help.handle()
async def dx_arcade_help(bot: Bot, event: GroupMessageEvent):
    await arcade_help.send(
        MessageSegment.image(image_to_base64(text_to_image(_HELP_TEXT))),
        at_sender=True,
    )


# =================== 添加机厅 ===================
# 使用较低优先级数字（4），避免被「添加机厅别名」误触发时覆盖
# 注：「添加机厅别名」matcher 的 priority=3，block=True，会先行拦截

add_arcade_matcher = on_startswith(('添加机厅', '新增机厅'), priority=4, block=True)


@add_arcade_matcher.handle()
async def add_arcade(bot: Bot, event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    for prefix in ('添加机厅', '新增机厅'):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    args = text.split()

    is_su = await SUPERUSER(bot, event)
    if not is_su:
        msg = '仅允许主人添加机厅\n请使用 来杯咖啡+内容 联系主人'
    elif len(args) == 1 and args[0] in ['帮助', 'help', '指令帮助']:
        msg = '添加机厅指令格式：添加机厅 <店名> <位置> <机台数量> <别称1> <别称2> ...'
    elif len(args) >= 3:
        if not args[2].isdigit():
            msg = '格式错误：添加机厅 <店名> <地址> <机台数量> [别称1] [别称2] ...'
        else:
            if not arcade.total.search_fullname(args[0]):
                aid = sorted(arcade.idList, reverse=True)
                if (sid := aid[0]) >= 10000:
                    sid += 1
                else:
                    sid = 10000
                arcade_dict = {
                    'name': args[0],
                    'location': args[1],
                    'province': '',
                    'mall': '',
                    'num': int(args[2]),
                    'id': str(sid),
                    'alias': args[3:] if len(args) > 3 else [],
                    'group': [],
                    'person': 0,
                    'by': '',
                    'time': '',
                }
                arcade.total.add_arcade(arcade_dict)
                await arcade.total.save_arcade()
                msg = f'机厅：{args[0]} 添加成功'
            else:
                msg = f'机厅：{args[0]} 已存在，无法添加机厅'
    else:
        msg = '格式错误：添加机厅 <店名> <地址> <机台数量> [别称1] [别称2] ...'

    await add_arcade_matcher.finish(msg, at_sender=True)


# =================== 删除机厅 ===================

del_arcade_matcher = on_startswith(('删除机厅', '移除机厅'), priority=5, block=True)


@del_arcade_matcher.handle()
async def delete_arcade(bot: Bot, event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    for prefix in ('删除机厅', '移除机厅'):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    name = text

    is_su = await SUPERUSER(bot, event)
    if not is_su:
        msg = '仅允许主人删除机厅\n请使用 来杯咖啡+内容 联系主人'
    elif not name:
        msg = '格式错误：删除机厅 <店名>，店名需全名'
    elif not arcade.total.search_fullname(name):
        msg = f'未找到机厅：{name}'
    else:
        arcade.total.del_arcade(name)
        await arcade.total.save_arcade()
        msg = f'机厅：{name} 删除成功'

    await del_arcade_matcher.finish(msg, at_sender=True)


# =================== 机厅别名（priority 更高，避免与「添加机厅」冲突）===================

alias_matcher = on_startswith(('添加机厅别名', '删除机厅别名'), priority=3, block=True)


@alias_matcher.handle()
async def update_arcade_alias(bot: Bot, event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    if text.startswith('添加机厅别名'):
        prefix = '添加机厅别名'
        add = True
    else:
        prefix = '删除机厅别名'
        add = False
    args = text[len(prefix):].strip().split()

    if len(args) != 2:
        msg = '格式错误：添加/删除机厅别名 <店名> <别名>'
    elif not args[0].isdigit() and len(_arc := arcade.total.search_fullname(args[0])) > 1:
        msg = '找到多个相同店名的机厅，请使用店铺ID更改机厅别名\n' + '\n'.join(
            [f'{_.id}：{_.name}' for _ in _arc]
        )
    else:
        msg = await update_alias(args[0], args[1], add)

    await alias_matcher.finish(msg, at_sender=True)


# =================== 修改机厅 ===================

modify_matcher = on_startswith(('修改机厅', '编辑机厅'), priority=5, block=True)


@modify_matcher.handle()
async def modify_arcade(bot: Bot, event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    for prefix in ('修改机厅', '编辑机厅'):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    args = text.split()

    is_admin = await (GROUP_ADMIN | GROUP_OWNER | SUPERUSER)(bot, event)
    if not is_admin:
        msg = '仅允许管理员修改机厅信息'
    elif len(args) < 3:
        msg = '格式错误：修改机厅 <店名> [数量] <数量>'
    elif not args[0].isdigit() and len(_arc := arcade.total.search_fullname(args[0])) > 1:
        msg = '找到多个相同店名的机厅，请使用店铺ID修改机厅\n' + '\n'.join(
            [f'{_.id}：{_.name}' for _ in _arc]
        )
    elif args[1] == '数量' and len(args) == 3 and args[2].isdigit():
        msg = await updata_arcade(args[0], args[2])
    else:
        msg = '格式错误：修改机厅 <店名> [数量] <数量>'

    await modify_matcher.finish(msg, at_sender=True)


# =================== 订阅/取消订阅机厅 ===================

subscribe_matcher = on_regex(r'^(订阅机厅|取消订阅机厅|取消订阅)\s(.+)', priority=5, block=True)


@subscribe_matcher.handle()
async def subscribe_arcade(
    bot: Bot,
    event: GroupMessageEvent,
    matched: Tuple[str, ...] = RegexGroup(),
):
    gid = event.group_id
    sub = matched[0] == '订阅机厅'
    name = matched[1]

    is_admin = await (GROUP_ADMIN | GROUP_OWNER | SUPERUSER)(bot, event)
    if not is_admin:
        msg = '仅允许管理员订阅和取消订阅'
    elif not name.isdigit() and len(_arc := arcade.total.search_fullname(name)) > 1:
        msg = '找到多个相同店名的机厅，请使用店铺ID订阅\n' + '\n'.join(
            [f'{_.id}：{_.name}' for _ in _arc]
        )
    else:
        msg = await subscribe(gid, name, sub)

    await subscribe_matcher.finish(msg, at_sender=True)


# =================== 按地区批量订阅/取消订阅 ===================

region_sub_matcher = on_startswith(('订阅地区', '取消订阅地区'), priority=5, block=True)


@region_sub_matcher.handle()
async def region_subscribe(bot: Bot, event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    if text.startswith('取消订阅地区'):
        sub = False
        region = text[len('取消订阅地区'):].strip()
    else:
        sub = True
        region = text[len('订阅地区'):].strip()

    is_admin = await (GROUP_ADMIN | GROUP_OWNER | SUPERUSER)(bot, event)
    if not is_admin:
        await region_sub_matcher.finish('仅允许管理员订阅和取消订阅', at_sender=True)

    if not region:
        await region_sub_matcher.finish(
            '格式：订阅地区 xx省xx市（如：浙江省宁波市）', at_sender=True
        )

    gid = event.group_id
    msg = await batch_subscribe_region(gid, region, sub)
    await region_sub_matcher.finish(msg, at_sender=True)


# =================== 查看订阅 ===================

check_sub_matcher = on_fullmatch(('查看订阅', '查看订阅机厅'), priority=5, block=True)


@check_sub_matcher.handle()
async def check_subscribe(bot: Bot, event: GroupMessageEvent):
    gid = int(event.group_id)
    arcade_list = arcade.total.group_subscribe_arcade(group_id=gid)
    if arcade_list:
        result = [f'群{gid}订阅机厅信息如下：']
        for a in arcade_list:
            alias = "\n  ".join(a.alias)
            result.append(
                f'店名：{a.name}\n'
                f'    - 地址：{a.location}\n'
                f'    - 数量：{a.num}\n'
                f'    - 别名：{alias}'
            )
        msg = '\n'.join(result)
    else:
        msg = '该群未订阅任何机厅'

    await check_sub_matcher.finish(msg, at_sender=True)


# =================== 设置地区 ===================

region_matcher = on_startswith('设置地区', priority=5, block=True)


@region_matcher.handle()
async def set_region(bot: Bot, event: GroupMessageEvent):
    is_admin = await (GROUP_ADMIN | GROUP_OWNER | SUPERUSER)(bot, event)
    if not is_admin:
        await region_matcher.finish('仅允许管理员设置地区', at_sender=True)

    text = event.get_plaintext().strip()
    region = text[len('设置地区'):].strip()
    if not region:
        current = get_group_region(event.group_id)
        if current:
            await region_matcher.finish(f'当前群地区：{current}', at_sender=True)
        else:
            await region_matcher.finish('格式：设置地区 xx省xx市（直辖市为 xx市）', at_sender=True)

    await set_group_region(event.group_id, region)
    await region_matcher.finish(f'已设置群地区为：{region}', at_sender=True)


# =================== 查找机厅 ===================

search_matcher = on_startswith(
    ('查找机厅', '查询机厅', '机厅查找', '机厅查询', '搜素机厅', '机厅搜素'),
    priority=5,
    block=True,
)


@search_matcher.handle()
async def search_arcade(bot: Bot, event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    for prefix in ('查找机厅', '查询机厅', '机厅查找', '机厅查询', '搜素机厅', '机厅搜素'):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    name = text

    if not name:
        await search_matcher.finish('格式错误：查找机厅 <关键词>', at_sender=True)
    elif arcade_list := arcade.total.search_name(name):
        result = ['为您找到以下机厅：\n']
        for a in arcade_list:
            result.append(
                f'店名：{a.name}\n'
                f'    - 地址：{a.location}\n'
                f'    - ID：{a.id}\n'
                f'    - 数量：{a.num}'
            )
        if len(arcade_list) < 5:
            await search_matcher.send('\n==========\n'.join(result), at_sender=True)
        else:
            await search_matcher.send(
                MessageSegment.image(image_to_base64(text_to_image('\n'.join(result)))),
                at_sender=True,
            )
    else:
        await search_matcher.send('没有这样的机厅哦', at_sender=True)


# =================== 排卡人数操作 ===================

person_matcher = on_regex(
    r'^(.+)?\s?(设置|设定|＝|=|增加|添加|加|＋|\+|减少|降低|减|－|-)\s?([0-9]+|＋|\+|－|-)(人|卡)?$',
    priority=5,
    block=True,
)


@person_matcher.handle()
async def arcade_person(
    bot: Bot,
    event: GroupMessageEvent,
    matched: Tuple[str, ...] = RegexGroup(),
):
    gid = event.group_id
    nickname = event.sender.nickname
    name_raw, value, num_str, _ = matched

    if not num_str.isdigit():
        if num_str in ['＋', '+']:
            person = 1
        elif num_str in ['－', '-']:
            person = 1
            value = '-' if value in ['+', '＋', '增加', '添加', '加'] else value
        else:
            await person_matcher.finish('请输入正确的数字', at_sender=True)
    else:
        person = int(num_str)

    arcade_list = arcade.total.group_subscribe_arcade(group_id=gid)
    if not arcade_list:
        await person_matcher.finish('该群未订阅机厅，无法更改机厅人数', at_sender=True)

    if name_raw:
        arcadeName = name_raw
        if '人数' in arcadeName:
            arcadeName = arcadeName[:-2]
        elif '卡' in arcadeName:
            arcadeName = arcadeName[:-1]

        _arcade = []
        for _a in arcade_list:
            if arcadeName == _a.name:
                _arcade.append(_a)
                break
            if arcadeName in _a.alias:
                _arcade.append(_a)
                break

        if not _arcade:
            await person_matcher.finish('已订阅的机厅中未找到该机厅', at_sender=True)
        else:
            msg = await update_person(_arcade, nickname, value, person)
            await person_matcher.send(msg, at_sender=True)


# =================== 排卡人数操作（省略运算符，如「md1」等同于「md=1」）===================

_DIRECT_NUM_RE = re.compile(r'^(.+?)(＋|\+|－|-)?(\d+)(人|卡)?$')

person_direct_matcher = on_message(priority=5, block=False)


@person_direct_matcher.handle()
async def arcade_person_direct(bot: Bot, event: GroupMessageEvent):
    try:
        text = event.get_plaintext().strip()
        m = _DIRECT_NUM_RE.fullmatch(text)
        if not m:
            return

        name_raw, op, num_str, _ = m.group(1), m.group(2), m.group(3), m.group(4)

        gid = event.group_id
        nickname = event.sender.nickname

        arcade_list = arcade.total.group_subscribe_arcade(group_id=gid)
        if not arcade_list:
            return

        person = int(num_str)
        arcadeName = name_raw.strip()
        if '人数' in arcadeName:
            arcadeName = arcadeName[:-2]
        elif '卡' in arcadeName:
            arcadeName = arcadeName[:-1]

        _arcade = []
        for _a in arcade_list:
            if arcadeName == _a.name:
                _arcade.append(_a)
                break
            if arcadeName in _a.alias:
                _arcade.append(_a)
                break

        if not _arcade:
            return

        if op in ('+', '＋'):
            value = '+'
        elif op in ('-', '－'):
            value = '-'
        else:
            value = '='
        msg = await update_person(_arcade, nickname, value, person)
        await person_direct_matcher.send(msg, at_sender=True)
    except Exception:
        pass


# =================== 查询已订阅机厅总人数 ===================

multiple_matcher = on_fullmatch(('机厅几人', 'jtj'), priority=4, block=True)


@multiple_matcher.handle()
async def arcade_query_multiple(bot: Bot, event: GroupMessageEvent):
    gid = event.group_id
    arcade_list = arcade.total.group_subscribe_arcade(gid)
    if not arcade_list:
        await multiple_matcher.finish('该群未订阅任何机厅', at_sender=True)
    active_list = [a for a in arcade_list if a.by != '自动清零']
    if not active_list:
        await multiple_matcher.finish('目前没有已记录的排卡人数', at_sender=True)
    result = arcade.total.arcade_to_msg(active_list)
    await multiple_matcher.send('\n'.join(result))


# =================== 查询指定机厅人数（后缀触发）===================

query_person_matcher = on_regex(
    r'^(.*?)(有多少人|有几人|有几卡|多少人|多少卡|几人|jr|j|几卡)$',
    flags=re.IGNORECASE,
    priority=5,
    block=True,
)


@query_person_matcher.handle()
async def arcade_query_person(
    bot: Bot,
    event: GroupMessageEvent,
    matched: Tuple[str, ...] = RegexGroup(),
):
    gid = event.group_id
    name = matched[0].strip().lower()

    if name:
        arcade_list = arcade.total.search_name(name)
        if not arcade_list:
            # 尝试 AI 模糊匹配
            matched = await fuzzy_match_arcade(name, gid)
            if matched:
                arcade_list = [matched]
                result = arcade.total.arcade_to_msg(arcade_list)
                msg = '\n'.join(result)
                if matched.alias:
                    msg += f'\n提示：该机厅已有别名 {", ".join(matched.alias)}，可直接使用别名查询'
                await query_person_matcher.send(msg)
            else:
                await query_person_matcher.finish('没有这样的机厅哦', at_sender=True)
        else:
            result = arcade.total.arcade_to_msg(arcade_list)
            await query_person_matcher.send('\n'.join(result))
    else:
        arcade_list = arcade.total.group_subscribe_arcade(gid)
        if arcade_list:
            active_list = [a for a in arcade_list if a.by != '自动清零']
            if not active_list:
                await query_person_matcher.finish('目前没有已记录的排卡人数', at_sender=True)
            result = arcade.total.arcade_to_msg(active_list)
            await query_person_matcher.send('\n'.join(result))
        else:
            await query_person_matcher.send(
                '该群未订阅任何机厅，请使用 订阅机厅 <名称> 指令订阅机厅',
                at_sender=True,
            )


# =================== 定时任务（需安装 nonebot-plugin-apscheduler）===================

try:
    from nonebot_plugin_apscheduler import scheduler

    @scheduler.scheduled_job('cron', hour=3)
    async def _scheduled_arcade_reset():
        from nonebot import get_bots
        from nonebot.log import logger
        try:
            # 快照当前官方机厅（排除手动添加的 id >= 10000）
            old_arcades = {}
            if arcade.total:
                old_arcades = {arc.id: arc for arc in arcade.total if int(arc.id) < 10000}

            new_total = await download_arcade_info()

            # 检测被远端移除的机厅
            new_ids = {arc.id for arc in new_total if int(arc.id) < 10000}
            removed = [old_arcades[aid] for aid in old_arcades if aid not in new_ids]

            if removed:
                await log_removed_arcades(removed)
                bots = get_bots()
                if bots:
                    bot = list(bots.values())[0]
                    msg = '以下机厅已从官方列表中移除：\n' + '\n'.join(
                        f'  {r.name}（ID: {r.id}, 地址: {r.location}）' for r in removed
                    )
                    await bot.send_private_msg(user_id=953743075, message=msg)

            # 用新数据更新 arcade.total
            arcade.total = new_total
            arcade.idList = [int(c_a.id) for c_a in arcade.total]

            # 重置人数
            for arc in arcade.total:
                arc.person = 0
                arc.by = '自动清零'
                arc.time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            await arcade.total.save_arcade()
        except Exception:
            return
        logger.info('maimaiDX排卡数据更新完毕')

except ImportError:
    pass
