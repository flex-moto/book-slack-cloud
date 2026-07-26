const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function cookie(name, value, domain, cookiePath = "/") {
  return { name, value, domain, path: cookiePath, storeId: "0" };
}

async function main() {
  const buttons = ["share", "timesclub"].map((target) => ({
    dataset: { target },
    disabled: true,
    addEventListener(_event, callback) {
      this.click = callback;
    },
  }));
  const status = { textContent: "", className: "" };
  const requestedUrls = [];
  const clipboardWrites = [];
  const shared = cookie("JSESSIONID", "share-session", "share.timescar.jp");
  const responses = {
    "https://share.timescar.jp/": [shared],
    "https://share.timescar.jp/view/member/mypage.jsp": [
      shared,
      cookie("SECURITY_TOKEN", "token==", "share.timescar.jp", "/view"),
    ],
    "https://share.timescar.jp/view/reserve/input.jsp": [shared],
    "https://api.timesclub.jp/": [
      cookie("remember-me", "persistent", ".timesclub.jp"),
    ],
    "https://api.timesclub.jp/view/pc/tpLogin.jsp": [
      cookie("remember-me", "persistent", ".timesclub.jp"),
      cookie("JSESSIONID", "club-session", "api.timesclub.jp", "/view/pc"),
    ],
  };

  const context = vm.createContext({
    URL,
    document: {
      querySelector(selector) {
        assert.equal(selector, "#status");
        return status;
      },
      querySelectorAll(selector) {
        assert.equal(selector, ".copy-button");
        return buttons;
      },
    },
    chrome: {
      tabs: {
        async query() {
          return [{ url: "https://share.timescar.jp/view/member/mypage.jsp" }];
        },
      },
      cookies: {
        async getAll({ url }) {
          requestedUrls.push(url);
          return responses[url] ?? [];
        },
      },
    },
    navigator: {
      clipboard: {
        async writeText(value) {
          clipboardWrites.push(value);
        },
      },
    },
  });

  const scriptPath = path.join(__dirname, "..", "tools", "timescar-cookie-copier", "popup.js");
  vm.runInContext(fs.readFileSync(scriptPath, "utf8"), context);
  await new Promise(setImmediate);

  assert.deepEqual(buttons.map((button) => button.disabled), [false, false]);

  await buttons[0].click();
  assert.deepEqual(requestedUrls.slice(0, 3), Object.keys(responses).slice(0, 3));
  assert.equal(clipboardWrites[0], "SECURITY_TOKEN=token==; JSESSIONID=share-session");

  await buttons[1].click();
  assert.deepEqual(requestedUrls.slice(3), Object.keys(responses).slice(3));
  assert.equal(clipboardWrites[1], "JSESSIONID=club-session; remember-me=persistent");

  const manifestPath = path.join(
    __dirname,
    "..",
    "tools",
    "timescar-cookie-copier",
    "manifest.json",
  );
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  assert.deepEqual(manifest.host_permissions, [
    "https://share.timescar.jp/*",
    "https://api.timesclub.jp/*",
  ]);

  console.log("Cookie Copier tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
