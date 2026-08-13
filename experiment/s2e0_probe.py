#!/usr/bin/env python3
"""S2-E0 能力探测 (板端运行): 2 图 × 6 条件 × 2 重复 = 24 请求
条件: baseline / seed / cache_prompt=false / n_probs / grammar / response_format
输出: /tmp/s2e0/resp_XX.json (完整响应) + /tmp/s2e0/probe_summary.json
"""
import base64, json, os, sys, time, urllib.request, urllib.error

HOST = "http://127.0.0.1:8088/v1/chat/completions"
OUTDIR = "/tmp/s2e0"
os.makedirs(OUTDIR, exist_ok=True)

SYSTEM = ("You are an expert in recognition, processing, and analysis. "
          "Please carefully analyze the image and answer the question accurately. "
          "Please respond with only 'yes' or 'no'. "
          "Detection target: industrial items. Scene: factory warehouse, dim lighting.")
QUESTION = "Is there a black industrial fan in the center of the image? Please answer only yes or no."

YESNO_GRAMMAR = r'''
root ::= ("Yes." | "No." | "yes" | "no" | "Yes" | "No")
'''

JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "yesno",
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string", "enum": ["yes", "no"]}},
            "required": ["answer"],
        },
    },
}

def build_payload(img_b64, cond):
    """text→image 顺序 (与 C 客户端一致)"""
    p = {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": QUESTION},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ]},
        ],
        "temperature": 0.0,
        "max_tokens": 16,
    }
    if cond == "seed":
        p["temperature"] = 0.5
        p["seed"] = 17001
    elif cond == "cache_off":
        p["cache_prompt"] = False
    elif cond == "n_probs":
        p["n_probs"] = 5
    elif cond == "grammar":
        p["grammar"] = YESNO_GRAMMAR
    elif cond == "response_format":
        p["response_format"] = JSON_SCHEMA
    return p

def request(img_b64, cond, idx):
    payload = build_payload(img_b64, cond)
    req = urllib.request.Request(
        HOST,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    status, body, err = None, None, None
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            status = resp.status
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read().decode()
        err = str(e)
    except Exception as e:
        err = str(e)
    dt = time.time() - t0
    rec = {"idx": idx, "cond": cond, "http_status": status,
           "latency_s": round(dt, 2), "error": err, "response": body}
    with open(f"{OUTDIR}/resp_{idx:02d}.json", "w") as f:
        json.dump(rec, f, indent=1)
    return rec

def main():
    with open("/tmp/s2e0/img_pos.jpg", "rb") as f:
        b64_pos = base64.b64encode(f.read()).decode()
    with open("/tmp/s2e0/img_neg.jpg", "rb") as f:
        b64_neg = base64.b64encode(f.read()).decode()
    conds = ["baseline", "seed", "cache_off", "n_probs", "grammar", "response_format"]
    results = []
    idx = 0
    for img_name, img_b64 in [("pos", b64_pos), ("neg", b64_neg)]:
        for cond in conds:
            for rep in (1, 2):
                idx += 1
                rec = request(img_b64, cond, idx)
                rec.update({"img": img_name, "rep": rep})
                results.append({k: v for k, v in rec.items() if k != "response"})
                print(f"[{idx:02d}] {img_name} {cond} rep{rep}: "
                      f"http={rec['http_status']} {rec['latency_s']}s", flush=True)
    with open(f"{OUTDIR}/probe_summary.json", "w") as f:
        json.dump(results, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
