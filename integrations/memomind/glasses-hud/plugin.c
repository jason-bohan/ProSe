#include "gm_plugin_lvgl_api.h"

/* ProSe coaching HUD: a cue box and a speaker mood/momentum box, both
 * bordered/rounded, updated from Bluetooth messages sent by the paired
 * ProSe Live Coach Web plugin. Single-click hides the mood/momentum box
 * (simplified view); double-click shows it again (full view) -- mirrors
 * the vendor's own nav-HUD "Double-click: Full view, single-click:
 * Simplified mode" convention.
 *
 * Wire payload (application-defined, channel PROSE_HUD_CHANNEL):
 *   byte 0      mood_intensity   (0 = no mood data, else 1-5)
 *   byte 1      mood_label_id    (index into MOOD_LABELS; ignored if
 *                                 mood_intensity == 0)
 *   byte 2      momentum_pct     (0-100)
 *   byte 3      speaker_len      (0-255)
 *   bytes       speaker (UTF-8, speaker_len bytes)
 *   2 bytes     prompt_len       (little-endian uint16; 0 = clear display)
 *   bytes       prompt (UTF-8, prompt_len bytes)
 *
 * Hit reactions (gamification): an in-band momentum swing between two
 * messages (+4..+12 = a landed rebuttal, -4..-12 = a lost exchange) plays a
 * brief flinch on the face that took it -- the speaker mood face (the
 * opponent) when momentum rises, the momentum boxer when it falls.
 *
 * Faces are kkrieger-style procedural: only the recipe ships, never the
 * pixels. Expressions are drawn at runtime into RAM frame buffers from
 * parameters (mouth curve from confidence, mood-driven brows, blink), the
 * flinch frames are derived per-hit by displacing the current face, and a
 * round-start banner wipes in over the HUD when a launcher menu turns into
 * a live session. The wire format is unchanged.
 */

#define PROSE_HUD_CHANNEL ((gm_plugin_bt_channel_t)20560U)

#define CUE_BOX_X 12
#define CUE_BOX_Y 12
#define CUE_BOX_WIDTH 576
#define CUE_BOX_HEIGHT 190
#define CUE_TEXT_MARGIN 14

#define STATUS_BOX_X 12
#define STATUS_BOX_Y 214
#define STATUS_BOX_WIDTH 576
#define STATUS_BOX_HEIGHT 120
#define STATUS_TEXT_MARGIN 14

/* Icon frame: a bordered box (reusing create_bordered_box, already proven
 * to render cleanly) with a generated FACE_W x FACE_H parametric face
 * centered inside it. */
#define ICON_FRAME_WIDTH 48
#define ICON_FRAME_HEIGHT 40
#define ICON_OFFSET_X ((ICON_FRAME_WIDTH - FACE_W) / 2)
#define ICON_OFFSET_Y ((ICON_FRAME_HEIGHT - FACE_H) / 2)

#define MOOD_ICON_X 14
#define MOOD_ICON_Y 4
#define STATUS_LABEL_X (MOOD_ICON_X + ICON_FRAME_WIDTH + 10)
#define STATUS_LABEL_WIDTH (STATUS_BOX_WIDTH - STATUS_LABEL_X - STATUS_TEXT_MARGIN)

#define BAR_X 20
#define BAR_Y 90
/* Shrunk from the box's full inner width to leave room for the boxer icon
 * standing at the end of the bar, with enough gap that it doesn't visually
 * merge into the bar's rounded end at this display's resolution. */
#define BAR_WIDTH 474
#define BAR_HEIGHT 14

#define BOXER_ICON_X (STATUS_BOX_WIDTH - STATUS_TEXT_MARGIN - ICON_FRAME_WIDTH)
#define BOXER_ICON_Y (BAR_Y + BAR_HEIGHT / 2 - ICON_FRAME_HEIGHT / 2)

#define MOOD_LABEL_COUNT 6U
static const char *const MOOD_LABELS[MOOD_LABEL_COUNT] = {
    "calm", "confident", "tense", "defensive", "frustrated", "neutral",
};

/* Longest rendered status line: "Frustrated 5/5 - 50 words-ish" headroom. */
#define STATUS_TEXT_CAPACITY 96U
#define CUE_TEXT_CAPACITY 192U

/* --- parametric face: the recipe, not the pixels ---------------------- *
 * A face frame is a 64-byte grayscale BGRA8888 palette (index 0
 * transparent, 1-15 = shade * 17) followed by 4-bit pixels (two per byte,
 * even x in the high nibble) -- the same layout tools/png_to_gmp_icon.py
 * emits, so generated frames plug straight into the image descriptors. */
#define FACE_W 32
#define FACE_H 24
#define FACE_ROW_BYTES (FACE_W / 2)
#define FACE_PIXEL_OFFSET 64
#define FACE_DATA_SIZE (FACE_PIXEL_OFFSET + FACE_ROW_BYTES * FACE_H) /* 448 */
#define FACE_SHADE 14U          /* primary stroke (bright) */
#define FACE_SHADE_DIM 9U       /* secondary stroke (dimmer) */

#define JOLT_FRAME_COUNT 10
#define JOLT_FRAME_MS 45U
#define JOLT_DURATION_MS (JOLT_FRAME_COUNT * JOLT_FRAME_MS) /* 450ms */

#define WIPE_BOX_W 280
#define WIPE_BOX_H 96
#define WIPE_CHAR_MS 35U
#define WIPE_HOLD_MS 700U
#define WIPE_TEXT_CAPACITY 32U

#define BLINK_MIN_MS 1800U
#define BLINK_SPAN_MS 2600U
#define BLINK_ON_MS 110U

typedef struct {
    int8_t mouth_curve;   /* -127 frown .. +127 smile */
    uint8_t mouth_open;   /* 0..200 open/shout mouth */
    uint8_t eye_open;     /* 0 = closed (blink) .. 255 */
    int8_t brow_tilt;     /* < -40 furrowed, > 40 worried */
    uint8_t dazed;        /* 1 = ring eyes + wavy mouth */
} face_params_t;

/* Raster icon: a bordered frame (create_bordered_box) containing an LVGL
 * animation object created with a single generated frame. The source is
 * swapped (anim_image_set_sources) whenever the face parameters change,
 * and a momentum swing temporarily plays a derived flinch sequence.
 * Shared by the speaker mood icon and the momentum "boxer" icon. */
typedef struct {
    gm_plugin_lvgl_obj_t *frame;
    gm_plugin_lvgl_obj_t *image;
    gm_plugin_lvgl_image_dsc_t dsc;
    const gm_plugin_lvgl_image_dsc_t *current;
    face_params_t params;
    union {
        uint32_t force_align; /* host rejects payloads not aligned to 4 bytes */
        uint8_t bytes[FACE_DATA_SIZE];
    } pixels;
} icon_t;

typedef struct {
    gm_plugin_lvgl_obj_t *cue_box;
    gm_plugin_lvgl_obj_t *cue_label;
    gm_plugin_lvgl_obj_t *status_box;
    gm_plugin_lvgl_obj_t *status_label;
    gm_plugin_lvgl_obj_t *bar_track;
    gm_plugin_lvgl_obj_t *bar_value;
    gm_plugin_lvgl_obj_t *wipe_box;
    gm_plugin_lvgl_obj_t *wipe_label;
    gm_plugin_lvgl_obj_t *wipe_bar;
    icon_t mood_icon;
    icon_t boxer_icon;
    bool status_box_visible;
    char cue_text[CUE_TEXT_CAPACITY];
    char status_text[STATUS_TEXT_CAPACITY];
} prose_hud_context_t;

static const gm_plugin_lvgl_api_t *s_ui;
static const gm_plugin_host_api_t *s_host;
static prose_hud_context_t s_context;
static int s_prev_momentum = -1; /* -1 until the first frame arrives */
static bool s_prev_was_menu;     /* last frame came from the HUD launcher */
static bool s_launcher_frame;    /* buttons route to the server state machine */

/* Flinch bank: derived from the icon that took the hit, on demand. */
static gm_plugin_lvgl_image_dsc_t s_jolt_dsc[JOLT_FRAME_COUNT];
static _Alignas(4) uint8_t s_jolt_px[JOLT_FRAME_COUNT][FACE_DATA_SIZE];
static uint32_t s_jolt_ms; /* remaining flinch time; blocks blink */

/* Round-start banner + blink state, advanced by on_loop. */
static char s_wipe_text[WIPE_TEXT_CAPACITY];
static uint32_t s_wipe_ms;
static bool s_wipe_active;
static uint32_t s_blink_countdown;
static uint32_t s_blink_ms;
static bool s_blink_on;
static uint32_t s_rng = 0x2545F491u;

static uint32_t face_random(void)
{
    s_rng = s_rng * 1664525u + 1013904223u;
    return s_rng >> 16;
}

static size_t prose_strlen(const char *text)
{
    size_t length = 0U;
    while (text[length] != '\0') ++length;
    return length;
}

/* The plugin links with -nostdlib; GCC still emits memcpy calls for small
 * struct assignments, so provide the symbol locally (a byte loop; copy
 * sizes here are at most a few dozen bytes). */
void *memcpy(void *destination, const void *source, size_t size)
{
    uint8_t *to = (uint8_t *)destination;
    const uint8_t *from = (const uint8_t *)source;
    for (size_t index = 0U; index < size; ++index) to[index] = from[index];
    return destination;
}

static void prose_strcpy_bounded(char *destination, size_t capacity,
                                 const uint8_t *source, uint32_t source_length)
{
    uint32_t copy_length = source_length;
    if (copy_length > capacity - 1U) copy_length = (uint32_t)(capacity - 1U);
    for (uint32_t index = 0U; index < copy_length; ++index)
        destination[index] = (char)source[index];
    destination[copy_length] = '\0';
}

/* ---- parametric face: palette, pixels, primitives -------------------- */

static void face_setup_frame(gm_plugin_lvgl_image_dsc_t *dsc, uint8_t *pixels)
{
    int offset;
    pixels[0] = 0U; pixels[1] = 0U; pixels[2] = 0U; pixels[3] = 0U; /* transparent */
    for (offset = 1; offset < 16; ++offset) {
        uint8_t shade = (uint8_t)(offset * 17);
        pixels[offset * 4 + 0] = shade;
        pixels[offset * 4 + 1] = shade;
        pixels[offset * 4 + 2] = shade;
        pixels[offset * 4 + 3] = 0xFFu;
    }
    for (offset = FACE_PIXEL_OFFSET; offset < FACE_DATA_SIZE; ++offset) pixels[offset] = 0U;
    /* Field-by-field: an aggregate assignment would emit a memcpy call, and
     * this plugin links with -nostdlib (no libc). */
    dsc->struct_size = (uint16_t)sizeof(gm_plugin_lvgl_image_dsc_t);
    dsc->width = FACE_W;
    dsc->height = FACE_H;
    dsc->format = GM_PLUGIN_LVGL_IMAGE_INDEXED_4BIT;
    dsc->reserved = 0U;
    dsc->data = pixels;
    dsc->data_size = FACE_DATA_SIZE;
}

static void face_set_pixel(uint8_t *buf, int x, int y, uint8_t shade)
{
    int index;
    if (x < 0 || x >= FACE_W || y < 0 || y >= FACE_H) return;
    index = FACE_PIXEL_OFFSET + y * FACE_ROW_BYTES + (x >> 1);
    if ((x & 1) != 0) buf[index] = (uint8_t)((buf[index] & 0xF0u) | (shade & 0x0Fu));
    else buf[index] = (uint8_t)((buf[index] & 0x0Fu) | ((shade & 0x0Fu) << 4));
}

static int face_get_pixel(const uint8_t *buf, int x, int y)
{
    int index = FACE_PIXEL_OFFSET + y * FACE_ROW_BYTES + (x >> 1);
    if ((x & 1) != 0) return (int)(buf[index] & 0x0Fu);
    return (int)(buf[index] >> 4);
}

static void face_fill_rect(uint8_t *buf, int x0, int y0, int width, int height, uint8_t shade)
{
    for (int y = y0; y < y0 + height; ++y)
        for (int x = x0; x < x0 + width; ++x)
            face_set_pixel(buf, x, y, shade);
}

static void face_line(uint8_t *buf, int x0, int y0, int x1, int y1, uint8_t shade)
{
    int dx = (x1 > x0) ? (x1 - x0) : (x0 - x1);
    int dy = (y1 > y0) ? (y1 - y0) : (y0 - y1);
    int sx = (x0 < x1) ? 1 : -1;
    int sy = (y0 < y1) ? 1 : -1;
    int error = dx - dy;
    for (;;) {
        int twice;
        face_set_pixel(buf, x0, y0, shade);
        if (x0 == x1 && y0 == y1) break;
        twice = 2 * error;
        if (twice > -dy) { error -= dy; x0 += sx; }
        if (twice < dx) { error += dx; y0 += sy; }
    }
}

static void face_ring(uint8_t *buf, int cx, int cy, int radius, uint8_t shade)
{
    int inner = (radius - 1) * (radius - 1);
    int outer = (radius + 1) * (radius + 1);
    for (int y = cy - radius; y <= cy + radius; ++y)
        for (int x = cx - radius; x <= cx + radius; ++x) {
            int dx = x - cx;
            int dy = y - cy;
            int distance = dx * dx + dy * dy;
            if (distance >= inner && distance <= outer) face_set_pixel(buf, x, y, shade);
        }
}

/* Draw one face frame: clears pixels (palette stays), then eyes, brows,
 * mouth. All geometry is tiny by design -- a 32x24 TE-style glyph face. */
static void face_render(uint8_t *buf, const face_params_t *params)
{
    static const int8_t dazed_wave[21] = {
        0, 1, 2, 2, 1, 0, -1, -2, -2, -1, 0, 1, 2, 2, 1, 0, -1, -2, -2, -1, 0,
    };
    for (int index = FACE_PIXEL_OFFSET; index < FACE_DATA_SIZE; ++index) buf[index] = 0U;

    if (params->dazed != 0U) {
        face_ring(buf, 10, 8, 2, FACE_SHADE);
        face_ring(buf, 22, 8, 2, FACE_SHADE);
        face_set_pixel(buf, 10, 8, FACE_SHADE_DIM);
        face_set_pixel(buf, 22, 8, FACE_SHADE_DIM);
        for (int x = 0; x < 21; ++x) {
            face_set_pixel(buf, 6 + x, 18 + dazed_wave[x], FACE_SHADE);
            face_set_pixel(buf, 6 + x, 19 + dazed_wave[x], FACE_SHADE);
        }
        return;
    }

    {
        int eye_height = 1 + (int)((unsigned)params->eye_open * 5u / 255u);
        int eye_top = 8 - eye_height / 2;
        face_fill_rect(buf, 8, eye_top, 4, eye_height, FACE_SHADE);
        face_fill_rect(buf, 20, eye_top, 4, eye_height, FACE_SHADE);
    }
    if (params->brow_tilt <= -40) { /* furrowed */
        face_line(buf, 7, 3, 14, 6, FACE_SHADE_DIM);
        face_line(buf, 25, 3, 18, 6, FACE_SHADE_DIM);
    } else if (params->brow_tilt >= 40) { /* worried */
        face_line(buf, 7, 6, 14, 3, FACE_SHADE_DIM);
        face_line(buf, 25, 6, 18, 3, FACE_SHADE_DIM);
    }
    if (params->mouth_open >= 90U) {
        int half_w = 3 + (int)params->mouth_open / 20;
        int half_h = 1 + (int)params->mouth_open / 45;
        face_fill_rect(buf, 16 - half_w, 17 - half_h, half_w * 2, half_h * 2, FACE_SHADE);
    } else {
        int amp = (int)params->mouth_curve * 4 / 127;
        for (int x = 6; x <= 26; ++x) {
            int t = x - 16;
            int y = 18 + (amp * (100 - t * t)) / 100;
            face_set_pixel(buf, x, y, FACE_SHADE);
            face_set_pixel(buf, x, y + 1, FACE_SHADE);
        }
    }
}

/* Mood label -> face parameters; mirrors the old baked MOOD_ICON_BY_LABEL
 * mapping (calm/confident smile, tense/frustrated scowl, rest neutral),
 * with intensity scaling the frustrated shout. */
static face_params_t mood_face_params(uint8_t label, uint8_t intensity)
{
    face_params_t params;
    params.mouth_curve = 0;
    params.mouth_open = 0;
    params.eye_open = 205;
    params.brow_tilt = 0;
    params.dazed = 0;
    switch (label) {
    case 0: params.mouth_curve = 45; break;                                   /* calm */
    case 1: params.mouth_curve = 95; break;                                   /* confident */
    case 2:                                                                   /* tense */
        /* Worried (raised inner) brows + a shallow frown: distinct from the
         * defensive scowl below, which uses furrowed brows and a flat mouth. */
        params.mouth_curve = -40; params.brow_tilt = 50; params.mouth_open = 35;
        break;
    case 3:                                                                   /* defensive */
        params.mouth_curve = -10; params.brow_tilt = -45; params.mouth_open = 25;
        break;
    case 4:                                                                   /* frustrated */
        params.mouth_curve = -70; params.brow_tilt = -95;
        params.mouth_open = (uint8_t)(30u + (unsigned)intensity * 30u);
        break;
    default: break;                                                           /* neutral */
    }
    if (params.mouth_open > 200U) params.mouth_open = 200U;
    return params;
}

/* Momentum -> boxer face: confidence literally curves the mouth. */
static face_params_t boxer_face_params(uint8_t momentum)
{
    face_params_t params;
    params.mouth_curve = (int8_t)(((int)momentum - 50) * 5 / 4);
    params.mouth_open = 0;
    params.eye_open = 210;
    params.brow_tilt = 0;
    params.dazed = 0;
    if (momentum >= 65U) {
        params.eye_open = 245;
        params.mouth_curve = (int8_t)(params.mouth_curve + 30);
    } else if (momentum <= 35U) {
        params.dazed = 1;
        params.eye_open = 150;
        params.mouth_curve = 0;
    }
    return params;
}

static gm_plugin_lvgl_obj_t *create_bordered_box(gm_plugin_lvgl_obj_t *parent,
                                                 int16_t x, int16_t y,
                                                 int16_t width, int16_t height)
{
    gm_plugin_lvgl_obj_t *box = s_ui->obj_create(parent);
    if (box == 0) return 0;
    s_ui->obj_set_pos(box, x, y);
    s_ui->obj_set_size(box, width, height);
    s_ui->style_set(box, GM_PLUGIN_LVGL_STYLE_BG_OPA,
                    gm_plugin_lvgl_style_number(0), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(box, GM_PLUGIN_LVGL_STYLE_BORDER_COLOR,
                    gm_plugin_lvgl_style_color(0xd0U), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(box, GM_PLUGIN_LVGL_STYLE_BORDER_OPA,
                    gm_plugin_lvgl_style_number(GM_PLUGIN_LVGL_OPA_COVER),
                    GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(box, GM_PLUGIN_LVGL_STYLE_BORDER_WIDTH,
                    gm_plugin_lvgl_style_number(2), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(box, GM_PLUGIN_LVGL_STYLE_RADIUS,
                    gm_plugin_lvgl_style_number(10), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(box, GM_PLUGIN_LVGL_STYLE_PAD_TOP,
                    gm_plugin_lvgl_style_number(0), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(box, GM_PLUGIN_LVGL_STYLE_PAD_BOTTOM,
                    gm_plugin_lvgl_style_number(0), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(box, GM_PLUGIN_LVGL_STYLE_PAD_LEFT,
                    gm_plugin_lvgl_style_number(0), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(box, GM_PLUGIN_LVGL_STYLE_PAD_RIGHT,
                    gm_plugin_lvgl_style_number(0), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->obj_clear_flag(box, GM_PLUGIN_LVGL_FLAG_SCROLLABLE);
    return box;
}

static gm_plugin_lvgl_obj_t *create_bar_rect(gm_plugin_lvgl_obj_t *parent,
                                             int16_t x, int16_t y,
                                             int16_t width, int16_t height,
                                             uint8_t shade)
{
    gm_plugin_lvgl_obj_t *rect = s_ui->obj_create(parent);
    if (rect == 0) return 0;
    s_ui->obj_set_pos(rect, x, y);
    s_ui->obj_set_size(rect, width, height);
    s_ui->style_set(rect, GM_PLUGIN_LVGL_STYLE_BG_COLOR,
                    gm_plugin_lvgl_style_color(shade), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(rect, GM_PLUGIN_LVGL_STYLE_BG_OPA,
                    gm_plugin_lvgl_style_number(GM_PLUGIN_LVGL_OPA_COVER),
                    GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(rect, GM_PLUGIN_LVGL_STYLE_BORDER_WIDTH,
                    gm_plugin_lvgl_style_number(0), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_ui->style_set(rect, GM_PLUGIN_LVGL_STYLE_RADIUS,
                    gm_plugin_lvgl_style_number(4), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    return rect;
}

static bool create_icon(icon_t *icon, gm_plugin_lvgl_obj_t *parent, int16_t x, int16_t y,
                        const face_params_t *initial)
{
    const gm_plugin_lvgl_image_dsc_t *frames[1];
    face_setup_frame(&icon->dsc, icon->pixels.bytes);
    face_render(icon->pixels.bytes, initial);
    icon->params = *initial;
    icon->current = &icon->dsc;
    frames[0] = &icon->dsc;
    icon->frame = create_bordered_box(parent, x, y, ICON_FRAME_WIDTH, ICON_FRAME_HEIGHT);
    if (icon->frame == 0) return false;
    icon->image = s_ui->anim_image_create(icon->frame, frames, 1U, 100U, 0U);
    if (icon->image == 0) {
        if (s_host != 0)
            s_host->log("prose-hud: anim_image_create failed at x=%d y=%d", (int)x, (int)y);
        return false;
    }
    s_ui->obj_set_pos(icon->image, ICON_OFFSET_X, ICON_OFFSET_Y);
    s_ui->obj_set_size(icon->image, FACE_W, FACE_H);
    if (s_host != 0)
        s_host->log("prose-hud: face icon created frame_xy=%d,%d data=%p",
                    (int)x, (int)y, (const void *)icon->pixels.bytes);
    return true;
}

/* Re-render an icon from new parameters (also used to restore after blink). */
static void render_icon(icon_t *icon, face_params_t params)
{
    if (icon->image == 0) return;
    icon->params = params;
    face_render(icon->pixels.bytes, &params);
    icon->current = &icon->dsc;
    s_ui->anim_image_set_sources(icon->image, &icon->current, 1U);
}

/* Momentary eye override without touching the icon's canonical params. */
static void render_icon_blink(icon_t *icon, uint8_t eye_open)
{
    face_params_t params;
    if (icon->image == 0) return;
    params = icon->params;
    params.eye_open = eye_open;
    face_render(icon->pixels.bytes, &params);
    icon->current = &icon->dsc;
    s_ui->anim_image_set_sources(icon->image, &icon->current, 1U);
}

/* Round-start banner: shows the incoming speaker (e.g. "READY") over the
 * HUD while on_loop wipes the text in and grows the underline, then hides. */
static void wipe_start(const char *text)
{
    size_t length = prose_strlen(text);
    if (s_context.wipe_box == 0 || length == 0U) return;
    if (length >= WIPE_TEXT_CAPACITY) length = WIPE_TEXT_CAPACITY - 1U;
    for (size_t index = 0U; index < length; ++index) s_wipe_text[index] = text[index];
    s_wipe_text[length] = '\0';
    s_wipe_ms = 0U;
    s_wipe_active = true;
    s_ui->label_set_text(s_context.wipe_label, "");
    s_ui->obj_set_size(s_context.wipe_bar, 0, 6);
    s_ui->obj_clear_flag(s_context.wipe_box, GM_PLUGIN_LVGL_FLAG_HIDDEN);
    if (s_host != 0) s_host->log("prose-hud: wipe start text=%s", s_wipe_text);
}

/* Flinch: derive JOLT_FRAME_COUNT displaced copies of the icon's current
 * pixels (kkrieger-style history transform) and let anim_image play them as
 * a decreasing zigzag with a settle frame. Stopped frames rest on the last
 * (undisplaced) frame; the next render_icon call resets to static. */
static void jolt_icon(icon_t *icon)
{
    static const int8_t shifts[JOLT_FRAME_COUNT] = { 0, 4, -4, 3, -3, 2, -2, 1, -1, 0 };
    const gm_plugin_lvgl_image_dsc_t *frames[JOLT_FRAME_COUNT];
    if (icon->image == 0) return;
    for (int frame = 0; frame < JOLT_FRAME_COUNT; ++frame) {
        for (int byte = 0; byte < FACE_DATA_SIZE; ++byte)
            s_jolt_px[frame][byte] = icon->pixels.bytes[byte];
        if (shifts[frame] != 0) {
            for (int y = 0; y < FACE_H; ++y) {
                for (int x = 0; x < FACE_W; ++x) {
                    int source_x = ((x - shifts[frame]) % FACE_W + FACE_W) % FACE_W;
                    face_set_pixel(s_jolt_px[frame], x, y,
                                   (uint8_t)face_get_pixel(icon->pixels.bytes, source_x, y));
                }
            }
        }
        frames[frame] = &s_jolt_dsc[frame];
    }
    s_ui->anim_image_set_sources(icon->image, frames, JOLT_FRAME_COUNT);
    s_ui->anim_image_set_frame_duration(icon->image, JOLT_FRAME_MS);
    s_ui->anim_image_set_repeat_count(icon->image, 0U);
    s_ui->anim_image_start(icon->image);
    s_jolt_ms = JOLT_DURATION_MS;
    if (s_host != 0) s_host->log("prose-hud: jolt frames=%d", JOLT_FRAME_COUNT);
}

static void update_bar_value(uint8_t momentum_pct)
{
    int16_t filled = (int16_t)((uint32_t)BAR_WIDTH * momentum_pct / 100U);
    if (filled < 0) filled = 0;
    if (filled > BAR_WIDTH) filled = BAR_WIDTH;
    if (s_context.bar_value != 0) s_ui->obj_set_size(s_context.bar_value, filled, BAR_HEIGHT);
}

static void set_status_box_visible(bool visible)
{
    if (s_context.status_box == 0) return;
    s_context.status_box_visible = visible;
    if (visible) s_ui->obj_clear_flag(s_context.status_box, GM_PLUGIN_LVGL_FLAG_HIDDEN);
    else s_ui->obj_add_flag(s_context.status_box, GM_PLUGIN_LVGL_FLAG_HIDDEN);
}

static gm_plugin_result_t prose_hud_start(void *context)
{
    gm_plugin_lvgl_obj_t *root;
    face_params_t neutral;
    int index;
    (void)context;

    root = s_ui->root_get();
    if (root == 0) return GM_PLUGIN_ESTATE;
    s_ui->obj_clean(root);

    s_context.cue_box = create_bordered_box(root, CUE_BOX_X, CUE_BOX_Y,
                                            CUE_BOX_WIDTH, CUE_BOX_HEIGHT);
    s_context.status_box = create_bordered_box(root, STATUS_BOX_X, STATUS_BOX_Y,
                                               STATUS_BOX_WIDTH, STATUS_BOX_HEIGHT);
    if (s_context.cue_box == 0 || s_context.status_box == 0) goto no_memory;

    s_context.cue_label = s_ui->label_create(s_context.cue_box);
    if (s_context.cue_label == 0) goto no_memory;
    s_ui->obj_set_pos(s_context.cue_label, CUE_TEXT_MARGIN, CUE_TEXT_MARGIN);
    s_ui->obj_set_size(s_context.cue_label,
                       (gm_plugin_lvgl_coord_t)(CUE_BOX_WIDTH - 2 * CUE_TEXT_MARGIN),
                       (gm_plugin_lvgl_coord_t)(CUE_BOX_HEIGHT - 2 * CUE_TEXT_MARGIN));
    s_ui->label_set_long_mode(s_context.cue_label, GM_PLUGIN_LVGL_LABEL_WRAP);
    s_ui->style_set(s_context.cue_label, GM_PLUGIN_LVGL_STYLE_TEXT_COLOR,
                    gm_plugin_lvgl_style_color(0xf0U), GM_PLUGIN_LVGL_SELECTOR_MAIN);

    s_context.status_label = s_ui->label_create(s_context.status_box);
    if (s_context.status_label == 0) goto no_memory;
    s_ui->obj_set_pos(s_context.status_label, STATUS_LABEL_X, STATUS_TEXT_MARGIN);
    s_ui->obj_set_size(s_context.status_label,
                       (gm_plugin_lvgl_coord_t)STATUS_LABEL_WIDTH, 28);
    s_ui->label_set_long_mode(s_context.status_label, GM_PLUGIN_LVGL_LABEL_CLIP);
    s_ui->style_set(s_context.status_label, GM_PLUGIN_LVGL_STYLE_TEXT_COLOR,
                    gm_plugin_lvgl_style_color(0xd0U), GM_PLUGIN_LVGL_SELECTOR_MAIN);

    neutral = mood_face_params(5U, 0U);
    if (!create_icon(&s_context.mood_icon, s_context.status_box, MOOD_ICON_X, MOOD_ICON_Y,
                     &neutral))
        goto no_memory;
    if (!create_icon(&s_context.boxer_icon, s_context.status_box, BOXER_ICON_X, BOXER_ICON_Y,
                     &neutral))
        goto no_memory;

    s_context.bar_track = create_bar_rect(s_context.status_box, BAR_X, BAR_Y,
                                          BAR_WIDTH, BAR_HEIGHT, 0x40U);
    s_context.bar_value = create_bar_rect(s_context.status_box, BAR_X, BAR_Y,
                                          0, BAR_HEIGHT, 0xd0U);
    if (s_context.bar_track == 0 || s_context.bar_value == 0) goto no_memory;

    /* Round-start banner: centered, created last so it draws on top. */
    s_context.wipe_box = create_bordered_box(
        root,
        (int16_t)(((int)s_ui->obj_get_width(root) - WIPE_BOX_W) / 2),
        (int16_t)(((int)s_ui->obj_get_height(root) - WIPE_BOX_H) / 2),
        WIPE_BOX_W, WIPE_BOX_H);
    if (s_context.wipe_box == 0) goto no_memory;
    s_context.wipe_label = s_ui->label_create(s_context.wipe_box);
    if (s_context.wipe_label == 0) goto no_memory;
    s_ui->obj_set_pos(s_context.wipe_label, 14, 18);
    s_ui->obj_set_size(s_context.wipe_label, WIPE_BOX_W - 28, 44);
    s_ui->label_set_long_mode(s_context.wipe_label, GM_PLUGIN_LVGL_LABEL_CLIP);
    s_ui->style_set(s_context.wipe_label, GM_PLUGIN_LVGL_STYLE_TEXT_COLOR,
                    gm_plugin_lvgl_style_color(0xf0U), GM_PLUGIN_LVGL_SELECTOR_MAIN);
    s_context.wipe_bar = create_bar_rect(s_context.wipe_box, 14, WIPE_BOX_H - 26, 0, 6, 0xd0U);
    if (s_context.wipe_bar == 0) goto no_memory;
    s_ui->obj_add_flag(s_context.wipe_box, GM_PLUGIN_LVGL_FLAG_HIDDEN);

    /* Flinch bank descriptors point at the persistent RAM frames. */
    for (index = 0; index < JOLT_FRAME_COUNT; ++index) {
        s_jolt_dsc[index].struct_size = (uint16_t)sizeof(gm_plugin_lvgl_image_dsc_t);
        s_jolt_dsc[index].width = FACE_W;
        s_jolt_dsc[index].height = FACE_H;
        s_jolt_dsc[index].format = GM_PLUGIN_LVGL_IMAGE_INDEXED_4BIT;
        s_jolt_dsc[index].reserved = 0U;
        s_jolt_dsc[index].data = s_jolt_px[index];
        s_jolt_dsc[index].data_size = FACE_DATA_SIZE;
    }

    s_context.cue_text[0] = '\0';
    s_context.status_text[0] = '\0';
    s_prev_momentum = -1;
    s_prev_was_menu = false;
    s_launcher_frame = false;
    s_jolt_ms = 0U;
    s_wipe_active = false;
    s_wipe_text[0] = '\0';
    s_blink_on = false;
    s_blink_ms = 0U;
    s_blink_countdown = BLINK_MIN_MS;
    s_ui->label_set_text(s_context.cue_label, "Listening...");
    s_ui->label_set_text(s_context.status_label, "");
    update_bar_value(50U);
    s_ui->obj_add_flag(s_context.cue_box, GM_PLUGIN_LVGL_FLAG_HIDDEN);
    set_status_box_visible(true);
    return GM_PLUGIN_OK;

no_memory:
    s_context.cue_box = 0;
    s_context.cue_label = 0;
    s_context.status_box = 0;
    s_context.status_label = 0;
    s_context.bar_track = 0;
    s_context.bar_value = 0;
    s_context.wipe_box = 0;
    s_context.wipe_label = 0;
    s_context.wipe_bar = 0;
    s_context.mood_icon.frame = 0;
    s_context.mood_icon.image = 0;
    s_context.boxer_icon.frame = 0;
    s_context.boxer_icon.image = 0;
    s_wipe_active = false;
    s_ui->obj_clean(root);
    return GM_PLUGIN_ENOMEM;
}

static void prose_hud_stop(void *context)
{
    gm_plugin_lvgl_obj_t *root;
    (void)context;
    root = s_ui->root_get();
    if (root != 0) s_ui->obj_clean(root);
    s_context.cue_box = 0;
    s_context.cue_label = 0;
    s_context.status_box = 0;
    s_context.status_label = 0;
    s_context.bar_track = 0;
    s_context.bar_value = 0;
    s_context.wipe_box = 0;
    s_context.wipe_label = 0;
    s_context.wipe_bar = 0;
    s_context.mood_icon.frame = 0;
    s_context.mood_icon.image = 0;
    s_context.boxer_icon.frame = 0;
    s_context.boxer_icon.image = 0;
    s_wipe_active = false;
    s_jolt_ms = 0U;
    s_blink_on = false;
}

static void handle_hud_message(const uint8_t *data, uint32_t length)
{
    uint8_t mood_intensity;
    uint8_t mood_label_id;
    uint8_t momentum_pct;
    uint8_t speaker_len;
    uint16_t prompt_len;
    const uint8_t *cursor = data;
    uint32_t remaining = length;

    if (remaining < 4U) return;
    mood_intensity = cursor[0];
    mood_label_id = cursor[1];
    momentum_pct = cursor[2];
    speaker_len = cursor[3];
    cursor += 4; remaining -= 4U;
    if (s_host != 0)
        s_host->log("prose-hud: msg len=%u mood_intensity=%u mood_label_id=%u momentum_pct=%u speaker_len=%u",
                    (unsigned)length, (unsigned)mood_intensity, (unsigned)mood_label_id,
                    (unsigned)momentum_pct, (unsigned)speaker_len);
    if (remaining < (uint32_t)speaker_len) return;

    {
        char speaker[64];
        bool is_menu;
        prose_strcpy_bounded(speaker, sizeof(speaker), cursor, speaker_len);
        is_menu = speaker_len >= 4U && speaker[0] == 'M' && speaker[1] == 'O'
                  && speaker[2] == 'D' && speaker[3] == 'E';
        /* Menu, setup, and matrix frames all accept accessory buttons; the
         * server owns the state machine, so presses are forwarded as-is. */
        s_launcher_frame = is_menu
            || (speaker_len >= 4U && speaker[0] == 'T' && speaker[1] == 'O'
                && speaker[2] == 'N' && speaker[3] == 'E')
            || (speaker_len >= 5U && speaker[0] == 'S' && speaker[1] == 'E'
                && speaker[2] == 'T' && speaker[3] == 'U' && speaker[4] == 'P');
        /* A launcher menu frame turning into a live-session frame starts
         * the round-start banner (speaker arrives as e.g. "READY"). */
        if (s_prev_was_menu && !is_menu) wipe_start(speaker);
        s_prev_was_menu = is_menu;

        if (mood_intensity > 0U && mood_intensity <= 5U && mood_label_id < MOOD_LABEL_COUNT) {
            /* Minimal formatted write without pulling in a libc snprintf dependency:
             * build "{speaker}: {mood} {intensity}/5" by hand. */
            size_t pos = 0U;
            size_t speaker_actual = prose_strlen(speaker);
            for (size_t i = 0U; i < speaker_actual && pos < STATUS_TEXT_CAPACITY - 1U; ++i)
                s_context.status_text[pos++] = speaker[i];
            if (pos < STATUS_TEXT_CAPACITY - 2U) {
                s_context.status_text[pos++] = ':';
                s_context.status_text[pos++] = ' ';
            }
            const char *mood = MOOD_LABELS[mood_label_id];
            size_t mood_len = prose_strlen(mood);
            for (size_t i = 0U; i < mood_len && pos < STATUS_TEXT_CAPACITY - 1U; ++i)
                s_context.status_text[pos++] = mood[i];
            if (pos < STATUS_TEXT_CAPACITY - 5U) {
                s_context.status_text[pos++] = ' ';
                s_context.status_text[pos++] = (char)('0' + (mood_intensity % 10U));
                s_context.status_text[pos++] = '/';
                s_context.status_text[pos++] = '5';
            }
            s_context.status_text[pos] = '\0';
            render_icon(&s_context.mood_icon, mood_face_params(mood_label_id, mood_intensity));
        } else {
            s_context.status_text[0] = '\0';
            render_icon(&s_context.mood_icon, mood_face_params(5U, 0U));
        }
    }
    if (s_context.status_label != 0) s_ui->label_set_text(s_context.status_label, s_context.status_text);
    render_icon(&s_context.boxer_icon, boxer_face_params(momentum_pct));
    update_bar_value(momentum_pct);

    /* In-band momentum swing = a scoring event: a rise knocks the speaker
     * mood face (the opponent took the hit), a drop knocks the momentum
     * boxer (you took it). Menu moves (±20..30) and session transitions sit
     * outside the band and stay still. */
    if (s_prev_momentum >= 0) {
        int delta = (int)momentum_pct - s_prev_momentum;
        if (delta >= 4 && delta <= 12) jolt_icon(&s_context.mood_icon);
        else if (delta <= -4 && delta >= -12) jolt_icon(&s_context.boxer_icon);
    }
    s_prev_momentum = (int)momentum_pct;

    cursor += speaker_len; remaining -= speaker_len;
    if (remaining < 2U) return;
    prompt_len = (uint16_t)(cursor[0] | ((uint16_t)cursor[1] << 8));
    cursor += 2; remaining -= 2U;
    if (remaining < (uint32_t)prompt_len) return;

    if (prompt_len == 0U) {
        s_context.cue_text[0] = '\0';
        if (s_context.cue_box != 0) s_ui->obj_add_flag(s_context.cue_box, GM_PLUGIN_LVGL_FLAG_HIDDEN);
        return;
    }
    prose_strcpy_bounded(s_context.cue_text, sizeof(s_context.cue_text), cursor, prompt_len);
    if (s_context.cue_label != 0) s_ui->label_set_text(s_context.cue_label, s_context.cue_text);
    if (s_context.cue_box != 0) s_ui->obj_clear_flag(s_context.cue_box, GM_PLUGIN_LVGL_FLAG_HIDDEN);
}

/* Periodic tick: advances the round-start banner wipe, the idle blink, and
 * the flinch cooldown. Time-based (elapsed_ms), never assumes a frame rate. */
static void prose_hud_loop(void *context, uint32_t elapsed_ms)
{
    (void)context;
    if (elapsed_ms > 250U) elapsed_ms = 250U;

    if (s_jolt_ms > elapsed_ms) s_jolt_ms -= elapsed_ms;
    else s_jolt_ms = 0U;

    if (s_wipe_active && s_context.wipe_box != 0) {
        uint32_t length = (uint32_t)prose_strlen(s_wipe_text);
        uint32_t reveal_ms = length * WIPE_CHAR_MS;
        uint32_t span = (reveal_ms > 0U) ? reveal_ms : 1U;
        uint32_t shown;
        char shown_text[WIPE_TEXT_CAPACITY];
        s_wipe_ms += elapsed_ms;
        shown = s_wipe_ms / WIPE_CHAR_MS;
        if (shown > length) shown = length;
        for (uint32_t index = 0U; index < shown; ++index) shown_text[index] = s_wipe_text[index];
        shown_text[shown] = '\0';
        s_ui->label_set_text(s_context.wipe_label, shown_text);
        {
            uint32_t progress = (s_wipe_ms < span) ? s_wipe_ms : span;
            int16_t bar_width = (int16_t)((uint32_t)(WIPE_BOX_W - 28) * progress / span);
            s_ui->obj_set_size(s_context.wipe_bar, bar_width, 6);
        }
        if (s_wipe_ms >= reveal_ms + WIPE_HOLD_MS) {
            s_ui->obj_add_flag(s_context.wipe_box, GM_PLUGIN_LVGL_FLAG_HIDDEN);
            s_ui->label_set_text(s_context.wipe_label, "");
            s_wipe_active = false;
            if (s_host != 0) s_host->log("prose-hud: wipe done");
        }
    }

    /* Idle blink -- suppressed while a flinch is playing so the two never
     * fight over anim_image_set_sources. */
    if (s_jolt_ms == 0U && s_context.mood_icon.image != 0) {
        if (s_blink_on) {
            if (s_blink_ms > elapsed_ms) {
                s_blink_ms -= elapsed_ms;
            } else {
                s_blink_on = false;
                s_blink_countdown = BLINK_MIN_MS + face_random() % BLINK_SPAN_MS;
                render_icon(&s_context.mood_icon, s_context.mood_icon.params);
                render_icon(&s_context.boxer_icon, s_context.boxer_icon.params);
            }
        } else if (s_blink_countdown > elapsed_ms) {
            s_blink_countdown -= elapsed_ms;
        } else {
            s_blink_on = true;
            s_blink_ms = BLINK_ON_MS;
            render_icon_blink(&s_context.mood_icon, 0U);
            render_icon_blink(&s_context.boxer_icon, 0U);
        }
    }
}

/* Accessory buttons while a launcher frame is showing: forward the press to
 * the server's state machine over the HUD channel; the phone relay POSTs it
 * to ProSe and the refreshed payload lands back on the lens. */
static const char *launcher_button_name(gm_plugin_button_t button)
{
    switch (button) {
    case GM_PLUGIN_BUTTON_PRIMARY: return "select";
    case GM_PLUGIN_BUTTON_UP: return "up";
    case GM_PLUGIN_BUTTON_DOWN: return "down";
    case GM_PLUGIN_BUTTON_LEFT: return "left";
    case GM_PLUGIN_BUTTON_RIGHT: return "right";
    case GM_PLUGIN_BUTTON_PAGE_UP: return "page_up";
    case GM_PLUGIN_BUTTON_PAGE_DOWN: return "page_down";
    case GM_PLUGIN_BUTTON_SCROLL_UP: return "scroll_up";
    case GM_PLUGIN_BUTTON_SCROLL_DOWN: return "scroll_down";
    case GM_PLUGIN_BUTTON_BACK: return "back";
    case GM_PLUGIN_BUTTON_HOME: return "home";
    default: return 0;
    }
}

static bool forward_button(gm_plugin_button_t button)
{
    const char *name = launcher_button_name(button);
    const char *prefix = "{\"button\":\"";
    char payload[32];
    size_t pos = 0U;
    size_t i;
    if (name == 0 || s_host == 0 || s_host->bt_send == 0) return false;
    for (i = 0U; prefix[i] != '\0' && pos < sizeof(payload) - 1U; ++i)
        payload[pos++] = prefix[i];
    for (i = 0U; name[i] != '\0' && pos < sizeof(payload) - 3U; ++i)
        payload[pos++] = name[i];
    payload[pos++] = '"';
    payload[pos++] = '}';
    payload[pos] = '\0';
    if (s_host->bt_send(PROSE_HUD_CHANNEL, payload, (uint32_t)pos) != GM_PLUGIN_OK) {
        s_host->log("prose-hud: button forward failed");
        return false;
    }
    return true;
}

static bool prose_hud_event(void *context, const gm_plugin_event_t *event)
{
    (void)context;
    if (event == 0) return false;
    switch (event->type) {
    case GM_PLUGIN_EVENT_BT_MESSAGE:
        if (event->data.bt.channel != PROSE_HUD_CHANNEL) return false;
        if (event->data.bt.length != 0U && event->data.bt.data == 0) return false;
        handle_hud_message(event->data.bt.data, event->data.bt.length);
        return true;
    case GM_PLUGIN_EVENT_BUTTON:
        if (s_launcher_frame) {
            if (event->data.button.action != GM_PLUGIN_BUTTON_ACTION_SINGLE)
                return false;
            return forward_button(event->data.button.button);
        }
        if (event->data.button.button != GM_PLUGIN_BUTTON_PRIMARY) return false;
        if (event->data.button.action == GM_PLUGIN_BUTTON_ACTION_SINGLE) {
            set_status_box_visible(false);
            return true;
        }
        if (event->data.button.action == GM_PLUGIN_BUTTON_ACTION_DOUBLE) {
            set_status_box_visible(true);
            return true;
        }
        return false;
    default:
        return false;
    }
}

gm_plugin_result_t gm_plugin_entry(const gm_plugin_host_api_t *host,
                                   gm_plugin_descriptor_t *plugin)
{
    const gm_plugin_capabilities_t required =
        GM_PLUGIN_CAP_BLUETOOTH | GM_PLUGIN_CAP_BUTTON;
    if (host == 0 || plugin == 0 || host->graphics.lvgl == 0 ||
        host->bt_send == 0 ||
        !GM_PLUGIN_VERSION_COMPATIBLE(host->abi_version, GM_PLUGIN_ABI_MIN_VERSION) ||
        host->struct_size < GM_PLUGIN_HOST_API_MIN_SIZE ||
        plugin->struct_size < GM_PLUGIN_DESCRIPTOR_MIN_SIZE ||
        (host->capabilities & required) != required)
        return GM_PLUGIN_ENOTSUP;
    s_ui = host->graphics.lvgl;
    if (s_ui == 0 || s_ui->struct_size < GM_PLUGIN_LVGL_API_1_1_SIZE ||
        !GM_PLUGIN_VERSION_COMPATIBLE(s_ui->api_version, GM_PLUGIN_VERSION(1U, 1U)) ||
        s_ui->anim_image_create == 0 || s_ui->anim_image_set_sources == 0 ||
        s_ui->anim_image_set_frame_duration == 0 ||
        s_ui->anim_image_set_repeat_count == 0 ||
        s_ui->anim_image_start == 0)
        return GM_PLUGIN_EVERSION;
    s_host = host;

    plugin->abi_version = GM_PLUGIN_ABI_MIN_VERSION;
    plugin->on_start = prose_hud_start;
    plugin->on_loop = prose_hud_loop;
    plugin->on_event = prose_hud_event;
    plugin->on_stop = prose_hud_stop;
    return GM_PLUGIN_OK;
}
