#!/usr/bin/env python3
"""
从 font.json 完全生成 event.json

这个脚本会：
1. 读取 font.json，遍历所有页码和所有位置
2. 对于每个非空字符，计算编码值：page_num * 256 + y * 16 + x
3. 完全从 font.json 生成 event.json，格式为 {"编码值(十六进制)": "字符"}
4. 不考虑现有的 event.json，完全以 font.json 为准
"""

import json
from pathlib import Path

def generate_event_json_from_font(font_json_path, event_json_path):
    """从 font.json 完全生成 event.json"""
    print(f"加载 font.json: {font_json_path}")
    
    # 读取 font.json
    with open(font_json_path, 'r', encoding='utf-8') as f:
        font_data = json.load(f)
    
    # 生成 event.json 数据
    event_data = {}
    total_chars = 0
    
    # 遍历所有页码
    for page_str in sorted(font_data.keys(), key=lambda x: int(x)):
        page_num = int(page_str)
        page_data = font_data[page_str]
        
        # 遍历16x16网格
        for y in range(16):
            if y >= len(page_data):
                continue
            row = page_data[y]
            for x in range(16):
                if x >= len(row):
                    continue
                
                char = row[x]
                
                # 只处理非空字符
                if char and char != "":
                    # 计算编码值：page_num * 256 + y * 16 + x
                    # 与 generate_font_images.py 中的公式保持一致
                    code = page_num * 256 + y * 16 + x
                    
                    # 转换为十六进制字符串（4位，小写）
                    hex_code_str = f"{code:04x}"
                    
                    # 添加到 event.json 数据中
                    # 如果同一个编码值出现多次（理论上不应该），后面的会覆盖前面的
                    event_data[hex_code_str] = char
                    total_chars += 1
    
    print(f"从 font.json 提取了 {total_chars} 个字符")
    
    # 按编码值排序（转换为整数后排序）
    sorted_event_data = {
        k: event_data[k] 
        for k in sorted(event_data.keys(), key=lambda x: int(x, 16))
    }
    
    # 保存 event.json
    print(f"\n保存 event.json: {event_json_path}")
    with open(event_json_path, 'w', encoding='utf-8') as f:
        json.dump(sorted_event_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n完成!")
    print(f"  event.json 包含 {len(sorted_event_data)} 个字符映射")
    
    # 计算编码范围
    if sorted_event_data:
        min_code = min(int(k, 16) for k in sorted_event_data.keys())
        max_code = max(int(k, 16) for k in sorted_event_data.keys())
        print(f"  编码范围: 0x{min_code:04x} - 0x{max_code:04x}")

if __name__ == "__main__":
    script_dir = Path(__file__).parent
    font_json_path = script_dir / "locale" / "font.json"
    event_json_path = script_dir / "locale" / "event.json"
    
    if not font_json_path.exists():
        print(f"错误: 找不到 font.json: {font_json_path}")
        exit(1)
    
    generate_event_json_from_font(font_json_path, event_json_path)
