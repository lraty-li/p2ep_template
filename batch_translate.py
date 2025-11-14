#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 GPT API 批量翻译 texts.json 中的 text 字段
翻译结果保存到新文件 texts_translated.json，不修改原文件
支持进度记录和失败重试功能
"""

import json
import sys
import time
import copy
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# 默认路径配置
DEFAULT_TEXTS_FILE = Path("texts/texts.json")
DEFAULT_API_KEY_FILE = Path("api_key.txt")
DEFAULT_PROGRESS_FILE = Path("texts/translate_progress.json")

# API 配置
API_BASE_URL = "https://api.vveai.com/v1/chat/completions"
MODEL = "gpt-4.1-mini"  # 或 "gpt-3.5-turbo", "gpt-4" 等
MAX_RETRIES = 3
RETRY_DELAY = 1  # 秒
CONTEXT_MAX_CHARS = 4096  # 上下文最大字符数（包括整个 prompt）
CONTEXT_MAX_ITEMS = 5  # 前后文最多收集的条数（每条）
MAX_WORKERS = 10  # 最大并发线程数
MAX_TASKS = None  # 最大任务数限制（None 表示不限制，可以设置为数字如 100）


def load_api_key(api_key_file: Path) -> Optional[str]:
    """从文件加载 API 密钥"""
    if api_key_file.exists():
        with open(api_key_file, 'r', encoding='utf-8') as f:
            key = f.read().strip()
            if key:
                return key
    return None


def load_progress(progress_file: Path) -> Dict[str, Any]:
    """加载进度记录文件"""
    if progress_file.exists():
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: 无法读取进度文件 {progress_file}: {e}")
            return {}
    return {}


def save_progress(progress_file: Path, progress_data: Dict[str, Any]):
    """保存进度记录文件"""
    try:
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"警告: 无法保存进度文件 {progress_file}: {e}")


def init_progress(texts_file: Path, output_file: Path) -> Dict[str, Any]:
    """初始化进度记录结构"""
    return {
        "version": "1.2",  # 更新版本号，使用 id 而不是 idx
        "source_file": str(texts_file),
        "output_file": str(output_file),
        "completed": {},  # {"file_key": [id1, id2, ...]} - 存储 id，不存储翻译文本
        "failed": {},     # {"file_key": [id1, id2, ...]} - 存储 id，不存储任何其他信息
        "stats": {
            "total": 0,
            "completed": 0,
            "failed": 0
        }
    }


def load_terms(terms_file: Path) -> Dict[str, str]:
    """从文件加载术语表"""
    if terms_file.exists():
        try:
            with open(terms_file, 'r', encoding='utf-8') as f:
                terms = json.load(f)
                # 过滤掉空值
                return {k: v for k, v in terms.items() if v and v.strip()}
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: 无法读取术语表文件 {terms_file}: {e}")
            return {}
    return {}


def save_output_files(output_file: Path, texts_data: Dict[str, Any], texts_dict: Dict[str, Any], speakers_dict: Dict[str, str], file_lock: threading.Lock = None):
    """保存输出文件"""
    def _save():
        # 确定保存的数据结构
        save_data = texts_data if ("texts" in texts_data or "speakers" in texts_data) else texts_dict
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        
        # 如果是直接结构且有speakers，也保存到单独的speakers_translated.json
        if speakers_dict and not ("texts" in texts_data or "speakers" in texts_data):
            speakers_output_file = output_file.parent / "speakers_translated.json"
            try:
                with open(speakers_output_file, 'w', encoding='utf-8') as f:
                    json.dump(speakers_dict, f, ensure_ascii=False, indent=2)
            except Exception:
                pass  # 定期保存时静默失败
    
    if file_lock:
        with file_lock:
            _save()
    else:
        _save()


def get_context(texts_list: List[Dict[str, Any]], current_idx: int, original_texts_list: List[Dict[str, Any]] = None, speakers_dict: Dict[str, str] = None, max_chars: int = CONTEXT_MAX_CHARS, max_items: int = CONTEXT_MAX_ITEMS) -> Tuple[List[str], List[str]]:
    """
    获取当前文本的前后文上下文（包含说话人信息）
    前后文平均分配字符数，交替收集以保持平衡
    
    Args:
        texts_list: 文本列表（当前翻译状态）
        current_idx: 当前文本的索引
        original_texts_list: 原文列表（可选，用于获取未翻译的上下文）
        speakers_dict: 说话人翻译字典（可选，用于获取翻译后的说话人名称）
        max_chars: 上下文最大字符数（前后文总字符数）
        max_items: 前后文最多收集的条数（每条）
    
    Returns:
        (前文列表, 后文列表) - 每个列表包含格式为"说话人：文本"的字符串
    """
    if not texts_list or current_idx < 0 or current_idx >= len(texts_list):
        return [], []
    
    # 获取说话人名称（优先使用翻译后的，如果没有则使用原文）
    def get_speaker_name(speaker_key: str) -> str:
        if not speaker_key:
            return ""
        if speakers_dict and speaker_key in speakers_dict:
            translated_speaker_raw = speakers_dict[speaker_key]
            translated_speaker = (translated_speaker_raw.strip() if translated_speaker_raw else "") if translated_speaker_raw is not None else ""
            if translated_speaker:
                return translated_speaker
        return speaker_key
    
    # 获取前后文的文本和说话人（优先使用已翻译的，如果没有则使用原文）
    def get_text_and_speaker_at_idx(idx: int) -> Tuple[str, str]:
        if 0 <= idx < len(texts_list):
            item = texts_list[idx]
            # 获取说话人
            speaker_key_raw = item.get("speaker")
            speaker_key = (speaker_key_raw.strip() if speaker_key_raw else "") if speaker_key_raw is not None else ""
            speaker_name = get_speaker_name(speaker_key) if speaker_key else ""
            
            # 优先使用已翻译的文本
            translated_raw = item.get("text")
            translated = (translated_raw.strip() if translated_raw else "") if translated_raw is not None else ""
            if translated:
                return translated, speaker_name
            # 如果没有翻译，尝试使用原文
            if original_texts_list and idx < len(original_texts_list):
                original_item = original_texts_list[idx]
                original_text_raw = original_item.get("text")
                original_text = (original_text_raw.strip() if original_text_raw else "") if original_text_raw is not None else ""
                if original_text:
                    # 如果原文中没有说话人信息，尝试从原文项中获取
                    if not speaker_name:
                        original_speaker_key_raw = original_item.get("speaker")
                        original_speaker_key = (original_speaker_key_raw.strip() if original_speaker_key_raw else "") if original_speaker_key_raw is not None else ""
                        speaker_name = get_speaker_name(original_speaker_key) if original_speaker_key else ""
                    return original_text, speaker_name
        return "", ""
    
    # 收集前文和后文（格式：说话人：文本）
    before_texts = []
    after_texts = []
    before_chars = 0  # 前文字符数
    after_chars = 0  # 后文字符数
    total_chars = 0  # 前后文总字符数
    
    # 准备前后文的索引列表
    before_indices = list(range(current_idx - 1, -1, -1))
    after_indices = list(range(current_idx + 1, len(texts_list)))
    
    # 交替收集前后文，保持字符数大致平衡
    before_idx = 0
    after_idx = 0
    
    while total_chars < max_chars:
        # 决定收集前文还是后文（优先收集字符数较少的一边，保持平衡）
        collect_before = False
        if before_idx < len(before_indices) and after_idx < len(after_indices):
            # 如果前文字符数少于或等于后文，优先收集前文；否则收集后文
            collect_before = (before_chars <= after_chars)
        elif before_idx < len(before_indices):
            collect_before = True
        elif after_idx < len(after_indices):
            collect_before = False
        else:
            break  # 没有更多文本可收集
        
        # 检查条数限制
        if collect_before:
            if len(before_texts) >= max_items:
                # 前文达到条数限制，尝试收集后文
                if after_idx >= len(after_indices) or len(after_texts) >= max_items:
                    break
                collect_before = False
        else:
            if len(after_texts) >= max_items:
                # 后文达到条数限制，尝试收集前文
                if before_idx >= len(before_indices) or len(before_texts) >= max_items:
                    break
                collect_before = True
        
        # 收集前文
        if collect_before and before_idx < len(before_indices):
            i = before_indices[before_idx]
            before_idx += 1
            
            text, speaker = get_text_and_speaker_at_idx(i)
            if not text:
                continue
            
            # 格式化：说话人：文本
            if speaker:
                formatted_text = f"{speaker}：{text}"
            else:
                formatted_text = text
            
            text_len = len(formatted_text)
            # 检查总字符数限制
            if total_chars + text_len > max_chars:
                break
            
            before_texts.insert(0, formatted_text)
            before_chars += text_len
            total_chars += text_len
        
        # 收集后文
        elif not collect_before and after_idx < len(after_indices):
            i = after_indices[after_idx]
            after_idx += 1
            
            text, speaker = get_text_and_speaker_at_idx(i)
            if not text:
                continue
            
            # 格式化：说话人：文本
            if speaker:
                formatted_text = f"{speaker}：{text}"
            else:
                formatted_text = text
            
            text_len = len(formatted_text)
            # 检查总字符数限制
            if total_chars + text_len > max_chars:
                break
            
            after_texts.append(formatted_text)
            after_chars += text_len
            total_chars += text_len
        else:
            break  # 无法继续收集
    
    return before_texts, after_texts


def get_speaker_context(speaker_key: str, texts_dict: Dict[str, List[Dict[str, Any]]], original_texts_dict: Dict[str, List[Dict[str, Any]]] = None, max_texts: int = 5) -> List[str]:
    """
    获取某个 speaker 对应的前几条文本作为上下文
    
    Args:
        speaker_key: 说话人键
        texts_dict: 文本字典（当前翻译状态）
        original_texts_dict: 原文字典（可选，用于获取未翻译的文本）
        max_texts: 最多返回的文本数量
    
    Returns:
        文本列表（格式：说话人：文本，如果没有说话人则只有文本）
    """
    context_texts = []
    
    # 遍历所有文件，查找使用该 speaker 的文本项
    for file_key, file_texts in texts_dict.items():
        if len(context_texts) >= max_texts:
            break
        
        # 获取原文列表（如果存在）
        original_file_texts = original_texts_dict.get(file_key, []) if original_texts_dict else []
        
        # 遍历该文件的所有文本项
        for idx, item in enumerate(file_texts):
            if len(context_texts) >= max_texts:
                break
            
            # 检查是否使用该 speaker
            item_speaker_raw = item.get("speaker")
            item_speaker = (item_speaker_raw.strip() if item_speaker_raw else "") if item_speaker_raw is not None else ""
            if item_speaker != speaker_key:
                continue
            
            # 获取文本（优先使用已翻译的）
            text_raw = item.get("text")
            text = (text_raw.strip() if text_raw else "") if text_raw is not None else ""
            if not text and original_file_texts and idx < len(original_file_texts):
                original_item = original_file_texts[idx]
                original_text_raw = original_item.get("text")
                text = (original_text_raw.strip() if original_text_raw else "") if original_text_raw is not None else ""
            
            if text:
                # 格式化：说话人：文本（但这里说话人就是我们要翻译的，所以只显示文本）
                context_texts.append(text)
    
    return context_texts[:max_texts]


def extract_relevant_terms(text: str, terms: Dict[str, str], max_terms: int = 20) -> Dict[str, str]:
    """
    从文本中提取相关的术语（只返回文本中出现的术语）
    
    Args:
        text: 要翻译的文本
        terms: 完整的术语表
        max_terms: 最多返回的术语数量（避免提示过长）
    
    Returns:
        相关的术语字典
    """
    if not terms or not text:
        return {}
    
    relevant = {}
    # 按术语长度从长到短排序，优先匹配长术语
    sorted_terms = sorted(terms.items(), key=lambda x: len(x[0]), reverse=True)
    
    for original, translated in sorted_terms:
        if original in text:
            relevant[original] = translated
            if len(relevant) >= max_terms:
                break
    
    return relevant


def calculate_prompt_base_chars(text: str, terms: Dict[str, str] = None, speaker: str = None) -> int:
    """
    计算 prompt 基础部分的字符数（system message + user message 基础部分，不包括上下文）
    
    Args:
        text: 要翻译的文本
        terms: 术语表
        speaker: 说话人
    
    Returns:
        基础部分的字符数
    """
    # 提取相关术语
    relevant_terms = extract_relevant_terms(text, terms or {}, max_terms=20)
    
    # 构建术语表部分
    terms_section = ""
    if relevant_terms:
        terms_list = []
        for original, translated in sorted(relevant_terms.items()):
            terms_list.append(f'  "{original}" → "{translated}"')
        terms_text = "\n".join(terms_list)
        terms_section = f"""
【术语表（必须严格遵守）】
以下术语在文本中出现，翻译时必须严格使用这些标准翻译，不得自行翻译或更改：
{terms_text}

**重要**：如果文本中出现上述术语，必须使用对应的中文翻译。
"""
    
    # System message 基础部分（固定内容）
    system_base = """
你正在翻译《女神异闻录2 罚》（Persona 2: Eternal Punishment）的文本。

【翻译总则】
1. 所有翻译输出必须为**自然流畅的简体中文**。
2. **绝对禁止音译罗马字母**（例如：Maya、Katsuya、Fujii、Okamura 等全部禁止出现）。
3. 人名、角色名、地名、组织名：
   - 若原文包含汉字：**保留汉字原文作为最终译名**。
   - 若原文仅为假名且已有通用中文译名：采用通用译名。
   - 若无通用译名：保留假名形式，不得转写为罗马字母。
4. 不允许擅自更改、提升、弱化或戏谑语义。禁止添加感情色彩和外号。例如：
   - "新人"不可擅自翻为"新人大佬"
   - "うらら"不可翻成"晴朗明媚"
5. 职称、身份、关系称谓需符合中文自然表达，保持正式、准确，不得英文化或乱加"Mr."、"Editor-in-Chief"等非原文信息。
   - 例："編集長" → "主编"
   - 不得翻译为 "Editor-in-Chief"
6. 只输出翻译，不添加解释、注释或额外说明。

【表达要求】
1. 对话用语气自然口语化，但不改变原文语气。
2. 同一角色、称呼在全文中必须保持一致。
3. 不可输出词典式映射表，翻译任务中仅处理给出的实际文本。
- 日语称谓（先生、校長、編集長等）必须根据原文语义和上下文翻译为中文自然称呼。
- 保留角色职业/身份，不允许泛化或硬套"先生""Mr."、"Editor-in-Chief"等。
- 翻译每条文本时，模型必须参考前后上下文、角色身份、情绪和场景。
- 代词、称谓和动作描述必须结合上下文理解。


【重点禁止项（必须严格执行）】
- 禁止出现任何罗马字母拼写的人名：（如 Maya / Katsuya / Fujii / Kashiwara等）
- 禁止擅自意译增加形容色彩：（如"うらら"翻成"晴朗明媚"）
- 禁止将汉字人名改成其他汉字：（如"黛ゆきの"绝不可变成"真弓雪乃"）
- 禁止英文化称谓：（如 "Mr. Saeko"、"Editor-in-Chief"、"Mr. Asō" 等）

【固有代号指令】
游戏中以全大写方式呈现的代号（如：ＪＯＫＥＲ、ＮＡＴＩＯＮＡＬＦＬＡＧ 等），视为专用符号单位。
此类词汇：
1) 不翻译；
2) 不加注音；
3) 不转换字形和大小写；
4) **严格按原文保留**。

{terms_section}

最终目标：在不破坏原文意义和角色特征前提下，使翻译自然清晰、统一、可读。
    """
    
    system_message = system_base.format(terms_section=terms_section)
    
    # User message 基础部分（新的结构：上下文信息和翻译文本分开）
    # 上下文信息部分（如果有说话人）
    context_message_base = ""
    if speaker:
        context_message_base = f"以下是上下文信息（仅用于理解语境和角色身份，不要翻译这些内容）：\n【说话人】：{speaker}"
    
    # 翻译文本部分
    translate_message_base = f"请翻译以下文本（只输出翻译后的纯文本内容）：\n{text}"
    
    # 计算总字符数（system message + 上下文 message + 翻译 message）
    total_chars = len(system_message)
    if context_message_base:
        total_chars += len(context_message_base)
    total_chars += len(translate_message_base)
    
    return total_chars


def translate_text(text: str, api_key: str, source_lang: str = "日语", target_lang: str = "简体中文", terms: Dict[str, str] = None, context_before: List[str] = None, context_after: List[str] = None, speaker: str = None, is_speaker_translation: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """
    使用 GPT API 翻译文本
    
    Args:
        text: 要翻译的文本
        api_key: API 密钥
        source_lang: 源语言
        target_lang: 目标语言
        terms: 术语表
        context_before: 前文列表（格式：说话人：文本）或 speaker 对应的文本列表
        context_after: 后文列表（格式：说话人：文本）
        speaker: 当前文本的说话人（可选）
        is_speaker_translation: 是否为翻译 speaker（用于调整上下文提示）
    
    返回 (翻译后的文本, 错误信息)
    成功时返回 (translated_text, None)
    失败时返回 (None, error_message)
    """
    if terms is None:
        terms = {}
    if context_before is None:
        context_before = []
    if context_after is None:
        context_after = []
    
    try:
        import requests
    except ImportError:
        error_msg = "需要安装 requests 库: pip install requests"
        print(f"错误: {error_msg}")
        return None, error_msg
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 提取文本中相关的术语（最多20个，避免提示过长）
    relevant_terms = extract_relevant_terms(text, terms, max_terms=20)
    
    # 构建术语表部分（只在有相关术语时添加）
    terms_section = ""
    if relevant_terms:
        terms_list = []
        for original, translated in sorted(relevant_terms.items()):
            terms_list.append(f'  "{original}" → "{translated}"')
        terms_text = "\n".join(terms_list)
        terms_section = f"""
【术语表（必须严格遵守）】
以下术语在文本中出现，翻译时必须严格使用这些标准翻译，不得自行翻译或更改：
{terms_text}

**重要**：如果文本中出现上述术语，必须使用对应的中文翻译。
"""
    
    # System message: 翻译规则和原则（作为系统级指令）
    system_message = f"""
你正在翻译《女神异闻录2 罚》（Persona 2: Eternal Punishment）的文本。

【翻译总则】
1. 所有翻译输出必须为**自然流畅的简体中文**。
2. **绝对禁止音译罗马字母**（例如：Maya、Katsuya、Fujii、Okamura 等全部禁止出现）。
3. 人名、角色名、地名、组织名：
   - 若原文包含汉字：**保留汉字原文作为最终译名**。
   - 若原文仅为假名且已有通用中文译名：采用通用译名。
   - 若无通用译名：保留假名形式，不得转写为罗马字母。
4. 不允许擅自更改、提升、弱化或戏谑语义。禁止添加感情色彩和外号。例如：
   - “新人”不可擅自翻为“新人大佬”
   - “うらら”不可翻成“晴朗明媚”
5. 职称、身份、关系称谓需符合中文自然表达，保持正式、准确，不得英文化或乱加“Mr.”、“Editor-in-Chief”等非原文信息。
   - 例：“編集長” → “主编”
   - 不得翻译为 “Editor-in-Chief”
6. 只输出翻译，不添加解释、注释或额外说明。

【表达要求】
1. 对话用语气自然口语化，但不改变原文语气。
2. 同一角色、称呼在全文中必须保持一致。
3. 不可输出词典式映射表，翻译任务中仅处理给出的实际文本。
- 日语称谓（先生、校長、編集長等）必须根据原文语义和上下文翻译为中文自然称呼。
- 保留角色职业/身份，不允许泛化或硬套“先生”“Mr.”、“Editor-in-Chief”等。
- 翻译每条文本时，模型必须参考前后上下文、角色身份、情绪和场景。
- 代词、称谓和动作描述必须结合上下文理解。


【重点禁止项（必须严格执行）】
- 禁止出现任何罗马字母拼写的人名：（如 Maya / Katsuya / Fujii / Kashiwara等）
- 禁止擅自意译增加形容色彩：（如“うらら”翻成“晴朗明媚”）
- 禁止将汉字人名改成其他汉字：（如“黛ゆきの”绝不可变成“真弓雪乃”）
- 禁止英文化称谓：（如 “Mr. Saeko”、“Editor-in-Chief”、“Mr. Asō” 等）

【固有代号指令】
游戏中以全大写方式呈现的代号（如：ＪＯＫＥＲ、ＮＡＴＩＯＮＡＬＦＬＡＧ 等），视为专用符号单位。
此类词汇：
1) 不翻译；
2) 不加注音；
3) 不转换字形和大小写；
4) **严格按原文保留**。

{terms_section}

最终目标：在不破坏原文意义和角色特征前提下，使翻译自然清晰、统一、可读。




    """
    
    # 构建消息列表
    messages = [
        {
            "role": "system",
            "content": system_message
        }
    ]
    
    # 如果有说话人信息或上下文，先作为单独的 user message 发送（仅用于理解，不翻译）
    context_info_parts = []
    if speaker:
        context_info_parts.append(f"【说话人】：{speaker}")
    
    if context_before or context_after:
        if context_before:
            if is_speaker_translation:
                context_info_parts.append("【该说话人对应的文本示例】")
            else:
                context_info_parts.append("【前文】")
            for i, ctx_text in enumerate(context_before, 1):
                context_info_parts.append(f"{i}. {ctx_text}")
        if context_after:
            context_info_parts.append("【后文】")
            for i, ctx_text in enumerate(context_after, 1):
                context_info_parts.append(f"{i}. {ctx_text}")
    
    # 如果有上下文信息，先发送一个 user message 提供上下文
    if context_info_parts:
        context_message = "以下是上下文信息（仅用于理解语境和角色身份，不要翻译这些内容）：\n" + "\n".join(context_info_parts)
        messages.append({
            "role": "user",
            "content": context_message
        })
    
    # 最后发送要翻译的文本
    messages.append({
        "role": "user",
        "content": f"请翻译以下文本（只输出翻译后的纯文本内容）：\n{text}"
    })
    
    data = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.7,
        "TopP":0.8,
         "TopK":20,
         "MinP":0,
           "stream": False,
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(API_BASE_URL, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            
            # 检查响应内容
            response_text = response.text
            if not response_text.strip():
                error_msg = "API 返回空响应"
                print(f"  错误: {error_msg}")
                if attempt < MAX_RETRIES - 1:
                    print(f"  重试 {attempt + 1}/{MAX_RETRIES}")
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                else:
                    return None, error_msg
            
            try:
                result = response.json()
            except json.JSONDecodeError as e:
                error_msg = f"API 返回的不是有效 JSON (状态码: {response.status_code})"
                print(f"  错误: {error_msg}")
                print(f"  响应内容: {response_text[:200]}...")
                if attempt < MAX_RETRIES - 1:
                    print(f"  重试 {attempt + 1}/{MAX_RETRIES}")
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                else:
                    return None, error_msg
            
            translated_text = result["choices"][0]["message"]["content"].strip()
            
            # 清理可能的引号
            if translated_text.startswith('"') and translated_text.endswith('"'):
                translated_text = translated_text[1:-1]
            
            return translated_text, None
            
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if attempt < MAX_RETRIES - 1:
                print(f"  请求失败，重试 {attempt + 1}/{MAX_RETRIES}: {e}")
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"  翻译失败: {e}")
                return None, error_msg
        except (KeyError, IndexError) as e:
            error_msg = f"解析响应失败: {e}"
            print(f"  {error_msg}")
            print(f"  响应结构: {result if 'result' in locals() else 'N/A'}")
            return None, error_msg
    
    return None, "达到最大重试次数"


def batch_translate_texts(texts_file: Path, api_key_file: Path, output_file: Path = None, dry_run: bool = False, debug: bool = False, max_workers: int = 5, debug_limit: int = 5, progress_file: Path = None, resume: bool = True, retry_failed: bool = False, max_tasks: int = None):
    """
    批量翻译 texts.json 中的文本，保存到新文件
    
    Args:
        texts_file: texts.json 文件路径（源文件）
        api_key_file: API 密钥文件路径
        output_file: 输出文件路径（如果为 None，则自动生成）
        dry_run: 如果为 True，只显示统计信息，不实际翻译
        debug: 如果为 True，仅翻译指定数量的文本
        max_workers: 最大并发线程数
        debug_limit: 调试模式下限制翻译的任务数（默认: 5）
        progress_file: 进度记录文件路径（如果为 None，则自动生成）
        resume: 如果为 True，从进度文件恢复已翻译的文本
        retry_failed: 如果为 True，重试之前失败的文本
        max_tasks: 最大任务数限制（None 表示不限制）
    """
    # 加载 API 密钥
    api_key = load_api_key(api_key_file)
    if not api_key and not dry_run:
        print(f"错误: 未找到 API 密钥文件 {api_key_file}")
        print(f"请创建该文件并填入 API 密钥")
        return
    
    # 确定输出文件路径
    if output_file is None:
        # 自动生成输出文件名：texts_translated.json
        output_file = texts_file.parent / "texts_translated.json"
    
    # 确定进度文件路径
    if progress_file is None:
        progress_file = texts_file.parent / "translate_progress.json"
    
    print(f"正在读取: {texts_file}")
    print(f"输出文件: {output_file}")
    print(f"进度文件: {progress_file}")
    
    # 读取原文 texts.json
    with open(texts_file, 'r', encoding='utf-8') as f:
        original_texts_data = json.load(f)
    
    # 深拷贝原文数据，用于比较和获取原文
    original_texts_data = copy.deepcopy(original_texts_data)
    
    # 处理原文结构
    if "texts" in original_texts_data and "speakers" in original_texts_data:
        original_texts_dict = original_texts_data.get("texts", {})
        original_speakers_dict = original_texts_data.get("speakers", {})
    else:
        original_texts_dict = original_texts_data
        original_speakers_dict = {}
    
    # 加载或初始化进度记录
    if resume or retry_failed:
        progress_data = load_progress(progress_file)
        if not progress_data:
            progress_data = init_progress(texts_file, output_file)
            print("创建新的进度记录文件")
        else:
            print(f"加载进度记录: 已完成 {progress_data.get('stats', {}).get('completed', 0)} 个，失败 {progress_data.get('stats', {}).get('failed', 0)} 个")
    else:
        progress_data = init_progress(texts_file, output_file)
        print("不使用进度记录（从头开始）")
    
    # 加载已翻译的译文（从输出文件，如果存在）
    # 这是我们要维护和更新的译文数据
    if output_file.exists():
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                translated_texts_data = json.load(f)
            print(f"从输出文件加载已翻译的译文: {output_file}")
        except Exception as e:
            print(f"警告: 无法读取输出文件，将从头开始: {e}")
            translated_texts_data = None
    else:
        translated_texts_data = None
    
    # 初始化译文数据结构（基于原文结构）
    if translated_texts_data:
        # 如果输出文件存在，使用其结构
        if "texts" in translated_texts_data and "speakers" in translated_texts_data:
            texts_dict = translated_texts_data.get("texts", {})
            speakers_dict = translated_texts_data.get("speakers", {})
        else:
            texts_dict = translated_texts_data
            speakers_dict = {}
        
        # 确保所有原文中的文件都在译文中（用原文填充缺失的部分）
        for file_key, file_texts in original_texts_dict.items():
            if file_key not in texts_dict:
                # 如果译文中没有这个文件，用原文初始化
                texts_dict[file_key] = copy.deepcopy(file_texts)
            else:
                # 如果译文中已有这个文件，确保所有条目都存在（用原文填充缺失的）
                for idx, original_item in enumerate(file_texts):
                    if idx >= len(texts_dict[file_key]):
                        texts_dict[file_key].append(copy.deepcopy(original_item))
                    else:
                        # 如果译文中的文本为空或与原文相同，保持原文（待翻译）
                        translated_text = texts_dict[file_key][idx].get("text", "").strip()
                        original_text = original_item.get("text", "").strip()
                        if not translated_text or translated_text == original_text:
                            # 保持结构，但文本保持原文（待翻译）
                            texts_dict[file_key][idx] = copy.deepcopy(original_item)
    else:
        # 如果输出文件不存在，用原文初始化译文
        texts_dict = copy.deepcopy(original_texts_dict)
        speakers_dict = copy.deepcopy(original_speakers_dict) if original_speakers_dict else {}
    
    # 如果 speakers_dict 为空，尝试从单独的 speakers.json 文件读取
    if not speakers_dict:
        speakers_file = texts_file.parent / "speakers.json"
        if speakers_file.exists():
            try:
                with open(speakers_file, 'r', encoding='utf-8') as f:
                    speakers_dict = json.load(f)
                print(f"从单独文件加载 speakers: {speakers_file}")
            except Exception as e:
                print(f"警告: 无法读取 speakers.json: {e}")
    
    # 优先从 speakers_translated.json 加载已翻译的值（如果存在）
    speakers_translated_file = texts_file.parent / "speakers_translated.json"
    if speakers_translated_file.exists() and speakers_dict:
        try:
            with open(speakers_translated_file, 'r', encoding='utf-8') as f:
                speakers_translated = json.load(f)
            # 更新 speakers_dict，使用已翻译的值（只更新非空值）
            updated_count = 0
            for key, translated_value in speakers_translated.items():
                if key in speakers_dict and translated_value and translated_value.strip():
                    speakers_dict[key] = translated_value
                    updated_count += 1
            if updated_count > 0:
                print(f"从 {speakers_translated_file} 恢复了 {updated_count} 个已翻译的 speakers")
        except Exception as e:
            print(f"警告: 无法读取 speakers_translated.json: {e}")
    
    # 加载术语表（从 speakers_translated copy.json）
    terms_file = texts_file.parent / "speakers_translated copy.json"
    terms = load_terms(terms_file)
    if terms:
        print(f"已加载术语表: {len(terms)} 个术语（从 {terms_file}）")
    else:
        print(f"未找到术语表文件 {terms_file}，将不使用术语表")
    
    # 从进度文件读取已完成和失败的索引
    completed_dict = progress_data.get("completed", {})
    failed_dict = progress_data.get("failed", {})
    
    total_texts = 0
    translated_count = 0
    empty_count = 0
    
    # 统计文本数量
    for file_key, file_texts in texts_dict.items():
        for item in file_texts:
            text_raw = item.get("text")
            text = (text_raw.strip() if text_raw else "") if text_raw is not None else ""
            if text:
                total_texts += 1
            else:
                empty_count += 1
    
    print(f"\n统计信息:")
    print(f"  文件数: {len(texts_dict)}")
    print(f"  需要翻译的文本: {total_texts}")
    print(f"  空文本: {empty_count}")
    if speakers_dict:
        speakers_total = len(speakers_dict)
        speakers_translated = sum(1 for v in speakers_dict.values() if v and v.strip())
        speakers_need_translate = speakers_total - speakers_translated
        print(f"  Speakers 总数: {speakers_total}")
        print(f"  Speakers 已翻译: {speakers_translated}")
        print(f"  Speakers 待翻译: {speakers_need_translate}")
    
    if dry_run:
        print("\n（仅预览模式，未实际翻译）")
        return
    
    # 先翻译 speakers（如果有）
    speakers_completed_count = 0
    speakers_failed_count = 0
    
    if speakers_dict:
        # 创建 speaker_keys 列表用于索引映射（不存储到 progress）
        speaker_keys = list(speakers_dict.keys())
        
        # 收集需要翻译的 speakers（根据 speakers_translated.json 中的值判断）
        speakers_to_translate = []
        
        for idx, speaker_key in enumerate(speaker_keys):
            speaker_value = speakers_dict[speaker_key]
            # 如果已经有翻译（不为空），跳过
            if speaker_value and speaker_value.strip():
                continue
            
            speakers_to_translate.append(idx)
        
        if speakers_to_translate:
            print(f"\n开始翻译 speakers...")
            print(f"需要翻译的 speakers: {len(speakers_to_translate)} 个")
            print(f"使用模型: {MODEL}")
            print(f"并发线程数: {max_workers}")
            
            # 线程安全的计数器和锁
            speakers_translated_count_lock = threading.Lock()
            speakers_completed_count_local = 0
            speakers_failed_count_local = 0
            speakers_file_lock = threading.Lock()
            speakers_progress_lock = threading.Lock()
            
            def translate_speaker_task(speaker_idx):
                """翻译单个 speaker 的任务函数"""
                nonlocal speakers_completed_count_local, speakers_failed_count_local
                
                speaker_key = speaker_keys[speaker_idx]
                
                # 获取该 speaker 对应的前几条文本作为上下文
                speaker_context = get_speaker_context(speaker_key, texts_dict, original_texts_dict, max_texts=5)
                
                context_info = ""
                if speaker_context:
                    context_info = f" [上下文: {len(speaker_context)}条文本]"
                
                print(f"  [{speaker_idx+1}/{len(speaker_keys)}] 翻译 speaker: {speaker_key[:50]}...{context_info}")
                
                # 将上下文转换为字符串列表格式（用于 translate_text 的 context_before 参数）
                context_before = speaker_context if speaker_context else None
                
                translated, error_msg = translate_text(speaker_key, api_key, terms=terms, context_before=context_before, is_speaker_translation=True)
                
                with speakers_progress_lock:
                    if translated:
                        speakers_dict[speaker_key] = translated
                        speakers_completed_count_local += 1
                        print(f"    [{speaker_idx+1}] 完成: {translated[:50]}...")
                    else:
                        speakers_failed_count_local += 1
                        print(f"    [{speaker_idx+1}] 翻译失败: {error_msg or '未知错误'}")
                
                return True
            
            # 调试模式限制任务数量
            if debug:
                speakers_to_translate = speakers_to_translate[:debug_limit]
                print(f"调试模式: 限制任务数为 {len(speakers_to_translate)}")
            
            # 使用线程池并发翻译
            speakers_save_interval = max(1, len(speakers_to_translate) // 20)  # 每完成约5%的任务保存一次
            speakers_interrupted = False
            
            try:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # 提交所有任务
                    future_to_speaker = {executor.submit(translate_speaker_task, idx): idx for idx in speakers_to_translate}
                    
                    # 处理完成的任务
                    try:
                        completed_speakers_count = 0
                        for future in as_completed(future_to_speaker):
                            speaker_idx = future_to_speaker[future]
                            try:
                                result = future.result()
                                if result is False:
                                    # 调试模式达到限制，取消剩余任务
                                    if debug:
                                        print(f"调试模式: 已达到限制，取消剩余任务")
                                        for f in future_to_speaker:
                                            f.cancel()
                                        break
                            except Exception as e:
                                print(f"    [{speaker_idx+1}] 任务执行异常: {e}")
                            
                            # 定期保存进度
                            completed_speakers_count += 1
                            if completed_speakers_count % speakers_save_interval == 0 or completed_speakers_count == len(speakers_to_translate):
                                # 构建要保存的译文数据
                                if "texts" in original_texts_data or "speakers" in original_texts_data:
                                    # 嵌套结构
                                    save_data = {
                                        "texts": texts_dict,
                                        "speakers": speakers_dict
                                    }
                                else:
                                    # 直接结构
                                    save_data = texts_dict
                                
                                save_output_files(output_file, save_data, texts_dict, speakers_dict, speakers_file_lock)
                                
                                # 保存进度文件
                                with speakers_progress_lock:
                                    save_progress(progress_file, progress_data)
                    except KeyboardInterrupt:
                        speakers_interrupted = True
                        print("\n\n收到中断信号 (CTRL+C)，正在优雅地关闭...")
                        print("正在取消未开始的 speaker 任务...")
                        
                        # 取消所有未完成的任务
                        cancelled_count = 0
                        for future in future_to_speaker:
                            if not future.done():
                                future.cancel()
                                cancelled_count += 1
                        
                        if cancelled_count > 0:
                            print(f"已取消 {cancelled_count} 个未开始的 speaker 任务")
                        
                        print("等待正在执行的 speaker 任务完成...")
                        # 等待正在执行的任务完成（最多等待5秒）
                        start_time = time.time()
                        for future in list(future_to_speaker.keys()):
                            if not future.done() and not future.cancelled():
                                try:
                                    future.result(timeout=1)
                                except:
                                    pass
                                if time.time() - start_time > 5:
                                    break
                        
                        print("正在保存当前 speaker 翻译进度...")
            except KeyboardInterrupt:
                speakers_interrupted = True
                print("\n\n收到中断信号 (CTRL+C)，正在保存 speaker 翻译进度...")
            
            speakers_completed_count = speakers_completed_count_local
            speakers_failed_count = speakers_failed_count_local
            
            # 最终保存译文数据
            if "texts" in original_texts_data or "speakers" in original_texts_data:
                # 嵌套结构
                save_data = {
                    "texts": texts_dict,
                    "speakers": speakers_dict
                }
            else:
                # 直接结构
                save_data = texts_dict
            
            save_output_files(output_file, save_data, texts_dict, speakers_dict)
            
            # 计算统计信息
            speakers_completed_total = sum(1 for v in speakers_dict.values() if v and v.strip())
            
            # 保存进度文件
            with speakers_progress_lock:
                save_progress(progress_file, progress_data)
            
            if speakers_interrupted:
                print(f"\nSpeaker 翻译已中断，进度已保存!")
                print(f"  本次翻译 speakers: {speakers_completed_count} 个")
                print(f"  本次失败 speakers: {speakers_failed_count} 个")
                print(f"  总计完成 speakers: {speakers_completed_total}/{len(speakers_dict)}")
                return
            else:
                print(f"\nSpeaker 翻译完成!")
                print(f"  本次翻译 speakers: {speakers_completed_count} 个")
                print(f"  本次失败 speakers: {speakers_failed_count} 个")
                print(f"  总计完成 speakers: {speakers_completed_total}/{len(speakers_dict)}")
    
    if debug:
        print(f"\n调试模式: 仅翻译前 {debug_limit} 个文本")
    
    print(f"\n开始翻译文本...")
    print(f"使用模型: {MODEL}")
    print(f"并发线程数: {max_workers}")
    
    # 收集所有需要翻译的任务
    tasks = []
    skipped_count = 0
    retry_count = 0
    
    for file_key, file_texts in texts_dict.items():
        for idx, item in enumerate(file_texts):
            # 从 original_texts_dict 读取原文，如果不存在则从 item 读取
            if file_key in original_texts_dict and idx < len(original_texts_dict[file_key]):
                original_text_raw = original_texts_dict[file_key][idx].get("text")
                original_text = (original_text_raw.strip() if original_text_raw else "") if original_text_raw is not None else ""
            else:
                text_raw = item.get("text")
                original_text = (text_raw.strip() if text_raw else "") if text_raw is not None else ""
            
            if not original_text:
                continue
            
            # 获取 item 的 id（用于进度记录）
            item_id = item.get("id")
            if not item_id:
                # 如果没有 id，使用 idx 作为后备（兼容旧格式）
                item_id = str(idx)
            
            # 检查进度记录版本，兼容旧格式（使用 idx）
            progress_version = progress_data.get("version", "1.1")
            if progress_version < "1.2":
                # 旧版本使用 idx
                is_completed = idx in completed_dict.get(file_key, [])
                is_failed = idx in failed_dict.get(file_key, [])
            else:
                # 新版本使用 id
                is_completed = item_id in completed_dict.get(file_key, [])
                is_failed = item_id in failed_dict.get(file_key, [])
            
            # 如果已完成且不是重试失败模式，跳过
            if is_completed and not retry_failed:
                skipped_count += 1
                continue
            
            # 如果是重试失败模式，只处理失败的文本
            if retry_failed and not is_failed:
                continue
            
            if retry_failed and is_failed:
                retry_count += 1
            
            # 获取说话人信息
            speaker_key_raw = item.get("speaker")
            speaker_key = (speaker_key_raw.strip() if speaker_key_raw else "") if speaker_key_raw is not None else ""
            
            tasks.append({
                "file_key": file_key,
                "idx": idx,
                "item_id": item_id,  # 添加 item_id
                "item": item,
                "text": original_text,
                "total_in_file": len(file_texts),
                "is_retry": is_failed,
                "file_texts": file_texts,  # 传递整个文件文本列表用于获取上下文
                "original_file_texts": original_texts_dict.get(file_key, []),  # 传递原文列表
                "speaker_key": speaker_key  # 传递说话人键
            })
    
    if skipped_count > 0:
        print(f"跳过已完成的文本: {skipped_count} 个")
    if retry_count > 0:
        print(f"准备重试失败的文本: {retry_count} 个")
    
    # 限制任务数量
    original_task_count = len(tasks)
    if debug:
        tasks = tasks[:debug_limit]
        print(f"调试模式: 限制任务数为 {len(tasks)}")
    elif max_tasks is not None and max_tasks > 0:
        tasks = tasks[:max_tasks]
        print(f"任务数限制: 从 {original_task_count} 个任务限制为 {len(tasks)} 个")
    
    if not tasks:
        print("没有需要翻译的任务")
        return
    
    # 线程安全的计数器和锁
    translated_count_lock = threading.Lock()
    translated_count_local = 0
    completed_count = 0
    failed_count_local = 0
    file_lock = threading.Lock()
    progress_lock = threading.Lock()
    
    def translate_task(task_info):
        """翻译单个任务的函数"""
        nonlocal translated_count_local, completed_count, failed_count_local
        
        file_key = task_info["file_key"]
        idx = task_info["idx"]
        item_id = task_info.get("item_id", str(idx))  # 获取 item_id，如果没有则使用 idx
        item = task_info["item"]
        original_text = task_info["text"]
        total_in_file = task_info["total_in_file"]
        is_retry = task_info.get("is_retry", False)
        file_texts = task_info.get("file_texts", [])
        original_file_texts = task_info.get("original_file_texts", [])
        speaker_key = task_info.get("speaker_key", "")
        
        # 再次检查空字符串（防止意外情况）
        if not original_text or not original_text.strip():
            return False
        
        # 检查调试模式限制
        with translated_count_lock:
            current_completed = completed_count
            if debug and current_completed >= debug_limit:
                return False
        
        # 获取说话人名称（优先使用翻译后的）
        speaker_name = ""
        if speaker_key:
            if speakers_dict and speaker_key in speakers_dict:
                translated_speaker_raw = speakers_dict[speaker_key]
                translated_speaker = (translated_speaker_raw.strip() if translated_speaker_raw else "") if translated_speaker_raw is not None else ""
                if translated_speaker:
                    speaker_name = translated_speaker
                else:
                    speaker_name = speaker_key
            else:
                speaker_name = speaker_key
        
        # 计算 prompt 基础部分的字符数
        prompt_base_chars = calculate_prompt_base_chars(original_text, terms, speaker_name)
        # 计算可用于上下文的字符数（总限制减去基础部分）
        available_context_chars = max(0, CONTEXT_MAX_CHARS - prompt_base_chars)
        
        # 获取上下文（包含说话人信息），使用剩余可用字符数
        context_before, context_after = get_context(file_texts, idx, original_file_texts, speakers_dict, available_context_chars)
        
        retry_prefix = "[重试] " if is_retry else ""
        context_info = ""
        if context_before or context_after:
            context_info = f" [上下文: 前{len(context_before)}句, 后{len(context_after)}句]"
        speaker_info = f" [{speaker_name}]" if speaker_name else ""
        print(f"  {retry_prefix}[{file_key}][{idx+1}/{total_in_file}]{speaker_info} 翻译: {original_text[:50]}...{context_info}")
        
        translated, error_msg = translate_text(original_text, api_key, terms=terms, context_before=context_before, context_after=context_after, speaker=speaker_name)
        
        with translated_count_lock:
            completed_count += 1
            
            # 更新进度记录
            with progress_lock:
                # 确保版本号是最新的
                if progress_data.get("version", "1.1") < "1.2":
                    progress_data["version"] = "1.2"
                    # 迁移旧格式：将 idx 转换为 id（如果可能）
                    # 这里我们保持兼容，新记录使用 id
                
                if file_key not in progress_data["completed"]:
                    progress_data["completed"][file_key] = []
                if file_key not in progress_data["failed"]:
                    progress_data["failed"][file_key] = []
                
                if translated:
                    item["text"] = translated
                    translated_count_local += 1
                    # 记录成功（使用 id）
                    if item_id not in progress_data["completed"][file_key]:
                        progress_data["completed"][file_key].append(item_id)
                    # 如果之前失败过，从失败记录中移除（兼容旧格式）
                    if file_key in progress_data["failed"]:
                        if item_id in progress_data["failed"][file_key]:
                            progress_data["failed"][file_key].remove(item_id)
                        # 兼容旧格式：也检查 idx
                        elif idx in progress_data["failed"][file_key]:
                            progress_data["failed"][file_key].remove(idx)
                    print(f"    [{file_key}][{idx+1}] 完成: {translated[:50]}...")
                else:
                    # 记录失败（使用 id）
                    failed_count_local += 1
                    # 添加 id（如果不存在）
                    if item_id not in progress_data["failed"][file_key]:
                        progress_data["failed"][file_key].append(item_id)
                    print(f"    [{file_key}][{idx+1}] 翻译失败: {error_msg or '未知错误'}")
            
            # 更新统计信息
            progress_data["stats"]["completed"] = sum(len(indices) for indices in progress_data["completed"].values())
            progress_data["stats"]["failed"] = sum(len(indices) for indices in progress_data["failed"].values())
        
        return True
    
    # 使用线程池并发翻译
    save_interval = max(1, len(tasks) // 20)  # 每完成约5%的任务保存一次
    
    interrupted = False
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_task = {executor.submit(translate_task, task): task for task in tasks}
            
            # 处理完成的任务
            try:
                for future in as_completed(future_to_task):
                    task = future_to_task[future]
                    try:
                        result = future.result()
                        if result is False:
                            # 调试模式达到限制，取消剩余任务
                            if debug:
                                print(f"调试模式: 已达到限制，取消剩余任务")
                                for f in future_to_task:
                                    f.cancel()
                                break
                    except Exception as e:
                        print(f"    [{task['file_key']}][{task['idx']+1}] 任务执行异常: {e}")
                    
                    # 定期保存进度
                    with translated_count_lock:
                        if completed_count % save_interval == 0 or completed_count == len(tasks):
                            # 构建要保存的译文数据
                            if "texts" in original_texts_data or "speakers" in original_texts_data:
                                # 嵌套结构
                                save_data = {
                                    "texts": texts_dict,
                                    "speakers": speakers_dict
                                }
                            else:
                                # 直接结构
                                save_data = texts_dict
                            
                            save_output_files(output_file, save_data, texts_dict, speakers_dict, file_lock)
                            
                            # 保存进度文件
                            with progress_lock:
                                save_progress(progress_file, progress_data)
            except KeyboardInterrupt:
                interrupted = True
                print("\n\n收到中断信号 (CTRL+C)，正在优雅地关闭...")
                print("正在取消未开始的任务...")
                
                # 取消所有未完成的任务
                cancelled_count = 0
                for future in future_to_task:
                    if not future.done():
                        future.cancel()
                        cancelled_count += 1
                
                if cancelled_count > 0:
                    print(f"已取消 {cancelled_count} 个未开始的任务")
                
                print("等待正在执行的任务完成...")
                # 等待正在执行的任务完成（最多等待5秒）
                start_time = time.time()
                for future in list(future_to_task.keys()):
                    if not future.done() and not future.cancelled():
                        try:
                            future.result(timeout=1)
                        except:
                            pass
                        if time.time() - start_time > 5:
                            break
                
                print("正在保存当前进度...")
    except KeyboardInterrupt:
        interrupted = True
        print("\n\n收到中断信号 (CTRL+C)，正在保存进度...")
    
    # 最终保存译文数据
    if "texts" in original_texts_data or "speakers" in original_texts_data:
        # 嵌套结构
        save_data = {
            "texts": texts_dict,
            "speakers": speakers_dict
        }
    else:
        # 直接结构
        save_data = texts_dict
    
    save_output_files(output_file, save_data, texts_dict, speakers_dict)
    
    # 最终保存进度文件
    try:
        with progress_lock:
            progress_data["stats"]["total"] = total_texts
            if speakers_dict:
                progress_data["stats"]["speakers_total"] = len(speakers_dict)
            save_progress(progress_file, progress_data)
    except Exception as e:
        print(f"警告: 保存进度文件失败: {e}")
    
    # 计算统计信息
    speakers_completed_total = sum(1 for v in speakers_dict.values() if v and v.strip()) if speakers_dict else 0
    
    # 打印统计信息
    status = "已中断，进度已保存" if interrupted else "完成"
    print(f"\n翻译{status}!")
    print(f"  本次翻译文本: {translated_count_local} 个")
    print(f"  本次失败文本: {failed_count_local} 个")
    if speakers_dict:
        print(f"  本次翻译 speakers: {speakers_completed_count} 个")
        print(f"  本次失败 speakers: {speakers_failed_count} 个")
    print(f"  总计完成文本: {progress_data['stats']['completed']}/{total_texts if not debug else min(total_texts, debug_limit)}")
    print(f"  总计失败文本: {progress_data['stats']['failed']} 个")
    if speakers_dict:
        print(f"  总计完成 speakers: {speakers_completed_total}/{len(speakers_dict)}")
    print(f"  输出文件: {output_file}")
    print(f"  进度文件: {progress_file}")
    
    if interrupted:
        print(f"\n提示: 重新运行脚本将自动从上次中断的地方继续")
    elif progress_data['stats']['failed'] > 0:
        print(f"\n提示: 使用 --retry-failed 参数可以重试失败的文本")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="使用 GPT API 批量翻译 texts.json")
    parser.add_argument("--texts", type=Path, default=DEFAULT_TEXTS_FILE, help="texts.json 文件路径（源文件）")
    parser.add_argument("--api-key", type=Path, default=DEFAULT_API_KEY_FILE, help="API 密钥文件路径")
    parser.add_argument("--output", type=Path, default=None, help="输出文件路径（默认: texts/texts_translated.json）")
    parser.add_argument("--progress", type=Path, default=None, help="进度记录文件路径（默认: texts/translate_progress.json）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际翻译")
    parser.add_argument("--debug", action="store_true", help="调试模式，仅翻译指定数量的文本")
    parser.add_argument("--threads", type=int, default=MAX_WORKERS, help=f"最大并发线程数（默认: {MAX_WORKERS}）")
    parser.add_argument("--limit", type=int, default=2, help="调试模式下限制翻译的任务数（默认: 5）")
    parser.add_argument("--max-tasks", type=int, default=MAX_TASKS, help=f"最大任务数限制（默认: {MAX_TASKS if MAX_TASKS else '不限制'}）")
    parser.add_argument("--no-resume", action="store_true", help="不从进度文件恢复，从头开始翻译")
    parser.add_argument("--retry-failed", action="store_true", help="仅重试之前失败的文本")
    
    args = parser.parse_args()
    
    resume = not args.no_resume
    
    try:
        batch_translate_texts(
            args.texts, 
            args.api_key, 
            args.output, 
            args.dry_run, 
            args.debug, 
            args.threads, 
            args.limit,
            args.progress,
            resume,
            args.retry_failed,
            args.max_tasks
        )
    except KeyboardInterrupt:
        # 如果 batch_translate_texts 没有捕获到，这里作为最后的保障
        print("\n\n程序被用户中断")
        sys.exit(130)  # 130 是 CTRL+C 的标准退出码


if __name__ == "__main__":
    main()
