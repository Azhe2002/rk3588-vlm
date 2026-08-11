#!/usr/bin/env python3
"""板端 HTTP 推理复现测试: 640x480 vs 320x240 各 N 轮 (与 8月7日 rk3588-vlm 链路一致)"""
import base64, json, sys, time, urllib.request

def infer(image_b64, question, system_prompt, seed, temp=0.1, max_tokens=32):
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": question},
            ]},
        ],
        "temperature": temp,
        "max_tokens": max_tokens,
        "seed": seed,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8088/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    dt = time.time() - t0
    return dt, data['choices'][0]['message']['content']

def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    with open('/tmp/img_640.jpg', 'rb') as f:
        b64_640 = base64.b64encode(f.read()).decode()
    with open('/tmp/img_320.jpg', 'rb') as f:
        b64_320 = base64.b64encode(f.read()).decode()
    q = "Is there a black industrial fan in the center of the image? Please answer only yes or no."
    sys_p = "You are an expert in recognition. Please respond with only 'yes' or 'no'. Detection target: industrial items. Scene: factory warehouse, dim lighting."
    print("=== 640x480 ===")
    for i in range(rounds):
        dt, out = infer(b64_640, q, sys_p, seed=i)
        print(f"seed{i}: {dt:.1f}s | {out}")
    print("=== 320x240 ===")
    for i in range(rounds):
        dt, out = infer(b64_320, q, sys_p, seed=i)
        print(f"seed{i}: {dt:.1f}s | {out}")

if __name__ == '__main__':
    main()
