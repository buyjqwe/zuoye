import os
import time
import argparse
import requests
import polib
from tqdm import tqdm # 引入进度条库
from concurrent.futures import ThreadPoolExecutor, as_completed # 引入并发库

# --- 配置 ---
# vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv
# V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V
#  请在此处直接填入您的 Cloudflare 凭证
# V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V V

CF_ACCOUNT_ID = "2222"
CF_API_TOKEN = "1111"

# ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


# Cloudflare Workers AI API 端点和模型
API_ENDPOINT = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/meta/m2m100-1.2b"
HEADERS = {"Authorization": f"Bearer {CF_API_TOKEN}"}


def translate_text(text: str, source_lang: str, target_lang: str) -> tuple[str, str | None]:
    """
    翻译单段文本。
    返回一个元组 (原始文本, 翻译后的文本)，方便在并发环境中将结果匹配回原始条目。
    """
    if not text.strip():
        return text, "" # 返回原文和空字符串

    payload = {"text": text, "source_lang": source_lang, "target_lang": target_lang}
    
    try:
        # 发送请求，超时设置为30秒
        response = requests.post(API_ENDPOINT, headers=HEADERS, json=payload, timeout=30)
        
        # 如果遇到速率限制(429)或服务器错误(5xx)，则等待5秒后重试一次
        if response.status_code == 429 or response.status_code >= 500:
             time.sleep(5)
             response = requests.post(API_ENDPOINT, headers=HEADERS, json=payload, timeout=30)

        response.raise_for_status() # 如果请求失败 (例如 4xx or 5xx), 抛出异常
        data = response.json()

        if data.get("success") and data.get("result"):
            return text, data["result"]["translated_text"]
        else:
            # 记录API返回的特定错误信息
            # print(f"\n[!] API 返回错误: {data.get('errors')} (原文: '{text[:30]}...')")
            return text, None
            
    except requests.exceptions.RequestException as e:
        # 记录网络请求相关的错误
        # print(f"\n[!] API 请求异常: {e} (原文: '{text[:30]}...')")
        return text, None


def process_po_file(input_file: str, output_file: str, src_lang: str, tgt_lang: str, force: bool, workers: int):
    """
    使用并发线程池处理 .po 文件。
    """
    if "在这里填入您" in CF_ACCOUNT_ID or "在这里填入您" in CF_API_TOKEN:
        print("错误：请先编辑脚本文件，填入您的 CLOUDFLARE_ACCOUNT_ID 和 CLOUDFLARE_API_TOKEN。")
        return

    try:
        po = polib.pofile(input_file, encoding='utf-8')
    except Exception as e:
        print(f"错误: 无法读取或解析文件 '{input_file}': {e}")
        return

    # 创建一个从 msgid 到 entry 对象的映射，方便后面快速、安全地更新条目
    entry_map = {entry.msgid: entry for entry in po if entry.msgid}

    # 筛选出所有需要翻译的条目
    entries_to_translate = []
    for entry in po:
        if entry.msgid == '' or entry.obsolete: continue
        if entry.msgstr and not force: continue
        # 跳过纯粹的占位符
        if all(char in '%s(){}[] ' for char in entry.msgid): continue
        entries_to_translate.append(entry)
    
    total_to_translate = len(entries_to_translate)
    if total_to_translate == 0:
        print("没有需要翻译的条目。")
        # 即使没有翻译，也保存一份输出文件，以保持流程一致性
        po.save(output_file)
        return

    print(f"文件 '{input_file}' 加载成功，共 {len(po)} 个条目，其中 {total_to_translate} 个需要翻译。")
    print(f"源语言: {src_lang}, 目标语言: {tgt_lang}, 并发数: {workers}")
    print("-" * 30)
    
    translated_count = 0
    
    # 使用线程池执行并发翻译
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # 准备提交给线程池的所有翻译任务
        futures = {executor.submit(translate_text, entry.msgid, src_lang, tgt_lang) for entry in entries_to_translate}
        
        # 使用 tqdm 创建一个进度条，实时显示任务完成情况
        for future in tqdm(as_completed(futures), total=total_to_translate, desc="翻译进度"):
            try:
                original_text, translated_text = future.result()
                if translated_text is not None:
                    # 通过之前创建的映射，找到原始的 entry 对象并更新其译文
                    if original_text in entry_map:
                        entry_map[original_text].msgstr = translated_text
                        translated_count += 1
            except Exception as e:
                print(f"处理一个翻译结果时出错: {e}")

    print("-" * 30)
    print("翻译完成！")
    print(f"成功翻译条目总数: {translated_count} / {total_to_translate}")

    try:
        po.save(output_file)
        print(f"结果已保存到: '{output_file}'")
    except Exception as e:
        print(f"错误: 无法保存文件 '{output_file}': {e}")


def main():
    parser = argparse.ArgumentParser(
        description="使用 Cloudflare AI 并发翻译 .po 文件。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("input_file", help="输入的 .po 文件路径。")
    parser.add_argument("output_file", help="输出的 .po 文件路径。")
    parser.add_argument("-sl", "--source-lang", required=True, help="源语言代码 (例如: en)。")
    parser.add_argument("-tl", "--target-lang", required=True, help="目标语言代码 (例如: zh)。")
    parser.add_argument("--force", action="store_true", help="强制重新翻译已有译文的条目。")
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="并发执行的线程数 (默认: 10)。"
    )

    args = parser.parse_args()

    process_po_file(
        args.input_file,
        args.output_file,
        args.source_lang,
        args.target_lang,
        args.force,
        args.workers
    )

if __name__ == "__main__":
    main()
