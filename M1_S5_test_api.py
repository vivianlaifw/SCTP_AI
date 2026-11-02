# M1_S5_test_api.py
# Module 1, Session 5: your first AI prompt call.
#
# The three settings you change are below. Your key lives in the .env file
# in your SCTP_AI folder. It never goes in this script.

PROVIDER = "groq"
# Activity 5.3 Level 3: change this to "google" to use your Google AI Studio key.

MODEL = "PUT-THE-MODEL-NAME-HERE"
# The trainer gives the model name in class. Copy it exactly, inside the quote marks.

PROMPT = "Give me a motivational quote for beginners in coding"
# Activity 5.3 Level 2: change the words inside the quote marks.


# You do not need to change anything below this line.

import logging
import os
import re
import sys
import time
from pathlib import Path

KEY_NAMES = {"groq": "GROQ_API_KEY", "google": "GOOGLE_API_KEY"}
KEY_STARTS = {"groq": ("gsk_",), "google": ("AQ.", "AIza")}
LIBRARIES = {"groq": "groq", "google": "google-genai"}
ENV_NAMES = (".env", ".env.txt", "env", "env.txt", ".env.local", "env.local")
PLACEHOLDER = "PUT-THE-MODEL-NAME-HERE"
BUSY_WAIT = 15
TIMEOUT_SECONDS = 60
TEMPERATURE = None   # None keeps the model's own default. Module 3 explains temperature.


def stop(message):
    """Prints a plain message and ends the script, with no error trace."""
    print()
    print(message)
    sys.exit(1)


def find_env_file():
    """Looks for the .env file in this script's folder, then up to two folders above."""
    here = Path(__file__).resolve().parent
    for folder in (here, here.parent, here.parent.parent):
        for name in ENV_NAMES:
            if (folder / name).is_file():
                return folder / name
    return None


def load_key(provider):
    """Reads the key for the chosen provider from the .env file."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        stop("The python-dotenv library is not installed. In the VS Code terminal, run:\n"
             "    pip install python-dotenv")
    wanted = KEY_NAMES[provider]
    env_file = find_env_file()
    if env_file is None:
        stop("No .env file was found. In VS Code, make a new file called .env in your SCTP_AI folder,\n"
             "beside this script, with this line in it:\n"
             "    " + wanted + "=paste-your-key-here")
    load_dotenv(env_file, override=True)
    key = os.environ.get(wanted, "")
    if not key:
        for name, value in os.environ.items():
            if name.upper() == wanted and value:
                key = value
                break
    key = key.strip().strip('"').strip("'").strip()
    if not key or key == "paste-your-key-here":
        stop("Your .env file (" + str(env_file) + ") has no key on a line starting " + wanted + "=\n"
             "Add the line, paste your key after the equals sign, save the file, and run this script again.")
    other = "google" if provider == "groq" else "groq"
    if key.startswith(KEY_STARTS[other]):
        stop("The key on the " + wanted + " line looks like a " + other.capitalize() + " key.\n"
             "Move it to the " + KEY_NAMES[other] + " line, or set PROVIDER to \"" + other + "\".")
    if not key.startswith(KEY_STARTS[provider]):
        print("Note: " + provider.capitalize() + " keys usually start with " + " or ".join(KEY_STARTS[provider])
              + ". Trying yours anyway.")
    return key


def ask_groq(key):
    """Sends PROMPT to MODEL on Groq and returns the reply text."""
    try:
        from groq import Groq
    except ImportError:
        stop("The groq library is not installed. In the VS Code terminal, run:\n    pip install groq")
    client = Groq(api_key=key, max_retries=0, timeout=TIMEOUT_SECONDS)
    extra = {} if TEMPERATURE is None else {"temperature": TEMPERATURE}
    reply = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": PROMPT}],
        **extra,
    )
    return reply.choices[0].message.content


def ask_google(key):
    """Sends PROMPT to MODEL on Google AI Studio and returns the reply text."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        stop("The google-genai library is not installed. In the VS Code terminal, run:\n    pip install google-genai")
    # The library prints a warning about a feature this script does not use. This hides it.
    logging.getLogger("google_genai.models").setLevel(logging.ERROR)
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_SECONDS * 1000))
    config = None if TEMPERATURE is None else types.GenerateContentConfig(temperature=TEMPERATURE)
    reply = client.models.generate_content(model=MODEL, contents=PROMPT, config=config)
    return reply.text


def status_of(error):
    """Returns the HTTP status number of a failed call, where there is one."""
    for name in ("status_code", "code"):
        value = getattr(error, name, None)
        if isinstance(value, int):
            return value
    return None


def is_quota(error):
    text = str(error)
    return status_of(error) == 429 or "RESOURCE_EXHAUSTED" in text or "rate_limit" in text.lower()


def is_busy(error):
    """True when the provider says the model is overloaded for every key, this one included."""
    text = str(error)
    return status_of(error) in (500, 502, 503, 504) or "UNAVAILABLE" in text or "high demand" in text.lower() \
        or "overloaded" in text.lower()


def wait_seconds(error):
    """Reads the wait the provider asks for, and adds five seconds."""
    found = re.search(r"(?:retry in|try again in)\s+([0-9.]+)\s*s", str(error), re.IGNORECASE)
    return int(float(found.group(1))) + 5 if found else 65


def explain(error):
    """Turns a failed call into one plain sentence."""
    text = str(error)
    status = status_of(error)
    if is_quota(error):
        return "Your allowance is still used up. Wait a minute, then run the script again."
    if is_busy(error):
        return ("The model is busy for everyone at the moment. Wait a minute and run the script again. "
                "If it stays busy, ask the trainer for the backup model name.")
    if "no longer available" in text.lower():
        return ("The model " + MODEL + " is no longer offered to new accounts. "
                "Ask the trainer for the current model name.")
    if status in (401, 403) or "API key not valid" in text or "invalid_api_key" in text.lower():
        return ("The provider did not accept your key. Check that the key in .env matches the one "
                "on the provider's site, with nothing else on the line.")
    if status == 404 or "model_not_found" in text or "not found" in text.lower():
        return ("The provider has no model called " + MODEL + ". Check the spelling against the name "
                "the trainer gave you.")
    if "timeout" in type(error).__name__.lower() or "timed out" in text.lower():
        return ("The model took longer than " + str(TIMEOUT_SECONDS) + " seconds to answer. Run the script again. "
                "If it happens again, ask the trainer for the backup model name.")
    if "connect" in type(error).__name__.lower() or "connect" in text.lower():
        return "The script could not reach the provider. Check your internet connection and run it again."
    first = text.splitlines()[0] if text.strip() else type(error).__name__
    return "The call failed: " + first[:200]


def main():
    if sys.version_info < (3, 10):
        stop("This script needs Python 3.10 or later. You are running " + sys.version.split()[0] + ".")
    provider = PROVIDER.strip().lower()
    if provider not in KEY_NAMES:
        stop("PROVIDER at the top of the script must be \"groq\" or \"google\". It is \"" + PROVIDER + "\".")
    if MODEL.strip() in ("", PLACEHOLDER):
        stop("Set MODEL at the top of the script to the model name the trainer gave you.\n"
             "Save the file, then run it again.")
    key = load_key(provider)
    ask = ask_groq if provider == "groq" else ask_google

    print("Asking " + provider + ", model " + MODEL + ":")
    print("    " + PROMPT)
    answer = None
    for attempt in (1, 2):
        try:
            answer = ask(key)
            break
        except Exception as error:
            if is_quota(error) and attempt == 1:
                wait = wait_seconds(error)
                print("Your allowance for this minute is used up. Waiting " + str(wait)
                      + " seconds, then trying once more.")
                time.sleep(wait)
                continue
            if is_busy(error) and attempt == 1:
                print("The model is busy at the moment. Waiting " + str(BUSY_WAIT) + " seconds, then trying once more.")
                time.sleep(BUSY_WAIT)
                continue
            stop(explain(error))
    if not answer:
        stop("The model sent back an empty reply. Run the script again, or change the prompt.")
    print()
    print("Reply:")
    print(answer)


if __name__ == "__main__":
    main()
