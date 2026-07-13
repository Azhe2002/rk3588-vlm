cmake_minimum_required(VERSION 3.16)
project(rk3588-vlm C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# ============================================================
# 源文件
# ============================================================
set(SOURCES
    main.c
    camera.c
    llama_server.c
    result_parser.c
)

# ============================================================
# 可执行文件
# ============================================================
add_executable(rk3588-vlm ${SOURCES})

# pthread (相机采集线程)
find_package(Threads REQUIRED)
target_link_libraries(rk3588-vlm PRIVATE Threads::Threads)

# libcurl (HTTP 请求常驻 llama-server)
find_package(CURL REQUIRED)
target_link_libraries(rk3588-vlm PRIVATE CURL::libcurl)

# ============================================================
# 编译选项
# ============================================================
target_compile_options(rk3588-vlm PRIVATE -Wall -Wextra -O2)

# _DEFAULT_SOURCE: POSIX 扩展 (usleep/setenv/strdup 等)
# _GNU_SOURCE:     strtok_r 原型
target_compile_definitions(rk3588-vlm PRIVATE _DEFAULT_SOURCE _GNU_SOURCE)

# ============================================================
# 安装
# ============================================================
install(TARGETS rk3588-vlm DESTINATION /userdata/llama/bin)
