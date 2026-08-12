#ifndef CAMERA_H
#define CAMERA_H

#include <stdint.h>

// 启动 5fps 独立采集线程和持久 GStreamer 管道。
// device: 相机设备路径，如 "/dev/video22"
// width, height: 采集分辨率
// gst_extra: 附加 GStreamer 元素串，插入 jpegenc 之前（实验2/3 变体图，
//            如 "gaussianblur sigma=15"、"videoscale ! video/x-raw,width=320,height=240"）；
//            空串表示不加
// 返回: 0 成功, -1 失败（失败时内部资源会被完整回收）
int camera_start(const char* device, int width, int height, const char* gst_extra);

// 从采集线程取最新一帧，以原子替换方式保存为 JPEG 文件。
// path: 保存路径，如 "/tmp/frame.jpg"
// 返回: 0 成功, -1 失败（参数无效、采集停止或等待新帧超时）
int camera_save_frame(const char* path);

// 停止采集线程；可重复调用。
void camera_stop(void);

#endif // CAMERA_H
