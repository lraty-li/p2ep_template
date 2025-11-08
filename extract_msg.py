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
                
                # 解析当前行（[end] 作为普通控制标记处理）
                parsed_line = parse_message_line(current_line)
                if parsed_line:
                    msg_lines.append(parsed_line)
                    # 如果 format 中包含 [end]，结束消息块收集
                    if '[end]' in parsed_line.get("format", ""):
                        i += 1
                        break
                
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


def extract_all_control_markers(line: str) -> tuple[str, list[str], list[str]]:
    """
    从行中提取所有控制标记（[...]格式）和文本内容
    
    返回: (文本内容, [文本前的标记列表], [文本后的标记列表])
    """
    # 从前往后解析，保持标记的原始顺序和位置
    markers_before = []
    markers_after = []
    text_parts = []
    
    i = 0
    text_started = False  # 是否已经开始遇到非空白文本内容
    
    while i < len(line):
        if line[i] == '[':
            # 找到左括号，查找匹配的右括号
            depth = 1
            j = i + 1
            paren_depth = 0  # 圆括号深度
            
            while j < len(line) and depth > 0:
                if line[j] == '[':
                    if paren_depth == 0:
                        depth += 1
                elif line[j] == ']':
                    if paren_depth == 0:
                        depth -= 1
                    else:
                        # 这是圆括号内的右括号，不是标记的结束
                        pass
                elif line[j] == '(':
                    paren_depth += 1
                elif line[j] == ')':
                    paren_depth -= 1
                j += 1
            
            if depth == 0:
                # 找到了完整的标记
                marker = line[i:j]
                if text_started:
                    markers_after.append(marker)
                else:
                    markers_before.append(marker)
                i = j
            else:
                # 未找到匹配的右括号，当作普通字符处理
                if line[i].strip():
                    text_started = True
                text_parts.append(line[i])
                i += 1
        else:
            # 普通字符
            char = line[i]
            # 如果遇到非空白字符，标记文本已开始
            if char.strip():
                text_started = True
            text_parts.append(char)
            i += 1
    
    # 清理文本（去除多余空格）
    text = ''.join(text_parts).strip()
    
    return text, markers_before, markers_after


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
    
    # 提取所有控制标记和文本（区分文本前后的标记）
    text_content, markers_before, markers_after = extract_all_control_markers(line)
    
    # 检查是否是角色名行: [color(yellow)]文本[color(white)]
    all_markers = markers_before + markers_after
    if len(all_markers) >= 2 and all_markers[0] == '[color(yellow)]' and all_markers[-1] == '[color(white)]':
        return {
            "type": "speaker",
            "text": text_content,
            "format": "[color(yellow)]{text}[color(white)]"
        }
    
    # 处理对话行
    format_parts = []
    
    # 添加文本前的标记
    format_parts.extend(markers_before)
    
    # 添加文本占位符
    if text_content:
        format_parts.append('{text}')
    
    # 添加文本后的标记
    format_parts.extend(markers_after)
    
    format_str = ''.join(format_parts)
    
    return {
        "type": "dialogue",
        "text": text_content,
        "format": format_str
    }


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
