# Templates

Drop PNG crops of the in-game UI here. They are matched with OpenCV
`matchTemplate` (grayscale, normalized cross-correlation), so capture them at
the same resolution / UI scale you play at (1920x1080 @ 100%) and crop tightly
around the icon without resizing.

| File          | What to crop                                            |
|---------------|---------------------------------------------------------|
| `bite.png`    | the "press Space" prompt that appears when a fish bites (optional; without it the bot uses bright-pixel detection) |
| `w.png`       | the W key icon in the WASD minigame                     |
| `a.png`       | the A key icon                                          |
| `s.png`       | the S key icon                                          |
| `d.png`       | the D key icon                                          |
| `w_rev.png`   | the reversed/upside-down W icon (bot presses **S**)     |
| `a_rev.png`   | the reversed A icon (bot presses **D**)                 |
| `s_rev.png`   | the reversed S icon (bot presses **W**)                 |
| `d_rev.png`   | the reversed D icon (bot presses **A**)                 |

Capture workflow:

```bash
# save frames of the WASD area while you fish one round by hand
python -m bdo_fishing_bot.tools.calibrate burst --region wasd --seconds 60 --fps 5
# pick a frame that shows the key row, cut it into single icons
python -m bdo_fishing_bot.tools.calibrate split-keys captures/wasd_123456_000000.png
# rename captures/keys/key_N.png -> templates/<name>.png, then verify
python -m bdo_fishing_bot.tools.calibrate analyze wasd captures/wasd_123456_000000.png --out check.png
```

The `*_rev.png` files are only needed once you have actually seen a reversed
icon; until then the bot simply presses the keys it can recognise.
