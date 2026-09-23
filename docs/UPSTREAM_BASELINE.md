# Upstream baseline

- Source: `https://github.com/open-webui/open-webui.git`
- Upstream version: `0.11.4`
- Upstream commit: `8bd8b4fac5e059578ac0c74b3c18d11139f88b7d`
- Local development branch: `tater-chat`
- Required Node range: `>=18.13.0 <=22.x.x`
- Selected Node version: `22`
- Required Python range: `>=3.11, <3.13`
- Selected Python version: `3.11`

## Baseline verification

Frontend dependencies install successfully with Node 22 using `npm ci`.

The untouched upstream frontend production build succeeds with:

```sh
NODE_OPTIONS=--max-old-space-size=8192 npm run build
```

The same build exhausts V8's default heap near 4 GB after transforming 6,366
modules. This is inherited build-cost debt. Keep the larger heap for baseline
verification until feature removal brings the bundle down enough to build with
the default limit.

The upstream production build also downloads a large ignored `static/pyodide/`
runtime. TaterChat no longer installs or prepares Pyodide: host-side execution
is provided by the bundled local terminal runtime instead.

After the first frontend cleanup slice, the production build succeeds on the
default Node 22 heap and transforms 6,078 modules. The upstream comparison was
6,366 modules and required the 8 GB heap override.

The untouched upstream `npm run check` baseline is not clean. On this checkout it reports:

- 7,001 errors;
- 198 warnings;
- 344 affected files.

The largest groups observed are inherited implicit-`any` JavaScript diagnostics and Svelte store typing diagnostics. These failures predate TaterChat changes and are not an appropriate all-at-once cleanup target. New TaterChat modules should receive focused tests and clean targeted checks.

The dependency installation reports 34 audit findings (2 low, 13 moderate, 18 high, and 1 critical). Do not apply `npm audit fix --force`; dependency removal and deliberate upgrades during the stripping work should reduce this surface without uncontrolled breaking changes.

The configured frontend test command exits successfully but currently finds no
test files. Focused tests must be added around every new TaterChat integration
instead of treating that empty result as coverage.

The system `python3` is Python 3.9.6 and is not compatible with this checkout. `/opt/homebrew/bin/python3.11` is available for the backend environment.
