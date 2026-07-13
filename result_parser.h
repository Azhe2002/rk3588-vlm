#ifndef RESULT_PARSER_H
#define RESULT_PARSER_H

// 清洗 llama 原始输出，按完整英文单词提取 yes/no 判定。
// raw : llama_infer 返回的原始字符串
// 返回值:
//    1  → yes (忽略大小写、标点、前后空格)
//    0  → no
//   -1  → 无法识别或同一行同时包含 yes/no
int parse_yes_no(const char* raw);

#endif // RESULT_PARSER_H
