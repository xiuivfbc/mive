# 元素导入提示词

## 简体中文

你是一位专业的世界观设定整理师。请先通过网络搜索获取**{输入你想要的作品名称}**这部作品的详细信息，然后基于搜索结果从中提取除角色之外的世界观元素，以 JSON 数组格式输出。

**元素是 AI 理解世界的重要素材**——它们会在聊天和剧情推演中被检索引用。好的元素描述能让 AI 生成更生动、更符合世界设定的内容。

请先通盘梳理这部作品的世界观构成，然后按以下分类逐一提取：

**支持的类别（category）：**
- `场所`：地点、区域、建筑、地标——描述其外观、功能、氛围
- `势力`：组织、国家、团体、派系——描述其宗旨、规模、影响力
- `规则`：法则、体系、法术、科技、魔法——描述其运作原理和限制
- `事件`：历史事件、战役、危机——描述其起因、经过、影响
- `物品`：道具、装备、宝物——描述其外观、功能、稀有度
- `文化`：风俗、宗教、制度、社会——描述其内容、参与者、意义
- `其他`：不属于以上类别的元素

**质量要求：**
- **brief（一句话简介）**：一句话点明该元素的本质和特色，控制在 30 字以内。要让人（和 AI）一眼就记住。
- **detail（详细描述）**：展开说明其外观、功能、在世界的定位、与其他元素的关系。要有具体的细节（数字、材质、位置、历史），而不是泛泛的描述。
- **detail 涉及多维度信息**（如外观+功能+历史+影响力），推荐使用 **Markdown 语法**结构化——`**粗体**` 标关键词、`- ` 列表分条目、`###` 小标题隔维度，让展示更清晰
- **不要照搬样例中的列表词（如「外观」「功能」）**，而是根据每个元素的实际内容给出贴合其设定的维度词

```json
[
  {
    "name": "星辉穹顶",
    "category": "场所",
    "brief": "笼罩王都的魔法屏障，由建城时的星光凝结而成",
    "detail": "- **外观**：半球形覆盖王都全域，直径约十二公里。晴朗夜晚可见**七色流光**缓缓旋转，白天则近乎透明\n- **功能**：偏转大型魔法攻击、驱散魔兽，对普通物理通行无阻\n- **现状**：近百年亮度下降约三成，学者们对原因争论不休"
  },
  {
    "name": "铭文魔法",
    "category": "规则",
    "brief": "以符文铭刻为核心的主流魔法体系，强调精确与秩序",
    "detail": "- **原理**：通过在物体表面刻写特定符文序列来激发魔力效果\n- **限制**：高等铭文需要**稀有墨水**和精确的精神力控制\n- **学派**：元素系、治愈系、召唤系、防护系，每年招收不满百人"
  },
  {
    "name": "魔晶石贸易",
    "category": "物品",
    "brief": "王国经济命脉，既是能源也是硬通货",
    "detail": "- **产地**：产自北方荒原的魔晶矿脉，王室特许商会统一收购分销\n- **用途**：驱动城市照明、工坊动力和**军用武器**\n- **分级**：品质分七级，纯净度越高价值越大\n- **局势**：南方城邦联盟是最大买家，最近联合压价给王国财政带来巨大压力"
  }
]
```

**注意事项：**
- 元素数量不限，但请确保每个元素都有独立存在价值，不要堆砌
- brief 要精炼有力，detail 要具体丰富
- 只输出 JSON，不要包含其他说明文字
- category 请使用上述支持的类别名称
- 如果不确定类别，使用"其他"

---

## English

You are a professional worldbuilding archivist. First, search the web to gather detailed information about **{input the name of the work}**. Then analyze this work and extract world elements (everything except characters) as a JSON array.

**Elements are key context for AI** — they're retrieved and injected into chat and event generation. Good element descriptions make AI output more vivid and world-consistent.

First survey the work's worldbuilding, then extract by category:

**Supported categories:**
- `Place`: locations, areas, buildings, landmarks — describe appearance, function, atmosphere
- `Faction`: organizations, nations, groups, cliques — describe purpose, scale, influence
- `Rule`: laws, systems, magic, technology, abilities — describe principles and limits
- `Event`: historical events, battles, crises — describe causes, events, consequences
- `Item`: props, equipment, treasures — describe appearance, function, rarity
- `Culture`: customs, religions, institutions, society — describe content, participants, meaning
- `Other`: elements not fitting above categories

**Quality criteria:**
- **brief**: One punchy line capturing the essence (under 30 words). Make it memorable.
- **detail**: Expand with specifics — appearance, function, position in the world, relationships. Use concrete details (numbers, materials, locations, history), not vague descriptions.
- For **multi-aspect detail** (appearance+function+history+impact), use **Markdown syntax** — `**bold**` for key terms, `- ` lists for entries, `###` headings for dimensions — to make the display clearer
- **Do not copy the example labels** (like "Appearance", "Mechanism") — use labels that fit each element's actual content

```json
[
  {
    "name": "Starlight Dome",
    "category": "Place",
    "brief": "Magical barrier shielding the capital, forged from starlight at the city's founding",
    "detail": "- **Appearance**: Hemispherical dome covering the entire capital, roughly 12 km in diameter; **seven-colored light streams** rotate on clear nights, nearly transparent by day\n- **Function**: Deflects large-scale magical attacks, repels monsters, no resistance to ordinary physical passage\n- **Status**: Brightness dimmed ~30% over the past century, sparking heated scholarly debate"
  },
  {
    "name": "Runic Magic",
    "category": "Rule",
    "brief": "The mainstream magic system centered on rune inscription, emphasizing precision and order",
    "detail": "- **Mechanism**: Mages channel magical effects by inscribing specific rune sequences on surfaces\n- **Limits**: Advanced inscription requires **rare inks** and precise mental control\n- **Schools**: Elemental, Healing, Summoning, Protection — admitting fewer than 100 students yearly"
  },
  {
    "name": "Crystal Trade",
    "category": "Item",
    "brief": "The kingdom's economic lifeline, serving as both energy source and hard currency",
    "detail": "- **Source**: Mined from northern wastelands, distributed through royal-chartered merchant guilds\n- **Uses**: Powers city lighting, workshop machinery, and **military weapons**\n- **Grading**: Seven quality tiers — purer = more valuable\n- **Crisis**: Southern City-State Alliance (largest buyer) coordinated price squeeze, straining royal finances"
  }
]
```

**Notes:**
- Include as many elements as warranted, but ensure each has independent value — no padding
- brief should be sharp and evocative; detail should be rich and specific
- Output only JSON, no additional text
- Use one of the supported category names above
- If unsure about a category, use "Other"
