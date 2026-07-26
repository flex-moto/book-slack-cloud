const TARGETS = {
  share: {
    host: "share.timescar.jp",
    secret: "TIMESCAR_COOKIE",
    urls: [
      "https://share.timescar.jp/",
      "https://share.timescar.jp/view/member/mypage.jsp",
      "https://share.timescar.jp/view/reserve/input.jsp",
    ],
  },
  timesclub: {
    host: "api.timesclub.jp",
    secret: "TIMESCAR_COOKIE_TIMESCLUB",
    urls: [
      "https://api.timesclub.jp/",
      "https://api.timesclub.jp/view/pc/tpLogin.jsp",
    ],
  },
};

const copyButtons = [...document.querySelectorAll(".copy-button")];
const status = document.querySelector("#status");

function setStatus(message, kind = "") {
  status.textContent = message;
  status.className = kind;
}

function isAllowedUrl(rawUrl) {
  try {
    const host = new URL(rawUrl).hostname;
    return Object.values(TARGETS).some((target) => target.host === host);
  } catch {
    return false;
  }
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0] ?? null;
}

async function initialize() {
  const tab = await getActiveTab();

  if (!tab?.url || !isAllowedUrl(tab.url)) {
    setStatus("タイムズカーへログインしたページで実行してください。", "error");
    return;
  }

  for (const button of copyButtons) {
    button.disabled = false;
  }
  setStatus("2つとも順番にコピーして、対応するSecretへ貼り付けてください。");
}

function cookieKey(cookie) {
  const partition = cookie.partitionKey?.topLevelSite ?? "";
  return [cookie.storeId, cookie.domain, cookie.path, cookie.name, partition].join("|");
}

async function getCookiesForTarget(target) {
  const byKey = new Map();
  for (const url of target.urls) {
    for (const cookie of await chrome.cookies.getAll({ url })) {
      byKey.set(cookieKey(cookie), cookie);
    }
  }
  return [...byKey.values()];
}

async function copyCookies(targetKey, button) {
  const target = TARGETS[targetKey];
  if (!target) return;

  button.disabled = true;
  setStatus(`${target.host} のCookieを取得しています…`);

  try {
    const cookies = await getCookiesForTarget(target);

    if (cookies.length === 0) {
      throw new Error(`${target.host} のCookieが見つかりません。ログイン状態を確認してください。`);
    }

    const headerString = cookies
      .sort((a, b) => b.path.length - a.path.length || a.name.localeCompare(b.name))
      .map(({ name, value }) => `${name}=${value}`)
      .join("; ");

    await navigator.clipboard.writeText(headerString);
    setStatus(`${target.secret} 用に${cookies.length}件をコピーしました。`, "success");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus(`コピーできませんでした: ${message}`, "error");
  } finally {
    button.disabled = false;
  }
}

for (const button of copyButtons) {
  button.addEventListener("click", () => copyCookies(button.dataset.target, button));
}
initialize().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  setStatus(`初期化できませんでした: ${message}`, "error");
});
