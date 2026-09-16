# Brand assets

Artwork for the `fuse_energy` domain, sized to the
[home-assistant/brands](https://github.com/home-assistant/brands) specification
so it can be submitted without reprocessing.

| File | Size | Spec |
| --- | --- | --- |
| `fuse_energy/icon.png` | 256×256 | icons must be 1:1 |
| `fuse_energy/icon@2x.png` | 512×512 | hDPI icon |
| `fuse_energy/logo.png` | 653×256 | logo, shortest side 128–256 |
| `fuse_energy/logo@2x.png` | 1306×512 | hDPI logo, shortest side 256–512 |
| `fuse_energy/dark_logo.png` | 653×256 | wordmark lightened for dark themes |
| `fuse_energy/dark_logo@2x.png` | 1306×512 | hDPI dark logo |

All are PNG with transparency and trimmed of surrounding whitespace. The icon is
the square mark with the wordmark cut away; the logo is the full lockup.

A `dark_` pair exists because the wordmark is near-black, which vanishes against
Home Assistant's default dark theme. The icon needs no dark variant — the orange
field reads on both.

## Before submitting these upstream

The brands repository states:

> Custom integrations must not use Home Assistant branded images, as this might
> confuse the end-user into thinking that the integration is an internal/official
> integration.

The mark in this artwork is Home Assistant's house-and-circuit logo. As it
stands, a pull request adding these to `home-assistant/brands` should be
expected to fail review on that rule, and the confusion it guards against is
real: this integration is unofficial and unaffiliated with both Fuse and Home
Assistant.

Artwork built on Fuse Energy's own mark would not have that problem, and is what
every other supplier integration uses.

Nothing depends on this either way. Until a domain is registered in the brands
repository, Home Assistant shows a generic placeholder, which is the current
behaviour — see the `ignore: brands` note in `.github/workflows/validate.yml`.
