.PHONY: install test demo compare serve clean

install:
	pip install -e ".[dev]"

test:
	pytest -q

# Run both demo agents and compare them
demo:
	agent-harness run --agent mock:v1 --out runs
	agent-harness run --agent mock:v2 --out runs
	@echo "Now: agent-harness compare <v1.json> <v2.json>"

serve:
	agent-harness serve --port 8000

clean:
	rm -rf build dist *.egg-info .pytest_cache runs/*.json runs/*.md runs/*.html
