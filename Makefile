.PHONY: test test-pytest test-verbose lint check install clean

test:
	python3 -m unittest discover tests -q

test-pytest:
	pytest -q

test-verbose:
	python3 -m unittest discover tests -v

lint:
	python3 -c "import py_compile, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('laserforge/**/*.py', recursive=True) + glob.glob('laserforge/*.py')]; print('Syntax & Bytecode Validation: PASSED')"

install:
	pip install -r requirements.txt

check: lint test

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
