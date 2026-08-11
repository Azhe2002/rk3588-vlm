#ifndef RESULT_PARSER_H
#define RESULT_PARSER_H

// 清洗 llama 原始输出，按完整英文单词提取 yes/no 判定。
// raw : llama_infer 返回的原始字符串
// 返回值:
//    1  → yes (忽略大小写、标点、前后空格)
//    0  → no
//   -1  → 无法识别或同一行同时包含 yes/no
int parse_yes_no(const char* raw);

// 宽泛判定：先尝试严格解析，失败后按语义关键词分析。
// 适用场景: 高分辨率(640x480)下模型输出完整句子
//           (如 "There is a black industrial fan in the center of the image.")
// 返回值: 1=yes, 0=no, -1=无法识别
int parse_yes_no_lenient(const char* raw);

#endif // RESULT_PARSER_H
