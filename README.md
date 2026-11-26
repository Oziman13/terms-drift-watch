# Terms Drift Watch

**A public record of how a page of terms changes between visits. Every validator fetches the page itself and reads it; every quotation is checked by code against the page the validator fetched; what counts as drift is plain code.**

Anyone starts a *watch* on one public HTTPS page (a terms of service, a pricing policy, a privacy notice) and then asks for *snapshots*. Each snapshot reads six topics on the page and compares them with the previous snapshot. The watch keeps every snapshot, so the history of the page stays readable and cannot be edited later.

* `contracts/terms_drift_watch.py`: the Intelligent Contract (one Python file, holds no funds).
* `tests/direct`: 230 direct-mode tests (genlayer-test; model and web mocked). `tests/glsim`: 5 tests on a local 5-validator network.
* `scripts/mutation_check.py`: breaks the contract on purpose in 133 ways and checks that the tests notice (all caught; one equivalent mutant was removed and is explained in the script; output in `evidence/mutation-check.txt`).

Status: **v0.3.0, written for GenVM v0.4. Tested in memory and on a local simulator, and run on Studio with real validator models: two snapshots of one page reached consensus (see [Live run](#live-run)).** Earlier versions failed on a real page; what was learned is in [Live run](#live-run) too.

## Why a contract for this

Terms change quietly: a new fee, a wider permission to share data, an arbitration clause that was not there. A page owner can overwrite its own history; a private monitor is one party's word. A public book where independent validators each fetched the page and agreed on what it said at that moment gives people something to point at.

## How it works

| Step | Call | Rule |
|---|---|---|
| 1. Watch | `watch(url, label)` | `url` is a public `https://` page (at most 300 characters; no spaces, non-ASCII, `\`, `#` or `@`; a plain host name, not `localhost`, `.local`, `.internal`, `.test`, `.invalid`). `label` is 3 to 80 characters. The book holds at most 100 watches. |
| 2. Snapshot | `snapshot(watch_id)` | Anyone. At most 12 per watch, at least 60 seconds apart. Returns `{"id","number","drifted"}`, or `UNREADABLE` (nothing is stored). |
| 3. Read | `get_watch_json`, `get_drift_json`, `get_count`, `get_page_json(offset, limit)` | `get_page_json` returns up to 50 summaries, oldest first. |

### The six topics

`FEES`, `DATA_SHARING`, `DISPUTES` (arbitration, class-action waiver, courts), `TERMINATION`, `LIABILITY`, `RENEWAL` (automatic renewal and cancelling). For each the model says `PRESENT`, `ABSENT` or `UNCLEAR`, and for `PRESENT` it copies 12 to 300 characters from the page. **The contract, not the model, checks the quotation**: after collapsing spaces and ignoring case it must occur in the page text the validator fetched. A `PRESENT` whose quotation is not on the page (or is shorter than 12 or longer than 300 characters) is stored as `UNCLEAR` with no quotation: words that are not on the page prove nothing. An answer in any other shape (not exactly the six topics, wrong keys) is an *error*, never an outcome. The page is read as **one line** (all white space collapsed, the first 8000 characters): models copy hard line breaks into their JSON and break it, which is what failed in the first live runs. The page and the earlier quotations go to the model as untrusted data between markers, and the prompt says never to obey them.

### What counts as drift

From the second snapshot on, the model is shown the words stored for each topic last time. For a topic that was `PRESENT` and still is, it says `SAME` or `CHANGED` in substance (a new amount, a wider permission, a shorter notice; a reworded sentence is `SAME`). Everything else is plain code:

| Before | Now | Drift |
|---|---|---|
| `PRESENT` | `PRESENT` | what the model said: `SAME` or `CHANGED` |
| `PRESENT` | `ABSENT` | `REMOVED` |
| `ABSENT` | `PRESENT` | `ADDED` |
| `ABSENT` | `ABSENT` | `SAME` |
| either `UNCLEAR` | | `UNKNOWN` |
| (first snapshot) | | `FIRST` |

A snapshot lists the topics that are `CHANGED`, `ADDED` or `REMOVED`.

### What the validators must agree on

Validators run the fetch and the model themselves (`gl.vm.run_nondet_default`). A validator accepts the leader's reading only if

1. it is well formed: the six topics, nothing else, and every `PRESENT` quotation really on the page *this validator* fetched;
2. both find a provision (`PRESENT`) on the same topics, **give or take two** (`MAX_SPLIT = 2`); `ABSENT` and `UNCLEAR` count as the same side; and
3. both reach exactly the **same list of drifted topics** (the topics that are `CHANGED`, `ADDED` or `REMOVED`).

Why not exact agreement: five validators run different models, and on a long legal page they read the edges differently (one says `UNCLEAR` where another says `ABSENT`). Requiring all six states to match made a real snapshot fail in testing. The tolerance is limited on purpose: a validator can accept a reading that differs on up to two topics, but never one that reports a different set of drifted topics, so what people act on (what changed) is checked exactly. The stored states and quotations are the leader's reading; validators need not agree on the quotations themselves. A validator that cannot fetch the page agrees only to "unreadable". When there is no clean answer or the validators do not agree, `snapshot` returns `UNREADABLE` or the transaction ends `UNDETERMINED`, and nothing is stored.

## What the record does not show

* It is a **model's reading of a page, not legal advice.** `ABSENT` means the validators' models found no provision in the text they were shown, not that the service has none.
* Only the first 8000 characters of a page are read. A long terms page can have its fees or arbitration clause further down, which shows up as `ABSENT` or `UNCLEAR`.
* The page is fetched as text. Pages that need scripts, a login or a cookie choice, or that show different text to different visitors, can fail to be read or can make validators disagree; then the call changes nothing.
* A snapshot proves what validators saw at that time, not that the page was the same for everyone, and not when the page was first changed (changes between two snapshots are not dated).
* The URL check is narrow on purpose. It is not a DNS or redirect sandbox.

## Run the tests

```bash
pip install genlayer-test            # direct mode
python3 -m pytest tests/direct       # model and web are mocked
pip install glsim fastapi uvicorn numpy
python3 -m pytest tests/glsim        # 5 tests on a local 5-validator network
python3 scripts/mutation_check.py 3  # breaks the contract 133 ways; survivors are listed
```

The contract file carries the runner hash of the published GenVM; the local harnesses ship their own, so the tests build `build/terms_drift_watch_local.py` (not committed) with only that first line swapped.

## Live run

Studio (GenLayer Studio, Studionet), real validator models, runner `kzybg95x…` (the hash Studio accepted on 25 Nov 2026). The contract was deployed from a throwaway Studio account (`0x7A23cDe01d7cF51dd0Df9f46a2e6731Cd2Ca0730`); anyone can deploy the same file from their own account.

* Contract v0.3.0: [`0x75e4f261AD418ccF94444638829167E75cBfFC6A`](https://explorer-studio.genlayer.com/address/0x75e4f261AD418ccF94444638829167E75cBfFC6A)
* Deploy: `0x7dfe0507134efec86c904f797a65c072533e987a9ea60a5811724b8240ef2140`
* `watch` (id 0, `https://www.apache.org/licenses/LICENSE-2.0.txt`): `0x0ad5013e5148e05b138dd53245ce6ce5b9b5f00d503e8abbdebea8335504b571`
* `snapshot` 1: `0x630b915db45840a893e2ef22b03b18a4b8da16b2cd5f01536efbd3c979e6cc54`: accepted, 3 agree / 1 disagree / 1 did not vote, returned `{"drifted": [], "id": 0, "number": 1}`.
* `snapshot` sent too early: `0xe8b221025e0d1b332a5a8e558cdece0a1a578c0623d8048ea1b7845e25572fa2` was refused by the 60 second rule (`snapshot too recent`), as designed.
* `snapshot` 2: `0x216ecbdecc0e0399a7a4c39b466cb764f2804437194cc43f73fad3b74bcaa9b8`: accepted, 3 agree / 2 did not vote, `{"drifted": [], "id": 0, "number": 2}`. In this snapshot the leader's `FEES` and `LIABILITY` quotations could not be matched to the page, so both were stored as `UNCLEAR` (drift `UNKNOWN`) instead of a made-up `CHANGED`.

What the live run does **not** show: only one page, which is a software licence and not a terms-of-service page (so most topics read `ABSENT`, and `FEES` is a stretch for "no-charge, royalty-free"); no real change of a page was observed, because I do not control a public page that I could change; two snapshots only; the votes of validators that did not vote say nothing either way.

What failed before, and why. v0.1.0 (all six states must match) and v0.2.0 (up to two states may differ) both ended `UNDETERMINED` on this page. A debug copy that printed its own reasoning showed the cause was not the model's opinion but its output: the licence text is hard-wrapped, models copied the line breaks into their JSON (invalid JSON, or a reply cut short) and some quotations were longer than 300 characters, so the leader's reading was an *error* while three validators read the page cleanly and disagreed. v0.3.0 reads the page as one line, stores an unverifiable quotation as `UNCLEAR` instead of failing the whole reading, and compares only where a provision was found.

## Licence

MIT.
