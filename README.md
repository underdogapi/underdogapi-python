# underdog-api (Python)

Python client for [Underdog API](https://underdogapi.com): Underdog Fantasy pick'em lines with separate Higher and
Lower payout multipliers, every recorded line move since 6 Nov 2026, the board at any past instant, and graded results.
Standard library only; Python 3.9+.

Underdog API is an independent data service operated by Stunning Couches LLC. It is not affiliated with, endorsed by
or operated by Underdog Fantasy.

## Install

```bash
pip install underdog-api
export UNDERDOG_API_KEY=ud_...   # free key, no card: https://underdogapi.com/sign-up
```

## Try it without a key

```python
from underdog_api import Client

demo = Client(api_key=None).demo("projections", league="NBA", limit=1)
print(demo["data"][0]["player"]["name"], demo["data"][0]["selections"])   # fictional rows, live shape
```

## The current board

```python
from underdog_api import Client

ud = Client()  # reads UNDERDOG_API_KEY
board = ud.projections(league="NBA", view="compact", limit=20)
for line in board["data"]:
    print(line)
print(board["meta"]["observed_at"])
```

## Everything that moved

```python
for change in ud.pages("/api/v1/changes", league="NFL", event_type="line.moved", limit=200):
    print(change["observed_at"], change["player_name"], change["stat"], change["previous_line"], "->", change["line"])
```

## The board at a past moment, and graded results (paid plans)

```python
past = ud.board(as_of="2026-11-14T23:00:00Z", league="NHL", limit=100)
graded = ud.results(league="NBA", date="2026-11-13", limit=200)
```

On the free key, graded results, hit rates, game logs, exports and the training set raise `PlanLimitError` with a
few labelled sample rows and the upgrade link; no credits are charged:

```python
from underdog_api import PlanLimitError

try:
    ud.results(league="NBA")
except PlanLimitError as e:
    print(e.message, e.upgrade_url, e.sample[:2])
```

## Into pandas

```python
import pandas as pd
rows = list(ud.pages("/api/v1/projections", league="NBA", view="compact", limit=200))
df = pd.json_normalize(rows)
```

## Notes

- Every method returns the parsed JSON body (`data` and `meta`). `ud.get(path, **params)` reaches any documented path.
- Per-minute 429s and 5xx answers are retried with backoff; the monthly credit 429 is raised at once.
- Credits: one per started 100 rows on simple reads; `ud.credit_costs()` returns the policy with no key.
- Reference: https://underdogapi.com/docs · Plans: https://underdogapi.com/pricing

## Tests

```bash
python -m unittest discover -s tests          # offline, fake transport
UNDERDOG_LIVE=1 python -m unittest discover -s tests   # also calls the keyless demo
```
