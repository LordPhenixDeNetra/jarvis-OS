.PHONY: boot run voice

invoque:
	@bash setup.sh

run:
	@uv run python main.py

voice:
	@uv run python voice_agent.py dev
