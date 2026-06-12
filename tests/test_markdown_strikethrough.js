/**
 * Regression: agent chat must not treat single-tilde approximations as strikethrough.
 * Run: node tests/test_markdown_strikethrough.js
 */
const fs = require("fs");
const path = require("path");

const markedPath = path.join(__dirname, "../frontend/js/vendor/marked.min.js");
const markedSrc = fs.readFileSync(markedPath, "utf8");
const fakeGlobal = { exports: {} };
const fn = new Function(
  "exports",
  "module",
  "globalThis",
  `${markedSrc}\nreturn globalThis.marked || exports;`
);
const marked = fn(fakeGlobal.exports, { exports: fakeGlobal.exports }, fakeGlobal);

marked.use({ gfm: true, breaks: true, pedantic: false });
marked.use({
  tokenizer: {
    del(src) {
      const match = /^~~(?=\S)([^\n]*?\S)~~/.exec(src);
      if (!match) return;
      return {
        type: "del",
        raw: match[0],
        text: match[1],
        tokens: this.lexer.inlineTokens(match[1]),
      };
    },
  },
});

function assert(condition, message) {
  if (!condition) {
    console.error("FAIL:", message);
    process.exit(1);
  }
}

const approx = "Revenue is ~$150B (~82% of DC) vs ~$87B prior year.";
const approxHtml = marked.parse(approx);
assert(!approxHtml.includes("<del>"), "single-tilde approximations must not render as <del>");

const intentional = "~~draft outline~~\n\nFinal answer here.";
const intentionalHtml = marked.parse(intentional);
assert(intentionalHtml.includes("<del>draft outline</del>"), "~~double tilde~~ should still strikethrough");

const singleTilde = "~roughly~ five items";
const singleHtml = marked.parse(singleTilde);
assert(!singleHtml.includes("<del>"), "single-tilde ~word~ must not strikethrough");

console.log("OK: markdown strikethrough regression tests passed");
