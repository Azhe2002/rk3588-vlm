#include "result_parser.h"

#include <ctype.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

static char* trim(char* text) {
    while (isspace((unsigned char)*text)) {
        ++text;
    }
    if (*text == '\0') {
        return text;
    }

    char* end = text + strlen(text);
    while (end > text && isspace((unsigned char)end[-1])) {
        --end;
    }
    *end = '\0';
    return text;
}

static void strip_wrapping_punctuation(char* text) {
    char* start = text;
    while (*start != '\0' && !isalnum((unsigned char)*start)) {
        ++start;
    }
    if (start != text) {
        memmove(text, start, strlen(start) + 1U);
    }

    size_t length = strlen(text);
    while (length > 0 && !isalnum((unsigned char)text[length - 1U])) {
        text[--length] = '\0';
    }
}

static bool token_equals(const char* start, size_t length, const char* expected) {
    size_t expected_length = strlen(expected);
    if (length != expected_length) {
        return false;
    }
    for (size_t i = 0; i < length; ++i) {
        if (tolower((unsigned char)start[i]) != (unsigned char)expected[i]) {
            return false;
        }
    }
    return true;
}

/* 返回 1/0 表示该行只包含一种明确答案，-1 表示没有答案或存在冲突。 */
static int parse_line(const char* line) {
    bool found_yes = false;
    bool found_no = false;
    const char* cursor = line;

    while (*cursor != '\0') {
        while (*cursor != '\0' && !isalpha((unsigned char)*cursor)) {
            ++cursor;
        }
        const char* start = cursor;
        while (isalpha((unsigned char)*cursor)) {
            ++cursor;
        }
        size_t length = (size_t)(cursor - start);
        if (token_equals(start, length, "yes")) {
            found_yes = true;
        } else if (token_equals(start, length, "no")) {
            found_no = true;
        }
    }

    if (found_yes == found_no) {
        return -1;
    }
    return found_yes ? 1 : 0;
}

int parse_yes_no(const char* raw) {
    if (!raw || raw[0] == '\0') {
        return -1;
    }

    char* buffer = strdup(raw);
    if (!buffer) {
        return -1;
    }

    /* 优先采用最后一条明确的非冲突输出，适配 CLI 前置日志。 */
    int result = -1;
    char* save_pointer = NULL;
    for (char* line = strtok_r(buffer, "\r\n", &save_pointer);
         line != NULL;
         line = strtok_r(NULL, "\r\n", &save_pointer)) {
        char* cleaned = trim(line);
        strip_wrapping_punctuation(cleaned);
        cleaned = trim(cleaned);
        if (cleaned[0] == '\0') {
            continue;
        }

        int line_result = parse_line(cleaned);
        if (line_result != -1) {
            result = line_result;
        }
    }

    free(buffer);
    return result;
}

/* ============================================================
 * 宽泛判定: parse_yes_no_lenient
 * 先尝试严格解析; 若 -1, 按语义关键词判断完整句子。
 * 语义策略: 在整句(小写)中搜索肯定/否定关键词组,
 *           仅命中一方 → 明确判定; 双方都命中或无命中 → -1。
 * ============================================================ */
int parse_yes_no_lenient(const char* raw) {
    if (!raw || raw[0] == '\0') {
        return -1;
    }

    int strict_result = parse_yes_no(raw);
    if (strict_result != -1) {
        return strict_result;
    }

    char* buffer = strdup(raw);
    if (!buffer) {
        return -1;
    }
    for (char* p = buffer; *p != '\0'; ++p) {
        *p = (char)tolower((unsigned char)*p);
    }

    /* 否定关键词组 (完整句子中出现即视为 NO 倾向) */
    static const char* const negatives[] = {
        "there is no", "there are no", "there is not", "there are not",
        "no black", "not present", "not visible", "doesn't", "don't",
        "isn't", "aren't", "without", "absent", "no fan", "no object",
        "missing", "not there", "gone", "cannot be seen", "can't be seen",
        "not found",
    };
    /* 肯定关键词组 (完整句子中出现即视为 YES 倾向) */
    static const char* const positives[] = {
        "there is a", "there is an", "there are", "is in", "is on",
        "is located", "is present", "is visible", "shows a", "shows an",
        "shows the", "contains", "has a", "has an", "appears", "you can see",
        "can be seen", "found", "sits on", "sitting on", "is sitting",
    };

    bool negative_hit = false;
    for (size_t i = 0; i < sizeof(negatives) / sizeof(negatives[0]); ++i) {
        if (strstr(buffer, negatives[i]) != NULL) {
            negative_hit = true;
            break;
        }
    }

    bool positive_hit = false;
    for (size_t i = 0; i < sizeof(positives) / sizeof(positives[0]); ++i) {
        if (strstr(buffer, positives[i]) != NULL) {
            positive_hit = true;
            break;
        }
    }

    /* 启发式: 无否定词 + 以 "a/an" 开头的存在性描述句 (省略动词),
     * 如 "A black fan in a factory warehouse." → YES 倾向
     * 注意: 不含 "the" 开头 (如 "The image is very dark." 是场景描述, 不应判 YES) */
    if (!negative_hit && !positive_hit) {
        if (strncmp(buffer, "a ", 2) == 0
                || strncmp(buffer, "an ", 3) == 0) {
            positive_hit = true;
        }
    }

    free(buffer);

    if (negative_hit && !positive_hit) {
        return 0;
    }
    if (positive_hit && !negative_hit) {
        return 1;
    }
    return -1;
}
