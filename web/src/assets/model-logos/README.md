# Model logos and chart colors

Downloaded on 2026-10-18. These marks identify model families; harness names remain
separate. Logos retain their supplied geometry and colors. Small symbols replace
full wordmarks where available, so they remain legible in table rows.

| Local asset | Source |
| --- | --- |
| `cursor.svg` | [Official Cursor favicon](https://cursor.com/marketing-static/favicon-light.svg), linked from its [brand site](https://cursor.com/brand) |
| `zai.svg` | [Official Z.ai favicon](https://z-cdn.chatglm.cn/z-ai/static/logo.svg), linked from [Z.ai](https://chat.z.ai/) |
| `anthropic.svg` | [Lobe Icons Claude symbol](https://github.com/lobehub/lobe-icons/blob/master/packages/static-svg/icons/claude-color.svg) |
| `openai.svg` | [Lobe Icons OpenAI](https://github.com/lobehub/lobe-icons/blob/master/packages/static-svg/icons/openai.svg) |
| `google.svg` | [Lobe Icons Gemini](https://github.com/lobehub/lobe-icons/blob/master/packages/static-svg/icons/gemini-color.svg) |
| `xai.svg` | [Lobe Icons Grok](https://github.com/lobehub/lobe-icons/blob/master/packages/static-svg/icons/grok.svg) |
| `moonshot.svg` | [Lobe Icons Kimi](https://github.com/lobehub/lobe-icons/blob/master/packages/static-svg/icons/kimi-color.svg) |
| `deepseek.svg` | [Lobe Icons DeepSeek symbol](https://github.com/lobehub/lobe-icons/blob/master/packages/static-svg/icons/deepseek-color.svg) |
| `minimax.svg` | [Lobe Icons MiniMax](https://github.com/lobehub/lobe-icons/blob/master/packages/static-svg/icons/minimax-color.svg) |
| `qwen.svg` | [Lobe Icons Qwen](https://github.com/lobehub/lobe-icons/blob/master/packages/static-svg/icons/qwen-color.svg) |
| `xiaomi.svg` | [Xiaomi logo (2021)](https://commons.wikimedia.org/wiki/File:Xiaomi_logo_(2021-).svg), the orange app-icon mark; MiMo has no standalone color symbol |

Lobe Icons files are community copies, distributed under the accompanying
`LICENSE.lobe-icons`. The copy in `web/public/LICENSE.lobe-icons` also ships
with the deployed site. Trademarks remain with their respective owners. See the
[OpenAI](https://openai.com/brand/), [Cursor](https://cursor.com/brand), and
[Grok](https://x.ai/legal/brand-guidelines) guidelines when replacing assets.

The `--vendor-*` tokens in `app.css` are GM-Bench chart colors, adjusted for light
and dark surfaces. They are not a claim to reproduce every company's palette:

- MiMo orange is based on the `#ff6700` accent in its
  [official V2 Flash page](https://mimo.xiaomi.com/mimo-v2-flash).
- Claude terracotta follows Anthropic's published `#d97757`
  [brand accent](https://github.com/anthropics/skills/blob/main/skills/brand-guidelines/SKILL.md).
- Gemini sky blue, Kimi azure, DeepSeek periwinkle, and Qwen violet preserve the
  sourced color families while separating nearby chart marks. Qwen's current
  website also uses blue; its violet logo is the reference here.
- MiniMax uses the pink end of its warm gradient; Grok and OpenAI use neutrals.
- Cursor cyan and Z.ai teal are deliberate editorial chart accents, retained to
  avoid adding more neutral or blue series. The logos remain unchanged.

Model names and harness labels remain visible so identification never depends on
color alone. Scripted baselines keep their existing neutral/red treatment.
