#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量将翻译后的文本回填到 JSON 文件中
从 speakers.json 和 texts.json 读取翻译，回填到 all.json
"""

import json
import sys
import copy
from pathlib import Path
from typing import Dict, List, Any

# 默认路径配置
DEFAULT_JSON_FILE = Path("json/all.json")
DEFAULT_TEXTS_DIR = Path("texts")
SPEAKERS_FILE = "speakers.json"
SPEAKERS_TRANSLATED_FILE = "speakers_translated.json"
TEXTS_FILE = "texts.json"
TEXTS_TRANSLATED_FILE = "texts_translated.json"


def update_json_with_translations(
    json_data: Dict[str, Any], 
    file_key: str,
    speakers_map: Dict[str, str],
    file_texts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    将翻译后的文本回填到 JSON 数据中
    
    Args:
        json_data: 原始 JSON 数据
        file_key: 文件名（不含扩展名）
        speakers_map: speaker 翻译映射 {原始名称: 翻译名称}
        file_texts: 对话列表，每个包含 {"msg": "...", "speaker": "...", "id": "...", "text": "..."}
    
    返回更新后的 JSON 数据
    """
    # 创建对话翻译映射
    dialogue_map = {}
    for dialogue in file_texts:
        msg_name = dialogue["msg"]
        dialogue_id = dialogue["id"]
        if msg_name not in dialogue_map:
            dialogue_map[msg_name] = {}
        dialogue_map[msg_name][dialogue_id] = dialogue["text"]
    
    # 更新 JSON 数据
    for msg_name in json_data["order"]:
        msg_data = json_data["messages"][msg_name]
        dialogue_index = 0
        
        # 更新 speaker（从原始 JSON 中读取原始 speaker 名称）
        for line in msg_data["lines"]:
            if line["type"] == "speaker":
                original_speaker = line["text"]
                if original_speaker in speakers_map and speakers_map[original_speaker]:
                    line["text"] = speakers_map[original_speaker]
                break
        
        # 更新 dialogue
        if msg_name in dialogue_map:
            for line in msg_data["lines"]:
                if line["type"] == "dialogue":
                    # 检查原始 text 是否是数组（多个文本段）
                    original_text = line.get("text")
                    is_multiple_segments = isinstance(original_text, list)
                    
                    if is_multiple_segments:
                        # 多个文本段：查找各个文本段的翻译
                        translated_segments = []
                        for seg_idx in range(len(original_text)):
                            seg_id = f"{msg_name}_dialogue_{dialogue_index}_seg_{seg_idx}"
                            translated = dialogue_map[msg_name].get(seg_id)
                            translated_segments.append(translated if translated else original_text[seg_idx])
                        line["text"] = translated_segments
                    else:
                        # 单个文本段：查找翻译
                        dialogue_id = f"{msg_name}_dialogue_{dialogue_index}"
                        if dialogue_id in dialogue_map[msg_name]:
                            line["text"] = dialogue_map[msg_name][dialogue_id]
                    
                    dialogue_index += 1
    
    return json_data


def batch_update_json(json_file: Path, texts_dir: Path, output_file: Path = None, use_translated: bool = True):
    """
    批量将翻译文本回填到 JSON 文件中，保存到新文件
    
    Args:
        json_file: JSON 文件路径（包含所有文件的数据，源文件）
        texts_dir: 翻译文本目录
        output_file: 输出文件路径（如果为 None，则自动生成）
        use_translated: 是否使用 texts_translated.json（默认 True）
    """
    # 优先使用 texts_translated.json，否则使用 texts.json
    if use_translated:
        texts_path = texts_dir / TEXTS_TRANSLATED_FILE
        if not texts_path.exists():
            texts_path = texts_dir / TEXTS_FILE
            print(f"未找到 {TEXTS_TRANSLATED_FILE}，使用 {TEXTS_FILE}")
    else:
        texts_path = texts_dir / TEXTS_FILE
    
    # 读取翻译后的文本
    texts_dict = {}
    speakers_map = {}
    if texts_path.exists():
        with open(texts_path, 'r', encoding='utf-8') as f:
            texts_dict = json.load(f)
        print(f"已加载对话文本: {len(texts_dict)} 个文件")
        
        # 从 texts_dict 中提取 speaker 翻译映射
        for file_key, file_texts in texts_dict.items():
            for item in file_texts:
                speaker = item.get("speaker")
                if speaker and speaker not in speakers_map:
                    # 如果 speaker 有翻译（包含中文），使用翻译后的
                    # 否则保持原样
                    speakers_map[speaker] = speaker
    else:
        print(f"警告: 未找到翻译文件，将跳过翻译")
    
    # 尝试读取 speakers 翻译（优先使用 speakers_translated.json）
    speakers_translated_path = texts_dir / SPEAKERS_TRANSLATED_FILE
    speakers_path = texts_dir / SPEAKERS_FILE
    
    # 优先从 speakers_translated.json 读取
    if speakers_translated_path.exists():
        with open(speakers_translated_path, 'r', encoding='utf-8') as f:
            speakers_from_file = json.load(f)
            # 更新 speakers_map，使用 speakers_translated.json 中的翻译
            for original, translated in speakers_from_file.items():
                if translated and translated.strip():  # 如果有非空翻译
                    speakers_map[original] = translated
        print(f"已加载 Speaker 翻译映射: {len([v for v in speakers_map.values() if v])} 个（从 {SPEAKERS_TRANSLATED_FILE}）")
    elif speakers_path.exists():
        # 如果 speakers_translated.json 不存在，尝试从 speakers.json 读取
        with open(speakers_path, 'r', encoding='utf-8') as f:
            speakers_from_file = json.load(f)
            # 更新 speakers_map，使用 speakers.json 中的翻译
            for original, translated in speakers_from_file.items():
                if translated and translated.strip():  # 如果有非空翻译
                    speakers_map[original] = translated
        print(f"已加载 Speaker 翻译映射: {len([v for v in speakers_map.values() if v])} 个（从 {SPEAKERS_FILE}）")
    
    # 确定输出文件路径
    if output_file is None:
        # 自动生成输出文件名：all_translated.json
        output_file = json_file.parent / "all_translated.json"
    
    print(f"正在读取: {json_file}")
    print(f"输出文件: {output_file}")
    
    # 读取所有 JSON 数据
    with open(json_file, 'r', encoding='utf-8') as f:
        all_data = json.load(f)
    
    # 深拷贝数据，避免修改原数据
    all_data = copy.deepcopy(all_data)
    
    updated_count = 0
    
    for file_key, json_data in all_data.items():
        try:
            # 检查是否有该文件的翻译
            file_texts = texts_dict.get(file_key, [])
            if not file_texts and not any(speakers_map.values()):
                print(f"跳过: 未找到翻译文本 {file_key}")
                continue
            
            print(f"正在回填: {file_key}")
            
            # 更新 JSON
            updated_json = update_json_with_translations(json_data, file_key, speakers_map, file_texts)
            all_data[file_key] = updated_json
            
            updated_count += 1
        except Exception as e:
            print(f"错误: 回填失败 {file_key}: {e}")
    
    # 保存更新后的 JSON 到新文件
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n回填完成: 成功 {updated_count} 个文件")
    print(f"输出文件: {output_file}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="批量将翻译文本回填到 JSON 文件")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_FILE, help="all.json 文件路径（源文件）")
    parser.add_argument("--texts", type=Path, default=DEFAULT_TEXTS_DIR, help="翻译文本目录")
    parser.add_argument("--output", type=Path, default=None, help="输出文件路径（默认: json/all_translated.json）")
    parser.add_argument("--no-translated", action="store_true", help="不使用 texts_translated.json，使用 texts.json")
    
    args = parser.parse_args()
    
    batch_update_json(args.json, args.texts, args.output, use_translated=not args.no_translated)


if __name__ == "__main__":
    main()
