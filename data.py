import base64
import json
import time
import traceback
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
import aiohttp
from nonebot.log import logger
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

# =================== 路径 ===================

_DATA_DIR = Path(__file__).parent / 'data'
_DATA_DIR.mkdir(exist_ok=True)

arcades_json: Path = _DATA_DIR / 'arcades.json'
_config_json: Path = _DATA_DIR / 'config.json'

# 字体路径：将 ShangguMonoSC-Regular.otf 放在本插件目录下即可
_FONT_PATH = Path(__file__).parent / 'ShangguMonoSC-Regular.otf'

# 系统 CJK 字体候选列表（按优先级排列，覆盖 Windows / Linux / macOS）
_FALLBACK_FONTS = [
    # Windows
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/simhei.ttf',
    'C:/Windows/Fonts/simsun.ttc',
    # Linux
    '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    # macOS
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Light.ttc',
    '/Library/Fonts/Arial Unicode.ttf',
]


# =================== 文件读写 ===================

async def writefile(file: Path, data: Any) -> bool:
    async with aiofiles.open(file, 'w', encoding='utf-8') as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=4))
    return True


# =================== 配置管理 ===================

def load_config() -> dict:
    """读取配置文件"""
    if _config_json.exists():
        return json.load(open(_config_json, 'r', encoding='utf-8'))
    return {}


async def save_config(config: dict) -> None:
    """保存配置文件"""
    await writefile(_config_json, config)


def get_group_region(group_id: int) -> Optional[str]:
    """获取群地区"""
    config = load_config()
    return config.get('group_regions', {}).get(str(group_id))


async def set_group_region(group_id: int, region: str) -> None:
    """设置群地区"""
    config = load_config()
    if 'group_regions' not in config:
        config['group_regions'] = {}
    config['group_regions'][str(group_id)] = region
    await save_config(config)


# =================== 图片工具 ===================

def _get_font(size: int) -> ImageFont.FreeTypeFont:
    if _FONT_PATH.exists():
        return ImageFont.truetype(str(_FONT_PATH), size)
    for path in _FALLBACK_FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise RuntimeError(
        '未找到支持中文的字体，请将 ShangguMonoSC-Regular.otf 放置到插件目录下'
    )


def text_to_image(text: str) -> Image.Image:
    size = 24
    font = _get_font(size)
    padding = 10
    margin = 4
    lines = text.strip().split('\n')
    max_width = 0
    b = size
    for line in lines:
        l, t, r, bottom = font.getbbox(line)
        max_width = max(max_width, r)
        b = bottom
    wa = max_width + padding * 2
    ha = b * len(lines) + margin * (len(lines) - 1) + padding * 2
    im = Image.new('RGB', (wa, ha), color=(255, 255, 255))
    draw = ImageDraw.Draw(im)
    for index, line in enumerate(lines):
        draw.text((padding, padding + index * (margin + b)), line, font=font, fill=(0, 0, 0))
    return im


def image_to_base64(img: Image.Image, format: str = 'PNG') -> str:
    output_buffer = BytesIO()
    img.save(output_buffer, format)
    byte_data = output_buffer.getvalue()
    base64_str = base64.b64encode(byte_data).decode()
    return 'base64://' + base64_str


# =================== 数据模型 ===================

class Arcade(BaseModel):
    name: str
    location: str
    province: str
    mall: str
    num: int
    id: str
    alias: List[str]
    group: List[int]
    person: int
    by: str
    time: str


class ArcadeList(List[Arcade]):

    async def save_arcade(self):
        return await writefile(arcades_json, [_.model_dump() for _ in self])

    def search_name(self, name: str) -> List[Arcade]:
        """模糊查询机厅"""
        arcade_list = []
        for arc in self:
            if name in arc.name:
                arcade_list.append(arc)
            elif name in arc.location:
                arcade_list.append(arc)
            elif name in arc.alias:
                arcade_list.append(arc)
        return arcade_list

    def search_fullname(self, name: str) -> List[Arcade]:
        """查询店铺全名机厅"""
        return [arc for arc in self if name == arc.name]

    def search_alias(self, alias: str) -> List[Arcade]:
        """查询别名机厅"""
        return [arc for arc in self if alias in arc.alias]

    def search_id(self, id: str) -> List[Arcade]:
        """指定ID查询机厅"""
        return [arc for arc in self if id == arc.id]

    def add_arcade(self, arcade_dict: dict) -> bool:
        """添加机厅"""
        self.append(Arcade(**arcade_dict))
        return True

    def del_arcade(self, arcadeName: str) -> bool:
        """删除机厅"""
        for arc in self:
            if arcadeName == arc.name:
                self.remove(arc)
                return True
        return False

    def group_in_arcade(self, group_id: int, arcadeName: str) -> bool:
        """是否已订阅该机厅"""
        for arc in self:
            if arcadeName == arc.name:
                if group_id in arc.group:
                    return True
        return False

    def group_subscribe_arcade(self, group_id: int) -> List[Arcade]:
        """已订阅机厅"""
        return [arc for arc in self if group_id in arc.group]

    @classmethod
    def arcade_to_msg(cls, arcade_list: List[Arcade]) -> List[str]:
        """机厅人数格式化"""
        result = []
        for arc in arcade_list:
            msg = f'{arc.name}\n    - 当前 {arc.person} 人\n'
            if arc.num > 1:
                msg += f'    - 平均 {arc.person / arc.num:.2f} 人\n'
            if arc.by:
                msg += f'    - 由 {arc.by} 更新于 {arc.time}'
            result.append(msg.strip())
        return result


class ArcadeData:

    total: Optional[ArcadeList]

    def __init__(self) -> None:
        self.arcades = []
        if arcades_json.exists():
            self.arcades: List[Dict] = json.load(open(arcades_json, 'r', encoding='utf-8'))
        self.idList = []

    def get_by_id(self, id: int) -> Optional[Dict]:
        id_list = [c_a['id'] for c_a in self.arcades]
        if id in id_list:
            return self.arcades[id_list.index(id)]
        return None

    async def getArcade(self):
        self.total = await download_arcade_info()
        self.idList = [int(c_a.id) for c_a in self.total]


arcade = ArcadeData()


# =================== AI 模糊匹配 ===================

def search_by_region(region: str) -> List[Arcade]:
    """筛选 location 以 region 开头的机厅"""
    return [arc for arc in arcade.total if arc.location.startswith(region)]


async def fuzzy_match_arcade(name: str, group_id: int) -> Optional[Arcade]:
    """
    通过 DeepSeek AI 模糊匹配机厅名称。
    1. 获取群的地区配置
    2. 筛选该地区的机厅
    3. 调用 DeepSeek API 选出最匹配的
    """
    region = get_group_region(group_id)
    if not region:
        return None

    config = load_config()
    api_key = config.get('deepseek_api_key')
    if not api_key:
        return None

    candidates = search_by_region(region)
    if not candidates:
        return None

    # 构建候选列表文本
    candidate_text = '\n'.join(
        f'{i+1}. {arc.name}' for i, arc in enumerate(candidates)
    )

    prompt = (
        f'你是一个机厅名称匹配助手。用户输入了一个简称或缩写，'
        f'请从以下机厅列表中找出最可能匹配的一个。\n'
        f'如果没有合理的匹配，只回复"无"。\n'
        f'如果有匹配，只回复对应的序号数字，不要回复其他任何内容。\n\n'
        f'机厅列表：\n{candidate_text}\n\n'
        f'用户输入：{name}'
    )

    try:
        connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                'https://api.deepseek.com/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': 'deepseek-chat',
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0,
                    'max_tokens': 16,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                answer = data['choices'][0]['message']['content'].strip()
                if answer == '无' or not answer.isdigit():
                    return None
                idx = int(answer) - 1
                if 0 <= idx < len(candidates):
                    return candidates[idx]
                return None
    except Exception:
        logger.error(f'DeepSeek API 调用失败: {traceback.format_exc()}')
        return None


# =================== 业务逻辑 ===================

async def download_arcade_info(save: bool = True) -> ArcadeList:
    # 重新加载本地数据，确保包含运行期间的所有更改（别名、订阅等）
    if arcades_json.exists():
        arcade.arcades = json.load(open(arcades_json, 'r', encoding='utf-8'))
    try:
        # 使用 ThreadedResolver 避免 Windows 上 aiodns 的 DNS 问题
        connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                'https://wc.wahlap.net/maidx/rest/location',
                timeout=aiohttp.ClientTimeout(total=30),
            ) as req:
                if req.status == 200:
                    data = await req.json()
                else:
                    data = None
                    logger.error('获取机厅信息失败')
    except Exception:
        data = None
        logger.error(f'Error: {traceback.format_exc()}')
        logger.error('获取机厅信息失败')

    arcadelist = ArcadeList()
    if data is not None:
        remote_ids = {_arc['id'] for _arc in data}
        if not arcade.arcades:
            for _arc in data:
                arcade_dict = {
                    'name': _arc['arcadeName'],
                    'location': _arc['address'],
                    'province': _arc['province'],
                    'mall': _arc['mall'],
                    'num': _arc['machineCount'],
                    'id': _arc['id'],
                    'alias': [],
                    'group': [],
                    'person': 0,
                    'by': '',
                    'time': '',
                }
                arcadelist.append(Arcade.model_validate(arcade_dict))
        else:
            for _arc in data:
                arcade_dict = arcade.get_by_id(_arc['id'])
                if arcade_dict is not None:
                    arcade_dict['name'] = _arc['arcadeName']
                    arcade_dict['location'] = _arc['address']
                    arcade_dict['province'] = _arc['province']
                    arcade_dict['mall'] = _arc['mall']
                    arcade_dict['num'] = _arc['machineCount']
                    arcade_dict['id'] = _arc['id']
                else:
                    arcade_dict = {
                        'name': _arc['arcadeName'],
                        'location': _arc['address'],
                        'province': _arc['province'],
                        'mall': _arc['mall'],
                        'num': _arc['machineCount'],
                        'id': _arc['id'],
                        'alias': [],
                        'group': [],
                        'person': 0,
                        'by': '',
                        'time': '',
                    }
                arcadelist.append(Arcade.model_validate(arcade_dict))
            # 保留手动添加的机厅（id >= 10000）
            for n in arcade.arcades:
                if int(n['id']) >= 10000:
                    arcadelist.append(Arcade.model_validate(n))
            # 清理本地缓存：移除远端已下架且非手动添加的机厅
            arcade.arcades = [
                a for a in arcade.arcades
                if a['id'] in remote_ids or int(a['id']) >= 10000
            ]
    else:
        for _a in arcade.arcades:
            arcadelist.append(Arcade.model_validate(_a))

    if save:
        await writefile(arcades_json, [_.model_dump() for _ in arcadelist])
    return arcadelist


async def updata_arcade(arcadeName: str, num: str) -> str:
    if arcadeName.isdigit():
        arcade_list = arcade.total.search_id(arcadeName)
    else:
        arcade_list = arcade.total.search_fullname(arcadeName)
    if arcade_list:
        _arcade = arcade_list[0]
        _arcade.num = int(num)
        msg = f'已修改机厅 [{arcadeName}] 机台数量为 [{num}]'
        await arcade.total.save_arcade()
    else:
        msg = f'未找到机厅：{arcadeName}'
    return msg


async def update_alias(arcadeName: str, aliasName: str, add_del: bool) -> str:
    """变更机厅别名，`add_del` 等于 `True` 为添加，`False` 为删除"""
    change = False
    if arcadeName.isdigit():
        arcade_list = arcade.total.search_id(arcadeName)
    else:
        arcade_list = arcade.total.search_fullname(arcadeName)
    if arcade_list:
        _arcade = arcade_list[0]
        if add_del:
            if aliasName not in _arcade.alias:
                _arcade.alias.append(aliasName)
                msg = f'机厅：{_arcade.name}\n已添加别名：{aliasName}'
                change = True
            else:
                msg = f'机厅：{_arcade.name}\n已拥有别名：{aliasName}\n请勿重复添加'
        else:
            if aliasName in _arcade.alias:
                _arcade.alias.remove(aliasName)
                msg = f'机厅：{_arcade.name}\n已删除别名：{aliasName}'
                change = True
            else:
                msg = f'机厅：{_arcade.name}\n未拥有别名：{aliasName}'
    else:
        msg = f'未找到机厅：{arcadeName}'
    if change:
        await arcade.total.save_arcade()
    return msg


async def subscribe(group_id: int, arcadeName: str, sub: bool) -> str:
    """订阅机厅，`sub` 等于 `True` 为订阅，`False` 为取消订阅"""
    change = False
    if arcadeName.isdigit():
        arcade_list = arcade.total.search_id(arcadeName)
    else:
        arcade_list = arcade.total.search_fullname(arcadeName)
    if arcade_list:
        _arcade = arcade_list[0]
        if sub:
            if arcade.total.group_in_arcade(group_id, _arcade.name):
                msg = f'该群已订阅机厅：{_arcade.name}'
            else:
                _arcade.group.append(group_id)
                msg = f'群：{group_id} 已添加订阅机厅：{_arcade.name}'
                change = True
        else:
            if not arcade.total.group_in_arcade(group_id, _arcade.name):
                msg = f'该群未订阅机厅：{_arcade.name}，无需取消订阅'
            else:
                _arcade.group.remove(group_id)
                msg = f'群：{group_id} 已取消订阅机厅：{_arcade.name}'
                change = True
    else:
        msg = f'未找到机厅：{arcadeName}'
    if change:
        await arcade.total.save_arcade()
    return msg


async def batch_subscribe_region(group_id: int, region: str, sub: bool) -> str:
    """按地区批量订阅/取消订阅机厅，同时设置/清除群地区配置"""
    candidates = search_by_region(region)
    if not candidates:
        return f'未找到地区「{region}」的任何机厅'

    added = []
    skipped = []
    removed = []
    for arc in candidates:
        if sub:
            if group_id not in arc.group:
                arc.group.append(group_id)
                added.append(arc.name)
            else:
                skipped.append(arc.name)
        else:
            if group_id in arc.group:
                arc.group.remove(group_id)
                removed.append(arc.name)

    await arcade.total.save_arcade()

    if sub:
        await set_group_region(group_id, region)
        lines = [f'已批量订阅「{region}」共 {len(added)} 家机厅']
        if skipped:
            lines.append(f'其中 {len(skipped)} 家已订阅，跳过')
        lines.append(f'同时已设置群地区为：{region}')
    else:
        lines = [f'已批量取消订阅「{region}」共 {len(removed)} 家机厅']

    return '\n'.join(lines)


async def log_removed_arcades(removed: List[Arcade]) -> None:
    """将被远端移除的机厅记录到 data/removed_arcades.json"""
    log_file = _DATA_DIR / 'removed_arcades.json'
    records = []
    if log_file.exists():
        records = json.load(open(log_file, 'r', encoding='utf-8'))
    records.append({
        'time': time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        'removed': [
            {'id': a.id, 'name': a.name, 'location': a.location}
            for a in removed
        ],
    })
    await writefile(log_file, records)


async def update_person(arcadeList: List[Arcade], userName: str, value: str, person: int) -> str:
    """变更机厅人数"""
    if len(arcadeList) == 1:
        _arcade = arcadeList[0]
        original_person = _arcade.person
        if value in ['+', '＋', '增加', '添加', '加']:
            if person > 30:
                return '请勿乱玩bot，恼！'
            _arcade.person += person
        elif value in ['-', '－', '减少', '降低', '减']:
            if person > 30 or person > _arcade.person:
                return '请勿乱玩bot，恼！'
            _arcade.person -= person
        elif value in ['=', '＝', '设置', '设定']:
            if abs(_arcade.person - person) > 30:
                return '请勿乱玩bot，恼！'
            _arcade.person = person
        if _arcade.person == original_person:
            return f'人数没有变化\n机厅：{_arcade.name}\n当前人数：{_arcade.person}'
        else:
            _arcade.by = userName
            _arcade.time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            await arcade.total.save_arcade()
            return f'机厅：{_arcade.name}\n当前人数：{_arcade.person}\n变更时间：{_arcade.time}'
    elif len(arcadeList) > 1:
        return '找到多个机厅，请使用id变更人数\n' + '\n'.join([f'{_.id}：{_.name}' for _ in arcadeList])
    else:
        return '没有找到指定机厅'
