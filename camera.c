#include "camera.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define CAMERA_FPS 5
#define FIRST_FRAME_TIMEOUT_SEC 8
#define SAVE_FRAME_TIMEOUT_SEC 8
#define MAX_JPEG_BYTES (64U * 1024U * 1024U)

static pthread_t g_thread;
static bool g_thread_started = false;
static atomic_bool g_running = ATOMIC_VAR_INIT(false);
static char g_device[256];
static char g_fx_extra[512];  /* 附加 GStreamer 元素 (实验2/3 变体图), 默认空 */
static int g_width = 1920;
static int g_height = 1080;
static pthread_mutex_t g_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_cond = PTHREAD_COND_INITIALIZER;
static bool g_frame_ready = false;
static pid_t g_capture_pid = -1;
static unsigned char* g_latest_frame = NULL;
static size_t g_latest_frame_length = 0;
static size_t g_latest_frame_capacity = 0;

static int add_seconds(struct timespec* ts, time_t seconds) {
    if (clock_gettime(CLOCK_REALTIME, ts) != 0) {
        return -1;
    }
    ts->tv_sec += seconds;
    return 0;
}

static int write_all(int fd, const unsigned char* data, size_t length) {
    size_t written = 0;
    while (written < length) {
        ssize_t n = write(fd, data + written, length - written);
        if (n > 0) {
            written += (size_t)n;
        } else if (n < 0 && errno == EINTR) {
            continue;
        } else {
            return -1;
        }
    }
    return 0;
}

static int publish_frame(const unsigned char* data, size_t length) {
    pthread_mutex_lock(&g_mutex);
    if (length > g_latest_frame_capacity) {
        unsigned char* resized = realloc(g_latest_frame, length);
        if (!resized) {
            pthread_mutex_unlock(&g_mutex);
            fprintf(stderr, "[camera] 保存最新帧到内存失败\n");
            return -1;
        }
        g_latest_frame = resized;
        g_latest_frame_capacity = length;
    }
    memcpy(g_latest_frame, data, length);
    g_latest_frame_length = length;
    g_frame_ready = true;
    pthread_cond_broadcast(&g_cond);
    pthread_mutex_unlock(&g_mutex);
    return 0;
}

static pid_t start_gstreamer(int* read_fd) {
    int pipefd[2];
    if (pipe(pipefd) != 0) {
        fprintf(stderr, "[camera] 创建采集管道失败: %s\n", strerror(errno));
        return -1;
    }

    pid_t pid = fork();
    if (pid < 0) {
        fprintf(stderr, "[camera] 启动 GStreamer 失败: %s\n", strerror(errno));
        close(pipefd[0]);
        close(pipefd[1]);
        return -1;
    }

    if (pid == 0) {
        char device_arg[sizeof(g_device) + 16];
        char pipeline[768];
        (void)snprintf(device_arg, sizeof(device_arg), "device=%s", g_device);

        // 整条管道拼成单个字符串传给 gst-launch-1.0。
        // g_fx_extra 插入 jpegenc 之前 (元素串内勿含空格; 需要带空格/引号的
        // caps 请用单引号包裹，如 videoscale ! video/x-raw,width=320,height=240)。
        int n = snprintf(pipeline, sizeof(pipeline),
            "v4l2src %s ! video/x-raw,format=NV12,width=%d,height=%d"
            " ! videorate drop-only=true ! video/x-raw,framerate=%d/1"
            "%s%s"
            " ! jpegenc ! fdsink fd=1 sync=false",
            device_arg, g_width, g_height, CAMERA_FPS,
            g_fx_extra[0] ? " ! " : "", g_fx_extra);

        if (n < 0 || (size_t)n >= sizeof(pipeline)) {
            static const char message[] = "[camera] GStreamer 管道串过长\n";
            (void)write(STDERR_FILENO, message, sizeof(message) - 1U);
            _exit(128);
        }

        close(pipefd[0]);
        if (dup2(pipefd[1], STDOUT_FILENO) < 0) {
            _exit(126);
        }
        close(pipefd[1]);

        execlp("gst-launch-1.0", "gst-launch-1.0", "-q", pipeline, (char*)NULL);

        static const char message[] = "[camera] 无法执行 gst-launch-1.0\n";
        (void)write(STDERR_FILENO, message, sizeof(message) - 1U);
        _exit(127);
    }

    close(pipefd[1]);
    *read_fd = pipefd[0];
    return pid;
}

static void* capture_thread(void* arg) {
    (void)arg;

    int read_fd = -1;
    pid_t pid = start_gstreamer(&read_fd);
    if (pid < 0) {
        atomic_store(&g_running, false);
        pthread_mutex_lock(&g_mutex);
        pthread_cond_broadcast(&g_cond);
        pthread_mutex_unlock(&g_mutex);
        return NULL;
    }

    pthread_mutex_lock(&g_mutex);
    g_capture_pid = pid;
    pthread_mutex_unlock(&g_mutex);

    size_t capacity = 256U * 1024U;
    size_t length = 0;
    unsigned char* frame = malloc(capacity);
    bool in_frame = false;
    unsigned char previous = 0;

    if (!frame) {
        fprintf(stderr, "[camera] 无法分配帧缓冲区\n");
        atomic_store(&g_running, false);
        (void)kill(pid, SIGKILL);
    }

    unsigned char chunk[64U * 1024U];
    while (frame && atomic_load(&g_running)) {
        ssize_t n = read(read_fd, chunk, sizeof(chunk));
        if (n == 0) {
            break;
        }
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            fprintf(stderr, "[camera] 读取采集流失败: %s\n", strerror(errno));
            break;
        }

        for (ssize_t i = 0; i < n; ++i) {
            unsigned char current = chunk[i];

            if (!in_frame) {
                if (previous == 0xffU && current == 0xd8U) {
                    frame[0] = 0xffU;
                    frame[1] = 0xd8U;
                    length = 2;
                    in_frame = true;
                }
                previous = current;
                continue;
            }

            if (length == capacity) {
                if (capacity >= MAX_JPEG_BYTES) {
                    fprintf(stderr, "[camera] JPEG 帧超过 %u MiB，已丢弃\n",
                            (unsigned)(MAX_JPEG_BYTES / (1024U * 1024U)));
                    length = 0;
                    in_frame = false;
                    previous = current;
                    continue;
                }
                size_t new_capacity = capacity * 2U;
                if (new_capacity > MAX_JPEG_BYTES) {
                    new_capacity = MAX_JPEG_BYTES;
                }
                unsigned char* resized = realloc(frame, new_capacity);
                if (!resized) {
                    fprintf(stderr, "[camera] 扩展帧缓冲区失败\n");
                    atomic_store(&g_running, false);
                    break;
                }
                frame = resized;
                capacity = new_capacity;
            }

            frame[length++] = current;
            if (previous == 0xffU && current == 0xd9U) {
                (void)publish_frame(frame, length);
                length = 0;
                in_frame = false;
            }
            previous = current;
        }
    }

    free(frame);
    close(read_fd);

    bool stopped_unexpectedly = atomic_exchange(&g_running, false);

    int status = 0;
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
    }

    pthread_mutex_lock(&g_mutex);
    g_capture_pid = -1;
    pthread_cond_broadcast(&g_cond);
    pthread_mutex_unlock(&g_mutex);

    if (WIFEXITED(status) && WEXITSTATUS(status) != 0) {
        fprintf(stderr, "[camera] GStreamer 异常退出，状态码: %d\n", WEXITSTATUS(status));
    } else if (WIFSIGNALED(status) && stopped_unexpectedly) {
        fprintf(stderr, "[camera] GStreamer 被信号 %d 终止\n", WTERMSIG(status));
    }
    return NULL;
}

static int write_frame_to_path(const unsigned char* data, size_t length,
                               const char* path) {
    char temp_path[PATH_MAX];
    int n = snprintf(temp_path, sizeof(temp_path), "%s.tmp.XXXXXX", path);
    if (n < 0 || (size_t)n >= sizeof(temp_path)) {
        errno = ENAMETOOLONG;
        return -1;
    }

    int destination_fd = mkstemp(temp_path);
    if (destination_fd < 0) {
        return -1;
    }
    if (fchmod(destination_fd, 0600) != 0) {
        int saved_errno = errno;
        close(destination_fd);
        unlink(temp_path);
        errno = saved_errno;
        return -1;
    }

    int result = 0;
    if (write_all(destination_fd, data, length) != 0) {
        result = -1;
    }

    if (result == 0 && fsync(destination_fd) != 0) {
        result = -1;
    }
    if (close(destination_fd) != 0 && result == 0) {
        result = -1;
    }

    if (result == 0 && rename(temp_path, path) != 0) {
        result = -1;
    }
    if (result != 0) {
        int saved_errno = errno;
        unlink(temp_path);
        errno = saved_errno;
    }
    return result;
}

int camera_start(const char* device, int width, int height, const char* gst_extra) {
    if (!device || device[0] == '\0' || width <= 0 || height <= 0) {
        fprintf(stderr, "[camera] 无效的设备或分辨率参数\n");
        return -1;
    }
    if (strlen(device) >= sizeof(g_device)) {
        fprintf(stderr, "[camera] 设备路径过长\n");
        return -1;
    }
    if (gst_extra && strlen(gst_extra) >= sizeof(g_fx_extra)) {
        fprintf(stderr, "[camera] --gst-extra 过长\n");
        return -1;
    }

    pthread_mutex_lock(&g_mutex);
    if (g_thread_started) {
        pthread_mutex_unlock(&g_mutex);
        return 0;
    }

    (void)snprintf(g_device, sizeof(g_device), "%s", device);
    if (gst_extra) (void)snprintf(g_fx_extra, sizeof(g_fx_extra), "%s", gst_extra);
    else g_fx_extra[0] = '\0';
    g_width = width;
    g_height = height;
    g_frame_ready = false;
    g_latest_frame_length = 0;
    g_capture_pid = -1;

    atomic_store(&g_running, true);
    int create_result = pthread_create(&g_thread, NULL, capture_thread, NULL);
    if (create_result != 0) {
        atomic_store(&g_running, false);
        pthread_mutex_unlock(&g_mutex);
        fprintf(stderr, "[camera] 采集线程创建失败: %s\n", strerror(create_result));
        return -1;
    }
    g_thread_started = true;

    struct timespec deadline;
    if (add_seconds(&deadline, FIRST_FRAME_TIMEOUT_SEC) != 0) {
        pthread_mutex_unlock(&g_mutex);
        camera_stop();
        return -1;
    }

    int wait_result = 0;
    while (!g_frame_ready && atomic_load(&g_running) && wait_result == 0) {
        wait_result = pthread_cond_timedwait(&g_cond, &g_mutex, &deadline);
    }
    bool ready = g_frame_ready;
    pthread_mutex_unlock(&g_mutex);

    if (!ready) {
        if (wait_result == ETIMEDOUT) {
            fprintf(stderr, "[camera] 等待第一帧超时（%d 秒）\n", FIRST_FRAME_TIMEOUT_SEC);
        } else {
            fprintf(stderr, "[camera] 采集管道未能提供首帧\n");
        }
        camera_stop();
        return -1;
    }

    printf("[camera] 采集线程已启动 (%s, %dx%d, %dfps)\n",
           device, width, height, CAMERA_FPS);
    return 0;
}

int camera_save_frame(const char* path) {
    if (!path || path[0] == '\0') {
        return -1;
    }

    struct timespec deadline;
    if (add_seconds(&deadline, SAVE_FRAME_TIMEOUT_SEC) != 0) {
        return -1;
    }

    pthread_mutex_lock(&g_mutex);
    int wait_result = 0;
    while (!g_frame_ready && atomic_load(&g_running) && wait_result == 0) {
        wait_result = pthread_cond_timedwait(&g_cond, &g_mutex, &deadline);
    }

    if (!g_frame_ready) {
        pthread_mutex_unlock(&g_mutex);
        if (wait_result == ETIMEDOUT) {
            fprintf(stderr, "[camera] 等待新帧超时（%d 秒）\n", SAVE_FRAME_TIMEOUT_SEC);
        }
        return -1;
    }

    size_t frame_length = g_latest_frame_length;
    unsigned char* frame_copy = malloc(frame_length);
    if (frame_copy) {
        memcpy(frame_copy, g_latest_frame, frame_length);
        g_frame_ready = false;
    }
    pthread_mutex_unlock(&g_mutex);

    if (!frame_copy) {
        fprintf(stderr, "[camera] 复制最新帧失败\n");
        return -1;
    }

    int result = write_frame_to_path(frame_copy, frame_length, path);
    int saved_errno = errno;
    free(frame_copy);
    errno = saved_errno;

    if (result != 0) {
        fprintf(stderr, "[camera] 保存帧到 %s 失败: %s\n", path, strerror(errno));
        return -1;
    }
    return 0;
}

void camera_stop(void) {
    pthread_mutex_lock(&g_mutex);
    if (!g_thread_started) {
        pthread_mutex_unlock(&g_mutex);
        return;
    }

    atomic_store(&g_running, false);
    pid_t pid = g_capture_pid;
    pthread_cond_broadcast(&g_cond);
    pthread_mutex_unlock(&g_mutex);

    if (pid > 0) {
        (void)kill(pid, SIGTERM);
        for (int i = 0; i < 10; ++i) {
            struct timespec pause = { .tv_sec = 0, .tv_nsec = 100000000L };
            while (nanosleep(&pause, &pause) != 0 && errno == EINTR) {
            }

            pthread_mutex_lock(&g_mutex);
            bool child_finished = g_capture_pid != pid;
            pthread_mutex_unlock(&g_mutex);
            if (child_finished) {
                break;
            }
            if (i == 9) {
                (void)kill(pid, SIGKILL);
            }
        }
    }
    (void)pthread_join(g_thread, NULL);

    pthread_mutex_lock(&g_mutex);
    g_thread_started = false;
    g_frame_ready = false;
    g_capture_pid = -1;
    free(g_latest_frame);
    g_latest_frame = NULL;
    g_latest_frame_length = 0;
    g_latest_frame_capacity = 0;
    pthread_mutex_unlock(&g_mutex);
    printf("[camera] 采集线程已停止\n");
}
