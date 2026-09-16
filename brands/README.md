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

Do not edit these by hand. Drop in new artwork — a landscape lockup with the
square mark on the left and the wordmark to the right, transparent background —
and run:

```sh
python3 brands/make_assets.py path/to/lockup.png
```

Every file above is derived from that one source, so the sizes stay correct and
the icon and logo cannot drift apart. Requires Pillow.

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
