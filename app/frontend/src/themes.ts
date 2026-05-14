export const UI_THEMES = [
  {
    id: "black_gray",
    name: "\u9ed1\u4e0e\u7070",
    description: "\u9ad8\u7ea7\u7070\u3001\u7c73\u767d\u3001\u9ed1\u4e0e\u51b7\u7070\u7684\u89e3\u6784\u5f0f\u7f16\u8f91\u754c\u9762\u3002",
    colors: ["#f6f3eb", "#d9dedb", "#111314", "#65716d"]
  },
  {
    id: "klee_bomb",
    name: "\u8e66\u8e66\u70b8\u5f39\uff01",
    description:
      "\u539f\u7248\u53ef\u8389\u3001\u8e66\u8e66\u70b8\u5f39\u3001\u8f70\u8f70\u706b\u82b1\u548c\u56db\u53f6\u8349\u62fc\u8d34\u7ec4\u6210\u7684\u81ea\u7531\u7ae5\u5fc3\u4e3b\u9898\u3002",
    colors: ["#fff3df", "#c63d32", "#f08a38", "#ffbf4d", "#4f9b63"]
  }
] as const;

export type UiThemeId = (typeof UI_THEMES)[number]["id"];

export const DEFAULT_THEME: UiThemeId = "black_gray";

export function isUiThemeId(value: string | null): value is UiThemeId {
  return UI_THEMES.some((themeOption) => themeOption.id === value);
}
