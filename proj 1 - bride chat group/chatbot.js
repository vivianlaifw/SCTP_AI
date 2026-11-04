// chatbot.js: the chat box on your page.
// It shows the box, sends each question to the chatbot's server part (the api folder),
// and shows the answer, with the tools the agent used to find it.
// Put <div id="chatbot"></div> where the box should go, and <script src="chatbot.js"></script> before </body>.

(function () {
  const place = document.getElementById("chatbot");
  if (!place) {
    return;
  }

  // The box, the notice and the form. None of this holds anything a visitor typed.
  place.innerHTML =
    '<p class="chat-notice">You\'re chatting with an AI. Its answers can be wrong. ' +
    "It is for adult visitors. Please don't type personal details.</p>" +
    '<div class="chat-log" aria-live="polite"></div>' +
    '<form class="chat-form">' +
    '<label for="chat-question">Ask about this website</label>' +
    '<input id="chat-question" maxlength="500" autocomplete="off">' +
    '<button type="submit">Ask</button>' +
    "</form>";

  const style = document.createElement("style");
  style.textContent =
    "#chatbot { border: 2px solid #1f6f63; border-radius: 8px; padding: 12px; margin: 24px 0; }" +
    "#chatbot .chat-notice { font-size: 0.9em; margin-top: 0; }" +
    "#chatbot .chat-log { max-height: 320px; overflow-y: auto; }" +
    "#chatbot .chat-user { font-weight: bold; }" +
    "#chatbot .chat-steps { font-size: 0.85em; color: #555; margin-bottom: 0; }" +
    "#chatbot .chat-form { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }" +
    "#chatbot label { width: 100%; }" +
    "#chatbot input { flex: 1; min-width: 0; font-size: 1em; padding: 8px; }" +
    "#chatbot button { font-size: 1em; padding: 8px 16px; }";
  document.head.appendChild(style);

  const log = place.querySelector(".chat-log");
  const form = place.querySelector(".chat-form");
  const input = place.querySelector("input");
  const button = place.querySelector("button");
  const earlier = [];

  // textContent shows what was typed as plain text, so typed code never runs on the page.
  function show(who, text) {
    const line = document.createElement("p");
    line.className = who === "user" ? "chat-user" : who === "steps" ? "chat-steps" : "chat-bot";
    line.textContent = (who === "user" ? "You: " : who === "steps" ? "Tools used: " : "Chatbot: ") + text;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const question = input.value.trim();
    if (question === "") {
      return;
    }
    input.value = "";
    show("user", question);
    button.disabled = true;
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, earlier: earlier.slice(-6) }),
      });
      const data = await response.json();
      if (Array.isArray(data.steps) && data.steps.length > 0) {
        show("steps", data.steps.join(", then "));
      }
      show("bot", data.answer || "Sorry, no answer came back.");
      if (response.ok) {
        earlier.push({ role: "user", text: question }, { role: "bot", text: data.answer });
      }
    } catch (error) {
      show("bot", "The chatbot could not be reached. Check your internet connection and try again.");
    }
    button.disabled = false;
    input.focus();
  });
})();
