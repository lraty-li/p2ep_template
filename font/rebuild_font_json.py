#!/usr/bin/env python3
"""
重建 font.json，从 texts_translated.json 收集实际使用的字符
"""

import json
import os
from pathlib import Path

# 每个页码有 16x16 = 256 个位置
CHARS_PER_PAGE = 256
GRID_SIZE = 16

def create_empty_page():
    """创建一个空的16x16字符网格"""
    return [["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]

def collect_chars_from_font_info(font_info_file):
    """从 font_info_small.json 收集所有字符（临时处理）"""
    print(f"读取字体信息文件: {font_info_file}")
    
    if not font_info_file.exists():
        print(f"警告: 未找到字体信息文件: {font_info_file}")
        return []
    
    with open(font_info_file, 'r', encoding='utf-8') as f:
        font_info_data = json.load(f)
    
    chars_set = set()
    
    # 遍历所有字体信息条目
    if isinstance(font_info_data, list):
        for item in font_info_data:
            if isinstance(item, dict) and 'char' in item:
                char = item['char']
                if isinstance(char, str) and char != "":
                    chars_set.add(char)
    
    # 转换为字符码点列表
    char_codes = []
    for char in chars_set:
        char_code = ord(char)
        # 排除控制字符
        if not (0x00 <= char_code <= 0x1F) and char_code != 0x7F and not (0x7F < char_code <= 0x9F):
            if char.isprintable() or char_code in [0x20, 0x09, 0x0A, 0x0D]:
                char_codes.append(char_code)
    
    # 按 Unicode 码点排序
    char_codes.sort()
    
    print(f"从字体信息文件收集到 {len(char_codes)} 个唯一字符")
    
    return char_codes

def collect_chars_from_texts(texts_file):
    """从 texts_translated.json 收集所有使用的字符"""
    print(f"读取文件: {texts_file}")
    
    with open(texts_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    chars_set = set()
    
    # 遍历所有文本
    if isinstance(data, dict):
        # 如果 texts_translated.json 的结构是 {filename: [texts]}
        for filename, texts_list in data.items():
            if isinstance(texts_list, list):
                for item in texts_list:
                    if isinstance(item, dict):
                        # 提取 text 字段
                        if 'text' in item:
                            text = item['text']
                            if isinstance(text, str):
                                chars_set.update(text)
                        # 提取 speaker 字段（如果有）
                        if 'speaker' in item:
                            speaker = item['speaker']
                            if isinstance(speaker, str):
                                chars_set.update(speaker)
        # 如果结构是 {speakers: {...}, texts: {...}}
        if 'speakers' in data:
            for speaker in data['speakers'].values():
                if isinstance(speaker, str):
                    chars_set.update(speaker)
        if 'texts' in data:
            if isinstance(data['texts'], dict):
                for filename, texts_list in data['texts'].items():
                    if isinstance(texts_list, list):
                        for item in texts_list:
                            if isinstance(item, dict) and 'text' in item:
                                text = item['text']
                                if isinstance(text, str):
                                    chars_set.update(text)
            elif isinstance(data['texts'], list):
                for item in data['texts']:
                    if isinstance(item, dict):
                        if 'text' in item:
                            text = item['text']
                            if isinstance(text, str):
                                chars_set.update(text)
                        if 'speaker' in item:
                            speaker = item['speaker']
                            if isinstance(speaker, str):
                                chars_set.update(speaker)
    
    # 过滤掉控制字符和不可打印字符
    filtered_chars = []
    for char in chars_set:
        char_code = ord(char)
        # 排除控制字符（0x00-0x1F, 0x7F-0x9F）和某些特殊控制字符
        # 保留所有可打印字符和常用空白字符（包括空格、制表符等）
        if not (0x00 <= char_code <= 0x1F) and char_code != 0x7F and not (0x7F < char_code <= 0x9F):
            # 使用 isprintable() 或检查是否为常用空白字符
            if char.isprintable() or char_code in [0x20, 0x09, 0x0A, 0x0D]:  # 空格、制表符、换行符、回车符
                filtered_chars.append(char_code)
    
    # 按 Unicode 码点排序
    filtered_chars.sort()
    
    print(f"收集到 {len(filtered_chars)} 个唯一字符")
    
    return filtered_chars

def collect_chars_from_speakers(speakers_file):
    """从 speakers_translated.json 收集所有 speaker 字符"""
    print(f"读取文件: {speakers_file}")
    
    if not speakers_file.exists():
        print(f"警告: 未找到文件 {speakers_file}")
        return []
    
    with open(speakers_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    chars_set = set()
    
    # 遍历所有 speaker 翻译
    if isinstance(data, dict):
        for speaker_key, speaker_value in data.items():
            # 收集原始 speaker 名称的字符
            if isinstance(speaker_key, str):
                chars_set.update(speaker_key)
            # 收集翻译后的 speaker 名称的字符
            if isinstance(speaker_value, str):
                chars_set.update(speaker_value)
    
    # 过滤掉控制字符和不可打印字符
    filtered_chars = []
    for char in chars_set:
        char_code = ord(char)
        # 排除控制字符（0x00-0x1F, 0x7F-0x9F）和某些特殊控制字符
        # 保留所有可打印字符和常用空白字符（包括空格、制表符等）
        if not (0x00 <= char_code <= 0x1F) and char_code != 0x7F and not (0x7F < char_code <= 0x9F):
            # 使用 isprintable() 或检查是否为常用空白字符
            if char.isprintable() or char_code in [0x20, 0x09, 0x0A, 0x0D]:  # 空格、制表符、换行符、回车符
                filtered_chars.append(char_code)
    
    # 按 Unicode 码点排序
    filtered_chars.sort()
    
    print(f"从 speakers 收集到 {len(filtered_chars)} 个唯一字符")
    
    return filtered_chars

def rebuild_font_json(chars_list):
    """根据字符列表重建 font.json"""
    font_data = {}
    
    current_index = 0
    max_pages = 32
    
    for page_num in range(max_pages):
        page = create_empty_page()
        filled_count = 0
        
        for y in range(GRID_SIZE):
            for x in range(GRID_SIZE):
                if current_index >= len(chars_list):
                    break
                
                char_code = chars_list[current_index]
                try:
                    char = chr(char_code)
                    # 确保字符是有效的 Unicode 字符
                    # 所有通过过滤的字符都应该被处理
                    page[y][x] = char
                    filled_count += 1
                except (ValueError, OverflowError) as e:
                    # 无效的字符码点，跳过但保留位置为空
                    print(f"警告: 无法处理字符码点 0x{char_code:X} ({char_code})")
                    page[y][x] = ""
                
                current_index += 1
            
            if current_index >= len(chars_list):
                break
        
        if filled_count == 0:
            break
        
        font_data[str(page_num)] = page
        print(f"页码 {page_num}: {filled_count} 个字符")
        
        if current_index >= len(chars_list):
            break
    
    return font_data

def main():
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # 输入文件：texts_translated.json
    texts_file = project_root / 'texts' / 'texts_translated.json'
    
    # 输出文件：font.json
    output_path = script_dir / 'locale' / 'font.json'
    
    if not texts_file.exists():
        print(f"错误: 未找到文件 {texts_file}")
        print("请先运行翻译脚本生成 texts_translated.json")
        return
    
    print("\n正在重建 font.json...")
    print("从 texts_translated.json 收集实际使用的字符...\n")
    
    # 收集字符
    chars_list = collect_chars_from_texts(texts_file)
    
    # 从 speakers_translated.json 收集 speaker 字符
    speakers_file = project_root / 'texts' / 'speakers_translated.json'
    speakers_chars = collect_chars_from_speakers(speakers_file)
    
    if speakers_chars:
        # 合并字符列表（去重）
        all_chars_set = set(chars_list) | set(speakers_chars)
        chars_list = sorted(list(all_chars_set))
        print(f"\n合并 texts 和 speakers 后总计: {len(chars_list)} 个唯一字符\n")
    
    # 临时处理：从 font_info_small.json 收集字符并合并
    font_info_file = script_dir / 'font_info_small.json'
    font_info_chars = collect_chars_from_font_info(font_info_file)
    
    if font_info_chars:
        # 合并字符列表（去重）
        all_chars_set = set(chars_list) | set(font_info_chars)
        chars_list = sorted(list(all_chars_set))
        print(f"\n合并后总计: {len(chars_list)} 个唯一字符（包含字体信息文件中的字符）\n")
    
    if len(chars_list) == 0:
        print("错误: 未收集到任何字符")
        return
    
    # 重建 font.json
    font_data = rebuild_font_json(chars_list)
    
    # 统计字符数量
    total_chars = 0
    for page_key, page_data in font_data.items():
        page_chars = sum(1 for row in page_data for char in row if char != "")
        total_chars += page_chars
    
    print(f"\n总计: {total_chars} 个字符（分布在 {len(font_data)} 个页码）")
    
    # 保存JSON文件
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(font_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n已保存到: {output_path}")

if __name__ == '__main__':
    main()
