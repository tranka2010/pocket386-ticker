#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dos.h>
#include <conio.h>
#include <io.h>
#include <fcntl.h>
#include "screen.h"

#define COM1_BASE 0x3F8
#define BIOS_TICKS_PER_DAY 0x1800B0UL

/* Edit these settings for direct TCP via the mTCP NC.EXE utility. */
#define TCP_HOST_IP       "TCP_HOST_IP"
#define TCP_HOST_PORT     8765

/* Edit these four settings before building the ESP-AT transport. */
#define ESP_WIFI_SSID     "ESP_WIFI_SSID"
#define ESP_WIFI_PASSWORD "ESP_WIFI_PASSWORD"
#define ESP_HOST_IP       "ESP_HOST_IP"
#define ESP_HOST_PORT     8765

#define TRANSPORT_SERIAL 0
#define TRANSPORT_ESP_AT 1
#define TRANSPORT_TCP    2

static int g_transport = TRANSPORT_SERIAL;
static int g_esp_transparent_active = 0;

static unsigned long get_dos_ticks(void)
{
    unsigned long far *clock_ptr = (unsigned long far *)0x0040006CL;
    return *clock_ptr;
}

static unsigned long elapsed_ticks(unsigned long start, unsigned long now)
{
    if (now >= start) return now - start;
    /* BIOS tick counter resets at midnight. */
    return (BIOS_TICKS_PER_DAY - start) + now;
}

static int init_serial(unsigned int baud)
{
    unsigned int divisor;
    if (baud == 0 || baud > 115200U || (115200UL % baud) != 0) return 0;
    divisor = (unsigned int)(115200UL / baud);
    if (divisor == 0) return 0;
    outportb(COM1_BASE + 1, 0x00);
    outportb(COM1_BASE + 3, 0x80);
    outportb(COM1_BASE + 0, divisor & 0xFF);
    outportb(COM1_BASE + 1, (divisor >> 8) & 0xFF);
    outportb(COM1_BASE + 3, 0x03); /* 8 data bits, no parity, 1 stop bit */
    outportb(COM1_BASE + 2, 0xC7); /* Enable/clear FIFO */
    outportb(COM1_BASE + 4, 0x0B); /* DTR, RTS, OUT2 */
    return 1;
}

static int send_serial_char(char c)
{
    unsigned long start;
    start = get_dos_ticks();
    while ((inportb(COM1_BASE + 5) & 0x20) == 0) {
        if (elapsed_ticks(start, get_dos_ticks()) >= 36UL) return 0;
    }
    outportb(COM1_BASE, (unsigned char)c);
    return 1;
}

static int send_serial_str(const char *str)
{
    while (*str) {
        if (!send_serial_char(*str++)) return 0;
    }
    return 1;
}

/* Returns 1 for a complete line, 0 for timeout, -1 for an overlong line. */
static int serial_read_line(char *buffer, int max_len, unsigned int timeout_sec)
{
    int idx, overflow;
    unsigned long start_ticks, max_ticks;
    idx = 0;
    overflow = 0;
    if (!buffer || max_len < 2) return 0;
    start_ticks = get_dos_ticks();
    max_ticks = (unsigned long)timeout_sec * 18UL;
    for (;;) {
        unsigned char ch;
        if (elapsed_ticks(start_ticks, get_dos_ticks()) >= max_ticks) {
            buffer[idx] = '\0';
            return 0;
        }
        if ((inportb(COM1_BASE + 5) & 0x01) == 0) continue;
        ch = (unsigned char)inportb(COM1_BASE);
        if (ch == '\n') break;
        if (ch == '\r') continue;
        if (idx < max_len - 1) buffer[idx++] = (char)ch;
        else overflow = 1; /* Drain through newline to preserve record alignment. */
    }
    buffer[idx] = '\0';
    return overflow ? -1 : 1;
}

static void clear_serial_rx(void)
{
    while (inportb(COM1_BASE + 5) & 0x01) (void)inportb(COM1_BASE);
}

static int wait_for_at_ok(unsigned int timeout_sec)
{
    char line[128];
    unsigned long start;
    int rc;
    start = get_dos_ticks();
    while (elapsed_ticks(start, get_dos_ticks()) < (unsigned long)timeout_sec * 18UL) {
        rc = serial_read_line(line, sizeof(line), 1);
        if (rc <= 0) continue;
        if (strcmp(line, "OK") == 0) return 1;
        if (strstr(line, "ERROR") != NULL || strstr(line, "FAIL") != NULL) return 0;
    }
    return 0;
}

static int try_at_baud(unsigned int baud)
{
    if (!init_serial(baud)) return 0;
    delay(150);
    clear_serial_rx();
    if (!send_serial_str("AT\r\n")) return 0;
    if (!wait_for_at_ok(3)) return 0;
    return 1;
}

static int send_at_command(const char *command, unsigned int timeout_sec)
{
    if (!send_serial_str(command) || !send_serial_str("\r\n")) return 0;
    return wait_for_at_ok(timeout_sec);
}

/* AT+CIPSEND returns a '>' prompt without requiring a newline. */
static int wait_for_at_prompt(unsigned int timeout_sec)
{
    char line[96];
    int idx;
    unsigned long start;
    idx = 0;
    line[0] = '\0';
    start = get_dos_ticks();
    while (elapsed_ticks(start, get_dos_ticks()) < (unsigned long)timeout_sec * 18UL) {
        unsigned char ch;
        if ((inportb(COM1_BASE + 5) & 0x01) == 0) continue;
        ch = (unsigned char)inportb(COM1_BASE);
        if (ch == '>') return 1;
        if (ch == '\r') continue;
        if (ch == '\n') {
            line[idx] = '\0';
            if (strstr(line, "ERROR") != NULL || strstr(line, "FAIL") != NULL) return 0;
            idx = 0;
            line[0] = '\0';
        } else if (idx < (int)sizeof(line) - 1) {
            line[idx++] = (char)ch;
        }
    }
    return 0;
}

static int initialize_esp_at_transport(void)
{
    char command[160];
    print_str(1, 23, "[ESP-AT] Detecting UART speed...", MAKE_ATTR(BLACK, YELLOW));
    if (!try_at_baud(115200U) && !try_at_baud(9600U)) {
        print_str(1, 23, "[ESP-AT] No AT response at 115200/9600", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }

    print_str(1, 23, "[ESP-AT] Configuring Wi-Fi...", MAKE_ATTR(BLACK, YELLOW));
    if (!send_at_command("ATE0", 4)) {
        print_str(1, 23, "[ESP-AT] ATE0 failed", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    if (!send_at_command("AT+CWMODE=1", 5)) {
        print_str(1, 23, "[ESP-AT] CWMODE failed", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    sprintf(command, "AT+CWJAP=\"%s\",\"%s\"", ESP_WIFI_SSID, ESP_WIFI_PASSWORD);
    if (!send_at_command(command, 60)) {
        print_str(1, 23, "[ESP-AT] Wi-Fi join failed; check SSID/password", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    if (!send_at_command("AT+CIPMUX=0", 5)) {
        print_str(1, 23, "[ESP-AT] CIPMUX failed", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }

    print_str(1, 23, "[ESP-AT] Connecting to Linux host...", MAKE_ATTR(BLACK, YELLOW));
    sprintf(command, "AT+CIPSTART=\"TCP\",\"%s\",%u", ESP_HOST_IP, ESP_HOST_PORT);
    if (!send_at_command(command, 30)) {
        print_str(1, 23, "[ESP-AT] TCP connect failed; check host/IP/firewall", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    if (!send_at_command("AT+CIPMODE=1", 5)) {
        print_str(1, 23, "[ESP-AT] Transparent mode failed", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    if (!send_serial_str("AT+CIPSEND\r\n") || !wait_for_at_prompt(8)) {
        print_str(1, 23, "[ESP-AT] CIPSEND prompt failed", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    /* The prompt is not dashboard data; clear any trailing prompt whitespace. */
    delay(100);
    clear_serial_rx();
    g_esp_transparent_active = 1;
    return 1;
}

static void close_esp_at_transport(void)
{
    if (!g_esp_transparent_active) return;
    /* ESP-AT requires a one-second guard period around the +++ escape. */
    delay(1100);
    (void)send_serial_str("+++");
    delay(1100);
    clear_serial_rx();
    (void)send_at_command("AT+CIPMODE=0", 5);
    (void)send_at_command("AT+CIPCLOSE", 5);
    g_esp_transparent_active = 0;
}

static void draw_dashboard_layout(void)
{
    unsigned char border, header;
    border = MAKE_ATTR(BLACK, CYAN);
    header = MAKE_ATTR(BLACK, YELLOW);
    clear_screen(MAKE_ATTR(BLACK, LIGHTGRAY));
    if (g_transport == TRANSPORT_ESP_AT)
        print_str(2, 0, "POCKET386 DASHBOARD [WIFI]", MAKE_ATTR(BLUE, WHITE));
    else if (g_transport == TRANSPORT_TCP)
        print_str(2, 0, "POCKET386 DASHBOARD [TCP]", MAKE_ATTR(BLUE, WHITE));
    else
        print_str(2, 0, "POCKET386 DASHBOARD [SERIAL]", MAKE_ATTR(BLUE, WHITE));
    draw_box(0,  1, 39, 8,  "1. WEATHER (Waltham, MA)", border, header);
    draw_box(40, 1, 79, 8,  "2. STOCKS & INDEXES", border, header);
    draw_box(0,  8, 39, 22, "3. HEADLINES (NPR / RSS)", border, header);
    draw_box(40, 8, 79, 22, "4. TODAY'S SPORTS SCORES", border, header);
    print_str(1, 23, "[F5] Force Refresh   [Q] Quit to DOS", MAKE_ATTR(BLACK, WHITE));
}

static void parse_field(const char *line, int field_idx, char *out, int max_len)
{
    int cur_field, i, o;
    cur_field = 0;
    i = 0;
    o = 0;
    if (!out || max_len < 1) return;
    out[0] = '\0';
    if (!line || field_idx < 0) return;
    while (line[i] && cur_field <= field_idx) {
        if (line[i] == '|') {
            cur_field++;
            i++;
            continue;
        }
        if (cur_field == field_idx && o < max_len - 1) out[o++] = line[i];
        i++;
    }
    out[o] = '\0';
}

static void clear_region(int left, int top, int right, int bottom, unsigned char attr)
{
    int x, y;
    char blank[81];
    int width;
    if (left < 0 || right >= SCREEN_COLS || left > right) return;
    width = right - left + 1;
    for (x = 0; x < width; ++x) blank[x] = ' ';
    blank[width] = '\0';
    for (y = top; y <= bottom; ++y) print_str(left, y, blank, attr);
}

static void print_two_line_headline(int start_y, int num, const char *text)
{
    char line1[36], line2[36], buf[40];
    int len, split_idx, tail_start;
    unsigned char num_attr, text_attr;
    len = strlen(text);
    num_attr = MAKE_ATTR(BLACK, YELLOW);
    text_attr = MAKE_ATTR(BLACK, LIGHTGRAY);
    if (len == 0 || start_y < 0 || start_y > 21) return;
    if (len <= 34) {
        sprintf(buf, "%d.%s", num, text);
        print_str(2, start_y, buf, text_attr);
        poke_char(2, start_y, (char)('0' + num), num_attr);
    } else {
        split_idx = 33;
        while (split_idx > 10 && text[split_idx] != ' ') split_idx--;
        if (split_idx <= 10) split_idx = 33;
        strncpy(line1, text, split_idx);
        line1[split_idx] = '\0';
        tail_start = split_idx + ((text[split_idx] == ' ') ? 1 : 0);
        strncpy(line2, text + tail_start, 34);
        line2[34] = '\0';
        sprintf(buf, "%d.%s", num, line1);
        print_str(2, start_y, buf, text_attr);
        poke_char(2, start_y, (char)('0' + num), num_attr);
        sprintf(buf, "  %s", line2);
        if (start_y + 1 <= 21) print_str(2, start_y + 1, buf, text_attr);
    }
}

static void parse_and_render_line(char *line)
{
    char field[128], f2[64], f3[64], f4[64], f5[64], f6[64];
    unsigned char text_attr, green_attr, red_attr;
    text_attr = MAKE_ATTR(BLACK, LIGHTGRAY);
    green_attr = MAKE_ATTR(BLACK, LIGHTGREEN);
    red_attr = MAKE_ATTR(BLACK, LIGHTRED);

    if (strncmp(line, "#DASHBOARD", 10) == 0) {
        parse_field(line, 1, field, sizeof(field));
        parse_field(line, 2, f2, sizeof(f2));
        clear_region(31, 0, 78, 0, MAKE_ATTR(BLACK, LIGHTGRAY));
        print_str(31, 0, field, MAKE_ATTR(BLACK, LIGHTCYAN));
        print_str(56, 0, f2, MAKE_ATTR(BLACK, YELLOW));
        return;
    }
    if (strncmp(line, "@WX", 3) == 0) {
        clear_region(1, 2, 38, 7, text_attr);
        parse_field(line, 1, field, sizeof(field));
        parse_field(line, 2, f2, sizeof(f2));
        parse_field(line, 3, f3, sizeof(f3));
        parse_field(line, 4, f4, sizeof(f4));
        f3[15] = '\0';
		f4[15] = '\0';
        print_str(2, 3, field, text_attr);
        print_str(2, 4, f2, MAKE_ATTR(BLACK, YELLOW));
        sprintf(f5, "%s  %s", f3, f4);
        print_str(2, 5, f5, text_attr);
    } else if (strncmp(line, "@ST", 3) == 0) {
        int i, row;
        clear_region(41, 2, 78, 7, text_attr);
        row = 3;
        for (i = 1; i <= 7 && row <= 7; i += 3) {
            char buf[36];
            parse_field(line, i, field, sizeof(field));
            parse_field(line, i + 1, f2, sizeof(f2));
            parse_field(line, i + 2, f3, sizeof(f3));
            if (field[0]) {
                field[7] = '\0'; f2[8] = '\0'; f3[8] = '\0';
                sprintf(buf, "%-7s %8s", field, f2);
                print_str(42, row, buf, text_attr);
                print_str(60, row, f3, (f3[0] == '-') ? red_attr : green_attr);
                row++;
            }
        }
    } else if (strncmp(line, "@HL", 3) == 0) {
        int i, y;
        clear_region(1, 9, 38, 21, text_attr);
        y = 10;
        for (i = 1; i <= 6 && y <= 21; ++i) {
            parse_field(line, i, field, sizeof(field));
            if (field[0]) {
                field[70] = '\0';
                print_two_line_headline(y, i, field);
                y += 2;
            }
        }
    } else if (strncmp(line, "@SP", 3) == 0) {
        int i, row;
        clear_region(41, 9, 78, 21, text_attr);
        row = 10;
        for (i = 1; i <= 60 && row <= 21; i += 6) {
            char buf[40];
            parse_field(line, i, field, sizeof(field));
            parse_field(line, i + 1, f2, sizeof(f2));
            parse_field(line, i + 2, f3, sizeof(f3));
            parse_field(line, i + 3, f4, sizeof(f4));
            parse_field(line, i + 4, f5, sizeof(f5));
            parse_field(line, i + 5, f6, sizeof(f6));
            if (field[0]) {
                field[3] = '\0'; f2[4] = '\0'; f3[4] = '\0';
                f4[4] = '\0'; f5[4] = '\0'; f6[9] = '\0';
                sprintf(buf, "%-3s %-4s %4s %-4s %4s", field, f2, f3, f4, f5);
                print_str(42, row, buf, text_attr);
                print_str(42, row + 1, f6, MAKE_ATTR(BLACK, LIGHTCYAN));
                row += 2;
            }
        }
    }
}

static int fetch_tcp_data(void)
{
    char command[200];
    char line_buf[512];
    FILE *fp;
    int got_end, system_rc;

    print_str(1, 23, "[TCP/mTCP updating...]              ", MAKE_ATTR(BLACK, YELLOW));

    /* mTCP's NC utility owns the TCP socket. Redirect its payload to a file so
       Borland C 3.0 does not need to link against a different mTCP toolchain. */
    fp = fopen("DASHGET.TXT", "wt");
    if (!fp) {
        print_str(1, 23, "[Cannot create DASHGET.TXT]          ", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    fputs("GET\n", fp);
    fclose(fp);
    remove("DASHRSP.TXT");

    /* -w allows the response to arrive after stdin reaches EOF. Avoid 2> NUL:
       some DOS command interpreters do not support stderr redirection and NC
       can then misread the 2 as an unknown option. */
    sprintf(command,"C:\\MTCP\\NC -target %s %u -w 3 < DASHGET.TXT > DASHRSP.TXT",
            TCP_HOST_IP, TCP_HOST_PORT);
    /* Replace system(command) with this */
    {
        int saved_stderr;
        int nul_handle;

        fflush(stderr);
        saved_stderr = dup(2);
        nul_handle = open("NUL", O_WRONLY);

        if (saved_stderr != -1 && nul_handle != -1) {
            dup2(nul_handle, 2);
            close(nul_handle);

            system_rc = system(command);

            fflush(stderr);
            dup2(saved_stderr, 2);
            close(saved_stderr);
        } else {
            if (nul_handle != -1)
                close(nul_handle);
            if (saved_stderr != -1)
                close(saved_stderr);

            system_rc = system(command);
        }
    }
    (void)system_rc; /* NC's exit code varies by mTCP release; @END is decisive. */
    fp = fopen("DASHRSP.TXT", "rt");
    if (!fp) {
        print_str(1, 23, "[TCP failed: no response file]       ", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    got_end = 0;
    while (fgets(line_buf, sizeof(line_buf), fp) != NULL) {
        size_t len;
        len = strlen(line_buf);
        while (len > 0 && (line_buf[len - 1] == '\r' || line_buf[len - 1] == '\n'))
            line_buf[--len] = '\0';
        if (strncmp(line_buf, "@END", 4) == 0) { got_end = 1; break; }
        if (line_buf[0]) parse_and_render_line(line_buf);
    }
    fclose(fp);
    if (!got_end) {
        print_str(1, 23, "[TCP incomplete; check server/NC]    ", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    print_str(1, 23, "[Online TCP/mTCP] [F5] Refresh [Q] Quit", MAKE_ATTR(BLACK, WHITE));
    return 1;
}

static int fetch_data_from_proxy(void)
{
    char line_buf[512];
    unsigned long start;
    int got_end, status;

    if (g_transport == TRANSPORT_TCP) return fetch_tcp_data();

    print_str(1, 23, "[Updating...]                        ", MAKE_ATTR(BLACK, YELLOW));
    if (!send_serial_str("GET\n")) {
        print_str(1, 23, "[Serial TX timeout] Press F5 to retry", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    start = get_dos_ticks();
    got_end = 0;
    while (elapsed_ticks(start, get_dos_ticks()) < 1800UL) { /* 100 seconds overall */
        status = serial_read_line(line_buf, sizeof(line_buf), 10);
        if (status == 0) {
            print_str(1, 23, "[Serial timeout] Press F5 to retry", MAKE_ATTR(BLACK, LIGHTRED));
            return 0;
        }
        if (status < 0) {
            print_str(1, 23, "[Oversized serial record skipped]     ", MAKE_ATTR(BLACK, LIGHTRED));
            continue;
        }
        if (strncmp(line_buf, "@END", 4) == 0) { got_end = 1; break; }
        parse_and_render_line(line_buf);
    }
    if (!got_end) {
        print_str(1, 23, "[Incomplete response] Press F5 to retry", MAKE_ATTR(BLACK, LIGHTRED));
        return 0;
    }
    print_str(1, 23, "[Online] [F5] Refresh [Q] Quit", MAKE_ATTR(BLACK, WHITE));
    return 1;
}

int main(int argc, char *argv[])
{
    unsigned long last_ticks, current_ticks;
    unsigned long refresh_interval_ticks;
    int i;

    refresh_interval_ticks = 546UL; /* Approximately 30 seconds at 18.2 Hz. */
    g_transport = TRANSPORT_SERIAL; /* Backward-compatible default. */
    for (i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "/ESP") == 0 || strcmp(argv[i], "/esp") == 0 || strcmp(argv[i], "-ESP") == 0 || strcmp(argv[i], "-esp") == 0)
            g_transport = TRANSPORT_ESP_AT;
        else if (strcmp(argv[i], "/SERIAL") == 0 || strcmp(argv[i], "/serial") == 0 || strcmp(argv[i], "-SERIAL") == 0 || strcmp(argv[i], "-serial") == 0)
            g_transport = TRANSPORT_SERIAL;
        else if (strcmp(argv[i], "/TCP") == 0 || strcmp(argv[i], "/tcp") == 0 || strcmp(argv[i], "-TCP") == 0 || strcmp(argv[i], "-tcp") == 0)
            g_transport = TRANSPORT_TCP;
        else {
            printf("Usage: DASHBRD [/SERIAL|/ESP|/TCP|/serial|/esp|/tcp]\n");
            return 1;
        }
    }

    if (g_transport == TRANSPORT_SERIAL && !init_serial(9600)) {
        printf("Invalid serial baud rate.\n");
        return 1;
    }
    draw_dashboard_layout();
    if (g_transport == TRANSPORT_ESP_AT && !initialize_esp_at_transport()) {
        print_str(1, 24, "Check ESP-AT firmware, Wi-Fi settings, and host IP in source.",
                  MAKE_ATTR(BLACK, LIGHTRED));
        return 1;
    }

    fetch_data_from_proxy();
    last_ticks = get_dos_ticks();
    while (1) {
        if (kbhit()) {
            char key;
            key = getch();
            if (key == 'q' || key == 'Q' || key == 27) break;
            if (key == 0) {
                key = getch();
                if (key == 63) {
                    fetch_data_from_proxy();
                    last_ticks = get_dos_ticks();
                }
            }
        }
        current_ticks = get_dos_ticks();
        if (elapsed_ticks(last_ticks, current_ticks) >= refresh_interval_ticks) {
            fetch_data_from_proxy();
            last_ticks = get_dos_ticks();
        }
        delay(100);
    }
    close_esp_at_transport();
    clear_screen(MAKE_ATTR(BLACK, LIGHTGRAY));
    gotoxy(1, 1);
    printf("Pocket386 Dashboard closed.\n");
    return 0;
}