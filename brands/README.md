# Brand assets

Artwork for the `fuse_energy` domain, sized to the
[home-assistant/brands](https://github.com/home-assistant/brands) specification
so it can be submitted without reprocessing.

| File | Size | Spec |
| --- | --- | --- |
| `fuse_energy/icon.png` | 256×256 | icons must be 1:1 |
| `fuse_energy/icon@2x.png` | 512×512 | hDPI icon |
| `fuse_energy/logo.png` | 747×256 | logo, shortest side 128–256 |
| `fuse_energy/logo@2x.png` | 1494×512 | hDPI logo, shortest side 256–512 |
| `fuse_energy/dark_logo.png` | 747×256 | wordmark lightened for dark themes |
| `fuse_energy/dark_logo@2x.png` | 1494×512 | hDPI dark logo |

All are PNG with transparency and trimmed of surrounding whitespace. The icon is
the square mark with the wordmark cut away, padded to 1:1 rather than stretched,
so the mark keeps its proportions.

A `dark_` pair exists because the wordmark is near-black and would otherwise
disappear against Home Assistant's default dark theme. The icon needs no dark
variant — the orange field reads on both.

## Regenerating

Do not edit the files above by hand — they are resized from the artwork in
`brands/src/`:

| Source | Used for |
| --- | --- |
| `src/mark.png` | `icon.png`, `icon@2x.png` — square, transparent |
| `src/lockup.png` | `logo.png`, `logo@2x.png` — landscape mark + wordmark |
| `src/lockup-dark.png` | `dark_logo.png`, `dark_logo@2x.png` |

```sh
python3 brands/make_assets.py
```

Requires Pillow. The script only resizes: it does no cropping, colour detection
or recolouring, so replacing the artwork is a matter of dropping in new source
files at whatever resolution you have. An earlier version derived all six
outputs from a single flattened lockup by finding the mark by colour — that
worked for exactly one image and would have silently mis-cropped a redraw at a
different scale or hue.

`src/lockup-dark.png` was produced from `src/lockup.png` by lightening the
wordmark, and is kept as a source rather than regenerated so that a hand-authored
dark variant can simply replace it.

## Submitting upstream

The brands repository states:

> Custom integrations must not use Home Assistant branded images, as this might
> confuse the end-user into thinking that the integration is an internal/official
> integration.

The current artwork puts a **fuse** inside the house, not Home Assistant's
house-and-circuit mark, and uses orange rather than Home Assistant's blue — so
it is the project's own mark, not a recolour of theirs. An earlier draft did use
the circuit mark and was replaced for exactly this reason.

What remains shared is a house glyph in a rounded square, which is a common
idiom rather than anything exclusive. That is a judgement for the brands
reviewers to make, but the rule's actual concern — a user mistaking this for an
official integration — is not raised by a fuse symbol.

Nothing depends on this either way. Until a domain is registered in the brands
repository, Home Assistant shows a generic placeholder, which is the current
behaviour — see the `ignore: brands` note in `.github/workflows/validate.yml`,
which should be removed once a brands pull request is merged.
