"""测试银联(UnionPay) LLM API 连通性和可用性
参考: unionpay.md
"""
import requests
import json
import time
import sys
import io

# Fix Windows GBK encoding issues
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API_URL = "https://ai.upcloud.unionpay.com/v1/chat/completions"
API_KEY = "b9716c4a-2a1c-4965-93c5-d2b0ec80a1f2"
MODEL = "qwen3.5-35b"

def test_chat():
    """测试基础对话"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "你好，请用一句话介绍你自己"}
        ]
    }
    
    print(f"[Test] 测试基础对话: {MODEL}")
    print(f"[Test] URL: {API_URL}")
    
    try:
        t0 = time.time()
        resp = requests.post(API_URL, json=data, headers=headers, timeout=30)
        elapsed = time.time() - t0
        
        print(f"[Info] HTTP Status: {resp.status_code}")
        print(f"[Info] 耗时: {elapsed:.2f}s")
        print(f"[Info] Content-Length: {len(resp.text)}, Content-Type: {resp.headers.get('Content-Type', 'N/A')}")
        
        # Always print raw response preview
        raw_preview = resp.text[:500]
        print(f"[Debug] Raw body: {raw_preview}")
        
        if resp.status_code == 200:
            if not resp.text.strip():
                print(f"[FAIL] HTTP 200 but empty body - API returned nothing")
                return False
            
            result = resp.json()
            choice = result.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content", "")
            usage = result.get("usage", {})
            
            print(f"[OK] API 连通正常")
            print(f"[Response] {content}")
            print(f"[Usage] prompt={usage.get('prompt_tokens')}, completion={usage.get('completion_tokens')}, total={usage.get('total_tokens')}")
            return True
        else:
            print(f"[FAIL] HTTP {resp.status_code}: {resp.text[:500]}")
            return False
    except requests.exceptions.ConnectTimeout:
        print(f"[FAIL] 连接超时 - API 地址不可达")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"[FAIL] 连接错误: {e}")
        return False
    except json.JSONDecodeError as e:
        print(f"[FAIL] JSON解析失败: {e}, 原始响应: {resp.text[:500]}")
        return False
    except Exception as e:
        print(f"[FAIL] 未知错误: {e}")
        return False

def test_stream():
    """测试流式输出"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "用一句话数1到5"}
        ],
        "stream": True
    }
    
    print(f"\n[Test] 测试流式输出: {MODEL}")
    
    try:
        t0 = time.time()
        resp = requests.post(API_URL, json=data, headers=headers, timeout=30, stream=True)
        
        if resp.status_code != 200:
            print(f"[FAIL] ❌ HTTP {resp.status_code}: {resp.text[:300]}")
            return False
        
        full_text = ""
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]  # strip "data: "
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full_text += content
                    print(content, end="", flush=True)
            except json.JSONDecodeError:
                pass
        
        elapsed = time.time() - t0
        print(f"\n[OK] ✅ 流式输出正常 ({len(full_text)} chars, {elapsed:.2f}s)")
        return True
    except Exception as e:
        print(f"[FAIL] ❌ 流式测试错误: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("银联 LLM API 连通性测试")
    print("=" * 50)
    
    ok1 = test_chat()
    ok2 = test_stream()
    
    print("\n" + "=" * 50)
    if ok1 and ok2:
        print("✅ 全部测试通过 - API Key 可用")
    else:
        print("❌ 存在失败测试 - 请检查 API Key / 网络")
    print("=" * 50)
