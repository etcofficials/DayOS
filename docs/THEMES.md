# Theme system

DayOS has five themes, chosen in **Settings → Appearance** (or the quick toggle on
Today). Switching is live, with a short cross-fade, and never touches your records.

| Id | Name | Mode | Character |
|---|---|---|---|
| `paper` (default) | Paper & Sage | light | Warm ivory paper, muted sage and soft botanical art |
| `midnight` | Midnight Focus | dark | Deep charcoal with muted sage; a quiet dark workspace |
| `zen` | Zen Minimal | light | Warm white, stone grey and a soft ink blue; spacious and typographic |
| `aurora` | Aurora | dark | Deep blue-black with restrained violet and blue |
| `espresso` | Espresso | dark | Warm cocoa and wood tones, cream type and muted amber |

`system` follows Windows: light uses Paper & Sage, dark uses Midnight Focus. The v1 names
`light` and `dark` still work, and old settings are migrated to `paper` and `midnight`.

## How it works

* `src/ui/themes.py` defines each `Theme` with the following parts:
  * colour **tokens** (bg, surface, elevated, text, text2, text3, accent, accent_soft, primary, danger …);
  * **fonts** (display, heading, body, numeric, mono);
  * **shape** (radii, shadow and hover lift);
  * **art** colours (the SVG illustrations are recoloured per theme);
  * optional **accent** variants.
* `complete_tokens()` derives semantic tokens that a theme doesn't set explicitly, such as hover, pressed, track, progress, nav pill, focus, selection and banner. Widgets use only these semantic names.
* `src/ui/theme.py` (`ThemeManager`) resolves the preference, applies the accent and text size (90 %, 100 %, 110 % or 125 %), and builds one application stylesheet from the tokens. It emits `changed` so painted widgets and icons re-render.
* Preferences: `theme`, `theme.accents` (per-theme accent), `font_scale` and `reduce_motion`.

## Guarantees (tested in `tests/test_themes.py`)

* Every theme defines the same token set.
* Text reaches a contrast ratio of at least 4.5:1 on its backgrounds, and text on accent buttons at least 3:1, in every theme and every accent variant.
* Theme artwork exists for every theme.
* Switching is live and persists across restarts. Invalid values are rejected.

## Motion

Animations are short (150–300 ms): page cross-fades, the gliding sidebar pill, card lift
on hover, checks drawing themselves, and dialog fades. **Reduce motion** (Settings →
Appearance) turns them off. DayOS also respects Windows' "Show animations" setting.
