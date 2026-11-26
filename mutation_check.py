"""Mutation check: change the contract on a disposable copy, one small edit at a time, and see whether the tests notice.

Run from the repository root:  python3 scripts/mutation_check.py [workers]
It first proves that the unmodified contract passes, then runs the tests against every mutant (stopping at the first
failing test). A mutant that survives is either a missing test or an equivalent change; survivors are listed.
Each entry is (label, text to find, replacement, which occurrence of the text to change: 1 = first).
"""
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "contracts/terms_drift_watch.py"

MUTANTS = [
    ("label min 4", "LABEL_MIN, LABEL_MAX = 3, 80", "LABEL_MIN, LABEL_MAX = 4, 80", 1),
    ("label min 2", "LABEL_MIN, LABEL_MAX = 3, 80", "LABEL_MIN, LABEL_MAX = 2, 80", 1),
    ("label max 79", "LABEL_MIN, LABEL_MAX = 3, 80", "LABEL_MIN, LABEL_MAX = 3, 79", 1),
    ("label max 81", "LABEL_MIN, LABEL_MAX = 3, 80", "LABEL_MIN, LABEL_MAX = 3, 81", 1),
    ("url max 299", "URL_MAX = 300", "URL_MAX = 299", 1),
    ("url max 301", "URL_MAX = 300", "URL_MAX = 301", 1),
    ("101 watches", "MAX_WATCHES = 100", "MAX_WATCHES = 101", 1),
    ("99 watches", "MAX_WATCHES = 100", "MAX_WATCHES = 99", 1),
    ("13 snapshots", "MAX_SNAPSHOTS = 12", "MAX_SNAPSHOTS = 13", 1),
    ("11 snapshots", "MAX_SNAPSHOTS = 12", "MAX_SNAPSHOTS = 11", 1),
    ("gap 61", "SNAPSHOT_GAP = 60 ", "SNAPSHOT_GAP = 61 ", 1),
    ("gap 59", "SNAPSHOT_GAP = 60 ", "SNAPSHOT_GAP = 59 ", 1),
    ("page limit 51", "PAGE_LIMIT = 50", "PAGE_LIMIT = 51", 1),
    ("page limit 49", "PAGE_LIMIT = 50", "PAGE_LIMIT = 49", 1),
    ("quote min 13", "QUOTE_MIN, QUOTE_MAX = 12, 300", "QUOTE_MIN, QUOTE_MAX = 13, 300", 1),
    ("quote min 11", "QUOTE_MIN, QUOTE_MAX = 12, 300", "QUOTE_MIN, QUOTE_MAX = 11, 300", 1),
    ("quote max 299", "QUOTE_MIN, QUOTE_MAX = 12, 300", "QUOTE_MIN, QUOTE_MAX = 12, 299", 1),
    ("quote max 301", "QUOTE_MIN, QUOTE_MAX = 12, 300", "QUOTE_MIN, QUOTE_MAX = 12, 301", 1),
    ("page 7999", "MAX_PAGE = 8000 ", "MAX_PAGE = 7999 ", 1),
    ("page 8001", "MAX_PAGE = 8000 ", "MAX_PAGE = 8001 ", 1),
    ("answer limit 7999", "MAX_MODEL = 8000", "MAX_MODEL = 7999", 1),
    ("answer limit 8001", "MAX_MODEL = 8000", "MAX_MODEL = 8001", 1),
    ("one model try", "MODEL_TRIES = 2", "MODEL_TRIES = 1", 1),
    ("three model tries", "MODEL_TRIES = 2", "MODEL_TRIES = 3", 1),
    ("a topic missing", '"LIABILITY", "RENEWAL")\nSTATES', '"LIABILITY")\nSTATES', 1),
    ("a topic renamed", '"FEES", "DATA_SHARING"', '"FEE", "DATA_SHARING"', 1),
    ("a state added", 'STATES = ("PRESENT", "ABSENT", "UNCLEAR")', 'STATES = ("PRESENT", "ABSENT", "UNCLEAR", "MAYBE")', 1),
    ("label control characters allowed", "or any(ord(c) < 32 or ord(c) == 127 for c in text):\n        raise gl.vm.UserError(\"invalid label\")", ":\n        raise gl.vm.UserError(\"invalid label\")", 1),
    ("label not squashed", 'text = _squash(value)\n    if not LABEL_MIN', 'text = value\n    if not LABEL_MIN', 1),
    ("http allowed", 'not value.startswith("https://")', 'not value.startswith("http")', 1),
    ("space in url allowed", "any(ord(c) <= 32 or ord(c) >= 127 for c in value)", "any(ord(c) < 32 or ord(c) >= 127 for c in value)", 1),
    ("non-ascii url allowed", "any(ord(c) <= 32 or ord(c) >= 127 for c in value)", "any(ord(c) <= 32 for c in value)", 1),
    ("fragment allowed", '("' + chr(92) * 2 + '", "#", "@")', '("' + chr(92) * 2 + '", "@")', 1),
    ("at sign allowed", '("' + chr(92) * 2 + '", "#", "@")', '("' + chr(92) * 2 + '", "#")', 1),
    ("backslash allowed", '("' + chr(92) * 2 + '", "#", "@")', '("#", "@")', 1),
    ("localhost allowed", '("local", "localhost", "internal", "test", "invalid")', '("local", "internal", "test", "invalid")', 1),
    ("local allowed", '("local", "localhost", "internal", "test", "invalid")', '("localhost", "internal", "test", "invalid")', 1),
    ("internal allowed", '("local", "localhost", "internal", "test", "invalid")', '("local", "localhost", "test", "invalid")', 1),
    ("test allowed", '("local", "localhost", "internal", "test", "invalid")', '("local", "localhost", "internal", "invalid")', 1),
    ("invalid allowed", '("local", "localhost", "internal", "test", "invalid")', '("local", "localhost", "internal", "test")', 1),
    ("one label host allowed", "len(labels) < 2 or", "len(labels) < 1 or", 1),
    ("numeric tld allowed", "not labels[-1].isalpha() or", "False or", 1),
    ("one letter tld allowed", "len(labels[-1]) < 2", "len(labels[-1]) < 1", 1),
    ("long label allowed", "len(label) > 63 or", "len(label) > 64 or", 1),
    ("dash start allowed", "label[0] == \"-\" or", "False or", 1),
    ("dash end allowed", "label[-1] == \"-\"", "False", 1),
    ("odd host characters allowed", 'any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in label)', "False", 1),
    ("empty label allowed", "any(not label or len(label)", "any(len(label)", 1),
    ("host not lower-cased", 'host = value[8:].split("/")[0].split("?")[0].lower()', 'host = value[8:].split("/")[0].split("?")[0]', 1),
    ("query ignored in host", 'host = value[8:].split("/")[0].split("?")[0].lower()', 'host = value[8:].split("/")[0].lower()', 1),
    ("full book allowed", "if watch_id >= MAX_WATCHES:", "if watch_id > MAX_WATCHES:", 1),
    ("count not advanced", "self.count = watch_id + 1", "self.count = watch_id", 1),
    ("watch sender not recorded", '"by": _sender(), "created": _now()', '"by": "", "created": _now()', 1),
    ("watch time not recorded", '"created": _now()', '"created": 0', 1),
    ("snapshot limit off by one", 'if len(entry["snapshots"]) >= MAX_SNAPSHOTS:', 'if len(entry["snapshots"]) > MAX_SNAPSHOTS:', 1),
    ("gap exclusive", 'now < entry["snapshots"][-1]["at"] + SNAPSHOT_GAP', 'now <= entry["snapshots"][-1]["at"] + SNAPSHOT_GAP', 1),
    ("gap never", 'if entry["snapshots"] and now < entry["snapshots"][-1]["at"] + SNAPSHOT_GAP:', "if False:", 1),
    ("gap counted from the first", 'entry["snapshots"][-1]["at"] + SNAPSHOT_GAP', 'entry["snapshots"][0]["at"] + SNAPSHOT_GAP', 1),
    ("previous ignored", 'previous = entry["snapshots"][-1]["topics"] if entry["snapshots"] else None', "previous = None", 1),
    ("previous is the first", 'previous = entry["snapshots"][-1]["topics"] if', 'previous = entry["snapshots"][0]["topics"] if', 1),
    ("unreadable stored", 'if reading["state"] != "OK":\n            return "UNREADABLE"', 'if False:\n            return "UNREADABLE"', 1),
    ("number off by one", 'number = len(entry["snapshots"]) + 1', 'number = len(entry["snapshots"])', 1),
    ("snapshot sender not recorded", '"at": now, "by": _sender(), "topics"', '"at": now, "by": "", "topics"', 1),
    ("snapshot time not recorded", '"at": now, "by": _sender(), "topics"', '"at": 0, "by": _sender(), "topics"', 1),
    ("drift not stored", '"quote": reading["topics"][t]["quote"], "drift": drifts[t]}', '"quote": reading["topics"][t]["quote"], "drift": "SAME"}', 1),
    ("quote not stored", '"state": reading["topics"][t]["state"], "quote": reading["topics"][t]["quote"]', '"state": reading["topics"][t]["state"], "quote": ""', 1),
    ("drifted list wrong", '"drifted": _drifted(drifts)})\n        self.watches', '"drifted": []})\n        self.watches', 1),
    ("returned drifted wrong", 'return json.dumps({"id": watch_id, "number": number, "drifted": _drifted(drifts)}', 'return json.dumps({"id": watch_id, "number": number, "drifted": []}', 1),
    ("first has no label", 'return "FIRST"', 'return "SAME"', 1),
    ("unclear before is known", 'if was == "UNCLEAR" or is_now == "UNCLEAR":', 'if is_now == "UNCLEAR":', 1),
    ("unclear now is known", 'if was == "UNCLEAR" or is_now == "UNCLEAR":', 'if was == "UNCLEAR":', 1),
    ("removed is a change", 'return now["change"] if is_now == "PRESENT" else "REMOVED"', 'return now["change"] if is_now == "PRESENT" else "SAME"', 1),
    ("change ignored", 'return now["change"] if is_now == "PRESENT"', 'return "SAME" if is_now == "PRESENT"', 1),
    ("added is the same", 'return "ADDED" if is_now == "PRESENT" else "SAME"', 'return "SAME"', 1),
    ("absent twice is added", 'return "ADDED" if is_now == "PRESENT" else "SAME"', 'return "ADDED"', 1),
    ("same is not a drift", 'if drifts[topic] in ("CHANGED", "ADDED", "REMOVED")', 'if drifts[topic] in ("CHANGED", "ADDED")', 1),
    ("added is not a drift", '("CHANGED", "ADDED", "REMOVED")', '("CHANGED", "REMOVED")', 1),
    ("removed is not a drift", '("CHANGED", "ADDED", "REMOVED")', '("CHANGED", "ADDED")', 1),
    ("changed is not a drift", '("CHANGED", "ADDED", "REMOVED")', '("ADDED", "REMOVED")', 1),
    ("drifted unsorted", 'return [topic for topic in TOPICS if drifts[topic]', 'return [topic for topic in reversed(TOPICS) if drifts[topic]', 1),
    ("quote may be anywhere", "if not _on_page(quote, page):\n        return {", "if False:\n        return {", 1),
    ("bad quote spoils the reading", "return {\"state\": \"UNCLEAR\", \"quote\": \"\", \"change\": \"\"}      # words", "return None      # words", 1),
    ("bad quote kept as present", "return {\"state\": \"UNCLEAR\", \"quote\": \"\", \"change\": \"\"}      # words", "return {\"state\": \"PRESENT\", \"quote\": quote, \"change\": \"\"}      # words", 1),
    ("bad quote becomes absent", "return {\"state\": \"UNCLEAR\", \"quote\": \"\", \"change\": \"\"}      # words", "return {\"state\": \"ABSENT\", \"quote\": \"\", \"change\": \"\"}      # words", 1),
    ("bad quote text still stored", "return {\"state\": \"UNCLEAR\", \"quote\": \"\", \"change\": \"\"}      # words", "return {\"state\": \"UNCLEAR\", \"quote\": quote, \"change\": \"\"}      # words", 1),
    ("page not squashed", "return _squash(body)[:MAX_PAGE]", "return body[:MAX_PAGE]", 1),
    ("page cut before squashing", "return _squash(body)[:MAX_PAGE]", "return _squash(body[:MAX_PAGE])", 1),
    ("split counts any state difference", "if (parsed[\"topics\"][t][\"state\"] == \"PRESENT\") != (mine[\"topics\"][t][\"state\"] == \"PRESENT\"))", "if parsed[\"topics\"][t][\"state\"] != mine[\"topics\"][t][\"state\"])", 1),
    ("split ignores what the validator found", "if (parsed[\"topics\"][t][\"state\"] == \"PRESENT\") != (mine[\"topics\"][t][\"state\"] == \"PRESENT\"))", "if parsed[\"topics\"][t][\"state\"] == \"PRESENT\" and mine[\"topics\"][t][\"state\"] != \"PRESENT\")", 1),
    ("split ignores what the leader found", "if (parsed[\"topics\"][t][\"state\"] == \"PRESENT\") != (mine[\"topics\"][t][\"state\"] == \"PRESENT\"))", "if mine[\"topics\"][t][\"state\"] == \"PRESENT\" and parsed[\"topics\"][t][\"state\"] != \"PRESENT\")", 1),
    ("quote case sensitive", "_squash(quote).lower() in _squash(page).lower()", "_squash(quote) in _squash(page)", 1),
    # (removed, equivalent: inside _on_page both _squash calls are redundant, because _fetch_page already returns the page on
    #  one line and _clean_topic squashes the quote before asking; dropping either changes nothing. Spacing is tested end to
    #  end by test_a_quote_may_differ_in_case_and_spacing_and_is_stored_squashed.)
    ("quote length unchecked", "return QUOTE_MIN <= len(quote) <= QUOTE_MAX and _squash(quote)", "return _squash(quote)", 1),
    ("quote kept for absent", 'return {"state": state, "quote": "", "change": ""}', 'return {"state": state, "quote": quote, "change": ""}', 1),
    ("change required everywhere", "if _needs_change(previous, topic):", "if previous is not None:", 1),
    ("change never required", "if _needs_change(previous, topic):", "if False:", 1),
    ("change set widened", 'if change not in ("SAME", "CHANGED"):', 'if change not in ("SAME", "CHANGED", "ADDED"):', 1),
    ("change unchecked", 'if change not in ("SAME", "CHANGED"):\n            return None', 'if False:\n            return None', 1),
    ("change kept where not asked", 'return {"state": "PRESENT", "quote": quote, "change": ""}', 'return {"state": "PRESENT", "quote": quote, "change": change}', 1),
    ("needs change on absent before", 'return previous is not None and previous[topic]["state"] == "PRESENT"', 'return previous is not None', 1),
    ("keys not exact", 'set(item) != {"state", "quote", "change"}', "False", 1),
    ("topics not exact", "if not isinstance(raw, dict) or set(raw) != set(TOPICS):", "if not isinstance(raw, dict):", 1),
    ("answer length unchecked", "if len(raw) > MAX_MODEL:\n                    continue", "if False:\n                    continue", 1),
    ("previous quotes shown for all", 'if previous is not None and previous[topic]["state"] == "PRESENT":\n            before[topic]', 'if previous is not None:\n            before[topic]', 1),
    ("previous quotes never shown", 'if previous is not None and previous[topic]["state"] == "PRESENT":\n            before[topic]', 'if False:\n            before[topic]', 1),
    ("validator takes any leader text", "if not isinstance(proposed, str) or len(proposed) > MAX_MODEL:\n            return False", "if not isinstance(proposed, str):\n            return False", 1),
    ("validator takes only a return", "if not isinstance(result, gl.vm.Return):\n            return False", "if False:\n            return False", 1),
    ("validator takes any unreadable page", 'return parsed == {"state": "ERROR"}', "return True", 1),
    ("validator skips the shape check", "if not _valid_reading(parsed, page, previous):\n            return False", "if not isinstance(parsed, dict):\n            return False", 1),
    ("validator takes any error", 'return parsed["state"] == mine["state"]', "return True", 1),
    ("validator ignores the states", "split <= MAX_SPLIT", "True", 1),
    ("split limit 3", "MAX_SPLIT = 2  ", "MAX_SPLIT = 3  ", 1),
    ("split limit 1", "MAX_SPLIT = 2  ", "MAX_SPLIT = 1  ", 1),
    ("split limit 2 not allowed", "split <= MAX_SPLIT", "split < MAX_SPLIT", 1),
    ("split counts nothing", "if (parsed[\"topics\"][t][\"state\"] == \"PRESENT\") != (mine[\"topics\"][t][\"state\"] == \"PRESENT\"))", "if False)", 1),
    ("validator ignores the drifted list", "and _drifted(_drifts(parsed[\"topics\"], previous)) == _drifted(_drifts(mine[\"topics\"], previous)))", ")", 1),
    ("validator drifted list without previous", "_drifted(_drifts(parsed[\"topics\"], previous)) == _drifted(_drifts(mine[\"topics\"], previous))", "_drifted(_drifts(parsed[\"topics\"], None)) == _drifted(_drifts(mine[\"topics\"], None))", 1),
    ("valid reading allows a changed quote", 'if clean is None or clean != value["topics"][topic]:', "if clean is None:", 1),
    ("valid reading allows any state", 'value["state"] != "OK" or not isinstance(value["topics"], dict)', 'not isinstance(value["topics"], dict)', 1),
    ("valid reading topics not exact", 'if set(value["topics"]) != set(TOPICS):\n        return False', "if False:\n        return False", 1),
    ("page read for only the first topics", "return _squash(body)[:MAX_PAGE]", "return _squash(body)[:MAX_PAGE + 100]", 1),
    ("empty page accepted", "if not isinstance(body, str) or not body.strip():", "if not isinstance(body, str):", 1),
    # left out on purpose: replacing a failed fetch by an empty page is the same as no page (the empty-page check catches both).
    ("page not truncated", "return _squash(body)[:MAX_PAGE]", "return _squash(body)", 1),
    ("page offset negative allowed", "or offset < 0 or", "or False or", 1),
    ("page limit zero allowed", "not 1 <= limit <= PAGE_LIMIT", "not 0 <= limit <= PAGE_LIMIT", 1),
    ("page not clipped", "range(offset, min(offset + limit, int(self.count)))", "range(offset, offset + limit)", 1),
    ("page type unchecked", "if type(offset) is not int or type(limit) is not int or", "if", 1),
    ("unknown watch accepted", "or watch_id >= int(self.count):\n            raise", "or False:\n            raise", 1),
    ("negative watch accepted", "if type(watch_id) is not int or watch_id < 0 or watch_id >= int(self.count):\n            raise", "if type(watch_id) is not int or watch_id >= int(self.count):\n            raise", 1),
    ("view of unknown watch", 'return "NONE"\n        return self.watches[watch_id]', 'return "{}"\n        return self.watches[watch_id]', 1),
    ("drift view wrong list", 'for s in entry["snapshots"] if topic in s["drifted"]]', 'for s in entry["snapshots"] if topic not in s["drifted"]]', 1),
    ("summary count wrong", '"snapshots": len(watch["snapshots"])', '"snapshots": 1', 1),
    ("summary drift wrong", '"latest_drifted": last["drifted"] if last else None', '"latest_drifted": None', 1),
    ("time parsing ignores the offset", "+ int(clock[0:2]) * 3600 + int(clock[3:5]) * 60 + int(clock[6:8]) - offset)", "+ int(clock[0:2]) * 3600 + int(clock[3:5]) * 60 + int(clock[6:8]))", 1),
]


def run_tests(directory: Path) -> bool:
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/direct", "-q", "-x", "-p", "no:cacheprovider"],
                            cwd=directory, capture_output=True, text=True)
    return result.returncode == 0


def main() -> int:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    source = (ROOT / CONTRACT).read_text()
    with tempfile.TemporaryDirectory(prefix="mutation-") as tmp:
        base = Path(tmp)

        def prepare(name: str) -> Path:
            work = base / name
            shutil.copytree(ROOT / "contracts", work / "contracts")
            shutil.copytree(ROOT / "tests", work / "tests", ignore=shutil.ignore_patterns("__pycache__"))
            return work

        if not run_tests(prepare("clean")):
            print("The unmodified contract does not pass its tests; stopping.")
            return 2
        print("unmodified contract passes; %d mutants" % len(MUTANTS), flush=True)

        def one(index_item):
            index, (label, old, new, nth) = index_item
            parts = source.split(old)
            if len(parts) <= nth:
                return label, "NOT FOUND"
            mutated = old.join(parts[:nth]) + new + old.join(parts[nth:])
            if mutated == source:
                return label, "NO CHANGE"
            work = prepare("m%d" % index)
            (work / CONTRACT).write_text(mutated)
            caught = not run_tests(work)
            shutil.rmtree(work, ignore_errors=True)
            return label, "caught" if caught else "SURVIVED"

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, enumerate(MUTANTS)))
    bad = [(label, state) for label, state in results if state != "caught"]
    print("%d of %d mutants caught" % (len(results) - len(bad), len(results)))
    for label, state in bad:
        print("  %s: %s" % (state, label))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
