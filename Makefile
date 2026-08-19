PREFIX ?= $(HOME)/.local

.PHONY: install uninstall test

install:
	./install.sh

uninstall:
	rm -rf "$(PREFIX)/lib/despierte"
	rm -f "$(PREFIX)/bin/despierte"

test:
	python3 -m unittest discover -s tests
