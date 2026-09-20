"""D2 默认专题种子：幂等注入 3 个任务型专题及其条目。

仅在配置 settings.seed_default_collections 开启时由 lifespan 调用。
用 system_settings(key='default_collections_seeded') 标记幂等：已标记则跳过。
条目通过 CollectionItem(item_type='catalog_entry') 引用 seed 创建的 published
CatalogEntry，使专题页在无文件资源时仍可展示 5-15 个可读条目；同时保留对
resource 条目的兼容（部署者可用 admin 替换为真实文件引用）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..models import CatalogEntry, Collection, CollectionItem, SystemSetting

_SEED_FLAG = "default_collections_seeded"


def _now() -> datetime:
    return datetime.now(timezone.utc)


_TOOLS = [
    ("VS Code", "software", "轻量级代码编辑器，插件生态丰富"),
    ("Git", "software", "分布式版本控制，团队协作基础"),
    ("Node.js", "software", "JavaScript 运行时，前端工具链依赖"),
    ("Python", "software", "通用脚本与数据处理语言"),
    ("Docker", "software", "容器化运行环境，隔离依赖"),
    ("Postman", "software", "接口调试与文档工具"),
    ("DBeaver", "software", "多数据库可视化管理客户端"),
    ("7-Zip", "software", "高压缩比归档工具"),
]

_SKILLS = [
    ("HTML 基础", "document", "页面结构与语义标签"),
    ("CSS 布局", "document", "Flex/Grid 布局与响应式"),
    ("JavaScript 入门", "document", "语法、DOM 与异步模型"),
    ("React 基础", "document", "组件、状态与 Hooks"),
    ("Node 服务", "document", "Express/Koa 接口搭建"),
    ("SQL 数据库", "document", "查询、索引与建模"),
    ("Git 协作", "video", "分支策略与冲突解决演示"),
    ("摄影构图", "video", "三分法与引导线构图讲解"),
    ("视频剪辑", "video", "剪辑节奏与转场入门"),
    ("音频处理", "video", "降噪与混音基础"),
    ("设计基础", "document", "排版、色彩与视觉层级"),
    ("项目实战", "video", "从需求到上线的完整流程"),
]

_ASSETS = [
    ("品牌 Logo", "image", "可缩放矢量品牌标识"),
    ("UI 图标集", "image", "常用界面线性图标包"),
    ("字体包", "image", "中英文开源字体合集"),
    ("背景纹理", "image", "无缝贴图与渐变素材"),
    ("插画素材", "image", "扁平风格插画组件"),
    ("PPT 模板", "document", "汇报与教学演示模板"),
    ("简历模板", "document", "结构与排版可复用简历"),
    ("合同范本", "document", "常用协作与授权合同"),
    ("配色方案", "image", "主题色板与可访问性校验"),
    ("图标规范", "document", "命名、栅格与导出约定"),
]

_TOPICS = [
    {
        "name": "工具配置入门",
        "description": "从零搭建开发与效率工具链，一次配齐常用软件。",
        "goal": "完成常用开发与效率工具的安装和基础配置",
        "audience": "刚搭建工作环境的开发者与内容创作者",
        "prerequisites": "一台可联网的电脑，管理员权限安装软件",
        "item_intro": "按顺序安装并配置以下工具，每步附简要说明。",
        "entries": _TOOLS,
    },
    {
        "name": "技能学习路径",
        "description": "系统化前后端与多媒体制作的学习路线。",
        "goal": "建立从基础到进阶的内容制作与开发技能体系",
        "audience": "希望系统学习前后端与多媒体制作的初学者",
        "prerequisites": "具备基本电脑操作能力，已完成工具配置",
        "item_intro": "按主题分阶段学习，每个条目对应一组教程或视频。",
        "entries": _SKILLS,
    },
    {
        "name": "项目素材准备",
        "description": "可复用的素材与文档模板，快速启动新项目。",
        "goal": "为典型项目准备可复用的素材与文档模板",
        "audience": "需要快速启动新项目的团队与个人",
        "prerequisites": "已确定项目主题与目标平台",
        "item_intro": "以下素材与模板按类别整理，可直接引用或二次加工。",
        "entries": _ASSETS,
    },
]


async def seed_default_collections(state) -> bool:
    """幂等注入默认专题。返回是否实际写入。"""
    flagged = await state.scalar(select(SystemSetting).where(SystemSetting.key == _SEED_FLAG))
    if flagged is not None:
        return False

    now = _now()
    entry_seq = 0
    for topic_index, topic in enumerate(_TOPICS):
        collection = Collection(
            name=topic["name"],
            description=topic["description"],
            cover="",
            status="active",
            visible_on_home=True,
            sort_order=topic_index,
            goal=topic["goal"],
            audience=topic["audience"],
            prerequisites=topic["prerequisites"],
            item_intro=topic["item_intro"],
        )
        state.add(collection)
        await state.flush()

        for position, (title, content_type, summary) in enumerate(topic["entries"]):
            entry_seq += 1
            entry_id = f"d2seed{entry_seq:03d}"
            slug = f"d2-seed-{entry_seq:03d}"
            entry = CatalogEntry(
                entry_id=entry_id,
                content_type=content_type,
                slug=slug,
                title=title,
                summary=summary,
                description=summary,
                cover_resource_id=None,
                status="published",
                revision=1,
                sort_order=position,
                published_at=now,
            )
            state.add(entry)
            state.add(CollectionItem(
                collection_id=collection.id,
                item_type="catalog_entry",
                catalog_entry_id=entry_id,
                note=summary,
                sort_order=position,
            ))

    state.add(SystemSetting(key=_SEED_FLAG, value="1", value_type="string"))
    await state.commit()
    return True
