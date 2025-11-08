#!/usr/bin/env python3
"""
重建 font.json 为 UTF-8 中文字符集
按照 UTF-8 编码顺序自动生成字符，填充到各个页码
"""

import json
import os

# 每个页码有 16x16 = 256 个位置
CHARS_PER_PAGE = 256
GRID_SIZE = 16

def create_empty_page():
    """创建一个空的16x16字符网格"""
    return [["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]

def fill_page_with_chars(page, start_char_code, end_char_code):
    """用UTF-8字符范围填充页面"""
    char_code = start_char_code
    filled_count = 0
    
    for y in range(GRID_SIZE):
        for x in range(GRID_SIZE):
            if char_code > end_char_code:
                break
            
            try:
                char = chr(char_code)
                # 跳过控制字符和不可打印字符
                if char.isprintable() and not (0x00 <= char_code <= 0x1F) and char_code != 0x7F:
                    page[y][x] = char
                    filled_count += 1
            except (ValueError, OverflowError):
                pass
            
            char_code += 1
        
        if char_code > end_char_code:
            break
    
    return filled_count, char_code

def rebuild_font_json():
    """重建 font.json"""
    font_data = {}
    
    # 页码0：基本ASCII字符、标点符号、数字、大写字母
    page0 = create_empty_page()
    # ASCII可打印字符：0x20-0x7E (空格到~)
    fill_page_with_chars(page0, 0x20, 0x7E)
    # 补充一些常用标点
    page0[0][0] = " "  # 空格
    font_data["0"] = page0
    
    # 页码1：小写字母、扩展ASCII、常用符号
    page1 = create_empty_page()
    # 小写字母已经在ASCII中，这里可以放扩展字符
    # 拉丁扩展A：0x0100-0x017F
    fill_page_with_chars(page1, 0x0100, 0x017F)
    # 如果不够，继续填充其他范围
    font_data["1"] = page1
    
    # 页码2-31：中文字符
    # CJK统一汉字：0x4E00-0x9FFF (共20992个字符)
    # 每个页码256个位置，30个页码可以放7680个字符
    start_cjk = 0x4E00  # CJK统一汉字起始
    end_cjk = 0x9FFF    # CJK统一汉字结束
    
    current_char = start_cjk
    
    for page_num in range(2, 32):  # 页码2到31
        page = create_empty_page()
        filled, next_char = fill_page_with_chars(page, current_char, end_cjk)
        font_data[str(page_num)] = page
        current_char = next_char
        
        if current_char > end_cjk:
            break
    
    return font_data

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, 'locale', 'font.json')
    
    print("正在重建 font.json...")
    print("按照 UTF-8 编码顺序生成字符...")
    
    font_data = rebuild_font_json()
    
    # 统计字符数量
    total_chars = 0
    for page_key, page_data in font_data.items():
        page_chars = sum(1 for row in page_data for char in row if char != "")
        total_chars += page_chars
        print(f"页码 {page_key}: {page_chars} 个字符")
    
    print(f"\n总计: {total_chars} 个字符")
    
    # 保存JSON文件
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(font_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n已保存到: {output_path}")

if __name__ == '__main__':
    main()

