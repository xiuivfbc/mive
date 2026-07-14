# 世界信息导入提示词

## 简体中文

你是一位专业的世界观分析师与叙事设计师。请先通过网络搜索获取**{输入你想要的作品名称}**这部作品的详细信息，然后基于搜索结果提取其世界观设定信息，以 JSON 格式输出。

> **为什么这些字段很重要：**
> - `plot_summary`（世界简介）概要描述整个作品，方便用户理解这个世界的全貌
> - `common_sense`（常识）会注入到**每一次聊天和剧情推演**中，是 AI 理解这个世界的基础上下文
> - `core_conflict`（核心冲突）帮助 AI 理解角色所处的矛盾环境
> - `tone_and_atmosphere`（基调氛围）控制 AI 输出的语言风格和情感色彩
> - `plot_development`（情节发展）让 AI 了解已发生的事件脉络

请按以下步骤思考，然后输出 JSON：

**第一步：分析作品**
先梳理这部作品的世界观构成——科技/魔法水平、社会结构、地理环境、文化习俗等基础设定。

**第二步：提炼关键信息**
针对每个字段，提取最核心、对角色行为最有影响的信息。

**第三步：生成输出**

```json
{
  "plot_summary": "作品的世界观简介。用 3-5 句话概括该作品的世界设定，让读者快速了解这个世界的全貌。\n\n> 💡 用 Markdown 加粗标注作品的核心特色，如年代设定、主要种族或文明类型。",
  "common_sense": "该世界中所有角色都知晓的常识性背景。使用 Markdown 结构化呈现——按实际维度使用 ### 小标题或 - 无序列表分点罗列。重点包括：科技/魔法水平、社会制度与阶级结构、地理气候、货币与经济、日常生活常识。从「这个世界的一名普通居民」的视角来写，不要涉及只有少数人知道的秘密。\n\n### 科技水平\n蒸汽机与初级电力普及，最新技术是符文矩阵通讯。\n\n### 社会结构\n城邦联盟制，议会共治。贵族与平民之间的社会流动性极低。\n\n### 地理气候\n大陆分为五大气候区，北部寒冷多矿，南部温暖湿润适合农耕。",
  "core_conflict": "一句话精准概括作品最核心的矛盾或主题。聚焦内在张力而非具体事件。\n\n> 💡 涉及多层矛盾时可用 Markdown 标明。",
  "tone_and_atmosphere": "描述作品整体的基调和情感氛围。用精炼的语言刻画情绪色彩，让 AI 能感受到该世界的「味道」。\n\n> 💡 多维度氛围（如不同场景的情感反差）可用 Markdown 分条目描述。",
  "plot_development": "主要情节发展脉络（如有）。按时间线简要说明已发生的关键事件，帮助 AI 理解当前时间点的世界状态。\n\n> 💡 时间线可用 Markdown 列表组织，一目了然。"
}
```

**质量要求：**
- `plot_summary` 控制在 100 字以内，用精炼的 3-5 句话概括作品全貌
- `common_sense` 是**最重要的字段**，请确保：
  - 内容丰富（300-800字），使用 **Markdown 结构化排版**
  - 聚焦「对角色行为有约束力」的设定（什么能做、什么不能做、社会如何看待不同行为）
  - 语言具体、有细节，避免空洞概括
  - 所有内容都是该世界「公开的常识」，不是秘密或剧情内幕
- `core_conflict` 控制在 50 字以内，像小说腰封一样有力；涉及多层矛盾可用 Markdown 标明
- `tone_and_atmosphere` 控制在 50 字以内，用感官语言（视觉、听觉、情感）；多维度氛围可用 Markdown 分条目
- `plot_development` 可用 Markdown 列表或时间线组织，按顺序呈现关键事件
- 所有涉及多方面的描述字段（`common_sense`、`plot_development` 等），都推荐使用 **Markdown 语法**结构化内容——`###` 小标题分维度、`- ` 列表分条目、`**粗体**` 标关键词，提升可读性
- **不要照搬样例中的列表词（如「科技水平」「社会结构」）**，而是根据该世界的实际内容给出贴合其设定的维度词
- 只输出 JSON，不要包含其他说明文字
- 如果不确定某个字段，可省略或留空

---

## English

You are a professional worldbuilding analyst and narrative designer. First, search the web to gather detailed information about **{input the name of the work}**. Then analyze this work and extract its world-setting information as JSON.

> **Why these fields matter:**
> - `plot_summary` is the world overview — gives users a quick grasp of what this world is about
> - `common_sense` is injected into **every chat and event** — it's the foundational context for the AI
> - `core_conflict` helps the AI understand the tensions shaping character decisions
> - `tone_and_atmosphere` controls the stylistic and emotional flavor of AI output
> - `plot_development` informs the AI of past events (only used when non-empty)

Think step by step before outputting.

```json
{
  "plot_summary": "World overview. 3-5 sentences summarizing the world's setting, giving readers a quick grasp of the world.\n\n> 💡 Use Markdown **bold** to highlight core features like era, major races or civilization types.",
  "common_sense": "Common knowledge that every character in this world would know. Use Markdown structure — ### subheadings or - bullet lists by dimension. Cover: technology/magic level, social structure, geography/climate, economy, daily life. Write from the perspective of 'an ordinary resident of this world'. No secrets or plot-specific reveals.\n\n### Technology\nSteam engines and basic electricity are widespread. The latest innovation is runic matrix communication.\n\n### Social Structure\nCity-state confederation governed by a council. Social mobility between nobles and commoners is extremely low.\n\n### Geography\nThe continent has five climate zones — cold and mineral-rich in the north, warm and fertile in the south.",
  "core_conflict": "A single, powerful sentence capturing the central tension or theme. Focus on the underlying friction, not specific plot events.\n\n> 💡 Use Markdown to separate multiple layers of conflict if applicable.",
  "tone_and_atmosphere": "The overall mood and emotional flavor of the world. Use sensory language that lets the AI feel the world's texture.\n\n> 💡 Use Markdown bullet points for multi-faceted atmosphere descriptions.",
  "plot_development": "Key plot progression (if any). A timeline of significant events that have occurred, helping the AI understand the current state of the world.\n\n> 💡 Use Markdown lists or timeline formatting for clarity."
}
```

**Quality criteria:**
- `plot_summary` — keep under 100 words, 3-5 concise sentences summarizing the world
- `common_sense` is the **most important field**. Ensure it:
  - Is rich and detailed (300-800 words), formatted with **Markdown structure**
  - Focuses on actionable worldbuilding — what constrains or enables character behavior
  - Uses concrete, specific language — avoid vague generalizations
  - Contains only public knowledge — no secrets or plot twists
- `core_conflict` — keep under 50 words, as punchy as a book jacket tagline; use Markdown for multi-layer conflicts
- `tone_and_atmosphere` — keep under 50 words, appeal to senses (sight, feeling, mood); use Markdown for multi-faceted descriptions
- `plot_development` — use Markdown lists or timeline to organize events chronologically
- For any multi-aspect description fields (`common_sense`, `plot_development`, etc.), use **Markdown syntax** to structure the content — `###` headings for dimensions, `- ` lists for entries, `**bold**` for key terms — to improve readability
- **Do not copy the example labels** (like "Technology", "Social Structure") — use labels that fit the actual world's content
- Output only JSON, no additional text
- Omit fields you are unsure about, or leave them as empty strings
