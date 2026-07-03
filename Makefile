.PHONY: setup test cli dashboard snapshot

setup:
	python3 -m venv .venv
	. .venv/bin/activate && python -m pip install -e ".[dev]"

test:
	. .venv/bin/activate && python -m pytest -q

cli:
	. .venv/bin/activate && polymarket-btc-bot --help

snapshot:
	. .venv/bin/activate && polymarket-btc-bot snapshot

dashboard:
	. .venv/bin/activate && polymarket-btc-bot dashboard

