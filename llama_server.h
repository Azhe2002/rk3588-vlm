#ifndef LLAMA_SERVER_H
#define LLAMA_SERVER_H

#ifdef __cplusplus
extern "C" {
#endif

// 不透明句柄
typedef void* llama_handle_t;

// 初始化 + 启动常驻 server（程序启动时调用一次，耗时 ~2-10s）
// model_path : .gguf 模型文件路径
// mmproj_path: mmproj 文件路径
// temperature: 采样温度 (0.0-2.0, 实验7 温度扫描用; 原固定值 0.1)
// 返回: 句柄 (NULL 表示失败)
llama_handle_t llama_init(const char* model_path, const char* mmproj_path, float temperature);

// 推理：图像 + 系统提示词 + 用户提示词 → 原始输出 (HTTP 请求)
// handle      : llama_init 返回的句柄
// image_path   : 图像文件路径 (JPEG/PNG)
// system_prompt: 系统提示词 (角色定位 + 检测目标 + 场景)
// user_prompt  : 用户提示词 (具体问题)
// 返回: malloc 的 C 字符串，调用者负责 free()，失败返回 NULL
char* llama_infer(llama_handle_t handle,
                  const char* image_path,
                  const char* system_prompt,
                  const char* user_prompt);

// 释放模型资源 (优雅关闭 server 子进程)
void llama_free(llama_handle_t handle);

// 获取版本字符串 (不需要初始化)
const char* llama_version(void);

#ifdef __cplusplus
}
#endif

#endif // LLAMA_SERVER_H
