#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "camera.h"
#include "llama_server.h"
#include "result_parser.h"

// ============================================================
// 默认值
// ============================================================
#define DEFAULT_CAMERA   "/dev/video22"
#define DEFAULT_WIDTH    320
#define DEFAULT_HEIGHT   240
#define DEFAULT_MODEL    "/userdata/llama/models/SmolVLM-500M-Instruct-Q8_0.gguf"
#define DEFAULT_MMPROJ   "/userdata/llama/models/mmproj-SmolVLM-500M-Instruct-Q8_0.gguf"
#define DEFAULT_OBJECT   "industrial items"
#define DEFAULT_SCENE    "factory warehouse, dim lighting"
#define DEFAULT_QUESTION "is there any object in the center of picture?"
#define DEFAULT_INTERVAL 15
#define MAX_WIDTH        3840
#define MAX_HEIGHT       2160
#define MAX_INTERVAL     86400
#define FRAME_PATH       "/dev/shm/frame.jpg"

// ============================================================
// 全局控制
// ============================================================
static volatile sig_atomic_t g_keep_running = 1;

static void signal_handler(int sig) {
    (void)sig;
    g_keep_running = 0;
}

static int install_signal_handlers(void) {
    struct sigaction act;
    memset(&act, 0, sizeof(act));
    act.sa_handler = signal_handler;
    sigemptyset(&act.sa_mask);
    if (sigaction(SIGINT, &act, NULL) != 0
            || sigaction(SIGTERM, &act, NULL) != 0) {
        fprintf(stderr, "[main] 安装信号处理器失败: %s\n", strerror(errno));
        return -1;
    }
    return 0;
}

// ============================================================
// 工具函数
// ============================================================

static bool copy_option(char* dst, size_t dst_size,
                        const char* value, const char* name) {
    size_t len = strlen(value);
    if (len >= dst_size) {
        fprintf(stderr, "参数 %s 过长（最多 %zu 字节）\n", name, dst_size - 1);
        return false;
    }
    memcpy(dst, value, len + 1);
    return true;
}

static bool parse_int(const char* text, int min, int max,
                      int* out, const char* name) {
    if (!text || text[0] == '\0') {
        fprintf(stderr, "参数 %s 缺少数值\n", name);
        return false;
    }
    errno = 0;
    char* end = NULL;
    long val = strtol(text, &end, 10);
    if (errno == ERANGE || end == text || *end != '\0'
            || val < min || val > max) {
        fprintf(stderr, "参数 %s 必须是 %d~%d 的整数: %s\n", name, min, max, text);
        return false;
    }
    *out = (int)val;
    return true;
}

static int64_t monotonic_ms(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return -1;
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static void sleep_ms(int64_t ms) {
    if (ms <= 0 || !g_keep_running) return;
    struct timespec rem = {
        .tv_sec  = (time_t)(ms / 1000),
        .tv_nsec = (long)((ms % 1000) * 1000000)
    };
    while (g_keep_running && nanosleep(&rem, &rem) != 0) {
        if (errno != EINTR) break;
    }
}

// ============================================================
// 参数
// ============================================================
typedef struct {
    char camera[256];
    char model[512];
    char mmproj[512];
    char object[256];
    char scene[256];
    char question[256];
    int  width;
    int  height;
    int  interval;
} config_t;

static void print_usage(const char* prog) {
    printf("Usage: %s [OPTIONS]\n", prog);
    printf("Options:\n");
    printf("  --camera   PATH   相机设备 (默认: %s)\n", DEFAULT_CAMERA);
    printf("  --model    PATH   模型文件 (默认: %s)\n", DEFAULT_MODEL);
    printf("  --mmproj   PATH   mmproj (默认: %s)\n", DEFAULT_MMPROJ);
    printf("  --object   STR    检测目标 (默认: %s)\n", DEFAULT_OBJECT);
    printf("  --scene    STR    场景描述 (默认: %s)\n", DEFAULT_SCENE);
    printf("  --question STR    检测问题 (默认: %s)\n", DEFAULT_QUESTION);
    printf("  --width    N      采集宽度 (默认: %d, 最大: %d)\n", DEFAULT_WIDTH, MAX_WIDTH);
    printf("  --height   N      采集高度 (默认: %d, 最大: %d)\n", DEFAULT_HEIGHT, MAX_HEIGHT);
    printf("  --interval N      推理间隔秒数 (默认: %d, 最大: %d)\n", DEFAULT_INTERVAL, MAX_INTERVAL);
    printf("  --help            显示帮助\n");
}

static int parse_args(int argc, char** argv, config_t* cfg) {
    memset(cfg, 0, sizeof(*cfg));
    copy_option(cfg->camera,   sizeof(cfg->camera),   DEFAULT_CAMERA,   "--camera");
    copy_option(cfg->model,    sizeof(cfg->model),    DEFAULT_MODEL,    "--model");
    copy_option(cfg->mmproj,   sizeof(cfg->mmproj),   DEFAULT_MMPROJ,   "--mmproj");
    copy_option(cfg->object,   sizeof(cfg->object),   DEFAULT_OBJECT,   "--object");
    copy_option(cfg->scene,    sizeof(cfg->scene),    DEFAULT_SCENE,    "--scene");
    copy_option(cfg->question, sizeof(cfg->question), DEFAULT_QUESTION, "--question");
    cfg->width    = DEFAULT_WIDTH;
    cfg->height   = DEFAULT_HEIGHT;
    cfg->interval = DEFAULT_INTERVAL;

    for (int i = 1; i < argc; i++) {
        const char* opt = argv[i];
        if (strcmp(opt, "--help") == 0 || strcmp(opt, "-h") == 0) {
            print_usage(argv[0]);
            return 1;
        }
        if (i + 1 >= argc) {
            fprintf(stderr, "参数 %s 缺少值\n", opt);
            return -1;
        }
        const char* val = argv[++i];
        bool ok = true;

        if      (strcmp(opt, "--camera")   == 0) ok = copy_option(cfg->camera,   sizeof(cfg->camera),   val, opt);
        else if (strcmp(opt, "--model")    == 0) ok = copy_option(cfg->model,    sizeof(cfg->model),    val, opt);
        else if (strcmp(opt, "--mmproj")   == 0) ok = copy_option(cfg->mmproj,   sizeof(cfg->mmproj),   val, opt);
        else if (strcmp(opt, "--object")   == 0) ok = copy_option(cfg->object,   sizeof(cfg->object),   val, opt);
        else if (strcmp(opt, "--scene")    == 0) ok = copy_option(cfg->scene,    sizeof(cfg->scene),    val, opt);
        else if (strcmp(opt, "--question") == 0) ok = copy_option(cfg->question, sizeof(cfg->question), val, opt);
        else if (strcmp(opt, "--width")    == 0) ok = parse_int(val, 1, MAX_WIDTH,  &cfg->width,    opt);
        else if (strcmp(opt, "--height")   == 0) ok = parse_int(val, 1, MAX_HEIGHT, &cfg->height,   opt);
        else if (strcmp(opt, "--interval") == 0) ok = parse_int(val, 1, MAX_INTERVAL,   &cfg->interval, opt);
        else {
            fprintf(stderr, "未知参数: %s\n", opt);
            print_usage(argv[0]);
            return -1;
        }
        if (!ok) return -1;
    }
    return 0;
}

// ============================================================
// Main
// ============================================================
int main(int argc, char** argv) {
    config_t cfg;
    int pr = parse_args(argc, argv, &cfg);
    if (pr != 0) return pr > 0 ? 0 : 1;
    if (install_signal_handlers() != 0) return 1;

    // 拼接系统提示词
    char system_prompt[1024];
    int slen = snprintf(system_prompt, sizeof(system_prompt),
        "You are an expert in recognition, processing, and analysis. "
        "Please carefully analyze the image and answer the question accurately. "
        "Please respond with only 'yes' or 'no'. "
        "Detection target: %s. Scene: %s.",
        cfg.object, cfg.scene);
    if (slen < 0 || (size_t)slen >= sizeof(system_prompt)) {
        fprintf(stderr, "[main] 系统提示词过长\n");
        return 1;
    }

    // banner
    printf("=========================================\n");
    printf("  RK3588 VLM 工业检测\n");
    printf("=========================================\n");
    printf("  相机:   %s\n", cfg.camera);
    printf("  模型:   %s\n", cfg.model);
    printf("  mmproj: %s\n", cfg.mmproj);
    printf("  物体:   %s\n", cfg.object);
    printf("  场景:   %s\n", cfg.scene);
    printf("  问题:   %s\n", cfg.question);
    printf("  分辨率: %dx%d\n", cfg.width, cfg.height);
    printf("  间隔:   %ds\n", cfg.interval);
    printf("=========================================\n\n");
    printf("[main] 系统提示词:\n  %s\n\n", system_prompt);
    printf("[main] 用户提示词:\n  %s\n\n", cfg.question);

    // 1. 启动常驻 llama-server (模型只加载一次)
    printf("[main] 启动推理服务...\n");
    llama_handle_t llama = llama_init(cfg.model, cfg.mmproj);
    if (!llama) {
        fprintf(stderr, "[main] 推理服务启动失败，退出\n");
        return 1;
    }

    // 2. 启动持久相机管道
    printf("[main] 启动相机...\n");
    if (camera_start(cfg.camera, cfg.width, cfg.height) != 0) {
        fprintf(stderr, "[main] 相机启动失败，退出\n");
        llama_free(llama);
        return 1;
    }

    printf("\n[main] 进入推理循环 (间隔 %ds)，Ctrl+C 退出\n\n", cfg.interval);

    // 3. 主循环
    unsigned long count = 0;
    int64_t program_start = monotonic_ms();

    while (g_keep_running) {
        count++;
        int64_t loop_start = monotonic_ms();
        printf("─── [%04lu] ─────────────────────────────\n", count);

        // 取帧 (持久管道已在后台持续采集，这里只取内存中最新帧并写盘)
        if (camera_save_frame(FRAME_PATH) != 0) {
            fprintf(stderr, "  📷 取帧失败，正在重启采集管道\n");
            camera_stop();
            if (g_keep_running
                    && camera_start(cfg.camera, cfg.width, cfg.height) == 0) {
                printf("  📷 采集管道已恢复\n");
            } else if (g_keep_running) {
                fprintf(stderr, "  📷 重启失败，下轮重试\n");
            }
            sleep_ms((int64_t)cfg.interval * 1000);
            continue;
        }
        printf("  📷 帧已保存: %s\n", FRAME_PATH);

        // HTTP 推理 (模型已在 server 中常驻)
        printf("  🤖 推理中...\n");
        fflush(stdout);
        char* raw = llama_infer(llama, FRAME_PATH, system_prompt, cfg.question);

        if (!raw) {
            fprintf(stderr, "  ❌ 推理失败\n");
        } else {
            printf("  📝 原始输出: \"%s\"\n", raw);
            int result = parse_yes_no(raw);
            if (result == 1)      printf("  ✅ 结果: YES (1)\n");
            else if (result == 0) printf("  ⚠️  结果: NO  (0)\n");
            else                  printf("  ❓ 结果: 无法识别 (-1)\n");
            free(raw);
        }

        // 计算剩余等待 (单调时钟)
        int64_t now = monotonic_ms();
        int64_t elapsed = (loop_start >= 0 && now >= loop_start) ? now - loop_start : 0;
        int64_t interval_ms = (int64_t)cfg.interval * 1000;
        int64_t remaining = interval_ms - elapsed;
        if (remaining < 0) {
            printf("  ⚡ 本轮耗时 %.2fs，超出间隔 %ds\n", (double)elapsed / 1000.0, cfg.interval);
            remaining = 0;
        }
        printf("  ⏱  耗时: %.2fs | 总计: #%lu\n\n", (double)elapsed / 1000.0, count);
        sleep_ms(remaining);
    }

    // 清理
    int64_t program_end = monotonic_ms();
    double total_s = (program_start >= 0 && program_end >= program_start)
                     ? (double)(program_end - program_start) / 1000.0 : 0.0;
    printf("\n[main] 收到终止信号，正在清理...\n");
    printf("[main] 停止: 共运行 %.2fs, 推理 %lu 次\n", total_s, count);

    llama_free(llama);
    camera_stop();
    unlink(FRAME_PATH);
    return 0;
}
