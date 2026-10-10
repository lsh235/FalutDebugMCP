let language = new URLSearchParams(location.search).get("lang") === "ko" ? "ko" : "en";
function translate() {
  document.documentElement.lang = language;
  for (const element of document.querySelectorAll("[data-en]")) element.textContent = element.dataset[language];
  for (const link of document.querySelectorAll("[data-demo]")) link.href = "reports/" + link.dataset.demo + "/report" + (language === "ko" ? ".ko" : "") + ".html";
  document.querySelector("#language").textContent = language === "en" ? "한국어" : "English";
  document.querySelector("#language").setAttribute("aria-label", language === "en" ? "한국어로 전환" : "Switch to English");
  document.querySelector("#copy-status").textContent = "";
}
document.querySelector("#language").addEventListener("click", () => {
  language = language === "en" ? "ko" : "en";
  const url = new URL(location.href); url.searchParams.set("lang", language);
  history.replaceState(null, "", url); translate();
});
document.querySelector("#copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(document.querySelector("#quick-command").textContent);
    document.querySelector("#copy-status").textContent = language === "en" ? "Copied" : "복사했습니다";
  } catch {
    document.querySelector("#copy-status").textContent = language === "en" ? "Select and copy the command above." : "위 명령을 선택해 복사하세요.";
  }
});
translate();
