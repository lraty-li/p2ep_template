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


def extract_markers(line: str) -> tuple[str, list[str], list[str]]:
    """提取控制标记和文本内容，返回 (文本, 文本前标记, 文本后标记)"""
    markers_before = []
    markers_after = []
    text_parts = []
    text_started = False
    i = 0
    
    while i < len(line):
        if line[i] == '[':
            depth = 1
            paren_depth = 0
            j = i + 1
            
            while j < len(line) and depth > 0:
                if line[j] == '[' and paren_depth == 0:
                    depth += 1
                elif line[j] == ']' and paren_depth == 0:
                    depth -= 1
                elif line[j] == '(':
                    paren_depth += 1
                elif line[j] == ')':
                    paren_depth -= 1
                j += 1
            
            if depth == 0:
                marker = line[i:j]
                (markers_after if text_started else markers_before).append(marker)
                i = j
            else:
                if line[i].strip():
                    text_started = True
                text_parts.append(line[i])
                i += 1
        else:
            if line[i].strip():
                text_started = True
            text_parts.append(line[i])
            i += 1
    
    return ''.join(text_parts).strip(), markers_before, markers_after


def is_first_line_speaker(line: str) -> Optional[Dict[str, Any]]:
    """判断消息块第一行是否为 speaker：有 [color(...)] 且无 [tab]"""
    if '[tab]' in line:
        return None
    
    text, markers_before, markers_after = extract_markers(line)
    all_markers = markers_before + markers_after
    
    color_pattern = re.compile(r'^\[color\([^)]+\)\]$')
    color_markers = [m for m in all_markers if color_pattern.match(m)]
    
    if len(color_markers) >= 2:
        format_str = color_markers[0] + '{text}' + color_markers[-1]
        return {
            "type": "speaker",
            "text": text,
            "format": format_str
        }
    
    return None


def parse_line(line: str) -> Optional[Dict[str, Any]]:
    """解析单行消息，遇到控制符进行分块，提取所有文本段"""
    line = line.rstrip()
    if not line.strip():
        return None
    
    # 提取所有文本段和控制符
    text_segments = []
    format_parts = []
    i = 0
    current_text = ""
    
    while i < len(line):
        if line[i] == '[':
            # 遇到控制符，先保存当前文本段
            if current_text.strip():
                text_segments.append(current_text.strip())
                format_parts.append(f"{{text{len(text_segments)-1}}}")
            current_text = ""
            
            # 解析控制符
            depth = 1
            paren_depth = 0
            j = i + 1
            while j < len(line) and depth > 0:
                if line[j] == '[' and paren_depth == 0:
                    depth += 1
                elif line[j] == ']' and paren_depth == 0:
                    depth -= 1
                elif line[j] == '(':
                    paren_depth += 1
                elif line[j] == ')':
                    paren_depth -= 1
                j += 1
            
            if depth == 0:
                marker = line[i:j]
                format_parts.append(marker)
                i = j
            else:
                current_text += line[i]
                i += 1
        else:
            current_text += line[i]
            i += 1
    
    # 处理最后的文本段
    if current_text.strip():
        text_segments.append(current_text.strip())
        format_parts.append(f"{{text{len(text_segments)-1}}}")
    
    # 如果没有文本段，只有控制符
    if not text_segments:
        return {
            "type": "dialogue",
            "text": "",
            "format": ''.join(format_parts)
        }
    
    # 如果有多个文本段，使用数组存储；如果只有一个，保持兼容性
    if len(text_segments) == 1:
        format_str = ''.join(format_parts).replace("{text0}", "{text}")
        return {
            "type": "dialogue",
            "text": text_segments[0],
            "format": format_str
        }
    else:
        return {
            "type": "dialogue",
            "text": text_segments,  # 数组
            "format": ''.join(format_parts)  # 包含 {text0}, {text1} 等
        }


def merge_tab_dialogues(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并连续的 [tab] dialogue 行，保留所有控制符和所有文本段"""
    result = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        if line.get("type") == "dialogue" and "[tab]" in line.get("format", ""):
            # 收集连续的 [tab] dialogue
            format_parts = []
            all_text_segments = []
            
            while i < len(lines) and lines[i].get("type") == "dialogue" and "[tab]" in lines[i].get("format", ""):
                format_str = lines[i].get("format", "")
                text = lines[i].get("text", "")
                
                # 获取所有文本段并展开格式字符串
                if isinstance(text, list):
                    all_text_segments.extend(text)
                    # 展开格式：替换 {text0}, {text1} 等为实际文本
                    expanded = format_str
                    for idx, seg in enumerate(text):
                        expanded = expanded.replace(f"{{text{idx}}}", seg, 1)
                else:
                    if text:
                        all_text_segments.append(text)
                    expanded = format_str.replace("{text}", text)
                
                format_parts.append(expanded)
                i += 1
            
            # 合并所有格式字符串（已展开的完整格式）
            merged_format_expanded = "".join(format_parts)
            
            # 将合并后的格式字符串中的文本段替换为占位符（从后往前替换）
            merged_format = merged_format_expanded
            for text_idx in range(len(all_text_segments) - 1, -1, -1):
                seg = all_text_segments[text_idx]
                pos = merged_format.rfind(seg)
                if pos != -1:
                    placeholder = "{text}" if (text_idx == 0 and len(all_text_segments) == 1) else f"{{text{text_idx}}}"
                    merged_format = merged_format[:pos] + placeholder + merged_format[pos + len(seg):]
            
            # 构建结果
            result.append({
                "type": "dialogue",
                "text": all_text_segments[0] if len(all_text_segments) == 1 else all_text_segments,
                "format": merged_format
            })
        else:
            result.append(line)
            i += 1
    
    return result


def parse_msg_file(file_path: Path) -> Dict[str, Any]:
    """解析 .msg 文件为 JSON"""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')
    
    result = {"comments": [], "messages": {}, "order": []}
    i = 0
    
    # 文件开头注释
    while i < len(lines) and not (lines[i].strip().endswith(':') and not lines[i].strip().startswith('#')):
        i += 1
    result["comments"].append('\n'.join(lines[:i]))
    
    # 解析消息块
    while i < len(lines):
        line = lines[i].strip()
        if line.endswith(':') and not line.startswith('#'):
            msg_name = line[:-1].strip()
            i += 1
            
            # 收集消息行
            msg_lines = []
            is_first_line = True
            while i < len(lines):
                if is_first_line:
                    speaker_parsed = is_first_line_speaker(lines[i])
                    if speaker_parsed:
                        msg_lines.append(speaker_parsed)
                        is_first_line = False
                        if '[end]' in speaker_parsed.get("format", ""):
                            i += 1
                            break
                        i += 1
                        continue
                    is_first_line = False
                
                parsed = parse_line(lines[i])
                if parsed:
                    msg_lines.append(parsed)
                    if '[end]' in parsed.get("format", ""):
                        i += 1
                        break
                i += 1
            
            # 合并 [tab] dialogue
            result["messages"][msg_name] = {"lines": merge_tab_dialogues(msg_lines)}
            result["order"].append(msg_name)
            
            # 消息后注释
            comment_start = i
            while i < len(lines) and not (lines[i].strip().endswith(':') and not lines[i].strip().startswith('#')):
                i += 1
            result["comments"].append('\n'.join(lines[comment_start:i]))
        else:
            i += 1
    
    return result


def extract_texts_for_translation(json_data: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    """提取文本用于翻译"""
    texts = {}
    
    for msg_name in json_data["order"]:
        msg_texts = []
        dialogue_idx = 0
        
        for line in json_data["messages"][msg_name]["lines"]:
            if line["type"] == "speaker":
                msg_texts.append({"id": f"{msg_name}_speaker", "text": line["text"]})
            elif line["type"] == "dialogue":
                text = line.get("text")
                # 处理多个文本段（数组）或单个文本段（字符串）
                if isinstance(text, list):
                    # 多个文本段
                    for seg_idx, seg in enumerate(text):
                        if seg:
                            msg_texts.append({"id": f"{msg_name}_dialogue_{dialogue_idx}_seg_{seg_idx}", "text": seg})
                    dialogue_idx += 1
                elif text:
                    # 单个文本段
                    msg_texts.append({"id": f"{msg_name}_dialogue_{dialogue_idx}", "text": text})
                    dialogue_idx += 1
        
        if msg_texts:
            texts[msg_name] = msg_texts
    
    return texts


def find_translated_text(translated_texts: Optional[Dict], msg_name: str, item_id: str) -> Optional[str]:
    """查找翻译文本"""
    if not translated_texts or msg_name not in translated_texts:
        return None
    for item in translated_texts[msg_name]:
        if item["id"] == item_id:
            return item["text"]
    return None


def rebuild_msg_file(json_data: Dict[str, Any], translated_texts: Dict[str, List[Dict[str, str]]] = None) -> str:
    """重组 .msg 文件"""
    lines = []
    
    if json_data["comments"]:
        lines.append(json_data["comments"][0])
    
    comment_idx = 1
    for msg_name in json_data["order"]:
        lines.append(f"{msg_name}:")
        
        dialogue_idx = 0
        for line in json_data["messages"][msg_name]["lines"]:
            if line["type"] == "speaker":
                text = find_translated_text(translated_texts, msg_name, f"{msg_name}_speaker") or line["text"]
                lines.append(line["format"].replace("{text}", text))
            elif line["type"] == "dialogue":
                format_str = line["format"]
                text = line.get("text", "")
                
                # 处理多个文本段（数组）或单个文本段（字符串）
                if isinstance(text, list):
                    # 多个文本段：替换 {text0}, {text1} 等
                    for seg_idx, seg in enumerate(text):
                        translated = find_translated_text(translated_texts, msg_name, f"{msg_name}_dialogue_{dialogue_idx}_seg_{seg_idx}") or seg
                        format_str = format_str.replace(f"{{text{seg_idx}}}", translated, 1)
                else:
                    # 单个文本段：检查是否有多个占位符（数据不一致的情况）
                    if re.search(r'\{text\d+\}', format_str):
                        # format 中有多个占位符，尝试从翻译文本中查找各个文本段
                        seg_idx = 0
                        while True:
                            placeholder = f"{{text{seg_idx}}}"
                            if placeholder not in format_str:
                                break
                            seg_translated = find_translated_text(translated_texts, msg_name, f"{msg_name}_dialogue_{dialogue_idx}_seg_{seg_idx}")
                            if seg_translated:
                                format_str = format_str.replace(placeholder, seg_translated, 1)
                            elif seg_idx == 0:
                                # 第一个占位符使用整个文本
                                translated = find_translated_text(translated_texts, msg_name, f"{msg_name}_dialogue_{dialogue_idx}") or text
                                format_str = format_str.replace(placeholder, translated or "", 1)
                            else:
                                # 其他占位符用空字符串替换
                                format_str = format_str.replace(placeholder, "", 1)
                            seg_idx += 1
                    else:
                        # 单个占位符 {text}
                        translated = find_translated_text(translated_texts, msg_name, f"{msg_name}_dialogue_{dialogue_idx}") or text
                        format_str = format_str.replace("{text}", translated or "")
                
                # 清理任何剩余的未替换占位符
                format_str = re.sub(r'\{text\d+\}', '', format_str)
                
                lines.append(format_str)
                dialogue_idx += 1
            elif line.get("format"):
                lines.append(line["format"])
        
        # 添加注释或空行
        if comment_idx < len(json_data["comments"]):
            lines.append(json_data["comments"][comment_idx] or "")
        else:
            lines.append("")
        comment_idx += 1
    
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
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(parse_msg_file(input_file), f, ensure_ascii=False, indent=2)
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
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(rebuild_msg_file(json_data, translated_texts))
        print(f"重组完成: {output_file}")
    
    else:
        print(f"错误: 未知命令 {command}")
        sys.exit(1)
