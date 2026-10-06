.PHONY: install init dev test check
install:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements.txt
init:
	.venv/bin/flask --app mortezkana init-db
dev:
	.venv/bin/flask --app mortezkana run
test:
	.venv/bin/python -m unittest discover -s tests -v
check: test
	.venv/bin/python -m compileall -q mortezkana tests
