# Hoteli brand: logo usage

Official logo files are in [`static/brand/`](../static/brand/). Use the SVGs wherever possible; the PNGs are for places that can't take vector files.

## The mark

A rounded teal square holding a white **H** made of two towers, with an amber **sun rising between them**: hospitality, a Kenyan sunrise and, read quickly, a friendly "**hi**". The same sun dots the *i* in the wordmark.

| File | Use it for |
| --- | --- |
| `hoteli-logo.svg` / `.png` | Default logo on white or light backgrounds |
| `hoteli-logo-light.svg` / `.png` | Dark backgrounds (white wordmark) |
| `hoteli-logo-tagline.svg`, `-tagline-light.svg` | With "Hotel management system" underneath, for headers, proposals and slides |
| `hoteli-logo-stacked.svg`, `-stacked-light.svg` | Square spaces: posters, splash screens, merchandise |
| `hoteli-logo-mono.svg` | Single-colour print, stamps and fax |
| `hoteli-mark.svg`, `hoteli-mark-512.png` | Icon on its own (avatars, small spaces) |
| `hoteli-mark-white.svg` | Icon on busy or coloured backgrounds (white tile) |
| `hoteli-mark-mono.svg` | Single-colour icon |
| `hoteli-app-icon.svg`, `icon-192.png`, `icon-512.png`, `apple-touch-icon.png` | App and home-screen icons (full-bleed: the platform rounds the corners) |
| `favicon.svg`, `favicon.ico`, `favicon-16/32/48.png` | Browser tabs |
| `social-preview.png` (1280×640) | GitHub *Settings → General → Social preview*, link previews |

## Colours

| Name | Hex | Role |
| --- | --- | --- |
| Hoteli Teal | `#0f766e` | Primary colour, the mark |
| Teal Light | `#14b8a6` | Gradient start |
| Teal Deep | `#115e59` | Gradient end, hover states |
| Sunrise Amber | `#f59e0b` | The sun, small accents only |
| Ink | `#0f172a` | Wordmark, text, dark backgrounds |

Wordmark typeface: **Poppins SemiBold**, converted to outlines (SIL Open Font License), so the logo never depends on installed fonts.

## Do

- Leave clear space around the logo of at least the height of the sun (about a quarter of the mark's height).
- Keep the mark at least 16 px (screen) or 6 mm (print) tall, and the full logo at least 24 px tall.
- Use the light version on dark or photographic backgrounds.

## Don't

- Stretch, rotate, outline or add shadows to the logo.
- Recolour the mark or the sun, except to use the provided single-colour files.
- Rebuild the wordmark in another font or change the spacing.
- Place the colour mark on a teal background (use `hoteli-mark-white.svg`).

## Editing

The logos are generated, so edit the script instead of the SVGs:

```bash
python branding/build_logos.py static/brand
```

```bash
node branding/export_png.js
```

`build_logos.py` needs `pip install fonttools` and the Poppins 500 and 600 TTF files in `branding/fonts/` (`Poppins-500.ttf`, `Poppins-600.ttf`), available from Google Fonts. `export_png.js` renders the PNGs into `static/brand/` with Playwright. (The `favicon.ico` bundles the 16, 32 and 48 px PNGs.)
