# karaoke.rodeo — design system

Source of truth for how the app looks. The tokens live in `web/static/common.css`; every page uses them. The
landing page (`web/welcome.html`) is the reference implementation. Earlier explorations (the `.design/` canvases)
are retired; this file replaces them.

---

## 1. Idea

The app is a **karaoke box at home**, drawn as one bright, chunky, slightly toy-like thing you can read and press.
There is **one surface: paper** — cream page, white cards, 3px ink outlines, hard offset shadows — and it covers
everything, the singing screen included.

The only dark rectangle in the app is the **video itself**, because a video is dark. The note lane, the score panel,
the result dialog, the charts, the calendar and the party strip are all paper cards like any other; what marks them
as *measured* is not a dark background but the **readout face** — big rounded numerals in the accent's paper
colour. (The readout used to be a pixel LED face; a pixel font is the voice of a dark machine and fought the paper,
so it is gone. Only the labeling instrument, which really is a dark machine, still uses it.)

This is deliberate and was learned the hard way: the previous design was a dark navy app, so any dark panel —
in any hue — reads as that old design surviving inside the new one. `.screen` survives only as a class name for
a card whose insides are drawn rather than written; it paints the same paper as `.panel`.

**Audience:** people learning Japanese through songs, 15–30, singing alone at home or with up to eight friends on
phones. Fun first; the learning benefit is a side effect the interface quietly supports.

**Furigana is a selling point.** The interface itself carries readings: every menu label, heading, button and
hint is annotated at load (`web/static/furigana.js`, a curated dictionary of the UI's own vocabulary, longest match
first). Song titles and artists carry their own stored readings (`title_ruby` / `artist_ruby`, 漢字《かな》 markup,
edited in the admin table) and are excluded from the dictionary pass with `.noruby`.

**The rodeo is a wink, not a theme.** One English line in the hero ("Grab a mic, partner.") and a rope lasso drawn
around the headline. No saloon type, no leather, no bull metaphors, and no other visible English anywhere:
English helper labels stay in `title` tooltips via `<span class="sub">` (see `applySubTooltips`).

---

## 2. Tokens (`common.css :root`)

Colours are declared with `light-dark()`; a plain light value precedes each so old browsers still get the light look.
`color-scheme: light dark` on `:root` follows the system; the profile menu pins `data-theme="light|dark"` on `<html>`
(persisted in `localStorage.karaoke_theme`, applied by a one-line script in every `<head>` before paint; `?theme=`
in the URL overrides for one load).

That same script pins one more setting: `data-ruby="off"` hides every `rt` (`karaoke_furigana`,
`?furigana=on|off`), switchable from the profile menu or, signed out, from the あ button beside the theme one.

### Paper

| Token | Light | Dark | Use |
|---|---|---|---|
| `--stage` | `#fffdf3` | `#16140f` | page background |
| `--panel` | `#ffffff` | `#221f18` | cards, buttons, dialogs |
| `--panel-2` | `#faf5e4` | `#2a251b` | inputs, chips, inset areas |
| `--line` | `#15120c` | `#453f31` | every outline. Dark keeps the 3px outline but never a bright one: cream borders on every card, button and field read as noise, not structure. |
| `--shadow` | `#15120c` | `#070605` | hard shadows |
| `--line-soft` | ink at 18% | cream at 14% | dividers inside a card (the only thin line allowed). Dark cannot derive this from `--line` — the muted outline is too close to the panel to read as a rule. |
| `--ink` / `--ink-dim` / `--ink-mute` | ink at 100 / 72 / 50% | cream at 100 / 76 / 52% | text |

### Accents

Fills are the same in both themes. Text needs two versions: readable on cream, bright again on dark paper.

| Role | Fill | Text on paper (light → dark) |
|---|---|---|
| pink — **the one accent**: the primary action, scores, "best", active tab, the brand dot, the logo's disc | `--accent #ff4d8f` | `--accent-t #bf1152 → #ff7fb0` |
| pink, quieted — a pink fill that must not compete with the primary (the パーティー button) | `--accent-soft #ffc9dd → #b83070`, hover `--accent-soft-h` | — |
| cyan — party codes, links, hit bars, focus ring | `--cyan #35d6f0` | `--cyan-t #0b7f96 → #35d6f0` |
| green / red — ok / error, and off-pitch on a screen (sharp, missed trace) | `--green #5ef07a`, `--red #ff5d5d` | `--green-t`, `--red-t` |

`--accent-soft` is its own light/dark pair rather than a mix with the card: on dark paper the card is warm brown,
so anything mixed into it turns brown — and so does a pink that is merely *dark* (a 30%-lightness rose reads as
maroon next to warm ink). The dark value is therefore quieted by saturation, not by lightness: same magenta hue as
`--accent`, kept bright enough to stay pink.

The accent is named `--accent`, never `--pink`: it is a role, and the whole site follows it. Everything that acts,
scores or marks "best" reads `--accent`, `--accent-t` or `--lane-hit*`, so the palette has exactly one place to
change. (There is no glow token any more: with the dark stage gone, nothing glows.)
One saturated fill carries "act on this"; a second next to it only splits the eye.

Two exceptions, both deliberate: **the lasso** around the hero headline is drawn in `--rope` / `--rope-t`
(`#ffc64b`) because it is a rope, not the brand; and **party seat colours** come from the server
(`SEAT_COLOURS` in `server/routers/party.py`) and stay many-hued because they identify people.

### Lane

The note lane is a `<canvas>`, so it cannot use the tokens directly: `--lane-hit`, `--lane-hit-soft` (scored notes),
`--lane-live` / `--lane-wait` (notes still coming), `--lane-miss`, `--lane-off`, `--lane-grid`, `--lane-label`,
`--lane-cursor`, `--lane-high` / `--lane-low` are plain `rgba()` literals that `play.js` reads off `:root` and hands
to the canvas. Canvas cannot parse `color-mix()` **or** `light-dark()`, so the dark values are spelled out twice —
under `prefers-color-scheme: dark` and under `[data-theme="dark"]` — and `play.js` re-reads them when either
changes (`karaoke:palette` from the menu, a `matchMedia` listener for the system). Since the lane is on paper, the
light values are the readable `-t` colours, not the bright fills. The landing's drawn lane uses the same tokens.

### Screen

There is no separate dark family any more. What used to be `--screen*` now maps onto paper: `--panel` for the card,
`--panel-2` for an inset (the lane plate, a chart, the party strip), the new `--panel-3` for a chip inside a panel,
`--line-soft` for an inner rule, and `--ink` / `--ink-dim` / `--ink-mute` for text.

The consequence for accents: on paper an accent is **always its `-t` text version**. A score is `--accent-t`, a
combo is `--cyan-t`, a chart series is `--cyan-t`. Saturated fills (`--accent`, `--cyan`) stay for *fills* — a
button, a bar, a seat dot — and glows are gone with the dark: a halo on cream is mud. The one place a bright
fill still sits on black is text over the video (the ふりがな stamp), and that is outlined, not glowing.

### Stickers

`--sticker-1…6`: pastel yellow, cyan, lilac, green, white, peach (muted in dark). Only for the song menu on the landing
page, assigned by `nth-child(6n+k)`, each with a fixed small rotation (−2.5° … +1.8°).

### Type

Two families, both already loaded by every page:

| Use | Face | Size / weight |
|---|---|---|
| everything | **M PLUS Rounded 1c** | body **15px** / 400, labels 700, headings and buttons 800 |
| numbers that are *measured* — scores, codes, counters, times | **Fredoka 600** (`--font-num`, class `.readout`) | 16–96px, `tabular-nums`. Loaded at one weight, so every use is chunky without setting a weight; kana and kanji inside a readout fall through to the body face |
| landing hero | M PLUS Rounded 1c 800 | `clamp(40px, 5.4vw, 66px)`, line-height 1.04, tracking −.03em |
| section h2 (landing) | 800 | `clamp(26px, 3vw, 32px)`, sub-line 14px `--ink-mute` |
| furigana `rt` | inherits | `.62em`, weight 500, **the colour of the text it annotates** (`currentColor` at 76%), never a fixed ink — on a pink button the label is black, so the reading is black too. It is the point of the app, so it is sized to be read: `.5em` came out at 7px on body text. |

**Nothing under 12px, and hints are 13–13.5px.** Every line of Japanese carries furigana at `.66em`, so a 12px
hint is really an 8px reading — the annotation that is the whole point of the app becomes decoration. Small text
therefore has a floor: 12px for tracked labels, table heads and legends, 13–13.5px for anything that is a sentence.

Japanese leads everywhere. Never show a slash-pair "日本語 / english" as visible text.

### Shape

- **Outlines: 3px, `--line`, always.** Inner dividers are 2px `--line-soft`. Nothing is 1px.
- **Radii:** pills `999px` (buttons, chips, nav items), fields `12px`, cards `16px`, panels `18px`, dialogs `22px`,
  the landing hero stickers `14px`, thumbnails inside stickers `9px`.
- **Hard shadows, offset down-right, no blur**, scaled to the element: `2px` small buttons and list rows ·
  `3px` buttons and tiles · `4px` cards and panels · `6px` big landing panels · `8px` dialogs. Shadows never move
  on hover; the element does.
- **Buttons are pills**: paper fill, 3px outline, 3px shadow. Hover moves the button 1px into its shadow, `:active`
  all the way (shadow 0). `.primary` is accent with ink text, `.warn` accent outline and text (outlined, so it never
  competes with the primary), `.party` `--accent-soft` — pink, but a quieter pink than the active nav pill,
  because starting a party is an offer, not where you are — `.ghost` no outline/shadow,
  `.danger` red outline and text, `.small` 12px.
- **Inputs** are `--panel-2` with a 3px outline and 12px radius. Focus is a 3px cyan outline everywhere.
- **Sliders** are an inset 16px track with a 20px accent knob. WebKit hangs the knob off the *top* of the track's
  content box, so its vertical centring is `margin-top: (track content − knob) / 2` and nothing else — with a
  16px border-box track and 3px rules that is `-5px`. Get it wrong and the knob rides low.
- **Song cards** (`.song`) and **stickers** lift 3–4px on hover; stickers also straighten (`rotate(0)`).
- **Nav items** press like buttons: quiet at rest, hover pops the outline and a 3px shadow out of the page,
  `:active` pushes the pill into it.
- **Sliders** are paper: a 16px inset track with a 3px outline and an accent knob carrying a 2px shadow.

---

## 3. Components

| Component | Rule |
|---|---|
| Header `header.top` | paper, 3px bottom rule, sticky. Logo = app icon on an accent disc in a 3px ring + **カラオケ.ロデオ** in 800, the dot in `--accent-t`. Nav items are pills that press like buttons; the active one is accent with a 2px shadow. On phones the row is ☰ · logo · avatar and the nav becomes a panel that **rolls down** out of the header (max-height with its rule and shadow growing in) — like the party strip, it never just appears. |
| Profile menu `.usermenu` | the avatar is the button (`.userbtn`, accent while open) and everything personal drops out of it: プロフィール · ふりがな · ダークモード · ログアウト. The panel grows out of nothing at the corner of the button (`scale(0) → scale(1)`, origin top right) and collapses back into it — never a shrunken copy of itself hanging in mid-air — while the rows slide in one after the other. Nothing fades. Each setting is a `.sw` switch, accent when on. **A guest gets the same button in the same place** (ゲ / ゲスト / ▾, `guestMenu`), holding the same ふりがな and ダークモード switches plus ログイン: playing without an account must not change the shape of the bar. Only a stranger who is neither signed in nor a guest has no menu, so あ and 🌙/☀️ stand in the nav as ghost buttons instead — on the landing too. |
| Party strip | an inset paper band under the header: accent label, cyan code, outlined member chips carrying seat colours, 🎤 on the singer. It **rolls down** out of the header when a party starts and rolls back up when it ends (`.partystrip` is a one-row grid animating `0fr → 1fr`, the inner row clips) — it never simply appears. |
| Panel `.panel` | white card, 4px shadow, 18px padding. |
| Song card `.song` | thumbnail is a still with a 3px rule below and **nothing written on it**, title 800 with ruby, artist dim, meta row with `N音 · m:ss` and the 1位 avatar + their best in accent readout — the card carries one score, in the meta row. In a catalogue grid (`.cards`) the card carries the landing page's sticker pastel, by `nth-child(6n+k)` — same six colours, same order, no rotation. |
| Landing sticker `.sticker` | same content as a song card on a pastel, rotated; tap = pick the song. |
| Stat tile `.tile` | label 11px tracked, readout value in `--accent-t`. |
| Chart `.chart`, calendar `.calwrap` | inset paper (`--panel-2`) in a 3px outline. Axis text `--ink-dim`, series `--cyan-t` at 3px, personal best `--accent-t`, calendar levels a light cyan ramp. |
| Score panel, lane, result dialog | paper cards with 4px shadows. Score in the readout face in `--accent-t`, no glow. The lane is a canvas on `--panel-2`; the video box is the only black thing on the page. |
| Table | uppercase 11px headers, 2px soft dividers, your own row tinted accent 22%. |
| Dialog | paper, 22px radius, 8px shadow, backdrop `rgba(21,18,12,.55)`, popped open from `scale(.6)`. **`confirm()` is never the browser's**: `confirmDialog()` in `common.js` draws the same paper card with やめる / the action, resolves a promise, and Esc answers "no" — a system dialog is a different app appearing on top of this one. |
| Message `.msg` | paper chip with 3px outline; `.ok` green text/outline, `.err` red. |
| Status pill `.pill` | 2px outline chip for song status (published green, labeling accent, processing cyan, failed red). |
| Footer | 3px top rule, `--ink-mute`, 12px 700. |

Motion: only what answers an action (button press, sticker lift, dialog open) plus the landing's ticker,
all off under `prefers-reduced-motion`.

**Nothing fades.** This is a toy console, and things on a console slide, pop, wipe, snap open and snap shut; they do
not dissolve. So: no `opacity` transitions and no opacity keyframes anywhere — the profile menu pops and its rows
slide, the toast rides up off the bottom edge, the ふりがな stamp slams down and is yanked away at `scale(0)`.
Opacity as a *state* (a disabled button at .45) is fine; opacity as a *motion* is not.

Between pages: the app is multi-page, so `@view-transition { navigation: auto }` in `common.css` makes a navigation
a **wipe** — the new page is pulled down over the old one (`page-wipe`, a `clip-path` inset), which holds still
underneath; `header.top` / `.partystrip` carry `view-transition-name`s and are swapped instantly, so the bar never
moves or flickers. `mix-blend-mode: normal` on the snapshots is load-bearing: the UA cross-fade blends them with
`plus-lighter`, which would blow two opaque pages out to white. Browsers without cross-document view transitions
simply navigate.

The other half of that smoothness is not CSS: the header used to wait for `/api/me` on every page, so each
navigation showed a bare page and then snapped a header onto it. `getMe` now keeps the last answer in
`sessionStorage` (`karaoke_me`) and `renderNav` draws from it immediately, then repaints only if the server
disagrees (`sameUser`). It is a drawing hint, never a permission: every endpoint still checks the cookie.

---

## 4. Pages

- `/` — logged out: the landing (`welcome.html`). Logged in: the catalogue (うたう). `/welcome` always shows the
  landing, `/songs` always the catalogue.
- うたう · きろく · ランキング · プロフィール · について · 管理 are **views of one document**, `app.html`: the router in
  `static/app.js` fetches a view's data (`static/view-*.js`, `load()`) while the current view stays on screen, then
  swaps `<main>` inside a view transition, so the wipe always reveals a finished page and the header is built once.
  Per-view CSS lives in `static/views.css`, scoped by the class the router puts on `<main>` (`.v-stats` …). Play,
  login, party join and the labeler are documents of their own; a link into or out of them is an ordinary navigation.
- Every visible string on the landing carries its English as a tooltip (`<span class="sub">`, or a `title` where
  the text is generated) — it is the page strangers read, so nothing there is untranslated.
- Landing sections, in order: header · hero (headline with lasso, one accent CTA 「歌いはじめる」; a four-song
  sticker menu — a taste of the catalogue, not the catalogue; the explanation that used to sit here lives on について) ·
  the ticker · あそびかた (a drawing of the real stage + three steps + result card) · きろく (four cards mirroring
  the stats page) · ランキング (総合 / 曲別 + live みんなの最近) · パーティー (steps, strip, phone mock) · about ·
  footer. Clicking a sticker opens the login dialog with the song kept as `next` and offers 「ゲストとして続ける」 (see below).
- The labeling tool (`label.html`) keeps its own dark, dense styling: it is an instrument over video frames, not a
  page anyone browses.

---

### Guest mode

Someone who taps a song without an account is offered **「ゲストとして続ける」** — on the landing's login dialog and on
`/login` whenever `next` points at `/play`. It sets `karaoke_guest` in that browser (`isGuest()` / `setGuest()` in
`common.js`) and goes straight to the song: no nickname, no account, no server state.

A guest plays exactly as anyone else — the note map and the video are open to anyone who may see the song, which is
why `song_map` and `media` take `current_user` rather than `require_user` — but there is nothing to save a play to,
so `finish()` skips the submit, the score panel says 「ゲスト：点数は保存されません」 and the result dialog offers the
login that would have kept it. The top bar is the signed-in one with ゲスト in place of a name (see the menu row
above), and the same note sits in the menu's head — a guest is a mode of the app, not a stripped-down version of it. Signing in clears the flag (`getMe`). Party guests are a different thing: they are
real members of a party with their own seat and colour, and their scores *are* kept.

## 5. Copy rules

- Describe what the code does. No invented numbers, no features that don't exist.
- Japanese owns every label; English lives in tooltips (`<span class="sub">`), except the hero wink.
- Buttons say what happens (`部屋をつくる`, `リンクを送る`, `コードでログイン`). The same action keeps the same name
  through the whole flow.
- Measured numbers (scores, codes, note counts, durations) are always in the readout face (`.readout`).

---

## 6. Accessibility floor

- Body text ≥ 4.5:1 in both themes (that is why accents have `-t` text versions).
- Furigana never replaces text; it annotates it. `.noruby` on anything whose reading is user data.
- Visible focus (3px cyan), buttons ≥ 32px tall, `prefers-reduced-motion` respected, `[hidden]` always wins.
- Layout is fluid: `minmax()` / `auto-fit` grids, wrapping headers; the page never scrolls sideways.
