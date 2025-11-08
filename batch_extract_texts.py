#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量从 JSON 文件中提取纯文本，用于翻译
从单个 all.json 文件读取，生成 speakers.json 和 texts.json
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any

from extract_msg import extract_texts_for_translation

# 默认路径配置
DEFAULT_JSON_FILE = Path("json/all.json")
DEFAULT_TEXTS_OUTPUT_DIR = Path("texts")
SPEAKERS_FILE = "speakers.json"
TEXTS_FILE = "texts.json"


def batch_extract_texts(json_file: Path, output_dir: Path):
    """
    批量从 JSON 文件中提取纯文本，用于翻译
    从单个 all.json 文件读取，生成 speakers.json 和 texts.json
    
    Args:
        json_file: JSON 文件路径（包含所有文件的数据）
        output_dir: 文本输出目录
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 全局数据
    all_speakers: Dict[str, str] = {}
    all_texts: Dict[str, List[Dict[str, Any]]] = {}
    
    # 读取所有 JSON 数据
    print(f"正在读取: {json_file}")
    with open(json_file, 'r', encoding='utf-8') as f:
        all_data = json.load(f)
    
    extracted_count = 0
    
    for file_key, json_data in all_data.items():
        try:
            print(f"正在提取文本: {file_key}")
            
            # 提取文本（使用原有函数）
            texts = extract_texts_for_translation(json_data)
            
            # 该文件的对话列表
            file_texts = []
            
            # 处理每个消息块
            for msg_name in json_data["order"]:
                if msg_name not in texts:
                    continue
                
                msg_texts = texts[msg_name]
                current_speaker = None
                
                for item in msg_texts:
                    if item["id"].endswith("_speaker"):
                        # 收集 speaker
                        speaker_text = item["text"]
                        if speaker_text not in all_speakers:
                            all_speakers[speaker_text] = ""
                        current_speaker = speaker_text
                    elif item["id"].startswith(msg_name + "_dialogue_"):
                        # 收集 dialogue，不记录文件信息（因为已经在键中）
                        file_texts.append({
                            "msg": msg_name,
                            "speaker": current_speaker,
                            "id": item["id"],
                            "text": item["text"]
                        })
            
            # 以文件名作为键
            all_texts[file_key] = file_texts
            
            extracted_count += 1
        except Exception as e:
            print(f"错误: 提取文本失败 {file_key}: {e}")
    
    # 保存 speakers.json
    speakers_path = output_dir / SPEAKERS_FILE
    with open(speakers_path, 'w', encoding='utf-8') as f:
        json.dump(all_speakers, f, ensure_ascii=False, indent=2)
    
    # 保存 texts.json
    texts_path = output_dir / TEXTS_FILE
    with open(texts_path, 'w', encoding='utf-8') as f:
        json.dump(all_texts, f, ensure_ascii=False, indent=2)
    
    print(f"\n提取完成: 成功 {extracted_count} 个文件")
    print(f"对话总数: {sum(len(v) for v in all_texts.values())}")
    print(f"Speaker 总数: {len(all_speakers)}")
    print(f"输出文件: {speakers_path}")
    print(f"输出文件: {texts_path}")


def main():
    # 如果提供了参数，使用参数；否则使用默认路径
    if len(sys.argv) >= 3:
        json_file = Path(sys.argv[1])
        output_dir = Path(sys.argv[2])
    else:
        json_file = DEFAULT_JSON_FILE
        output_dir = DEFAULT_TEXTS_OUTPUT_DIR
        print(f"使用默认路径:")
        print(f"  JSON 文件: {json_file}")
        print(f"  输出目录: {output_dir}")
        print()
    
    batch_extract_texts(json_file, output_dir)


if __name__ == "__main__":
    main()
