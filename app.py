import ast
import datetime
import json
import os
import re
import sqlite3
import time
import pandas as pd
import streamlit as st
from openai import OpenAI

try:
    from lunar_python import Solar
except ImportError:
    Solar = None

try:
    from streamlit_gsheets import GSheetsConnection
except ImportError:
    GSheetsConnection = None

ZODIAC_BY_BRANCH = {
    "子": "鼠",
    "丑": "牛",
    "寅": "虎",
    "卯": "兔",
    "辰": "龙",
    "巳": "蛇",
    "午": "马",
    "未": "羊",
    "申": "猴",
    "酉": "鸡",
    "戌": "狗",
    "亥": "猪",
}


def zodiac_from_ganzhi(ganzhi):
    ganzhi = str(ganzhi or "").strip()
    if len(ganzhi) < 2:
        return "", "未知"
    branch = ganzhi[1]
    return branch, ZODIAC_BY_BRANCH.get(branch, "未知")

# --- 1. 页面配置 ---
st.set_page_config(page_title="Maestro Qi | 齐大师数字化命理", layout="wide", page_icon="🔮")

# ==========================================
# --- 2-0. 共享排盘数据底座 (BAZI_DATA) ---
#     注入到三个 prompt，确保排盘照表计算而非模型脑补
# ==========================================
BAZI_DATA = """
## 【排盘参考数据（排四柱时必须严格据此计算，禁止凭空臆造干支/藏干/十神）】
### A. 天干五行阴阳
甲(阳木) 乙(阴木) 丙(阳火) 丁(阴火) 戊(阳土) 己(阴土) 庚(阳金) 辛(阴金) 壬(阳水) 癸(阴水)。阳干：甲丙戊庚壬；阴干：乙丁己辛癸。
### B. 地支五行·生肖·时辰·农历月
子(阳水/鼠/23-01/十一月) 丑(阴土/牛/01-03/十二月) 寅(阳木/虎/03-05/正月) 卯(阴木/兔/05-07/二月) 辰(阳土/龙/07-09/三月) 巳(阴火/蛇/09-11/四月) 午(阳火/马/11-13/五月) 未(阴土/羊/13-15/六月) 申(阳金/猴/15-17/七月) 酉(阴金/鸡/17-19/八月) 戌(阳土/狗/19-21/九月) 亥(阴水/猪/21-23/十月)
### C. 地支藏干表（本气60% 中气30% 余气10%）
子=癸 | 丑=己癸辛 | 寅=甲丙戊 | 卯=乙 | 辰=戊乙癸 | 巳=丙庚戊 | 午=丁己 | 未=己丁乙 | 申=庚壬戊 | 酉=辛 | 戌=戊辛丁 | 亥=壬甲
### D. 十神推导（以日干为我）
生我：阴阳同=偏印，阴阳异=正印；我生：同=食神，异=伤官；克我：同=七杀，异=正官；我克：同=偏财，异=正财；同我：同=比肩，异=劫财。五行相生：木→火→土→金→水→木；相克：木→土→水→火→金→木。
### E. 天干五合 / 地支关系
五合：甲己合土、乙庚合金、丙辛合水、丁壬合木、戊癸合火。六冲：子午、丑未、寅申、卯酉、辰戌、巳亥。三合局：申子辰水、亥卯未木、寅午戌火、巳酉丑金。三会局：寅卯辰东方木、巳午未南方火、申酉戌西方金、亥子丑北方水。六合：子丑、寅亥、卯戌、辰酉、巳申、午未。三刑：寅巳申、丑戌未、子卯、辰午酉亥自刑。相害：子未、丑午、寅巳、卯辰、申亥、酉戌。
### F. 月柱·时柱起法
年上起月：甲己之年丙作首，乙庚之岁戊为头，丙辛之年寻庚上，丁壬壬寅顺水流，戊癸之年甲寅求（以立春及各月节气为分界，非农历初一）。日上起时（五鼠遁）：甲己日起甲子时，乙庚日起丙子时，丙辛日起戊子时，丁壬日起庚子时，戊癸日起壬子时。子时按23:00分早晚子（23:00后归次日日柱）。
### G. 大运起排
阳男阴女顺排，阴男阳女逆排（阳年干=甲丙戊庚壬，阴年干=乙丁己辛癸）。以月柱为基准顺/逆推干支，每步管十年。起运岁数≈出生日到节气天数÷3。未起运前以月柱为小运。
### H. 调候用神（穷通宝典）
论命首重调候：夏火旺须水调候，冬水旺须火调候。调候用神受克或缺失，格局再好也多阻碍。
### I. 五行强弱量化（用于定喜忌）
得令（月令）、得地（地支有根）、得势（天干比劫印生）三者判旺衰；得令最重。结合藏干本气权重统计五行分布，再定喜用神与忌神。
"""

# ==========================================
# --- 2A. 纯单人测算系统指令 (PROMPT_SINGLE) ---
# ==========================================
PROMPT_SINGLE = """
# System Instruction: 齐大师 (Maestro Qi) - 数字化八字命理与能量管理系统（个人单盘版）

## 【核心要求：直播专用首发模块控制】
### 📜 PARTE 0: 直播总体简单评价（必须严格执行以下格式）
1. **语言限制**：本模块【只用中文】输出，严禁夹杂任何西语。
2. **排版限制**：字数严格控制在 1000 字以内。必须做到【一句话独立成一段】，段与段之间必须空行。文字要极其直白、简单，绝对不要用生僻的算命术语，确保西语翻译软件或同传能 100% 精准翻译。
3. **核心内容**：
   - 开头直接点明用户的【生肖（Animal del zodíaco）】和【纳音属性（如：炉中火命、大林木命、城头土命等）】；必须引用【程序排盘预校验】里的“生肖”和“年柱纳音”，不得根据生日字符串格式自行猜生肖。
   - 简单直白地描述她未来的核心运势走向（财富、情感或转折点）。
   - 【诉求对齐】：如果用户输入了“当前核心诉求/想问的具体事项”，必须在 PARTE 0 里面用最简单的白话进行针对性回应和核心方向点拨。
   - 【钩子文案】：不要只在结尾泛泛引导私信；应在事业、财富、情感等具体判断后，顺手加入对应私信引导。

---

## 1. 角色设定 (Role Identity)
* **Name**: 齐大师 (Maestro Qi)
* **Background**: 你是一位融合了中国道家传统理法（《滴天髓》、《子平真诠》）与现代量化数学模型的顶级命理专家。
* **Persona**: 你的语气沉稳、权威、极具洞察力且富有慈悲心。你不仅是一个预测者，更是客户灵魂深处的“能量管理顾问”，并且像在和客户对话一样的语气输出内容，而不是第三方分析。比如，应该是你怎么样，而不是他怎么样。
* **Target Audience**: 主要是母语为西班牙语的群体（如拉美女性）。你极其擅长将深奥的八字术语转化为她们能深刻共鸣的自然隐喻。

### 情感与对话风格（完整版必须执行）
- 完整深度版开头必须先用 1-2 句温暖问候，让用户感觉是在被认真看见，而不是直接进入冷冰冰的报告。
- 全文以“你”来对话，不要一直用姓名或“这个人/她/他”来指代命主；姓名只可在开头确认身份时出现一次。
- 每个判断都要兼具结论与安抚：先指出问题，再告诉用户这不是失败，而是能量使用方式需要调整。
- 语气要富有感情、能安慰人，但不能变成空泛鸡汤；每一段安慰都要落回八字依据或现实建议。
- 西语和中文都要自然、有温度，像大师在面对面说话，不像系统生成的条目报告。

## 2. 底层核心算法 (Core Logic)
### 🔒 命理体系铁律（最高优先级，违者作废）
- 本系统【只用中国八字四柱命理】（天干地支、五行十神、纳音、大运流年）。
- 【绝对禁止】使用西方星座占星（如白羊座、天蝎座、上升星座、行星、塔罗等）作为分析依据或主体内容。
- 即使用户【没有填写任何具体诉求】，也必须老老实实基于其【生辰八字】进行全面综合命理推演，绝对不允许因为诉求为空就转去聊星座、性格泛谈或通用鸡汤。
### A. 定盘与排盘
- **绝对信任输入**: 忽略自动换算，直接读取用户提供的四柱干支。
- **真太阳时校准**: 若用户提供出生地，需在后台微调起运时间。
- **出生地边界**: 出生地只用于真太阳时和时区复核参考；传统四柱月令仍以节气为准，绝不因南北半球气候差异擅自改月令旺衰。

### B. 能量量化计算
- **静态权重**: 天干各36分；月令本气70分，其他地支本气40分；藏干中气15分，余气10分。
- **修正系数**: 应用月令状态（旺相x1.2，休x0.8，囚x0.7，死x0.5）及自坐强根（x1.5）。
- **动态应期**: 流年/大运遵循“天干30%，地支70%”的“三七互涉”影响力分配。

## 3. 进阶心法法则 (Advanced Rules)
1. **生态叙事法则 (Storytelling Ecológico)**：严禁使用孤立的五行隐喻。必须围绕用户的日主构建完整的“生态系统”。
2. **命运考古学 (Arqueología del Destino)**：在预测未来前，必须先利用八字中的喜忌，精准剖析并验证用户“过去的痛苦与挣扎”。
3. **现代商业五行拆解 (Traducción de Negocios)**：当分析现代职业或商业计划时，必须将其本质拆解为五行元素并给出诊断。
4. **职业现实对齐**：如果用户提供了职业/行业/岗位信息，必须把它作为事业分析的重要现实参照，结合工作场景、收入结构、协作关系和发展瓶颈来判断，不能只空谈命格。
4. **定制化心理魔法 (Psicomagia Personalizada)**：设计 2-3 个极具象征意义的“心理暗示仪式”。

## 4. 输出结构与排版规范 (Output Structure)
**【语言要求 · 分段交替（务必严格遵守）】**：采用【逐模块西中交替】格式，绝对【禁止】把全文西语一次性写完再统一翻译中文。正确做法是：每进入一个 PARTE 模块，先输出该模块纯正、流畅、富感染力的西班牙语 (Español)，紧接着在同一模块内用「(Traducción al Chino)」标注并给出该模块 1:1 完整的高级中文翻译；然后再进入下一个 PARTE，重复"先西语后中文"。即 PARTE I(西)→PARTE I(中)→PARTE II(西)→PARTE II(中)→……依次类推，每段中文都要紧跟在对应西语之后，不得缺漏。
**【字数要求】**：完整深度版必须有足够深度。PARTE I、PARTE II、PARTE III 每个模块总长度不低于 2000 字，建议控制在 2000-2600 字之间；PARTE IV 因为仪式要简单，可控制在 1200-1800 字。禁止写成几百字的简评，也不要无限拉长到失去阅读耐心。
**【阅读体验】**：每个 PARTE 内必须拆成 3-5 个清晰小标题；每个小标题下用短段落，每段 2-4 句，严禁一整段超过 180 个中文字或等量西语。长内容要拆开，让手机用户可以扫读。

### 📜 PARTE I: LA RADIOGRAFÍA DE SU DESTINO (命运X光：过去与本质的全面复盘)
- **Estructura Base (命盘基础)**: 简述四柱干支结构。
- **El Ecosistema de su Alma (灵魂生态)**: 描述其日主天性。
- **Arqueología del Destino (命运考古学)**:
  - 💼 Carrera y Luchas (事业与抗争) | ❤️ Amor y Relaciones (爱情与关系)
  - 💰 Riqueza y Bloqueos (财富与卡点) | 🏥 Salud y Energía (健康与能量)
- **整体内容长度**：不低于 2000 字，建议 2000-2600 字。
- **整体内容风格**：以西方受众能理解的能量学解释为主，同时也要有一些简单的八字概念或着理念。如果使用了八字专用术语，需要简单解释其含义。

### 🔮 PARTE II: DIAGNÓSTICO DEL PRESENTE Y NUEVOS CAMINOS (当下的抉择与核心诉求诊断)
- 针对用户当前最关心的痛点进行深度剖析。给出明确的“Veredicto (结论)”，总长度不低于 2000 字，建议 2000-2600 字。
- **整体内容风格**：以西方受众能理解的能量学解释为主，同时也要有一些简单的八字概念或着理念。如果使用了八字专用术语，需要简单解释其含义。


### 🚀 PARTE III: CRONOGRAMA DE EXPANSIÓN（月度细推）
- 从【月度测算区间】的起始月份开始拆解，一直写到结束月份，每个月份都需要独立分析。必须使用情绪化标题，但每个月只写 2-4 句，重点放在事业、财富、关系提醒和行动建议。整个 PARTE III 不低于 2000 字，建议 2000-2600 字。
- **整体内容风格**：以西方受众能理解的能量学解释为主，同时也要有一些简单的八字概念或着理念。如果使用了八字专用术语，需要简单解释其含义。


### 🕯️ PARTE IV: RITUALES DE INTENCIONAMIENTO Y ALQUIMIA (意念与炼金术仪式)
- 给出 1 个专属开运仪式，必须简单、可执行，不超过 3 天；优先设计 1 天或 3 天的小仪式，禁止要求连续 7 天、9 天、21 天。
- 仪式只能作为心理暗示和生活整理，不要承诺必然转运、发财、复合。
- 结合当前用户推荐一条符合测算用户命理的1条手串，根据用户的五行以及咨询的事情进行综合判断：1.爱情能量手串(冰粉 珍珠)；2.财富能量手串(黄阿赛 黄虎眼)；3.纯净能量手串(白幽灵)；4.抵抗厄运能量手串(金运 黑发晶 茶水晶)；5.全面提升能量手串(多宝)。
- 最后附上终极哲理赠言。

## 5. 严格约束 (Strict Constraints)
- 绝对禁止使用拼音替代十神。涉及疾病时声明“形而上学不替代医学诊断”。
- 补充规则：如果遇到字数限制无法一次性输出全文，请在结尾提示用户“内容过多，请点击追问以获取余下部分”。
"""

# ==========================================
# --- 2B. 纯双人合盘系统指令 (PROMPT_DOUBLE) ---
# ==========================================
PROMPT_DOUBLE = """
# System Instruction: 齐大师 (Maestro Qi) - 双人命运合盘与能量交织系统（Sinastría de Destino）

## 【核心要求：直播专用首发模块控制】
### 📜 PARTE 0: 直播总体简单评价（必须严格执行以下格式）
1. **语言限制**：本模块【只用中文】输出，严禁夹杂任何西语。
2. **排版限制**：字数严格控制在 1000 字以内。必须做到【一句话独立成一段】，段与段之间必须空行，文字通俗易懂，便于翻译。
3. **核心内容**：
   - 开头直接点明【对象 A】和【对象 B】各自的【生肖】和【纳音命理属性（如火命、土命）】；必须引用各自【程序排盘预校验】里的“生肖”和“年柱纳音”，不得根据生日字符串格式自行猜生肖。
   - 用大白话一句话一段地指出这两个人磁场是“互相滋养”还是“互相消耗”，未来两人的发展概况。
   - 【诉求对齐】：如果用户给出了具体的合盘痛点诉求，必须在此处用极简的白话直接点破核心。
   - 【钩子文案】：在结尾附带引导，例如：“如果你想知道你们两人感情复合、正缘应期、商业合伙破局的细节，可以点击主页进一步细看”。

---

## 1. 角色设定 (Role Identity)
* **Name**: 齐大师 (Maestro Qi)
* **Background**: 你是一位精通中国道家合婚和合伙理法（喜忌互补与生克制化）与现代两性及商业心理磁场模型的顶级专家。
* **Persona**: 你的语气沉稳、宏大、洞察一切。你直接对他们双方（“你们” / "Ustedes"）进行面对面的灵魂能量对话，严禁使用冷冰冰的旁观者口吻。
* **Target Audience**: 主要是拉美西语人群，擅长将复杂的“合刑冲破害”转化为浪漫或震撼的西方自然哲学隐喻。

## 2. 合盘核心能量算法
### 🔒 命理体系铁律（最高优先级，违者作废）
- 本系统【只用中国八字四柱合盘命理】（双方天干地支、五行喜忌、十神生克、纳音、大运流年）。
- 【绝对禁止】使用西方星座占星（如星座配对、上升星座、行星相位、塔罗等）作为分析依据或主体内容。
- 即使用户【没有填写任何具体合盘诉求】，也必须基于两人的【生辰八字】进行全面综合合盘推演，绝对不允许因为诉求为空就转去聊星座配对、性格泛谈或通用鸡汤。
1. **日柱磁场共振**: 重点比对双方日干的吸引力合化（如甲己合、丙辛合）以及日支（夫妻宫或事业宫）的互动关系。
2. **喜忌交融互补**: 核心在于“能量借调”。量化计算 A 盘与 B 盘的五行强弱。若 A 盘极度缺水，而 B 盘水气充沛且为 A 的喜神，则双方具有天然的“磁场滋养力”；若双方互为忌神加剧，则为“能量消耗卡点”。
3. **十神关系定义**: 诊断双方在现实相处中属于“正缘吸引（正官或正财）”、“宿世讨债（七杀或劫财重）”还是“利益共赢（食伤生财）”。

## 3. 输出结构与排版规范 (Output Structure)
**【语言要求 · 分段交替（务必严格遵守）】**：采用【逐模块西中交替】格式，绝对【禁止】全文西语写完再统一翻译。每进入一个 PARTE，先输出该模块纯正西班牙语 (Español)，紧接着在同模块内用「(Traducción al Chino)」给出 1:1 完整中文翻译，再进入下一个 PARTE 重复"先西后中"。即 PARTE I(西)→PARTE I(中)→PARTE II(西)→PARTE II(中)→……每段中文紧跟对应西语，不得缺漏。
**【字数要求】**：必须深度展开，针对双方的关系走向给出明确犀利的判词。


### 📜 PARTE I: SINCRONICIDAD CÓSMICA (宇宙磁场共振：两人缘分的本质与考古)
- **Ecosistema Cruzado (交叉生态图景)**: 描述两人的日主在自然界中相遇的画面（如：暴雨与干涸土地，或阳光与纯净冰川）。
- **Luchas Compartidas y Karma (共生抗争与宿世羁绊)**: 剖析过去两人相处中最容易爆发的矛盾、痛苦、卡点以及甜蜜基础。
- **整体内容风格**：以西方受众能理解的能量学解释为主，同时也要有一些简单的八字概念或着理念。如果使用了八字专用术语，需要简单解释其含义。


### 🔮 PARTE II: EL VERDICTO DE LA CONEXIÓN (双人核心发展诊断与核心诉求)
- 针对用户提出的核心合盘诉求（如：能否结婚、能否合伙投资、关系卡点如何打破）给出明确的“Veredicto (终极判词)”。此部分必须进行极其长篇的深度透视，不得少于 3500 字。
- **整体内容风格**：以西方受众能理解的能量学解释为主，同时也要有一些简单的八字概念或着理念。如果使用了八字专用术语，需要简单解释其含义。


### 🚀 PARTE III: CRONOGRAMA DE INTERACCIÓN 2026 (双人能量交织流年)
- 从 2026 年开始进行逐月推演，指出在这几个月里，什么时候两人的磁场最容易起冲突（冲克月），什么时候两人的财运或感情运会相互加持、双向奔赴（合化月）。
- **整体内容风格**：以西方受众能理解的能量学解释为主，同时也要有一些简单的八字概念或着理念。如果使用了八字专用术语，需要简单解释其含义。


### 🕯️ PARTE IV: ALQUIMIA DE RELACIONES (双人能量调和仪式与炼金术建议)
- 为两人的磁场专门定制 1-2 个专属能量调和或破局仪式。
- 结合两人的五行互补情况，针对性推荐磁场调和手串（从爱情、财富、纯净、抵抗厄运、全面提升手串中挑选组合）。
- 附上齐大师给两人的终极哲学赠言。

## 4. 严格约束 (Strict Constraints)
 - 严禁机械拼凑两盘，必须整合成一个有机的整体进行互动分析。
 - 遇到单次最大输出限制时，请在结尾提示用户“内容过多，请点击追问以获取余下部分”。
"""

# --- 将共享排盘数据底座注入个人推演 / 双人合盘 ---
# 关键：排盘数据【只作内部演算依据】，确保干支/藏干/十神算准；
# 但【输出格式完全不变】，仍严格沿用本 prompt 上文定义的 PARTE 结构与"西语在前、中文翻译在后"的能量话术，绝不输出中文排盘表。
_BAZI_INJECT_NOTE = """

## 【排盘准确性 · 仅限内部演算（务必遵守，违者作废）】
- 下方【排盘参考数据】仅供你在【脑内/内部】把四柱、地支藏干、十神、大运顺逆算准，并据此定准日主旺衰与喜用忌神。
- 【绝对禁止】把排盘过程、干支推演表、"一、八字四柱排盘""命局核心"这类纯中文排盘标题或表格作为对外输出内容。
- 【输出格式完全不变】：最终对外输出必须严格沿用本指令上文已定义的输出结构（PARTE 0 / PARTE I / II / III / IV 等模块标题与顺序），并保持【逐模块西中交替】的双语能量话术习惯——每个 PARTE 先西语 (Español) 后用「(Traducción al Chino)」紧跟该模块中文翻译，再进入下一模块，绝不全文西语写完再统一翻译；语气、感染力、自然隐喻一律不变。
- 简言之：排盘只在后台帮你算准，前台呈现仍是你原汁原味、面向西语用户的那一套能量叙事，不得变成中文排盘报告。
""" + BAZI_DATA

_STYLE_ALIGNMENT_NOTE = """

## 【参考成稿风格补强（务必执行）】
- 参考优质成稿的写法，开头不要先铺太多理论，而是先用一句很清楚的“核心诊断”点破这张命盘最重要的矛盾或优势。
- 事业与财富必须落到现实语言：行业、岗位、工作方式、收入结构、合作边界、表达方式、执行节奏，而不是只讲五行术语。
- 如果谈过去、现在、未来，优先讲“这类能量会让你在现实里怎样表现、怎样卡住、怎样突破”，不要长篇解释概念。
- 月度推演必须写成“月份标题 + 该月重点 + 工作/钱/关系/风险/建议”的结构，尽量具体、可执行、可复盘，不要空泛教学。
- 结尾要给出清楚的判断和 1-2 个现实动作，避免重复鸡汤式总结；如果要引导私信，尽量放在对应主题后面，而不是最后泛泛一句。
"""

PROMPT_SINGLE = PROMPT_SINGLE + _BAZI_INJECT_NOTE
PROMPT_DOUBLE = PROMPT_DOUBLE + _BAZI_INJECT_NOTE
PROMPT_SINGLE = PROMPT_SINGLE + _STYLE_ALIGNMENT_NOTE

PROMPT_BRACELET = """
# System Instruction: 齐大师 - 八字配饰直播口播

你是齐大师，依据用户请求中的【程序排盘预校验】生成中文直播口播稿。

## 八字依据
- 只相信程序预校验中的四柱/三柱、日主、生肖、纳音、五行、大运和出生时间。
- 不自行改盘，不根据生日文字格式猜生肖，不补写未知时柱。
- 先从八字状态判断需要强化或平衡的能量，再推荐配饰。

## 输出要求
- 只输出中文直播口播稿，不输出排盘过程、英文、PARTE I/II/III/IV或系统说明。
- 先讲八字总判断，再讲事业、财富、感情或稳定防护中最相关的内容。
- 健康不作为手串推荐维度。
- 自然过渡到配饰，必须出现“主播此处拿出手串展示：”。
- 只推荐一条主手串，说明一到三种材质及其现实象征意义。
- 手串不能被说成保证发财、复合、转运、挡灾或治疗疾病。
- 如需具体月份或更精细的佩戴判断，引导用户补充出生时间私信咨询。
"""

PROMPT_FENGSHUI_LIVE = """
# System Instruction: 齐大师 - 中文直播风水知识口播脚本

## 角色
你是面向直播间的东方风水知识主播。
你的任务不是给个人测算，而是在开播时用一个公共风水知识点快速留住陌生观众。

## 核心原则
- 不要问出生年月，不要讲八字，不要讲复杂流程。
- 陌生用户进入后，必须在 5 秒内听懂今天直播在讲什么。
- 先给价值，再互动；先讲一个所有人都能检查的家居风水点，再引导观众留言或私信。
- 语气要像主播正在直接讲，不像文章、课程、提纲或备注。
- 内容要生活化：家门、镜子、厨房、卧室、沙发、杂物、光线、财位、办公桌。
- 不做恐吓，不说“必破财、必倒霉、一定影响婚姻”等绝对话术。

## 输出语言
- 默认输出中文直接口播稿。
- 如果用户指定西语，才输出西语。
- 不要输出“中文提示”“互动句”“私信引导”等拆开的备注板块，除非用户明确要求分块。

## 直播口播结构
1. 第 1 句必须是强开场，5 秒内讲清主题。
2. 立即给第一条公共知识，不要先问问题。
3. 围绕主题讲 3-5 个可检查细节，给观众马上能做的小动作。
4. 中间自然插入 1-2 个互动句，让观众检查家里某个位置并留言。
5. 结尾自然引导：如果想看自己家门、卧室、厨房或财位，可以私信发平面图/照片。

## 开场示范
你现在先看一下自己家的入户门。

有三件事，最容易让一个家的气场进不来，也最容易让人一回家就觉得累。

今天我先教你自己判断第一条。
"""


# ==========================================
# --- 2C. 中国传统算法系统指令 (PROMPT_BAZI) ---
#     内嵌四柱排盘参考数据，确保排盘准确而非凭空臆测
# ==========================================
PROMPT_BAZI = """
# System Instruction: 齐大师 (Maestro Qi) - 中国传统四柱八字正统排盘与论命系统（Bazi Clásico）

## 【最高铁律：体系纯正性】
- 本模块【只用中国传统四柱八字命理】，严格依据《穷通宝典》《三命通会》《滴天髓》《渊海子平》《子平真诠》《千里命稿》《神峰通考》等经典论命。
- 【绝对禁止】使用西方星座占星（白羊/天蝎/上升星座/行星相位/塔罗等）。
- 即使用户【未填写具体诉求】，也必须基于其生辰八字做全面综合论命，绝不允许跑偏成星座或泛泛性格鸡汤。
- 排盘必须严格依照下方【排盘参考数据】计算，禁止凭空臆造干支、藏干、十神。

## 0. 角色设定
* **Name**: 齐大师 (Maestro Qi)
* **Persona**: 沉稳、权威、慈悲，是一位精研经典典籍的正统命理学者。以对话口吻直接对客户说"你"，而非第三方旁观。
* **Target Audience**: 母语为西班牙语的群体（如拉美女性），需将深奥术语转化为可共鸣的自然隐喻。

## 【排盘参考数据（必须严格据此计算）】

### A. 天干五行阴阳
甲(阳木) 乙(阴木) 丙(阳火) 丁(阴火) 戊(阳土) 己(阴土) 庚(阳金) 辛(阴金) 壬(阳水) 癸(阴水)
阳干：甲丙戊庚壬；阴干：乙丁己辛癸。

### B. 地支五行·生肖·时辰·农历月
子(阳水/鼠/23-01/十一月) 丑(阴土/牛/01-03/十二月) 寅(阳木/虎/03-05/正月) 卯(阴木/兔/05-07/二月) 辰(阳土/龙/07-09/三月) 巳(阴火/蛇/09-11/四月) 午(阳火/马/11-13/五月) 未(阴土/羊/13-15/六月) 申(阳金/猴/15-17/七月) 酉(阴金/鸡/17-19/八月) 戌(阳土/狗/19-21/九月) 亥(阴水/猪/21-23/十月)

### C. 地支藏干表（本气60% 中气30% 余气10%）
子=癸 | 丑=己癸辛 | 寅=甲丙戊 | 卯=乙 | 辰=戊乙癸 | 巳=丙庚戊 | 午=丁己 | 未=己丁乙 | 申=庚壬戊 | 酉=辛 | 戌=戊辛丁 | 亥=壬甲

### D. 十神推导（以日干为我）
生我：阴阳同=偏印，阴阳异=正印；我生：同=食神，异=伤官；克我：同=七杀，异=正官；我克：同=偏财，异=正财；同我：同=比肩，异=劫财。
五行相生：木→火→土→金→水→木；相克：木→土→水→火→金→木。

### E. 天干五合 / 地支关系
五合：甲己合土、乙庚合金、丙辛合水、丁壬合木、戊癸合火。
六冲：子午、丑未、寅申、卯酉、辰戌、巳亥。
三合局：申子辰水、亥卯未木、寅午戌火、巳酉丑金。
三会局：寅卯辰东方木、巳午未南方火、申酉戌西方金、亥子丑北方水。
六合：子丑、寅亥、卯戌、辰酉、巳申、午未。
三刑：寅巳申、丑戌未、子卯、辰午酉亥自刑。
相害：子未、丑午、寅巳、卯辰、申亥、酉戌。

### F. 月柱·时柱起法
年上起月（口诀）：甲己之年丙作首，乙庚之岁戊为头，丙辛之年寻庚上，丁壬壬寅顺水流，戊癸之年甲寅求。（均以立春及各月节气为月份分界，非农历初一）
日上起时（五鼠遁）：甲己日起甲子时，乙庚日起丙子时，丙辛日起戊子时，丁壬日起庚子时，戊癸日起壬子时。子时按23:00分早晚子（23:00后归次日日柱）。

### G. 大运起排
阳男阴女顺排，阴男阳女逆排（阳年干=甲丙戊庚壬，阴年干=乙丁己辛癸）。以月柱为基准顺/逆推干支，每步管十年。起运岁数≈出生日到节气天数÷3。未起运前以月柱为小运。

### H. 调候用神原则（穷通宝典）
论命首重调候：夏火旺须水调候，冬水旺须火调候。如：甲木生寅月先丙后癸；甲木生酉月先丁制金再丙暖木；庚金生子月必用丙火解冻。调候用神受克或缺失，格局再好也多阻碍。

### I. 常用神煞
天乙贵人：甲戊庚见丑未，乙己见子申，丙丁见亥酉，壬癸见卯巳，庚辛见寅午。
桃花：申子辰在酉，寅午戌在卯，巳酉丑在午，亥卯未在子。
驿马：申子辰在寅，寅午戌在申，巳酉丑在亥，亥卯未在巳。
华盖：申子辰在辰，寅午戌在戌，巳酉丑在丑，亥卯未在未。

### J. 宫位论法（千里命稿）
年柱=祖上父母/1-16岁；月柱=父母兄弟工作/17-32岁；日柱=自己(日干)配偶(日支)/33-48岁；时柱=子女晚年/49岁后。

## 【核心要求：直播专用首发模块控制】
### 📜 PARTE 0: 直播总体简单评价（直播快评模式专用）
1. 只用中文，严禁夹杂西语。
2. 1000字以内，一句一段、段间空行，直白通俗便于翻译。
3. 开头点明【生肖】和【纳音（如炉中火命、大林木命）】，必须引用【程序排盘预校验】里的“生肖”和“年柱纳音”，不得根据生日字符串格式自行猜生肖；简单说核心运势走向，针对核心诉求白话点拨。不要只在结尾泛泛引导私信；应在事业、财富、情感等具体判断后，顺手加入对应私信引导。

## 输出结构（完整深度模式）
**【语言 · 分段交替】**：采用【逐模块西中交替】格式，禁止全文西语写完再统一翻译。每个 PARTE 先输出纯正流畅、富感染力的西班牙语 (Español)，紧接着用「(Traducción al Chino)」给出该模块 1:1 完整中文翻译，再进入下一 PARTE 重复"先西后中"，严禁缺段。
**【字数】**：每模块深度展开，单语言总字数不低于 1500 字。所有论断尽量引用经典出处（如"据《滴天髓》得令为身旺之基…"）。

### 🀄 PARTE I: EL TRAZADO DEL DESTINO (正统排盘)
- 严格据上方参考数据排出四柱（年/月/日/时柱天干地支），列出每柱十神与藏干，以表格清晰呈现。
- 注明日主、判断旺衰（得令/得地/得势，参考《滴天髓》），定身强身弱。
- 排出大运（方向、起运岁、各步干支）。
- 若时辰未知，只做年月日六字分析并说明。

### 🔮 PARTE II: ANÁLISIS PROFUNDO (格局·用神·五行综合论命)
- 统计五行力量分布，定喜用神与忌神（调候+扶抑+通关，参考《穷通宝典》《子平真诠》）。
- 判定格局及高低成败。结合十神与宫位，剖析事业、财富、感情婚姻、健康。此部分不少于 3000 字。

### 🚀 PARTE III: CRONOGRAMA（月度流年细推）
- 分析当前所处大运吉凶，再从【月度测算区间】起始月份开始逐月推演（结合流年干支与原局/大运的冲合刑害），每月独立小标题，不少于 2000 字。

### 🕯️ PARTE IV: VERIFICACIÓN Y ALQUIMIA (历史校准·开运建议·手串)
- 【历史校准】据大运流年，提出 3-5 个该人"已发生"的关键事件时间段与性质，请用户验证。
- 给出 1 个不流于表面的专属开运仪式。
- 结合五行喜忌与诉求，推荐 1 条手串：1.爱情(冰粉/珍珠)；2.财富(黄阿赛/黄虎眼)；3.纯净(白幽灵)；4.抵御厄运(金运/黑发晶/茶水晶)；5.全面提升(多宝)。
- 附终极哲理赠言。

## 严格约束
- 涉疾病声明"形而上学不替代医学诊断"，涉财务提醒理性决策；语气中性建设性，不恐吓。
- 禁止用拼音替代十神。结尾提示"命理仅供参考，人生在于自身努力与选择"。
- 若一次输出超长，请在结尾提示"内容过多，请点击追问以获取余下部分"。
"""

PROMPT_BAZI = PROMPT_BAZI + _STYLE_ALIGNMENT_NOTE

LIVE_QUICK_REPORT_CONSTRAINT = """

⚠️【重要提醒：直播快速简评模式｜统一口播规则】：
当前由直播快速引擎驱动，只输出直播口播稿，严禁输出 PARTE I/II/III/IV，严禁输出完整深度报告。

【命理计算边界】
- 不重新发明排盘，不改变程序排盘预校验结果。
- 必须以用户请求中的【程序排盘预校验】、四柱/三柱、日主、生肖、年柱纳音、五行旺衰、大运预排和核心诉求为依据。
- 如果程序提示时柱未知，这是内部边界，不要在开头输出技术性免责声明；只在讲“具体月份、具体应期、哪月换工作/签约/守财”时自然说明必须补出生时间。
- 不得在没有具体出生时间时给出“几月到几月该做什么”的确定建议。

【直播目标】
- 输出中文，900-1300字左右，一句一段，段间空行，像主播正在直播间讲。
- 让拉美用户听得懂：少讲术语，多讲“这股气在现实里怎么表现”。
- 中文必须为 TikTok 西语语音翻译服务：句子要短，主语要清楚，少用成语、歇后语、网络词和只有中文才顺的比喻。
- 每句话尽量只表达一个意思，避免“既……又……但是……”连续绕太长；不要用“格局打开、扛起来、压一头、绷着、破局”这类机器翻译容易变怪的表达。
- 只保留少量必要术语，例如“财星主导”“官星主导”“印星主导”“食伤主导”“比劫主导”和“XX大运”。每个术语首次出现时，必须在紧接的一句中用白话解释。后文不要重复解释，也不要继续增加术语。
- 其他表达一律优先用可直译成西语的短句。每句尽量不超过一个判断和一个现实影响。
- 但不能写成普通心理咨询或职场建议；每个重要判断都要先有八字来源，再落到现实。
- 禁止不同命盘都写成“压力大、责任重、自己硬扛”的模板；只有官杀、土重、财官压身、火土过旺或诉求明确指向压力时，才把压力当核心。
- 禁止夸张承诺和恐吓，不说必发财、必破财、必有灾。
- 本模式不推荐手串，除非用户明确问手串。

【术语翻译规则】
- “十神、月令、藏干、合冲刑害、喜用忌神”等内容只用于内部判断。除下方允许保留的少量术语外，不要把这些术语写进直播稿。
- 禁止直接输出“有根、透出、藏干、得令、格局清纯、身弱不担财”这类海外用户难懂的说法。
- 必须改成可口播的白话：
  有根 = 底下还有支撑，不是完全没力量。
  透出 = 这股能量在表面，别人容易看见。
  藏干 = 命盘底下还藏着这股气。
  得令 = 出生季节对这股气有利。
  身弱不担财 = 机会和钱会来，但身体、节奏或判断未必接得稳。
- 如果使用“财星主导”等主轴词，首次出现后只用一句白话解释，马上转到钱、工作、关系或行动。不要讲成课堂。
- 如果使用“XX大运”，首次出现后必须紧接一句解释：“这是她目前所处的十年人生阶段。”后文直接说“这十年”或“这个阶段”。

【命格主轴规则】
- 必须判断这个八字的“命格主轴/人生结构”，但不要输出复杂古籍术语堆叠。
- 如果传统格局能清楚判断，可以说“这张盘更像是财星主导、官星主导、印星主导、食伤主导、比劫主导，或财官/印食/食伤生财这类复合结构”。
- 如果时辰不足导致不能定死格局，要说“按目前年月日三柱看，更像是……主导”，不要装作完整四柱已经确定。
- 命格主轴必须翻译成海外用户能懂的话：
  财星主导 = 人生容易围绕资源、钱、交易、客户和现实选择展开。
  官星主导 = 人生容易被工作要求、身份责任、关系承诺和外界标准推动。
  印星主导 = 人生更靠学习、专业、证书、经验、贵人和保护力量起势。
  食伤主导 = 人生更靠表达、内容、技术输出、销售、人气和创造力打开。
  比劫主导 = 人生更靠自己、竞争、朋友同辈、合伙关系和独立行动推动。
- 命格主轴必须和当前年龄、大运阶段连起来讲。用“机会开始增加、方向正在改变、需要减少旧负担、正在积累、正在转型、把能力变成稳定收入”等直白短句描述。
- 禁止只说“是什么格”不解释走向；必须说“这个结构到了现在这个年纪，会把重点推向哪里”。

【输出结构】
只输出一个标题：
### 📜 PARTE 0: 直播总体简单评价

标题后按以下 4 个小标题输出，标题照抄：
【1. 命格主轴与五行能量】
【2. 过去状态回顾】
【3. 现在的障碍】
【4. 2026-2027流年前瞻】

【1. 命格主轴与五行能量】
- 开头先点明生肖和纳音命格，例如“她是属猴，纳音是剑锋金命”。必须引用【程序排盘预校验】里的“生肖”和“年柱纳音”，不得根据生日字符串格式自行猜。
- 生肖和纳音只作为入口，不展开生肖性格鸡汤。
- 接着必须给命格主轴判断，例如：“这张盘按目前资料看，更像是财星和食伤一起推动的结构。”然后马上白话解释：“也就是钱、客户、表达和行动会一起影响她的人生选择。”
- 命格主轴不能超过3句话，不能讲成课堂；重点是让观众听懂“这个人靠什么起势，又容易被什么拖住”。
- 先给一个五行比例感，顺序固定为木、火、土、金、水，例如：木15%，火30%，土25%，金10%，水20%。
- 比例不是科学测量，但必须体现相对强弱；明显多写25%-35%，明显少写5%-15%，中等写15%-25%。
- 不要把五行全部长篇解释。比例之后，只挑“最多的1-2个”和“最少/最受压的1个”解释。
- 解释必须简单：木是成长和计划，火是行动和曝光，土是稳定和现实，金是判断和边界，水是头脑、流动和钱的流动。
- 不能说“水有根但不强”。要说：“水不是完全没有，底下还有一点支撑，所以她有想法和机会感；但水不够稳，机会来了以后容易流动不顺，钱和信息接得住但不一定守得住。”

【2. 过去状态回顾】
- 用五行回顾过去，不编具体事件。
- 必须同时讲正面和负面。
- 正面讲过去靠哪股气拿到机会：行动力、表达、人缘、学习、专业、执行、适应力、资源整合。
- 负面讲同一股气用过头以后造成什么：急、散、慢、卡、守不住钱、边界弱、合作消耗、计划太多落地少。
- 语气像“这几年你大概率会有这种感受”，不要说绝对事件。

【3. 现在的障碍】
- 这是直播转化核心，要讲得具体、有命理感、有痛点。
- 必须告诉用户现在最大的2-3个障碍，每个障碍都先说命盘信号，再说现实卡点。
- 障碍不能都写压力。要按五行差异写：
  木过多：想升级、想换方向，但路线容易长出太多枝。
  木太少：想改变，却缺持续计划和学习线。
  火过多：机会、人气、行动强，但急着回应、急着证明，容易冲动决定。
  火太少：心里知道要动，但曝光、表达、主动争取偏慢。
  土过多：现实牵绊重，钱、家、稳定感会把选择压住。
  土太少：想法不少，但落地、坚持和长期结构不足。
  金过多：标准高、判断强，但容易过度挑剔或切得太快。
  金太少：边界不够，容易被别人带节奏，合作里吃亏。
  水过多：机会感和想法多，但方向散、钱流动快。
  水太少：信息流、现金流、贵人流动不顺，遇到变化容易紧。
- 必须给一句清楚结论：“她现在不是……而是……”

【4. 2026-2027流年前瞻】
- 分别以2026年、2027年组织短段落；每一年都必须覆盖事业、财富、感情、健康，不能两年合讲后漏掉某一维度。保持全文900-1300字要求，通过减少重复解释为流年前瞻留出篇幅。
- 必须先讲十年大运：从【大运预排】里找出当前年份所在的大运，写清楚“她现在走的是XX大运，大约从XXXX年到XXXX年。这是她目前所处的十年人生阶段。”这是“大运”首次出现时的白话解释。
- 必须判断当前是否处在阶段交接。如果当前年份距离某步大运开始或结束在1年内，就说“现在接近两个十年阶段的交接”；如果在中段，就说“这个十年阶段已经进入中段，影响会更明显”；如果接近尾声，就说“这个十年阶段接近结束，需要决定保留什么、放下什么”。
- 必须把命格主轴和大运连起来判断当前年纪的走向，例如：“财星主导的人，走到这步运，重点不是有没有机会，而是钱从哪里来、又从哪里漏掉。”
- 当前年纪走向必须具体到事业和财富：是适合把技能变现、从稳定工作转向副业、靠客户资源起势、重新建立边界、还是先守住现金和合作关系。
- 不要把每个人都写成“2026机会更强，2027适合长期规划”。
- 两年使用相同分析标准。内部结合丙午、丁未与日主的关系、出生季节、地支内部力量、当前十年阶段及实际存在的合冲刑害来判断。对外只说具体命盘信号造成的现实影响，不罗列术语。每年至少点明一个此人具体命盘依据；没有成立的关系不得编造，不能见合就说一定改变，见冲就说一定有灾。
- 五行的生活化解释不能代替十神判断，不能把火一律解释为曝光、土一律解释为稳定。程序未提供确定的旺衰和喜忌时，须结合已有资料谨慎判断，不得把模型推断冒充程序计算结果。最终口播只给简短结论，不展示推导过程。
- 每年事业讲工作机会或阻力及应对；财富讲收入来源或支出风险及应对。职业未提供时不要擅自假定对方经商、做内容或出售个人服务。
- 每年感情讲关系中的支持或矛盾、相处重点与建议，结合日支及相关十神和流年的联系。关系状态未知时不假定已婚、单身或有第三者；不得断言结婚、出轨、分手必然发生。
- 每年健康只讲可用于自我观察的作息、精力、休息与生活习惯提醒。五行与身体的对应只能作为传统文化解释，不能据此判断器官疾病、炎症、发病时间或医疗风险；有持续不适建议就医，不以手串或风水代替医疗。
- 四个维度各用简短句子给出重点；正负面按资料支持程度表达，不为了凑齐而编事件。相同年度可以事业有机会但关系需磨合，不强行把所有维度归为整体吉或凶。
- 比较两年各维度的变化依据，允许两年相近、2027更活跃或资料不足以分高下；不得预设2026上升、2027稳定，也不得为制造差异硬判相反结论。
- 不得给具体月份建议。必须说明“月份应期要看出生时辰”，因为时柱会改变机会、破财、合作、贵人和行动窗口。
- 私信/WhatsApp钩子不要像功能说明，要像关键缺口：
  “她这两年不是没有财气，关键是财来的时候，会不会同时带出漏财点。到底是合作漏财、冲动花钱、家里花钱，还是选错方向，这个要看时柱。补具体出生时间私信我，我才能把2026-2027拆到月份。”
  “直播里我只能看大方向，不能乱定月份；如果她想知道哪几个月机会最明显、哪几个月最容易破财或签错承诺，需要把几点几分，或者至少几点到几点出生补给我。”
- 最后一段加入符合当前五行偏性的居家风水小建议，具体到哪里少放什么、哪里可以放什么；只说生活调整，不承诺转运发财。
- 风水建议按命盘所需元素选1-2条即可：
  需要木：东方、书桌或学习工作区保持通畅，可放健康绿植、木质物件；少堆旧纸箱和枯萎植物。
  需要火：南方、客厅曝光区可用暖光、红色小点缀或明亮摆件；少放太多黑灰冷色和厚重遮挡。
  需要土：房屋中心、餐厅或稳定区保持干净，可放陶瓷、方形收纳、米黄土色小物；少放杂乱移动物。
  需要金：西方、西北方或办公区加强整洁和边界，可放金属色、白色、圆形或收纳类物件；少放破损物品。
  需要水：北方、入口动线或工作灵感区保持流动，可放蓝黑色小物、玻璃杯、流线形摆件；少放过强灯光和红色杂物。
  某元素过旺：不要继续在对应方位堆同类颜色、材质和物件，而是用命盘所需元素做平衡。

【互动点写法】
- 最多1句，放在五行或障碍段中间，不要放在最后凑数。
- 互动句要让直播间的人对照自己，例如：“直播间注意听，如果你的盘也是火很重，最怕的不是没机会，而是机会一热就先冲出去，钱还没稳住，人先累了。”

【禁止高频套话】
- 禁止输出：“你过去不是靠运气过日子的人”“靠自己硬撑”“适合有结果有标准有反馈的事情”“不适合混乱反复没有边界的环境”“你不是没能力”“方向收窄再加速”。
- 禁止结尾只写“想知道更多私信我”。
"""

# 直播请求使用独立的八字规则和直播解说规则。
# 保留排盘参考数据，确保直播模型不会脱离程序预校验自行改盘。
LIVE_BAZI_RULES = BAZI_DATA + """

## 【直播模式八字计算边界】
- 以用户请求中的【程序排盘预校验】为最终排盘依据。
- 不根据生日字符串重新猜生肖，不自行改写年柱、月柱、日柱、时柱或大运。
- 如果程序只提供年月日三柱，不能补写未知时柱，也不能据此确定具体月份应期。
- 五行判断必须综合出生季节、天干地支、地支藏气和大运，不以单个字直接断定旺衰。
- 2026、2027的判断必须先结合原局五行和当前大运，再分别落到事业、财富、感情与健康提醒。
- 具体月份、合作窗口、破财窗口和精确应期，需要出生时间；没有时辰时只讲年度和阶段方向。
"""

LIVE_ENGINE_BASE = """
你是齐大师，负责根据用户请求中的【程序排盘预校验】结果，生成中文直播口播稿。

只相信程序预校验给出的四柱、生肖、纳音、五行、大运和出生时间信息，不自行改盘。
最终只输出用户当前模式要求的正文，不输出分析过程、系统说明、英文翻译或额外备注。
中文要适合被 TikTok 西语语音翻译：句子短，主语清楚，少用生僻术语。
直播稿只保留“财星主导”等命格主轴词和“XX大运”等少量必要术语。术语首次出现后，紧接一句白话解释。其余命理依据只用于内部判断，输出时改成容易直译成西语的短句。
"""

# --- 3. 初始化 Session State ---
if "main_report" not in st.session_state:
    st.session_state.main_report = ""
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_prompt_type" not in st.session_state:
    st.session_state.current_prompt_type = "single"
if "last_name" not in st.session_state:
    st.session_state.last_name = ""
if "last_birth" not in st.session_state:
    st.session_state.last_birth = ""
if "last_save_ok" not in st.session_state:
    st.session_state.last_save_ok = False
if "last_save_error" not in st.session_state:
    st.session_state.last_save_error = ""
if "enable_copy_review" not in st.session_state:
    st.session_state.enable_copy_review = True
if "last_review_status" not in st.session_state:
    st.session_state.last_review_status = ""

# --- 4. 数据持久化：优先 Google Sheets，SQLite 仅作本地兜底 ---
RECORD_COLUMNS = ["id", "name", "birth_info", "report", "history", "date", "ptype"]
LOCAL_DB_PATH = "fortunes.db"


def get_config(section, key, env_name, default=""):
    """Read deployment config without hard-coding secrets in source code."""
    value = None
    try:
        section_data = st.secrets.get(section, {})
        if hasattr(section_data, "get"):
            value = section_data.get(key)
    except Exception:
        value = None
    return os.environ.get(env_name, value if value not in (None, "") else default)


def has_non_ascii(value):
    try:
        str(value).encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def validate_api_config(api_key, base_url, model, label):
    if not api_key:
        return f"请先在 Streamlit Secrets 里填写{label} API Key。"

    if has_non_ascii(api_key):
        return f"{label} API Key 里含有中文或非英文字符。请不要填写 `sk-你的APIKey` 这种占位符，要换成平台给你的真实 key。"

    if any(placeholder in api_key.lower() for placeholder in ["your", "api_key", "apikey", "placeholder"]):
        return f"{label} API Key 看起来还是示例占位符，请换成真实 key。"

    if has_non_ascii(base_url):
        return f"{label} Base URL 里含有中文或非英文字符，请填写真实接口地址。"

    if has_non_ascii(model):
        return f"{label}模型名称里含有中文或非英文字符，请填写真实模型名。"

    return ""


def get_api_engines(primary_key, primary_url, primary_model, mode="live"):
    """Build an ordered API pool. Comma/newline separated backup keys stay outside source code."""
    engines = [("首选接口", primary_key, primary_url, primary_model)]
    prefix = "OPENAI_LIVE" if mode == "live" else "OPENAI_FULL"
    section_name = "openai_live" if mode == "live" else "openai_full"
    backup_keys = get_config(section_name, "api_keys", f"{prefix}_API_KEYS", "")
    backup_urls = get_config(section_name, "base_urls", f"{prefix}_BASE_URLS", "")
    backup_models = get_config(section_name, "models", f"{prefix}_MODELS", "")
    if isinstance(backup_keys, (list, tuple)):
        backup_keys = ",".join(str(item) for item in backup_keys)
    if isinstance(backup_urls, (list, tuple)):
        backup_urls = ",".join(str(item) for item in backup_urls)
    if isinstance(backup_models, (list, tuple)):
        backup_models = ",".join(str(item) for item in backup_models)
    keys = [item.strip() for item in backup_keys.replace("\n", ",").split(",") if item.strip()]
    urls = [item.strip() for item in backup_urls.replace("\n", ",").split(",") if item.strip()]
    models = [item.strip() for item in backup_models.replace("\n", ",").split(",") if item.strip()]
    for index, key in enumerate(keys):
        url = urls[index] if index < len(urls) else primary_url
        model = models[index] if index < len(models) else primary_model
        if (key, url, model) != (primary_key, primary_url, primary_model):
            engines.append((f"备用接口 {index + 1}", key, url, model))
    return engines


def format_generation_error(error):
    text = str(error)
    lower_text = text.lower()
    if "524" in lower_text or "proxy read timeout" in lower_text or "took too long" in lower_text:
        return (
            "推演超时：当前 API 代理要求 120 秒内完成返回，但这次模型生成太慢或内容太长。"
            "请优先切换到更快的快速模型，或缩短本次输出；如果是完整版深度报告，建议先生成核心分析，再用追问继续补后半段。"
        )
    return f"推演错误：{error}"


def review_copy_text(raw_text, primary_engine, fallback_engine=None, context_label="报告"):
    raw_text = str(raw_text or "").strip()
    if not raw_text:
        return raw_text, False, "空内容，跳过复核。"

    review_prompt = """
你是专业中文文案复核编辑。
任务：只做语法、病句、重复、标点、口播顺滑度、个别生硬表达的修正。
严格禁止：
- 改变命理结论、五行判断、年份月份、职业判断、事业财富情感结论
- 新增事实、删掉关键建议、改写成更夸张的说法
- 改变标题层级、段落结构、模块顺序
- 输出说明、点评、修改清单
如果原文已经很好，只做最小幅度润色。
只输出修订后的正文，不要附加解释。
"""

    engines = [primary_engine]
    if fallback_engine and fallback_engine != primary_engine:
        engines.append(fallback_engine)

    last_error = ""
    for engine_label, api_key, base_url, model in engines:
        if not api_key or not base_url or not model:
            continue
        try:
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=300.0)
            max_tokens = min(2200, max(900, int(len(raw_text) * 0.6)))
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": review_prompt},
                    {
                        "role": "user",
                        "content": f"请复核并润色下面这份【{context_label}】文案，只修语法和表达，不改结论：\n\n{raw_text}",
                    },
                ],
                stream=False,
                temperature=0.1,
                max_tokens=max_tokens,
            )
            revised = resp.choices[0].message.content.strip()
            if revised:
                return revised, True, f"已完成{engine_label}文案复核。"
        except Exception as e:
            last_error = str(e)
            continue

    return raw_text, False, f"文案复核失败，已保留原文。{last_error}"


def add_months(dt, months):
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    return dt.replace(year=year, month=month, day=1)


def build_month_forecast_note():
    start_dt = datetime.datetime.now().replace(day=1)
    end_dt = add_months(start_dt, 12)
    labels = []
    cursor = start_dt
    for _ in range(13):
        labels.append(f"{cursor.year}年{cursor.month}月")
        cursor = add_months(cursor, 1)
    return (
        f"起始月份：{start_dt.year}年{start_dt.month}月\n"
        f"结束月份：{end_dt.year}年{end_dt.month}月\n"
        f"逐月顺序：{'、'.join(labels)}\n"
        "说明：必须从起始月份写到结束月份，共13个月，每个月独立分析，不要跳月，不要固定写死 2026。"
    )


def normalize_record_identity(name, birth, ptype):
    name = str(name or "").strip()
    birth = str(birth or "").strip()
    ptype = str(ptype or "single").strip()
    return name, birth, ptype


def validate_record_identity(name, birth, ptype):
    name, birth, ptype = normalize_record_identity(name, birth, ptype)
    if not name:
        return "请先填写姓名/代称，否则历史档案无法识别是谁的测算。"
    if not birth:
        return "请先填写生辰/生日信息，否则历史档案无法识别是哪一次测算。"
    return ""


def set_current_record_identity(name, birth, ptype):
    name, birth, ptype = normalize_record_identity(name, birth, ptype)
    st.session_state.last_name = name
    st.session_state.last_birth = birth
    st.session_state.current_prompt_type = ptype


def parse_solar_birth_datetime(raw):
    raw = str(raw or "").strip()
    if not raw:
        return None

    text = (
        raw.replace("年", "-")
        .replace("月", "-")
        .replace("日", " ")
        .replace("/", "-")
        .replace(".", "-")
        .replace("：", ":")
        .strip()
    )

    compact = re.match(
        r"^\s*(\d{4})(\d{2})(\d{2})(?:\s*(\d{1,2})(?::?(\d{2}))?)?\s*$",
        raw,
    )
    dashed = re.match(
        r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2})(?::(\d{1,2}))?)?\s*$",
        text,
    )
    match = compact or dashed
    if not match:
        return None

    year, month, day = [int(match.group(i)) for i in range(1, 4)]
    has_time = match.group(4) is not None
    hour = int(match.group(4)) if has_time else 12
    minute = int(match.group(5) or 0) if has_time else 0

    try:
        datetime.datetime(year, month, day, hour, minute)
    except ValueError:
        return None

    return {
        "year": year,
        "month": month,
        "day": day,
        "hour": hour,
        "minute": minute,
        "has_time": has_time,
    }


def format_hide_gan(values):
    if not values:
        return "无"
    return "、".join([str(v) for v in values if str(v).strip()]) or "无"


def build_bazi_precheck(name, gender, birth, place="", label="命主"):
    if Solar is None:
        return "【程序排盘预校验】未启用：缺少 lunar-python 依赖。请检查 requirements.txt 是否已包含 lunar-python==1.4.8。"

    parsed = parse_solar_birth_datetime(birth)
    if not parsed:
        return (
            "【程序排盘预校验】未启用：当前生辰格式无法被程序稳定识别。\n"
            "请优先让用户填写阳历格式，如 1988-05-17 08:30 或 19880517 0830。\n"
            "在未取得确定四柱前，不得凭空臆造年柱、月柱、日柱、时柱、大运起运岁数。"
        )

    solar = Solar.fromYmdHms(
        parsed["year"],
        parsed["month"],
        parsed["day"],
        parsed["hour"],
        parsed["minute"],
        0,
    )
    lunar = solar.getLunar()
    eight_char = lunar.getEightChar()
    year_ganzhi = eight_char.getYear()
    year_branch, zodiac = zodiac_from_ganzhi(year_ganzhi)
    year_nayin = eight_char.getYearNaYin()
    gender_value = 1 if "男" in str(gender) or "Hombre" in str(gender) else 0
    yun = eight_char.getYun(gender_value)

    pillars = [
        ("年柱", year_ganzhi, eight_char.getYearShiShenGan(), eight_char.getYearHideGan(), year_nayin, eight_char.getYearXunKong()),
        ("月柱", eight_char.getMonth(), eight_char.getMonthShiShenGan(), eight_char.getMonthHideGan(), eight_char.getMonthNaYin(), eight_char.getMonthXunKong()),
        ("日柱", eight_char.getDay(), "日主", eight_char.getDayHideGan(), eight_char.getDayNaYin(), eight_char.getDayXunKong()),
    ]
    if parsed["has_time"]:
        pillars.append(("时柱", eight_char.getTime(), eight_char.getTimeShiShenGan(), eight_char.getTimeHideGan(), eight_char.getTimeNaYin(), eight_char.getTimeXunKong()))

    pillar_lines = []
    for title, ganzhi, shishen, hide_gan, nayin, xunkong in pillars:
        pillar_lines.append(f"- {title}：{ganzhi}｜十神：{shishen}｜藏干：{format_hide_gan(hide_gan)}｜纳音：{nayin}｜旬空：{xunkong}")

    dayun_lines = []
    for dayun in yun.getDaYun()[:9]:
        ganzhi = dayun.getGanZhi()
        if not ganzhi:
            ganzhi = "起运前小运"
        dayun_lines.append(
            f"- {dayun.getStartAge()}-{dayun.getEndAge()}岁（{dayun.getStartYear()}-{dayun.getEndYear()}）：{ganzhi}"
        )

    if parsed["has_time"]:
        time_note = f"{parsed['hour']:02d}:{parsed['minute']:02d}"
        pillars_summary = f"四柱：{eight_char}"
        detail_title = "四柱明细"
        dayun_note = "以上四柱与大运为程序确定性预排结果。"
    else:
        time_note = "未提供具体时辰；程序仅预排年月日三柱，时柱未知，不得强推"
        pillars_summary = (
            "年月日三柱："
            f"{eight_char.getYear()} {eight_char.getMonth()} {eight_char.getDay()}｜时柱：未知"
        )
        detail_title = "年月日三柱明细"
        dayun_note = (
            "以上年月日三柱为程序确定性预排结果；因缺少出生时辰，时柱、子女晚年宫、时柱神煞、"
            "部分起运细节只能做近似参考，不得当作确定结论。"
        )

    return f"""【程序排盘预校验｜{label}】
姓名/代称：{name or label}
输入生辰：{birth}
识别为阳历：{parsed['year']:04d}-{parsed['month']:02d}-{parsed['day']:02d} {time_note}
出生地：{place or "未提供"}（提示：当前程序尚未做经纬度真太阳时校正；若出生时间接近时辰交界，需人工复核）
性别：{gender}
农历：{lunar}
生肖：{zodiac}（年柱地支：{year_branch or "未知"}）｜年柱纳音：{year_nayin}
{pillars_summary}
日主：{eight_char.getDayGan()}
胎元：{eight_char.getTaiYuan()}｜命宫：{eight_char.getMingGong()}｜身宫：{eight_char.getShenGong()}
大运方向：{"顺排" if yun.isForward() else "逆排"}
起运：{yun.getStartYear()}年{yun.getStartMonth()}个月{yun.getStartDay()}天{yun.getStartHour()}小时

{detail_title}：
{chr(10).join(pillar_lines)}

大运预排：
{chr(10).join(dayun_lines)}

【模型约束】
{dayun_note}
分析时必须以程序预排为准；如与自行推算不一致，以程序预排为准，并仅提示用户在节气交界、时辰交界或真太阳时情况下需人工复核。
"""


def join_prechecks(*items):
    prechecks = [item for item in items if item]
    return "\n\n".join(prechecks)


def get_gsheets_worksheet():
    return get_config("storage", "worksheet", "GSHEETS_WORKSHEET", "records")


def has_gsheets_secrets():
    try:
        connections = st.secrets.get("connections", {})
        return bool(connections.get("gsheets")) and GSheetsConnection is not None
    except Exception:
        return False


def get_gsheets_connection():
    if not has_gsheets_secrets():
        return None
    try:
        return st.connection("gsheets", type=GSheetsConnection)
    except Exception as e:
        st.warning(f"Google Sheets 连接失败，已临时切换到本地 SQLite：{e}")
        return None


def normalize_records_df(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=RECORD_COLUMNS)

    df = df.copy()
    for col in RECORD_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[RECORD_COLUMNS].fillna("")
    df["id"] = pd.to_numeric(df["id"], errors="coerce").fillna(0).astype(int)
    return df


@st.cache_data(ttl=30, max_entries=1, show_spinner=False)
def read_gsheets_records(worksheet):
    """Avoid re-reading the whole archive on every Streamlit rerun."""
    gsheets = get_gsheets_connection()
    if not gsheets:
        return pd.DataFrame(columns=RECORD_COLUMNS)
    return normalize_records_df(gsheets.read(worksheet=worksheet, ttl=0))


def history_to_text(history):
    return json.dumps(history or [], ensure_ascii=False)


def history_from_text(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        try:
            parsed = ast.literal_eval(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, SyntaxError):
            return []


def init_db():
    conn = sqlite3.connect(LOCAL_DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            birth_info TEXT,
            report TEXT,
            history TEXT,
            date TEXT
        )
    ''')
    # 兼容老库：若无 ptype 列则补加（记录测算类型 single/double/bazi）
    c.execute("PRAGMA table_info(records)")
    cols = [row[1] for row in c.fetchall()]
    if "ptype" not in cols:
        c.execute("ALTER TABLE records ADD COLUMN ptype TEXT DEFAULT 'single'")
    conn.commit()
    conn.close()

init_db()

def load_records_from_sqlite():
    conn = sqlite3.connect(LOCAL_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, birth_info, report, history, date, ptype FROM records ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "name": row[1],
            "birth_info": row[2],
            "report": row[3],
            "history": row[4],
            "date": row[5],
            "ptype": row[6],
        }
        for row in rows
    ]


def load_records():
    gsheets = get_gsheets_connection()
    if gsheets:
        try:
            df = read_gsheets_records(get_gsheets_worksheet())
            df = df.sort_values("id", ascending=False)
            cloud_records = df.to_dict("records")
            local_records = load_records_from_sqlite()
            seen = {
                (
                    str(row.get("name", "")),
                    str(row.get("birth_info", "")),
                    str(row.get("ptype", "")),
                )
                for row in cloud_records
            }
            local_only = []
            for row in local_records:
                key = (
                    str(row.get("name", "")),
                    str(row.get("birth_info", "")),
                    str(row.get("ptype", "")),
                )
                if key not in seen and str(row.get("report", "")).strip():
                    row = dict(row)
                    row["id"] = f"local-{row.get('id')}"
                    local_only.append(row)
            return local_only + cloud_records
        except Exception as e:
            st.warning(f"读取云端档案失败，已临时读取本地 SQLite：{e}")
    return load_records_from_sqlite()


def load_record_by_id(record_id):
    records = load_records()
    for record in records:
        if str(record.get("id")) == str(record_id):
            return record
    return None


def restore_record_to_session(record):
    if not record:
        return False

    st.session_state.main_report = record.get("report", "")
    st.session_state.chat_history = history_from_text(record.get("history", ""))
    st.session_state.last_name = str(record.get("name", "") or "")
    st.session_state.last_birth = str(record.get("birth_info", "") or "")

    saved_ptype = record.get("ptype") or None
    if saved_ptype in ("single", "double", "bazi", "bracelet", "fengshui"):
        st.session_state.current_prompt_type = saved_ptype
    elif "&" in st.session_state.last_name:
        st.session_state.current_prompt_type = "double"
    else:
        st.session_state.current_prompt_type = "single"

    st.session_state.last_save_ok = True
    st.session_state.last_save_error = ""
    return True


def save_to_sqlite(name, birth, report, history, ptype="single"):
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        c = conn.cursor()
        history_str = history_to_text(history)
        date_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        c.execute("SELECT id FROM records WHERE name=? AND birth_info=?", (str(name), str(birth)))
        row = c.fetchone()

        if row:
            c.execute("UPDATE records SET report=?, history=?, date=?, ptype=? WHERE id=?",
                      (str(report), history_str, date_now, str(ptype), row[0]))
        else:
            c.execute("INSERT INTO records (name, birth_info, report, history, date, ptype) VALUES (?, ?, ?, ?, ?, ?)",
                      (str(name), str(birth), str(report), history_str, date_now, str(ptype)))

        conn.commit()
        conn.close()
        st.toast("⚡ 齐大师永久记忆已同步！")
        return True
    except Exception as e:
        st.error(f"数据库写入失败: {e}")
        return False


def save_to_gsheets(name, birth, report, history, ptype="single"):
    gsheets = get_gsheets_connection()
    if not gsheets:
        return False

    try:
        worksheet = get_gsheets_worksheet()
        df = normalize_records_df(gsheets.read(worksheet=worksheet, ttl=0))
        date_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        name, birth, ptype = normalize_record_identity(name, birth, ptype)
        history_str = history_to_text(history)

        matched = (df["name"].astype(str) == name) & (df["birth_info"].astype(str) == birth)
        if matched.any():
            idx = df.index[matched][0]
            if not int(df.loc[idx, "id"] or 0):
                df.loc[idx, "id"] = int(df["id"].max()) + 1 if not df.empty else 1
            df.loc[idx, ["name", "birth_info", "report", "history", "date", "ptype"]] = [
                name,
                birth,
                str(report),
                history_str,
                date_now,
                ptype,
            ]
        else:
            next_id = int(df["id"].max()) + 1 if not df.empty else 1
            df = pd.concat(
                [
                    df,
                    pd.DataFrame(
                        [
                            {
                                "id": next_id,
                                "name": name,
                                "birth_info": birth,
                                "report": str(report),
                                "history": history_str,
                                "date": date_now,
                                "ptype": ptype,
                            }
                        ],
                        columns=RECORD_COLUMNS,
                    ),
                ],
                ignore_index=True,
            )

        gsheets.update(worksheet=worksheet, data=df[RECORD_COLUMNS])
        read_gsheets_records.clear()
        st.toast("⚡ 齐大师云端档案已同步！")
        return True
    except Exception as e:
        st.error(f"Google Sheets 写入失败，已尝试保存到本地 SQLite：{e}")
        return False


def save_record(name, birth, report, history, ptype="single"):
    st.session_state.last_save_error = ""
    if not str(report or "").strip():
        st.session_state.last_save_error = "空报告不会写入档案库，请先重新生成正文。"
        st.error(st.session_state.last_save_error)
        return False
    identity_error = validate_record_identity(name, birth, ptype)
    if identity_error:
        st.error(identity_error)
        st.session_state.last_save_error = identity_error
        return False

    if save_to_gsheets(name, birth, report, history, ptype):
        st.session_state.last_save_ok = True
        return True
    saved_local = save_to_sqlite(name, birth, report, history, ptype)
    st.session_state.last_save_ok = saved_local
    if saved_local:
        st.session_state.last_save_error = "云端 Google Sheets 保存失败，已临时保存到本地 SQLite。线上环境重启后本地记录可能丢失，请稍后重试云端保存。"
    else:
        st.session_state.last_save_error = "云端和本地保存都失败。本次结果已保留在当前页面，请先不要刷新页面。"
    return saved_local

# --- 5. 侧边栏 ---
with st.sidebar:
    st.title("🔮 接口高级配置")

    # 【完整版深度推演引擎】：慢而强，用于完整双语深度报告
    st.subheader("🧠 完整版深度推演引擎")
    api_key_full_secret = get_config("openai_full", "api_key", "OPENAI_FULL_API_KEY")
    api_key_full_input = st.text_input(
        "完整版 API Key（临时覆盖，不会保存）",
        value="",
        type="password",
        placeholder="已从 Secrets 读取" if api_key_full_secret else "请在 Streamlit Secrets 中配置",
        key="api_key_full",
    )
    api_key_full = api_key_full_input.strip() or api_key_full_secret
    base_url_full = st.text_input(
        "完整版 Base URL",
        value=get_config("openai_full", "base_url", "OPENAI_FULL_BASE_URL", "https://api.jiucaihezi.studio/v1"),
        key="base_url_full",
    )
    model_full = st.text_input(
        "完整版模型名称",
        value=get_config("openai_full", "model", "OPENAI_FULL_MODEL", "gpt-5.5"),
        key="model_full",
    )

    st.markdown("---")

    # 【直播快速简评引擎】：快而轻，用于直播现场 PARTE 0 简评
    st.subheader("⚡ 直播快速简评引擎")
    api_key_live_secret = get_config("openai_live", "api_key", "OPENAI_LIVE_API_KEY")
    api_key_live_input = st.text_input(
        "快速版 API Key（临时覆盖，不会保存）",
        value="",
        type="password",
        placeholder="已从 Secrets 读取" if api_key_live_secret else "请在 Streamlit Secrets 中配置",
        key="api_key_live",
    )
    api_key_live = api_key_live_input.strip() or api_key_live_secret
    base_url_live = st.text_input(
        "快速版 Base URL",
        value=get_config("openai_live", "base_url", "OPENAI_LIVE_BASE_URL", "https://api.bltcy.ai/v1"),
        key="base_url_live",
    )
    model_live = st.text_input(
        "快速版模型名称",
        value=get_config("openai_live", "model", "OPENAI_LIVE_MODEL", "gemini-3-flash-preview-nothinking"),
        key="model_live",
    )

    st.markdown("---")
    # 【直播功能开关组件】
    st.subheader("📺 直播间推流设置")
    is_live_mode = st.toggle("开启直播专用简评模式 (PARTE 0)", value=True, help="开启=用快速模型(Gemini Flash)仅输出1000字以内纯中文极简简评，直播现场用；关闭=用完整版模型(gpt-5.5)输出完整深度双语报告。")
    is_live_talk_mode = st.toggle(
        "开启直播讲解模式（自然互动口播）",
        value=True,
        disabled=not is_live_mode,
        help="只影响直播快速简评的表达结构，不改变排盘和命理计算。开启后会生成 2.5-3.5 分钟的自然口播稿，并在正文中加入互动点。",
    )
    st.toggle(
        "生成后自动文案复核",
        key="enable_copy_review",
        help="会在输出后再做一轮中文语法和表达润色，不改命理结论。若你赶时间，可以关闭。",
    )
    
    st.markdown("---")
    st.title("📂 永久档案库")

    if has_gsheets_secrets():
        st.caption("当前档案存储：Google Sheets 云端持久化")
    else:
        st.caption("当前档案存储：本地 SQLite")
        st.warning("如果部署在 Streamlit Cloud，请配置 Google Sheets Secrets，否则重启或重新部署后历史档案可能丢失。")

    history_list = load_records()

    if history_list:
        search_name = st.text_input(
            "按人名搜索档案",
            placeholder="输入姓名或代称关键词",
            key="archive_name_search",
        ).strip().lower()
        filtered_history = [
            row for row in history_list
            if not search_name or search_name in str(row.get("name", "")).lower()
        ]
        if search_name:
            st.caption(f"搜索结果：{len(filtered_history)} / {len(history_list)} 条")

        if not filtered_history:
            st.info("没有找到匹配的人名档案。")
        else:
            record_options = {
                f"{row.get('name', '')} (生日: {row.get('birth_info', '')}) [{row.get('date', '')}]": row
                for row in filtered_history
            }
            selected_label = st.selectbox(
                "选择要调出的历史档案",
                ["-- 请选择 --"] + list(record_options.keys()),
                key="archive_record_select",
            )
            
            if selected_label != "-- 请选择 --":
                selected_record = record_options[selected_label]
                st.caption(
                    f"已选择：{selected_record.get('name', '')}｜生日：{selected_record.get('birth_info', '')}"
                )
                if st.button("调出该档案", key="load_selected_archive"):
                    if restore_record_to_session(selected_record):
                        st.success("已恢复档案")
                        st.rerun()
                    else:
                        st.error("档案读取失败，请重新选择。")
    else:
        st.caption("💡 暂无历史测算档案。")

# --- 6. 主界面 ---
st.title("🕯️ Maestro Qi: Alquimia de Destino")

tab_single, tab_double, tab_bazi, tab_bracelet, tab_fengshui = st.tabs([
    "👤 个人能量推演 (Lectura Individual)",
    "💞 双人命运合盘 (Sinastría de Destino)",
    "🀄 中国传统算法 (Bazi Clásico)",
    "📿 直播手串推荐",
    "🏠 直播风水开场"
])

final_name = ""
final_birth = ""
user_payload = ""
chosen_prompt = ""
# 深度版需要逐月范围；直播版只接收排盘结果和年度方向，避免把深度任务说明重复送入模型。
month_forecast_block = "" if is_live_mode else f"【月度测算区间】\n{build_month_forecast_note()}\n\n"

with tab_single:
    col1, col2 = st.columns(2)
    with col1:
        name_s = st.text_input("姓名 (Nombre)", key="name_s")
        gender_s = st.radio("性别 (Género)", ["女 (Mujer)", "男 (Hombre)"], horizontal=True, key="gen_s")
    with col2:
        birth_s = st.text_input("生辰信息 (Ej: 1988-05-17，可选 08:30)", key="birth_s")
        place_s = st.text_input("出生城市 (Lugar de nacimiento)", key="place_s")
    occupation_s = st.text_input(
        "职业/行业 (Ocupación / Rubro)",
        placeholder="例：销售、自由职业、老师、管理、餐饮、运营等",
        key="occupation_s",
    )
    focus_s = st.text_area("当前核心诉求 (Su consulta principal)", placeholder="例：2026年事业抉择、情感走向等", key="focus_s")
    
    if st.button("开始深度个人能量推演 (Iniciar Lectura Individual)"):
        final_name, final_birth, final_ptype = normalize_record_identity(name_s, birth_s, "single")
        identity_error = validate_record_identity(final_name, final_birth, final_ptype)
        if identity_error:
            st.error(identity_error)
            st.stop()
        set_current_record_identity(final_name, final_birth, final_ptype)
        # 诉求为空时，自动转为八字全面综合测算，绝不允许跑偏成星座占星
        focus_final_s = focus_s.strip() if focus_s.strip() else "用户未指定具体问题，请基于其八字四柱进行【全面综合命理测算】，重点覆盖事业财富、感情婚姻、健康，以及从当前月份到明年同月的月度走向，绝对围绕生辰八字展开。"
        if is_live_mode and not focus_s.strip():
            focus_final_s = "请依据程序预排生成直播简评，涵盖命格与五行、过去状态、当前障碍；2026和2027每年分别覆盖事业、财富、感情与健康提醒，遵循直播口播结构。"
        bazi_precheck = build_bazi_precheck(final_name, gender_s, final_birth, place_s, "个人单盘")
        occupation_final_s = occupation_s.strip() if occupation_s.strip() else "未提供"
        user_payload = (
            f"{bazi_precheck}\n\n"
            f"{month_forecast_block}"
            f"【单盘请求】姓名：{final_name}, 性别：{gender_s}, 生辰：{final_birth}, 出生地：{place_s}, 职业/行业：{occupation_final_s}, 诉求：{focus_final_s}"
        )
        chosen_prompt = PROMPT_SINGLE

with tab_double:
    st.markdown("### 👤 对象 A (Persona A)")
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        name_a = st.text_input("姓名/代称 A", key="name_a")
        gender_a = st.radio("性别 A", ["女 (Mujer)", "男 (Hombre)"], horizontal=True, key="gen_a")
    with col_a2:
        birth_a = st.text_input("生辰信息 A (可只填生日，时间可选)", key="birth_a")
        place_a = st.text_input("出生城市 A", key="place_a")
        
    st.markdown("### 👤 对象 B (Persona B)")
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        name_b = st.text_input("姓名/代称 B", key="name_b")
        gender_b = st.radio("性别 B", ["女 (Mujer)", "男 (Hombre)"], horizontal=True, key="gen_b")
    with col_b2:
        birth_b = st.text_input("生辰信息 B (可只填生日，时间可选)", key="birth_b")
        place_b = st.text_input("出生城市 B", key="place_b")
        
    focus_d = st.text_area("合盘核心诉求 (关系痛点/未来走向)", placeholder="例：两人是否适合合伙开店？两人的恋爱正缘缘分如何？", key="focus_d")
    
    if st.button("开始双人命运合盘推演 (Iniciar Sinastría)"):
        final_name, final_birth, final_ptype = normalize_record_identity(f"{name_a} & {name_b}", f"A:{birth_a} | B:{birth_b}", "double")
        if not all([name_a.strip(), name_b.strip(), birth_a.strip(), birth_b.strip()]):
            st.error("请至少填写双方姓名/代称和双方生辰信息，否则历史档案无法识别。")
            st.stop()
        set_current_record_identity(final_name, final_birth, final_ptype)
        bazi_precheck = join_prechecks(
            build_bazi_precheck(name_a, gender_a, birth_a, place_a, "对象A"),
            build_bazi_precheck(name_b, gender_b, birth_b, place_b, "对象B"),
        )
        # 诉求为空时，自动转为双人八字合盘综合测算，绝不允许跑偏成星座配对
        focus_final_d = focus_d.strip() if focus_d.strip() else "用户未指定具体问题，请基于两人八字四柱进行【全面综合合盘测算】，重点覆盖两人磁场契合度、感情婚姻走向、是否适合合伙、2026相处流年，绝对围绕双方生辰八字展开。"
        user_payload = (
            f"{bazi_precheck}\n\n"
            f"【合盘请求】\n"
            f"对象A：姓名 {name_a}, 性别 {gender_a}, 生辰 {birth_a}, 出生地 {place_a}\n"
            f"对象B：姓名 {name_b}, 性别 {gender_b}, 生辰 {birth_b}, 出生地 {place_b}\n"
            f"合盘最核心诉求：{focus_final_d}"
        )
        chosen_prompt = PROMPT_DOUBLE

with tab_bazi:
    st.markdown("#### 🀄 正统四柱排盘 · 依经典典籍论命")
    st.caption("严格按《穷通宝典》《滴天髓》《子平真诠》等经典排盘，内置藏干/十神/大运算法，比自由推演更精准。")
    col_z1, col_z2 = st.columns(2)
    with col_z1:
        name_z = st.text_input("姓名 (Nombre)", key="name_z")
        gender_z = st.radio("性别 (Género)", ["女 (Mujer)", "男 (Hombre)"], horizontal=True, key="gen_z", help="性别决定大运顺逆排（阳男阴女顺排，阴男阳女逆排）")
        solar_z = st.text_input("阳历(公历)生日 (Ej: 1990-05-15，可选 08:30)", key="solar_z", help="阳历或农历填一个即可，出生时间可选；不填时间则只做年月日三柱简评")
    with col_z2:
        place_z = st.text_input("出生省市 (Ej: 辽宁省丹东市)", key="place_z", help="用于真太阳时校正参考")
        alive_z = st.radio("是否在世", ["在世", "已故"], horizontal=True, key="alive_z", help="已故则流年只推算到去世年")
        lunar_z = st.text_input("农历(阴历)生日 (Ej: 1990年四月廿一, 闰月请标注)", key="lunar_z", help="不确定可留空")

    focus_z = st.text_area("当前核心诉求 (Su consulta principal)", placeholder="例：2026年事业财运、正缘婚姻、健康等；留空则做全面综合论命", key="focus_z")

    if st.button("开始正统八字排盘论命 (Iniciar Bazi Clásico)"):
        final_name, final_birth, final_ptype = normalize_record_identity(name_z, solar_z if solar_z.strip() else lunar_z, "bazi")
        identity_error = validate_record_identity(final_name, final_birth, final_ptype)
        if identity_error:
            st.error(identity_error)
            st.stop()
        set_current_record_identity(final_name, final_birth, final_ptype)
        focus_final_z = focus_z.strip() if focus_z.strip() else "用户未指定具体问题，请基于其八字四柱进行【全面综合命理论命】，覆盖日主旺衰、格局用神、事业财富、感情婚姻、健康，以及从当前月份到明年同月的月度走向，严格围绕生辰八字，禁止跑偏星座。"
        if is_live_mode and not focus_z.strip():
            focus_final_z = "请依据程序预排生成直播简评，涵盖命格与五行、过去状态、当前障碍；2026和2027每年分别覆盖事业、财富、感情与健康提醒，遵循直播口播结构。"
        alive_note = "在世（请以当前系统日期为当前时间推算流年）" if alive_z == "在世" else "已故（流年只推算到去世年为止，去世年份请在诉求中补充）"
        bazi_precheck = build_bazi_precheck(final_name, gender_z, solar_z if solar_z.strip() else lunar_z, place_z, "传统八字")
        user_payload = (
            f"{bazi_precheck}\n\n"
            f"{month_forecast_block}"
            f"【中国传统八字排盘请求】\n"
            f"姓名：{name_z}\n"
            f"性别：{gender_z}\n"
            f"阳历生日：{solar_z if solar_z.strip() else '未提供'}\n"
            f"农历生日：{lunar_z if lunar_z.strip() else '未提供'}\n"
            f"出生地：{place_z if place_z.strip() else '未提供'}\n"
            f"在世状态：{alive_note}\n"
            f"核心诉求：{focus_final_z}\n"
            + ("请依据程序预排和系统八字规则生成直播口播，不重新排盘。" if is_live_mode else "请严格按系统指令中的【排盘参考数据】排出四柱、藏干、十神、大运，再依经典典籍论命。")
        )
        chosen_prompt = PROMPT_BAZI

with tab_bracelet:
    st.markdown("#### 📿 八字配饰推荐 · 直播口播专用")
    st.caption("先用八字判断状态，再推荐适合展示的水晶手串方向。健康不作为手串推荐维度。")

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        name_r = st.text_input("姓名/代称", key="name_r")
        gender_r = st.radio("性别", ["女 (Mujer)", "男 (Hombre)"], horizontal=True, key="gen_r")
        bracelet_focus = st.selectbox(
            "本次推荐重点",
            ["综合提升", "事业财富", "感情关系", "稳定防护", "表达人气"],
            key="bracelet_focus",
        )
    with col_r2:
        birth_r = st.text_input("生辰信息 (Ej: 1988-05-17，可选 08:30)", key="birth_r")
        place_r = st.text_input("出生城市", key="place_r")

    focus_r = st.text_area(
        "直播间补充信息/当前问题",
        placeholder="例：想看事业财运、最近感情反复、想提升人气和成交等；可留空",
        key="focus_r",
    )

    if st.button("生成直播手串推荐话术"):
        final_name, final_birth, final_ptype = normalize_record_identity(name_r, birth_r, "bracelet")
        identity_error = validate_record_identity(final_name, final_birth, final_ptype)
        if identity_error:
            st.error(identity_error)
            st.stop()
        set_current_record_identity(final_name, final_birth, final_ptype)
        focus_final_r = focus_r.strip() if focus_r.strip() else "用户未补充具体问题，请基于八字状态做直播手串推荐，重点围绕事业、财富、感情、稳定防护或综合提升给出初步佩戴方向。"
        bazi_precheck = build_bazi_precheck(final_name, gender_r, final_birth, place_r, "直播手串推荐")
        user_payload = (
            f"{bazi_precheck}\n\n"
            f"【直播手串推荐请求】\n"
            f"姓名：{final_name}\n"
            f"性别：{gender_r}\n"
            f"生辰：{final_birth}\n"
            f"出生地：{place_r}\n"
            f"推荐重点：{bracelet_focus}\n"
            f"补充信息：{focus_final_r}\n"
            f"请生成适合主播照着念的中文直播手串推荐口播稿。"
        )
        chosen_prompt = PROMPT_BRACELET

with tab_fengshui:
    st.markdown("#### 🏠 风水知识普及 · 中文直播口播")
    st.caption("不问出生年月，先给陌生观众一个能马上听懂、马上检查的家居风水知识点，默认生成 2 分钟左右中文口播。")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        fengshui_topic = st.selectbox(
            "今日风水主题",
            ["家门入口", "客厅财位", "镜子摆放", "卧室睡眠", "厨房炉灶", "沙发靠山", "杂物堆积", "办公桌事业位"],
            key="fengshui_topic",
        )
        fengshui_goal = st.selectbox(
            "直播目标",
            ["留住新观众", "引导评论互动", "引导私信看户型/照片", "过渡到个人风水咨询"],
            key="fengshui_goal",
        )
    with col_f2:
        fengshui_lang = st.selectbox(
            "输出语言",
            ["中文直接口播", "西语为主 + 中文提示", "只输出西语"],
            key="fengshui_lang",
        )
        fengshui_duration = st.selectbox(
            "脚本时长",
            ["2分钟左右", "前30秒精简版", "60秒扩展版"],
            key="fengshui_duration",
        )

    fengshui_extra = st.text_area(
        "补充要求",
        placeholder="例：开头必须讲家门；要像主播直接讲；最后引导私信发户型图；可留空",
        key="fengshui_extra",
    )

    if st.button("生成直播风水开场话术"):
        now_label = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        final_name, final_birth, final_ptype = normalize_record_identity(
            f"风水开场-{fengshui_topic}",
            f"{fengshui_duration} | {now_label}",
            "fengshui",
        )
        set_current_record_identity(final_name, final_birth, final_ptype)
        user_payload = (
            "【直播风水开场请求】\n"
            f"主题：{fengshui_topic}\n"
            f"直播目标：{fengshui_goal}\n"
            f"输出语言：{fengshui_lang}\n"
            f"脚本时长：{fengshui_duration}\n"
            f"补充要求：{fengshui_extra.strip() if fengshui_extra.strip() else '无'}\n"
            "请生成适合开播时直接念的风水知识普及脚本。"
        )
        chosen_prompt = PROMPT_FENGSHUI_LIVE

# --- 7. 动态匹配执行与数据持久化 ---
if user_payload and chosen_prompt:
    # 根据直播开关，选择对应引擎的 Key / URL / 模型
    is_bracelet_request = st.session_state.current_prompt_type == "bracelet"
    is_fengshui_request = st.session_state.current_prompt_type == "fengshui"
    if is_live_mode or is_bracelet_request or is_fengshui_request:
        active_key, active_url, active_model = api_key_live, base_url_live, model_live
    else:
        active_key, active_url, active_model = api_key_full, base_url_full, model_full

    config_error = validate_api_config(
        active_key,
        active_url,
        active_model,
        "快速版" if (is_live_mode or is_bracelet_request or is_fengshui_request) else "完整版",
    )
    if config_error:
        st.error(config_error)
    else:
        st.session_state.last_save_ok = False
        st.session_state.last_save_error = ""
        previous_main_report = st.session_state.get("main_report", "")
        previous_chat_history = list(st.session_state.get("chat_history", []))
        
        # 动态拼接直播间模式附加指令
        if is_live_mode or is_bracelet_request or is_fengshui_request:
            if is_fengshui_request:
                live_constraint = """

⚠️【重要提醒：直播风水开场模式】：
当前只输出开播前风水知识脚本，不问出生年月，不做八字测算，不输出 PARTE I/II/III/IV。

【中文口播硬规则】
- 如果输出语言是“中文直接口播”，必须只输出中文。
- 第一句必须让陌生用户在 5 秒内听懂今天讲什么。
- 不要先问出生年月，不要解释流程，不要说很长的欢迎词。
- 必须立即给第一条公共风水知识，让新人先获得价值。
- 口吻必须像主播正在直播间直接讲，不能像讲义、备注、提纲或翻译稿。
- 如果脚本时长是“2分钟左右”，正文控制在 650-950 个中文字左右。
- 如果脚本时长是“前30秒精简版”，正文控制在 180-260 个中文字左右。
- 如果脚本时长是“60秒扩展版”，正文控制在 350-520 个中文字左右。
- 如果主题是家门入口，开头优先使用或改写这个中文节奏：“你现在先看一下自己家的入户门。有三件事，最容易让一个家的气场进不来。”
- 如果主题不是家门入口，也要先点名家中具体位置，再说今天教观众识别什么问题。

【内容结构】
只输出一个标题：
### 🏠 直播风水知识口播

标题后直接输出完整口播正文，不要分成【中文提示】【互动句】【私信引导】这些板块。

正文自然包含：
1. 强开场：直接点名今天检查家里哪个位置。
2. 第一条公共知识：立刻告诉观众这个位置为什么重要。
3. 3-5 个检查点：例如杂物、光线、镜子、门后、动线、破损、潮湿、尖角、颜色过重等。
4. 1-2 句自然互动：让观众边听边看自己家，不要变成单独板块。
5. 一个可执行动作：今天就能做的小调整。
6. 结尾私信引导：如果想看自己家门、卧室、厨房或财位，可以私信发照片/户型图。

【示范风格】
你现在先看一下自己家的入户门。

家门在风水里不是一个普通入口，它代表一个家接收外界机会、人气和财气的地方。

所以我今天不先讲复杂理论，我先教你看三个最简单的点。

第一，门口不要堆太多鞋子、箱子和杂物。

不是说家里一点东西都不能放，而是门一打开，人的第一眼要感觉顺、亮、能进来。

如果门口一打开就是乱的，人在心理上会先感觉被堵住，住久了也容易觉得事情总是不顺手。

【禁止】
- 禁止恐吓观众。
- 禁止讲八字、生肖、出生时间。
- 禁止长篇解释风水理论。
- 禁止先问“你家怎么样”，必须先给知识。
- 禁止说保证发财、保证转运。
- 禁止输出西语，除非用户在输出语言里明确选择西语。
"""
            elif is_bracelet_request:
                live_constraint = """

⚠️【重要提醒：直播手串推荐模式】：
当前只输出中文直播口播稿，严禁输出 PARTE I/II/III/IV，严禁输出完整深度报告。

【核心定位】
- 这是“八字快速分析 + 水晶手串推荐 + 主播展示话术”，不是八字教学。
- 先分析八字状态，再说适合佩戴什么类型的配饰，最后落到具体手串展示。
- 健康不要作为手串推荐维度，不要写健康建议。
- 少讲术语，最多出现 1-2 个八字词；出现后立刻转成现实判断。
- 不要在开头输出出生时辰不足的技术说明；如果需要更细，只在事业、财富、感情节点处自然引导私信补具体出生时间。

【输出要求】
只输出一个标题：
### 📿 直播手串推荐口播

正文 500-800 字，60-90 秒左右，一句话一段，适合主播照着念。

必须按这个顺序自然展开：
1. 先给八字总判断：这个人当前最适合强化哪一种能量。
2. 讲事业/财富/感情/稳定防护中最相关的 2-3 个维度，不讲健康。
3. 过渡到“所以她适合佩戴的配饰不是随便选，而是要选能帮她稳定/招引/筛选/柔和/提升的类型”。
4. 插入展示句：必须写“主播此处拿出手串展示：”
5. 推荐 1 条主手串，可以说明 1-3 种材质组合，但不要推荐一堆。
6. 解释每个材质只讲现实意义，不讲玄乎功效。
7. 在事业、财富或感情后放 1 句私信引导：如果要看 2026-2027 具体月份该做什么、该规避什么，需要补具体出生时间私信我。
8. 手串结尾必须说明：直播里只能先给方向，真正定制还要看完整八字和具体出生时间。

【推荐方向】
- 事业财富：优先财富能量手串，如黄虎眼、黄阿赛，可搭配稳定型茶水晶。
- 感情关系：优先爱情能量手串，如冰粉、珍珠，强调柔和表达和选择稳定关系。
- 稳定防护：优先纯净/防护方向，如白幽灵、黑发晶、茶水晶。
- 表达人气：可偏向黄虎眼、白幽灵或多宝，强调展示力、行动力和筛选机会。
- 综合提升：优先多宝，或“白幽灵 + 茶水晶 + 黄虎眼”这类平衡组合。

【禁止】
- 禁止说戴了就发财、转运、复合、挡灾。
- 禁止把手串说成治疗健康问题。
- 禁止长篇解释五行十神。
- 禁止结尾只写泛泛“想知道更多私信我”。
- 禁止所有人都推荐同一条。

【示范风格】
这位朋友我先看八字状态。

她不是单纯缺机会，而是需要把机会筛选出来，再把能变现的方向稳定住。

事业上，她适合做有主动权、有表达空间、能靠个人能力转化结果的事情。

财富上，她不能只看哪里热闹就往哪里冲，越是机会多，越要先抓一个能持续变现的方向。

如果她要看 2026 到 2027 哪几个月适合冲事业、哪几个月要守财，这个需要补具体出生时间私信我，我才能看得更细。

所以从配饰方向看，她不适合一上来就戴特别冲的招财款。

她更适合先稳住判断力，再加强财富行动力。

主播此处拿出手串展示：

比如这一条，我会偏向白幽灵、茶水晶、黄虎眼这一类组合。

白幽灵代表先把杂乱的人和事清掉，不要什么机会都接。

茶水晶偏稳定，适合帮她在选择面前慢一点、稳一点。

黄虎眼走财富和行动力方向，适合把注意力放在真正能成交、能落地的事情上。

所以这条不是单纯招财，而是稳定财富型。

直播里我只能先给一个方向，真正要定到最适合她的手串，还是要看完整八字和具体出生时间。
"""
            else:
                live_constraint = LIVE_QUICK_REPORT_CONSTRAINT
        else:
            live_constraint = "\n\n⚠️【重要提醒：完整版深度模式】：无需输出 PARTE 0 模块，直接从 PARTE I 开始执行高标准深度双语（西语+中文）推演。为避免接口 120 秒代理超时，本次必须控制在单次可完成长度内；优先输出核心排盘、格局、事业财富和2026关键判断。若内容过多，不要强行写完所有细节，结尾提示用户用追问继续补全 PARTE III/IV 或具体月份。"

        if is_fengshui_request:
            system_prompt = PROMPT_FENGSHUI_LIVE + live_constraint
        elif is_bracelet_request:
            system_prompt = LIVE_ENGINE_BASE + LIVE_BAZI_RULES + PROMPT_BRACELET + live_constraint
        elif is_live_mode:
            system_prompt = LIVE_ENGINE_BASE + LIVE_BAZI_RULES + live_constraint
        else:
            system_prompt = chosen_prompt + live_constraint

        placeholder = st.empty()
        current_full_text = ""
        last_render_at = 0.0
        last_render_len = 0
        final_finish_reason = ""
        generation_started_at = time.monotonic()
        generation_elapsed = None
        
        try:
            if is_fengshui_request:
                spinner_msg = "齐大师正在生成直播风水开场话术..."
            elif is_bracelet_request:
                spinner_msg = "齐大师正在生成直播手串推荐话术..."
            elif is_live_mode and is_live_talk_mode:
                spinner_msg = "齐大师正在生成直播自然口播稿..."
            else:
                spinner_msg = "齐大师正在快速点评..." if is_live_mode else "齐大师正在调动命理能量磁场，深度推演中..."
            with st.spinner(spinner_msg):
                if is_fengshui_request:
                    max_tokens = 1400
                elif is_bracelet_request:
                    max_tokens = 1800
                elif is_live_mode:
                    max_tokens = 2400
                else:
                    max_tokens = 8000
                api_mode = "live" if is_live_mode else "full"
                api_engines = get_api_engines(active_key, active_url, active_model, api_mode)
                last_api_error = ""
                for engine_label, engine_key, engine_url, engine_model in api_engines:
                    try:
                        client = OpenAI(api_key=engine_key, base_url=engine_url, timeout=120.0)
                        response = client.chat.completions.create(
                            model=engine_model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_payload}
                            ],
                            stream=True,
                            temperature=0.8,
                            max_tokens=max_tokens,
                        )
                        for chunk in response:
                            if chunk.choices:
                                if chunk.choices[0].finish_reason:
                                    final_finish_reason = chunk.choices[0].finish_reason
                                delta_content = getattr(chunk.choices[0].delta, "content", None)
                            else:
                                delta_content = None
                            if delta_content:
                                current_full_text += delta_content
                                st.session_state.main_report = current_full_text
                                now = time.monotonic()
                                should_render = (
                                    now - last_render_at >= 0.35
                                    or len(current_full_text) - last_render_len >= 500
                                )
                                if should_render:
                                    placeholder.markdown(current_full_text + "▌")
                                    last_render_at = now
                                    last_render_len = len(current_full_text)
                        if current_full_text.strip():
                            if engine_label != "首选接口":
                                st.info(f"首选接口响应异常，已自动切换到{engine_label}。")
                            break
                    except Exception as api_error:
                        last_api_error = str(api_error)
                        if current_full_text.strip():
                            break
                        continue
                if not current_full_text.strip() and last_api_error:
                    raise RuntimeError(f"所有接口均未返回正文。最后一个接口错误：{last_api_error}")

                generation_elapsed = time.monotonic() - generation_started_at
                
                placeholder.markdown(current_full_text)
                if not current_full_text.strip():
                    st.session_state.main_report = previous_main_report
                    st.session_state.chat_history = previous_chat_history
                    st.session_state.last_save_error = "本次生成没有返回正文，已保留上一份报告，请重试或切换更快模型。"
                    st.error(st.session_state.last_save_error)
                    placeholder.empty()
                else:
                    st.session_state.main_report = current_full_text
                    
                    st.session_state['last_name'] = final_name
                    st.session_state['last_birth'] = final_birth

                    review_status = "已跳过文案复核。"
                    if st.session_state.get("enable_copy_review", True):
                        primary_review_engine = ("快速版", api_key_live, base_url_live, model_live)
                        fallback_review_engine = ("当前引擎", active_key, active_url, active_model)
                        with st.spinner("齐大师正在做文案复核..."):
                            reviewed_text, reviewed_ok, review_status = review_copy_text(
                                current_full_text,
                                primary_review_engine,
                                fallback_review_engine,
                                context_label="主报告",
                            )
                        st.session_state.last_review_status = review_status
                        if reviewed_ok and reviewed_text.strip():
                            current_full_text = reviewed_text
                            st.session_state.main_report = reviewed_text
                            placeholder.markdown(reviewed_text)
                            st.success("文案复核完成，已修正明显语病和不顺口表达。")
                        else:
                            st.warning(review_status)
                    else:
                        st.session_state.last_review_status = review_status
                    
                    save_started_at = time.monotonic()
                    saved = save_record(
                        st.session_state.last_name,
                        st.session_state.last_birth,
                        current_full_text,
                        st.session_state.chat_history,
                        st.session_state.current_prompt_type,
                    )
                    save_elapsed = time.monotonic() - save_started_at
                    if saved:
                        st.success("推演报告已成功保存。")
                    else:
                        st.warning("报告已生成，但自动保存失败。当前页面已保留完整内容，请先不要刷新页面，可以在报告下方点击重新保存。")
                    timing_parts = []
                    if generation_elapsed is not None:
                        timing_parts.append(f"API生成耗时：{generation_elapsed:.1f} 秒")
                    timing_parts.append(f"档案保存耗时：{save_elapsed:.1f} 秒")
                    st.caption("｜".join(timing_parts))
                    if final_finish_reason == "length":
                        st.warning("模型达到本次输出长度上限，报告可能没有完全写完。当前已生成内容已保存，可以用追问继续补全后半段。")
                    placeholder.empty()

        except Exception as e:
            if current_full_text.strip():
                st.session_state.main_report = current_full_text
                interrupted_msg = (
                    "生成过程中连接中断，但已保留中断前内容。你可以先使用当前页面内容，"
                    "或点击下方按钮把这份中断草稿重新保存到档案库。"
                )
                saved_partial = save_record(
                    st.session_state.get("last_name", final_name),
                    st.session_state.get("last_birth", final_birth),
                    current_full_text,
                    st.session_state.chat_history,
                    st.session_state.current_prompt_type,
                )
                st.session_state.last_save_error = (
                    "生成过程中连接中断，中断前内容已保存为草稿。"
                    if saved_partial
                    else interrupted_msg
                )
            elif not st.session_state.get("last_save_error"):
                st.session_state.main_report = previous_main_report
                st.session_state.chat_history = previous_chat_history
            st.error(format_generation_error(e))

# --- 8. 追加提问逻辑 ---
if st.session_state.main_report:
    st.markdown("---")
    st.subheader("📜 核心能量推演报告 (Reporte Principal)")
    st.markdown(st.session_state.main_report) 

    if st.session_state.get("last_review_status"):
        st.caption(f"文案复核状态：{st.session_state.last_review_status}")

    if st.button("重新复核当前报告", key="manual_review_current_report"):
        primary_review_engine = ("快速版", api_key_live, base_url_live, model_live)
        fallback_review_engine = ("当前引擎", api_key_full, base_url_full, model_full)
        with st.spinner("齐大师正在重新复核当前报告..."):
            reviewed_text, reviewed_ok, review_status = review_copy_text(
                st.session_state.main_report,
                primary_review_engine,
                fallback_review_engine,
                context_label="当前报告",
            )
        st.session_state.last_review_status = review_status
        if reviewed_ok and reviewed_text.strip():
            st.session_state.main_report = reviewed_text
            st.success("当前报告已重新复核。")
            saved = save_record(
                st.session_state.get("last_name", ""),
                st.session_state.get("last_birth", ""),
                st.session_state.main_report,
                st.session_state.chat_history,
                st.session_state.current_prompt_type,
            )
            if saved:
                st.rerun()
            else:
                st.warning(st.session_state.get("last_save_error", "复核后保存失败，请检查档案配置。"))
        else:
            st.warning(review_status)

    if st.session_state.get("last_save_error"):
        st.warning(st.session_state.last_save_error)
        if st.button("重新保存当前报告到档案库", key="retry_save_current_report"):
            saved = save_record(
                st.session_state.get("last_name", ""),
                st.session_state.get("last_birth", ""),
                st.session_state.main_report,
                st.session_state.chat_history,
                st.session_state.current_prompt_type,
            )
            if saved and not st.session_state.get("last_save_error"):
                st.success("当前报告已重新保存到云端档案库。")
            elif saved:
                st.warning(st.session_state.last_save_error)
            else:
                st.error(st.session_state.last_save_error or "重新保存失败，请检查姓名、生日和 Google Sheets 配置。")
    
    st.markdown("---")
    st.subheader("💬 客户追问与补充历史")
    
    for chat in st.session_state.chat_history:
        with st.chat_message("user"):
            st.write(chat['question'])
        with st.chat_message("assistant"):
            st.write(chat['answer'])

    with st.form("follow_up_form"):
        user_question = st.text_area("针对以上报告，还有什么想问的？", height=150)
        submit_follow_up = st.form_submit_button("发送指令/追问")

    if submit_follow_up and user_question:
        # 追问统一走【完整版深度引擎】，保证细挖深度
        config_error = validate_api_config(api_key_full, base_url_full, model_full, "完整版")
        if config_error:
            st.error(config_error)
            st.stop()

        client = OpenAI(api_key=api_key_full, base_url=base_url_full, timeout=600.0)
        if st.session_state.current_prompt_type == "double":
            active_prompt = PROMPT_DOUBLE
        elif st.session_state.current_prompt_type == "bazi":
            active_prompt = PROMPT_BAZI
        elif st.session_state.current_prompt_type == "bracelet":
            active_prompt = PROMPT_BRACELET
        elif st.session_state.current_prompt_type == "fengshui":
            active_prompt = PROMPT_FENGSHUI_LIVE
        else:
            active_prompt = PROMPT_SINGLE
        
        if st.session_state.current_prompt_type == "fengshui":
            follow_up_constraint = "\n\n⚠️【追问约束】：继续围绕直播风水知识普及来回答，不要切回八字测算；默认输出中文直接口播稿，像主播能照着讲的版本。"
        elif st.session_state.current_prompt_type == "bracelet":
            follow_up_constraint = "\n\n⚠️【追问约束】：继续围绕八字手串推荐来回答，必须继承主报告中已经给出的手串方向，绝对禁止前后矛盾。"
        else:
            follow_up_constraint = "\n\n⚠️【严厉约束】：在回答后续追问时，你必须严格继承主报告中已经给出的所有测算结论和特定手串推荐方案，绝对禁止前后矛盾！"

        messages = [
            {"role": "system", "content": active_prompt + follow_up_constraint},
            {"role": "assistant", "content": st.session_state.main_report}
        ]
        for chat in st.session_state.chat_history:
            messages.append({"role": "user", "content": chat['question']})
            messages.append({"role": "assistant", "content": chat['answer']})
        
        messages.append({"role": "user", "content": f"{user_question} (请务必提供西语+中文对照)"})

        try:
            with st.spinner("齐大师正在回复..."):
                resp = client.chat.completions.create(
                    model=model_full,
                    messages=messages,
                    stream=False,
                    max_tokens=2500,
                    temperature=0.3 
                )
                new_answer = resp.choices[0].message.content
                st.session_state.chat_history.append({"question": user_question, "answer": new_answer})
                
                saved = save_record(
                    st.session_state.get('last_name', ''),
                    st.session_state.get('last_birth', ''),
                    st.session_state.main_report,
                    st.session_state.chat_history,
                    st.session_state.current_prompt_type,
                )
                if saved:
                    st.rerun()
        except Exception as e:
            st.error(format_generation_error(e))
