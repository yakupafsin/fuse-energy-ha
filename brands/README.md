# Brand assets

Source artwork and the script that resizes it. The images it produces live in
[`custom_components/fuse_energy/brand/`](../custom_components/fuse_energy/brand)
and ship with the integration.

## Why they ship with the integration

Home Assistant 2026.3 added the
[Brands Proxy API](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api).
A custom integration now supplies its own images from a `brand/` directory
inside the integration package, and those take priority over the brands CDN. No
manifest key, and no pull request to `home-assistant/brands` — that repository
no longer accepts additions for custom components.

## Files

| Output | Size |
| --- | --- |
| `brand/icon.png` | 256×256 |
| `brand/icon@2x.png` | 512×512 |
| `brand/logo.png` | 747×256 |
| `brand/logo@2x.png` | 1494×512 |
| `brand/dark_logo.png` | 747×256 |
| `brand/dark_logo@2x.png` | 1494×512 |

Sizes follow the brands specification — icons square, logos 128–256px on the
shortest side and 256–512px for hDPI — which the proxy API does not require but
which keeps the images correct at the sizes Home Assistant renders them.

A `dark_` pair exists because the wordmark is near-black and would otherwise
disappear against Home Assistant's default dark theme. The icon needs no dark
variant — the orange field reads on both.

## Regenerating

Do not edit the outputs by hand. They are resized from `brands/src/`:

| Source | Used for |
| --- | --- |
| `src/mark.png` | `icon.png`, `icon@2x.png` — square, transparent |
| `src/lockup.png` | `logo.png`, `logo@2x.png` — landscape mark + wordmark |
| `src/lockup-dark.png` | `dark_logo.png`, `dark_logo@2x.png` |

```sh
python3 brands/make_assets.py
```

Requires Pillow. The script only resizes: no cropping, colour detection or
recolouring, so replacing the artwork means dropping in new source files at
whatever resolution you have.

`src/lockup-dark.png` was produced from `src/lockup.png` by lightening the
wordmark, and is kept as a source rather than regenerated so a hand-authored
dark variant can simply replace it.
