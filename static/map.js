document.querySelectorAll(".load-map").forEach((button) => {
  button.addEventListener("click", () => {
    const container = button.parentElement.querySelector(".map-container");
    if (!container || container.firstChild) return;

    const url = new URL("https://maps.google.com/maps");
    url.searchParams.set("q", button.dataset.mapQuery);
    url.searchParams.set("output", "embed");

    const frame = document.createElement("iframe");
    frame.src = url.toString();
    frame.title = `Karte zu ${button.dataset.mapQuery}`;
    frame.referrerPolicy = "no-referrer";
    frame.setAttribute("allowfullscreen", "");
    container.append(frame);
    button.hidden = true;
    frame.focus();
  });
});
