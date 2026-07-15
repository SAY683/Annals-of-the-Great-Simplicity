"""
Counterfactual Sentai — Token / Concept Filters
================================================
统一处理 TRACE token 到 DoWhy 概念节点的过滤逻辑。
兼容字级和词级 BPE，避免在多个模块中重复维护 stopword / punctuation 列表。
"""

import unicodedata


# BPE 特殊碎片与 SentencePiece 前缀
BPE_FRAGMENTS = {"<unk>", "▁<unk>", "<s>", "</s>", "<pad>", "<mask>"}

# 中文高频虚词（字级 BPE 单字过滤）
# 包括：结构助词、介词、代词、语气词、量词/数词、常见副词性单字
_CN_STOP_CHARS = set(
    "的了是在和也就都还会要把能被到着过所而为"
    "之以其于及与此但若虽因故既且或非"
    "它他她你我咱这那哪什怎为对中个种样"
    "么呢吧啊哦嗯哟哈嘛哩呐哇喽兮哉乎邪"
    "一二三四五六七八九十百千万亿几两多更"
    "只条张本片根件块项位把次回遍顿阵任"
    "将不地来去上下左右前后里外内间旁过"
    "着过得好累真太比较更最很极已正曾"
    "又也并而况且跟同与及以及除非若假使"
    "让令叫使被把给由在从向往朝到至于"
)

# 古汉语虚词/语法字：在 classical_mode 下保留，避免过滤掉 Shenji 古文中的重要因果信号
_CLASSICAL_KEEP_CHARS = set("之乎者也矣焉哉邪与")

# 中文常见虚词/连接词/语法词/代词（多字 BPE 亦需过滤）
_CN_STOP_WORDS = {
    # 连接词
    "导致", "从而", "因此", "因而", "所以", "于是", "可见", "总之",
    "因为", "由于", "既然", "除非", "即使", "尽管", "虽然", "但是",
    "然而", "不过", "只是", "可是", "而且", "并且", "或者", "还是",
    "与其", "不如", "不但", "不仅", "不管", "无论", "只要", "只有",
    "况且", "何况", "加之", "此外", "另外", "同时", "同样", "反而",
    # 介词/助词组合
    "对于", "关于", "根据", "按照", "通过", "经过", "随着", "顺着",
    "沿着", "趁着", "除了", "除去", "向着", "朝着", "对着", "为了",
    "为着", "作为", "成为", "以为", "认为", "看作", "当作",
    # 副词/语气词/助动词
    "非常", "十分", "特别", "相当", "比较", "稍微", "略微", "尤其",
    "大概", "大约", "几乎", "简直", "根本", "绝对", "相对", "最终",
    "最初", "首先", "其次", "再次", "最后", "接着", "然后", "后来",
    "例如", "比如", "譬如", "诸如", "等等", "云云", "之类",
    "什么", "怎么", "怎样", "如何", "为何", "为什么", "干什么", "怎么样",
    "是不是", "能不能", "可不可以", "要不要", "有没有", "能否", "是否",
    "已经", "曾经", "正在", "将要", "就要", "快要", "马上", "立刻",
    "也许", "或许", "大概", "恐怕", "应该", "应当", "必须", "需要",
    "可以", "可能", "能够", "会", "能", "可", "要", "得", "须",
    "那么", "这么", "多么", "如此", "那样", "这样", "一样", "一般",
    "一下", "一点", "一些", "一方面", "另一方面", "之一", "之二",
    "起来", "下去", "出来", "过来", "过去", "进来", "进去",
    # 代词/数量词/指示词
    "这个", "那个", "这些", "那些", "这里", "那里", "这边", "那边",
    "这种", "那种", "这位", "那位", "本人", "对方", "彼此", "大家",
    "我们", "你们", "他们", "她们", "它们", "咱们", "自己", "人家",
    "一切", "所有", "任何", "每个", "有些", "有的", "之一", "其余",
    "一个", "一种", "一些", "一点", "许多", "很多", "不少", "大量",
    "部分", "全部", "整体", "局部", "多数", "少数", "一半", "全部",
    # 常见语法词/助词组合（jieba 易切出；BPE 跨域文本亦常产生）
    "就是", "不是", "而是", "还是", "或是", "即是", "便是", "乃是",
    "才有", "才是", "也有", "没有", "要有", "会有", "能有", "可有", "似有",
    "之中", "之间", "之内", "之外", "之前", "之后", "以上", "以下",
    "之类", "的话", "来说", "而言", "看来", "说来",
    "觉得", "感到", "感觉", "认为", "以为", "看见", "看到", "显得",
    "到了", "的是", "这一", "这就是", "从未", "我们要", "的东西",
    "的人", "这一点", "世界的", "的原因", "主动的", "对此", "不可",
    # 数量/程度
    "许多", "很多", "不少", "大量", "部分", "全部", "整体", "局部",
    "非常", "极其", "十分", "相当", "特别", "尤其", "越发", "更加",
    "越来越", "愈来", "愈来愈", "最多", "最少", "最大", "最小",
}

# 基础标点集合
_PUNCT_BASE = (
    # 中文标点
    "。，、；：？！“”‘’"
    "（）【】《》…—·"
    # ASCII 标点
    ",.;:?!'\""
    # 括号
    "()[]{}"
    # CJK 扩展标点
    "「」"
)

PUNCT_SET = set(_PUNCT_BASE)
# 通过码点补充，避免源文件编码歧义
for _cp in (
    0x201C, 0x201D, 0x2018, 0x2019, 0x300C, 0x300D,
    0xFF08, 0xFF09, 0x300A, 0x300B,
    0x0028, 0x0029, 0x005B, 0x005D, 0x007B, 0x007D,
    0x0022, 0x0027,
):
    PUNCT_SET.add(chr(_cp))


def is_valid_concept(name: str, classical_mode: bool = False) -> bool:
    """
    判断 token/concept 名称是否适合进入因果图。
    过滤条件:
      - 空字符串或 BPE 特殊碎片
      - SentencePiece 前缀 ▁
      - 纯标点
      - 纯数字
      - 单字中文虚词（classical_mode=True 时保留古汉语虚词，适用于 Shenji 古文）
      - <other> 聚合桶
    """
    if not name or name in BPE_FRAGMENTS:
        return False
    if name.startswith("▁"):
        return False

    stripped = name.strip()
    if not stripped:
        return False

    # 纯标点
    if all(ch in PUNCT_SET for ch in stripped):
        return False

    # 纯数字（含全角数字）
    if stripped.isdigit():
        return False
    try:
        if all(unicodedata.digit(ch) is not None for ch in stripped):
            return False
    except (ValueError, TypeError):
        pass

    # 字级 BPE: 单字虚词
    if len(stripped) == 1 and stripped in _CN_STOP_CHARS:
        if classical_mode and stripped in _CLASSICAL_KEEP_CHARS:
            pass  # 古汉语模式下保留之/乎/者/也等虚词
        else:
            return False

    # 多字 BPE / 词级: 常见虚词/连接词/语法词
    if stripped in _CN_STOP_WORDS:
        return False

    if name == "<other>":
        return False

    return True


def is_unk_token(token: str) -> bool:
    """判断是否为 UNK token（含 SentencePiece 前缀形式）。"""
    return token in ("<unk>", "▁<unk>")


def classify_bpe_type(token_list: list[str]) -> str:
    """
    根据有效 token 中单字比例，推测 BPE 类型。
    返回 "character" 或 "word"。
    """
    valid = [t for t in token_list if t not in BPE_FRAGMENTS and not t.startswith("▁")]
    if not valid:
        return "unknown"
    n_single = sum(1 for t in valid if len(t.strip()) == 1)
    ratio = n_single / len(valid)
    return "character" if ratio > 0.6 else "word"
