// 界面语言（CR-4）：一次只显示一种语言，默认中文。界面文字全部在语言包 i18n/zh.json、i18n/en.json 里，两份的键一样。
// 不翻译：数字、型号、规则编号、文件名、Rev 和版本号、单位，以及用户录入的内容。
import en from "./i18n/en.json";
import zh from "./i18n/zh.json";

export type Lang = "zh" | "en";
type Pack = { [key: string]: string | Pack };

const PACKS: Record<Lang, Pack> = { zh, en };
const STORE = "avp.lang"; // 登录前用这台电脑上次的语言；登录后按用户保存的设置

function stored(): Lang {
  try {
    return localStorage.getItem(STORE) === "en" ? "en" : "zh";
  } catch {
    return "zh";
  }
}

let current: Lang = stored();

export function lang(): Lang {
  return current;
}

export function setLang(l: Lang) {
  current = l;
  document.documentElement.lang = l === "zh" ? "zh-CN" : "en";
  try {
    localStorage.setItem(STORE, l);
  } catch {
    // 浏览器不让存时，只是下次登录前回到默认中文
  }
}

function lookup(pack: Pack, key: string): string | undefined {
  let node: string | Pack | undefined = pack;
  for (const part of key.split(".")) node = typeof node === "object" ? node[part] : undefined;
  return typeof node === "string" ? node : undefined;
}

export function t(key: string, vars?: Record<string, string | number>): string {
  const text = lookup(PACKS[current], key) ?? key;
  return vars ? text.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : text;
}

// 规则编号、选项代码等按名字取（没有的原样显示）
export function tOr(key: string, fallback: string): string {
  return lookup(PACKS[current], key) ?? fallback;
}
