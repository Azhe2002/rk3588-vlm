#include "result_parser.h"
#include <stdio.h>

/* 单元测试: 验证 parse_yes_no_lenient 语义判定 */
int main(void) {
    struct {
        const char* input;
        int expected;   /* 1=YES 0=NO -1=无法识别 */
        const char* desc;
    } cases[] = {
        /* --- 严格模式也应识别的短答案 --- */
        {"Yes.",                           1, "严格-短答案 yes"},
        {"no",                             0, "严格-短答案 no"},
        {"YES",                            1, "严格-大写 yes"},
        {"No.",                            0, "严格-大写 no"},

        /* --- 640x480 实测出现的完整句子 --- */
        {"There is a black industrial fan in the center of the image.", 1, "v2实测-256M完整句"},
        {"A black industrial fan is in the foreground of the image.",   1, "v2实测-500M完整句"},
        {"A black industrial fan is on a table in a factory warehouse.",1, "v2实测-500M桌上"},
        {"A black industrial fan is located in a factory warehouse.",   1, "v2实测-500M位于"},
        {"A black industrial fan sits on a table in a factory warehouse.",1, "v2实测-500M坐着"},
        {"A black industrial fan is on a table in the foreground of the image.", 1, "v2实测-500M前景桌上"},
        {"A black fan is in the foreground of the image.",               1, "v2实测-500M黑色风扇"},
        {"A black fan in a factory warehouse.",                          1, "v2实测-500M省略is"},

        /* --- 否定完整句 --- */
        {"There is no black industrial fan in the image.", 0, "否定-没有风扇"},
        {"There is not a fan in the image.",               0, "否定-无风扇"},
        {"The fan is not present in the image.",           0, "否定-不出现"},
        {"No fan is visible.",                             0, "否定-不可见"},
        {"A black fan is missing from the image.",         0, "否定-a开头缺失"},

        /* --- 边界: 无法识别 --- */
        {"Maybe it could be somewhere else.", -1, "模糊-无法判定"},
        {"The image is very dark.",           -1, "模糊-无关描述"},
        {"",                                  -1, "空字符串"},
    };

    int n = (int)(sizeof(cases) / sizeof(cases[0]));
    int pass = 0, fail = 0;
    for (int i = 0; i < n; i++) {
        int got = parse_yes_no_lenient(cases[i].input);
        int ok = (got == cases[i].expected);
        printf("[%s] %-28s expect=%d got=%d\n",
               ok ? "PASS" : "FAIL", cases[i].desc, cases[i].expected, got);
        if (ok) pass++; else fail++;
    }

    printf("\n===== %d/%d PASS =====\n", pass, n);
    return fail == 0 ? 0 : 1;
}
