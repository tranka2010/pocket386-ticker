#ifndef SCREEN_H
#define SCREEN_H

#include <string.h>
#include <stdio.h>

#define SCREEN_COLS 80
#define SCREEN_ROWS 25
#define MAKE_ATTR(bg, fg) ((unsigned char)(((bg) << 4) | ((fg) & 0x0F)))

#define BLACK        0
#define BLUE         1
#define GREEN        2
#define CYAN         3
#define RED          4
#define MAGENTA      5
#define BROWN        6
#define LIGHTGRAY    7
#define DARKGRAY     8
#define LIGHTBLUE    9
#define LIGHTGREEN   10
#define LIGHTCYAN    11
#define LIGHTRED     12
#define LIGHTMAGENTA 13
#define YELLOW       14
#define WHITE        15

#if defined(POCKET386_LINUX) || defined(__linux__)
#define BOX_TL '+'
#define BOX_TR '+'
#define BOX_BL '+'
#define BOX_BR '+'
#define BOX_HL '-'
#define BOX_VL '|'

static void linux_set_attr(unsigned char attr)
{
    static const int ansi[8] = {30, 34, 32, 36, 31, 35, 33, 37};
    int fg, bg;
    fg = attr & 0x0F;
    bg = (attr >> 4) & 0x0F;
    printf("\033[0;%s%d;%dm", (fg >= 8) ? "1;" : "", ansi[fg & 7], ansi[bg & 7] + 10);
}

static void poke_char(int x, int y, unsigned char ch, unsigned char attr)
{
    if (x < 0 || x >= SCREEN_COLS || y < 0 || y >= SCREEN_ROWS) return;
    printf("\033[%d;%dH", y + 1, x + 1);
    linux_set_attr(attr);
    putchar(ch);
    fflush(stdout);
}

static void print_str(int x, int y, const char *str, unsigned char attr)
{
    if (!str || y < 0 || y >= SCREEN_ROWS || x >= SCREEN_COLS) return;
    printf("\033[%d;%dH", y + 1, (x < 0 ? 1 : x + 1));
    linux_set_attr(attr);
    while (*str && x < SCREEN_COLS) {
        if (x >= 0) putchar(*str);
        ++x;
        ++str;
    }
    fflush(stdout);
}

static void clear_screen(unsigned char attr)
{
    printf("\033[2J\033[H");
    linux_set_attr(attr);
    fflush(stdout);
}

static void gotoxy(int x, int y)
{
    if (x < 1) x = 1;
    if (y < 1) y = 1;
    printf("\033[%d;%dH", y, x);
}
#else
#include <dos.h>
#define VRAM_SEG 0xB800
#define BOX_TL 218
#define BOX_TR 191
#define BOX_BL 192
#define BOX_BR 217
#define BOX_HL 196
#define BOX_VL 179

static void poke_char(int x, int y, unsigned char ch, unsigned char attr)
{
    unsigned int offset;
    if (x < 0 || x >= SCREEN_COLS || y < 0 || y >= SCREEN_ROWS) return;
    offset = (unsigned int)((y * SCREEN_COLS + x) * 2);
    pokeb(VRAM_SEG, offset, (char)ch);
    pokeb(VRAM_SEG, offset + 1, attr);
}

static void print_str(int x, int y, const char *str, unsigned char attr)
{
    if (!str || y < 0 || y >= SCREEN_ROWS || x >= SCREEN_COLS) return;
    while (*str && x < SCREEN_COLS) {
        if (x >= 0) poke_char(x, y, (unsigned char)*str, attr);
        ++x;
        ++str;
    }
}

static void clear_screen(unsigned char attr)
{
    int x, y;
    for (y = 0; y < SCREEN_ROWS; ++y)
        for (x = 0; x < SCREEN_COLS; ++x)
            poke_char(x, y, ' ', attr);
}
#endif

static void draw_box(int left, int top, int right, int bottom,
                     const char *title, unsigned char border_attr,
                     unsigned char title_attr)
{
    int x, y, len;
    if (left < 0 || top < 0 || right >= SCREEN_COLS || bottom >= SCREEN_ROWS ||
        left >= right || top >= bottom) return;
    for (x = left + 1; x < right; ++x) {
        poke_char(x, top, BOX_HL, border_attr);
        poke_char(x, bottom, BOX_HL, border_attr);
    }
    for (y = top + 1; y < bottom; ++y) {
        poke_char(left, y, BOX_VL, border_attr);
        poke_char(right, y, BOX_VL, border_attr);
    }
    poke_char(left, top, BOX_TL, border_attr);
    poke_char(right, top, BOX_TR, border_attr);
    poke_char(left, bottom, BOX_BL, border_attr);
    poke_char(right, bottom, BOX_BR, border_attr);
    if (title && *title) {
        len = strlen(title);
        if (left + 2 < right) {
            poke_char(left + 1, top, ' ', border_attr);
            print_str(left + 2, top, title, title_attr);
            if (left + 2 + len <= right) poke_char(left + 2 + len, top, ' ', border_attr);
        }
    }
}

#endif
