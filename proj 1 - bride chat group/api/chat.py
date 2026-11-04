# api/chat.py
# Your chatbot's server part. Vercel runs this file each time someone on your page asks a question.
# Your chatbot works as a small agent. The AI model can choose one of three tools before it answers:
# find_facts looks in your facts file, today gives the date, and calculate does a sum.
# This file runs each tool the model chooses, sends back what it found, and lets the model answer.
#
# The two settings you change are below. Your key goes in Vercel's settings. It never goes in this file.

PROVIDER = "google"
# Change this to "google" if your key is from Google AI Studio.

MODEL = "gemini-3.1-flash-lite"
# The trainer gives the model name in class. Copy it exactly, inside the quote marks.


# You do not need to change anything below this line.

import ast
import datetime
import json
import os
import re
import socket
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

KEY_NAMES = {"google": "GOOGLE_API_KEY"}
PLACEHOLDER = "your-model-name"
FACTS_FILE = "site.md"
RULES_FILE = "rules.md"
MAX_QUESTION = 500          # the longest question, in characters
MAX_EARLIER = 6             # how many earlier messages go with each question
MAX_ANSWER_TOKENS = 1500    # the longest answer the model may write
TIMEOUT_SECONDS = 30        # how long to wait for the model each time
MAX_STEPS = 3               # how many rounds of tools the model may use for one question
MAX_FACT_LINES = 8          # the most lines find_facts sends back
SINGAPORE = datetime.timezone(datetime.timedelta(hours=8))

NO_PERSONAL = ("Please don't type personal details, such as a phone number, an email address "
               "or an NRIC number, here. Ask your question again without them.")

# Patterns that look like personal details. A question that matches one never reaches the model.
PERSONAL = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),                          # an email address
    re.compile(r"(?<!\d)(?:\+?65[ -]?)?[3689]\d{3}[ -]?\d{4}(?!\d)"),  # a Singapore phone number
    re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE),               # a full NRIC or FIN number
]

# What the model is told about its tools, every time. What it may answer from is rule 1 in your rules file.
HOW_TO_USE_TOOLS = ("You have three tools. Before you answer any question about this website, use find_facts "
                    "to look up the facts, with one or two words from the question. Use today for anything "
                    "about today's date or day of the week. Use calculate for any sum.")


# Part 1: reading your two files

def read_file(name):
    """Reads one of your website's files. Returns empty text if the file is missing."""
    site_folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for folder in (site_folder, os.getcwd()):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    return ""


def instructions():
    """Puts your rules and the note about the tools together into the instructions the model gets."""
    return read_file(RULES_FILE).strip() + "\n\n" + HOW_TO_USE_TOOLS


def fact_lines():
    """Your facts, one to a line. Lines that start with a dash count as facts, if there are any."""
    lines = [line.strip() for line in read_file(FACTS_FILE).splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    dashed = [line.lstrip("-* ").strip() for line in lines if line[0] in "-*"]
    return dashed or lines


# Part 2: checking what the visitor typed

def has_personal_details(text):
    """True if the text looks like it holds an email address, a phone number or an NRIC number."""
    for pattern in PERSONAL:
        if pattern.search(text):
            return True
    return False


def clean_earlier(earlier):
    """Keeps the last few earlier messages, and drops any that are the wrong shape or hold personal details."""
    kept = []
    if not isinstance(earlier, list):
        return kept
    for item in earlier[-MAX_EARLIER:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = item.get("text")
        if role in ("user", "bot") and isinstance(text, str) and text.strip() and not has_personal_details(text):
            kept.append({"role": role, "text": text.strip()[:2000]})
    return kept


# Part 3: the agent's three tools. Each one only reads or works something out. None of them changes anything.

TOOLS = [
    {"name": "find_facts",
     "description": "Looks in this website's facts file and returns every fact that holds one of the words.",
     "parameters": {"type": "object",
                    "properties": {"words": {"type": "string",
                                             "description": "One or two words to look for, such as start or bring."}},
                    "required": ["words"]}},
    {"name": "today",
     "description": "Returns today's date and day of the week in Singapore.",
     "parameters": None},
    {"name": "calculate",
     "description": "Works out a sum with numbers, + - * / and brackets, such as 3 * 15 or (5 + 2) * 4.",
     "parameters": {"type": "object",
                    "properties": {"sum": {"type": "string", "description": "The sum to work out."}},
                    "required": ["sum"]}},
]
COMMON_WORDS = {"the", "and", "for", "are", "you", "your", "what", "when", "where", "which", "who", "how",
                "does", "can", "about", "with", "this", "that", "there", "have", "any", "website"}


def find_facts(words):
    """Returns the facts that hold any of the words, or says that none do."""
    wanted = []
    for word in re.findall(r"[a-z0-9]+", words.lower()):
        if len(word) > 2 and word not in COMMON_WORDS:
            wanted.append(word[:-1] if word.endswith("s") and len(word) > 3 else word)
    if not wanted:
        return "Give one or two words to look for, such as start or bring."
    found = [line for line in fact_lines() if any(word in line.lower() for word in wanted)]
    if not found:
        return "No facts hold those words."
    return "\n".join(found[:MAX_FACT_LINES])


def today():
    """Returns today's date and day of the week in Singapore, in words."""
    now = datetime.datetime.now(SINGAPORE)
    return now.strftime("%A ") + str(now.day) + now.strftime(" %B %Y")


def calculate(sum_text):
    """Works out a sum with numbers, + - * / and brackets. Anything else is refused."""
    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float) and abs(node.value) <= 1e9:
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            number = value(node.operand)
            return -number if isinstance(node.op, ast.USub) else number
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = value(node.left), value(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("not a plain sum")
    if len(sum_text) > 60:
        return "That sum is too long."
    try:
        result = value(ast.parse(sum_text.replace("x", "*").replace("×", "*"), mode="eval").body)
    except ZeroDivisionError:
        return "That sum divides by zero."
    except (SyntaxError, ValueError, TypeError, RecursionError, OverflowError):
        return "That is not a sum I can work out. Use numbers, + - * / and brackets."
    result = round(result, 2)
    return str(int(result)) if result == int(result) else str(result)


def run_tool(name, arguments):
    """Runs the tool the model chose, and returns what it found as text."""
    if not isinstance(arguments, dict):
        arguments = {}
    if name == "find_facts":
        return find_facts(str(arguments.get("words", ""))[:100])
    if name == "today":
        return today()
    if name == "calculate":
        return calculate(str(arguments.get("sum", ""))[:100])
    return "There is no tool called " + str(name)[:40] + "."


def step_name(name, arguments):
    """How a step shows in the chat box, such as find_facts("bring")."""
    if not isinstance(arguments, dict) or not arguments:
        return str(name)[:40] + "()"
    first = str(next(iter(arguments.values())))[:60]
    return str(name)[:40] + '("' + first + '")'


# Part 4: asking the model, step by step

def post(url, body, headers):
    """Sends one request to the AI provider and returns its reply as a dictionary."""
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "sctp-site-chatbot/2.0", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def ask_groq(key, earlier, question, steps):
    """Asks a model on Groq, runs the tools it chooses, and returns its answer."""
    messages = [{"role": "system", "content": instructions()}]
    for item in earlier:
        role = "user" if item["role"] == "user" else "assistant"
        messages.append({"role": role, "content": item["text"]})
    messages.append({"role": "user", "content": question})
    tools = []
    for tool in TOOLS:
        tools.append({"type": "function", "function": {
            "name": tool["name"], "description": tool["description"],
            "parameters": tool["parameters"] or {"type": "object", "properties": {}}}})
    base = os.environ.get("GROQ_BASE_URL", "https://api.groq.com")
    for step in range(MAX_STEPS + 1):
        body = {"model": MODEL, "messages": messages, "tools": tools, "max_completion_tokens": MAX_ANSWER_TOKENS,
                "tool_choice": "none" if step == MAX_STEPS else "auto"}   # the last round must answer
        if "gpt-oss" in MODEL:
            body["reasoning_effort"] = "low"   # these models think before they answer; low keeps it quick
        reply = post(base + "/openai/v1/chat/completions", body, {"Authorization": "Bearer " + key})
        message = (reply.get("choices") or [{}])[0].get("message") or {}
        calls = message.get("tool_calls") or []
        if not calls or step == MAX_STEPS:
            return message.get("content") or ""
        # The model chose one or more tools. Run each one, and send back what it found.
        messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
        for call in calls:
            name = (call.get("function") or {}).get("name")
            try:
                arguments = json.loads((call.get("function") or {}).get("arguments") or "{}")
            except ValueError:
                arguments = {}
            steps.append(step_name(name, arguments))
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "name": name,
                             "content": run_tool(name, arguments)})
    return ""


def ask_google(key, earlier, question, steps):
    """Asks a model on Google AI Studio, runs the tools it chooses, and returns its answer."""
    contents = []
    for item in earlier:
        role = "user" if item["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": item["text"]}]})
    contents.append({"role": "user", "parts": [{"text": question}]})
    declarations = []
    for tool in TOOLS:
        declaration = {"name": tool["name"], "description": tool["description"]}
        if tool["parameters"]:
            declaration["parameters"] = tool["parameters"]
        declarations.append(declaration)
    base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
    for step in range(MAX_STEPS + 1):
        body = {
            "systemInstruction": {"parts": [{"text": instructions()}]},
            "contents": contents,
            "tools": [{"functionDeclarations": declarations}],
            "generationConfig": {"maxOutputTokens": MAX_ANSWER_TOKENS},
        }
        if step == MAX_STEPS:
            body["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}   # the last round must answer
        reply = post(base + "/v1beta/models/" + MODEL + ":generateContent", body, {"x-goog-api-key": key})
        parts = ((reply.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        calls = [part["functionCall"] for part in parts if isinstance(part.get("functionCall"), dict)]
        if not calls or step == MAX_STEPS:
            return "".join(part.get("text", "") for part in parts if not part.get("thought"))
        # The model chose one or more tools. Its reply goes back unchanged, then what each tool found.
        contents.append({"role": "model", "parts": parts})
        results = []
        for call in calls:
            name, arguments = call.get("name"), call.get("args") or {}
            steps.append(step_name(name, arguments))
            result = {"name": name, "response": {"result": run_tool(name, arguments)}}
            if call.get("id"):
                result["id"] = call["id"]   # newer models match each result to its call by this id
            results.append({"functionResponse": result})
        contents.append({"role": "user", "parts": results})
    return ""


def explain(error):
    """Turns a failed call into one plain sentence."""
    if isinstance(error, urllib.error.HTTPError):
        try:
            detail = error.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        if error.code in (401, 403) or "API key" in detail or "API_KEY" in detail:
            return ("The AI provider did not accept the key. Check " + KEY_NAMES[PROVIDER.strip().lower()]
                    + " in Vercel's settings, then redeploy.")
        if error.code == 404:
            return "The AI provider has no model called " + MODEL + ". Check MODEL at the top of the chatbot's file."
        if error.code == 429:
            return "The chatbot has had too many questions for now. Please try again in a minute."
        if error.code >= 500:
            return "The AI model is busy for everyone at the moment. Please try again in a minute."
        return "The AI provider refused the question (error " + str(error.code) + "). Please try again."
    if isinstance(error, (socket.timeout, TimeoutError)) or "timed out" in str(error):
        return "The AI model took too long to answer. Please try again."
    return "The chatbot could not reach the AI provider. Please try again later."


# Part 5: one question in, one answer out

def answer(question, earlier):
    """Works out the reply to one question. Returns a status number, the reply, and the tools used."""
    steps = []
    if not isinstance(question, str) or not question.strip():
        return 400, "Please type a question.", steps
    question = question.strip()
    if len(question) > MAX_QUESTION:
        return 400, "Please keep your question under " + str(MAX_QUESTION) + " characters.", steps
    if has_personal_details(question):
        return 400, NO_PERSONAL, steps
    provider = PROVIDER.strip().lower()
    if provider not in KEY_NAMES:
        return 500, 'PROVIDER at the top of the chatbot\'s file must be "groq" or "google".', steps
    if MODEL.strip() in ("", PLACEHOLDER):
        return 500, "Set MODEL at the top of the chatbot's file to the model name the trainer gave you.", steps
    key = os.environ.get(KEY_NAMES[provider], "").strip()
    if not key:
        return 500, ("The chatbot has no key yet. In Vercel, add " + KEY_NAMES[provider]
                     + " under Settings, Environment Variables, then redeploy."), steps
    ask = ask_groq if provider == "groq" else ask_google
    try:
        text = ask(key, clean_earlier(earlier), question, steps).strip()
    except Exception as error:
        return 502, explain(error), steps
    if not text:
        return 502, "The AI model sent back an empty answer. Please ask again.", steps
    return 200, text, steps


# Part 6: what Vercel calls

class handler(BaseHTTPRequestHandler):
    """Vercel hands each request from the page to this class."""

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 20000:
            return self.send_answer(400, "Please send one short question.")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return self.send_answer(400, "The question did not arrive in the right form.")
        if not isinstance(body, dict):
            return self.send_answer(400, "The question did not arrive in the right form.")
        status, text, steps = answer(body.get("question"), body.get("earlier"))
        self.send_answer(status, text, steps)

    def do_GET(self):
        self.send_answer(405, "Ask your question in the chat box on the page.")

    def send_answer(self, status, text, steps=()):
        data = json.dumps({"answer": text, "steps": list(steps)}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass   # writes nothing to the logs, so nobody's questions are kept there
