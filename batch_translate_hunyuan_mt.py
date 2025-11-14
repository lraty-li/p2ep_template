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
API_BASE_URL = "http://127.0.0.1:8080/v1/chat/completions"
MODEL = "gpt-4o-mini"  # 或 "gpt-3.5-turbo", "gpt-4" 等
MAX_RETRIES = 3
RETRY_DELAY = 1  # 秒


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
        "version": "1.1",
        "source_file": str(texts_file),
        "output_file": str(output_file),
        "completed": {},  # {"file_key": [idx1, idx2, ...]} - 只存储索引，不存储翻译文本
        "failed": {},     # {"file_key": [idx1, idx2, ...]} - 只存储索引，不存储任何其他信息
        "stats": {
            "total": 0,
            "completed": 0,
            "failed": 0
        }
    }


def get_task_key(file_key: str, idx: int) -> str:
    """生成任务唯一标识"""
    return f"{file_key}:{idx}"


def load_translated_from_output(output_file: Path, original_texts_dict: Dict[str, List[Dict]]) -> Dict[str, Dict[int, str]]:
    """
    从输出文件加载已翻译的文本（通过比较原文和译文判断）
    
    返回: {"file_key": {idx: "translated_text"}}
    """
    if not output_file.exists():
        return {}
    
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            output_data = json.load(f)
        
        # 处理嵌套结构
        if "texts" in output_data:
            output_texts_dict = output_data.get("texts", {})
        else:
            output_texts_dict = output_data
        
        translated_dict = {}
        for file_key, file_texts in output_texts_dict.items():
            if file_key not in original_texts_dict:
                continue
            
            translated_dict[file_key] = {}
            for idx, item in enumerate(file_texts):
                if idx < len(original_texts_dict[file_key]):
                    original_text = original_texts_dict[file_key][idx].get("text", "").strip()
                    # 如果原始文本为空，跳过（不恢复空字符串的翻译）
                    if not original_text:
                        continue
                    
                    translated_text = item.get("text", "").strip()
                    # 如果翻译文本存在且与原文不同，说明已翻译
                    if translated_text and translated_text != original_text:
                        translated_dict[file_key][idx] = translated_text
        
        return translated_dict
    except Exception as e:
        print(f"警告: 无法从输出文件加载已翻译内容: {e}")
        return {}


def translate_text(text: str, api_key: str, source_lang: str = "日语", target_lang: str = "简体中文") -> Tuple[Optional[str], Optional[str]]:
    """
    使用 GPT API 翻译文本
    
    Args:
        text: 要翻译的文本
        api_key: API 密钥
        source_lang: 源语言
        target_lang: 目标语言
    
    返回 (翻译后的文本, 错误信息)
    成功时返回 (translated_text, None)
    失败时返回 (None, error_message)
    """
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
    
    # 游戏控制字符列表（需要原样保留）
    control_chars_info = """
游戏控制字符（必须原样保留，不要翻译）：
    以 [ 开头，以 ] 结尾
    连大小写都不准改变
"""
    
    # 根据模型说明：模型没有默认 system_prompt，所以只使用 user message
    # 按照模型要求的 prompt 模板格式（ZH<=>XX 翻译）
    # 格式：把下面的文本翻译成<target_language>，不要额外解释。\n\n<source_text>
    # 注意：这是游戏文本，需要理解日语语义（禁止音译），片假名和平假名按语义翻译
    # 游戏控制字符（[xxx]格式）必须原样保留
    
    # 计算原文长度（用于后处理检查）
    original_length = len(text)
    
    for attempt in range(MAX_RETRIES):
        # 如果是重试（因为长度过长），使用更严格的 prompt
        if attempt > 0:
            user_message = f"只翻译，不要解释。把下面的文本翻译成简体中文：\n\n{text}"
        else:
            user_message = f"把下面的文本翻译成简体中文，不要额外解释。\n\n{text}"
        
        data = {
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": user_message
                }
            ],
            # 使用模型建议的生成参数
            "temperature": 0.7,
            "top_k": 20,
            "top_p": 0.6,
            "repetition_penalty": 1.05
        }
        
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
            
            # 后处理检查：如果翻译结果比原文长2倍，重新翻译
            translated_length = len(translated_text)
            if translated_length > original_length * 2:
                print(f"  警告: 翻译结果过长（原文{original_length}字符，译文{translated_length}字符），可能包含解释，重新翻译...")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                else:
                    # 如果重试次数用完，标记为失败翻译
                    error_msg = f"翻译结果过长（原文{original_length}字符，译文{translated_length}字符），可能包含解释"
                    print(f"  错误: {error_msg}")
                    return None, error_msg
            
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


def batch_translate_texts(texts_file: Path, api_key_file: Path, output_file: Path = None, dry_run: bool = False, debug: bool = False, max_workers: int = 5, debug_limit: int = 5, progress_file: Path = None, resume: bool = True, retry_failed: bool = False):
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
    
    # 读取 texts.json
    with open(texts_file, 'r', encoding='utf-8') as f:
        texts_data = json.load(f)
    
    # 深拷贝数据，避免修改原数据
    texts_data = copy.deepcopy(texts_data)
    
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
    
    # texts.json 结构: {"E0000": [...], "E0001": [...], ...}
    # 如果包含 "speakers" 和 "texts" 键，则使用嵌套结构
    if "texts" in texts_data and "speakers" in texts_data:
        texts_dict = texts_data.get("texts", {})
        speakers_dict = texts_data.get("speakers", {})
    else:
        # 直接结构，以文件名作为键
        texts_dict = texts_data
        speakers_dict = {}
    
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
    
    # 从输出文件和进度文件恢复已翻译的文本
    completed_dict = progress_data.get("completed", {})
    failed_dict = progress_data.get("failed", {})
    progress_version = progress_data.get("version", "1.0")
    restored_count = 0
    
    # 保存原始 texts_dict 用于比较
    original_texts_dict = copy.deepcopy(texts_dict)
    
    if resume:
        # 从输出文件恢复已翻译的内容
        translated_from_output = load_translated_from_output(output_file, original_texts_dict)
        
        # 根据进度文件中的索引恢复
        for file_key in completed_dict:
            if file_key not in texts_dict:
                continue
            
            completed_items = completed_dict[file_key]
            
            # 处理新格式（索引列表）和旧格式（字典）
            if isinstance(completed_items, list):
                # 新格式：索引列表
                for idx in completed_items:
                    if isinstance(idx, int) and 0 <= idx < len(texts_dict[file_key]):
                        # 检查原始文本是否为空，如果为空则跳过
                        original_text = original_texts_dict[file_key][idx].get("text", "").strip()
                        if not original_text:
                            continue
                        
                        # 优先从输出文件恢复
                        if file_key in translated_from_output and idx in translated_from_output[file_key]:
                            texts_dict[file_key][idx]["text"] = translated_from_output[file_key][idx]
                            restored_count += 1
            else:
                # 旧格式：字典 {idx: translated_text}
                for idx_str, translated_text in completed_items.items():
                    try:
                        idx = int(idx_str)
                        if 0 <= idx < len(texts_dict[file_key]):
                            # 检查原始文本是否为空，如果为空则跳过
                            original_text = original_texts_dict[file_key][idx].get("text", "").strip()
                            if not original_text:
                                continue
                            
                            # 优先从输出文件恢复，否则使用进度文件中的内容
                            if file_key in translated_from_output and idx in translated_from_output[file_key]:
                                texts_dict[file_key][idx]["text"] = translated_from_output[file_key][idx]
                            else:
                                texts_dict[file_key][idx]["text"] = translated_text
                            restored_count += 1
                    except (ValueError, IndexError):
                        pass
        
        # 恢复输出文件中有但进度文件中没有的（可能进度文件丢失）
        for file_key, translated_items in translated_from_output.items():
            if file_key not in texts_dict:
                continue
            for idx, translated_text in translated_items.items():
                # 检查原始文本是否为空，如果为空则跳过
                if 0 <= idx < len(original_texts_dict.get(file_key, [])):
                    original_text = original_texts_dict[file_key][idx].get("text", "").strip()
                    if not original_text:
                        continue
                
                # 检查是否已在进度文件中
                is_in_progress = False
                if file_key in completed_dict:
                    if isinstance(completed_dict[file_key], list):
                        is_in_progress = idx in completed_dict[file_key]
                    else:
                        is_in_progress = str(idx) in completed_dict[file_key]
                
                if not is_in_progress and 0 <= idx < len(texts_dict[file_key]):
                    texts_dict[file_key][idx]["text"] = translated_text
                    restored_count += 1
    
    if restored_count > 0:
        print(f"从输出文件和进度文件恢复了 {restored_count} 个已翻译的文本")
    
    total_texts = 0
    translated_count = 0
    empty_count = 0
    
    # 统计文本数量
    for file_key, file_texts in texts_dict.items():
        for item in file_texts:
            text = item.get("text", "").strip()
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
        
        # 从 speakers_translated.json 恢复已翻译的 speakers
        if resume:
            # 尝试从输出文件恢复（嵌套结构）
            if output_file.exists():
                try:
                    with open(output_file, 'r', encoding='utf-8') as f:
                        output_data = json.load(f)
                    if "speakers" in output_data:
                        output_speakers = output_data["speakers"]
                        for speaker_key in speaker_keys:
                            if speaker_key in output_speakers:
                                translated_value = output_speakers[speaker_key]
                                if translated_value and translated_value.strip():
                                    speakers_dict[speaker_key] = translated_value
                except Exception as e:
                    print(f"警告: 从输出文件恢复 speakers 失败: {e}")
            
            # 尝试从单独的 speakers_translated.json 文件恢复（直接结构）
            speakers_translated_file = texts_file.parent / "speakers_translated.json"
            if speakers_translated_file.exists():
                try:
                    with open(speakers_translated_file, 'r', encoding='utf-8') as f:
                        output_speakers = json.load(f)
                    for speaker_key in speaker_keys:
                        if speaker_key in output_speakers:
                            translated_value = output_speakers[speaker_key]
                            if translated_value and translated_value.strip():
                                speakers_dict[speaker_key] = translated_value
                except Exception as e:
                    print(f"警告: 从 speakers_translated.json 恢复失败: {e}")
            
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
                
                print(f"  [{speaker_idx+1}/{len(speaker_keys)}] 翻译 speaker: {speaker_key[:50]}...")
                
                translated, error_msg = translate_text(speaker_key, api_key)
                
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
                                # 保存输出文件和进度文件
                                if "texts" in texts_data or "speakers" in texts_data:
                                    texts_data["texts"] = texts_dict
                                    texts_data["speakers"] = speakers_dict
                                    save_data = texts_data
                                else:
                                    save_data = texts_dict
                                
                                with speakers_file_lock:
                                    with open(output_file, 'w', encoding='utf-8') as f:
                                        json.dump(save_data, f, ensure_ascii=False, indent=2)
                                    
                                    # 如果是直接结构且有speakers，也保存到单独的speakers_translated.json（不覆盖原文件）
                                    if speakers_dict and not ("texts" in texts_data or "speakers" in texts_data):
                                        speakers_output_file = output_file.parent / "speakers_translated.json"
                                        try:
                                            with open(speakers_output_file, 'w', encoding='utf-8') as f:
                                                json.dump(speakers_dict, f, ensure_ascii=False, indent=2)
                                        except Exception as e:
                                            pass  # 定期保存时静默失败，避免输出太多
                                
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
            
            # 最终保存
            if "texts" in texts_data or "speakers" in texts_data:
                texts_data["texts"] = texts_dict
                texts_data["speakers"] = speakers_dict
                save_data = texts_data
            else:
                save_data = texts_dict
                if speakers_dict:
                    speakers_output_file = output_file.parent / "speakers_translated.json"
                    try:
                        with open(speakers_output_file, 'w', encoding='utf-8') as f:
                            json.dump(speakers_dict, f, ensure_ascii=False, indent=2)
                        print(f"Speakers 已保存到: {speakers_output_file}")
                    except Exception as e:
                        print(f"警告: 保存 speakers_translated.json 失败: {e}")
            
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"警告: 保存输出文件失败: {e}")
            
            # 计算统计信息（直接从 speakers_dict 计算）
            speakers_completed_total = sum(1 for v in speakers_dict.values() if v and v.strip())
            
            # 保存进度文件（不包含 speakers 信息）
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
            # 从 original_texts_dict 读取原文，而不是从可能已被恢复翻译的 texts_dict 读取
            if file_key in original_texts_dict and idx < len(original_texts_dict[file_key]):
                original_text = original_texts_dict[file_key][idx].get("text", "").strip()
            else:
                original_text = item.get("text", "").strip()
            # 跳过空字符串
            if not original_text:
                continue
            
            # 检查是否已完成（支持新旧格式）
            is_completed = False
            if file_key in completed_dict:
                completed_items = completed_dict[file_key]
                if isinstance(completed_items, list):
                    # 新格式：索引列表
                    is_completed = idx in completed_items
                else:
                    # 旧格式：字典
                    is_completed = str(idx) in completed_items
            
            # 检查是否是失败的文本（支持新旧格式）
            is_failed = False
            if file_key in failed_dict:
                failed_items = failed_dict[file_key]
                if isinstance(failed_items, list):
                    # 新格式：索引列表
                    is_failed = idx in failed_items
                else:
                    # 旧格式：字典（兼容处理）
                    is_failed = str(idx) in failed_items
            
            # 如果已完成且不是重试失败模式，跳过
            if is_completed and not retry_failed:
                skipped_count += 1
                continue
            
            # 如果是重试失败模式，只处理失败的文本
            if retry_failed and not is_failed:
                continue
            
            # 如果是重试失败的文本，记录
            if retry_failed and is_failed:
                retry_count += 1
            
            tasks.append({
                "file_key": file_key,
                "idx": idx,
                "item": item,
                "text": original_text,
                "total_in_file": len(file_texts),
                "is_retry": is_failed
            })
    
    if skipped_count > 0:
        print(f"跳过已完成的文本: {skipped_count} 个")
    if retry_count > 0:
        print(f"准备重试失败的文本: {retry_count} 个")
    
    # 调试模式限制任务数量
    if debug:
        tasks = tasks[:debug_limit]
        print(f"调试模式: 限制任务数为 {len(tasks)}")
    
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
        item = task_info["item"]
        original_text = task_info["text"]
        total_in_file = task_info["total_in_file"]
        is_retry = task_info.get("is_retry", False)
        
        # 再次检查空字符串（防止意外情况）
        if not original_text or not original_text.strip():
            return False
        
        # 检查调试模式限制
        with translated_count_lock:
            current_completed = completed_count
            if debug and current_completed >= debug_limit:
                return False
        
        retry_prefix = "[重试] " if is_retry else ""
        print(f"  {retry_prefix}[{file_key}][{idx+1}/{total_in_file}] 翻译: {original_text[:50]}...")
        
        translated, error_msg = translate_text(original_text, api_key)
        
        with translated_count_lock:
            completed_count += 1
            
            # 更新进度记录
            with progress_lock:
                # 确保使用新格式（索引列表）
                if progress_data.get("version", "1.0") < "1.1":
                    progress_data["version"] = "1.1"
                    # 升级旧格式
                    old_completed = progress_data.get("completed", {})
                    new_completed = {}
                    for fk, items in old_completed.items():
                        if isinstance(items, dict):
                            new_completed[fk] = [int(k) for k in items.keys() if k.isdigit()]
                        else:
                            new_completed[fk] = items
                    progress_data["completed"] = new_completed
                
                if file_key not in progress_data["completed"]:
                    progress_data["completed"][file_key] = []
                if file_key not in progress_data["failed"]:
                    progress_data["failed"][file_key] = []
                
                idx_str = str(idx)
                
                if translated:
                    item["text"] = translated
                    translated_count_local += 1
                    # 记录成功（只保存索引）
                    if idx not in progress_data["completed"][file_key]:
                        progress_data["completed"][file_key].append(idx)
                    # 如果之前失败过，从失败记录中移除
                    if file_key in progress_data["failed"]:
                        failed_items = progress_data["failed"][file_key]
                        if isinstance(failed_items, list):
                            if idx in failed_items:
                                failed_items.remove(idx)
                        else:
                            # 旧格式：字典（兼容处理）
                            if idx_str in failed_items:
                                del failed_items[idx_str]
                    print(f"    [{file_key}][{idx+1}] 完成: {translated[:50]}...")
                else:
                    # 记录失败（只保存索引）
                    failed_count_local += 1
                    if file_key not in progress_data["failed"]:
                        progress_data["failed"][file_key] = []
                    # 确保是新格式（索引列表）
                    if not isinstance(progress_data["failed"][file_key], list):
                        # 升级旧格式
                        old_failed = progress_data["failed"][file_key]
                        progress_data["failed"][file_key] = [int(k) for k in old_failed.keys() if k.isdigit()]
                    # 添加索引（如果不存在）
                    if idx not in progress_data["failed"][file_key]:
                        progress_data["failed"][file_key].append(idx)
                    print(f"    [{file_key}][{idx+1}] 翻译失败: {error_msg or '未知错误'}")
            
            # 更新统计信息
            progress_data["stats"]["completed"] = sum(len(indices) if isinstance(indices, list) else (len(indices) if isinstance(indices, dict) else 0) for indices in progress_data["completed"].values())
            progress_data["stats"]["failed"] = sum(len(indices) if isinstance(indices, list) else (len(indices) if isinstance(indices, dict) else 0) for indices in progress_data["failed"].values())
        
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
                            # 保存输出文件和进度文件
                            if "texts" in texts_data or "speakers" in texts_data:
                                texts_data["texts"] = texts_dict
                                texts_data["speakers"] = speakers_dict
                                save_data = texts_data
                            else:
                                save_data = texts_dict
                            
                            with file_lock:
                                with open(output_file, 'w', encoding='utf-8') as f:
                                    json.dump(save_data, f, ensure_ascii=False, indent=2)
                                
                                # 如果是直接结构且有speakers，也保存到单独的speakers_translated.json（不覆盖原文件）
                                if speakers_dict and not ("texts" in texts_data or "speakers" in texts_data):
                                    speakers_output_file = output_file.parent / "speakers_translated.json"
                                    try:
                                        with open(speakers_output_file, 'w', encoding='utf-8') as f:
                                            json.dump(speakers_dict, f, ensure_ascii=False, indent=2)
                                    except Exception as e:
                                        pass  # 定期保存时静默失败，避免输出太多
                            
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
    
    # 最终保存
    if "texts" in texts_data or "speakers" in texts_data:
        texts_data["texts"] = texts_dict
        texts_data["speakers"] = speakers_dict
        save_data = texts_data
    else:
        save_data = texts_dict
        # 直接结构，speakers 保存到单独的 speakers_translated.json 文件（不覆盖原文件）
        if speakers_dict:
            speakers_output_file = output_file.parent / "speakers_translated.json"
            try:
                with open(speakers_output_file, 'w', encoding='utf-8') as f:
                    json.dump(speakers_dict, f, ensure_ascii=False, indent=2)
                print(f"Speakers 已保存到: {speakers_output_file}")
            except Exception as e:
                print(f"警告: 保存 speakers_translated.json 失败: {e}")
    
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"警告: 保存输出文件失败: {e}")
    
    # 最终保存进度文件
    try:
        with progress_lock:
            progress_data["stats"]["total"] = total_texts
            if speakers_dict:
                progress_data["stats"]["speakers_total"] = len(speakers_dict)
            save_progress(progress_file, progress_data)
    except Exception as e:
        print(f"警告: 保存进度文件失败: {e}")
    
    translated_count = translated_count_local
    failed_count = failed_count_local
    
    # 计算 speakers 统计信息（直接从 speakers_dict 计算）
    if speakers_dict:
        speakers_completed_total = sum(1 for v in speakers_dict.values() if v and v.strip())
    
    if interrupted:
        print(f"\n翻译已中断，进度已保存!")
        print(f"  本次翻译文本: {translated_count} 个")
        print(f"  本次失败文本: {failed_count} 个")
        if speakers_dict:
            print(f"  本次翻译 speakers: {speakers_completed_count} 个")
            print(f"  本次失败 speakers: {speakers_failed_count} 个")
        print(f"  总计完成文本: {progress_data['stats']['completed']}/{total_texts if not debug else min(total_texts, debug_limit)}")
        print(f"  总计失败文本: {progress_data['stats']['failed']} 个")
        if speakers_dict:
            print(f"  总计完成 speakers: {speakers_completed_total}/{len(speakers_dict)}")
        print(f"  输出文件: {output_file}")
        print(f"  进度文件: {progress_file}")
        print(f"\n提示: 重新运行脚本将自动从上次中断的地方继续")
    else:
        print(f"\n翻译完成!")
        print(f"  本次翻译文本: {translated_count} 个")
        print(f"  本次失败文本: {failed_count} 个")
        if speakers_dict:
            print(f"  本次翻译 speakers: {speakers_completed_count} 个")
            print(f"  本次失败 speakers: {speakers_failed_count} 个")
        print(f"  总计完成文本: {progress_data['stats']['completed']}/{total_texts if not debug else min(total_texts, debug_limit)}")
        print(f"  总计失败文本: {progress_data['stats']['failed']} 个")
        if speakers_dict:
            print(f"  总计完成 speakers: {speakers_completed_total}/{len(speakers_dict)}")
        print(f"  输出文件: {output_file}")
        print(f"  进度文件: {progress_file}")
        if progress_data['stats']['failed'] > 0:
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
    parser.add_argument("--threads", type=int, default=5, help="最大并发线程数（默认: 5）")
    parser.add_argument("--limit", type=int, default=5, help="调试模式下限制翻译的任务数（默认: 5）")
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
            args.retry_failed
        )
    except KeyboardInterrupt:
        # 如果 batch_translate_texts 没有捕获到，这里作为最后的保障
        print("\n\n程序被用户中断")
        sys.exit(130)  # 130 是 CTRL+C 的标准退出码


if __name__ == "__main__":
    main()
