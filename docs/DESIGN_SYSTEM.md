# 宇宙第一工作台 Design System

## 方向

Flat productivity UI：安静、清晰、内容优先。参考 Apple 的克制、Linear 的精确和 Notion 的编辑感，但不复制任何产品。禁止把所有区域做成卡片、禁止满屏渐变/毛玻璃/Glow、禁止用 Emoji 充当结构图标。

## Tokens

```css
:root {
  --color-background: #f0fdfa;
  --color-surface: #ffffff;
  --color-surface-subtle: #e8f1f4;
  --color-surface-elevated: #ffffff;
  --color-foreground: #134e4a;
  --color-foreground-secondary: #475569;
  --color-foreground-muted: #64748b;
  --color-border: #99f6e4;
  --color-divider: #d7e9e7;
  --color-primary: #0d9488;
  --color-primary-hover: #0f766e;
  --color-primary-active: #115e59;
  --color-accent: #ea580c;
  --color-success: #15803d;
  --color-warning: #b45309;
  --color-danger: #dc2626;
  --color-info: #2563eb;
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-full: 999px;
  --shadow-sm: 0 1px 2px rgb(15 23 42 / 0.06);
  --shadow-md: 0 6px 20px rgb(15 23 42 / 0.10);
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-5: 20px; --space-6: 24px; --space-8: 32px; --space-10: 40px;
  --space-12: 48px; --space-16: 64px;
  --motion-fast: 150ms; --motion-normal: 200ms;
}
```

## Typography

Inter/system sans；中文使用系统 sans-serif。Display 32/40 700；H1 28/36 700；H2 22/30 650；H3 17/24 650；Body 16/26 400；Body small 14/22；Label 13/20 600；Caption 12/18。长标题使用 `text-wrap: balance`，数字列使用 `font-variant-numeric: tabular-nums`。

## 组件规则

- 每屏一个 Primary action；Secondary 使用描边或低强调按钮。
- Button / input / card 使用统一 radius，不使用超大圆角伪装高级感。
- 交互目标最小 44×44px；`:focus-visible` 使用 2px 高对比 ring。
- Modal / popover 才允许有限阴影和背景模糊；普通内容保持稳定不透明。
- 状态必须同时有文字/图标和颜色，不依赖颜色单独传达含义。
- 选题卡使用“标题 → 理由 → 指标 → 操作”顺序；证据和算法说明放在折叠详情。

## 响应式

Desktop 使用双栏 Split View；768px 以下改为单列，先助手后产物；390px 以下隐藏低优先级元数据，保留当前步骤、输入、主操作和错误修复入口。禁止横向滚动，固定底栏必须有内容 inset。

