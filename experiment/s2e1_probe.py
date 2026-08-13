#!/usr/bin/env python3
"""S2-E1 图文顺序消融探测 (板端运行)
读取 /tmp/s2e1/plan.json (frame + order 列表, 每帧两顺序随机先后),
逐请求发送 (cache_prompt=false, t=0.0, max_tokens=16, 无约束),
输出 /tmp/s2e1/rounds.jsonl (每行: frame_id/sha256/order/status/latency/raw/usage)
"""
import base64, hashlib, json, os, sys, time, urllib.request, urllib.error

HOST = "http://127.0.0.1:8088/v1/chat/completions"
DIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/s2e1"
FRAMES = f"{DIR}/frames"
OUT = f"{DIR}/rounds.jsonl"

SYSTEM = ("You are an expert in recognition, processing, and analysis. "
          "Please carefully analyze the image and answer the question accurately. "
          "Please respond with only 'yes' or 'no'. "
          "Detection target: industrial items. Scene: factory warehouse, dim lighting.")
QUESTION = "Is there a black industrial fan in the center of the image? Please answer only yes or no."

def build_payload(img_b64, order):
    """order: 'text-image' (C客户端顺序) / 'image-text' (历史静态脚本顺序)"""
    if order == "text-image":
        content = [
            {"type": "text", "text": QUESTION},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        ]
    else:
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            {"type": "text", "text": QUESTION},
        ]
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": content},
        ],
        "temperature": 0.0,
        "max_tokens": 16,
        "cache_prompt": False,
    }

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def request(img_b64, order):
    payload = build_payload(img_b64, order)
    req = urllib.request.Request(
        HOST,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
        dt = time.time() - t0
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        return {"http_status": 200, "latency_s": round(dt, 2),
                "raw_output": content, "usage": usage, "error": None}
    except urllib.error.HTTPError as e:
        dt = time.time() - t0
        return {"http_status": e.code, "latency_s": round(dt, 2),
                "raw_output": None, "usage": None,
                "error": e.read().decode()[:300]}
    except Exception as e:
        dt = time.time() - t0
        return {"http_status": None, "latency_s": round(dt, 2),
                "raw_output": None, "usage": None, "error": str(e)}

def main():
    plan = json.load(open(f"{DIR}/plan.json"))
    # 预加载全部帧 base64 (20 帧 × ~130KB ≈ 3.5MB, 内存可承受)
    cache = {}
    with open(OUT, "w") as out:
        for item in plan:
            fid = item["frame_id"]
            order = item["order"]
            if fid not in cache:
                p = f"{FRAMES}/{fid}"
                with open(p, "rb") as f:
                    cache[fid] = base64.b64encode(f.read()).decode()
            rec = request(cache[fid], order)
            rec.update({"frame_id": fid, "sha256": item["sha256"], "order": order})
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{fid} {order}: http={rec['http_status']} "
                  f"{rec['latency_s']}s out={rec['raw_output']!r}", flush=True)
    print("DONE")

if __name__ == "__main__":
    main()
