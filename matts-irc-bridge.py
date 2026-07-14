#!/usr/bin/env python3
"""Entry point for the Matts IRC LLM bridge."""
from backend.v2.services.irc_bridge import main


if __name__ == "__main__":
    raise SystemExit(main())
