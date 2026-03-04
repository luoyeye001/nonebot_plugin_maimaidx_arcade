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
