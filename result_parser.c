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
