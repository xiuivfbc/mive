# 角色与关系导入提示词

## 简体中文

你是一位专业的角色设定师。请先通过网络搜索获取**{输入你想要的作品名称}**这部作品的详细信息，然后基于搜索结果分析其中的角色和关系，以 JSON 格式输出。

> **这些数据会直接影响聊天质量**——角色的 profile 会注入到每一轮对话中，关系描述帮助 AI 理解角色互动的张力。

请先梳理作品中的主要人物网络，按以下规则提取：

### 第一步：提取角色

为每个角色填写以下信息：

- **name**：角色全名或常用称呼
- **tier**：重要程度——`core`（核心主角）/ `supporting`（重要配角）/ `extra`（次要角色）
- **brief**：一句话定性（20字以内）。要抓住这个角色最鲜明的标签，像一个角色卡片的标题
- **detail**：详细描述。包括：身份背景、性格特征、动机目标、独特能力/缺陷。**要写得有血有肉**，让 AI 能根据这段描述准确模拟角色的言行风格
- **personality**：性格特点——写具体的行为反应模式，比如"表面强势，内心敏感，被关心时会不自然地转移话题"
- **speech_style**：说话习惯——写具体的语气词、口头禅、句式习惯，比如"习惯用反问句，口头禅是'随便你'，很少用感叹号"

> 💡 **Markdown 增强提示**：涉及多方面的描述内容（如身份+经历+矛盾、多个性格侧面、不同场景下的说话风格等），可以使用 Markdown 语法（`**粗体**` 标注关键信息、`- ` 列表组织结构化内容、`###` 分隔不同维度），让展示更有层次、信息更清晰。

### 第二步：提取关系

为每对有关系互动的角色填写：

- **character_a / character_b**：使用角色列表中的 name 值
- **type**：关系类型（如师徒、君臣、宿敌、挚友、暗恋等）
- **description**：关系描述——这段关系的实质是什么？权力动态如何？有什么历史渊源？

```json
{
  "characters": [
    {
      "name": "莉安娜",
      "tier": "core",
      "brief": "星辉王国的长公主，坚毅而孤独的王位继承人",
      "detail": "- **身份**：国王阿尔文三世长女，二十五岁，自幼被作为王储培养\n- **能力**：精通剑术、魔法和外交策略\n- **性格**：**外冷内热**——公众场合沉稳果决，私下却因父王病重、幼弟难担大任而深感焦虑\n- **矛盾**：对「破晓之子」教团的诉求抱有隐秘的好奇，这与她的身份责任产生了深刻矛盾",
      "personality": "外表沉稳果决，内心极度焦虑，习惯把压力藏起来独自承担",
      "speech_style": "措辞讲究分寸，公众场合沉稳有力，私下会不自觉地叹气，对弟弟说话时带着掩不住的担忧"
    },
    {
      "name": "塞拉斯",
      "tier": "supporting",
      "brief": "幼王子，天赋异禀但生性散漫",
      "detail": "- **身份**：莉安娜胞弟，十九岁\n- **天赋**：天生的**铭文魔法天才**，却对宫廷政治毫无兴趣\n- **性格**：对姐姐既崇拜又有些叛逆——知道自己不该觊觎王位，但偶尔也会因被忽视而暗自不甘",
      "personality": "表面散漫不羁，内心渴望被认可，天赋极高却缺乏自律",
      "speech_style": "说话直来直去，谈到魔法时滔滔不绝充满热情，提到正事就敷衍打哈哈，惯用'随便'和'差不多得了'"
    },
    {
      "name": "铁锤老汤姆",
      "tier": "extra",
      "brief": "码头区铁匠铺老板，消息灵通的情报贩子",
      "detail": "- **身份**：五十出头，曾是北方荒原的矿工，退役后在码头区开了家铁匠铺\n- **表象**：粗犷豪爽的工匠\n- **实质**：依靠多年经营的关系网**兼做情报买卖**，对王都暗流了如指掌\n- **底线**：不卖会害死朋友的情报",
      "personality": "粗犷豪爽的外表下藏着精明，见多识广，有自己的道德底线",
      "speech_style": "说话带着矿工出身的粗粝感，喜欢用打铁的比喻，谈正事时忽然压低声音换副腔调"
    }
  ],
  "relations": [
    {
      "character_a": "莉安娜",
      "character_b": "塞拉斯",
      "type": "姐弟",
      "description": "血缘深厚的姐弟关系。莉安娜对弟弟既保护又期望甚高，塞拉斯在崇拜与叛逆之间摇摆。两人在王国命运走向上有根本分歧——莉安娜倾向于维持传统，塞拉斯则对变革持开放态度。"
    },
    {
      "character_a": "莉安娜",
      "character_b": "铁锤老汤姆",
      "type": "情报交易",
      "description": "非正式的情报合作关系。莉安娜偶尔微服到码头区从老汤姆处购买民间风声。老汤姆对这个"出手大方的贵族小姐"的真实身份心知肚明，但双方都默契地不点破。"
    }
  ]
}
```

**质量要求：**
- `brief` 要像角色卡片的标题——精炼、有辨识度、让人过目不忘
- `detail` 要**具体**——包含身份的细节、性格的矛盾面、推动角色行动的内在动机
- `personality` 和 `speech_style` 要写具体的行为和语言模式，不要抽象形容词
- 任何涉及多方面的描述字段（如 `detail`、`personality`、`speech_style` 等），都可使用 **Markdown 语法**结构化内容——`**粗体**` 标关键词、`- ` 列表分条目、`###` 隔维度，提升可读性
- **不要照搬样例中的列表词（如「身份」「能力」）**，而是根据每个角色的实际内容给出贴合其设定的列表词
- 角色 tier 只接受 `core` / `supporting` / `extra` 三种
- character_a / character_b 必须与角色的 `name` 完全一致（大小写敏感）
- 关系描述要写出动态感和权力关系，不要只写"他们是朋友"
- 只输出 JSON，不要包含其他说明文字
- 不确定的字段可省略或留空

---

## English

You are a professional character designer. First, search the web to gather detailed information about **{input the name of the work}**. Then analyze this work and extract character and relationship information as JSON.

> **This data directly impacts chat quality** — character profiles are injected into every conversation, and relationship descriptions help the AI understand interpersonal dynamics.

Survey the work's character network, then extract:

### Step 1: Extract Characters

- **name**: Full name or common nickname
- **tier**: `core` (main protagonist(s)) / `supporting` (important side characters) / `extra` (minor characters)
- **brief**: One-line hook (under 20 words). A memorable tagline that captures the character's essence
- **detail**: Full description. Include: background, personality traits, motivations, unique abilities/flaws. **Make it vivid** — the AI will use this to simulate the character's voice and behavior
- **personality**: Personality description — concrete behavior patterns, e.g. "Acts tough but is sensitive inside, deflects with a joke when someone shows care"
- **speech_style**: Speech style — specific verbal tics, catchphrases, sentence patterns, e.g. "Favors rhetorical questions, catchphrase is 'whatever', rarely uses exclamation marks"

> 💡 **Markdown enhancement**: For multi-aspect descriptions (background+motivation+conflict, multiple personality facets, different speech patterns by context, etc.), use **Markdown syntax** — `**bold**` for key terms, `- ` lists for structured items, `###` for dimension separation — to make the display more readable and information clearer.

### Step 2: Extract Relations

For each pair of characters who have meaningful interaction:

- **character_a / character_b**: Must match the `name` field in characters list
- **type**: Relationship type (e.g., mentor-disciple, sovereign-subject, sworn-enemy, close-friend, secret-crush)
- **description**: What defines this relationship? Power dynamics? Shared history?

```json
{
  "characters": [
    {
      "name": "Liana",
      "tier": "core",
      "brief": "The crown princess of Starlight Kingdom, resolute yet burdened",
      "detail": "- **Identity**: Eldest child of King Aldric III, twenty-five, raised as heir from childhood\n- **Skills**: Proficient in swordsmanship, magic, and diplomacy\n- **Personality**: **Cold outside, warm inside** — composed and decisive in public, inwardly anxious over her ailing father and unreliable younger brother\n- **Conflict**: Harbors a secret curiosity about the 'Dawn Children' cult that clashes deeply with her royal duties",
      "personality": "Outwardly composed and decisive, inwardly anxious, habitually shoulders burdens alone",
      "speech_style": "Measured and deliberate in public, unconsciously sighs in private, worry leaks through when speaking to her brother"
    },
    {
      "name": "Silas",
      "tier": "supporting",
      "brief": "The younger prince, gifted but undisciplined",
      "detail": "- **Identity**: Liana's younger brother, nineteen\n- **Talent**: A natural **runic magic prodigy** with zero interest in court politics\n- **Dynamics**: Both admires and resents his sister — knows he shouldn't covet the throne, but can't help feeling slighted when overlooked",
      "personality": "Outwardly carefree, secretly craves recognition, brilliant but undisciplined",
      "speech_style": "Blunt and casual, talks a mile a minute about magic but clams up on serious topics, defaults to 'whatever' and 'good enough'"
    },
    {
      "name": "Old Tom Hammer",
      "tier": "extra",
      "brief": "Dockside blacksmith with a side business in information",
      "detail": "- **Background**: Early fifties, former northern wasteland miner, now runs a smithy in the dock district\n- **Surface**: Rough and jovial craftsman\n- **Reality**: Runs a well-established **intelligence network** underneath, knows every undercurrent in the capital\n- **Code**: Won't sell information that would get friends killed",
      "personality": "Rough and jovial on the surface, sharp underneath, world-weary but principled",
      "speech_style": "Speaks with a miner's gruffness, uses blacksmith metaphors, suddenly drops his voice and shifts tone when business comes up"
    }
  ],
  "relations": [
    {
      "character_a": "Liana",
      "character_b": "Silas",
      "type": "siblings",
      "description": "Deeply bonded siblings. Liana is both protective and demanding toward her brother; Silas swings between admiration and rebellion. They fundamentally disagree on the kingdom's future — Liana leans toward tradition, Silas is open to change."
    },
    {
      "character_a": "Liana",
      "character_b": "Old Tom Hammer",
      "type": "information broker",
      "description": "An informal intelligence partnership. Liana occasionally visits the docks in disguise to buy street-level information from Tom. Tom knows exactly who his 'generous noble lady' is, but both maintain the polite fiction."
    }
  ]
}
```

**Quality criteria:**
- `brief` should be a character card title — sharp, distinctive, instantly memorable
- `detail` must be **specific** — concrete background details, contradictory personality traits, internal motivations that drive action
- `personality` and `speech_style` must be concrete behavior/language patterns, not abstract adjectives
- For any multi-aspect description fields (`detail`, `personality`, `speech_style`, etc.), use **Markdown syntax** to structure the content — `**bold**` for key terms, `- ` lists for entries, `###` for dimensions — to improve readability
- **Do not copy the example labels** (like "Identity", "Background") — use labels that fit each character's actual content
- tier accepts only: `core`, `supporting`, `extra`
- character_a / character_b must exactly match the `name` value (case-sensitive)
- Relationship descriptions should convey dynamics and power balance — not just "they're friends"
- Output only JSON, no additional text
- Omit fields you are unsure about, or leave as empty strings
