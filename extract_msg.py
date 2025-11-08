#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取 .msg 文件为 JSON 格式，用于翻译
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional


def parse_msg_file(file_path: Path) -> Dict[str, Any]:
    """
    解析 .msg 文件为结构化 JSON
    
    返回格式:
    {
        "comments": [""],  # 文件开头的注释
        "messages": {
            "msg_0": {
                "lines": [
                    {
                        "type": "speaker",  # "speaker" | "dialogue" | "end"
                        "text": "お婆さん",
                        "format": "[color(yellow)]{text}[color(white)]"
                    },
                    {
                        "type": "dialogue",
                        "text": "なんとまぁ、寂しい背中だい…",
                        "format": "[tab]{text}"
                    },
                    {
                        "type": "end",
                        "format": "[sync][wait][clear][end]"
                    }
                ]
            }
        },
        "order": ["msg_0", "msg_1", ...]
    }
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.split('\n')
    result = {
        "comments": [],
        "messages": {},
        "order": []
    }
    
    current_comment = []
    i = 0
    
    # 处理文件开头的注释
    while i < len(lines):
        line = lines[i]
        if line.strip().endswith(':') and not line.strip().startswith('#'):
            break
        current_comment.append(line)
        i += 1
    
    result["comments"].append('\n'.join(current_comment))
    
    # 解析消息块
    while i < len(lines):
        line = lines[i].strip()
        
        # 检查是否是消息标识
        if line.endswith(':') and not line.startswith('#'):
            msg_name = line[:-1].strip()
            i += 1
            
            msg_lines = []
            
            # 收集消息内容直到 [end]
            while i < len(lines):
                current_line = lines[i]
                
                # 检查是否到达结束标记
                if '[end]' in current_line:
                    # 提取结束标记前的所有内容
                    end_content = current_line.strip()
                    msg_lines.append({
                        "type": "end",
                        "format": end_content
                    })
                    i += 1
                    break
                
                # 解析当前行
                parsed_line = parse_message_line(current_line)
                if parsed_line:
                    msg_lines.append(parsed_line)
                
                i += 1
            
            result["messages"][msg_name] = {
                "lines": msg_lines
            }
            result["order"].append(msg_name)
            
            # 收集消息后的注释
            current_comment = []
            while i < len(lines):
                line = lines[i]
                if line.strip().endswith(':') and not line.strip().startswith('#'):
                    break
                current_comment.append(line)
                i += 1
            
            if current_comment:
                result["comments"].append('\n'.join(current_comment))
        else:
            i += 1
    
    return result


def parse_message_line(line: str) -> Optional[Dict[str, Any]]:
    """
    解析单行消息内容
    
    返回格式:
    - {"type": "speaker", "text": "...", "format": "..."}
    - {"type": "dialogue", "text": "...", "format": "..."}
    - None (空行)
    """
    line = line.rstrip()
    
    if not line.strip():
        return None
    
    # 检查是否是角色名行: [color(yellow)]文本[color(white)]
    speaker_pattern = r'\[color\(yellow\)\](.*?)\[color\(white\)\]'
    match = re.search(speaker_pattern, line)
    if match:
        text = match.group(1)
        return {
            "type": "speaker",
            "text": text,
            "format": "[color(yellow)]{text}[color(white)]"
        }
    
    # 检查是否是对话行: [tab]文本
    if line.startswith('[tab]'):
        text = line[5:]  # 移除 [tab]
        return {
            "type": "dialogue",
            "text": text,
            "format": "[tab]{text}"
        }
    
    # 其他格式的行（可能包含其他标记）
    # 尝试提取文本内容
    text = line
    format_parts = []
    
    # 处理 [tab] 前缀
    if text.startswith('[tab]'):
        format_parts.append('[tab]')
        text = text[5:]
    
    # 处理其他标记（如果有）
    if text.strip():
        format_parts.append('{text}')
        return {
            "type": "dialogue",
            "text": text,
            "format": ''.join(format_parts)
        }
    
    return None


def extract_texts_for_translation(json_data: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    """
    从 JSON 数据中提取纯文本，用于翻译
    
    返回格式:
    {
        "msg_0": [
            {"id": "msg_0_speaker", "text": "お婆さん"},
            {"id": "msg_0_dialogue_0", "text": "なんとまぁ、寂しい背中だい…"},
            ...
        ],
        ...
    }
    """
    texts = {}
    
    for msg_name in json_data["order"]:
        msg_data = json_data["messages"][msg_name]
        msg_texts = []
        
        dialogue_index = 0
        for line in msg_data["lines"]:
            if line["type"] == "speaker":
                msg_texts.append({
                    "id": f"{msg_name}_speaker",
                    "text": line["text"]
                })
            elif line["type"] == "dialogue":
                msg_texts.append({
                    "id": f"{msg_name}_dialogue_{dialogue_index}",
                    "text": line["text"]
                })
                dialogue_index += 1
        
        if msg_texts:
            texts[msg_name] = msg_texts
    
    return texts


def rebuild_msg_file(json_data: Dict[str, Any], translated_texts: Dict[str, List[Dict[str, str]]] = None) -> str:
    """
    从 JSON 数据重组 .msg 文件
    
    Args:
        json_data: 原始 JSON 数据
        translated_texts: 翻译后的文本（可选，如果不提供则使用原始文本）
    
    返回重组后的 .msg 文件内容
    """
    lines = []
    
    # 添加文件开头的注释
    if json_data["comments"]:
        lines.append(json_data["comments"][0])
    
    # 处理每个消息块
    comment_index = 1
    for msg_name in json_data["order"]:
        msg_data = json_data["messages"][msg_name]
        
        # 消息标识
        lines.append(f"{msg_name}:")
        
        # 处理消息行
        dialogue_index = 0
        for line in msg_data["lines"]:
            if line["type"] == "speaker":
                # 使用翻译后的文本或原始文本
                text = line["text"]
                if translated_texts and msg_name in translated_texts:
                    for item in translated_texts[msg_name]:
                        if item["id"] == f"{msg_name}_speaker":
                            text = item["text"]
                            break
                
                # 重组格式
                format_str = line["format"].replace("{text}", text)
                lines.append(format_str)
            
            elif line["type"] == "dialogue":
                # 使用翻译后的文本或原始文本
                text = line["text"]
                if translated_texts and msg_name in translated_texts:
                    for item in translated_texts[msg_name]:
                        if item["id"] == f"{msg_name}_dialogue_{dialogue_index}":
                            text = item["text"]
                            break
                
                # 重组格式
                format_str = line["format"].replace("{text}", text)
                lines.append(format_str)
                dialogue_index += 1
            
            elif line["type"] == "end":
                # 结束标记
                lines.append(line["format"])
        
        # 添加消息后的注释和空行
        if comment_index < len(json_data["comments"]):
            comment = json_data["comments"][comment_index]
            if comment.strip():
                lines.append(comment)
            else:
                # 如果没有注释，添加空行以保持格式
                lines.append("")
            comment_index += 1
        else:
            # 如果注释用完了，添加空行
            lines.append("")
    
    return '\n'.join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: extract_msg.py <command> [args...]")
        print("命令:")
        print("  extract <input.msg> <output.json>  - 提取 .msg 为 JSON")
        print("  rebuild <input.json> <output.msg> [translated.json] - 重组 JSON 为 .msg")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "extract":
        if len(sys.argv) < 4:
            print("错误: extract 需要输入文件和输出文件")
            sys.exit(1)
        
        input_file = Path(sys.argv[2])
        output_file = Path(sys.argv[3])
        
        print(f"正在提取: {input_file} -> {output_file}")
        json_data = parse_msg_file(input_file)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        
        print(f"提取完成: {output_file}")
    
    elif command == "rebuild":
        if len(sys.argv) < 4:
            print("错误: rebuild 需要输入 JSON 和输出文件")
            sys.exit(1)
        
        input_file = Path(sys.argv[2])
        output_file = Path(sys.argv[3])
        translated_file = Path(sys.argv[4]) if len(sys.argv) > 4 else None
        
        print(f"正在重组: {input_file} -> {output_file}")
        
        with open(input_file, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        translated_texts = None
        if translated_file and translated_file.exists():
            with open(translated_file, 'r', encoding='utf-8') as f:
                translated_texts = json.load(f)
        
        msg_content = rebuild_msg_file(json_data, translated_texts)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(msg_content)
        
        print(f"重组完成: {output_file}")
    
    else:
        print(f"错误: 未知命令 {command}")
        sys.exit(1)
