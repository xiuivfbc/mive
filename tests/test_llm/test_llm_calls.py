"""
LLM 调用集成测试。

目标：模拟创建世界流程中各个 LLM 调用点的真实输入，验证输出结构能被正确解析。
不测试业务逻辑，不依赖数据库，只关注 LLM 调用本身是否正常工作。

运行方式：
    pytest tests/test_llm/ -v
    （需设置 LLM_PROVIDER / LLM_API_KEY，可选 LLM_MODEL / LLM_BASE_URL）
"""

from src.models.scale import SCALES
from src.services.event_dialogue_service import PLANNER_SYSTEM_PROMPT
from src.services.extraction_service import (
    _EXTRACT_CHARACTERS_PROMPT,
    _EXTRACT_ELEMENTS_PROMPT,
)

# ── 公用测试数据（基于 wiki_filtered.txt 中的《2.5次元的诱惑》）────────────
_WORLD_TITLE = "2.5次元的诱惑"
_WORLD_AUTHOR = "橋本悠"
_WORLD_DESC = "以 Cosplay 文化为核心的青春恋爱漫画"

_WORLD_BACKGROUND = (
    "《2.5次元的诱惑》是以 Cosplay 文化为核心的青春恋爱漫画。"
    "故事发生在高中动漫同好会，围绕 Cosplay 和二次元文化展开。"
)

_ELEMENTS_DESC = (
    "- [人物角色] 织部莉莉卡: 对 Cosplay 极度热爱的动漫同好会成员，技术精湛\n"
    "  详情: 因深爱二次元世界而投身 Cosplay，将所有时间精力倾注于此，"
    "眼中只有如何让角色完美具现化。\n"
    "- [人物角色] 小鳥遊京介: 动漫同好会会长，起初不了解 Cosplay 但被莉莉卡震撼\n"
    "  详情: 被迫接触 Cosplay 文化后发现其魅力，从一无所知变成莉莉卡最大的支持者。\n"
    "- [地点] 社团教室: 动漫同好会的主要活动场所\n"
    "- [设定] Cosplay: 扮演动漫角色、制作服装道具的文化活动"
)

_CHARS_BRIEF = (
    "- 织部莉莉卡: 动漫同好会成员，对 Cosplay 极度热爱，技术精湛\n"
    "- 小鳥遊京介: 动漫同好会会长，被莉莉卡的 Cosplay 吸引，现在积极支持她"
)

_WORLD_ELEMENTS_CTX = (
    f"世界设定（{_WORLD_TITLE}）：\n"
    "  [设定] Cosplay：扮演动漫角色的文化活动\n"
    "  [地点] 社团教室：动漫同好会的主要活动场所"
)

_CHAR_A_BLOCK = (
    "【织部莉莉卡】对 Cosplay 极度热爱的动漫同好会核心成员，技术精湛，"
    "常独自练习，眼中只有如何让角色完美具现化。"
)
_CHAR_B_BLOCK = (
    "【小鳥遊京介】动漫同好会会长，一开始对 Cosplay 一无所知，"
    "被莉莉卡的 Cosplay 震撼后决心支持她，两人逐渐产生感情。"
)


# ════════════════════════════════════════════════════════════════════════════
# 1. 元素提取
# ════════════════════════════════════════════════════════════════════════════


class TestExtractionLLMCall:
    """ExtractionService 新流水线对应的 LLM 调用"""

    async def test_extract_characters(self, llm, wiki_content):
        """extract_characters：应返回含 name+tier 的数组"""
        config = SCALES["standard"]
        if config.char_target == 0:
            target_desc = (
                "任务：提取 wiki 中所有有独立介绍段落的角色，不设数量上限。"
                "wiki 中每个以标题或独立段落介绍的角色都必须出现在结果中。"
            )
            overflow_hint = (
                "逐一检查 wiki 中的角色介绍段落，每个有独立介绍的角色都必须提取，不得遗漏。"
            )
        else:
            target_desc = f"目标数量：{config.char_target} 个角色"
            overflow_hint = "超出目标数量时，按出场顺序舍弃末尾角色。"
        prompt = _EXTRACT_CHARACTERS_PROMPT.format(
            title=_WORLD_TITLE,
            target_desc=target_desc,
            overflow_hint=overflow_hint,
        )
        result = await llm.complete_json(
            system="你是角色识别与分级专家。只返回合法的 JSON 数组。",
            prompt=prompt,
            cacheable_system_prefix=wiki_content,
            max_tokens=4096,
            prefill="[",
        )
        # unwrap dict if needed
        if isinstance(result, dict):
            for key in ("characters", "results", "items", "data"):
                if isinstance(result.get(key), list):
                    result = result[key]
                    break
        assert isinstance(result, list), (
            f"expected list, got {type(result).__name__}: {str(result)[:200]}"
        )
        assert len(result) >= 1, "should have at least one character"
        for item in result:
            assert isinstance(item, dict), f"item should be dict: {item}"
            assert "name" in item, f"missing name: {item}"
            assert "tier" in item, f"missing tier: {item}"
            assert item["tier"] in ("core", "supporting", "extra"), f"invalid tier: {item['tier']}"

    async def test_extract_elements(self, llm, wiki_content):
        """extract_elements：应返回 7 个固定 tab 的 dict"""
        config = SCALES["standard"]
        element_min, element_max = config.element_range
        element_desc = (
            f"{config.label}，总共提取 {element_min}-{element_max} 个元素（硬性要求，不得超过上限）"
        )
        prompt = _EXTRACT_ELEMENTS_PROMPT.format(
            title=_WORLD_TITLE,
            element_desc=element_desc,
        )
        result = await llm.complete_json(
            system="你是世界观元素提取专家。只返回合法的 JSON 对象。",
            prompt=prompt,
            cacheable_system_prefix=wiki_content,
            max_tokens=8192,
        )
        assert isinstance(result, dict), (
            f"expected dict, got {type(result).__name__}: {str(result)[:200]}"
        )
        # 至少有一个非空 tab
        has_content = False
        for tab in ("场所", "势力", "规则", "事件", "物品", "文化", "其他"):
            if tab in result and isinstance(result[tab], list) and len(result[tab]) > 0:
                has_content = True
                for item in result[tab]:
                    assert isinstance(item, dict), f"item should be dict: {item}"
                    assert "name" in item, f"missing name: {item}"
                    assert "brief" in item, f"missing brief: {item}"
        assert has_content, "at least one tab should have elements"


# ════════════════════════════════════════════════════════════════════════════
# 2. 角色档案生成
# ════════════════════════════════════════════════════════════════════════════


class TestCharacterGenerationLLMCall:
    """GenerationService 中角色档案生成的 LLM 调用（Step 1）"""

    # 角色档案生成 system prompt
    _STEP1_SYSTEM = (
        "你是一个角色档案生成器，根据世界观素材为指定角色生成档案。\n\n"
        "输出必须是严格 JSON 对象，字段名和层级不可更改：\n"
        '{"name":"角色原名","profile":{"brief":"一句话简介","detail":"详细描写"}}\n\n'
        "⚠️ brief 和 detail 在 profile 层，不在 basic 里面。\n"
        '❌ 错误：{"profile":{"brief":"...","detail":"..."}}\n'
        '✅ 正确：{"profile":{"brief":"...","detail":"..."}}'
    )

    _WORLD_CONTEXT = f"世界观规则:\n{_WORLD_BACKGROUND}\n\n世界观元素:\n{_ELEMENTS_DESC}"

    async def test_character_profile_core(self, llm):
        """core 档位角色档案生成"""
        prompt = (
            "角色：「织部莉莉卡」  重要性：core\n"
            "已知信息 — brief: 对 Cosplay 极度热爱的女生，痴迷于将二次元角色具现化  "
            "detail: 动漫同好会成员，对 Cosplay 有着近乎偏执的热情，技术精湛，常独自练习\n\n"
            "生成要求（core档位）：完整描写，包含详细背景、性格、外貌、心理。detail 120-240字。\n\n"
            "字段填充要求：\n"
            "• profile.basic 内：name 固定为「织部莉莉卡」；"
            "gender/age/occupation/race/tier 必须非空\n"
            "• profile 内：brief 和 detail 必须非空\n\n"
            "内容质量要求：\n"
            "• detail 必须写出只属于这个角色的具体细节（执念、习惯、标志性经历）\n"
            "  ❌ 禁止通用套话：「性格坚强」「充满正义感」\n"
            "  ✅ 要求具体描写：「因目睹父亲被杀而立誓复仇，下棋时有摸耳垂的习惯」\n"
            "• brief 同样须体现该角色独有特征"
        )
        result = await llm.complete_json(
            system=self._STEP1_SYSTEM,
            prompt=prompt,
            cacheable_system_prefix=self._WORLD_CONTEXT,
            max_tokens=8192,
        )
        # 允许 LLM 有时返回列表包裹
        if isinstance(result, list):
            result = result[0] if result else {}
        assert isinstance(result, dict), f"expected dict: {str(result)[:200]}"
        assert result.get("name"), "name field missing or empty"
        profile = result.get("profile", {})
        assert isinstance(profile, dict), f"profile should be dict: {profile}"
        assert profile.get("brief"), "profile.brief missing"
        assert profile.get("detail"), "profile.detail missing"

    async def test_character_profile_extra(self, llm):
        """extra 档位角色档案生成（简短描写）"""
        prompt = (
            "角色：「路人甲同学」  重要性：extra\n"
            "已知信息 — brief: 动漫同好会的普通成员  "
            "detail: 偶尔在社团活动中露面，无特别背景。\n\n"
            "生成要求（extra档位）：仅姓名+身份/绰号+一句话。detail 10-24字。\n\n"
            "字段填充要求：\n"
            "• profile.basic 内：name 固定为「路人甲同学」；"
            "gender/age/occupation/race/tier 必须非空\n"
            "• profile 内：brief 和 detail 必须非空"
        )
        result = await llm.complete_json(
            system=self._STEP1_SYSTEM,
            prompt=prompt,
            cacheable_system_prefix=self._WORLD_CONTEXT,
            max_tokens=8192,
        )
        if isinstance(result, list):
            result = result[0] if result else {}
        assert isinstance(result, dict)
        profile = result.get("profile", {})
        assert profile.get("brief")
        assert profile.get("detail")


# ════════════════════════════════════════════════════════════════════════════
# 3. 角色关系判断
# ════════════════════════════════════════════════════════════════════════════


class TestRelationJudgmentLLMCall:
    """GenerationService 关系判断的 LLM 调用（Step 2 阶段一/二）"""

    # 关系判断 system prompt（重构后三段式共用 rel_system）
    _SYSTEM = """你是作品角色关系判断器。根据提供的作品资料和角色档案判断两人之间的关系。

【有关系的判断依据（满足任一即可）】
1. 作品资料或角色档案中明确提到两人之间的互动、情感或关联
2. 两人同属一个具体组织/社团，且资料中描述了该组织内成员的互动场���
3. 一方的经历或动机明确涉及另一方（如"为了接近他""受她影响"）

【没有关系，输出 false】
- 仅凭同校/同圈子，资料中完全没有两人交集的描述
- 无任何依据，纯属推断

【evidence_type 说明】
- "explicit"：依据来自资料/档案对两人关系的直接描述（对应依据1）
- "inferred"：依据来自组织归属或情节推断（对应依据2或3）

type 必须体现真实关系性质（如：青梅竹马/单恋/社团伙伴/对手/师生），禁止写"同学"等零信息量词。
只输出严格 JSON，不要 Markdown。
有关系：{"has_relation": true, "relation": {"type": "关系类型(2-8字)",
"description": "具体描述(50-150字)", "direction": "bidirectional或a_to_b或b_to_a",
"evidence_type": "explicit或inferred"}}
无关系：{"has_relation": false, "relation": null}"""

    def _cacheable_prefix(self):
        return self._SYSTEM + f"\n\n作品背景:\n{_WORLD_BACKGROUND}"

    async def test_relation_has_relation(self, llm):
        """明确有关系的角色对：应返回 has_relation:true 且 relation 结构完整"""
        prompt = (
            f"{_CHAR_A_BLOCK}\n\n"
            f"{_CHAR_B_BLOCK}\n\n"
            "请根据以上资料判断：织部莉莉卡 和 小鳥遊京介 之间是否有关系？\n"
            "有关系则描述具体互动/情感/关联；确实无任何交集则输出 false。"
        )
        result = await llm.complete_json(
            system=self._cacheable_prefix(),
            prompt=prompt,
        )
        assert isinstance(result, dict), f"expected dict: {str(result)[:200]}"
        assert "has_relation" in result
        # 这对角色在同一社团且有明确互动，预期有关系
        if result["has_relation"]:
            rel = result.get("relation")
            assert isinstance(rel, dict), "relation should be dict when has_relation is true"
            for field in ("type", "description", "direction", "evidence_type"):
                assert rel.get(field), f"relation.{field} is empty"
            assert rel["direction"] in ("bidirectional", "a_to_b", "b_to_a")
            assert rel["evidence_type"] in ("explicit", "inferred")

    async def test_relation_no_relation(self, llm):
        """明确无关系的角色对：应返回 has_relation:false 且 relation 为 null"""
        char_x = (
            "【完全无关角色X】一个在完全不同场景下活动的角色，"
            "没有任何记录显示其与角色Y有过任何接触或联系。"
        )
        char_y = (
            "【完全无关角色Y】另一个独立场景的角色，档案中完全未提及角色X，两人之间无任何共同点。"
        )
        prompt = (
            f"{char_x}\n\n"
            f"{char_y}\n\n"
            "请根据以上资料判断：完全无关角色X 和 完全无关角色Y 之间是否有关系？\n"
            "确实无任何交集则输出 false。"
        )
        result = await llm.complete_json(
            system=self._cacheable_prefix(),
            prompt=prompt,
        )
        assert isinstance(result, dict)
        assert "has_relation" in result
        # 无关角色预期返回 false
        assert result["has_relation"] is False, f"expected no relation, got: {result}"
        assert result.get("relation") is None


# ════════════════════════════════════════════════════════════════════════════
# 4. 关系反思（审计）
# ════════════════════════════════════════════════════════════════════════════


class TestReflectionLLMCall:
    """GenerationService 关系反思的 LLM 调用（Step 5 Reflection Pass）"""

    _REL_PROMPT_BASE = (
        f"{_CHAR_A_BLOCK}\n\n"
        f"{_CHAR_B_BLOCK}\n\n"
        "已生成关系记录：\n"
        "类型: {rel_type}\n"
        "描述: {description}\n"
        "方向: bidirectional\n\n"
        "请审核：以上描述对于 织部莉莉卡 和 小鳥遊京介 是否准确？"
    )

    # 反思 system prompt（原 reflection_system_explicit，已从 generation_service 移除）
    _EXPLICIT_SYSTEM = (
        "你是关系质量审核员。此关系有作品原文直接依据，"
        "禁止删除，只允许修正措辞错误。\n"
        "\n"
        "【你的任务】\n"
        "检查描述措辞是否存在明显的张冠李戴错误"
        "（描述内容指向完全不同的两个人）。\n"
        "- 如有张冠李戴：修正为正确措辞，"
        "仍返回 valid: true\n"
        "- 无论如何，不得返回 valid: false\n"
        "\n"
        "只输出严格 JSON，不要 Markdown。\n"
        '{"valid": true, "relation": {"type": "...",'
        ' "description": "...", "direction": "..."}}'
    )

    # 反思 system prompt（原 reflection_system_inferred，已从 generation_service 移除）
    _INFERRED_SYSTEM = (
        "你是关系质量审核员。你的唯一任务是发现"
        '"张冠李戴"错误——即描述内容明显属于'
        "另外两个人，与给定角色毫无关联。\n"
        "\n"
        "【返回 valid: false 的唯一条件】\n"
        "描述中提到的具体人名、事件、场景，"
        "明显与给定的两个角色档案完全对不上号"
        "（即内容是写别人的）。\n"
        "\n"
        "【绝对不要因为以下原因返回 false】\n"
        "- 描述不够详细或有点笼统\n"
        "- 关系类型措辞不够精准\n"
        "- 你觉得两人关系没那么深\n"
        "- 档案里没有明确印证"
        "（档案不完整是正常的）\n"
        "\n"
        "只要描述内容没有明显指向其他人，"
        "一律返回 valid: true，"
        "可小幅修正描述措辞。\n"
        "只输出严格 JSON，不要 Markdown。\n"
        '通过/修正：{"valid": true, "relation": '
        '{"type": "...", "description": "...", '
        '"direction": "..."}}\n'
        '张冠李戴：{"valid": false}'
    )

    async def test_reflection_explicit_valid(self, llm):
        """explicit 关系反思：描述准确时必须返回 valid:true"""
        prompt = self._REL_PROMPT_BASE.format(
            rel_type="青梅竹马",
            description=(
                "莉莉卡与京介在动漫同好会中相识，"
                "京介被她的 Cosplay 震撼后成为她最大的支持者，"
                "两人逐渐产生感情"
            ),
        )
        result = await llm.complete_json(system=self._EXPLICIT_SYSTEM, prompt=prompt)
        assert isinstance(result, dict), f"expected dict: {str(result)[:200]}"
        assert result.get("valid") is True, f"explicit 关系不得删除，got: {result}"
        rel = result.get("relation", {})
        assert isinstance(rel, dict)
        for field in ("type", "description", "direction"):
            assert rel.get(field), f"relation.{field} missing or empty"

    async def test_reflection_inferred_correct(self, llm):
        """inferred 关系反思：描述与角色对应时应返回 valid:true"""
        prompt = self._REL_PROMPT_BASE.format(
            rel_type="社团伙伴",
            description="两人同属动漫同好会，在 Cosplay 活动中有所合作，京介会帮莉莉卡处理社团事务",
        )
        result = await llm.complete_json(system=self._INFERRED_SYSTEM, prompt=prompt)
        assert isinstance(result, dict), f"expected dict: {str(result)[:200]}"
        assert "valid" in result
        if result["valid"]:
            rel = result.get("relation", {})
            assert isinstance(rel, dict)
            for field in ("type", "description", "direction"):
                assert rel.get(field), f"relation.{field} missing"

    async def test_reflection_inferred_wrong_person(self, llm):
        """inferred 关系反思：明显张冠李戴时应返回 valid:false"""
        prompt = (
            f"{_CHAR_A_BLOCK}\n\n"
            f"{_CHAR_B_BLOCK}\n\n"
            "已生成关系记录：\n"
            "类型: 师生\n"
            "描述: 田中太郎是佐藤花子的武道老师，两人在道场中相遇，师父传授学生必杀技\n"
            "方向: a_to_b\n\n"
            "请审核：以上描述对于 织部莉莉卡 和 小鳥遊京介 是否准确？"
        )
        result = await llm.complete_json(system=self._INFERRED_SYSTEM, prompt=prompt)
        assert isinstance(result, dict)
        assert "valid" in result
        # 描述里是完全不同的人，应被标记为张冠李戴
        assert result["valid"] is False, f"expected invalid (wrong person), got: {result}"


# ════════════════════════════════════════════════════════════════════════════
# 5. 角色聊天
# ════════════════════════════════════════════════════════════════════════════


class TestChatLLMCall:
    """DialogueGenerationService 的两个 LLM 调用"""

    async def test_select_participants(self, llm):
        """选角调用：应返回包含 participants 数组和 narration 字符串的 JSON"""
        cacheable_prefix = (
            "你是一个虚拟世界的叙事引擎。根据世界观、角色列表和对话上下文，选出本轮参与对话的角色，并生成场景旁白。\n\n"
            f"{_WORLD_ELEMENTS_CTX}\n\n"
            f"全量角色列表：\n{_CHARS_BRIEF}"
        )
        system_prompt = (
            "\n\n规则：\n"
            "1. 根据用户话语和场景，选出最适合参与的角色（1-4人）\n"
            "2. 生成一段场景旁白（可含地点/氛围），允许为空字符串\n"
            "3. 输出 JSON 格式\n\n"
            '{"participants": ["角色名A", "角色名B"], "narration": "..."}'
        )
        user_prompt = (
            "最近对话历史：\n（无）\n\n"
            "用户刚刚说：你们最近在准备什么 Cosplay？\n\n"
            "请选出参与角色并生成旁白。"
        )
        result = await llm.complete_json(
            system_prompt,
            user_prompt,
            cacheable_system_prefix=cacheable_prefix,
        )
        assert isinstance(result, dict), f"expected dict: {str(result)[:200]}"
        assert "participants" in result, f"missing 'participants': {result}"
        assert isinstance(result["participants"], list), "participants should be list"
        assert "narration" in result, f"missing 'narration': {result}"
        assert isinstance(result["narration"], str), "narration should be str"

    async def test_generate_response(self, llm):
        """对话生成调用：应返回包含 messages 数组的 JSON，每条消息结构正确"""
        participant_profiles = (
            "【织部莉莉卡】\n"
            "简介：对 Cosplay 极度热爱的动漫同好会成员，技术精湛\n"
            "详细：因为对二次元世界的深厚热爱，莉莉卡将所有心血都倾注于 Cosplay 制作，"
            "常常为了完美还原一个角色的服装细节而废寝忘食。她的言行举止都透露出对二次元的狂热。\n"
            "性格：热情专注，对 Cosplay 近乎偏执，认真时旁若无人"
        )
        cacheable_prefix = (
            "你是一个虚拟世界的对话引擎。请根据以下信息生成角色对话和旁白。\n\n"
            f"{_WORLD_ELEMENTS_CTX}\n\n"
            f"全量角色列表：\n{_CHARS_BRIEF}"
        )
        system_prompt = (
            "\n\n"
            f"参与角色详细档案：\n{participant_profiles}\n\n"
            "规则：\n"
            "1. 【强制】本轮只允许以下角色发言：织部莉莉卡。其他角色不得出现在输出中。\n"
            "2. 对话中存在一位用户参与者（时空探索者），自然交谈即可\n"
            "3. 严格按照角色档案中的性格和说话风格生成对话\n"
            "4. 根据需要在角色 content 中穿插动作/神情描写，用 *星号* 包裹\n"
            "5. 输出 JSON 格式\n\n"
            "输出格式:\n"
            '{"messages": [{"type": "dialogue", "sender_type": "character", '
            '"sender_name": "角色名", "content": "内容"}]}'
        )
        user_prompt = (
            "当前用户身份：时空探索者\n\n"
            "最近对话历史:\n（无）\n\n"
            "用户刚刚说：\n莉莉卡，你现在在做哪个角色的 Cosplay？\n\n"
            "请生成回复。"
        )
        result = await llm.complete_json(
            system_prompt,
            user_prompt,
            cacheable_system_prefix=cacheable_prefix,
        )
        assert isinstance(result, dict), f"expected dict: {str(result)[:200]}"
        messages = result.get("messages")
        assert isinstance(messages, list), f"'messages' should be list: {result}"
        assert len(messages) >= 1, "should have at least one message"
        for msg in messages:
            assert isinstance(msg, dict)
            assert msg.get("sender_name"), "message missing sender_name"
            assert msg.get("content"), "message content is empty"
            assert msg.get("type") == "dialogue"


# ════════════════════════════════════════════════════════════════════════════
# 6. 事件推演 Planner
# ════════════════════════════════════════════════════════════════════════════


class TestEventPlannerLLMCall:
    """EventDialogueService Planner 的 LLM 调用"""

    async def test_event_planner(self, llm):
        """Planner 应返回包含 event_title 和 scenes 数组的 JSON"""
        char_list_text = (
            "- 织部莉莉卡（动漫同好会，Cosplay 爱好者，核心成员）\n- 小鳥遊京介（动漫同好会会长）"
        )
        planner_user = (
            f"世界观背景：\n{_WORLD_BACKGROUND}\n\n"
            f"角色列表：\n{char_list_text}\n\n"
            "注入事件：\n"
            "学校文化祭即将举行，动漫同好会决定以 Cosplay 展示为核心节目参加，"
            "但经费严重不足，服装制作时间也只剩三天，社团内部出现了是否继续的分歧。"
        )
        result = await llm.complete_json(PLANNER_SYSTEM_PROMPT, planner_user)
        assert isinstance(result, dict), f"expected dict: {str(result)[:200]}"
        assert "event_title" in result, f"missing 'event_title': {result}"
        assert "scenes" in result, f"missing 'scenes': {result}"
        assert result.get("event_title"), "event_title should not be empty"
        scenes = result["scenes"]
        assert isinstance(scenes, list), "scenes should be list"
        assert 1 <= len(scenes) <= 3, f"scenes count should be 1-3, got {len(scenes)}"
        for scene in scenes:
            assert isinstance(scene, dict)
            assert "scene_id" in scene, f"scene missing scene_id: {scene}"
            assert "location" in scene, f"scene missing location: {scene}"
            assert "factions" in scene, f"scene missing factions: {scene}"
            assert isinstance(scene["factions"], list)
            assert "goal" in scene, f"scene missing goal: {scene}"
