#define _DEFAULT_SOURCE  // usleep/setenv/kill/popen 等 POSIX 扩展函数所需

#include "llama_server.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>
#include <errno.h>
#include <unistd.h>
#include <signal.h>
#include <fcntl.h>
#include <time.h>
#include <sys/wait.h>
#include <sys/types.h>
#include <curl/curl.h>

// ============================================================
// 第二版: 常驻 llama-server + HTTP 推理
//
// 第一版问题: 每次 llama_infer() 都通过 popen() 启动一个新的
// llama-mtmd-cli 进程，模型权重会被完整重新加载一次。对 500M~2B
// 级别的模型这通常是几百毫秒到几秒的固定开销，且每一轮推理都要
// 承担一次 —— 在 15s 间隔的循环里这是纯浪费。
//
// 现在的方案: llama_init() 时 fork+exec 一次 llama-server (llama.cpp
// 自带的 OpenAI 兼容 HTTP 服务，同样支持 --mmproj 多模态)，模型只
// 加载一次并常驻内存；llama_infer() 只是一次 HTTP 请求，往返通常
// 在几十到几百毫秒。llama_free() 时优雅关闭该子进程。
//
// 同时: 不再用 system()/popen() 拼接 shell 命令字符串 —— 那种写法里
// system_prompt/user_prompt 只做了替换双引号这一种"转义"，其余 shell
// 元字符 ($, `, ;, \ 等) 完全没处理，等于允许任意命令注入。这里全部
// 换成 fork+exec* 传 argv 数组，请求体则用 JSON 转义后通过 libcurl
// 发送，彻底绕开 shell 解析。
// ============================================================

#define SERVER_BIN          "/userdata/llama/bin/llama-server"
#define LIB_PATH            "/userdata/llama/bin"
#define SERVER_HOST         "127.0.0.1"
#define SERVER_PORT         8088
#define HEALTH_TIMEOUT_SEC  30
#define INFER_TIMEOUT_SEC   30

struct llama_handle {
    char    model_path[512];
    char    mmproj_path[512];
    char    base_url[128];
    pid_t   server_pid;
    int     initialized;
    float   temperature;  /* 请求体采样温度 (实验7: --temp 可调, 默认 0.1) */
};

// ---------------- 内存缓冲 (用于 libcurl 写回调) ----------------

struct membuf {
    char*  data;
    size_t len;
    size_t cap;
};

static size_t write_cb(void* ptr, size_t size, size_t nmemb, void* userdata) {
    struct membuf* mb = (struct membuf*)userdata;
    size_t add = size * nmemb;

    if (mb->len + add + 1 > mb->cap) {
        size_t newcap = mb->cap * 2 + add + 1;
        char* nd = realloc(mb->data, newcap);
        if (!nd) return 0; // 触发 curl 报错
        mb->data = nd;
        mb->cap  = newcap;
    }
    memcpy(mb->data + mb->len, ptr, add);
    mb->len += add;
    mb->data[mb->len] = '\0';
    return add;
}

static int curl_global_ready = 0;

static void ensure_curl_global(void) {
    if (!curl_global_ready) {
        curl_global_init(CURL_GLOBAL_DEFAULT);
        curl_global_ready = 1;
    }
}

// ---------------- base64 ----------------

static const char b64_table[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static char* base64_encode(const unsigned char* data, size_t len) {
    size_t out_len = 4 * ((len + 2) / 3);
    char* out = malloc(out_len + 1);
    if (!out) return NULL;

    size_t i = 0, j = 0;
    while (i < len) {
        uint32_t a = i < len ? data[i++] : 0;
        uint32_t b = i < len ? data[i++] : 0;
        uint32_t c = i < len ? data[i++] : 0;
        uint32_t triple = (a << 16) | (b << 8) | c;

        out[j++] = b64_table[(triple >> 18) & 0x3F];
        out[j++] = b64_table[(triple >> 12) & 0x3F];
        out[j++] = b64_table[(triple >> 6)  & 0x3F];
        out[j++] = b64_table[triple & 0x3F];
    }

    size_t mod = len % 3;
    if (mod == 1) { out[out_len - 1] = '='; out[out_len - 2] = '='; }
    else if (mod == 2) { out[out_len - 1] = '='; }

    out[out_len] = '\0';
    return out;
}

// ---------------- JSON 转义 / 简易提取 ----------------
// 只做我们自己拼装/解析所需的最小 JSON 处理，不引入第三方 JSON 库依赖。

static char* json_escape(const char* in) {
    if (!in) in = "";
    size_t len = strlen(in);
    char* out = malloc(len * 2 + 1);
    if (!out) return NULL;

    size_t j = 0;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)in[i];
        switch (c) {
            case '"':  out[j++] = '\\'; out[j++] = '"';  break;
            case '\\': out[j++] = '\\'; out[j++] = '\\'; break;
            case '\n': out[j++] = '\\'; out[j++] = 'n';  break;
            case '\r': out[j++] = '\\'; out[j++] = 'r';  break;
            case '\t': out[j++] = '\\'; out[j++] = 't';  break;
            default:
                if (c < 0x20) {
                    // 其余控制字符直接丢弃，避免生成非法 JSON
                } else {
                    out[j++] = (char)c;
                }
        }
    }
    out[j] = '\0';
    return out;
}

// 从 /v1/chat/completions 的响应体里取出 choices[0].message.content
// OpenAI 兼容格式有两种常见写法: "content":"text" 或 "content": "text"
// 这里先找到 "content" 键，然后跳过冒号和可选空格，定位到值的开头引号。
static char* extract_json_content(const char* json) {
    if (!json) return NULL;

    const char* p = strstr(json, "\"content\"");
    if (!p) return NULL;
    p += 9; // 跳过 "content"

    // 跳过 ": 或 ": " 部分
    while (*p && (*p == ':' || *p == ' ' || *p == '\t')) p++;
    if (*p != '"') return NULL;
    p++; // 跳过值的开头引号

    size_t cap = 256, len = 0;
    char* out = malloc(cap);
    if (!out) return NULL;

    while (*p && *p != '"') {
        char decoded;
        if (*p == '\\' && *(p + 1)) {
            p++;
            switch (*p) {
                case 'n':  decoded = '\n'; break;
                case 'r':  decoded = '\r'; break;
                case 't':  decoded = '\t'; break;
                case '"':  decoded = '"';  break;
                case '\\': decoded = '\\'; break;
                case '/':  decoded = '/';  break;
                default:   decoded = *p;   break;
            }
            p++;
        } else {
            decoded = *p++;
        }

        if (len + 1 >= cap) {
            cap *= 2;
            char* nd = realloc(out, cap);
            if (!nd) { free(out); return NULL; }
            out = nd;
        }
        out[len++] = decoded;
    }
    out[len] = '\0';

    // 首尾空白裁剪
    while (len > 0 && isspace((unsigned char)out[len - 1])) out[--len] = '\0';
    char* start = out;
    while (*start && isspace((unsigned char)*start)) start++;
    if (start != out) memmove(out, start, strlen(start) + 1);

    if (out[0] == '\0') { free(out); return NULL; }
    return out;
}

// ---------------- server 生命周期 ----------------

static int wait_for_server_ready(const char* base_url, int timeout_sec) {
    CURL* curl = curl_easy_init();
    if (!curl) return -1;

    char url[256];
    snprintf(url, sizeof(url), "%s/health", base_url);

    time_t start = time(NULL);
    int ok = 0;

    while (time(NULL) - start < timeout_sec) {
        struct membuf mb = { malloc(1), 0, 1 };
        if (!mb.data) break;
        mb.data[0] = '\0';

        curl_easy_setopt(curl, CURLOPT_URL, url);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &mb);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 2L);

        CURLcode res = curl_easy_perform(curl);
        long code = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code);
        free(mb.data);

        if (res == CURLE_OK && code == 200) { ok = 1; break; }
        usleep(300000);
    }

    curl_easy_cleanup(curl);
    return ok ? 0 : -1;
}

llama_handle_t llama_init(const char* model_path, const char* mmproj_path, float temperature) {
    ensure_curl_global();

    struct llama_handle* h = calloc(1, sizeof(struct llama_handle));
    if (!h) return NULL;

    if (temperature < 0.0f || temperature > 2.0f) {
        fprintf(stderr, "[llama] 温度参数非法: %.2f (允许 0.0~2.0)\n", temperature);
        free(h);
        return NULL;
    }
    h->temperature = temperature;

    strncpy(h->model_path,  model_path,  sizeof(h->model_path) - 1);
    strncpy(h->mmproj_path, mmproj_path, sizeof(h->mmproj_path) - 1);

    // 快速验证文件存在，尽早给出清晰报错
    FILE* f = fopen(model_path, "rb");
    if (!f) {
        fprintf(stderr, "[llama] 模型文件不存在: %s\n", model_path);
        free(h);
        return NULL;
    }
    fclose(f);

    f = fopen(mmproj_path, "rb");
    if (!f) {
        fprintf(stderr, "[llama] mmproj 文件不存在: %s\n", mmproj_path);
        free(h);
        return NULL;
    }
    fclose(f);

    if (access(SERVER_BIN, X_OK) != 0) {
        fprintf(stderr,
            "[llama] 找不到可执行文件: %s\n"
            "        请确认 llama.cpp 编译时启用了 server target (llama-server)\n",
            SERVER_BIN);
        free(h);
        return NULL;
    }

    snprintf(h->base_url, sizeof(h->base_url), "http://%s:%d", SERVER_HOST, SERVER_PORT);

    // Moondream2 需要 --chat-template vicuna，SmolVLM 系列不需要，
    // 这里按模型/投影文件名自动判断，避免每次手动传参。
    int need_vicuna =
        strstr(model_path, "oondream") != NULL ||
        strstr(mmproj_path, "oondream") != NULL;

    char port_str[16];
    snprintf(port_str, sizeof(port_str), "%d", SERVER_PORT);

    pid_t pid = fork();
    if (pid < 0) {
        fprintf(stderr, "[llama] fork 失败: %s\n", strerror(errno));
        free(h);
        return NULL;
    }

    if (pid == 0) {
        // 子进程: 启动常驻 server，模型只在这里加载一次
        setenv("LD_LIBRARY_PATH", LIB_PATH, 1);

        int devnull = open("/dev/null", O_WRONLY);
        if (devnull >= 0) {
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
        }

        if (need_vicuna) {
            execl(SERVER_BIN, SERVER_BIN,
                  "-m", model_path, "--mmproj", mmproj_path,
                  "--host", SERVER_HOST, "--port", port_str,
                  "-ngl", "0",
                  "--chat-template", "vicuna",
                  (char*)NULL);
        } else {
            execl(SERVER_BIN, SERVER_BIN,
                  "-m", model_path, "--mmproj", mmproj_path,
                  "--host", SERVER_HOST, "--port", port_str,
                  "-ngl", "0",
                  (char*)NULL);
        }
        // execl 只有失败才会返回
        _exit(127);
    }

    h->server_pid = pid;

    printf("[llama] 正在启动常驻 server (pid=%d)，等待模型加载...\n", pid);

    if (wait_for_server_ready(h->base_url, HEALTH_TIMEOUT_SEC) != 0) {
        fprintf(stderr, "[llama] server 启动超时 (%ds)，可能是模型过大或路径错误\n", HEALTH_TIMEOUT_SEC);
        kill(pid, SIGTERM);
        waitpid(pid, NULL, 0);
        free(h);
        return NULL;
    }

    h->initialized = 1;
    printf("[llama] 常驻 server 已就绪: %s (port=%d)\n", model_path, SERVER_PORT);
    return (llama_handle_t)h;
}

char* llama_infer(llama_handle_t handle,
                   const char* image_path,
                   const char* system_prompt,
                   const char* user_prompt) {
    struct llama_handle* h = (struct llama_handle*)handle;
    if (!h || !h->initialized) return NULL;

    // 读取图像并 base64 编码
    FILE* imgf = fopen(image_path, "rb");
    if (!imgf) {
        fprintf(stderr, "[llama] 无法打开图像: %s\n", image_path);
        return NULL;
    }
    fseek(imgf, 0, SEEK_END);
    long img_size = ftell(imgf);
    fseek(imgf, 0, SEEK_SET);
    if (img_size <= 0) {
        fclose(imgf);
        return NULL;
    }
    unsigned char* img_data = malloc((size_t)img_size);
    if (!img_data) { fclose(imgf); return NULL; }
    if (fread(img_data, 1, (size_t)img_size, imgf) != (size_t)img_size) {
        free(img_data);
        fclose(imgf);
        return NULL;
    }
    fclose(imgf);

    char* b64 = base64_encode(img_data, (size_t)img_size);
    free(img_data);
    if (!b64) return NULL;

    char* sys_esc = json_escape(system_prompt);
    char* usr_esc = json_escape(user_prompt);
    if (!sys_esc || !usr_esc) {
        free(b64); free(sys_esc); free(usr_esc);
        return NULL;
    }

    size_t body_cap = strlen(b64) + strlen(sys_esc) + strlen(usr_esc) + 512;
    char* body = malloc(body_cap);
    if (!body) {
        free(b64); free(sys_esc); free(usr_esc);
        return NULL;
    }

    // OpenAI 兼容格式: image_url 用 data URI 内嵌 base64
    // temperature 由 llama_init 传入 (默认 0.1, 实验7 通过 --temp 扫描)
    snprintf(body, body_cap,
        "{"
          "\"messages\":["
            "{\"role\":\"system\",\"content\":\"%s\"},"
            "{\"role\":\"user\",\"content\":["
              "{\"type\":\"text\",\"text\":\"%s\"},"
              "{\"type\":\"image_url\",\"image_url\":{\"url\":\"data:image/jpeg;base64,%s\"}}"
            "]}"
          "],"
          "\"temperature\":%.2f,"
          "\"max_tokens\":16"
        "}",
        sys_esc, usr_esc, b64, h->temperature);

    free(b64);
    free(sys_esc);
    free(usr_esc);

    char url[256];
    snprintf(url, sizeof(url), "%s/v1/chat/completions", h->base_url);

    CURL* curl = curl_easy_init();
    if (!curl) { free(body); return NULL; }

    struct membuf mb = { malloc(1), 0, 1 };
    if (!mb.data) { curl_easy_cleanup(curl); free(body); return NULL; }
    mb.data[0] = '\0';

    struct curl_slist* headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &mb);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, (long)INFER_TIMEOUT_SEC);

    CURLcode res = curl_easy_perform(curl);
    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    free(body);

    if (res != CURLE_OK || http_code != 200) {
        fprintf(stderr, "[llama] 推理请求失败: %s (HTTP %ld)\n",
                curl_easy_strerror(res), http_code);
        free(mb.data);
        return NULL;
    }

    char* content = extract_json_content(mb.data);
    free(mb.data);
    return content; // malloc 分配，调用者负责 free()
}

void llama_free(llama_handle_t handle) {
    struct llama_handle* h = (struct llama_handle*)handle;
    if (!h) return;

    if (h->server_pid > 0) {
        kill(h->server_pid, SIGTERM);

        int status;
        int exited = 0;
        for (int i = 0; i < 30; i++) { // 最多等待约 3s
            pid_t r = waitpid(h->server_pid, &status, WNOHANG);
            if (r == h->server_pid) { exited = 1; break; }
            usleep(100000);
        }
        if (!exited) {
            kill(h->server_pid, SIGKILL);
            waitpid(h->server_pid, NULL, 0);
        }
    }

    free(h);
    printf("[llama] 资源已释放 (server 已停止)\n");
}

const char* llama_version(void) {
    static char version[64] = {0};
    if (version[0] == '\0') {
        char cmd[256];
        snprintf(cmd, sizeof(cmd),
            "export LD_LIBRARY_PATH=%s; %s --version 2>&1",
            LIB_PATH, SERVER_BIN);
        FILE* p = popen(cmd, "r"); // 一次性诊断用途，非热路径，保留 popen 无妨
        if (p) {
            if (fgets(version, sizeof(version), p)) {
                size_t len = strlen(version);
                while (len > 0 && (version[len - 1] == '\n' || version[len - 1] == '\r'))
                    version[--len] = '\0';
            }
            pclose(p);
        }
        if (version[0] == '\0') strcpy(version, "unknown");
    }
    return version;
}
