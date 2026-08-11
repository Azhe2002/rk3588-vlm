#!/usr/bin/env python3
"""板端 llama-server HTTP 推理测试: 640x480 vs 320x240 (复现 8月7日实验链路)"""
import base64, json, sys, time, urllib.request
import board

HOST = '192.168.1.8'
PORT = 8088

def infer(image_b64, question, system_prompt, seed=None, temp=0.1, max_tokens=32):
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
        f"http://{HOST}:{PORT}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    dt = time.time() - t0
    return dt, data['choices'][0]['message']['content']

def main():
    with open('/home/azhe/workspace/rk3588-vlm/experiment/rk3588_640x480.jpg', 'rb') as f:
        b64_640 = base64.b64encode(f.read()).decode()
    with open('/home/azhe/workspace/rk3588-vlm/experiment/rk3588_capture_320x240.jpg', 'rb') as f:
        b64_320 = base64.b64encode(f.read()).decode()
    q = "Is there a black industrial fan in the center of the image? Please answer only yes or no."
    sys_p = "You are an expert in recognition. Please respond with only 'yes' or 'no'. Detection target: industrial items. Scene: factory warehouse, dim lighting."
    print("=== 640x480 (10 rounds) ===")
    for i in range(10):
        dt, out = infer(b64_640, q, sys_p, seed=i)
        print(f"seed{i}: {dt:.1f}s | {out!r}")
    print("=== 320x240 (10 rounds) ===")
    for i in range(10):
        dt, out = infer(b64_320, q, sys_p, seed=i)
        print(f"seed{i}: {dt:.1f}s | {out!r}")

if __name__ == '__main__':
    main()
